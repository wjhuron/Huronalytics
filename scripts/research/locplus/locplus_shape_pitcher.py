#!/usr/bin/env python3
"""locplus_shape_pitcher.py — the PITCHER-level read of shape-class Loc+ surfaces.

locplus_shape_split_fit.py found, held out by season at the pitch level, that
surfaces cut by the pitch's own movement class (arm p3: thirds of IVB, or of
arm-side HB for the sinker) fit better when BLENDED with the shipped surfaces:
FF and CH near w = 0.5 (10/10 pairs), SI and FC near 0.25, SL none, CU worse.
A pitch-level win does not decide a pitcher grade (failure log 2026-09-02), so
this script runs the released grade's own decider on the blend.

Per season, on that season's full surfaces as production (the surface pickles of
locplus_shape_split_fit.py are reused), per pitch:
    loc_g   released location value: grouped value minus its cell mean
    loc_s   class value minus the mean of ITS cell (class, hands, count), so the
            class's own level (which is stuff, not location) never enters
    loc     (1 - w_group) * loc_g + w_group * loc_s
Arms: base (w = 0), tuned (FF .5, CH .5, SI .25, FC .25), ffch (FF .5, CH .5).

Decider, the same as locplus_location_sweep.py report: season Y grade against
season Y+1 run value, partial on out-of-sample Stuff+, WITHIN pitcher hand and
role, mean of the luck-neutral and actual columns, paired pitcher bootstrap,
five pairs. Split-half reliability is a diagnostic. VALIDATION: the base arm is
compared with the released grade's table (data/_loc_location_sweep/s2_base_*).

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/locplus_shape_pitcher.py
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
import locplus_shape_split_fit as SS  # noqa: E402

CACHE = os.path.join(ROOT, 'data', '_loc_shape_split')
OUT = os.path.join(ROOT, 'data', '_loc_shape_pitcher.json')
YEARS = SS.YEARS
ARM = 'p3'
W = {'tuned': {'FF': 0.5, 'CH': 0.5, 'SI': 0.25, 'FC': 0.25}, 'ffch': {'FF': 0.5, 'CH': 0.5}}
B = 2000


def tab_path(y):
    return os.path.join(CACHE, f'pitcher_{y}.pkl')


def season(y):
    ps = SS.label([p for p in SS.load(y) if lp.is_eligible_baseline(p)])
    dates = sorted({p['Game Date'] for p in ps if p['Game Date']})
    par = {d: i % 2 for i, d in enumerate(dates)}
    rows = {}
    for arm in ('g', ARM):
        SS.set_arm(ps, arm)
        S = pickle.load(open(SS.surf_path(y, arm), 'rb'))
        rows[arm] = np.array([(lambda v: np.nan if v is None else v)(lp.location_value(p, S)) for p in ps], float)
        del S
    SS.set_arm(ps, 'g')
    d = pd.DataFrame({'pitcher': [p.get('Pitcher') for p in ps], 'throws': [p.get('Throws') for p in ps],
                      'pt': [p['_pt0'] for p in ps], 'g': [p['_g'] for p in ps],
                      'half': [par.get(p['Game Date'], 0) for p in ps], 'loc_g': rows['g'], 'loc_s': rows[ARM]})
    del ps
    gc.collect()
    d = d[np.isfinite(d['loc_g']) & np.isfinite(d['loc_s'])]
    d['base'] = d['loc_g']
    for name, wmap in W.items():
        w = d['g'].map(wmap).fillna(0.0)
        d[name] = (1 - w) * d['loc_g'] + w * d['loc_s']
    arms = ['base'] + list(W)
    g = d.groupby(['pitcher', 'throws'])
    t = g[arms].mean()
    t['n'] = g.size()
    for h in (0, 1):
        gh = d[d['half'] == h].groupby(['pitcher', 'throws'])
        for a in arms:
            t[f'{a}_h{h}'] = gh[a].mean()
        t[f'n_h{h}'] = gh.size()
    u = d.groupby(['pitcher', 'throws', 'pt'])
    ut = u[arms].mean()
    ut['n'] = u.size()
    ut['g'] = u['g'].first()
    pickle.dump({'pitcher': t, 'unit': ut}, open(tab_path(y) + '.tmp', 'wb'))
    os.replace(tab_path(y) + '.tmp', tab_path(y))
    return t


def report():
    import locplus_two_number_build as T2
    rng = np.random.default_rng(0)
    tabs = {y: pickle.load(open(tab_path(y), 'rb')) for y in YEARS}
    sweep = os.path.join(ROOT, 'data', '_loc_location_sweep')
    for y in (2022, 2025):
        fn = os.path.join(sweep, f's2_base_{y}.pkl')
        if os.path.exists(fn):
            ref = pickle.load(open(fn, 'rb'))['pitcher']
            j = tabs[y]['pitcher'][['base', 'n']].join(ref[['loc']], how='inner')
            j = j[j['n'] >= 300]
            print(f'VALIDATION {y}: base arm against the released grade table, {len(j)} pitchers 300+: r {np.corrcoef(j["base"], j["loc"])[0, 1]:.4f}')
    out = {}
    print(f'\n{"arm":<7s}{"level r":>9s}{"delta vs base":>16s}{"se":>8s}{"z":>6s}{"pairs":>7s} | {"pooled delta":>13s}{"se":>8s} | {"half r":>7s}{"SD x100":>9s}{"r with base":>12s}   per pair')
    for arm in ['base'] + list(W):
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
        f = lambda st: (np.mean([v[0] for v in st]), np.mean([v[1] for v in st]),
                        np.sqrt(sum(v[2] ** 2 for v in st)) / len(st), sum(v[1] > 0 for v in st))
        wi, po = f(per), f(perp)
        rs, sds, rb = [], [], []
        for y in YEARS:
            t = tabs[y]['pitcher']
            h = t[(t['n_h0'] >= 150) & (t['n_h1'] >= 150)]
            rs.append(float(np.corrcoef(h[f'{arm}_h0'], h[f'{arm}_h1'])[0, 1]))
            q = t[t['n'] >= 300]
            sds.append(float(q[arm].std() * 100))
            rb.append(float(np.corrcoef(q[arm], q['base'])[0, 1]))
        out[arm] = {'within': wi, 'pooled': po, 'half_r': float(np.mean(rs)), 'sd': float(np.mean(sds)), 'r_base': float(np.mean(rb)),
                    'per_pair': [v[1] for v in per]}
        z = wi[1] / wi[2] if wi[2] else 0.0
        print(f'{arm:<7s}{wi[0]:>9.4f}{wi[1]:>+16.4f}{wi[2]:>8.4f}{z:>+6.1f}{wi[3]:>5d}/5 | {po[1]:>+13.4f}{po[2]:>8.4f} | {np.mean(rs):>7.3f}{np.mean(sds):>9.3f}{np.mean(rb):>12.3f}   '
              + ' '.join(f'{v[1]:+.4f}' for v in per))
    # how far a pitcher and a pitch-type unit move, in grade points (10 points = one SD of the base grade)
    q = pd.concat([tabs[y]['pitcher'][tabs[y]['pitcher']['n'] >= 1000] for y in YEARS])
    mv = (q['tuned'] - q['base']) / q['base'].std() * 10
    print(f'\npitchers with 1,000+ pitches ({len(q)} seasons): tuned minus base in base-SD points: mean |move| {mv.abs().mean():.2f}, 90th pct {mv.abs().quantile(.9):.2f}, max {mv.abs().max():.2f}')
    u = pd.concat([tabs[y]['unit'][tabs[y]['unit']['n'] >= 300] for y in YEARS])
    for grp in ('FF', 'CH', 'SI', 'FC'):
        s = u[u['g'] == grp]
        m2 = (s['tuned'] - s['base']) / s['base'].std() * 10
        print(f'  {grp} units 300+ ({len(s)}): mean |move| {m2.abs().mean():.2f} points, 90th pct {m2.abs().quantile(.9):.2f}, max {m2.abs().max():.2f}, r with base {np.corrcoef(s["tuned"], s["base"])[0, 1]:.3f}')
    json.dump(out, open(OUT + '.tmp', 'w'), indent=1, default=float)
    os.replace(OUT + '.tmp', OUT)
    print(f'\nwrote {OUT}')


if __name__ == '__main__':
    for y in YEARS:
        if not os.path.exists(tab_path(y)):
            season(y)
            print(f'{y}: pitcher table built', flush=True)
            gc.collect()
    report()
