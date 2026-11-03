#!/usr/bin/env python3
"""Free three-outfielder placement: most combined catch probability, and does
it hold up on held-out seasons?

Objective: expected outs = sum over the batter's LD + FB past the dirt of the
best catch probability among LF, CF and RF (spray_advance_report.out_prob_matrix,
the official Statcast catch surface). Each outfielder may stand anywhere on a
10 ft grid past the dirt and at least 10 ft inside the reference fence; the
search fits on SMOOTHED balls (each ball a Gaussian cloud, bandwidth by
leave-one-out likelihood, as the chart's shift fit does), by best response
from many starts, then refines each fielder on a 2.5 ft grid.

Gate, per pitcher hand, leaving one season out: the free fit against the
chart's current optimum fitted on the same seasons (the smoothed 2-number
shift) and against the teams' fixed spots against the batter, all scored on
the held-out season's RAW balls. A one-season free fit lost to real
positioning 6/6 on 2026 halves (memory: of-alignment-overfit-2026-10).

Usage (from the repo root):
    python3 scripts/research/fielding/of_free_gate.py --csv ~/Downloads/savant_data.csv \
        --seasons 2024 2025 2026 --batter-id 695578
"""
import argparse
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'tools'))
import catch_grid  # noqa: E402
import hang_time  # noqa: E402
import spray_advance_report as sar  # noqa: E402
from runner_state_gate import of_keep  # noqa: E402

STARTS = 60


def candidates(step):
    pts = []
    for x in np.arange(-330, 331, step):
        for y in np.arange(150, 431, step):
            th = math.atan2(x, y)
            r = math.hypot(x, y)
            if abs(th) <= math.radians(45) and sar.dirt_arc_r(th) + 10 <= r <= 330 + 70 * math.cos(2 * th) - 10:
                pts.append((x, y))
    return np.array(pts, float)


def ball_probs(cand, balls, grid, smooth_h=None, seed=0):
    """[candidate, ball] catch probability; averaged over smoothing draws."""
    n = len(balls[0])
    if smooth_h is None:
        return sar.out_prob_matrix(cand, balls, grid)
    sb = sar.smooth(balls, smooth_h, np.random.default_rng(seed))
    out = np.empty((len(cand), n))
    for i in range(0, len(cand), 100):
        out[i:i + 100] = sar.out_prob_matrix(cand[i:i + 100], sb, grid).reshape(-1, n, sar.M_JITTER).mean(2)
    return out


def best_three(P, rng, seeds=()):
    m = P.shape[0]
    best = (-1.0, None)
    inits = [list(s) for s in seeds] + [list(rng.choice(m, 3, replace=False)) for _ in range(STARTS)]
    for idx in inits:
        for _ in range(50):
            moved = False
            for j in range(3):
                others = P[[idx[k] for k in range(3) if k != j]].max(0)
                v = np.maximum(P, others[None]).sum(1)
                b = int(np.argmax(v))
                if v[b] > v[idx[j]] + 1e-9:
                    idx[j], moved = b, True
            if not moved:
                break
        val = float(P[idx].max(0).sum())
        if val > best[0]:
            best = (val, list(idx))
    return best


def fit_free(balls, grid, rng):
    h, _ = sar.pick(sar.AIR_BW_GRID, sar.loo_2d(np.column_stack(balls[:2]), sar.AIR_BW_GRID))
    coarse = candidates(10)
    P = ball_probs(coarse, balls, grid, h)
    _v, idx = best_three(P, rng)
    spots = coarse[idx]
    # refine each fielder on a 2.5 ft grid within 10 ft, others fixed, twice
    for _ in range(2):
        for j in range(3):
            c = spots[j]
            local = np.array([(c[0] + dx, c[1] + dy) for dx in np.arange(-10, 10.1, 2.5)
                              for dy in np.arange(-10, 10.1, 2.5)])
            Pl = ball_probs(local, balls, grid, h)
            Po = ball_probs(np.delete(spots, j, 0), balls, grid, h).max(0)
            spots[j] = local[int(np.argmax(np.maximum(Pl, Po[None]).sum(1)))]
    return spots[np.argsort(spots[:, 0])], h


def score(spots, balls, grid):
    return float(sar.out_prob_matrix(np.asarray(spots), balls, grid).max(0).sum())


def team_of(batter_id, seasons):
    with open(os.path.join(sar.REPO, 'data', f'_positioning_{batter_id}.json')) as f:
        rows = [r for r in json.load(f) if r['season'] in seasons]
    return np.array([np.array([[float(r['start_pos_x']), float(r['start_pos_y'])]
                               for r in rows if int(r['pos_id']) == p]).mean(0) for p in (7, 8, 9)])


def fmt(spots):
    return '  '.join(f'{k} {math.degrees(math.atan2(*p)):.1f}/{math.hypot(*p):.0f}'
                     for k, p in zip(('LF', 'CF', 'RF'), spots))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--csv', required=True)
    ap.add_argument('--seasons', type=int, nargs='+', required=True)
    ap.add_argument('--batter-id', type=int, required=True)
    args = ap.parse_args()
    rows, _d, _r = sar.load(None, args.csv, args.seasons)
    tracked = sar.load_tracked(args.seasons)
    hmodel, *_ = hang_time.fit(args.seasons, exclude=args.batter_id)
    grid, _ = catch_grid.fill(catch_grid.build())
    teams = team_of(args.batter_id, args.seasons)
    rng = np.random.default_rng(0)
    seasons = sorted({r['date'][:4] for r in rows})
    from of_pitchgroup_gate import fit as shift_fit
    for hand, sub in (('Total', rows), ('vs RHP', [r for r in rows if r['throws'] == 'R']),
                      ('vs LHP', [r for r in rows if r['throws'] == 'L'])):
        k = of_keep(sub)
        allb, _ = sar.of_balls(k, tracked, hmodel)
        full, h = fit_free(allb, grid, rng)
        print(f'\n{hand}: free fit on all {len(allb[0])} balls (bw {h:g} ft): {fmt(full)}')
        print(f'   in-sample expected outs: free {score(full, allb, grid):.1f}  teams {score(teams, allb, grid):.1f}')
        w_shift = w_teams = 0
        tot = {'free': 0.0, 'shift': 0.0, 'teams': 0.0}
        for s in seasons:
            tr = [r for r in k if r['date'][:4] != s]
            te = [r for r in k if r['date'][:4] == s]
            fb, _ = sar.of_balls(tr, tracked, hmodel)
            eb, _ = sar.of_balls(te, tracked, hmodel)
            free, _h = fit_free(fb, grid, rng)
            sp, sd = shift_fit(tr, tracked, hmodel, grid)
            vf, vs, vt = score(free, eb, grid), score(sar.positions(sp, sd), eb, grid), score(teams, eb, grid)
            w_shift += vf > vs; w_teams += vf > vt
            tot['free'] += vf; tot['shift'] += vs; tot['teams'] += vt
            print(f'   held-out {s} (n={len(eb[0])}): free {vf:.1f}  shift {vs:.1f}  teams {vt:.1f}   free fit: {fmt(free)}')
        print(f'   free beats shift {w_shift}/{len(seasons)}, beats teams {w_teams}/{len(seasons)}; '
              f'totals free {tot["free"]:.1f}  shift {tot["shift"]:.1f}  teams {tot["teams"]:.1f}')


if __name__ == '__main__':
    main()
