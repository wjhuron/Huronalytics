"""bat_thin_prior_test.py: does the batting prior over-project thin-history hitters, by position, age or a small Triple-A sample?

Why (2026-11-03): Blake Hunt (3 MLB PA, 156 Triple-A PA) projected .305 wOBA and 1.71 WAR per 600 PA, and a held-out
cut showed catchers with thin history running below their projections. That cut was post hoc, so this tests it properly.

Pool and objective are bat_experience_test.py's: every non-pitcher with >= 1 PA in T (2018-2026) and >= 1 MLB PA in
T-3..T-1, PA_T-weighted MSE of the wOBA delta, leave one target season out. A term is fit and its shape chosen only on
the other eight seasons. Base arm: the shipped prior (n0 450, c -.04, k 200, wa .75).

Candidates add to the prior, so history still shrinks them away:
    mu' = mu + (g @ x) / (1 + E / kt)
  allpos   x = [1]                      every position, the same thin-history shift
  C        x = [catcher]
  pos4     x = [C, 2B/SS, CF, corner]   position from the history seasons, never the target season
  age      x = [max(age - a0, 0)]       a0 swept
  C+age, pos4+age
  Cxage    x = [C, C * max(age - a0, 0)]
  posL+thin  a level by position at every history length (kt = inf) plus a thin-history term on C, 2B/SS and CF
  aaaPA    wa' = wa * pa / (pa + m)     a small Triple-A season gets less bridge weight (the bridge is fit on >= 200 PA), m swept
Reported: held-out MSE, season wins, paired bootstrap, the thin and regular slices, calibration by group, the catcher
surface (c x kt), and a placebo that shuffles the catcher label within season and history bin.

Usage: python3 scripts/research/projection/bat_thin_prior_test.py
Output: console + data/_proj/_bat_thin_prior_test.json
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bat_experience_test as bx
import bat_rate_backtest as v1

TARGETS = bx.TARGETS
N0, C0, K0, WA0 = 450, -0.04, 200, 0.75
GRID_KT = [25, 50, 100, 200, 400, 800, 1600, 3200, 6400, float('inf')]
GRID_C = [0.0, -0.005, -0.01, -0.015, -0.02, -0.03, -0.04, -0.05, -0.06, -0.08]
GRID_A0 = [24, 26, 28, 30]
GRID_M = [0, 50, 100, 200, 400, 800, 1600]
N_BOOT = 2000
N_PLACEBO = 500
MI = {'2B', 'SS'}


def history_pos(AG, pid, T):
    for y in (T - 1, T - 2, T - 3):
        ag = AG.get(y, {}).get(pid)
        if ag is not None and ag[1] and ag[1] != 'P':
            return ag[1]
    return None


def build():
    Dr, Aaa, Mlb = bx.build()
    AG = {y: v1.load_ages(y) for y in range(2015, 2027)}
    Z = {}
    for T in TARGETS:
        z = bx.arrays(Dr[T], bx.bridge_beta(Aaa, Mlb, T))
        z['age'] = np.array([r['age'] for r in Dr[T]], float)
        pos = [history_pos(AG, r['id'], T) for r in Dr[T]]
        if pos.count(None):
            print(f'  T {T}: {pos.count(None)} rows with no history position, counted as corner')
        z['isC'] = np.array([p == 'C' for p in pos], float)
        z['isMI'] = np.array([p in MI for p in pos], float)
        z['isCF'] = np.array([p == 'CF' for p in pos], float)
        z['isCorner'] = 1.0 - z['isC'] - z['isMI'] - z['isCF']
        z['aaa_pa'] = np.array([r['aaa'][1]['pa'] if r['aaa'] else 0 for r in Dr[T]], float)
        z['shr'] = N0 / (z['den'] + N0)
        z['id'] = np.array([r['id'] for r in Dr[T]])
        Z[T] = z
    return Z


def base(z, m=0.0):
    wa = WA0 * (z['aaa_pa'] / (z['aaa_pa'] + m) if m else np.ones(len(z['y'])))
    mu = C0 / (1 + z['E'] / K0)
    mu = np.where(z['has_a'], wa * z['mu_a'] + (1 - wa) * mu, mu)
    return (z['num'] + N0 * mu) / (z['den'] + N0) + z['aging']


def x_of(z, arm, a0=26):
    ag = np.maximum(z['age'] - a0, 0.0)
    return {'allpos': [np.ones(len(z['y']))], 'C': [z['isC']], 'pos4': [z['isC'], z['isMI'], z['isCF'], z['isCorner']],
            'age': [ag], 'C+age': [z['isC'], ag], 'pos4+age': [z['isC'], z['isMI'], z['isCF'], z['isCorner'], ag],
            'Cxage': [z['isC'], z['isC'] * ag], 'MI': [z['isMI']], 'CF': [z['isCF']], 'corner': [z['isCorner']],
            'MIxage': [z['isMI'], z['isMI'] * ag], 'CFxage': [z['isCF'], z['isCF'] * ag], 'cornerxage': [z['isCorner'], z['isCorner'] * ag],
            'Cxage+MI+CF': [z['isC'], z['isC'] * ag, z['isMI'] + z['isCF']],
            'allxage': [z['isC'], z['isC'] * ag, z['isMI'], z['isMI'] * ag, z['isCF'], z['isCF'] * ag, z['isCorner'], z['isCorner'] * ag]}[arm]


def term(z, arm, kt, a0):
    if arm == 'posL+thin':
        lvl = [v * z['shr'] for v in x_of(z, 'pos4', a0)]
        thin = [v * z['shr'] / (1 + z['E'] / kt) for v in x_of(z, 'pos4', a0)[:3]]
        return np.column_stack(lvl + thin)
    return np.column_stack([v * z['shr'] / (1 + z['E'] / kt) for v in x_of(z, arm, a0)])


def wmse(p, z, mask=None):
    m = np.ones(len(p), bool) if mask is None else mask
    return float((z['w'][m] * (p[m] - z['y'][m]) ** 2).sum() / z['w'][m].sum())


def fit(Z, Ts, arm, kt, a0, key=None):
    """Season-weighted WLS of the base residual on the term: each season counts once, as the objective does."""
    A, b = [], []
    for T in Ts:
        z = Z[T]; s = np.sqrt(z['w'] / z['w'].sum())
        X = term(z, arm, kt, a0) if key is None else (z[key] * z['shr'] / (1 + z['E'] / kt))[:, None]
        A.append(X * s[:, None]); b.append((z['y'] - base(z)) * s)
    return np.linalg.lstsq(np.vstack(A), np.concatenate(b), rcond=None)[0]


def loso(Z, arm):
    kts = [k for k in GRID_KT if k != float('inf')] if arm == 'posL+thin' else GRID_KT
    grid = [(kt, a0) for kt in kts for a0 in (GRID_A0 if 'age' in arm else [26])]
    pred, chosen = {}, {}
    for T in TARGETS:
        tr = [t for t in TARGETS if t != T]
        best = None
        for kt, a0 in grid:
            g = fit(Z, tr, arm, kt, a0)
            s = np.mean([wmse(base(Z[t]) + term(Z[t], arm, kt, a0) @ g, Z[t]) for t in tr])
            if best is None or s < best[0]:
                best = (s, kt, a0, g)
        _, kt, a0, g = best
        pred[T] = base(Z[T]) + term(Z[T], arm, kt, a0) @ g
        chosen[T] = dict(kt=kt, a0=a0, g=[round(float(v), 4) for v in g])
    return pred, chosen


def loso_m(Z):
    pred, chosen = {}, {}
    for T in TARGETS:
        tr = [t for t in TARGETS if t != T]
        m = min(GRID_M, key=lambda v: np.mean([wmse(base(Z[t], v), Z[t]) for t in tr]))
        pred[T] = base(Z[T], m); chosen[T] = dict(m=m)
    return pred, chosen


def report(name, pred, chosen, Z, P0):
    rng = np.random.default_rng(0)
    d = [wmse(pred[T], Z[T]) - wmse(P0[T], Z[T]) for T in TARGETS]
    boots = []
    for _ in range(N_BOOT):
        b = []
        for T in TARGETS:
            z = Z[T]; ix = rng.integers(0, len(z['y']), len(z['y']))
            w = z['w'][ix]; y = z['y'][ix]
            b.append(((w * (pred[T][ix] - y) ** 2).sum() - (w * (P0[T][ix] - y) ** 2).sum()) / w.sum())
        boots.append(np.mean(b))
    sl = {}
    for lab, f in (('thin E<=50', lambda z: z['E'] <= 50), ('E 50-300', lambda z: (z['E'] > 50) & (z['E'] <= 300)), ('reg PA_T>=200', lambda z: z['w'] >= 200)):
        vals = []
        for T in TARGETS:
            z = Z[T]; m = f(z)
            vals.append(wmse(pred[T], z, m) - wmse(P0[T], z, m))
        sl[lab] = (float(np.mean(vals)) * 1e4, int(sum(v < 0 for v in vals)))
    wins = int(sum(v < 0 for v in d))
    print(f'{name:10s} dMSE x1e4 {np.mean(d)*1e4:+.4f} (se {np.std(boots)*1e4:.4f})  wins {wins}/{len(TARGETS)}  per T ' + ' '.join(f'{v*1e4:+.3f}' for v in d))
    print(f'           ' + '   '.join(f'{k}: {v[0]:+.3f} ({v[1]}/9)' for k, v in sl.items()))
    last = list(chosen.values())
    print(f'           chosen per T: ' + ' '.join(json.dumps(c, separators=(",", ":")) for c in last[:3]) + ' ...')
    return dict(dmse=float(np.mean(d)), se=float(np.std(boots)), wins=wins, per_T=d, slices=sl, chosen=chosen)


def calib(pred, Z, label):
    print(f'\n  calibration, actual - projected, x1000, {label}')
    allz = {k: np.concatenate([Z[T][k] for T in TARGETS]) for k in ('y', 'w', 'E', 'isC', 'isMI', 'isCF', 'isCorner', 'age')}
    p = np.concatenate([pred[T] for T in TARGETS])
    out = {}
    for lab, m in (('E<=50 C', (allz['E'] <= 50) & (allz['isC'] == 1)), ('E<=50 MI', (allz['E'] <= 50) & (allz['isMI'] == 1)), ('E<=50 CF', (allz['E'] <= 50) & (allz['isCF'] == 1)),
                   ('E<=50 corner', (allz['E'] <= 50) & (allz['isCorner'] == 1)), ('E<=50 age>=27', (allz['E'] <= 50) & (allz['age'] >= 27)), ('E<=50 age<27', (allz['E'] <= 50) & (allz['age'] < 27)),
                   ('E 50-300 C', (allz['E'] > 50) & (allz['E'] <= 300) & (allz['isC'] == 1)), ('E 50-300 other', (allz['E'] > 50) & (allz['E'] <= 300) & (allz['isC'] == 0)),
                   ('E>300 C', (allz['E'] > 300) & (allz['isC'] == 1)), ('E>300 other', (allz['E'] > 300) & (allz['isC'] == 0))):
        v = float((allz['w'][m] * (allz['y'][m] - p[m])).sum() / allz['w'][m].sum())
        out[lab] = v
        print(f'    {lab:16s} n {int(m.sum()):5d} PA {allz["w"][m].sum():8.0f}  {v*1000:+.1f}')
    return out


def surface(Z):
    print('\n  catcher surface, pooled MSE x1e4 minus base, c (rows) by kt (columns)')
    b0 = np.mean([wmse(base(Z[T]), Z[T]) for T in TARGETS])
    print('          ' + ''.join(f'{k:>9.0f}' for k in GRID_KT))
    S = {}
    for c in GRID_C:
        row = []
        for kt in GRID_KT:
            row.append(float(np.mean([wmse(base(Z[T]) + c * Z[T]['isC'] * Z[T]['shr'] / (1 + Z[T]['E'] / kt), Z[T]) for T in TARGETS]) - b0))
        S[c] = row
        print(f'    {c:+.3f}' + ''.join(f'{v*1e4:+9.4f}' for v in row))
    return S


def placebo(Z, real, kt):
    """Shuffle the catcher label within season and history bin. Same kt as the real arm's median choice."""
    rng = np.random.default_rng(1)
    out = []
    bins = [0, 50, 150, 300, 600, 1200, 10 ** 7]
    for _ in range(N_PLACEBO):
        Y = {}
        for T in TARGETS:
            z = Z[T]; lab = z['isC'].copy(); eb = np.digitize(z['E'], bins)
            for b in np.unique(eb):
                ix = np.where(eb == b)[0]; lab[ix] = rng.permutation(lab[ix])
            Y[T] = dict(z, fake=lab)
        d = []
        for T in TARGETS:
            g = fit(Y, [t for t in TARGETS if t != T], 'C', kt, 26, key='fake')[0]
            z = Y[T]
            d.append(wmse(base(z) + g * z['fake'] * z['shr'] / (1 + z['E'] / kt), z) - wmse(base(z), z))
        out.append(np.mean(d))
    out = np.array(out)
    print(f'\n  placebo, shuffled catcher label, kt {kt}: mean {out.mean()*1e4:+.4f}, sd {out.std()*1e4:.4f}, real {real*1e4:+.4f}, real beats {(out > real).mean()*100:.1f}% of {N_PLACEBO}')
    return dict(mean=float(out.mean()), sd=float(out.std()), beats=float((out > real).mean()))


