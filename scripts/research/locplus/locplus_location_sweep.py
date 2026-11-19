#!/usr/bin/env python3
"""locplus_location_sweep.py — smoothing bandwidth for the LOCATION grade.

The location grade (2026-11-18 build) is, per pitch,
    value with the ball in play in count currency
    minus the league mean of that value for the pitch's (group, batter hand, pitcher hand, count).
It holds no count level, no matchup level and no hand level, so the trap that
bent every earlier bandwidth test is gone: a wider kernel can no longer win by
turning the grade into the count mix. This sweeps the kernel again on that grade.

Per config (PHYS_X_IN, PHYS_Z_FRAC; every K as shipped) and season 2021-2026:
  pitcher  full-season surfaces (as production). Season mean of the location part
           per pitcher, and the same on odd and even game dates.
  pitch    surfaces built on even dates score odd dates and the reverse. Squared
           error of the count-currency value against the pitch's actual hitter
           run value (-RunExp), summed by game date (the bootstrap block).

DECIDERS, fixed before the run:
  the grade is a pitcher grade, so the PITCHER objective decides: next season,
  partial on Stuff+, within pitcher hand and role, mean of the luck-neutral and
  actual run-value columns, against the shipped bandwidth (6 in / 0.30), paired
  pitcher bootstrap. A config must not fit held-out PITCHES worse than shipped.
  Split-half reliability is printed as a diagnostic only.
Name the case when reading: an interior optimum, the best on the grid, or flat.

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/locplus_location_sweep.py run [--procs 2]
  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/locplus_location_sweep.py report
"""
import argparse
import gc
import json
import os
import pickle
import sys
from collections import defaultdict
from multiprocessing import Pool

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'stuff'))
import pipeline.locplus as lp  # noqa: E402
import locplus_fullseason_replicate as FR  # noqa: E402

CACHE = os.path.join(ROOT, 'data', '_loc_location_sweep')
XS = (2.0, 3.0, 4.5, 6.0, 9.0)
ZS = (0.12, 0.17, 0.22, 0.30, 0.40)
YEARS = list(range(2021, 2027))
SHIP = (6.0, 0.30)
B = 1000


def cname(bx, bz):
    return f'x{bx:g}_z{bz:g}'


def tab_path(name, y):
    return os.path.join(CACHE, f'{name}_{y}.pkl')


def value(S, off, pre):
    """Count-currency expected value for precomputed (key, count, i, j, bats) rows."""
    RV, SW, WH, FL, XW, XO, PCS = S['RV'], S['SW'], S['WH'], S['FL'], S['XW'], S['XWOFF'], S['PCS']
    rw, rf, rc, rb = RV['whiff'], RV['foul'], RV['cs'], RV['ball']
    out = np.empty(len(pre))
    for n, (key, c, i, j, bats) in enumerate(pre):
        if key not in WH:
            out[n] = np.nan
            continue
        psw, pwh, pfl = SW[key][c][i][j], WH[key][c][i][j], FL[key][i][j]
        pbip = max(0.0, 1.0 - pwh - pfl)
        vbip = XW[key][i][j] + XO.get(c, 0.0) + off.get(c, 0.0)
        pcs = PCS[bats][c][i][j]
        sv = pwh * rw.get(c, 0.0) + pfl * rf.get(c, 0.0) + pbip * vbip
        tv = pcs * rc.get(c, 0.0) + (1 - pcs) * rb.get(c, 0.0)
        out[n] = psw * sv + (1 - psw) * tv
    return out


