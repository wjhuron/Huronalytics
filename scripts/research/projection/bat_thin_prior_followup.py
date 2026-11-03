"""bat_thin_prior_followup.py: each position alone, position x age, a forward-only test, and the 2027 effect (2026-11-03).

Follows bat_thin_prior_test.py, whose first pass put the age pivot of the catcher x age arm at the low edge of its grid.
Forward test: fit on seasons before T only, T 2021-2026, so no later season informs the term.
Age cap: the Cxage slope with age clipped at a0 + cap, swept, then the shipped form (a0 24, cap 5) with kt chosen on the other seasons.

Usage: python3 scripts/research/projection/bat_thin_prior_followup.py
Output: console + data/_proj/_bat_thin_prior_followup.json
"""
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bat_rate_backtest as v1
import bat_thin_prior_test as t

t.GRID_A0 = [18, 20, 22, 24, 26, 28, 30]
ARMS = ('C', 'MI', 'CF', 'corner', 'Cxage', 'MIxage', 'CFxage', 'cornerxage', 'Cxage+MI+CF', 'allxage')


def curve(Z, arm):
    """In-sample season-weighted MSE over kt and a0, with coefficients refit at each cell."""
    b0 = np.mean([t.wmse(t.base(Z[T]), Z[T]) for T in t.TARGETS])
    print(f'\n  {arm} surface, MSE x1e4 minus base, a0 (rows) by kt (columns)')
    print('        ' + ''.join(f'{k:>9.0f}' for k in t.GRID_KT))
    out = {}
    for a0 in t.GRID_A0:
        row = []
        for kt in t.GRID_KT:
            g = t.fit(Z, t.TARGETS, arm, kt, a0)
            row.append(float(np.mean([t.wmse(t.base(Z[T]) + t.term(Z[T], arm, kt, a0) @ g, Z[T]) for T in t.TARGETS]) - b0))
        out[a0] = row
        print(f'    {a0:>3d} ' + ''.join(f'{v*1e4:+9.4f}' for v in row))
    return out


def forward(Z, arm):
    d = {}
    for T in [x for x in t.TARGETS if x >= 2021]:
        tr = [x for x in t.TARGETS if x < T]
        grid = [(kt, a0) for kt in t.GRID_KT for a0 in (t.GRID_A0 if 'age' in arm else [26])]
        best = None
        for kt, a0 in grid:
            g = t.fit(Z, tr, arm, kt, a0)
            s = np.mean([t.wmse(t.base(Z[x]) + t.term(Z[x], arm, kt, a0) @ g, Z[x]) for x in tr])
            if best is None or s < best[0]:
                best = (s, kt, a0, g)
        _, kt, a0, g = best
        d[T] = t.wmse(t.base(Z[T]) + t.term(Z[T], arm, kt, a0) @ g, Z[T]) - t.wmse(t.base(Z[T]), Z[T])
    print(f'  forward {arm:12s} mean {np.mean(list(d.values()))*1e4:+.4f}  wins {sum(v < 0 for v in d.values())}/{len(d)}  ' + ' '.join(f'{k}:{v*1e4:+.3f}' for k, v in d.items()))
    return d


def placebo_cxage(Z, real, kt, a0, n=500):
    rng = np.random.default_rng(3)
    bins = [0, 50, 150, 300, 600, 1200, 10 ** 7]
    out = []
    for _ in range(n):
        Y = {}
        for T in t.TARGETS:
            z = dict(Z[T]); eb = np.digitize(z['E'], bins); ix = np.arange(len(eb))
            for b in np.unique(eb):
                i = np.where(eb == b)[0]; ix[i] = rng.permutation(i)
            z['isC'] = Z[T]['isC'][ix]
            Y[T] = z
        d = []
        for T in t.TARGETS:
            g = t.fit(Y, [x for x in t.TARGETS if x != T], 'Cxage', kt, a0)
            d.append(t.wmse(t.base(Y[T]) + t.term(Y[T], 'Cxage', kt, a0) @ g, Y[T]) - t.wmse(t.base(Y[T]), Y[T]))
        out.append(np.mean(d))
    out = np.array(out)
    print(f'  placebo Cxage kt {kt} a0 {a0}: mean {out.mean()*1e4:+.4f}, sd {out.std()*1e4:.4f}, real {real*1e4:+.4f}, real beats {(out > real).mean()*100:.1f}% of {n}')
    return dict(mean=float(out.mean()), sd=float(out.std()), beats=float((out > real).mean()))


