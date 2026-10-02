"""bat_horizon_backtest.py: batting projection at 1, 3 and 5 seasons out (ZiPS-style horizons).

Base season B, history B-2..B (Savant xwOBA/wOBA from 2015, so B >= 2017), target T = B + h.
Replicates: h=1 B 2017-2025 (9), h=3 B 2017-2023 (7), h=5 B 2017-2021 (5). Pool: >= 200 PA in
T, > 0 PA in the history. Objective: PA_T-weighted MSE against actual wOBA_T (delta from league).
LOSO over base seasons; the aging curve, when used, is fitted only on pairs before B + 1.

The level part is v1's (a, d, n0). Aging candidates, all applied as the change from the
history's weighted age to the target age:
  lin    v1 rule cumulated over the h years: +ys per year below peak, -os per year above
  curve  s x [C(age_T) - weighted C(age at each history season)], aging_hitters curve (n0 450, W 3)
Both age forms are swept per horizon, because a rule tuned at h=1 says nothing about h=5.

Usage: python3 scripts/research/projection/bat_horizon_backtest.py
Output: console + data/_proj/_bat_horizon_backtest.json
"""
import itertools
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aging_hitters as ag
import bat_rate_backtest as v1

HORIZONS = {1: range(2017, 2026), 3: range(2017, 2024), 5: range(2017, 2022)}
LEVEL = {'a': [0.625, 0.75, 0.875, 1.0], 'd': [0.55, 0.7, 0.85], 'n0': [300, 450, 600, 900]}
LIN = {'ys': [0.0, 0.002, 0.004, 0.006], 'os': [0.0015, 0.003, 0.0045, 0.006, 0.0075], 'peak': [27, 28, 29, 30, 31, 32, 33]}
CURVE = {'s': [0.0, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]}


def build(X, LG, A, B, h):
    T = B + h
    rows = []
    for pid, (pa_t, w_t, _) in X[T].items():
        if pa_t < v1.MIN_PA_T:
            continue
        ag_t = A[T].get(pid)
        if ag_t is None or ag_t[1] == 'P':
            continue
        hist = []
        for k in range(3):
            v = X[B - k].get(pid)
            hist.append((v[0], v[1] - LG[B - k][0], v[2] - LG[B - k][1]) if v else (0, 0.0, 0.0))
        if sum(x[0] for x in hist) == 0:
            continue
        rows.append((ag_t[0], pa_t, w_t - LG[T][0], *[c for x in hist for c in x]))
    return np.array(rows, float)


def level(M, a, d, n0):
    num = np.zeros(len(M)); den = np.zeros(len(M))
    for k in range(3):
        pa, w, x = M[:, 3 + 3 * k], M[:, 4 + 3 * k], M[:, 5 + 3 * k]
        num += d ** k * pa * (a * x + (1 - a) * w)
        den += d ** k * pa
    return num / (den + n0), den


def age_from(M, h, d):
    """weighted history age (age_T - h - k for season B - k)."""
    den = np.zeros(len(M)); s = np.zeros(len(M))
    for k in range(3):
        wt = d ** k * M[:, 3 + 3 * k]
        s += wt * (M[:, 0] - h - k)
        den += wt
    return s / den


def lin_term(a0, a1, ys, os_, peak):
    """integral of the piecewise-linear rate from age a0 to a1."""
    lo = np.minimum(a1, peak) - np.minimum(a0, peak)
    hi = np.maximum(a1, peak) - np.maximum(a0, peak)
    return ys * lo - os_ * hi


def curve_term(C, a0, a1, s):
    def c(x):
        x = np.clip(x, ag.AGE_LO, ag.AGE_HI)
        f = np.floor(x).astype(int); r = x - f
        lo = np.array([C[int(v)] for v in f]); hi = np.array([C[int(min(v + 1, ag.AGE_HI))] for v in f])
        return lo + r * (hi - lo)
    return s * (c(a1) - c(a0))


def main():
    X = {y: v1.load_xstats(y) for y in range(2015, 2027)}
    LG = {y: v1.league(X[y]) for y in X}
    A = {y: v1.load_ages(y) for y in range(2015, 2027)}
    Pm = ag.pairs()
    out = {}
    for h, bases in HORIZONS.items():
        bases = list(bases)
        D = {B: build(X, LG, A, B, h) for B in bases}
        C = {B: v1_cum(ag.curve(Pm[Pm[:, 0] <= B], 450, 3)) for B in bases}
        res = {}
        for form, grid in (('lin', LIN), ('curve', CURVE)):
            keys = list(LEVEL) + list(grid)
            combos = list(itertools.product(*[LEVEL[k] for k in LEVEL], *[grid[k] for k in grid]))
            L = np.zeros((len(combos), len(bases)))
            for j, B in enumerate(bases):
                M = D[B]
                lv_cache = {}
                for i, c in enumerate(combos):
                    a, d, n0 = c[:3]
                    if (a, d, n0) not in lv_cache:
                        lv_cache[(a, d, n0)] = (level(M, a, d, n0)[0], age_from(M, h, d))
                    lv, a0 = lv_cache[(a, d, n0)]
                    at = lin_term(a0, M[:, 0], *c[3:]) if form == 'lin' else curve_term(C[B], a0, M[:, 0], *c[3:])
                    L[i, j] = v1.wmse(lv + at, M[:, 2], M[:, 1])
            held = []
            for j in range(len(bases)):
                o = [k for k in range(len(bases)) if k != j]
                b = int(np.argmin(L[:, o].mean(axis=1)))
                held.append((L[b, j], dict(zip(keys, combos[b]))))
            best = int(np.argmin(L.mean(axis=1)))
            curves = {}
            for ki, k in enumerate(keys):
                vals = LEVEL.get(k) or grid[k]
                pts = []
                for v in vals:
                    cc = list(combos[best]); cc[ki] = v
                    pts.append((v, float(L[combos.index(tuple(cc))].mean() * 1e4)))
                curves[k] = pts
            res[form] = {'held': held, 'pooled': dict(zip(keys, combos[best])), 'curves': curves}
        # Marcel-style null at this horizon: no aging, v1 level only (pooled level of the lin form, s=0 aging)
        print(f'\n== h = {h}  bases {bases[0]}-{bases[-1]}  n = {[len(D[B]) for B in bases]}')
        wins = 0
        for j, B in enumerate(bases):
            l1, c1 = res['lin']['held'][j]; l2, c2 = res['curve']['held'][j]
            wins += l2 < l1
            print(f'  B {B} T {B+h}: lin {l1*1e4:7.3f}  curve {l2*1e4:7.3f}   lin {tuple(c1.values())}  curve {tuple(c2.values())}')
        print(f'  curve beats lin in {wins}/{len(bases)}')
        for form in ('lin', 'curve'):
            print(f'  {form} pooled {res[form]["pooled"]}')
            for k, pts in res[form]['curves'].items():
                print(f'     {k:>5}: ' + '  '.join(f'{v}:{l:.3f}' for v, l in pts))
        out[h] = {f: {'held': [(float(l), c) for l, c in res[f]['held']], 'pooled': res[f]['pooled'], 'curves': res[f]['curves']} for f in res}
    tmp = os.path.join(v1.P, '_bat_horizon_backtest.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(out, f, indent=1)
    os.replace(tmp, os.path.join(v1.P, '_bat_horizon_backtest.json'))


def v1_cum(c):
    run, out = 0.0, {}
    for a in sorted(c):
        run += c[a]
        out[a] = run
    return out


if __name__ == '__main__':
    main()