def season_job(y):
    os.makedirs(CACHE, exist_ok=True)
    todo = [(bx, bz) for bx in XS for bz in ZS if not os.path.exists(tab_path(cname(bx, bz), y))]
    if not todo:
        return y, 0
    pitches = FR.load_season(y)
    base_p = [p for p in pitches if lp.is_eligible_baseline(p)]
    del pitches
    gc.collect()
    dates = sorted({p['Game Date'] for p in base_p if p['Game Date']})
    par = {d: i % 2 for i, d in enumerate(dates)}
    pre, meta = [], []
    for p in base_p:
        c = lp.get_count(p)
        px, zn = lp.safe_float(p.get('PlateX')), lp._znorm(p)
        if c is None or px is None or zn is None:
            continue
        key = (lp.group_of(p), p.get('Bats'), p.get('Throws'))
        re = lp.safe_float(p.get('RunExp'))
        pre.append((key, c, lp._xbin(px), lp._zbin(zn), p['Bats']))
        meta.append((p.get('Pitcher'), p.get('Throws'), key + (c,), par.get(p['Game Date'], 0), p['Game Date'],
                     (-re if re is not None else np.nan)))
    m = pd.DataFrame(meta, columns=['pitcher', 'throws', 'cell', 'half', 'date', 'y'])
    fold_base = {f: [p for p in base_p if par.get(p['Game Date']) != f] for f in (0, 1)}
    off_full = lp.build_bip_count_offsets(base_p, FR.LG, FR.SCALE)
    off_fold = {f: lp.build_bip_count_offsets(fold_base[f], FR.LG, FR.SCALE) for f in (0, 1)}
    half = m['half'].values
    for bx, bz in todo:
        FR.apply({'PHYS_X_IN': bx, 'PHYS_Z_FRAC': bz})
        try:
            v = value(lp.build_surfaces(base_p, FR.LG, FR.SCALE), off_full, pre)
            oos = np.full(len(pre), np.nan)
            for f in (0, 1):
                Sf = lp.build_surfaces(fold_base[f], FR.LG, FR.SCALE)
                idx = np.where(half == f)[0]
                oos[idx] = value(Sf, off_fold[f], [pre[i] for i in idx])
                del Sf
        finally:
            FR.restore()
        d = m.assign(v=v)
        d = d[np.isfinite(d['v'])]
        d['loc'] = d['v'] - d.groupby('cell')['v'].transform('mean')
        g = d.groupby(['pitcher', 'throws'])
        t = pd.DataFrame({'loc': g['loc'].mean(), 'n': g.size()})
        for h in (0, 1):
            gh = d[d['half'] == h].groupby(['pitcher', 'throws'])
            t[f'loc_h{h}'], t[f'n_h{h}'] = gh['loc'].mean(), gh.size()
        e = (m['y'].values - oos) ** 2
        ok = np.isfinite(e)
        sse = pd.DataFrame({'date': m['date'].values[ok], 'e': e[ok]}).groupby('date')['e'].agg(['sum', 'size'])
        tmp = tab_path(cname(bx, bz), y) + '.tmp'
        pickle.dump({'pitcher': t, 'sse': sse}, open(tmp, 'wb'))
        os.replace(tmp, tab_path(cname(bx, bz), y))
    return y, len(todo)


# ── stage 2: at the chosen kernel, one thing changed per arm ───────────────
BASE2 = {'PHYS_X_IN': 2.0, 'PHYS_Z_FRAC': 0.12}
FLAT_K = ('K_WHIFF', 'K_FOUL', 'K_XWCON', 'K_SWING_COLL', 'K_CS')      # a location surface toward its scalar mean
COUNT_K = ('K_WH_COUNT', 'K_SWING_COUNT')                              # a per-count surface toward the collapsed one
SPLIT = {'ST': 'ST', 'FS': 'FS', 'KC': 'KC'}
CHILD = set(SPLIT)
FAR = (18.0, 0.75, 0.45)      # inches off centre, zone-heights below, above: the 2026-09-19 pitch-level optima


def _k(a, b):
    d = dict(BASE2)
    d.update({k: FR.ORIG[k] * a for k in FLAT_K})
    d.update({k: FR.ORIG[k] * b for k in COUNT_K})
    return d


