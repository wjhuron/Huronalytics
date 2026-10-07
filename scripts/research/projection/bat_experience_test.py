"""bat_experience_test.py: the batting projection on EVERY hitter, and the prior it regresses toward.

Why (2026-10-03): hpWAR projected Pinckney (29 MLB PA) at a league-average .318 wOBA and 2.6 WAR per
600 PA. The v1 projection regresses to the MLB league mean, and its backtest scored only hitters with
>= 200 PA in the target season, so it never saw the thin-history players it over-rates.

Pool here: every non-pitcher with >= 1 PA in the target season T (2018-2026) and >= 1 MLB PA in
T-3..T-1; objective PA_T-weighted MSE of the wOBA delta, leave one target season out. Arms, all on the
v1 level and aging settings (a .75, d .7, ys .002, os .0045, peak 30), differing only in the PRIOR the
history is shrunk toward (and N0, re-swept for each):
  league     mu = 0 (v1 as shipped)
  exper      mu(E) = c / (1 + E / k), E = raw MLB PA in the history: thin history pulls toward a
             below-average level, a long one toward league. c, k swept.
  exper+aaa  as exper, but a hitter with a Triple-A season in T-1 or T-2 takes the box-bridge
             prediction (aaa_hitter_bridge.py, refit leaving out every pair whose MLB season is T) as
             his prior, mixed with mu(E) at weight w_a (swept; 1 = bridge only).
Reported: held-out MSE per season, the calibration table (PA-weighted mean of actual minus projected,
by history-PA bin), and the regulars-only score (target >= 200 PA) so a gain on the thin end cannot
hide a loss on the regulars.

Usage: python3 scripts/research/projection/bat_experience_test.py
Output: console + data/_proj/_bat_experience_test.json
"""
import itertools
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aaa_hitter_bridge as hb
import bat_rate_backtest as v1

TARGETS = list(range(2018, 2027))
A, D, YS, OS, PEAK = 0.75, 0.7, 0.002, 0.0045, 30
BINS = [(1, 50), (50, 150), (150, 300), (300, 600), (600, 1200), (1200, 10 ** 6)]
GRID_N0 = [200, 300, 450, 700]
GRID_C = [0.0, -0.01, -0.02, -0.03, -0.04, -0.05, -0.06]
GRID_K = [50, 100, 200, 400, 800]
GRID_WA = [0.0, 0.25, 0.5, 0.75, 1.0]


def build():
    X = {y: v1.load_xstats(y) for y in range(2015, 2027)}
    LG = {y: v1.league(X[y]) for y in X}
    AG = {y: v1.load_ages(y) for y in range(2015, 2027)}
    Aaa, Mlb = hb.season_tables()
    D_ = {}
    for T in TARGETS:
        rows = []
        for pid, (pa_t, w_t, _) in X[T].items():
            ag = AG[T].get(pid)
            if ag is None or ag[1] == 'P':
                continue
            hist = []
            for k in range(3):
                v = X[T - 1 - k].get(pid)
                hist.append((v[0], v[1] - LG[T - 1 - k][0], v[2] - LG[T - 1 - k][1]) if v else (0, 0.0, 0.0))
            E = sum(h[0] for h in hist)
            if E == 0:
                continue
            aaa = None
            for y in (T - 1, T - 2):
                if y in Aaa and pid in Aaa[y][0]:
                    aaa = (y, Aaa[y][0][pid], Mlb[y][0].get(pid))
                    break
            rows.append({'id': pid, 'age': ag[0], 'pa': pa_t, 'y': w_t - LG[T][0], 'hist': hist, 'E': E, 'aaa': aaa})
        D_[T] = rows
    return D_, Aaa, Mlb


def bridge_beta(Aaa, Mlb, leave_T):
    """box bridge refit on every AAA-Y -> MLB-Y+1 pair whose MLB season is not leave_T (N0 1000)."""
    X, yv, wv = [], [], []
    for y in hb.YEARS:
        if y + 1 == leave_T:
            continue
        for pid, a in Aaa[y][0].items():
            m1 = Mlb[y + 1][0].get(pid)
            if a['pa'] < 200 or a['age'] is None or not m1 or m1['pa'] < 100:
                continue
            X.append(hb.features(a, Mlb[y][0].get(pid), 1000)); yv.append(m1['d_woba']); wv.append(m1['pa'])
    return hb.wols(np.array(X), np.array(yv), np.array(wv, float))


def arrays(rows, beta):
    n = len(rows)
    num = np.zeros(n); den = np.zeros(n); agew = np.zeros(n)
    for i, r in enumerate(rows):
        for k, (pa, w, x) in enumerate(r['hist']):
            wt = D ** k * pa
            num[i] += wt * (A * x + (1 - A) * w); den[i] += wt; agew[i] += wt * (r['age'] - 1 - k)
    age = np.array([r['age'] for r in rows], float)
    a0 = agew / den
    lo = np.minimum(age, PEAK) - np.minimum(a0, PEAK); hi = np.maximum(age, PEAK) - np.maximum(a0, PEAK)
    aging = YS * lo - OS * hi
    E = np.array([r['E'] for r in rows], float)
    has_a = np.array([r['aaa'] is not None for r in rows])
    mu_a = np.zeros(n)
    for i, r in enumerate(rows):
        if r['aaa']:
            y, a, m = r['aaa']
            if a['age'] is not None:
                mu_a[i] = float(np.array([1.0] + hb.features(a, m, 1000)) @ beta)
            else:
                has_a[i] = False
    return {'num': num, 'den': den, 'aging': aging, 'E': E, 'has_a': has_a, 'mu_a': mu_a,
            'y': np.array([r['y'] for r in rows]), 'w': np.array([r['pa'] for r in rows], float)}


