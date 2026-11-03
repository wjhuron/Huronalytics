#!/usr/bin/env python3
"""Out-of-sample gate for a shifted standard outfield, one hitter-season.

Base alignment: where a normal outfielder plays, measured from the 2026
range plays (play-weighted season-average start positions, all hitters):
LF -28.5 deg / 295 ft, CF -1.1 / 319, RF 26.4 / 289. Wally's first rule,
CF over second and the corners halfway to the lines (+-22.5), scored 4.5
expected outs worse on Wood's 89 tracked balls (67.8 vs 72.3 of 77.0
official): real corner outfielders play nearer the lines.

The fit moves the whole outfield with TWO numbers only: a rotation phi (deg,
positive = toward right field) and a depth change delta (ft, all three).
phi is bounded so no fielder starts past a foul line; a fielder
past the reference fence minus 10 ft makes the alignment invalid. The
objective is expected outs on the official catch surface (see
scripts/tools/spray_advance_report.py for the ball set and timing).

Variants:
    A  shift fitted on the raw balls of the fitting half
    B  shift fitted on SMOOTHED balls: each ball is a Gaussian cloud of
       M_JITTER draws around its landing spot, bandwidth by leave-one-out
       likelihood on the fitting half's own balls; timing and wall weight
       are the ball's own
Both are scored on the RAW balls of the other half.

Baselines on the scoring half:
    standard   phi = 0, delta = 0, same objective
    real       Savant's official catch_rate from the fielders' real start
               positions. It exists only for tracked balls, so the clean
               comparison is on tracked balls; on untracked balls real
               outfielders made 0 outs (every untracked out was an
               infielder's lineout), which the 'all balls' line uses.

Splits: with several seasons, leave one season out (fit on the others,
score the held-out season), the independent-replicate test; with one
season, halves by date, both ways.

Pass: a variant wins most held-out splits against both baselines, per panel.

Usage (from the repo root):
    python3 scripts/research/fielding/of_shift_gate.py --batter "Wood, James"
    python3 scripts/research/fielding/of_shift_gate.py --csv ~/Downloads/savant_data.csv \
        --seasons 2024 2025 2026
"""
import argparse
import math
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'tools'))
import catch_grid  # noqa: E402
import hang_time  # noqa: E402
import spray_advance_report as sar  # noqa: E402

BASE_ANG, BASE_DEPTH = sar.BASE_ANG, sar.BASE_DEPTH     # one home: spray_advance_report
PHI_GRID, DELTA_GRID = sar.PHI_GRID, sar.DELTA_GRID


positions = sar.positions


def score_grid(balls, grid, weights=None):
    """Expected outs for every (phi, delta); NaN where invalid."""
    v = np.full((len(PHI_GRID), len(DELTA_GRID)), np.nan)
    for i, phi in enumerate(PHI_GRID):
        for j, d in enumerate(DELTA_GRID):
            pos = positions(phi, d)
            if pos is None:
                continue
            p = sar.out_prob_matrix(pos, balls, grid).max(0)
            v[i, j] = (p * weights).sum() if weights is not None else p.sum()
    return v


def argmax(v):
    i, j = np.unravel_index(np.nanargmax(v), v.shape)
    edge = []
    if i in (0, len(PHI_GRID) - 1):
        edge.append('phi at foul-line bound')
    if j in (0, len(DELTA_GRID) - 1) or np.isnan(v[i, max(j - 1, 0)]) or np.isnan(v[i, min(j + 1, v.shape[1] - 1)]):
        edge.append('delta at grid/fence edge')
    return PHI_GRID[i], DELTA_GRID[j], ', '.join(edge) or 'interior'


def smooth(balls, h, rng):
    """Same draws as the chart's fit: per-ball weight 1 / M_JITTER."""
    sb = sar.smooth(balls, h, rng)
    return sb, np.full(len(sb[0]), 1.0 / sar.M_JITTER)


def at(balls, grid, phi, d):
    return sar.out_prob_matrix(positions(phi, d), balls, grid).max(0)


