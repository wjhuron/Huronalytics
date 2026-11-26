#!/usr/bin/env python3
"""stuff_vsplit_read.py — read the velocity-split gate arms (2026-11-25).

Arms (stuff_gate_v2_ext.py): VSPLIT and VMEAN_ADD against the gate's SHIPPED,
IDENT3_VSPLIT and IDENT3_VMEAN_ADD against IDENT3 (pitcher identity removed from
both sides). Every comparison is paired on the same seed; the table shows the
mean over pairs and seeds, the pitcher-bootstrap SE (mean of the per-seed SEs,
because the seeds share the pitchers), the spread of the per-seed means, and
the count of positive (pair, seed) cells.

  .venv/bin/python scripts/research/stuff/stuff_vsplit_read.py
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stuff_gate_v2 as G  # noqa: E402
import stuff_gate_v2_ext as E  # noqa: E402
import stuff_gate_ext_summary as S  # noqa: E402

PAIRS = (2021, 2022, 2023, 2024, 2025)
SEEDS = (0, 1, 2)
ship = lambda y, s: G.agg_path('SHIPPED', y, s)
ext = lambda a: (lambda y, s: E.agg_path(a, y, s))
COMPS = [('VS_CTRL', ext('VS_CTRL'), 'SHIPPED', ship),
         ('VSPLIT', ext('VSPLIT'), 'SHIPPED', ship),
         ('VMEAN_ADD', ext('VMEAN_ADD'), 'SHIPPED', ship),
         ('IDENT3', ext('IDENT3'), 'SHIPPED', ship),
         ('IDENT3_VSPLIT', ext('IDENT3_VSPLIT'), 'IDENT3', ext('IDENT3')),
         ('IDENT3_VMEAN_ADD', ext('IDENT3_VMEAN_ADD'), 'IDENT3', ext('IDENT3'))]
COLS = [('gate raw', 'gate:pooled:raw:t'), ('gate rend', 'gate:pooled:rend:t'),
        ('free raw', 'free:pooled:raw:t'), ('free rend', 'free:pooled:rend:t'),
        ('free in hand', 'free:hand:raw:t'), ('free in role', 'free:role:raw:t'),
        ('free actual RV', 'free:pooled:raw:rv')] + [(f'type {pt}', f'type:{pt}') for pt in S.TYPES]


def main():
    hm, rm = G.hand_map(), G.role_map()
    for arm, pa, base, pb in COMPS:
        cell = {}                      # key -> {seed: [(base r, d, se) per pair]}
        for s in SEEDS:
            rng = np.random.default_rng(100 + s)
            for y in PAIRS:
                if not (os.path.exists(pa(y, s)) and os.path.exists(pb(y, s))):
                    continue
                aa, ab = pd.read_pickle(pa(y, s)), pd.read_pickle(pb(y, s))
                tcn = aa['py1x']['tcn']          # arm-independent; not read below
                for k, v in S.compare(aa, ab, y, tcn, hm[y], rm[y + 1], rng).items():
                    cell.setdefault(k, {}).setdefault(s, []).append(v)
        if not cell:
            continue
        n = {s: len(v) for s, v in cell[COLS[0][1]].items()}
        print(f'\n== {arm} minus {base}  (pairs per seed: {n}) ==')
        print(f'  {"read":<16}{"base r":>8}{"delta":>9}{"boot SE":>9}{"seed SD":>9}{"z":>7}{"positive":>10}')
        for lab, k in COLS:
            if k not in cell:
                continue
            per = cell[k]
            means = [np.mean([v[1] for v in per[s]]) for s in per]
            ses = [np.sqrt(sum(v[2] ** 2 for v in per[s])) / len(per[s]) for s in per]
            d, se = float(np.mean(means)), float(np.mean(ses))
            sd = float(np.std(means, ddof=1)) if len(means) > 1 else float('nan')
            tot = np.sqrt(se ** 2 + (0 if np.isnan(sd) else sd ** 2 / len(means)))
            pos = sum(v[1] > 0 for s in per for v in per[s])
            cnt = sum(len(per[s]) for s in per)
            b = float(np.mean([v[0] for s in per for v in per[s]]))
            z = d / tot if tot > 0 else float('nan')
            print(f'  {lab:<16}{b:>8.4f}{d:>9.4f}{se:>9.4f}{sd:>9.4f}{z:>7.1f}{f"{pos}/{cnt}":>10}')


if __name__ == '__main__':
    main()
