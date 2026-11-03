"""bat_components_test.py: do plate-discipline and power components add to the wOBA/xwOBA projection?

Steamer and ZiPS are component projections; ours projects wOBA from wOBA and xwOBA history only. On the
wide pool of bat_experience_test (targets 2018-2026, held-out exper+aaa projection as the base), add the
history of MLB K%, BB% and ISO (box lines, deltas from the league, weighted d^k by PA like the batting
history and shrunk at N0_C PA) as residual channels: target delta = base + OLS(components), the OLS fit
leaving the target season out. N0_C swept. A gain here means the components carry signal that wOBA and
xwOBA do not.

Usage: python3 scripts/research/projection/bat_components_test.py
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aaa_hitter_bridge as hb
import bat_experience_test as bx

N0_GRID = [100, 200, 400, 800, 1600]
D_ = 0.7


def comp_hist(M, pid, T, n0):
    num = np.zeros(3); den = 0.0
    for k in range(3):
        v = M[T - 1 - k][0].get(pid)
        if v:
            wt = D_ ** k * v['pa']
            num += wt * np.array([v['d_k'], v['d_bb'], v['d_iso']]); den += wt
    return num / (den + n0)


def main():
    D, Aaa, Mlb = bx.build()
    held = {h['T']: h['chosen'] for h in json.load(open(os.path.join(bx.v1.P, '_bat_experience_test.json')))['exper+aaa']['held']}
    base, Y, W, IDS = {}, {}, {}, {}
    for T in bx.TARGETS:
        Z = bx.arrays(D[T], bx.bridge_beta(Aaa, Mlb, T))
        base[T] = bx.project(Z, *held[T]); Y[T] = Z['y']; W[T] = Z['w']; IDS[T] = [r['id'] for r in D[T]]
    for n0 in N0_GRID:
        C = {T: np.array([comp_hist(Mlb, pid, T, n0) for pid in IDS[T]]) for T in bx.TARGETS}
        gains, coefs = [], []
        for T in bx.TARGETS:
            tr = [S for S in bx.TARGETS if S != T]
            X = np.vstack([C[S] for S in tr]); r = np.concatenate([Y[S] - base[S] for S in tr]); w = np.concatenate([W[S] for S in tr])
            b = hb.wols(X, r, w)
            p = base[T] + np.column_stack([np.ones(len(C[T])), C[T]]) @ b
            m0 = np.average((base[T] - Y[T]) ** 2, weights=W[T]); m1 = np.average((p - Y[T]) ** 2, weights=W[T])
            gains.append(1 - m1 / m0); coefs.append(b)
        print(f'N0_C {n0:>5}: mean gain {100*np.mean(gains):+.2f}%  wins {sum(g > 0 for g in gains)}/{len(gains)}  '
              f'coef (int, K, BB, ISO) {np.round(np.mean(coefs, axis=0), 4).tolist()}')


if __name__ == '__main__':
    main()
