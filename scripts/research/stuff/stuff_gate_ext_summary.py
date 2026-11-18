#!/usr/bin/env python3
"""stuff_gate_ext_summary.py — read the stuff_gate_v2_ext.py arms against SHIPPED.

Per arm, arm minus SHIPPED (seed 0), mean of five pairs, paired pitcher bootstrap:
  pool   'gate' = 300 pitches in Y and Y+1 (the gate's rule)
         'free' = 300 in Y, any Y+1 pitch, weighted by Y+1 pitches
  frame  pooled | within hand | within role (demeaned inside the group)
  unit   raw prediction mean | rendered atom mean
  target t (luck-neutral) | rv (actual) | tcn (luck-neutral, count mean removed)
plus the per-pitch-type next-season r (units with 150 pitches in both seasons).
SEED NOISE: SHIPPED seed 1 and seed 2 are read the same way against seed 0; a
delta inside that spread is not a result.

  .venv/bin/python scripts/research/stuff/stuff_gate_ext_summary.py
"""
import json
import os
import re
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stuff_gate_v2 as G  # noqa: E402
import stuff_gate_v2_ext as E  # noqa: E402

PAIRS = (2021, 2022, 2023, 2024, 2025)
B = 1000
OUT = os.path.join(E.EXT, 'summary.json')
TYPES = ('FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS')


def wr(a, b, w, g=None):
    if g is not None:
        a, b = a.copy(), b.copy()
        for code in np.unique(g):
            m = (g == code) * w
            sw = np.maximum(m.sum(1, keepdims=True), 1e-12)
            a = a - ((a * m).sum(1, keepdims=True) / sw) * (g == code)
            b = b - ((b * m).sum(1, keepdims=True) / sw) * (g == code)
    sw = w.sum(1, keepdims=True)
    ca = a - (a * w).sum(1, keepdims=True) / sw
    cb = b - (b * w).sum(1, keepdims=True) / sw
    return (w * ca * cb).sum(1) / np.sqrt((w * ca * ca).sum(1) * (w * cb * cb).sum(1))


def ptab(agg, tcn):
    j = agg['py'].join(agg['py1'], lsuffix='_y', rsuffix='_y1', how='inner')
    j = j[j['n_y'] >= 300].copy()
    j['tcn'] = tcn.reindex(j.index)
    return j


def compare(aa, ab, y, tcn, hm, rm, rng):
    ta, tb = ptab(aa, tcn), ptab(ab, tcn)
    j = ta[['s', 's_r']].join(tb[['s', 's_r', 't', 'rv', 'tcn', 'n_y1']], rsuffix='_b', how='inner').dropna()
    hand = np.array([0 if hm.get(p) == 'L' else 1 for p in j.index])
    role = np.array([{'SP': 0, 'RP': 1}.get(rm.get(p), 2) for p in j.index])
    n = len(j)
    idx = np.vstack([np.arange(n)[None, :], rng.integers(0, n, size=(B, n))])
    V = {c: j[c].values.astype(float)[idx] for c in j.columns}
    Gc = {'pooled': None, 'hand': hand[idx], 'role': role[idx]}
    out = {}
    for pool in ('gate', 'free'):
        w = (V['n_y1'] >= 300).astype(float) if pool == 'gate' else V['n_y1']
        for fr, g in Gc.items():
            for unit, ca, cb in (('raw', 's', 's_b'), ('rend', 's_r', 's_r_b')):
                for tg in ('t', 'rv', 'tcn'):
                    ra, rb = wr(V[ca], V[tg], w, g), wr(V[cb], V[tg], w, g)
                    d = ra - rb
                    out[f'{pool}:{fr}:{unit}:{tg}'] = (float(rb[0]), float(d[0]), float(d[1:].std()))
    # per pitch type, unit level
    ua = aa['uy'].join(aa['uy1'], lsuffix='_y', rsuffix='_y1', how='inner')
    ub = ab['uy'].join(ab['uy1'], lsuffix='_y', rsuffix='_y1', how='inner')
    u = ua[['s']].join(ub[['s', 't', 'n_y', 'n_y1']], rsuffix='_b', how='inner')
    u = u[(u['n_y'] >= 150) & (u['n_y1'] >= 150)].dropna()
    for pt in TYPES:
        s = u[u.index.get_level_values('pitch_type') == pt]
        if len(s) >= 40:
            m = len(s)
            ix = np.vstack([np.arange(m)[None, :], rng.integers(0, m, size=(B, m))])
            A_, B_, T_ = (s[c].values.astype(float)[ix] for c in ('s', 's_b', 't'))
            one = np.ones_like(T_)
            ra, rb = wr(A_, T_, one), wr(B_, T_, one)
            out[f'type:{pt}'] = (float(rb[0]), float((ra - rb)[0]), float((ra - rb)[1:].std()))
    return out


