#!/usr/bin/env python3
"""locplus_shape_gates.py — coloring gates for the shape-class Loc+ grade.

Same method and seasons as locplus_location_gates.py (the script behind the
released STABILIZE_N_PT and SOCIAL_LOC_MIN_PITCHES), on two grades of the same
pitches and the same random splits, both from the BRANCH module:
  rel     the released location value (the branch bundle without its class part);
          must land near the released gates
  shape   the shape-class blend
k = n (1 - rho) / rho from two non-overlapping n-pitch samples per cell.

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/locplus_shape_gates.py /path/to/branch [2024,2025,2026]
"""
import gc
import json
import os
import random
import sys
from collections import defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline.locplus as lp  # noqa: E402
import locplus_fullseason_replicate as FR  # noqa: E402
import locplus_location_gates as LG  # noqa: E402
import locplus_shape_loader as SL  # noqa: E402

ST = LG.ST
OUT = os.path.join(ROOT, 'data', '_loc_shape_gates.json')


def social(rows, pick, seeds=10, grid=(5, 10, 15, 20, 25, 30, 40, 50, 60, 75, 100, 125, 150, 200, 250, 300), min_cells=100):
    """locplus_location_gates.social_k for one value column."""
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
    return float(np.array(ks)[order][np.searchsorted(cw, cw[-1] / 2)])


def main():
    BR = SL.branch(sys.argv[1])
    years = [int(v) for v in sys.argv[2].split(',')] if len(sys.argv) > 2 else [2024, 2025, 2026]
    res = {}
    for y in years:
        base = [p for p in SL.load_season(y) if BR.is_eligible_baseline(p)]
        if hasattr(BR, 'FAR_MISS_X_IN'):
            # far-miss branch (2026-11-19): the control is the same module with the rule off
            # (= the live shape-class grade); the cell means differ, so it is a second build
            cut = (BR.FAR_MISS_X_IN, BR.FAR_MISS_Z_LO, BR.FAR_MISS_Z_HI)
            BR.FAR_MISS_X_IN = BR.FAR_MISS_Z_LO = BR.FAR_MISS_Z_HI = float('inf')
            S0 = BR.build_surfaces(base, FR.LG, FR.SCALE)
            BR.FAR_MISS_X_IN, BR.FAR_MISS_Z_LO, BR.FAR_MISS_Z_HI = cut
            S = BR.build_surfaces(base, FR.LG, FR.SCALE)
            pairs_ = ((S0, cut), (S, cut))
        else:
            S = BR.build_surfaces(base, FR.LG, FR.SCALE)
            S0 = {k: v for k, v in S.items() if k != 'SHAPE'}
            pairs_ = None
        cells = {'rel': defaultdict(list), 'shape': defaultdict(list)}
        rows = []
        for p in base:
            if pairs_:
                BR.FAR_MISS_X_IN = BR.FAR_MISS_Z_LO = BR.FAR_MISS_Z_HI = float('inf')
                a = BR.location_value(p, S0)
                BR.FAR_MISS_X_IN, BR.FAR_MISS_Z_LO, BR.FAR_MISS_Z_HI = pairs_[1][1]
                b = BR.location_value(p, S)
            else:
                a, b = BR.location_value(p, S0), BR.location_value(p, S)
            if a is None or b is None:
                continue
            pt = p.get('_pt0') or p.get('Pitch Type')
            key = (p.get('Pitcher'), p.get('Throws'), pt)
            cells['rel'][key].append(a)
            cells['shape'][key].append(b)
            rows.append(((p.get('Pitcher'), p.get('Throws'), p.get('Bats'), pt), a, b))
        del base, S, S0
        gc.collect()
        g = {k: LG.gates(v) for k, v in cells.items()}
        soc = {'rel': social(rows, lambda r: r[1]), 'shape': social(rows, lambda r: r[2])}
        res[y] = {'gates': g, 'social': soc}
        print(f'\n{y}:  {"grp":>5s}{"released const":>16s}{"rel k (min-max)":>20s}{"shape k (min-max)":>22s}')
        for G in ST.GROUPS:
            if G in g['rel'] and G in g['shape']:
                a, b = g['rel'][G], g['shape'][G]
                print(f'       {G:>5s}{lp.STABILIZE_N_PT.get(G, 0):>16d}{f"{a[0]:.0f} ({a[1]:.0f}-{a[2]:.0f})":>20s}{f"{b[0]:.0f} ({b[1]:.0f}-{b[2]:.0f})":>22s}')
        print(f'       social-card cell k: released {soc["rel"]:.0f}, shape {soc["shape"]:.0f}', flush=True)
        del cells, rows
        gc.collect()
    print('\ngate by group, median over seasons: released constant | rel | shape')
    for G in ST.GROUPS:
        a = [res[y]['gates']['rel'][G][0] for y in years if G in res[y]['gates']['rel']]
        b = [res[y]['gates']['shape'][G][0] for y in years if G in res[y]['gates']['shape']]
        if a and b:
            print(f'  {G}: {lp.STABILIZE_N_PT.get(G, 0)} | {np.median(a):.0f} | {np.median(b):.0f}   ({" ".join(f"{x:.0f}" for x in b)})')
    print(f'  social: {np.median([res[y]["social"]["rel"] for y in years]):.0f} | {np.median([res[y]["social"]["shape"] for y in years]):.0f}')
    json.dump({str(y): {'gates': {k: {g: list(t) for g, t in d.items()} for k, d in r['gates'].items()}, 'social': r['social']}
               for y, r in res.items()}, open(OUT + '.tmp', 'w'), indent=1)
    os.replace(OUT + '.tmp', OUT)


if __name__ == '__main__':
    main()
