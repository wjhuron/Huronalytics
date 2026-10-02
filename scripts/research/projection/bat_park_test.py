"""bat_park_test.py: should the batting projection remove park from the history, and add the target park back?

The v1 projection (bat_rate_backtest.py) blends raw Savant xwOBA and wOBA, both measured in the
hitter's home park. Park effect in wOBA units for one season: (exposure - 1) x lgRPA x wOBAscale,
exposure = (PF/100 + 1)/2 (the hWAR convention), with the share that reaches each input measured
WITHIN batter (hwar_park_pass_within.py): xwOBA .37, actual wOBA ~1.0. So the blend's share is
    pass(a) = a x .37 + (1 - a) x 1.0
Arms (identical level and aging constants, the v1 pooled ones; only the park term differs):
    none     v1 as shipped in research
    hist     subtract m x pass(a) x park effect from each history season
    hist+T   the same, and add m x 1.0 x the target-season park effect back (the target is actual wOBA
             in the park he plays in)
m sweeps the strength (1 = the measured pass-through). Club = the season line's club (the final club
for a traded hitter; a labeled approximation). Park factors: data/_proj/park_factors_hist.json.
LOSO over targets for m; paired wins against `none` per held-out season.

Usage: python3 scripts/research/projection/bat_park_test.py
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bat_rate_backtest as v1

PF = json.load(open(os.path.join(v1.P, 'park_factors_hist.json')))
LG_RPA, SCALE = 0.118, 1.24          # 2021-2026 Guts range .116-.121 / 1.20-1.26; the term is small
A, D, N0, YS, OS, PEAK = 0.75, 0.7, 450, 0.002, 0.0015, 29
M_GRID = [0.0, 0.25, 0.375, 0.5, 0.625, 0.75]


def clubs(y):
    return {r['id']: r.get('team') for r in json.load(open(os.path.join(v1.P, f'lines_hitting_{y}.json')))}


def park_eff(y, team):
    pf = PF.get(str(y), {}).get(str(team))
    return 0.0 if pf is None else ((pf / 100 + 1) / 2 - 1) * LG_RPA * SCALE


def main():
    data, LG = v1.build()
    C = {y: clubs(y) for y in range(2015, 2027)}
    pass_mix = A * 0.37 + (1 - A) * 1.0
    res = {}
    for arm in ('hist', 'hist+T'):
        L = np.zeros((len(M_GRID), len(v1.TARGETS))); base = []
        for j, T in enumerate(v1.TARGETS):
            M = data[T].copy()
            pid = M[:, 0].astype(int)
            base.append(v1.wmse(v1.project(M, A, D, N0, YS, OS, PEAK), M[:, 3], M[:, 2]))
            pe_h = [np.array([park_eff(T - 1 - k, C[T - 1 - k].get(p)) for p in pid]) for k in range(3)]
            pe_t = np.array([park_eff(T, C[T].get(p)) for p in pid])
            for i, m in enumerate(M_GRID):
                X = M.copy()
                for k in range(3):
                    X[:, 6 + 3 * k] -= m * 1.0 * pe_h[k]          # wOBA column: full pass
                    X[:, 7 + 3 * k] -= m * 0.37 * pe_h[k]         # xwOBA column: .37 pass
                p = v1.project(X, A, D, N0, YS, OS, PEAK)
                if arm == 'hist+T':
                    p = p + m * 1.0 * pe_t
                L[i, j] = v1.wmse(p, M[:, 3], M[:, 2])
        print(f'\n== arm {arm}  (blend pass at a={A}: {pass_mix:.3f})')
        held = []
        for j, T in enumerate(v1.TARGETS):
            o = [k for k in range(len(v1.TARGETS)) if k != j]
            b = int(np.argmin(L[:, o].mean(axis=1)))
            held.append((T, M_GRID[b], L[b, j], base[j]))
        wins = sum(l < b for _, _, l, b in held)
        print('  held-out:', ' '.join(f'{T}:m{m} {100*(1-l/b):+.1f}%' for T, m, l, b in held), f'| wins {wins}/{len(held)}')
        print('  pooled curve (mean MSE x1e4):', '  '.join(f'm{m}:{L[i].mean()*1e4:.3f}' for i, m in enumerate(M_GRID)),
              f'| none {np.mean(base)*1e4:.3f}')
        res[arm] = {'held': held, 'curve': {str(m): float(L[i].mean()) for i, m in enumerate(M_GRID)}, 'none': float(np.mean(base))}
    tmp = os.path.join(v1.P, '_bat_park_test.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(res, f, indent=1)
    os.replace(tmp, os.path.join(v1.P, '_bat_park_test.json'))


if __name__ == '__main__':
    main()
