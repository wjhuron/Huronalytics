#!/usr/bin/env python3
"""stuff_gate_survivor.py — re-read every cached gate v2 arm on a pool that is
not gated on the TARGET season.

Gate v2's nxt_r keeps a pitcher only with >= 300 pitches in Y AND in Y+1. A
pitcher whose stuff failed and who lost his job leaves the pool, which the repo
rule of 2026-10-07 forbids (gate on the base period only, weight by the target
period). This reads the cached aggregates (no refit) and scores:

  gate   Pearson r, n_Y >= 300 and n_Y+1 >= 300              (the gate's rule)
  free   weighted r, n_Y >= 300, every pitcher with any Y+1 pitch,
         weight = Y+1 pitches                                 (base-period gate)

A pitcher with NO pitch in Y+1 has no outcome and cannot enter either pool; the
script counts them, because that part of the selection cannot be removed.

Deltas are arm minus SHIPPED on the same seed and pair, paired pitcher bootstrap,
raw and rendered grade, luck-neutral target (t) and actual run value (rv).

  .venv/bin/python scripts/research/stuff/stuff_gate_survivor.py [--dir data/_gate_v2]
"""
import argparse
import json
import os
import re
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PAIRS = (2021, 2022, 2023, 2024, 2025)
MIN_Y = 300
B = 1000


def wr(a, b, w):
    """Row-wise weighted Pearson r for (boot, n) arrays."""
    sw = w.sum(1, keepdims=True)
    am = (a * w).sum(1, keepdims=True) / sw
    bm = (b * w).sum(1, keepdims=True) / sw
    ca, cb = a - am, b - bm
    return (w * ca * cb).sum(1) / np.sqrt((w * ca * ca).sum(1) * (w * cb * cb).sum(1))


def table(agg):
    j = agg['py'].join(agg['py1'], lsuffix='_y', rsuffix='_y1', how='left')
    return j[j['n_y'] >= MIN_Y]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=os.path.join(ROOT, 'data', '_gate_v2'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'data', '_gate_v2', 'survivor_summary.json'))
    a = ap.parse_args()
    files = {}
    for fn in os.listdir(a.dir):
        m = re.match(r'agg_(.+)_(\d{4})_s(\d+)\.pkl$', fn)
        if m:
            files[(m.group(1), int(m.group(2)), int(m.group(3)))] = os.path.join(a.dir, fn)
    names = sorted({k[0] for k in files})
    rng = np.random.default_rng(0)
    pool, res = {}, {}
    for name in names:
        rows = []
        for (nm, y, s), fn in sorted(files.items()):
            if nm != name or y not in PAIRS or ('SHIPPED', y, s) not in files:
                continue
            ta = table(pd.read_pickle(fn))
            tb = table(pd.read_pickle(files[('SHIPPED', y, s)]))
            j = ta[['s', 's_r']].join(tb[['s', 's_r', 't', 'rv', 'n_y1']], rsuffix='_b', how='inner')
            if (y, s) not in pool:
                pool[(y, s)] = {'n_base': int(len(j)), 'no_y1': int(j['n_y1'].isna().sum()),
                                'under300': int(((j['n_y1'] < 300) & j['n_y1'].notna()).sum())}
            j = j[j['n_y1'].notna()]
            n = len(j)
            idx = np.vstack([np.arange(n)[None, :], rng.integers(0, n, size=(B, n))])
            V = {c: j[c].values.astype(float)[idx] for c in j.columns}
            rec = {}
            for pl in ('gate', 'free'):
                w = (V['n_y1'] >= 300).astype(float) if pl == 'gate' else V['n_y1']
                for unit, ca, cb in (('raw', 's', 's_b'), ('rend', 's_r', 's_r_b')):
                    for tg in ('t', 'rv'):
                        ra, rb = wr(V[ca], V[tg], w), wr(V[cb], V[tg], w)
                        d = ra - rb
                        rec[f'{pl}:{unit}:{tg}'] = (float(rb[0]), float(d[0]), float(d[1:].std()))
            rows.append((y, s, rec))
        if not rows:
            continue
        out = {'pairs': sorted({r[0] for r in rows}), 'seeds': sorted({r[1] for r in rows})}
        for k in rows[0][2]:
            byp = {}
            for y, s, rec in rows:
                byp.setdefault(y, []).append(rec[k])
            d = [float(np.mean([v[1] for v in vs])) for vs in byp.values()]
            se = [float(np.mean([v[2] for v in vs])) for vs in byp.values()]
            out[k] = {'ship_r': round(float(np.mean([np.mean([v[0] for v in vs]) for vs in byp.values()])), 4),
                      'd': round(float(np.mean(d)), 4),
                      'se': round(float(np.sqrt(np.sum(np.square(se))) / len(se)), 4),
                      'pos': int(sum(x > 0 for x in d)), 'n_pairs': len(d)}
        res[name] = out
    print('pool by pair (seed 0): base = n_Y >= 300')
    for (y, s), v in sorted(pool.items()):
        if s == 0:
            print(f'  {y}->{y + 1}: base {v["n_base"]}, no Y+1 pitch {v["no_y1"]} '
                  f'({v["no_y1"] / v["n_base"]:.1%}), under 300 in Y+1 {v["under300"]} '
                  f'({v["under300"] / v["n_base"]:.1%})')
    sh = res.get('SHIPPED', {})
    print('\nSHIPPED level:  ' + '  '.join(f'{k} {sh[k]["ship_r"]:.3f}' for k in sh if ':' in k))
    print(f'\n{"arm":<14s}{"seeds":>6s} | {"gate raw t":>20s} {"free raw t":>20s} | {"gate rend t":>20s} '
          f'{"free rend t":>20s} | {"free raw rv":>20s}')
    for name in names:
        if name == 'SHIPPED' or name not in res:
            continue
        r = res[name]
        f = lambda k: f"{r[k]['d']:+.4f} ({r[k]['se']:.4f}) {r[k]['pos']}/{r[k]['n_pairs']}"
        print(f'{name:<14s}{len(r["seeds"]):>6d} | {f("gate:raw:t"):>20s} {f("free:raw:t"):>20s} | '
              f'{f("gate:rend:t"):>20s} {f("free:rend:t"):>20s} | {f("free:raw:rv"):>20s}')
    json.dump({'pool': {f'{y}_s{s}': v for (y, s), v in pool.items()}, 'arms': res}, open(a.out, 'w'), indent=1)


if __name__ == '__main__':
    main()
