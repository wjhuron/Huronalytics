#!/usr/bin/env python3
"""locplus_farmiss_location.py — a far-miss rule for the RELEASED Loc+ grade.

Loc+ clamps a pitch outside its grid into the edge cell. With the 2 in / 0.12
kernel the outer region is far more accurate than before, but the clamp remains:
a changeup 34.6 in off the plate in a 1-2 count still grades 152. The pitch-level
calibration on the new kernel (locplus_farmiss_rule.py calib, 2026-11-19) moved
the point where "a far miss is a certain ball" beats the surface from 18 to about
24 inches (low 0.8 -> 1.0 zone heights, high 0.4 -> 0.6).

Rule: beyond a cutoff, the expected value is the count's ball value. The grade
then takes that value minus the situation mean, like every other pitch.

This runs the released grade's own harness (locplus_location_sweep.py stage 2:
full-season surfaces for the pitcher table, odd/even-date surfaces for held-out
pitch error) for a grid of cutoffs, one dimension at a time and then combined.
  PITCH    held-out squared error against actual run value, arm minus base,
           date-block bootstrap, seasons better. Decides the cutoff: inside the
           true crossing the rule is WORSE, so it cannot be gamed inward.
  PITCHER  the released decider (next season, Stuff+ held equal, within hand and
           role, five pairs). The no-harm check: a cutoff must not lose here.
The shape-class surfaces are switched off in this harness (it scores the group
surfaces through its own fast path); the rule acts on far pitches only.

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/locplus_farmiss_location.py run
  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/locplus_farmiss_location.py report
"""
import gc
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'stuff'))
import pipeline.locplus as lp  # noqa: E402
import locplus_location_sweep as LS  # noqa: E402

lp.SHAPE_ON = False
INF = float('inf')
ARMS = {'fm_base': None}
for x in (18, 20, 22, 24, 26, 28, 32):
    ARMS[f'fm_x{x}'] = ('far', float(x), INF, INF)
for lo in (0.6, 0.8, 1.0, 1.25, 1.5):
    ARMS[f'fm_lo{lo}'] = ('far', INF, lo, INF)
for hi in (0.4, 0.5, 0.6, 0.8, 1.0):
    ARMS[f'fm_hi{hi}'] = ('far', INF, INF, hi)
ARMS['fm_24_1.0_0.6'] = ('far', 24.0, 1.0, 0.6)
ARMS['fm_22_1.0_0.6'] = ('far', 22.0, 1.0, 0.6)
ARMS['fm_26_1.25_0.8'] = ('far', 26.0, 1.25, 0.8)
OUT = os.path.join(LS.CACHE, 'farmiss_report.json')
B = 1000


def run():
    LS.ARMS2 = {n: (LS.BASE2, f) for n, f in ARMS.items()}
    for y in LS.YEARS:
        _, n = LS.season_job2(y)
        print(f'{y}: {n} arms built', flush=True)
        gc.collect()


def report():
    import locplus_two_number_build as T2
    rng = np.random.default_rng(0)
    tabs = {(n, y): pickle.load(open(LS.tab_path(n, y), 'rb')) for n in ARMS for y in LS.YEARS}
    frames = {}
    for y in LS.YEARS[:-1]:
        f0 = T2.pair_frame(y)
        frames[y] = f0[f0['role'] != 'NA']
    out = {}
    print(f'{"arm":<16s}{"PITCH sq err x1e4 (z) seasons":>32s} | {"PITCHER within hand+role x1e4 (z) pairs":>42s} | {"pooled x1e4 (z)":>16s} | {"half r":>7s}')
    for n in ARMS:
        ds = []
        for y in LS.YEARS:
            a, b = tabs[(n, y)]['sse'], tabs[('fm_base', y)]['sse']
            j = a.join(b, lsuffix='_a', rsuffix='_b', how='inner')
            ds.append(pd.DataFrame({'d': j['sum_a'] - j['sum_b'], 'n': j['size_b'], 'y': y}))
        dd = pd.concat(ds)
        est = dd['d'].sum() / dd['n'].sum()
        dv, nv = dd['d'].values, dd['n'].values
        bs = [dv[ix].sum() / nv[ix].sum() for ix in (rng.integers(0, len(dd), len(dd)) for _ in range(B))]
        wins = sum(1 for y in LS.YEARS if dd[dd.y == y]['d'].sum() < 0)
        per, perp = [], []
        for y in LS.YEARS[:-1]:
            f0 = frames[y]

            def col(nm):
                t = tabs[(nm, y)]['pitcher']
                t = t[t['n'] >= 300].reset_index().sort_values('n').drop_duplicates('pitcher', keep='last').set_index('pitcher')
                return -t['loc'].reindex(f0.index)
            d = f0.assign(a=col(n), b=col('fm_base')).dropna(subset=['a', 'b'])
            k = len(d)
            idx = np.vstack([np.arange(k)[None, :], rng.integers(0, k, size=(B, k))])
            V = {c: d[c].values.astype(float)[idx] for c in ('a', 'b', 'stuff', 'x', 'rv', 'w')}
            for store, g in ((per, pd.factorize(d['hand'] + d['role'])[0][idx]), (perp, None)):
                ra = sum(T2.wpartial(V['a'], V[tg], V['stuff'], V['w'], g) for tg in ('x', 'rv')) / 2
                rb = sum(T2.wpartial(V['b'], V[tg], V['stuff'], V['w'], g) for tg in ('x', 'rv')) / 2
                store.append((float(ra[0]), float((ra - rb)[0]), float((ra - rb)[1:].std())))
        f = lambda st: (np.mean([v[0] for v in st]), np.mean([v[1] for v in st]),
                        np.sqrt(sum(v[2] ** 2 for v in st)) / len(st), sum(v[1] > 0 for v in st))
        wi, po = f(per), f(perp)
        rs = []
        for y in LS.YEARS:
            t = tabs[(n, y)]['pitcher']
            h = t[(t['n_h0'] >= 150) & (t['n_h1'] >= 150)]
            rs.append(float(np.corrcoef(h['loc_h0'], h['loc_h1'])[0, 1]))
        sd = float(np.std(bs))
        out[n] = {'pitch': (est * 1e4, sd * 1e4, wins), 'within': wi, 'pooled': po, 'rel': float(np.mean(rs))}
        if n == 'fm_base':
            print(f'{n:<16s}{"BASE":>32s} | {f"level {wi[0]:.4f}":>42s} | {"":>16s} | {np.mean(rs):>7.3f}')
            continue
        zp = est / sd if sd else 0.0
        print(f'{n:<16s}{f"{est * 1e4:+.4f} ({zp:+.1f}) {wins}/6":>32s} | {f"{wi[1] * 1e4:+.1f} ({wi[1] / wi[2] if wi[2] else 0:+.1f}) {wi[3]}/5":>42s} | '
              f'{f"{po[1] * 1e4:+.1f} ({po[1] / po[2] if po[2] else 0:+.1f})":>16s} | {np.mean(rs):>7.3f}')
    json.dump(out, open(OUT + '.tmp', 'w'), indent=1, default=float)
    os.replace(OUT + '.tmp', OUT)


if __name__ == '__main__':
    {'run': run, 'report': report}[sys.argv[1]]()
