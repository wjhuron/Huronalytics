#!/usr/bin/env python3
"""stuff_hand_level_methods.py — how should Stuff+ carry the left-hander level?

Left-handers grade about 5 points below right-handers and beat that grade by
about 7 points next season (stuff_hand_calibration.py). Four ways to put the hand
level into the grade, all read on the gate's pairs (grade of Y, results of Y+1):

  ship    shipped: one anchor per pitch type
  anchor  one anchor (mean and SD) per pitch type AND pitcher hand: sets the two
          hands' averages equal, no more
  offset  shipped plus a flat left-hander offset in points, estimated on the
          OTHER four pairs (so the offset is always out of sample)
  feat    pitcher hand as a model feature (gate arm LHP)
  feat_i  the same with the pitcher's own seasons out of training (IDENT3_LHP),
          read against IDENT3

ship, anchor and offset are re-rendered from the cached SHIPPED unit means (unit =
pitcher x type, grade = pitch-weighted mean of unit grades; atoms are not
re-rounded, so 'ship' here differs from the gate's rendered column in the first
decimal). Pool: 300 pitches in Y, any Y+1 pitch, weighted by Y+1 pitches.

Read: pooled next-season r (cross-hand comparisons), within-hand r (must not
lose), and the left-hander offset that REMAINS (0 = equal grades mean equal
results), each with a pitcher bootstrap.

  .venv/bin/python scripts/research/stuff/stuff_hand_level_methods.py
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
import stuff_gate_v2_ext as E  # noqa: E402

OUT = os.path.join(G.CACHE, 'hand_level_methods.json')
PAIRS = (2021, 2022, 2023, 2024, 2025)
B = 1000
QUAL = 50


def render(u, keys):
    """u: unit frame (pitcher, pitch_type, hand, s, n). Anchor per `keys`; fallback to per type."""
    q = u[u['n'] >= QUAL]
    base = q.groupby('pitch_type')['s'].agg(['mean', 'std', 'size'])
    a = q.groupby(keys)['s'].agg(['mean', 'std', 'size'])
    j = u.join(a, on=keys).join(base, on='pitch_type', rsuffix='_t')
    ok = (j['size'] >= 5) & (j['std'] > 0)
    mu = np.where(ok, j['mean'], j['mean_t'])
    sd = np.where(ok, j['std'], j['std_t'])
    g = 100 + 10 * (j['s'] - mu) / sd
    d = pd.DataFrame({'g': g, 'n': j['n'], 'pitcher': j['pitcher']}).dropna()
    return (d['g'] * d['n']).groupby(d['pitcher']).sum() / d['n'].groupby(d['pitcher']).sum()


def wls_off(g, t, lhp, w):
    X = np.column_stack([np.ones(len(g)), g, lhp])
    sw = np.sqrt(w)
    b = np.linalg.lstsq(X * sw[:, None], t * sw, rcond=None)[0]
    return b[2] / b[1]


def wr(a, b, w, g=None):
    def dm(x):
        if g is None:
            return x - (x * w).sum() / w.sum()
        out = x.copy()
        for c in np.unique(g):
            m = g == c
            out[m] = x[m] - (x[m] * w[m]).sum() / w[m].sum()
        return out
    a, b = dm(a), dm(b)
    return float((w * a * b).sum() / np.sqrt((w * a * a).sum() * (w * b * b).sum()))


def main():
    hm = G.hand_map()
    frames = {}
    for y in PAIRS:
        a = pd.read_pickle(G.agg_path('SHIPPED', y, 0))
        u = a['uy'].reset_index()
        u['hand'] = [hm[y].get(p, 'R') for p in u['pitcher']]
        j = a['py'].join(a['py1'], lsuffix='_y', rsuffix='_y1', how='inner')
        j = j[j['n_y'] >= 300]
        d = pd.DataFrame({'t': j['t'], 'rv': j['rv'], 'w': j['n_y1']})
        d['ship'] = render(u, ['pitch_type']).reindex(d.index)
        d['anchor'] = render(u, ['pitch_type', 'hand']).reindex(d.index)
        d['lhp'] = [1.0 if hm[y].get(p) == 'L' else 0.0 for p in d.index]
        for nm, arm in (('feat', 'LHP'), ('ident', 'IDENT3'), ('feat_i', 'IDENT3_LHP')):
            fn = E.agg_path(arm, y, 0)
            if os.path.exists(fn):
                d[nm] = pd.read_pickle(fn)['py']['s_r'].reindex(d.index)
        d['gate'] = j['s_r']
        frames[y] = d.dropna(subset=['ship', 'anchor', 't', 'rv'])
    for y in PAIRS:      # out-of-sample flat offset
        tr = pd.concat([frames[o] for o in PAIRS if o != y])
        off = wls_off(tr['ship'].values, tr['t'].values * 100, tr['lhp'].values, tr['w'].values)
        frames[y]['offset'] = frames[y]['ship'] + off * frames[y]['lhp']
        frames[y].attrs['off'] = off
    print('out-of-sample left-hander offset by pair (points): ' + ', '.join(f'{y} {frames[y].attrs["off"]:+.2f}' for y in PAIRS))
    methods = [m for m in ('gate', 'ship', 'anchor', 'offset', 'feat', 'ident', 'feat_i') if all(m in frames[y] for y in PAIRS)]
    rng = np.random.default_rng(0)
    res = {}
    for m in methods:
        rows = []
        for y in PAIRS:
            d = frames[y].dropna(subset=[m])
            g, t, rv, w, l = (d[c].values.astype(float) for c in (m, 't', 'rv', 'w', 'lhp'))
            base = 'ident' if m == 'feat_i' else 'ship'
            gb = d[base].values.astype(float) if base in d else g
            stat = lambda ix: (wr(g[ix], t[ix], w[ix]), wr(g[ix], rv[ix], w[ix]), wr(g[ix], t[ix], w[ix], l[ix]),
                               wls_off(g[ix], t[ix] * 100, l[ix], w[ix]),
                               wr(g[ix], t[ix], w[ix]) - wr(gb[ix], t[ix], w[ix]),
                               wr(g[ix], t[ix], w[ix], l[ix]) - wr(gb[ix], t[ix], w[ix], l[ix]),
                               np.average(g[ix][l[ix] == 1], weights=w[ix][l[ix] == 1]) - np.average(g[ix][l[ix] == 0], weights=w[ix][l[ix] == 0]))
            n = len(d)
            pt = stat(np.arange(n))
            bs = np.array([stat(rng.integers(0, n, n)) for _ in range(B)])
            rows.append((pt, bs.std(0)))
        mean = np.mean([r[0] for r in rows], axis=0)
        se = np.sqrt(np.sum([r[1] ** 2 for r in rows], axis=0)) / len(rows)
        pos = np.sum([np.array(r[0]) > 0 for r in rows], axis=0)
        res[m] = {'r_t': mean[0], 'r_rv': mean[1], 'r_within_hand': mean[2], 'offset_left': mean[3], 'offset_se': se[3],
                  'd_pooled': mean[4], 'd_pooled_se': se[4], 'd_pooled_pos': int(pos[4]),
                  'd_within': mean[5], 'd_within_se': se[5], 'd_within_pos': int(pos[5]), 'gap_L_minus_R': mean[6]}
    print(f'\n{"method":<8s}{"pooled r xRV":>13s}{"RV":>8s}{"in hand":>9s} | {"d pooled vs base":>24s}{"d in hand vs base":>24s} | '
          f'{"grade gap L-R":>14s}{"offset left (se)":>18s}')
    for m, r in res.items():
        print(f'{m:<8s}{r["r_t"]:>13.4f}{r["r_rv"]:>8.4f}{r["r_within_hand"]:>9.4f} | '
              f'{f"""{r["d_pooled"]:+.4f} ({r["d_pooled_se"]:.4f}) {r["d_pooled_pos"]}/5""":>24s}'
              f'{f"""{r["d_within"]:+.4f} ({r["d_within_se"]:.4f}) {r["d_within_pos"]}/5""":>24s} | '
              f'{r["gap_L_minus_R"]:>+14.2f}{f"""{r["offset_left"]:+.2f} ({r["offset_se"]:.2f})""":>18s}')
    print('base = ship for every method except feat_i, whose base is ident')
    json.dump({k: {a: float(b) for a, b in v.items()} for k, v in res.items()}, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
