#!/usr/bin/env python3
"""locplus_within_between.py — why does the Loc+ unit grade forecast for fastballs only?

Unit read of 2026-11-19: the released location value forecasts next-season unit results for
FF (-.20) and SI (-.16), not for CH, CU, FC, SL, and with the WRONG sign for FS (+.42).
Two explanations make different predictions:
  the surface is wrong for that type      -> the value misprices single pitches too
  selection between pitchers              -> single pitches are priced right, but pitchers
                                             with a better pitch throw it to spots the
                                             average pitch should not go
This splits the relation of actual value to location value into WITHIN unit (pitcher x pitch
type x season; the pitcher and his pitch are held fixed) and BETWEEN units, per pitch type,
on each season's own released surfaces:
  within slope    regression of the pitch's actual hitter run value on its location value,
                  both demeaned inside the unit. 1.0 = the value is calibrated pitch by pitch.
  between slope   the same regression on unit means (units 300+ pitches), season-demeaned.
A within slope near 1 with a between slope near 0 or negative is selection, not a bad surface.

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/locplus_within_between.py
"""
import gc
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline.locplus as lp  # noqa: E402
import locplus_fullseason_replicate as FR  # noqa: E402
import locplus_shape_loader as SL  # noqa: E402
from pipeline.sdplus import make_rv_xrv  # noqa: E402

OUT = os.path.join(ROOT, 'data', '_loc_within_between.json')
YEARS = list(range(2021, 2027))
TYPES = ('FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'KC', 'CH', 'FS')


def season(y):
    ps = [p for p in SL.load_season(y) if lp.is_eligible_baseline(p)]
    S = lp.build_surfaces(ps, FR.LG, FR.SCALE)
    rvx = make_rv_xrv(FR.LG, FR.SCALE, count_offsets=lp.build_bip_count_offsets(ps, FR.LG, FR.SCALE))
    rows = []
    for p in ps:
        v = lp.location_value(p, S)
        re = lp.safe_float(p.get('RunExp'))
        x = rvx(p)
        if v is None or re is None or x is None:
            continue
        ck = lp.cell_key(p)
        rows.append((p.get('Pitcher'), p.get('_pt0') or p.get('Pitch Type'), ck, v, -re, x))
    del ps, S
    gc.collect()
    d = pd.DataFrame(rows, columns=['pitcher', 'pt', 'cell', 'loc', 'rv', 'x'])
    # the outcome on the grade's own footing: minus the situation mean, as the location value is
    for c in ('rv', 'x'):
        d[c] = d[c] - d.groupby('cell')[c].transform('mean')
    d['y'] = y
    return d.drop(columns='cell')


def slope(a, b):
    a, b = a - a.mean(), b - b.mean()
    den = float((a * a).sum())
    return (float((a * b).sum()) / den if den else float('nan')), float(np.corrcoef(a, b)[0, 1])


def main():
    acc = {pt: {'w': np.zeros(5), 'units': []} for pt in TYPES}
    for y in YEARS:
        d = season(y)
        d = d[d['pt'].isin(TYPES)]
        g = d.groupby(['pitcher', 'pt'])
        n = g['loc'].transform('size')
        w = d[n >= 100].copy()
        for c in ('loc', 'rv', 'x'):
            w[c + '_w'] = w[c] - w.groupby(['pitcher', 'pt'])[c].transform('mean')
        for pt, s in w.groupby('pt'):
            a = acc[pt]['w']
            a += np.array([len(s), (s['loc_w'] ** 2).sum(), (s['loc_w'] * s['rv_w']).sum(), (s['loc_w'] * s['x_w']).sum(), 0.0])
        u = g.agg(loc=('loc', 'mean'), rv=('rv', 'mean'), x=('x', 'mean'), n=('loc', 'size')).reset_index()
        u = u[u['n'] >= 300]
        for c in ('loc', 'rv', 'x'):
            u[c] = u[c] - u.groupby('pt')[c].transform('mean')
        for pt, s in u.groupby('pt'):
            acc[pt]['units'].append(s)
        print(f'{y}: {len(d)} pitches', flush=True)
        del d, w, u
        gc.collect()
    rng = np.random.default_rng(0)
    out = {}
    print('\nslope of the outcome on the location value (both minus the situation mean). 1.0 = calibrated')
    print(f'{"type":>5s}{"pitches":>10s}{"WITHIN actual":>15s}{"WITHIN luck-neutral":>21s} | {"units":>6s}{"BETWEEN actual (se)":>22s}{"BETWEEN luck-neutral (se)":>27s}{"unit r":>8s}')
    for pt in TYPES:
        n, sxx, sxy_rv, sxy_x, _ = acc[pt]['w']
        if not acc[pt]['units'] or sxx == 0:
            continue
        U = pd.concat(acc[pt]['units'])
        b_rv, r_rv = slope(U['loc'].values, U['rv'].values)
        b_x, r_x = slope(U['loc'].values, U['x'].values)
        bs = []
        for _ in range(1000):
            i = rng.integers(0, len(U), len(U))
            bs.append((slope(U['loc'].values[i], U['rv'].values[i])[0], slope(U['loc'].values[i], U['x'].values[i])[0]))
        se = np.std(np.array(bs), axis=0)
        out[pt] = {'pitches': int(n), 'within_rv': sxy_rv / sxx, 'within_x': sxy_x / sxx, 'units': len(U), 'between_rv': b_rv, 'between_x': b_x,
                   'se_rv': float(se[0]), 'se_x': float(se[1]), 'unit_r_x': r_x}
        print(f'{pt:>5s}{int(n):>10d}{sxy_rv / sxx:>15.2f}{sxy_x / sxx:>21.2f} | {len(U):>6d}{f"{b_rv:+.2f} ({se[0]:.2f})":>22s}{f"{b_x:+.2f} ({se[1]:.2f})":>27s}{r_x:>+8.2f}')
    json.dump(out, open(OUT + '.tmp', 'w'), indent=1)
    os.replace(OUT + '.tmp', OUT)


if __name__ == '__main__':
    main()
