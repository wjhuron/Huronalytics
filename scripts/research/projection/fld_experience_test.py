"""fld_experience_test.py: the fielding projection on EVERY fielder, and the prior it regresses toward.

Same question as bat_experience_test.py, for Savant fielding run value per 1000 defensive outs. The v1
fielding projection (fld_rate_backtest.py) scored fielders with >= 1500 outs in the target season and
shrank toward 0 (average). Here: every fielder with >= 1 out in T (2019-2026) and >= 1 out in the
history, outs_T-weighted MSE, leave one season out. Arms differ only in the prior:
  zero    mu = 0 (v1)
  exper   mu(E) = c / (1 + E / k), E = raw history outs
Settings otherwise the v1 pooled ones (d .55, age peak 34, yi .05, od .2); N0 re-swept per arm.
Reports the calibration table by history outs and the per-bin MSE.

Usage: python3 scripts/research/projection/fld_experience_test.py
"""
import itertools
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fld_rate_backtest as fr

TARGETS = list(range(2019, 2027))
D, PEAK, YI, OD = 0.55, 34, 0.05, 0.2
BINS = [(1, 500), (500, 1500), (1500, 3000), (3000, 6000), (6000, 10 ** 7)]
GRID_N0 = [1000, 2000, 3000, 4500]
GRID_C = [0.0, -0.5, -1.0, -1.5, -2.0, -3.0]
GRID_K = [1000, 4000, 16000, 64000, 10 ** 9]


def build():
    S = {y: fr.season(y) for y in range(2016, 2027)}
    Z = {}
    for T in TARGETS:
        rows = []
        for pid, (o, r, age) in S[T].items():
            if age is None:
                continue
            h = [S[T - 1 - k].get(pid, (0, 0.0, None)) for k in range(3)]
            E = sum(x[0] for x in h)
            if E == 0:
                continue
            num = sum(D ** k * x[0] * x[1] for k, x in enumerate(h)); den = sum(D ** k * x[0] for k, x in enumerate(h))
            rows.append((num, den, E, age, r, o))
        a = np.array(rows, float)
        Z[T] = {'num': a[:, 0], 'den': a[:, 1], 'E': a[:, 2], 'age': a[:, 3], 'y': a[:, 4], 'w': a[:, 5]}
    return Z


def project(z, n0, c, k):
    mu = c / (1 + z['E'] / k)
    age = z['age']
    return (z['num'] + n0 * mu) / (z['den'] + n0) + np.where(age < PEAK, YI * (PEAK - age), -OD * (age - PEAK))


def wmse(p, z, m=None):
    m = np.ones(len(p), bool) if m is None else m
    return float((z['w'][m] * (p[m] - z['y'][m]) ** 2).sum() / z['w'][m].sum())


def main():
    Z = build()
    print('pool per season:', {T: len(Z[T]['y']) for T in TARGETS})
    arms = {'zero': [(n0, 0.0, 1000) for n0 in GRID_N0],
            'exper': list(itertools.product(GRID_N0, GRID_C, GRID_K))}
    best = {}
    for arm, combos in arms.items():
        L = np.array([[wmse(project(Z[T], *c), Z[T]) for T in TARGETS] for c in combos])
        held = []
        for j, T in enumerate(TARGETS):
            o = [i for i in range(len(TARGETS)) if i != j]
            held.append(combos[int(np.argmin(L[:, o].mean(axis=1)))])
        b = int(np.argmin(L.mean(axis=1)))
        best[arm] = (combos[b], held, L)
        print(f'\n== {arm}: pooled {combos[b]}  mean MSE {L[b].mean():.3f}')
        if arm == 'exper':
            for nm, idx, grid in (('n0', 0, GRID_N0), ('c', 1, GRID_C), ('k', 2, GRID_K)):
                pts = []
                for v in grid:
                    cc = list(combos[b]); cc[idx] = v
                    pts.append(f'{v}:{L[combos.index(tuple(cc))].mean():.3f}')
                print(f'    {nm:>3}: ' + '  '.join(pts))
    wins = 0
    for j, T in enumerate(TARGETS):
        wins += wmse(project(Z[T], *best['exper'][1][j]), Z[T]) < wmse(project(Z[T], *best['zero'][1][j]), Z[T])
    print(f'\nexper beats zero in {wins}/{len(TARGETS)} held-out seasons')
    for lo, hi in BINS:
        cz, ce, mz, me = [], [], [], []
        for j, T in enumerate(TARGETS):
            z = Z[T]; m = (z['E'] >= lo) & (z['E'] < hi)
            if not m.any():
                continue
            pz = project(z, *best['zero'][1][j]); pe = project(z, *best['exper'][1][j])
            cz.append((z['w'][m] * (z['y'][m] - pz[m])).sum() / z['w'][m].sum()); ce.append((z['w'][m] * (z['y'][m] - pe[m])).sum() / z['w'][m].sum())
            mz.append(wmse(pz, z, m)); me.append(wmse(pe, z, m))
        print(f'  history outs {lo}-{hi if hi < 10**7 else "+"}: bias zero {np.mean(cz):+.2f} exper {np.mean(ce):+.2f} runs/1000 outs | '
              f'MSE zero {np.mean(mz):.2f} exper {np.mean(me):.2f} | exper no worse {sum(a <= b + 1e-12 for a, b in zip(me, mz))}/{len(me)}')


if __name__ == '__main__':
    main()
