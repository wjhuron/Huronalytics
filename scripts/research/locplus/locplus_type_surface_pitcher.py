#!/usr/bin/env python3
"""locplus_type_surface_pitcher.py — own surfaces for the splitter and the sweeper: the
PITCHER-level read on the released Loc+ grade.

Loc+ scores ST / SV on the slider surfaces and FS on the changeup surfaces. On the released
kernel the pitch-level test (locplus_type_split_fit.py, 10 season pairs) says:
  parents fit better WITHOUT the children   CH without FS (9/10), SL without ST (9/10)
  children take only a light own surface    FS at w .25 (8/10), ST at w .25 (9/10 luck-neutral)
  the curveball must keep the knuckle curve (0/10 when split)
and the unit read by pitch type says the grade has a REVERSED next-season sign for the
splitter (+.42, se .105). This script reads the released grade's own decider for those
designs, with the production module as it is (shape classes and the far-miss rule on).

Per season, two bundles from pipeline.locplus on that season's own pitches:
  base    the released grade
  split   GROUP with ST and FS as groups of their own (SV stays with SL, KC with CU)
Each value has ITS OWN situation mean removed (a split group has its own cells), so a type's
level, which is stuff, cannot enter the grade. Arms, per pitch:
  par       parents (CH, SL types) take the split value; children keep the base value
  c25       children take .75 base + .25 split; parents keep the base value
  par_c25   both
  full      every pitch takes the split value

Reads: pitcher level (next season, Stuff+ held equal, within hand and role, 5 pairs, paired
bootstrap); split-half reliability; and BY PITCH TYPE the unit partial r with next-season
unit results (a working grade is NEGATIVE: the value is hitter-positive).

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/locplus_type_surface_pitcher.py
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
import locplus_fullseason_replicate as FR  # noqa: E402
import locplus_shape_loader as SL  # noqa: E402

CACHE = os.path.join(ROOT, 'data', '_loc_type_surface')
YEARS = list(range(2021, 2027))
SPLIT = {'ST': 'ST', 'FS': 'FS'}
CHILD = set(SPLIT)
PARENT_GROUPS = {'SL', 'CH'}
ARMS = ('base', 'par', 'c25', 'par_c25', 'full')
ORIG = dict(lp.GROUP)
B = 2000


def set_group(split):
    lp.GROUP.clear()
    lp.GROUP.update(ORIG)
    if split:
        lp.GROUP.update(SPLIT)


def season(y):
    ps = [p for p in SL.load_season(y) if lp.is_eligible_baseline(p)]
    dates = sorted({p['Game Date'] for p in ps if p['Game Date']})
    par = {d: i % 2 for i, d in enumerate(dates)}
    vals = {}
    for name, split in (('b', False), ('s', True)):
        set_group(split)
        S = lp.build_surfaces(ps, FR.LG, FR.SCALE)
        vals[name] = np.array([(lambda v: np.nan if v is None else v)(lp.location_value(p, S)) for p in ps], float)
        del S
    set_group(False)
    pt = np.array([p.get('_pt0') or p.get('Pitch Type') for p in ps])
    grp = np.array([ORIG.get(t, 'OTHER') for t in pt])
    d = pd.DataFrame({'pitcher': [p.get('Pitcher') for p in ps], 'throws': [p.get('Throws') for p in ps], 'pt': pt, 'g': grp,
                      'half': [par.get(p['Game Date'], 0) for p in ps], 'b': vals['b'], 's': vals['s']})
    del ps
    gc.collect()
    d = d[np.isfinite(d['b']) & np.isfinite(d['s'])]
    child = d['pt'].isin(CHILD).values
    parent = d['g'].isin(PARENT_GROUPS).values & ~child
    d['base'] = d['b']
    d['par'] = np.where(parent, d['s'], d['b'])
    d['c25'] = np.where(child, 0.75 * d['b'] + 0.25 * d['s'], d['b'])
    d['par_c25'] = np.where(parent, d['s'], d['c25'])
    d['full'] = d['s']
    g = d.groupby(['pitcher', 'throws'])
    t = g[list(ARMS)].mean()
    t['n'] = g.size()
    for h in (0, 1):
        gh = d[d['half'] == h].groupby(['pitcher', 'throws'])
        for a in ARMS:
            t[f'{a}_h{h}'] = gh[a].mean()
        t[f'n_h{h}'] = gh.size()
    u = d.groupby(['pitcher', 'pt'])
    ut = u[list(ARMS)].mean()
    ut['n'] = u.size()
    return {'pitcher': t, 'unit': ut}


def part(a, b, c):
    ra = a - np.polyval(np.polyfit(c, a, 1), c)
    rb = b - np.polyval(np.polyfit(c, b, 1), c)
    return float(np.corrcoef(ra, rb)[0, 1])


def report(tabs):
    import locplus_two_number_build as T2
    import stuff_gate_v2 as G
    rng = np.random.default_rng(0)
    print(f'\n{"arm":<9s}{"level":>8s}{"vs base":>10s}{"se":>8s}{"z":>6s}{"pairs":>7s} | {"pooled":>8s}{"se":>8s} | {"half r":>7s}   per pair')
    out = {}
    for arm in ARMS:
        per, perp = [], []
        for y in YEARS[:-1]:
            f0 = T2.pair_frame(y)
            f0 = f0[f0['role'] != 'NA']

            def col(nm):
                t = tabs[y]['pitcher']
                t = t[t['n'] >= 300].reset_index().sort_values('n').drop_duplicates('pitcher', keep='last').set_index('pitcher')
                return -t[nm].reindex(f0.index)
            d = f0.assign(a=col(arm), b=col('base')).dropna(subset=['a', 'b'])
            k = len(d)
            idx = np.vstack([np.arange(k)[None, :], rng.integers(0, k, size=(B, k))])
            V = {c: d[c].values.astype(float)[idx] for c in ('a', 'b', 'stuff', 'x', 'rv', 'w')}
            for store, grp in ((per, pd.factorize(d['hand'] + d['role'])[0][idx]), (perp, None)):
                ra = sum(T2.wpartial(V['a'], V[tg], V['stuff'], V['w'], grp) for tg in ('x', 'rv')) / 2
                rb = sum(T2.wpartial(V['b'], V[tg], V['stuff'], V['w'], grp) for tg in ('x', 'rv')) / 2
                store.append((float(ra[0]), float((ra - rb)[0]), float((ra - rb)[1:].std())))
        f = lambda st: (np.mean([v[0] for v in st]), np.mean([v[1] for v in st]), np.sqrt(sum(v[2] ** 2 for v in st)) / len(st), sum(v[1] > 0 for v in st))
        wi, po = f(per), f(perp)
        rs = []
        for y in YEARS:
            t = tabs[y]['pitcher']
            h = t[(t['n_h0'] >= 150) & (t['n_h1'] >= 150)]
            rs.append(float(np.corrcoef(h[f'{arm}_h0'], h[f'{arm}_h1'])[0, 1]))
        out[arm] = {'within': wi, 'pooled': po, 'rel': float(np.mean(rs))}
        z = wi[1] / wi[2] if wi[2] else 0.0
        print(f'{arm:<9s}{wi[0]:>8.4f}{wi[1]:>+10.4f}{wi[2]:>8.4f}{z:>+6.1f}{wi[3]:>5d}/5 | {po[1]:>+8.4f}{po[2]:>8.4f} | {np.mean(rs):>7.3f}   ' + ' '.join(f'{v[1]:+.4f}' for v in per))
    # by pitch type: unit partial r with the unit's next-season result, Stuff+ held equal
    rows = []
    for y in YEARS[:-1]:
        u = tabs[y]['unit']
        u = u[u['n'] >= 300]
        a = pd.read_pickle(G.agg_path('SHIPPED', y, 0))
        uy, uy1 = a['uy'].copy(), a['uy1'].copy()
        for t in (uy, uy1):
            t.index = t.index.set_names(['pitcher', 'pt'])
        j = u.join(uy.add_suffix('_y'), how='inner').join(uy1.add_suffix('_n'), how='inner')
        j = j[j['n_n'] >= 150].dropna(subset=['base', 's_y', 't_n']).reset_index()
        j['y'] = y
        rows.append(j)
    J = pd.concat(rows)
    print('\nby pitch type: unit location value against the unit result next season, partial on Stuff+ (NEGATIVE = the grade works); bootstrap se of the base')
    print(f'{"type":>5s}{"units":>7s}' + ''.join(f'{a:>10s}' for a in ARMS) + f'{"se":>8s}')
    for pt in ('FS', 'CH', 'ST', 'SL', 'SV', 'KC', 'CU', 'FC', 'FF', 'SI'):
        s = J[J['pt'] == pt].copy()
        if len(s) < 30:
            continue
        for c in list(ARMS) + ['s_y', 't_n']:
            s[c] = s[c] - s.groupby('y')[c].transform('mean')
        vals = [part(s[a].values, s['t_n'].values, s['s_y'].values) for a in ARMS]
        bs = []
        for _ in range(1000):
            i = rng.integers(0, len(s), len(s))
            bs.append(part(s['base'].values[i], s['t_n'].values[i], s['s_y'].values[i]))
        out[f'type:{pt}'] = dict(zip(ARMS, vals), n=len(s), se=float(np.std(bs)))
        print(f'{pt:>5s}{len(s):>7d}' + ''.join(f'{v:>+10.3f}' for v in vals) + f'{np.std(bs):>8.3f}')
    json.dump(out, open(os.path.join(CACHE, 'report.json'), 'w'), indent=1, default=float)


if __name__ == '__main__':
    os.makedirs(CACHE, exist_ok=True)
    tabs = {}
    for y in YEARS:
        fn = os.path.join(CACHE, f'tab_{y}.pkl')
        if not os.path.exists(fn):
            pickle.dump(season(y), open(fn + '.tmp', 'wb'))
            os.replace(fn + '.tmp', fn)
            print(f'{y}: built', flush=True)
            gc.collect()
        tabs[y] = pickle.load(open(fn, 'rb'))
    report(tabs)
