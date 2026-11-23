#!/usr/bin/env python3
"""social_note_gates.py — minimum sample for each social-card caption metric.

The social pitcher card prints a small caption under a pitch's Stuff+ chip: nVAA for a
four-seam or a sinker, and a note for another pitch type only when one validated metric is
far from normal (pitch_type_metric_importance.py chose the metrics). Each needs a minimum
sample. This measures, on the 2026 MLB pitch cache, the split-half reliability of each metric
for its pitch type and the denominator k at which reliability is .50, the convention the
card's other gates use (SOCIAL_WHIFF_MIN_SWINGS and friends in cards/pitcher.py).

Method: each pitcher x pitch type unit is split into two random halves of its denominator
events (five seeds); r is the weighted correlation of the two half values across units with
at least 2 x FLOOR events; k = n_half x (1 - r) / r, n_half the harmonic mean of the halves.
FLOOR is swept so the reading does not depend on one pool.

  .venv/bin/python scripts/research/cards/social_note_gates.py
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from pipeline.utils import SWING_DESCRIPTIONS, WHIFF_DESCRIPTIONS  # noqa: E402

# (pitch types, metric, denominator)
CASES = [(('FF',), 'vaa', 'pitches'), (('SI',), 'vaa', 'pitches'), (('FC',), 'spin', 'pitches'),
         (('CU', 'KC'), 'k2', 'two-strike swings'), (('CU', 'KC'), 'chase', 'out-of-zone pitches'),
         (('CH',), 'chase', 'out-of-zone pitches'), (('CH',), 'velo', 'pitches')]
FLOORS = {'pitches': (25, 50, 100), 'two-strike swings': (10, 20, 40), 'out-of-zone pitches': (20, 40, 80)}
SEEDS = 5


def main():
    with open(os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl'), 'rb') as fh:
        rows = pickle.load(fh)
    keep = ('Pitcher', 'Pitch Type', 'Velocity', 'Spin Rate', 'VAA', 'PlateZ', 'InZone', 'Count', 'Description', 'BBType')
    d = pd.DataFrame([{k: r.get(k) for k in keep} for r in rows if r.get('_source', 'MLB') == 'MLB' and r.get('Pitch Type')])
    del rows
    for c in ('Velocity', 'Spin Rate', 'VAA', 'PlateZ'):
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d['swing'] = d['Description'].isin(SWING_DESCRIPTIONS) & ~d['BBType'].isin(['bunt', 'Bunt'])
    d['whiff'] = d['Description'].isin(WHIFF_DESCRIPTIONS)
    d['two'] = d['Count'].astype(str).str.endswith('-2')
    print(f'{len(d):,} MLB pitches of 2026')
    print(f'{"types":<8s}{"metric":<8s}{"denominator":<22s}{"floor":>6s}{"units":>7s}{"r":>7s}{"n half":>8s}{"k at r .50":>12s}')
    for types, metric, den in CASES:
        g = d[d['Pitch Type'].isin(types)]
        if metric == 'k2':
            g = g[g['two'] & g['swing']].assign(x=lambda t: t['whiff'].astype(float))
        elif metric == 'chase':
            g = g[g['InZone'] == 'No'].assign(x=lambda t: t['swing'].astype(float))
        elif metric == 'vaa':
            g = g.dropna(subset=['VAA', 'PlateZ'])
            b = np.polyfit(g['PlateZ'], g['VAA'], 1)
            g = g.assign(x=g['VAA'] - b[0] * (g['PlateZ'] - g['PlateZ'].mean()))     # nVAA: the location removed
        else:
            col = {'spin': 'Spin Rate', 'velo': 'Velocity'}[metric]
            g = g.dropna(subset=[col]).assign(x=lambda t: t[col])
        for floor in FLOORS[den]:
            ks, rs, nh, nu = [], [], [], 0
            for seed in range(SEEDS):
                rng = np.random.default_rng(seed)
                h = rng.integers(0, 2, len(g))
                t = g.assign(h=h).groupby(['Pitcher', 'h'])['x'].agg(['mean', 'size']).unstack('h').dropna()
                t = t[(t[('size', 0)] >= floor) & (t[('size', 1)] >= floor)]
                if len(t) < 30:
                    continue
                w = 2.0 / (1.0 / t[('size', 0)] + 1.0 / t[('size', 1)])
                a, c = t[('mean', 0)].values, t[('mean', 1)].values
                ma, mc = np.average(a, weights=w), np.average(c, weights=w)
                r = np.average((a - ma) * (c - mc), weights=w) / np.sqrt(np.average((a - ma) ** 2, weights=w) * np.average((c - mc) ** 2, weights=w))
                n_half = len(t) / (1.0 / w).sum()
                rs.append(r)
                nh.append(n_half)
                ks.append(n_half * (1 - r) / r)
                nu = len(t)
            if rs:
                print(f'{"/".join(types):<8s}{metric:<8s}{den:<22s}{floor:>6d}{nu:>7d}{np.mean(rs):>7.3f}{np.mean(nh):>8.0f}{np.mean(ks):>12.1f}')
            else:
                print(f'{"/".join(types):<8s}{metric:<8s}{den:<22s}{floor:>6d}   too few units')


if __name__ == '__main__':
    main()