ARMS2 = {
    's2_base': (BASE2, None),
    's2_a0.05': (_k(0.05, 1), None), 's2_a0.25': (_k(0.25, 1), None), 's2_a4': (_k(4, 1), None),
    's2_b0.25': (_k(1, 0.25), None), 's2_b4': (_k(1, 4), None), 's2_a0.25_b0.25': (_k(0.25, 0.25), None),
    's2_hier': (BASE2, 'hier'),      # CH / SL / CU surfaces built WITHOUT FS / ST / KC; the small types keep the pooled surface
    's2_far': (BASE2, 'far'),        # beyond FAR a pitch takes the count's ball value
}


def season_job2(y):
    os.makedirs(CACHE, exist_ok=True)
    todo = [n for n in ARMS2 if not os.path.exists(tab_path(n, y))]
    if not todo:
        return y, 0
    pitches = FR.load_season(y)
    base_p = [p for p in pitches if lp.is_eligible_baseline(p)]
    del pitches
    gc.collect()
    dates = sorted({p['Game Date'] for p in base_p if p['Game Date']})
    par = {d: i % 2 for i, d in enumerate(dates)}
    orig_group = dict(lp.GROUP)
    pre, pre_s, meta, far, child = [], [], [], [], []
    for p in base_p:
        c = lp.get_count(p)
        px, zn = lp.safe_float(p.get('PlateX')), lp._znorm(p)
        if c is None or px is None or zn is None:
            continue
        pt = p.get('Pitch Type')
        g = lp.group_of(p)
        gs = SPLIT.get(pt, g)
        i, j = lp._xbin(px), lp._zbin(zn)
        re = lp.safe_float(p.get('RunExp'))
        pre.append(((g, p.get('Bats'), p.get('Throws')), c, i, j, p['Bats']))
        pre_s.append(((gs, p.get('Bats'), p.get('Throws')), c, i, j, p['Bats']))
        child.append(pt in CHILD)
        far.append(abs(px) * 12.0 > FAR[0] or zn < -FAR[1] or zn > 1.0 + FAR[2])
        meta.append((p.get('Pitcher'), p.get('Throws'), (g, p.get('Bats'), p.get('Throws'), c), par.get(p['Game Date'], 0),
                     p['Game Date'], (-re if re is not None else np.nan), c))
    m = pd.DataFrame(meta, columns=['pitcher', 'throws', 'cell', 'half', 'date', 'y', 'count'])
    child, far = np.array(child), np.array(far)
    half = m['half'].values
    fold_base = {f: [p for p in base_p if par.get(p['Game Date']) != f] for f in (0, 1)}

    def build(rows, split):
        lp.GROUP.clear(); lp.GROUP.update(orig_group)
        if split:
            lp.GROUP.update(SPLIT)
        try:
            return lp.build_surfaces(rows, FR.LG, FR.SCALE)
        finally:
            lp.GROUP.clear(); lp.GROUP.update(orig_group)

    def score(rows, idx, flag):
        off = lp.build_bip_count_offsets(rows, FR.LG, FR.SCALE)
        S = build(rows, False)
        v = value(S, off, [pre[i] for i in idx])
        if flag == 'hier':
            Ss = build(rows, True)
            vs = value(Ss, off, [pre_s[i] for i in idx])
            par_ = ~child[idx]
            v = np.where(par_, vs, v)          # parents from the surfaces built without the small types
        if flag == 'far':
            ball = np.array([S['RV']['ball'].get(c, 0.0) for c in m['count'].values[idx]])
            v = np.where(far[idx], ball, v)
        return v

    allidx = np.arange(len(pre))
    for name in todo:
        cfg, flag = ARMS2[name]
        FR.apply(cfg)
        try:
            v = score(base_p, allidx, flag)
            oos = np.full(len(pre), np.nan)
            for f in (0, 1):
                idx = np.where(half == f)[0]
                oos[idx] = score(fold_base[f], idx, flag)
        finally:
            FR.restore()
        d = m.assign(v=v)
        d = d[np.isfinite(d['v'])]
        d['loc'] = d['v'] - d.groupby('cell')['v'].transform('mean')
        g = d.groupby(['pitcher', 'throws'])
        t = pd.DataFrame({'loc': g['loc'].mean(), 'n': g.size()})
        for h in (0, 1):
            gh = d[d['half'] == h].groupby(['pitcher', 'throws'])
            t[f'loc_h{h}'], t[f'n_h{h}'] = gh['loc'].mean(), gh.size()
        e = (m['y'].values - oos) ** 2
        ok = np.isfinite(e)
        sse = pd.DataFrame({'date': m['date'].values[ok], 'e': e[ok]}).groupby('date')['e'].agg(['sum', 'size'])
        tmp = tab_path(name, y) + '.tmp'
        pickle.dump({'pitcher': t, 'sse': sse}, open(tmp, 'wb'))
        os.replace(tmp, tab_path(name, y))
    return y, len(todo)


