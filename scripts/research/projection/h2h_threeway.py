"""h2h_threeway.py: ours vs Steamer vs ZiPS vs blends, batting wOBA and pitcher runs per 9, 2020-2025.

Matched set: players all three systems projected (ours from h2h_batting / h2h_pitching, the held-out
versions; pitchers here WITHOUT Stuff+ because its history starts in 2021, so ours is understated on
the pitcher side). Every projection centered on the matched set's actual mean (ranking and spread,
not environment). Weights on the simplex in steps of .1, chosen leaving the season out.

Usage: python3 scripts/research/projection/h2h_threeway.py
"""
import itertools
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import h2h_batting as hb
import h2h_pitching as hp
import pit_experience_test as pe

YEARS = list(range(2020, 2026))
SIMPLEX = [(a / 10, b / 10, round(1 - a / 10 - b / 10, 1)) for a in range(11) for b in range(11 - a)]


def centered(p, y, w):
    return p - np.average(p, weights=w) + np.average(y, weights=w)


def evaluate(data, label):
    L = {T: [float(np.average(((wo * o + ws * s + wz * z) - y) ** 2, weights=w)) for wo, ws, wz in SIMPLEX]
         for T, (o, s, z, y, w) in data.items()}
    held = []
    for T in YEARS:
        b = int(np.argmin(np.mean([L[S] for S in YEARS if S != T], axis=0)))
        held.append((SIMPLEX[b], L[T][b]))
    single = {nm: [L[T][SIMPLEX.index(v)] for T in YEARS] for nm, v in (('ours', (1.0, 0.0, 0.0)), ('steamer', (0.0, 1.0, 0.0)), ('zips', (0.0, 0.0, 1.0)))}
    two = {nm: [L[T][SIMPLEX.index(v)] for T in YEARS] for nm, v in (('ours+steamer 50/50', (0.5, 0.5, 0.0)), ('ours+zips 50/50', (0.5, 0.0, 0.5)), ('equal thirds', (0.3, 0.3, 0.4)))}
    pooled = np.mean(list(L.values()), axis=0); bp = int(np.argmin(pooled))
    print(f'\n== {label}: n per season {[len(data[T][3]) for T in YEARS]}')
    for nm, v in {**single, **two}.items():
        print(f'   {nm:20s} mean MSE {np.mean(v):.5f}')
    hm = [h[1] for h in held]
    print(f'   held-out 3-way       mean MSE {np.mean(hm):.5f}   weights (ours, steamer, zips) {[h[0] for h in held]}')
    print(f'   pooled argmin {SIMPLEX[bp]}; held-out 3-way beats every single system in '
          f'{sum(h < min(single[k][i] for k in single) for i, h in enumerate(hm))}/{len(YEARS)}, beats ours+steamer 50/50 in '
          f'{sum(h < two["ours+steamer 50/50"][i] for i, h in enumerate(hm))}/{len(YEARS)}')


def main():
    ours = hb.ours_by_season()
    bat = {}
    for T in YEARS:
        S, Z = hb.fg('steamer', T), hb.fg('zips', T)
        ids = [i for i in ours[T] if i in S and i in Z]
        y = np.array([ours[T][i][1] for i in ids]); w = np.array([ours[T][i][2] for i in ids])
        bat[T] = tuple(centered(np.array(v), y, w) for v in ([ours[T][i][0] for i in ids], [S[i] for i in ids], [Z[i] for i in ids])) + (y, w)
    evaluate(bat, 'batting wOBA')
    D = pe.build(); preds = pe.run(D, '+exper', 20); IDS = hp.ids_by_season()
    pit = {}
    for T in YEARS:
        S, Z = hp.fg('steamer', T), hp.fg('zips', T)
        idx = [i for i, pid in enumerate(IDS[T]) if pid in S and pid in Z]
        y = D[T]['y'][idx]; w = D[T]['w'][idx]
        pit[T] = (centered(preds[T][idx], y, w), centered(np.array([S[IDS[T][i]][0] for i in idx]), y, w),
                  centered(np.array([Z[IDS[T][i]][0] for i in idx]), y, w), y, w)
    evaluate(pit, 'pitcher runs per 9 (ours without Stuff+)')


if __name__ == '__main__':
    main()
