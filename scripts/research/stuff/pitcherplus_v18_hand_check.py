#!/usr/bin/env python3
"""pitcherplus_v18_hand_check.py — does Pitcher+ stay right for left-handers when
Stuff+ takes pitcher hand as a feature (v18)?

Pitcher+ has no hand term and frozen weights (Stuff+ .20, Loc+ .06, ...), and Loc+
still reads left-handers a few points high. This reads the shipped Pitcher+ recipe
on its own harness (pitcherplus_v14_audit.py: panel S = split halves, panel Y =
year pairs, target future xRV/100) with two Stuff+ inputs that differ only in the
Stuff+ code: v17 and v18 (pitcherplus_stuff_loso_v14.py run on each).

  1. frozen formula: r on both panels, v17 vs v18
  2. left-hander calibration, year pairs: next-season xRV/100 = a + b * Pitcher+ + c * LHP.
     c / b is the left-hander offset in Pitcher+ points (positive = left-handers beat
     their Pitcher+). Pitcher bootstrap.
  3. refit weights of the shipped six, v17 vs v18 (does anything move?)

Hand comes from data/_era_targets.json (MLB Stats API, keyed by MLB id).

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/stuff/pitcherplus_v18_hand_check.py V17.csv V18.csv
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pitcherplus_v14_audit as A  # noqa: E402

ps = A.ps
ROOT = A.ROOT
B = 2000


def hands():
    tg = json.load(open(os.path.join(ROOT, 'data', '_era_targets.json')))
    return {(int(pid), int(y)): r.get('hand') for y, d in tg.items() for pid, r in d['pitchers'].items()}


def pairs_table(t):
    kmap = {f: k for f, _w, k in A.SHIPPED}
    full = t[(t['half'] == 'full') & (t['n'] >= A.MIN_FULL)]
    full = A.shrunk_z(full, A.SHIPPED_SUBSET, kmap, A.Q_FULL)
    full['comp'] = sum(w * full[f + '_sz'] for f, w, _ in A.SHIPPED)
    # Pitcher+ points: 100 + 10 z within the season's rows here
    full['pp'] = 100 + 10 * full.groupby('season')['comp'].transform(lambda s: (s - s.mean()) / s.std())
    p = full.merge(full.assign(season=full['season'] - 1)[['pid', 'season', 'xrv100']],
                   on=['pid', 'season'], suffixes=('', '_n1'))
    return p[np.isfinite(p['xrv100_n1'])]


def offset(p, hm, rng):
    p = p.copy()
    p['lhp'] = [{'L': 1.0, 'R': 0.0}.get(hm.get((int(a), int(b)))) for a, b in zip(p['pid'], p['season'])]
    p = p.dropna(subset=['lhp'])
    X = np.column_stack([np.ones(len(p)), p['pp'].values, p['lhp'].values])
    y = p['xrv100_n1'].values

    def fit(ix):
        b = np.linalg.lstsq(X[ix], y[ix], rcond=None)[0]
        return b[2] / b[1], b[1], b[2]
    pt = fit(np.arange(len(p)))
    bs = np.array([fit(rng.integers(0, len(p), len(p)))[0] for _ in range(B)])
    gap = p.loc[p.lhp == 1, 'pp'].mean() - p.loc[p.lhp == 0, 'pp'].mean()
    return {'n': len(p), 'lhp_n': int(p.lhp.sum()), 'offset_pts': float(pt[0]), 'se': float(bs.std()),
            'slope': float(pt[1]), 'gap_L_minus_R': float(gap)}


def refit_weights(t):
    kmap = A.stab_constants()
    (S_X, S_y, _), (Y_X, Y_y, _) = A.build_panels(t, kmap)
    cols = [A.SURVIVORS.index(c) for c in A.SHIPPED_SUBSET]
    out = {}
    for label, X, y in (('S', S_X, S_y), ('Y', Y_X, Y_y)):
        b = np.linalg.lstsq(np.column_stack([np.ones(len(y)), X[:, cols]]), y, rcond=None)[0]
        out[label] = dict(zip(A.SHIPPED_SUBSET, (b[1:] / np.abs(b[1:]).sum()).round(3)))
    return out


def main():
    hm = hands()
    rng = np.random.default_rng(0)
    res = {}
    for tag, csv in (('v17', sys.argv[1]), ('v18', sys.argv[2])):
        t = A.load_tables(csv)
        r_s, r_y = A.frozen_eval(t)
        res[tag] = {'r_S': r_s, 'r_Y': r_y, 'hand': offset(pairs_table(t), hm, rng), 'w': refit_weights(t)}
    print(f'\n{"":<6s}{"frozen r_S":>11s}{"r_Y":>8s}{"combined":>10s} | {"Pitcher+ gap L-R":>17s}{"LHP offset (pts)":>18s}{"se":>6s}{"pairs":>7s}{"LHP":>5s}')
    for tag, r in res.items():
        h = r['hand']
        print(f'{tag:<6s}{r["r_S"]:>11.4f}{r["r_Y"]:>8.4f}{(r["r_S"] + r["r_Y"]) / 2:>10.4f} | {h["gap_L_minus_R"]:>+17.2f}'
              f'{h["offset_pts"]:>+18.2f}{h["se"]:>6.2f}{h["n"]:>7d}{h["lhp_n"]:>5d}')
    print('\nrefit weights of the shipped six (normalized; shipped: stuff .20 loc .06 k .21 izwhiff .19 xrv .23 gb .12)')
    for tag, r in res.items():
        for lab in ('S', 'Y'):
            print(f'  {tag} panel {lab}: ' + '  '.join(f'{k} {v:+.3f}' for k, v in r['w'][lab].items()))
    json.dump(res, open(os.path.join(ROOT, 'data', '_pplus_v18_hand_check.json'), 'w'), indent=1, default=float)


if __name__ == '__main__':
    main()
