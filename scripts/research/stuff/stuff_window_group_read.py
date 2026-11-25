#!/usr/bin/env python3
"""stuff_window_group_read.py — read the training-window and pitch-group arms of
stuff_gate_v2_ext.py, each against the baseline that isolates its question.

Question 1 (window): does a Stuff+ model trained on fewer, nearer seasons grade better?
  NEAR2 / NEAR3 / REC08 / REC06   against SHIPPED (every season but Y and Y+1)
  PAST                             against SHIPPED (cost of having no later season)
  PAST_D1 / PAST_D2                against PAST    (oldest one / two seasons removed)
  PAST_R1 / PAST_R2                against PAST    (the same number of rows, at random)
  PAST_D1 - PAST_R1, D2 - R2       the window effect with the sample size held equal
Question 2 (groups): do separate models for pitch groups grade better?
  GRP2 / GRP3                      against SHIPPED
Question 3 (target): does a chain of outcome models grade better than one run-value model?
  CHAIN / CHAIN_MIX / CHAIN_CNT    against SHIPPED

Reads are the ext summary's own (stuff_gate_ext_summary.compare): pool 'gate' (300 pitches in
Y and Y+1) and 'free' (300 in Y, weighted by Y+1 pitches), pooled / within hand / within role,
raw and rendered, luck-neutral and actual run value, and next-season r by pitch type. The
count-neutral target is NOT read here: the 2026 sidecar predates the stored 2026 frame.
SEED rows are SHIPPED seed 1 and 2 against seed 0: a delta inside that spread is not a result.

  .venv/bin/python scripts/research/stuff/stuff_window_group_read.py [seed]
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stuff_gate_v2 as G  # noqa: E402
import stuff_gate_v2_ext as E  # noqa: E402
import stuff_gate_ext_summary as S  # noqa: E402

PAIRS = (2021, 2022, 2023, 2024, 2025)
COLS = [('gate raw', 'gate:pooled:raw:t'), ('free raw', 'free:pooled:raw:t'), ('free rend', 'free:pooled:rend:t'),
        ('free raw rv', 'free:pooled:raw:rv'), ('in hand', 'free:hand:raw:t'), ('in role', 'free:role:raw:t'),
        ('in hand rend', 'free:hand:rend:t'), ('in role rend', 'free:role:rend:t')]


def read(pa, pb, hm, rm, rng):
    """arm path function pa against baseline path function pb, over the pairs both have."""
    per = {}
    for y in PAIRS:
        if os.path.exists(pa(y)) and os.path.exists(pb(y)):
            # compare() drops a pitcher with no count-neutral target, so it needs the series even
            # though this tool does not read that column. Any ext aggregate of the pair has it.
            tcn = pd.read_pickle(E.agg_path('NEAR3', y, 0))['py1x']['tcn']
            per[y] = S.compare(pd.read_pickle(pa(y)), pd.read_pickle(pb(y)), y, tcn, hm[y], rm[y + 1], rng)
    if not per:
        return None
    r = {'pairs': sorted(per), 'by_pair': {y: {k: per[y][k][1] for k, _ in [(c[1], 0) for c in COLS] if k in per[y]} for y in per}}
    for k in set().union(*[set(v) for v in per.values()]):
        vs = [per[y][k] for y in per if k in per[y]]
        r[k] = {'base': float(np.mean([v[0] for v in vs])), 'd': float(np.mean([v[1] for v in vs])),
                'se': float(np.sqrt(sum(v[2] ** 2 for v in vs)) / len(vs)), 'pos': int(sum(v[1] > 0 for v in vs)), 'n': len(vs)}
    return r


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    hm, rm = G.hand_map(), G.role_map()
    rng = np.random.default_rng(0)
    ext = lambda a: (lambda y: E.agg_path(a, y, seed))
    ship = lambda s: (lambda y: G.agg_path('SHIPPED', y, s))
    plan = [('SEED1', ship(1), ship(0)), ('SEED2', ship(2), ship(0))]
    plan += [(f'{a} - SHIPPED', ext(a), ship(seed)) for a in ('NEAR2', 'NEAR3', 'REC08', 'REC06', 'PAST', 'GRP2', 'GRP3',
                                                                 'CHAIN', 'CHAIN_MIX', 'CHAIN_CNT')]
    plan += [(f'{a} - PAST', ext(a), ext('PAST')) for a in ('PAST_D1', 'PAST_R1', 'PAST_D2', 'PAST_R2')]
    plan += [('PAST_D1 - PAST_R1', ext('PAST_D1'), ext('PAST_R1')), ('PAST_D2 - PAST_R2', ext('PAST_D2'), ext('PAST_R2'))]
    res = {}
    for name, pa, pb in plan:
        r = read(pa, pb, hm, rm, rng)
        if r:
            res[name] = r
    f = lambda r, k: (f"{r[k]['d']:+.4f} ({r[k]['se']:.4f}) {r[k]['pos']}/{r[k]['n']}" if k in r else '')
    print(f'seed {seed}. arm minus baseline, next-season r, mean of pairs (paired bootstrap SE), pairs positive')
    print(f'{"read":<20s}{"pairs":>16s} | ' + ' '.join(f'{c[0]:>21s}' for c in COLS))
    for name, r in res.items():
        print(f'{name:<20s}{",".join(str(y)[2:] for y in r["pairs"]):>16s} | ' + ' '.join(f'{f(r, c[1]):>21s}' for c in COLS))
    print('\nbaseline level (mean of its pairs): ' + '  '.join(
        f'{n}: gate raw {r["gate:pooled:raw:t"]["base"]:.3f}, free raw {r["free:pooled:raw:t"]["base"]:.3f}'
        for n, r in res.items() if n in ('NEAR2 - SHIPPED', 'PAST_D1 - PAST')))
    print('\nby pair, free raw (luck-neutral):')
    for name, r in res.items():
        print(f'{name:<20s}' + ' '.join(f'{y}: {r["by_pair"][y].get("free:pooled:raw:t", float("nan")):+.4f}' for y in r['pairs']))
    print('\nnext-season r by pitch type: baseline level, then arm minus baseline (SE)')
    print(f'{"read":<20s}' + ''.join(f'{pt:>17s}' for pt in S.TYPES))
    for name, r in res.items():
        print(f'{name:<20s}' + ''.join((f'{r["type:" + pt]["d"]:>+9.3f} ({r["type:" + pt]["se"]:.3f})' if f'type:{pt}' in r else f'{"":>17s}')
                                       for pt in S.TYPES))
    lv = res.get('NEAR2 - SHIPPED') or next(iter(res.values()))
    print(f'{"SHIPPED level":<20s}' + ''.join(f'{lv.get("type:" + pt, {}).get("base", float("nan")):>17.3f}' for pt in S.TYPES))
    out = os.path.join(E.EXT, f'window_group_read_s{seed}.json')
    json.dump(res, open(out, 'w'), indent=1, default=float)
    print(f'\nwrote {out}')


if __name__ == '__main__':
    main()
