#!/usr/bin/env python3
"""locplus_farmiss_branch_check.py — the far-miss rule in the BRANCH code, shape classes on.

locplus_farmiss_location.py measured the rule on the group surfaces only (its harness
has its own fast scoring path). This runs the branch module itself, end to end, with
the shape-class blend on, twice per season on that season's own surfaces:
  off   FAR_MISS_* at infinity = the live grade
  on    the branch constants
and reads the released decider (next season, Stuff+ held equal, within pitcher hand
and role, five pairs, paired pitcher bootstrap) plus split-half reliability.

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/locplus_farmiss_branch_check.py /path/to/branch
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
import locplus_fullseason_replicate as FR  # noqa: E402
import locplus_shape_loader as SL  # noqa: E402

CACHE = os.path.join(ROOT, 'data', '_loc_farmiss_branch')
YEARS = list(range(2021, 2027))
B = 2000
INF = float('inf')


def season(BR, y, cut):
    ps = [p for p in SL.load_season(y) if BR.is_eligible_baseline(p)]
    dates = sorted({p['Game Date'] for p in ps if p['Game Date']})
    par = {d: i % 2 for i, d in enumerate(dates)}
    cols = {}
    for name, c in (('off', (INF, INF, INF)), ('on', cut)):
        BR.FAR_MISS_X_IN, BR.FAR_MISS_Z_LO, BR.FAR_MISS_Z_HI = c
        S = BR.build_surfaces(ps, FR.LG, FR.SCALE)
        cols[name] = np.array([(lambda v: np.nan if v is None else v)(BR.location_value(p, S)) for p in ps], float)
        del S
    BR.FAR_MISS_X_IN, BR.FAR_MISS_Z_LO, BR.FAR_MISS_Z_HI = cut
    d = pd.DataFrame({'pitcher': [p.get('Pitcher') for p in ps], 'throws': [p.get('Throws') for p in ps],
                      'half': [par.get(p['Game Date'], 0) for p in ps], **cols})
    del ps
    gc.collect()
    d = d[np.isfinite(d['off']) & np.isfinite(d['on'])]
    changed = float((np.abs(d['on'] - d['off']) > 1e-12).mean())
    g = d.groupby(['pitcher', 'throws'])
    t = g[['off', 'on']].mean()
    t['n'] = g.size()
    for h in (0, 1):
        gh = d[d['half'] == h].groupby(['pitcher', 'throws'])
        for a in ('off', 'on'):
            t[f'{a}_h{h}'] = gh[a].mean()
        t[f'n_h{h}'] = gh.size()
    return t, changed


def main():
    BR = SL.branch(sys.argv[1])
    cut = (BR.FAR_MISS_X_IN, BR.FAR_MISS_Z_LO, BR.FAR_MISS_Z_HI)
    os.makedirs(CACHE, exist_ok=True)
    tabs = {}
    for y in YEARS:
        fn = os.path.join(CACHE, f'pitcher_{y}.pkl')
        if not os.path.exists(fn):
            t, ch = season(BR, y, cut)
            pickle.dump({'t': t, 'changed': ch}, open(fn, 'wb'))
            print(f'{y}: built; share of pitches the cell means or the rule moved {ch:.3f}', flush=True)
        tabs[y] = pickle.load(open(fn, 'rb'))['t']
    import locplus_two_number_build as T2
    rng = np.random.default_rng(0)
    per, perp = [], []
    for y in YEARS[:-1]:
        f0 = T2.pair_frame(y)
        f0 = f0[f0['role'] != 'NA']

        def col(nm):
            t = tabs[y]
            t = t[t['n'] >= 300].reset_index().sort_values('n').drop_duplicates('pitcher', keep='last').set_index('pitcher')
            return -t[nm].reindex(f0.index)
        d = f0.assign(a=col('on'), b=col('off')).dropna(subset=['a', 'b'])
        k = len(d)
        idx = np.vstack([np.arange(k)[None, :], rng.integers(0, k, size=(B, k))])
        V = {c: d[c].values.astype(float)[idx] for c in ('a', 'b', 'stuff', 'x', 'rv', 'w')}
        for store, grp in ((per, pd.factorize(d['hand'] + d['role'])[0][idx]), (perp, None)):
            ra = sum(T2.wpartial(V['a'], V[tg], V['stuff'], V['w'], grp) for tg in ('x', 'rv')) / 2
            rb = sum(T2.wpartial(V['b'], V[tg], V['stuff'], V['w'], grp) for tg in ('x', 'rv')) / 2
            store.append((float(rb[0]), float((ra - rb)[0]), float((ra - rb)[1:].std())))
    f = lambda st: (np.mean([v[0] for v in st]), np.mean([v[1] for v in st]), np.sqrt(sum(v[2] ** 2 for v in st)) / len(st), sum(v[1] > 0 for v in st))
    wi, po = f(per), f(perp)
    rel = {a: float(np.mean([np.corrcoef(*(lambda h: (h[f'{a}_h0'], h[f'{a}_h1']))(tabs[y][(tabs[y]['n_h0'] >= 150) & (tabs[y]['n_h1'] >= 150)]))[0, 1]
                             for y in YEARS])) for a in ('off', 'on')}
    q = pd.concat([tabs[y][tabs[y]['n'] >= 1000] for y in YEARS])
    mv = (q['on'] - q['off']) / q['off'].std() * 10
    print(f'\nrule {cut[0]:g} in / {cut[1]:g} low / {cut[2]:g} high, shape classes on')
    print(f'PITCHER within hand and role: live level {wi[0]:.4f}, rule minus live {wi[1]:+.4f} (se {wi[2]:.4f}, z {wi[1] / wi[2]:+.1f}), pairs {wi[3]}/5; per pair '
          + ' '.join(f'{v[1]:+.4f}' for v in per))
    print(f'PITCHER pooled: rule minus live {po[1]:+.4f} (se {po[2]:.4f})')
    print(f'split-half r: live {rel["off"]:.3f}, rule {rel["on"]:.3f}')
    print(f'pitchers with 1,000+ pitches ({len(q)} seasons): move in grade points (10 = one SD): mean |move| {mv.abs().mean():.2f}, 90th pct {mv.abs().quantile(.9):.2f}, '
          f'max {mv.abs().max():.2f}; r with the live grade {np.corrcoef(q["on"], q["off"])[0, 1]:.4f}')
    json.dump({'within': wi, 'pooled': po, 'rel': rel, 'cut': cut}, open(os.path.join(CACHE, 'report.json'), 'w'), indent=1, default=float)


if __name__ == '__main__':
    main()