def placebo_pos4(Z, real, kt):
    """Shuffle whole position labels within season and history bin, and refit all four coefficients."""
    rng = np.random.default_rng(2)
    bins = [0, 50, 150, 300, 600, 1200, 10 ** 7]
    out = []
    for _ in range(N_PLACEBO):
        Y = {}
        for T in TARGETS:
            z = dict(Z[T]); eb = np.digitize(z['E'], bins); ix = np.arange(len(eb))
            for b in np.unique(eb):
                i = np.where(eb == b)[0]; ix[i] = rng.permutation(i)
            for k in ('isC', 'isMI', 'isCF', 'isCorner'):
                z[k] = Z[T][k][ix]
            Y[T] = z
        d = []
        for T in TARGETS:
            g = fit(Y, [t for t in TARGETS if t != T], 'pos4', kt, 26)
            d.append(wmse(base(Y[T]) + term(Y[T], 'pos4', kt, 26) @ g, Y[T]) - wmse(base(Y[T]), Y[T]))
        out.append(np.mean(d))
    out = np.array(out)
    print(f'  placebo, shuffled position labels, kt {kt}: mean {out.mean()*1e4:+.4f}, sd {out.std()*1e4:.4f}, real {real*1e4:+.4f}, real beats {(out > real).mean()*100:.1f}% of {N_PLACEBO}')
    return dict(mean=float(out.mean()), sd=float(out.std()), beats=float((out > real).mean()))


