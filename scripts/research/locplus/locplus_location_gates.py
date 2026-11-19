#!/usr/bin/env python3
"""locplus_location_gates.py — coloring gates for the LOCATION grade.

Same method as locplus_stabilize_celllevel.py (the script behind STABILIZE_N_PT):
cells are (pitcher, hand, pitch type), surfaces are built once on the full season,
two random non-overlapping n-pitch samples per cell give rho(n) directly, and
k = n (1 - rho) / rho, median over the n grid, 10 seeds. The gate is k: at n = k
half the variance of a colored cell is signal (the 0.5 line is a convention).

Two grades on the same pitches and the same splits:
  ship      the shipped Loc+ value (shipped kernel): must land near STABILIZE_N_PT
  location  count-currency value at the kernel of the 2026-11-18 sweep (2 in / 0.12)
            minus the league mean for (group, batter hand, pitcher hand, count)

Run on several seasons, because a gate measured on one season is one sample.

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/locplus_location_gates.py [2024,2025,2026]
"""
import gc
import json
import os
import random
import statistics
import sys
from collections import defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline.locplus as lp  # noqa: E402
import locplus_fullseason_replicate as FR  # noqa: E402
import locplus_count_calibration as CC  # noqa: E402
import locplus_stabilize_celllevel as ST  # noqa: E402

KERNEL = {'PHYS_X_IN': 2.0, 'PHYS_Z_FRAC': 0.12}
OUT = os.path.join(ROOT, 'data', '_loc_location_gates.json')


def cells_for(y):
    base = [p for p in FR.load_season(y) if lp.is_eligible_baseline(p)]
    S0 = lp.build_surfaces(base, FR.LG, FR.SCALE)
    off = lp.build_bip_count_offsets(base, FR.LG, FR.SCALE)
    FR.apply(KERNEL)
    try:
        S1 = lp.build_surfaces(base, FR.LG, FR.SCALE)
    finally:
        FR.restore()
    rows, acc = [], defaultdict(lambda: [0.0, 0])
    for p in base:
        v0 = lp.score_pitch(p, S0)
        if v0 is None:
            continue
        v1 = CC.score(p, S1, off, None)
        ck = (lp.group_of(p), p.get('Bats'), p.get('Throws'), lp.get_count(p))
        acc[ck][0] += v1
        acc[ck][1] += 1
        rows.append(((p.get('Pitcher'), p.get('Throws'), p.get('Pitch Type')), v0, v1, ck))
    del base, S0, S1
    gc.collect()
    mean = {k: s / n for k, (s, n) in acc.items()}
    ship, loc = defaultdict(list), defaultdict(list)
    for key, v0, v1, ck in rows:
        ship[key].append(v0)
        loc[key].append(v1 - mean[ck])
    return ship, loc


def social_k(y, seeds=10, grid=(5, 10, 15, 20, 25, 30, 40, 50, 60, 75, 100, 125, 150, 200, 250, 300), min_cells=100):
    """The social card's cell: pitcher x pitcher hand x BATTER hand x pitch type, values demeaned
    within (pitcher hand, batter hand, type), k = cell-weighted median over n with 100+ cells
    (scripts/research/cards/social_stabilize.py, the method behind SOCIAL_LOC_MIN_PITCHES)."""
    base = [p for p in FR.load_season(y) if lp.is_eligible_baseline(p)]
    off = lp.build_bip_count_offsets(base, FR.LG, FR.SCALE)
    S0 = lp.build_surfaces(base, FR.LG, FR.SCALE)
    FR.apply(KERNEL)
    try:
        S1 = lp.build_surfaces(base, FR.LG, FR.SCALE)
    finally:
        FR.restore()
    acc, rows = defaultdict(lambda: [0.0, 0]), []
    for p in base:
        v0 = lp.score_pitch(p, S0)
        if v0 is None:
            continue
        v1 = CC.score(p, S1, off, None)
        ck = (lp.group_of(p), p.get('Bats'), p.get('Throws'), lp.get_count(p))
        acc[ck][0] += v1
        acc[ck][1] += 1
        rows.append(((p.get('Pitcher'), p.get('Throws'), p.get('Bats'), p.get('Pitch Type')), v0, v1, ck))
    del base, S0, S1
    gc.collect()
    mean = {k: s_ / n_ for k, (s_, n_) in acc.items()}
    out = {}
    for name, pick in (('ship', lambda r: r[1]), ('location', lambda r: r[2] - mean[r[3]])):
        cells, grp = defaultdict(list), defaultdict(list)
        for r in rows:
            cells[r[0]].append(pick(r))
        for k, v in cells.items():
            grp[k[1:]].extend(v)
        gm = {k: sum(v) / len(v) for k, v in grp.items()}
        ks, ws = [], []
        for n in grid:
            rs = []
            for sd in range(seeds):
                rng = random.Random(sd)
                A, B_ = [], []
                for k, v in cells.items():
                    if len(v) < 2 * n:
                        continue
                    smp = rng.sample(v, 2 * n)
                    A.append(sum(smp[:n]) / n - gm[k[1:]])
                    B_.append(sum(smp[n:]) / n - gm[k[1:]])
                if len(A) >= min_cells:
                    r = ST.pearson(A, B_)
                    if r and r > 0:
                        rs.append((n * (1 - r) / r, len(A)))
            if rs:
                ks.append(float(np.median([x[0] for x in rs])))
                ws.append(float(np.mean([x[1] for x in rs])))
        order = np.argsort(ks)
        cw = np.cumsum(np.array(ws)[order])
        out[name] = float(np.array(ks)[order][np.searchsorted(cw, cw[-1] / 2)])
    return out


