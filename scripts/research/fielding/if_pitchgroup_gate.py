#!/usr/bin/env python3
"""Does conditioning the INFIELD on pitch group beat the hand-only infield?

The infield twin of of_pitchgroup_gate.py. Spots and objective are the
chart's (spray_advance_report.infield_spots): two infielders per side of
second base, at the angles with the smallest mean absolute angle from a
grounder to the nearest infielder, solved exactly. No infield catch surface
exists, so held-out grounders are scored on that same objective: mean angle
(deg) to the nearest of the four fielders, LOWER is better.

Per held-out season and pitcher hand, three fits on the other seasons:
    total   all grounders, both hands (what every chart panel draws now)
    hand    grounders against that hand
    group   one infield per pitch group against that hand; each held-out
            grounder is scored by its own group's infield. A group with
            fewer than two fitting grounders on a side of second base cannot
            be fitted and falls back to the hand infield (counted).
Groups are of_pitchgroup_gate.GROUPS.

Pass: group beats both total and hand in most held-out seasons, per hand.

Result, Wood 2024-2026 (2026-10-27, after the exact constrained fit
replaced the split-at-second-base fit): FAILS for both hands. vs RHP group
beats hand 0/3 (pooled mean 6.13 deg vs hand 5.58, total 5.63); vs LHP 1/3
(6.05 vs 5.63 / 5.62). An earlier 3/3 'pass' against RHP was an artifact of
the old fit. Hand vs total is flat (within 0.05 deg pooled, hand 2/3 per
hand), so one infield serves every pitcher.

Usage (from the repo root):
    python3 scripts/research/fielding/if_pitchgroup_gate.py \
        --csv ~/Downloads/savant_data.csv --seasons 2024 2025 2026
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'tools'))
import spray_advance_report as sar  # noqa: E402
from of_pitchgroup_gate import GROUPS  # noqa: E402


def fittable(angs):
    return len(angs) >= 4


def cost(angs, spots):
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
    gb = [r for r in rows if r['key'] == 'ground_ball' and GROUPS.get(r['ptype'])]
    seasons = sorted({r['date'][:4] for r in gb})
    ang = lambda rs: np.array([r['ang'] for r in rs])

    for hand in ('R', 'L'):
        h = [r for r in gb if r['throws'] == hand]
        print(f'\nvs {hand}HP grounders: ' + ', '.join(
            f'{g} {sum(GROUPS[r["ptype"]] == g for r in h)}' for g in ('Hard', 'Breaking', 'Offspeed')))
        w_total = w_hand = 0
        sums = {'total': 0.0, 'hand': 0.0, 'group': 0.0}
        n_all = 0
        for s in seasons:
            tr_all = [r for r in gb if r['date'][:4] != s]
            tr = [r for r in h if r['date'][:4] != s]
            te = [r for r in h if r['date'][:4] == s]
            sp_total = sar.infield_spots(ang(tr_all))
            sp_hand = sar.infield_spots(ang(tr))
            c_total, c_hand = cost(ang(te), sp_total), cost(ang(te), sp_hand)
            c_group, parts = 0.0, []
            for g in ('Hard', 'Breaking', 'Offspeed'):
                a = ang([r for r in tr if GROUPS[r['ptype']] == g])
                teg = ang([r for r in te if GROUPS[r['ptype']] == g])
                sp = sar.infield_spots(a) if fittable(a) else sp_hand
                c = cost(teg, sp)
                c_group += c
                parts.append(f'{g:8s} n={len(teg):3d}  fit '
                             + ' '.join(f'{k} {v:+.0f}' for k, v in sp.items())
                             + ('' if fittable(a) else ' (hand fallback)')
                             + f'   mean {c / max(len(teg), 1):.2f} vs hand {cost(teg, sp_hand) / max(len(teg), 1):.2f}')
            n = len(te)
            n_all += n
            w_total += c_group < c_total
            w_hand += c_group < c_hand
            for k, v in (('total', c_total), ('hand', c_hand), ('group', c_group)):
                sums[k] += v
            print(f'  held-out {s} (n={n}): mean deg  total {c_total / n:.2f}  hand {c_hand / n:.2f}  '
                  f'group {c_group / n:.2f}')
            for line in parts:
                print('      ' + line)
        k = len(seasons)
        print(f'  group beats total {w_total}/{k}, beats hand {w_hand}/{k};  pooled mean deg  '
              f'total {sums["total"] / n_all:.3f}  hand {sums["hand"] / n_all:.3f}  '
              f'group {sums["group"] / n_all:.3f}')


if __name__ == '__main__':
    main()
