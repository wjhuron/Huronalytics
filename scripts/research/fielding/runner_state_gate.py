#!/usr/bin/env python3
"""Does conditioning the alignment on RUNNER STATE beat the hand-only one?

The runner-state twin of of_pitchgroup_gate.py and if_pitchgroup_gate.py.
Runner states are Savant's positioning groups: bases empty, runner on first
only, other (any runner on second or third). Per pitcher hand and held-out
season, fit on the other seasons:
    outfield   one smoothed 2-number shift per runner state vs the hand shift
               (expected outs on the held-out balls, higher is better)
    infield    one exact 4-median infield per runner state vs the hand
               infield (mean angle to the nearest infielder, lower is better)
Each held-out ball is scored by its own state's alignment. A state with too
few fitting balls falls back to the hand fit.

This tests the batter's SPRAY by runner state only. Runner states also bring
game constraints the scores do not model (the first baseman holds a runner,
double-play depth, the infield in), which apply whatever the spray says.

Usage (from the repo root):
    python3 scripts/research/fielding/runner_state_gate.py \
        --csv ~/Downloads/savant_data.csv --seasons 2024 2025 2026
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'tools'))
import catch_grid  # noqa: E402
import hang_time  # noqa: E402
import spray_advance_report as sar  # noqa: E402
from of_pitchgroup_gate import fit as of_fit, score as of_score  # noqa: E402

STATES = ('empty', '1b', 'other')


def of_keep(sub):
    import math
    return [r for r in sub if r['key'] in ('line_drive', 'fly_ball') and r['event'] != 'Home Run'
            and math.hypot(r['x'], r['y']) > sar.dirt_arc_r(math.atan2(r['x'], r['y']))]


def if_cost(angs, spots):
    if len(angs) == 0:
        return 0.0
    s = np.array(list(spots.values()))
    return float(np.abs(angs[:, None] - s[None]).min(1).sum())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--csv', required=True)
    ap.add_argument('--seasons', type=int, nargs='+', required=True)
    args = ap.parse_args()

    rows, _d, _r = sar.load(None, args.csv, args.seasons)
    tracked = sar.load_tracked(args.seasons)
    ids = {tracked[r['pitch_id']]['batter_id'] for r in rows if r['pitch_id'] in tracked}
    hmodel, *_ = hang_time.fit(args.seasons, exclude=ids.pop())
    grid, _ = catch_grid.fill(catch_grid.build())
    seasons = sorted({r['date'][:4] for r in rows})

    for hand in ('R', 'L'):
        h = [r for r in rows if r['throws'] == hand]
        # ---- outfield ----
        k = of_keep(h)
        print(f'\nvs {hand}HP outfield: ' + ', '.join(f'{st} {sum(r["runners"] == st for r in k)}' for st in STATES))
        w = 0
        tot = {'hand': 0.0, 'state': 0.0, 'normal': 0.0}
        for s in seasons:
            tr = [r for r in k if r['date'][:4] != s]
            te = [r for r in k if r['date'][:4] == s]
            hp, hd = of_fit(tr, tracked, hmodel, grid)
            v_hand = of_score(te, tracked, hmodel, grid, hp, hd)
            v_norm = of_score(te, tracked, hmodel, grid, 0.0, 0.0)
            v_state, parts = 0.0, []
            for st in STATES:
                trs = [r for r in tr if r['runners'] == st]
                tes = [r for r in te if r['runners'] == st]
                sp, sd = of_fit(trs, tracked, hmodel, grid) if len(trs) >= 4 else (hp, hd)
                v = of_score(tes, tracked, hmodel, grid, sp, sd)
                v_state += v
                parts.append(f'{st} ({sp:+.1f}, {sd:+.0f}) n={len(tes)} {v:.1f} vs hand '
                             f'{of_score(tes, tracked, hmodel, grid, hp, hd):.1f}')
            w += v_state > v_hand
            tot['hand'] += v_hand; tot['state'] += v_state; tot['normal'] += v_norm
            print(f'  held-out {s} (n={len(te)}): normal {v_norm:.1f}  hand ({hp:+.1f}, {hd:+.0f}) {v_hand:.1f}  '
                  f'state {v_state:.1f}   [' + '; '.join(parts) + ']')
        print(f'  outfield: state beats hand {w}/{len(seasons)}; totals normal {tot["normal"]:.1f}  '
              f'hand {tot["hand"]:.1f}  state {tot["state"]:.1f}')
        # ---- infield ----
        gb = [r for r in h if r['key'] == 'ground_ball']
        print(f'vs {hand}HP infield: ' + ', '.join(f'{st} {sum(r["runners"] == st for r in gb)}' for st in STATES))
        w = 0
        tot = {'hand': 0.0, 'state': 0.0, 'n': 0}
        for s in seasons:
            tr = [r for r in gb if r['date'][:4] != s]
            te = [r for r in gb if r['date'][:4] == s]
            ang = lambda rs: np.array([r['ang'] for r in rs])
            sp_hand = sar.infield_spots(ang(tr))
            c_hand = if_cost(ang(te), sp_hand)
            c_state = 0.0
            for st in STATES:
                a = ang([r for r in tr if r['runners'] == st])
                sp = sar.infield_spots(a) if len(a) >= 4 else sp_hand
                c_state += if_cost(ang([r for r in te if r['runners'] == st]), sp)
            w += c_state < c_hand
            tot['hand'] += c_hand; tot['state'] += c_state; tot['n'] += len(te)
            print(f'  held-out {s} (n={len(te)}): mean deg hand {c_hand / len(te):.2f}  state {c_state / len(te):.2f}')
        print(f'  infield: state beats hand {w}/{len(seasons)}; pooled mean deg hand '
              f'{tot["hand"] / tot["n"]:.3f}  state {tot["state"] / tot["n"]:.3f}')


if __name__ == '__main__':
    main()
