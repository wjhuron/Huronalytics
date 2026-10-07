"""h2h_pitching.py: our runs-per-9 projection against Steamer and ZiPS, scored on what actually happened.

Matched set per target season T: every pitcher in pit_experience_test's wide pool (>= 1 out in T,
>= 1 MLB BF in T-3..T-1, position players excluded) that the FanGraphs system also projected (MLBAM
id). Truth: actual RA9 in T, as a delta from the league. Ours: the +exper arm (OLS on the wide pool,
x_E with k 20) fitted LEAVING T OUT; no Stuff+ (its history starts in 2021), so this is the
conservative version of ours. Theirs: projected ERA scaled to runs (RA9 = ERA x league RA9 / league
ERA of T, the earned-run gap) and, separately, projected FIP. Each projection is centered on the
matched set's IP-weighted actual mean, so this compares ranking and spread, not environment.
Blend w x ours + (1 - w) x theirs(ERA) chosen leaving the season out. Steamer 2018-2025, ZiPS 2020-2025.

Usage: python3 scripts/research/projection/h2h_pitching.py
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pit_experience_test as pe
import pit_rate_backtest as pr

SYSTEMS = {'steamer': range(2018, 2026), 'zips': range(2020, 2026)}
W_GRID = [i / 10 for i in range(11)]


def fg(system, T):
    out = {}
    for r in json.load(open(os.path.join(pr.P, 'fg', f'{system}_{T}_pit.json'))):
        m = r.get('xMLBAMID')
        if m and r.get('ERA') is not None and (r.get('IP') or 0) > 0:
            out[int(m)] = (float(r['ERA']), float(r['FIP']) if r.get('FIP') is not None else None)
    return out


def ids_by_season():
    S = {y: pr.season(y) for y in range(2015, 2027)}
    out = {}
    for T in pe.TARGETS:
        out[T] = [pid for pid, t in S[T].items() if any(S[T - 1 - k].get(pid) for k in range(3))]
    return out


def wstats(p, y, w):
    p = p - np.average(p, weights=w) + np.average(y, weights=w)
    pc, yc = p - np.average(p, weights=w), y - np.average(y, weights=w)
    return (float(np.average((p - y) ** 2, weights=w)),
            float(np.sum(w * pc * yc) / np.sqrt(np.sum(w * pc ** 2) * np.sum(w * yc ** 2))),
            float(np.sum(w * pc * yc) / np.sum(w * pc ** 2)), p)


def main():
    D = pe.build()
    preds = pe.run(D, '+exper', 20)
    IDS = ids_by_season()
    for T in pe.TARGETS:
        assert len(IDS[T]) == len(D[T]['y']), (T, len(IDS[T]), len(D[T]['y']))
    for system, years in SYSTEMS.items():
        print(f'\n===== ours vs {system} (runs per 9) =====')
        print(f'{"T":>5} {"n":>4} | {"MSE ours":>8} {"ERA":>7} {"FIP":>7} | {"r ours":>6} {"ERA":>6} {"FIP":>6} | {"slope ours":>10} {"ERA":>6}')
        per, B = [], {}
        for T in years:
            F = fg(system, T)
            idx = [i for i, pid in enumerate(IDS[T]) if pid in F and F[pid][1] is not None]
            y = D[T]['y'][idx]; w = D[T]['w'][idx]; o = preds[T][idx]
            era = np.array([F[IDS[T][i]][0] for i in idx]); fip = np.array([F[IDS[T][i]][1] for i in idx])
            mo, ro, so, oc = wstats(o, y, w); me, re_, se, ec = wstats(era, y, w); mf, rf, sf, fc = wstats(fip, y, w)
            per.append((T, mo, me, mf)); B[T] = (oc, ec, y, w)
            print(f'{T:>5} {len(idx):>4} | {mo:8.3f} {me:7.3f} {mf:7.3f} | {ro:6.3f} {re_:6.3f} {rf:6.3f} | {so:10.3f} {se:6.3f}')
        print(f'ours beats {system} ERA in {sum(p[1] < p[2] for p in per)}/{len(per)}, FIP in {sum(p[1] < p[3] for p in per)}/{len(per)}; '
              f'mean MSE ours {np.mean([p[1] for p in per]):.3f} ERA {np.mean([p[2] for p in per]):.3f} FIP {np.mean([p[3] for p in per]):.3f}')
        L = {T: [float(np.average(((wb * oc + (1 - wb) * ec) - y) ** 2, weights=w)) for wb in W_GRID] for T, (oc, ec, y, w) in B.items()}
        held = []
        for T in L:
            b = int(np.argmin(np.mean([L[S] for S in L if S != T], axis=0))); held.append((T, W_GRID[b], L[T][b]))
        print('  blend curve (weight on OURS): ' + '  '.join(f'{wb}:{v:.3f}' for wb, v in zip(W_GRID, np.mean(list(L.values()), axis=0))))
        print(f'  held-out blend beats both in {sum(l < min(p[1], p[2]) for (_, _, l), p in zip(held, per))}/{len(held)}; weights {[h[1] for h in held]}')


if __name__ == '__main__':
    main()