def main():
    hm, rm = G.hand_map(), G.role_map()
    rng = np.random.default_rng(0)
    arms = sorted({re.match(r'agg_(.+)_\d{4}_s0\.pkl$', f).group(1) for f in os.listdir(E.EXT)
                   if re.match(r'agg_(.+)_\d{4}_s0\.pkl$', f)})
    todo = [(a, lambda y, a=a: E.agg_path(a, y, 0)) for a in arms]
    todo += [(f'SEED{s}', lambda y, s=s: G.agg_path('SHIPPED', y, s)) for s in (1, 2)]
    res = {}
    for name, pf in todo:
        per = {}
        for y in PAIRS:
            if not os.path.exists(pf(y)):
                continue
            ab = pd.read_pickle(G.agg_path('SHIPPED', y, 0))
            aa = pd.read_pickle(pf(y))
            # the count-neutral Y+1 target is arm-independent; any ext aggregate of the pair has it
            src = next((E.agg_path(a, y, 0) for a in arms if os.path.exists(E.agg_path(a, y, 0))), None)
            tcn = pd.read_pickle(src)['py1x']['tcn'] if src else pd.Series(dtype=float)
            per[y] = compare(aa, ab, y, tcn, hm[y], rm[y + 1], rng)
        if not per:
            continue
        r = {'pairs': sorted(per)}
        for k in set().union(*[set(v) for v in per.values()]):
            vs = [per[y][k] for y in per if k in per[y]]
            r[k] = {'ship': round(float(np.mean([v[0] for v in vs])), 4), 'd': round(float(np.mean([v[1] for v in vs])), 4),
                    'se': round(float(np.sqrt(sum(v[2] ** 2 for v in vs)) / len(vs)), 4),
                    'pos': int(sum(v[1] > 0 for v in vs)), 'n': len(vs)}
        res[name] = r
    f = lambda r, k: (f"{r[k]['d']:+.4f} ({r[k]['se']:.4f}) {r[k]['pos']}/{r[k]['n']}" if k in r else '')
    cols = [('gate raw t', 'gate:pooled:raw:t'), ('free raw t', 'free:pooled:raw:t'), ('free rend t', 'free:pooled:rend:t'),
            ('free raw rv', 'free:pooled:raw:rv'), ('free raw tcn', 'free:pooled:raw:tcn'),
            ('in hand', 'free:hand:raw:t'), ('in role', 'free:role:raw:t')]
    print(f'{"arm":<12s}{"pairs":>6s} | ' + ' '.join(f'{c[0]:>22s}' for c in cols))
    for name, r in res.items():
        print(f'{name:<12s}{len(r["pairs"]):>6d} | ' + ' '.join(f'{f(r, c[1]):>22s}' for c in cols))
    print('\nper pitch type, next-season unit r: SHIPPED level, then arm minus SHIPPED (se)')
    print(f'{"arm":<12s}' + ''.join(f'{pt:>17s}' for pt in TYPES))
    sh = next(iter(res.values()), {})
    print(f'{"SHIPPED r":<12s}' + ''.join(f'{sh.get("type:" + pt, {}).get("ship", float("nan")):>17.3f}' for pt in TYPES))
    for name, r in res.items():
        print(f'{name:<12s}' + ''.join((f'{r["type:" + pt]["d"]:>+9.3f} ({r["type:" + pt]["se"]:.3f})' if f'type:{pt}' in r else f'{"":>17s}')
                                       for pt in TYPES))
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
