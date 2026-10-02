"""bat_rate_backtest_v2.py: the v1 batting projection with the empirical aging curve.

Same targets, pool, objective and LOSO as bat_rate_backtest.py. The age term changes:

    v1     linear: +ys (peak - age) below the peak, -os (age - peak) above
    v2     curve:  s x [C(age_T) - sum_k w_k C(age_T - 1 - k) / sum_k w_k],  w_k = d^k PA_{T-1-k}

C is the cumulative per-age delta of aging_hitters.curve, fitted ONLY on season pairs whose
later season is before T (no target season, no future), on the raw or the shrunk-450 scale.
s scales the curve (1 = as measured) and is swept, with a, d and n0.

Usage: python3 scripts/research/projection/bat_rate_backtest_v2.py
Output: console + data/_proj/_bat_rate_backtest_v2.json
"""
import itertools
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aging_hitters as ag
import bat_rate_backtest as v1

GRID = {
    'a': [0.5, 0.625, 0.75, 0.875, 1.0],
    'd': [0.55, 0.7, 0.85],
    'n0': [300, 450, 600],
    's': [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5],
    'curve_n0': [0, 450],
}


def cumulative(c):
    ages = sorted(c)
    out, run = {}, 0.0
    for a in ages:
        run += c[a]
        out[a] = run
    return out


def project(M, C, a, d, n0, s):
    age_t = M[:, 1]
    num = np.zeros(len(M)); den = np.zeros(len(M)); cage = np.zeros(len(M))
    for k in range(3):
        pa, w, x = M[:, 5 + 3 * k], M[:, 6 + 3 * k], M[:, 7 + 3 * k]
        wt = d ** k * pa
        num += wt * (a * x + (1 - a) * w)
        den += wt
        cage += wt * np.array([C[int(min(max(t - 1 - k, ag.AGE_LO), ag.AGE_HI))] for t in age_t])
    proj = (num / den) * den / (den + n0)
    c_t = np.array([C[int(min(max(t, ag.AGE_LO), ag.AGE_HI))] for t in age_t])
    return proj + s * (c_t - cage / den)


def main():
    data, LG = v1.build()
    Pm = ag.pairs()
    curves = {(T, cn): cumulative(ag.curve(Pm[Pm[:, 0] < T], cn, 3)) for T in v1.TARGETS for cn in GRID['curve_n0']}
    keys = list(GRID)
    combos = list(itertools.product(*[GRID[k] for k in keys]))
    L = np.zeros((len(combos), len(v1.TARGETS)))
    for j, T in enumerate(v1.TARGETS):
        M = data[T]
        for i, (a, d, n0, s, cn) in enumerate(combos):
            L[i, j] = v1.wmse(project(M, curves[(T, cn)], a, d, n0, s), M[:, 3], M[:, 2])
    v1_best = json.load(open(os.path.join(v1.P, '_bat_rate_backtest.json')))['loso']
    print(f'{"T":>5} {"marcel":>8} {"v1":>8} {"v2":>8}  chosen (a d n0 s curve_n0)')
    w1 = wm = 0
    rows = []
    for j, T in enumerate(v1.TARGETS):
        o = [k for k in range(len(v1.TARGETS)) if k != j]
        b = int(np.argmin(L[:, o].mean(axis=1)))
        r1 = v1_best[j]
        w1 += L[b, j] < r1['model']; wm += L[b, j] < r1['marcel']
        rows.append({'T': T, 'v2': L[b, j], 'v1': r1['model'], 'marcel': r1['marcel'], 'chosen': dict(zip(keys, combos[b]))})
        print(f'{T:>5} {r1["marcel"]*1e4:8.3f} {r1["model"]*1e4:8.3f} {L[b, j]*1e4:8.3f}  {combos[b]}')
    print(f'v2 beats v1 in {w1}/{len(v1.TARGETS)}, Marcel in {wm}/{len(v1.TARGETS)} held-out seasons')
    best = int(np.argmin(L.mean(axis=1)))
    print('pooled argmin:', dict(zip(keys, combos[best])))
    for ki, k in enumerate(keys):
        pts = []
        for v in GRID[k]:
            c = list(combos[best]); c[ki] = v
            pts.append(f'{v}:{L[combos.index(tuple(c))].mean()*1e4:.3f}')
        print(f'  {k:>8}: ' + '  '.join(pts))
    out = {'loso': rows, 'pooled': dict(zip(keys, combos[best])), 'grid': GRID}
    tmp = os.path.join(v1.P, '_bat_rate_backtest_v2.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(out, f, indent=1)
    os.replace(tmp, os.path.join(v1.P, '_bat_rate_backtest_v2.json'))


if __name__ == '__main__':
    main()