def effect_2027(Z, arm, kt, a0):
    """The 2027 one-year shift for catchers, from the fit on every season, on the shipped CSV's rate. Reads, writes nothing shipped."""
    g = t.fit(Z, t.TARGETS, arm, kt, a0)
    print(f'\n  2027 effect, {arm}, kt {kt} a0 {a0}, g {np.round(g, 4).tolist()}')
    P = v1.P
    X = {y: v1.load_xstats(y) for y in range(2023, 2027)}
    rows = list(csv.DictReader(open(os.path.join(P, 'projections_hitters.csv'))))
    hc = json.load(open(os.path.join(os.path.dirname(P), 'hwar_constants.json'))) if os.path.exists(os.path.join(os.path.dirname(P), 'hwar_constants.json')) else None
    out = []
    for r in rows:
        if r['pos'] != 'C' or not r.get('WAR600_2027'):
            continue
        pid = int(r['mlbId']); age = float(r['age_2027'])
        den = sum(0.7 ** k * X[2026 - k][pid][0] for k in range(4) if pid in X[2026 - k])
        E = sum(X[2026 - k][pid][0] for k in range(3) if pid in X[2026 - k])
        ag = max(age - a0, 0.0)
        sh = (g[0] + g[1] * ag) * 450 / (den + 450) / (1 + E / kt)
        lg = float(r['wOBA_2027']) - float(r['bat600_2027']) * 0 if False else None
        out.append(dict(id=pid, name=r['name'], age=age, E=E, wOBA=float(r['wOBA_2027']), full=float(r['WAR600_2027']), bat=float(r['bat600_2027']), d=sh))
    # runs per wOBA point and runs per win, read from the shipped row's own arithmetic (Hunt: 16.6 runs, 1.71 WAR)
    return out, g


def capped(z, kt, a0, cap):
    ag = np.minimum(np.maximum(z['age'] - a0, 0), cap)
    return np.column_stack([z['isC'] * z['shr'] / (1 + z['E'] / kt), z['isC'] * ag * z['shr'] / (1 + z['E'] / kt)])


def fit_capped(Z, Ts, kt, a0, cap):
    A, b = [], []
    for T in Ts:
        z = Z[T]; s = np.sqrt(z['w'] / z['w'].sum())
        A.append(capped(z, kt, a0, cap) * s[:, None]); b.append((z['y'] - t.base(z)) * s)
    return np.linalg.lstsq(np.vstack(A), np.concatenate(b), rcond=None)[0]


def cap_test(Z):
    b0 = np.mean([t.wmse(t.base(Z[T]), Z[T]) for T in t.TARGETS])
    print('\n  age cap curve, best kt and a0 at each cap, MSE x1e4 minus base (in sample)')
    curve_ = {}
    for cap in (2, 3, 4, 5, 6, 7, 8, 10, 12, 99):
        cells = []
        for kt in (100, 200, 400, 800, 1600):
            for a0 in (22, 24, 26):
                g = fit_capped(Z, t.TARGETS, kt, a0, cap)
                cells.append((float(np.mean([t.wmse(t.base(Z[T]) + capped(Z[T], kt, a0, cap) @ g, Z[T]) for T in t.TARGETS]) - b0), kt, a0))
        curve_[cap] = min(cells)
        print(f'    cap {cap:>3d}: {curve_[cap][0]*1e4:+.4f}  kt {curve_[cap][1]} a0 {curve_[cap][2]}')
    KTS = (100, 200, 400, 800, 1600, 3200)
    d = {}
    for T in t.TARGETS:
        tr = [x for x in t.TARGETS if x != T]
        kt = min(KTS, key=lambda v: np.mean([t.wmse(t.base(Z[x]) + capped(Z[x], v, 24, 5) @ fit_capped(Z, tr, v, 24, 5), Z[x]) for x in tr]))
        d[T] = t.wmse(t.base(Z[T]) + capped(Z[T], kt, 24, 5) @ fit_capped(Z, tr, kt, 24, 5), Z[T]) - t.wmse(t.base(Z[T]), Z[T])
    print(f'  shipped form, a0 24 cap 5, held out: {np.mean(list(d.values()))*1e4:+.4f}  wins {sum(v < 0 for v in d.values())}/9')
    g = fit_capped(Z, t.TARGETS, 800, 24, 5)
    print(f'  all seasons, kt 800: g {np.round(g, 4).tolist()}')
    return dict(curve=curve_, held=d, g=[float(v) for v in g])


def main():
    Z = t.build()
    P0 = {T: t.base(Z[T]) for T in t.TARGETS}
    res = {}
    for arm in ARMS:
        pred, ch = t.loso(Z, arm)
        res[arm] = t.report(arm, pred, ch, Z, P0)
        res[arm]['calib'] = t.calib(pred, Z, arm) if arm in ('C', 'Cxage', 'Cxage+MI+CF') else None
    res['surface_Cxage'] = {str(k): v for k, v in curve(Z, 'Cxage').items()}
    print()
    res['forward'] = {arm: forward(Z, arm) for arm in ('C', 'Cxage', 'MI', 'CF', 'corner', 'Cxage+MI+CF')}
    ch = list(res['Cxage']['chosen'].values())
    kt = float(np.median([c['kt'] for c in ch])); a0 = int(np.median([c['a0'] for c in ch]))
    res['placebo_Cxage'] = placebo_cxage(Z, res['Cxage']['dmse'], kt, a0)
    out, g = effect_2027(Z, 'Cxage', kt, a0)
    res['effect'] = dict(kt=kt, a0=a0, g=[float(v) for v in g], rows=out)
    res['cap'] = cap_test(Z)
    tmp = os.path.join(v1.P, '_bat_thin_prior_followup.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(res, f, indent=1, default=float)
    os.replace(tmp, os.path.join(v1.P, '_bat_thin_prior_followup.json'))


if __name__ == '__main__':
    main()
