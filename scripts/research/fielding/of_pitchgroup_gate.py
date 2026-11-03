#!/usr/bin/env python3
"""Does conditioning the outfield shift on PITCH GROUP beat the hand-only shift?

A per-pitcher alignment against one batter has almost no direct data (Wood
has seen no Phillies pitcher more than 6 times in a season), so it must come
from the pitcher's pitch mix applied to the batter's tendencies by pitch
group. That only helps if the batter's air balls move with the pitch group
in a way that survives out of sample. This tests the extreme case: one shift
per (pitcher hand, pitch group), fitted on the other seasons, scored on the
held-out season's balls of that group, against the hand-only shift fitted on
the same seasons and the unshifted normal outfield.

Groups (a convention): Hard = FF, SI; Breaking = FC, SL, ST, CU, KC, SV;
Offspeed = CH, FS, FO. FC sits with Breaking because Wood's air balls off
cutters average -4 deg against RHP, beside breaking balls (-2), not
four-seamers (-9). A group with no fitting balls falls back to the hand fit.

Fits are the chart's: the 2-number shift of the measured normal outfield on
smoothed balls (spray_advance_report.smoothed_tab, seed 0).

Usage (from the repo root):
    python3 scripts/research/fielding/of_pitchgroup_gate.py \
        --csv ~/Downloads/savant_data.csv --seasons 2024 2025 2026
"""
import argparse
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'tools'))
import catch_grid  # noqa: E402
import hang_time  # noqa: E402
import spray_advance_report as sar  # noqa: E402

GROUPS = {'FF': 'Hard', 'SI': 'Hard',
          'FC': 'Breaking', 'SL': 'Breaking', 'ST': 'Breaking', 'CU': 'Breaking',
          'KC': 'Breaking', 'SV': 'Breaking',
          'CH': 'Offspeed', 'FS': 'Offspeed', 'FO': 'Offspeed'}


def keep(sub):
    return [r for r in sub if r['key'] in ('line_drive', 'fly_ball') and r['event'] != 'Home Run'
            and math.hypot(r['x'], r['y']) > sar.dirt_arc_r(math.atan2(r['x'], r['y']))
            and GROUPS.get(r['ptype'])]


def fit(rows, tracked, hmodel, grid):
    balls, _ = sar.of_balls(rows, tracked, hmodel)
    tab, _h = sar.smoothed_tab(balls, grid)
    phi, delta, _w = sar.best_shift(tab.sum(2))
    return phi, delta


def score(rows, tracked, hmodel, grid, phi, delta):
    if not rows:
        return 0.0
    balls, _ = sar.of_balls(rows, tracked, hmodel)
    return float(sar.out_prob_matrix(sar.positions(phi, delta), balls, grid).max(0).sum())


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
        k = keep([r for r in rows if r['throws'] == hand])
        print(f'\nvs {hand}HP: ' + ', '.join(
            f'{g} {sum(GROUPS[r["ptype"]] == g for r in k)}' for g in ('Hard', 'Breaking', 'Offspeed'))
            + ' air balls')
        tot = {'normal': 0.0, 'hand': 0.0, 'group': 0.0}
        wins_hand = wins_normal = 0
        for s in seasons:
            tr = [r for r in k if r['date'][:4] != s]
            te = [r for r in k if r['date'][:4] == s]
            hp, hd = fit(tr, tracked, hmodel, grid)
            v_norm = score(te, tracked, hmodel, grid, 0.0, 0.0)
            v_hand = score(te, tracked, hmodel, grid, hp, hd)
            v_grp, parts = 0.0, []
            for g in ('Hard', 'Breaking', 'Offspeed'):
                trg = [r for r in tr if GROUPS[r['ptype']] == g]
                teg = [r for r in te if GROUPS[r['ptype']] == g]
                gp, gd = fit(trg, tracked, hmodel, grid) if trg else (hp, hd)
                v = score(teg, tracked, hmodel, grid, gp, gd)
                v_grp += v
                parts.append(f'{g} ({gp:+.1f}, {gd:+.0f}) n={len(teg)} '
                             f'{v:.1f} vs hand {score(teg, tracked, hmodel, grid, hp, hd):.1f}')
            wins_hand += v_grp > v_hand
            wins_normal += v_grp > v_norm
            for key, v in (('normal', v_norm), ('hand', v_hand), ('group', v_grp)):
                tot[key] += v
            print(f'  held-out {s} (n={len(te)}): normal {v_norm:.1f}  hand ({hp:+.1f}, {hd:+.0f}) '
                  f'{v_hand:.1f}  group {v_grp:.1f}')
            for line in parts:
                print('      ' + line)
        n = len(seasons)
        print(f'  group beats hand {wins_hand}/{n}, beats normal {wins_normal}/{n};  '
              f'totals normal {tot["normal"]:.1f}  hand {tot["hand"]:.1f}  group {tot["group"]:.1f}')


if __name__ == '__main__':
    main()