def project(Z, n0, c, k, wa):
    mu = c / (1 + Z['E'] / k)
    mu = np.where(Z['has_a'], wa * Z['mu_a'] + (1 - wa) * mu, mu)
    return (Z['num'] + n0 * mu) / (Z['den'] + n0) + Z['aging']


def wmse(p, Z, mask=None):
    m = np.ones(len(p), bool) if mask is None else mask
    return float((Z['w'][m] * (p[m] - Z['y'][m]) ** 2).sum() / Z['w'][m].sum())


def calib(p, Z):
    out = []
    for lo, hi in BINS:
        m = (Z['E'] >= lo) & (Z['E'] < hi)
        out.append((f'{lo}-{hi if hi < 10**6 else "+"}', int(m.sum()), float((Z['w'][m] * (Z['y'][m] - p[m])).sum() / Z['w'][m].sum()) if m.any() else None))
    return out


def main():
    Dr, Aaa, Mlb = build()
    Z = {T: arrays(Dr[T], bridge_beta(Aaa, Mlb, T)) for T in TARGETS}
    print('pool per season:', {T: len(Dr[T]) for T in TARGETS},
          '| with an AAA season in T-1/T-2:', {T: int(Z[T]['has_a'].sum()) for T in TARGETS})
    arms = {'league': [(n0, 0.0, 100, 0.0) for n0 in GRID_N0],
            'exper': [(n0, c, k, 0.0) for n0, c, k in itertools.product(GRID_N0, GRID_C, GRID_K)],
            'exper+aaa': [(n0, c, k, wa) for n0, c, k, wa in itertools.product(GRID_N0, GRID_C, GRID_K, GRID_WA)]}
    res = {}
    for arm, combos in arms.items():
        L = np.array([[wmse(project(Z[T], *c), Z[T]) for T in TARGETS] for c in combos])
        held, pooled_p = [], {}
        for j, T in enumerate(TARGETS):
            o = [i for i in range(len(TARGETS)) if i != j]
            b = int(np.argmin(L[:, o].mean(axis=1)))
            p = project(Z[T], *combos[b])
            held.append({'T': T, 'mse': float(L[b, j]), 'chosen': combos[b],
                         'reg': wmse(p, Z[T], Z[T]['w'] >= 200)})
            pooled_p[T] = p
        best = int(np.argmin(L.mean(axis=1)))
        cal = {}
        allp = np.concatenate([pooled_p[T] for T in TARGETS])
        Zall = {k2: np.concatenate([Z[T][k2] for T in TARGETS]) for k2 in ('y', 'w', 'E')}
        cal = calib(allp, Zall)
        res[arm] = {'held': held, 'pooled': combos[best], 'calib': cal,
                    'mean_mse': float(np.mean([h['mse'] for h in held])), 'mean_reg': float(np.mean([h['reg'] for h in held]))}
        print(f'\n== {arm}: held-out mean MSE x1e4 {res[arm]["mean_mse"]*1e4:.3f}   regulars-only {res[arm]["mean_reg"]*1e4:.3f}   pooled (n0, c, k, wa) {combos[best]}')
        print('   calibration, actual - projected by history PA (wOBA points x1000): ' +
              '  '.join(f'{b}: {v*1000:+.1f} (n {n})' for b, n, v in cal))
        if arm != 'league':
            for nm, idx, grid in (('n0', 0, GRID_N0), ('c', 1, GRID_C), ('k', 2, GRID_K)) + ((('wa', 3, GRID_WA),) if arm == 'exper+aaa' else ()):
                pts = []
                for v in grid:
                    cc = list(combos[best]); cc[idx] = v
                    pts.append(f'{v}:{L[combos.index(tuple(cc))].mean()*1e4:.3f}')
                print(f'     {nm:>3}: ' + '  '.join(pts))
    for arm in ('exper', 'exper+aaa'):
        w = sum(h['mse'] < l['mse'] for h, l in zip(res[arm]['held'], res['league']['held']))
        wr = sum(h['reg'] <= l['reg'] + 1e-12 for h, l in zip(res[arm]['held'], res['league']['held']))
        print(f'{arm} beats league prior in {w}/{len(TARGETS)} held-out seasons; regulars no worse in {wr}/{len(TARGETS)}')
    tmp = os.path.join(v1.P, '_bat_experience_test.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(res, f, indent=1, default=float)
    os.replace(tmp, os.path.join(v1.P, '_bat_experience_test.json'))


if __name__ == '__main__':
    main()