def gates(cells):
    out = {}
    for G in ST.GROUPS:
        per_seed, ncell = [], 0
        for s in ST.SEEDS:
            random.seed(s)
            ks = []
            for n in ST.N_GRID:
                A, B = [], []
                for key, v in cells.items():
                    if lp.GROUP.get(key[2]) != G or len(v) < 2 * n:
                        continue
                    smp = random.sample(v, 2 * n)
                    A.append(sum(smp[:n]) / n)
                    B.append(sum(smp[n:]) / n)
                if len(A) < ST.MIN_CELLS:
                    continue
                if n == 71 and s == 0:
                    ncell = len(A)
                r = ST.pearson(A, B)
                if r and r > 0:
                    ks.append(n * (1 - r) / r)
            if ks:
                per_seed.append(statistics.median(ks))
        if per_seed:
            out[G] = (statistics.median(per_seed), min(per_seed), max(per_seed), ncell)
    return out


def main():
    years = [int(v) for v in sys.argv[1].split(',')] if len(sys.argv) > 1 else [2024, 2025, 2026]
    if len(sys.argv) > 2 and sys.argv[2] == 'social':
        res = {y: social_k(y) for y in years}
        for y, r in res.items():
            print(f'{y}: social-card cell k   shipped Loc+ {r["ship"]:.0f}   location {r["location"]:.0f}')
        print(f'location, median over seasons: {np.median([r["location"] for r in res.values()]):.0f}')
        json.dump({str(y): r for y, r in res.items()}, open(OUT.replace('.json', '_social.json'), 'w'), indent=1)
        return
    res = {}
    for y in years:
        ship, loc = cells_for(y)
        gs, gl = gates(ship), gates(loc)
        res[y] = {'ship': gs, 'location': gl}
        print(f'\n{y}: cells {len(ship)}')
        print(f'{"grp":>5s}{"shipped const":>14s}{"ship k (min-max)":>20s}{"location k (min-max)":>24s}{"cells@71":>10s}')
        for G in ST.GROUPS:
            if G in gs and G in gl:
                a, b = gs[G], gl[G]
                print(f'{G:>5s}{lp.STABILIZE_N_PT.get(G, 0):>14d}{f"{a[0]:.0f} ({a[1]:.0f}-{a[2]:.0f})":>20s}'
                      f'{f"{b[0]:.0f} ({b[1]:.0f}-{b[2]:.0f})":>24s}{b[3]:>10d}')
        del ship, loc
        gc.collect()
    print('\nlocation gate by group, median over seasons (and each season):')
    for G in ST.GROUPS:
        v = [res[y]['location'][G][0] for y in years if G in res[y]['location']]
        if v:
            print(f'  {G}: {np.median(v):.0f}   ' + ' '.join(f'{x:.0f}' for x in v))
    json.dump({str(y): {k: {g: list(t) for g, t in d.items()} for k, d in r.items()} for y, r in res.items()},
              open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