def run2(procs):
    with Pool(procs) as pool:
        for y, n in pool.imap_unordered(season_job2, YEARS):
            print(f'{y}: {n} stage-2 arms built', flush=True)


def _init(xs, zs):
    global XS, ZS
    XS, ZS = xs, zs


def run(procs):
    with Pool(procs, initializer=_init, initargs=(XS, ZS)) as pool:
        for y, n in pool.imap_unordered(season_job, YEARS):
            print(f'{y}: {n} configs built', flush=True)


# ── report ─────────────────────────────────────────────────────────────────
def report():
    import locplus_two_number_build as T2
    import stuff_gate_v2 as G
    rng = np.random.default_rng(0)
    names = [cname(bx, bz) for bx in XS for bz in ZS
             if all(os.path.exists(tab_path(cname(bx, bz), y)) for y in YEARS)]     # cells never run stay blank
    ship = cname(*SHIP)
    tabs = {(n, y): pickle.load(open(tab_path(n, y), 'rb')) for n in set(names) | {ship} for y in YEARS
            if os.path.exists(tab_path(n, y))}
    out = {}
    # pitch level: MSE minus shipped, date-block bootstrap pooled over seasons
    pitch = {}
    for n in names:
        ds = []
        for y in YEARS:
            a, b = tabs[(n, y)]['sse'], tabs[(ship, y)]['sse']
            j = a.join(b, lsuffix='_a', rsuffix='_b', how='inner')
            ds.append(pd.DataFrame({'d': j['sum_a'] - j['sum_b'], 'n': j['size_b'], 'y': y}))
        dd = pd.concat(ds)
        est = dd['d'].sum() / dd['n'].sum()
        bs = []
        dv, nv = dd['d'].values, dd['n'].values
        for _ in range(B):
            ix = rng.integers(0, len(dd), len(dd))
            bs.append(dv[ix].sum() / nv[ix].sum())
        wins = sum(1 for y in YEARS if dd[dd.y == y]['d'].sum() < 0)
        pitch[n] = (est * 1e4, np.std(bs) * 1e4, wins)
    # pitcher level
    frames = {}
    for y in YEARS[:-1]:
        f0 = T2.pair_frame(y)
        f0 = f0[f0['role'] != 'NA']
        frames[y] = f0
    pit, rel = {}, {}
    for n in names:
        per, perp = [], []
        for y in YEARS[:-1]:
            f0 = frames[y]

            def col(nm):
                t = tabs[(nm, y)]['pitcher']
                t = t[t['n'] >= 300].reset_index().sort_values('n').drop_duplicates('pitcher', keep='last').set_index('pitcher')
                return -t['loc'].reindex(f0.index)
            d = f0.assign(a=col(n), b=col(ship)).dropna(subset=['a', 'b'])
            k = len(d)
            idx = np.vstack([np.arange(k)[None, :], rng.integers(0, k, size=(B, k))])
            V = {c: d[c].values.astype(float)[idx] for c in ('a', 'b', 'stuff', 'x', 'rv', 'w')}
            for store, g in ((per, pd.factorize(d['hand'] + d['role'])[0][idx]), (perp, None)):
                ra = sum(T2.wpartial(V['a'], V[tg], V['stuff'], V['w'], g) for tg in ('x', 'rv')) / 2
                rb = sum(T2.wpartial(V['b'], V[tg], V['stuff'], V['w'], g) for tg in ('x', 'rv')) / 2
                store.append((float(ra[0]), float((ra - rb)[0]), float((ra - rb)[1:].std())))
        f = lambda st: (np.mean([v[0] for v in st]), np.mean([v[1] for v in st]),
                        np.sqrt(sum(v[2] ** 2 for v in st)) / len(st), sum(v[1] > 0 for v in st))
        pit[n] = {'within': f(per), 'pooled': f(perp)}
        rs = []
        for y in YEARS:
            t = tabs[(n, y)]['pitcher']
            h = t[(t['n_h0'] >= 150) & (t['n_h1'] >= 150)]
            rs.append(float(np.corrcoef(h['loc_h0'], h['loc_h1'])[0, 1]))
        rel[n] = float(np.mean(rs))

    def grid(title, fn):
        print(f'\n{title}')
        print('  x_in \\ z ' + ''.join(f'{z:>20.2f}' for z in ZS))
        for bx in XS:
            print(f'  {bx:>8.1f} ' + ''.join(f'{(fn(cname(bx, bz)) if cname(bx, bz) in names else ""):>20s}' for bz in ZS))
    grid('PITCHER: next-season partial r of the location part, within hand and role (level)',
         lambda n: f'{pit[n]["within"][0]:.4f}')
    grid('PITCHER: delta vs shipped 6 / 0.30, within hand and role, x 1e4 (z) pairs won',
         lambda n: 'SHIPPED' if n == ship else f'{pit[n]["within"][1] * 1e4:+.0f} ({pit[n]["within"][1] / pit[n]["within"][2]:+.1f}) {pit[n]["within"][3]}/5')
    grid('PITCHER, pooled frame: delta vs shipped x 1e4 (z)',
         lambda n: 'SHIPPED' if n == ship else f'{pit[n]["pooled"][1] * 1e4:+.0f} ({pit[n]["pooled"][1] / pit[n]["pooled"][2]:+.1f})')
    grid('PITCH: held-out squared error vs actual run value, minus shipped, x 1e4 (z) seasons better',
         lambda n: 'SHIPPED' if n == ship else f'{pitch[n][0]:+.3f} ({pitch[n][0] / pitch[n][1]:+.1f}) {pitch[n][2]}/6')
    grid('diagnostic: split-half reliability of the location part (150+ pitches per half)', lambda n: f'{rel[n]:.3f}')
    for n in names:
        out[n] = {'pitcher_within': pit[n]['within'], 'pitcher_pooled': pit[n]['pooled'], 'pitch': pitch[n], 'rel': rel[n]}
    json.dump(out, open(os.path.join(CACHE, 'report.json'), 'w'), indent=1, default=float)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['run', 'report', 'run2'])
    ap.add_argument('--procs', type=int, default=2)
    ap.add_argument('--xs', default=None, help='comma list of PHYS_X_IN values (default: the first grid)')
    ap.add_argument('--zs', default=None, help='comma list of PHYS_Z_FRAC values')
    a = ap.parse_args()
    if a.xs:
        XS = tuple(float(v) for v in a.xs.split(','))
    if a.zs:
        ZS = tuple(float(v) for v in a.zs.split(','))
    {'run': lambda: run(a.procs), 'run2': lambda: run2(a.procs), 'report': report}[a.cmd]()