def splits(rows):
    """(name, fit rows, score rows). Several seasons: leave one season out,
    the independent-replicate test. One season: halves by date, both ways."""
    seasons = sorted({r['date'][:4] for r in rows})
    if len(seasons) > 1:
        return [(f'fit {"+".join(x for x in seasons if x != s)} -> score {s}',
                 [r for r in rows if r['date'][:4] != s], [r for r in rows if r['date'][:4] == s])
                for s in seasons]
    ds = sorted(r['date'] for r in rows)
    cut = ds[len(ds) // 2]
    h = [[r for r in rows if r['date'] < cut], [r for r in rows if r['date'] >= cut]]
    return [('fit H1 -> score H2', h[0], h[1]), ('fit H2 -> score H1', h[1], h[0])]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--batter', help='Sheets name, "Last, First"')
    src.add_argument('--csv', help='Baseball Savant search CSV for one batter')
    ap.add_argument('--seasons', type=int, nargs='+', default=[2026])
    args = ap.parse_args()

    rows, _d, _r = sar.load(args.batter, args.csv, args.seasons)
    tracked = sar.load_tracked(args.seasons)
    ids = {tracked[r['pitch_id']]['batter_id'] for r in rows if r['pitch_id'] in tracked}
    hmodel, *_ = hang_time.fit(args.seasons, exclude=ids.pop())
    grid, _ = catch_grid.fill(catch_grid.build())
    rng = np.random.default_rng(0)

    def keep(sub):
        return [r for r in sub if r['key'] in ('line_drive', 'fly_ball') and r['event'] != 'Home Run'
                and math.hypot(r['x'], r['y']) > sar.dirt_arc_r(math.atan2(r['x'], r['y']))]

    print(f'grid: phi {PHI_GRID[0]}..{PHI_GRID[-1]} by 1.5 deg, delta {DELTA_GRID[0]}..{DELTA_GRID[-1]} by 5 ft')
    tally = {}
    for lab, sub in (('Total', rows), ('vs RHP', [r for r in rows if r['throws'] == 'R']),
                     ('vs LHP', [r for r in rows if r['throws'] == 'L'])):
        for name, fit_rows, score_rows in splits(keep(sub)):
            fb, _ = sar.of_balls(fit_rows, tracked, hmodel)
            eb, src_ = sar.of_balls(score_rows, tracked, hmodel)
            t = np.array([s == 'tracked' for s in src_])
            real_t = sum(float(tracked[r['pitch_id']]['catch_rate']) for r in score_rows
                         if r['pitch_id'] in tracked)

            vA = score_grid(fb, grid)
            pA, dA, eA = argmax(vA)
            xy = np.column_stack(fb[:2])
            h, hw = sar.pick(sar.AIR_BW_GRID, sar.loo_2d(xy, sar.AIR_BW_GRID))
            sb, sw = smooth(fb, h, rng)
            vB = score_grid(sb, grid, sw)
            pB, dB, eB = argmax(vB)

            std = at(eb, grid, 0, 0)
            sA, sB = at(eb, grid, pA, dA), at(eb, grid, pB, dB)
            print(f'{lab:7s} {name}  fit n={len(fb[0])}  score n={len(t)} ({t.sum()} tracked)  '
                  f'smoothing bw {h:g} ft ({hw})')
            print(f'    A raw:    phi {pA:+5.1f}  delta {dA:+4.0f}  [{eA}]')
            print(f'    B smooth: phi {pB:+5.1f}  delta {dB:+4.0f}  [{eB}]')
            print(f'    tracked balls: real {real_t:5.1f}  standard {std[t].sum():5.1f}  A {sA[t].sum():5.1f}  B {sB[t].sum():5.1f}')
            print(f'    all balls:     real {real_t:5.1f}  standard {std.sum():5.1f}  A {sA.sum():5.1f}  B {sB.sum():5.1f}')
            for v, val in (('A', sA), ('B', sB)):
                tally.setdefault((lab, v), []).append(
                    (val.sum() > std.sum(), val[t].sum() > real_t, val.sum() > real_t))
    print('\nwins per panel (vs standard all balls / vs real tracked / vs real all balls):')
    for (lab, v), w in tally.items():
        n = len(w)
        print(f'  {lab:7s} {v}: {sum(x[0] for x in w)}/{n}  {sum(x[1] for x in w)}/{n}  {sum(x[2] for x in w)}/{n}')


if __name__ == '__main__':
    main()