def main():
    Z = build()
    P0 = {T: base(Z[T]) for T in TARGETS}
    ms = np.mean([wmse(P0[T], Z[T]) for T in TARGETS])
    print(f'base arm mean MSE x1e4 {ms*1e4:.3f} (shipped arm in _bat_experience_test.json reads 13.74 with per-season tuning)')
    res = {'base_mse': float(ms)}
    calib(P0, Z, 'SHIPPED')
    for arm in ('allpos', 'C', 'pos4', 'age', 'C+age', 'pos4+age', 'Cxage', 'posL+thin'):
        pred, ch = loso(Z, arm)
        res[arm] = report(arm, pred, ch, Z, P0)
        res[arm]['calib'] = calib(pred, Z, arm)
    pred, ch = loso_m(Z)
    res['aaaPA'] = report('aaaPA', pred, ch, Z, P0)
    print('  aaaPA curve, m: MSE x1e4 minus base  ' + '  '.join(f'{m}:{(np.mean([wmse(base(Z[T], m), Z[T]) for T in TARGETS]) - ms)*1e4:+.4f}' for m in GRID_M))
    res['surface'] = {str(k): v for k, v in surface(Z).items()}
    kts = [c['kt'] for c in res['C']['chosen'].values()]
    res['placebo_C'] = placebo(Z, res['C']['dmse'], float(np.median(kts)))
    res['placebo_pos4'] = placebo_pos4(Z, res['pos4']['dmse'], float(np.median([c['kt'] for c in res['pos4']['chosen'].values()])))
    tmp = os.path.join(v1.P, '_bat_thin_prior_test.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(res, f, indent=1, default=float)
    os.replace(tmp, os.path.join(v1.P, '_bat_thin_prior_test.json'))


if __name__ == '__main__':
    main()
