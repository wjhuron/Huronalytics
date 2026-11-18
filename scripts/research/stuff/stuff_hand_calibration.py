#!/usr/bin/env python3
"""stuff_hand_calibration.py — is a Stuff+ point worth the same for a left-hander?

Left-handers grade below right-handers on every pitch type. This asks whether the
gap is real or a level error: at EQUAL Stuff+, do left-handers allow fewer runs
next season? From the gate's cached SHIPPED aggregates (out-of-sample grades of
season Y, model fit on neither Y nor Y+1), no refit:

  pitcher level   t(Y+1) = a + b * grade(Y) + c * LHP,  weighted by Y+1 pitches,
                  pitchers with >= 300 pitches in Y and any pitch in Y+1
  unit level      the same per pitch type, (pitcher, type) with >= 150 pitches in Y

t is runs prevented per pitch on the luck-neutral target (pitcher-positive).
c / b is the left-hander offset in Stuff+ points: how many points a left-hander's
grade would have to rise for equal grades to mean equal results. Bootstrap over
pitchers; five pairs, three seeds averaged.

  .venv/bin/python scripts/research/stuff/stuff_hand_calibration.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stuff_gate_v2 as G  # noqa: E402

OUT = os.path.join(G.CACHE, 'hand_calibration.json')
PAIRS = (2021, 2022, 2023, 2024, 2025)
B = 1000
TYPES = ('FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS')


def wls(X, y, w):
    Xw = X * np.sqrt(w)[:, None]
    return np.linalg.lstsq(Xw, y * np.sqrt(w), rcond=None)[0]


def fit(df, rng):
    """returns offset points (c/b), slope b (runs/100 per point), LHP mean grade gap, boot SE of offset"""
    X = np.column_stack([np.ones(len(df)), df['g'].values, df['lhp'].values])
    y, w = df['t'].values * 100, df['w'].values
    beta = wls(X, y, w)
    off = beta[2] / beta[1]
    pit = df['pitcher'].values
    ids = np.unique(pit)
    pos = {p: np.where(pit == p)[0] for p in ids}
    bs = []
    for _ in range(B):
        idx = np.concatenate([pos[p] for p in rng.choice(ids, len(ids))])
        b_ = wls(X[idx], y[idx], w[idx])
        bs.append(b_[2] / b_[1])
    gap = np.average(df.g[df.lhp == 1], weights=df.w[df.lhp == 1]) - np.average(df.g[df.lhp == 0], weights=df.w[df.lhp == 0])
    return float(off), float(beta[1]), float(gap), float(np.std(bs))


def main():
    hm = G.hand_map()
    rng = np.random.default_rng(0)
    res = {'pitcher': {}, 'unit': {}}
    for y in PAIRS:
        ps, us = [], []
        for seed in (0, 1, 2):
            fn = G.agg_path('SHIPPED', y, seed)
            if not os.path.exists(fn):
                continue
            a = pd.read_pickle(fn)
            j = a['py'].join(a['py1'], lsuffix='_y', rsuffix='_y1', how='inner')
            j = j[j['n_y'] >= 300]
            ps.append(pd.DataFrame({'g': j['s_r'], 't': j['t'], 'w': j['n_y1']}))
            u = a['uy'].join(a['uy1'], lsuffix='_y', rsuffix='_y1', how='inner')
            u = u[u['n_y'] >= 150]
            us.append(pd.DataFrame({'g': u['s_r'], 't': u['t'], 'w': u['n_y1']}))
        p = sum(ps) / len(ps)
        p = p.dropna().reset_index()
        p['lhp'] = [1.0 if hm[y].get(n) == 'L' else 0.0 for n in p['pitcher']]
        res['pitcher'][y] = fit(p, rng)
        u = (sum(us) / len(us)).dropna().reset_index()
        u['lhp'] = [1.0 if hm[y].get(n) == 'L' else 0.0 for n in u['pitcher']]
        for pt in TYPES:
            s = u[u['pitch_type'] == pt]
            if (s.lhp == 1).sum() >= 15:
                res['unit'].setdefault(pt, {})[y] = fit(s, rng)
        print(f'{y}: pitcher offset {res["pitcher"][y][0]:+.2f} pts (se {res["pitcher"][y][3]:.2f}), '
              f'grade gap L-R {res["pitcher"][y][2]:+.2f}', flush=True)

    def pool(d):
        off = np.mean([v[0] for v in d.values()])
        se = np.sqrt(sum(v[3] ** 2 for v in d.values())) / len(d)
        return off, se, np.mean([v[2] for v in d.values()]), np.mean([v[1] for v in d.values()]), sum(v[0] > 0 for v in d.values()), len(d)
    print('\nleft-hander offset in Stuff+ points (positive = left-handers beat their grade next season)')
    print(f'{"level":>10s}{"offset":>9s}{"se":>7s}{"z":>7s}{"pairs>0":>9s}{"grade gap L-R":>15s}{"runs/100 per pt":>17s}')
    o = pool(res['pitcher'])
    print(f'{"pitcher":>10s}{o[0]:>+9.2f}{o[1]:>7.2f}{o[0] / o[1]:>+7.1f}{o[4]:>6d}/{o[5]}{o[2]:>+15.2f}{o[3]:>17.4f}')
    out = {'pitcher': {'offset': o[0], 'se': o[1], 'gap': o[2], 'slope': o[3]}}
    for pt in TYPES:
        if pt in res['unit'] and len(res['unit'][pt]) >= 3:
            o = pool(res['unit'][pt])
            out[pt] = {'offset': o[0], 'se': o[1], 'gap': o[2], 'slope': o[3], 'pairs': o[5]}
            print(f'{pt:>10s}{o[0]:>+9.2f}{o[1]:>7.2f}{o[0] / o[1]:>+7.1f}{o[4]:>6d}/{o[5]}{o[2]:>+15.2f}{o[3]:>17.4f}')
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
