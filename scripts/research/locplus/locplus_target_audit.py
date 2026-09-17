#!/usr/bin/env python3
"""locplus_target_audit.py — does a Loc+ verdict depend on the TARGET it is
graded against? (2026-09-17, companion to stuff/stuff_gate_target_audit.py)

Every pitcher-level Loc+ decision was read on ONE target: second-half
luck-neutral xRV of the SAME season (locplus_fullseason_replicate.py). That
target is modelled (xwOBA on balls in play, the same quantity Loc+'s contact
surface is built from), it is within-season, and its only standard error is
the spread of six season deltas. This script asks whether the verdict holds
on the targets nobody looked at:

  within  first-half Loc+ (surfaces on the full season, as production) vs
          the second half's  x  luck-neutral xRV   (the shipped decider)
                             rv ACTUAL run value   (-RunExp, luck included)
  next    full-season Loc+ of year Y vs year Y+1's x and rv (five pairs;
          2025->2026 scores a partial season). Loc+ had no next-season test.

Protocol is the replicate's, imported from it (surfaces, scoring, anchors,
config setter, season loader), so the 'within / x' column reproduces its
stored numbers: that is the validation, printed first.

`run` scores each (config, season) ONCE and caches a per-pitcher table in
data/_loc_target_audit/. `summary` reads only those tables: delta r vs
shipped per season, a PAIRED pitcher bootstrap SE (the replicate had none),
pooled across seasons, on both units (raw ExpRV mean, rendered atom mean)
and both targets, plus the FF-velocity partial. Target dependence is tested
on the EXCESS d_rv - rho * d_x with rho = r(x, rv) over the same pitchers:
actual RV is the luck-neutral target plus noise, so every delta shrinks by
rho on it, and the plain difference is not evidence of anything.

STUFF CONTROL. A pitcher-level Loc+ objective can be gamed by a surface
that absorbs stuff: smoothing location away leaves pitch-type and count
levels, which track how good the arm is. The replicate's control is FF
velocity alone. Here every delta is also read with the pitcher's Stuff+
partialled out: the gate v2 SHIPPED aggregate of season Y (seed 0), an
out-of-sample grade (the model never saw Y or Y+1). It exists for Y in
2021..2025, so the 2026 within-season row has no stuff-partial column.

For 2026 the gate has no aggregate of its own, so the control is the
PRODUCTION Stuff+ (`stuffScore` in data/pitcher_leaderboard_rs.json, MLB rows,
the row with the most pitches per name). It is pitcher-grouped out-of-fold,
not season-held-out; as a control variable that is enough, and it is said
here so nobody reads the 2026 row as identical in kind to 2021-2025.

THROUGH-SEASON CHECK (`run-cut`, `summary --cut f`). The audit above builds
surfaces on the FULL season. Production builds them on whatever the season
has so far. `run-cut` rebuilds everything at a cutoff (fraction f of the
season's dates): surfaces, anchors and the pitcher's Loc+ use ONLY pitches
through the cutoff, and the target is the REST of that season. Tables are
named <config>@c<f>; `summary --cut f` compares them against shipped@c<f>.

Floors: within keeps the replicate's (150 scored / 150 actual / 40 FF).
next uses 300 pitches in each season, the Stuff+ gate's MIN_NXT, a
convention borrowed so the two audits read on the same population rule,
plus the same 40-FF floor (the velocity partial needs it; like the
replicate, this drops pitchers without a four-seamer from every column).

Usage:
  python3 scripts/research/locplus/locplus_target_audit.py run \\
      --config w4.5=4.5:0.22 --config w9=9:0.40 [--seasons 2021,2022]
  python3 scripts/research/locplus/locplus_target_audit.py summary
A --config is PHYS_X_IN:PHYS_Z_FRAC[:kmA[:kmB]]. kmA multiplies the shipped
FLAT-PRIOR K's (K_WHIFF, K_FOUL, K_XWCON, K_SWING_COLL, K_CS: a location
surface shrunk toward its scalar mean), kmB the COUNT K's (K_WH_COUNT,
K_SWING_COUNT: a per-count surface shrunk toward the collapsed surface);
kmB defaults to kmA, both default to 1. The kernel is unnormalized, so a K is
in kernel-weighted units and weakens as the bandwidth grows (kernel mass
2*pi*sx*sz cells: 56 at 6/0.30, 155 at 9/0.55); that is why K is swept
JOINTLY with the bandwidth. Name such configs x<bx>_z<bz>_a<kmA>_b<kmB>; a
bare x<bx>_z<bz> is a1_b1.
A --kset is name=bx:bz:K_WHIFF:K_WH_COUNT:K_FOUL:K_XWCON:K_SWING_COLL:
K_SWING_COUNT:K_CS (absolute values, the replicate's order).
DECIDER (declared 2026-09-17 before the joint sweep ran): next season,
Stuff+ partialled, rendered unit, mean of the xRV and actual-RV deltas
('ren_avg_pstuff'; the equal weighting is a convention), and the config must
not lose on any of the four Stuff+-partialled columns. `summary` also runs a
leave-one-pair-out selection: the argmax of the decider on four pairs is
scored on the fifth, which is the honest gain of "pick the best of N".
A --flag is name=ATTR:VALUE, one pipeline.locplus module attribute flipped at
the shipped bandwidth (e.g. --flag noCS=CS_COUNT_TRANSFORM:0), restored after.
"""
import argparse
import gc
import json
import math
import os
import sys
import time
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline.locplus as lp                           # noqa: E402
import locplus_constants_multiseason as base            # noqa: E402
import locplus_fullseason_replicate as FR               # noqa: E402
from pipeline.sdplus import make_rv_xrv                 # noqa: E402

CACHE = os.path.join(ROOT, 'data', '_loc_target_audit')
OUT = os.path.join(CACHE, 'summary.json')
MIN_NXT = 300            # convention: the Stuff+ gate's next-season floor
PARTIAL_Y = 2025
BOOT_B = 2000


def table_path(name, yr):
    return os.path.join(CACHE, f'tab_{name}_{yr}.pkl')


def _mean(v):
    return (sum(v) / len(v), len(v)) if v else (float('nan'), 0)


def targets(base_p, first_dates, rv_x):
    """Per pitcher, config-independent: second-half and full-season means of
    both targets, and FF velocity (first half, full)."""
    acc = defaultdict(lambda: defaultdict(list))
    for p in base_p:
        k = (p.get('Pitcher'), p.get('Throws'))
        first = p['Game Date'] in first_dates
        x = rv_x(p)
        re = lp.safe_float(p.get('RunExp'))
        rv = -re if re is not None else None        # hitter-positive, as rv_x
        for tag, v in (('x', x), ('rv', rv)):
            if v is not None:
                acc[k][f'{tag}_full'].append(v)
                if not first:
                    acc[k][f'{tag}_2h'].append(v)
        if p['Pitch Type'] == 'FF':
            ve = lp.safe_float(p['Velocity'])
            if ve is not None:
                acc[k]['velo_full'].append(ve)
                if first:
                    acc[k]['velo_1h'].append(ve)
    rows = {}
    for k, d in acc.items():
        r = {}
        for c in ('x_full', 'x_2h', 'rv_full', 'rv_2h', 'velo_full', 'velo_1h'):
            r[c], r['n_' + c] = _mean(d.get(c, []))
        rows[k] = r
    return rows


def score_config(base_p, scorable, first_dates):
    """Per pitcher Loc+ for the config currently applied to pipeline.locplus:
    raw ExpRV mean and rendered atom mean, first half and full season."""
    S = lp.build_surfaces(base_p, FR.LG, FR.SCALE)
    scored = []
    for p in scorable:
        v = lp.score_pitch(p, S)
        if v is not None:
            scored.append((p, v))
    anc = FR.group_anchors(scored)
    acc = defaultdict(lambda: defaultdict(list))
    for p, v in scored:
        k = (p.get('Pitcher'), p.get('Throws'))
        a = anc.get(lp.group_of(p))
        atom = int(round(100.0 - lp.LOC_SCALE_K * (v - a[0]) / a[1])) if a else None
        halves = ('full', '1h') if p['Game Date'] in first_dates else ('full',)
        for h in halves:
            acc[k][f'raw_{h}'].append(v)
            if atom is not None:
                acc[k][f'ren_{h}'].append(atom)
    rows = {}
    for k, d in acc.items():
        r = {}
        for c in ('raw_full', 'raw_1h', 'ren_full', 'ren_1h'):
            r[c], r['n_' + c] = _mean(d.get(c, []))
        rows[k] = r
    return rows


def run(configs, seasons):
    os.makedirs(CACHE, exist_ok=True)
    rv_x = make_rv_xrv(FR.LG, FR.SCALE)
    for yr in seasons:
        todo = [n for n in configs if not os.path.exists(table_path(n, yr))]
        if not todo:
            print(f'=== {yr}: every table cached', flush=True)
            continue
        t0 = time.time()
        pitches = FR.load_season(yr)
        base_p = [p for p in pitches if lp.is_eligible_baseline(p)]
        scorable = [p for p in pitches if lp._is_scorable(p)]
        dates = sorted({p['Game Date'] for p in base_p if p['Game Date']})
        first_dates = set(dates[:len(dates) // 2])
        tg = targets(base_p, first_dates, rv_x)
        print(f'=== {yr}: {len(pitches)} pitches, {len(base_p)} baseline, '
              f'{len(scorable)} scorable, {len(dates)} dates ({time.time() - t0:.0f}s)', flush=True)
        for name in todo:
            t1 = time.time()
            extra = {k: getattr(lp, k) for k in configs[name] if k not in FR.ORIG}
            FR.apply(configs[name])
            try:
                sc = score_config(base_p, scorable, first_dates)
            finally:
                FR.restore()
                for k, v in extra.items():      # FR.restore covers its own keys only
                    setattr(lp, k, v)
            df = pd.DataFrame.from_dict({k: {**sc[k], **tg.get(k, {})} for k in sc}, orient='index')
            df.index = pd.MultiIndex.from_tuples(df.index, names=['pitcher', 'throws'])
            tmp = table_path(name, yr) + '.tmp'
            df.to_pickle(tmp)
            os.replace(tmp, table_path(name, yr))
            print(f'    {name:>10s} {len(df)} pitchers [{time.time() - t1:.0f}s]', flush=True)
        del pitches, base_p, scorable
        gc.collect()


def run_cut(configs, seasons, fracs):
    """Production-sample-size replicate: everything the grade uses stops at
    the cutoff date; the target is the rest of the season."""
    os.makedirs(CACHE, exist_ok=True)
    rv_x = make_rv_xrv(FR.LG, FR.SCALE)
    for yr in seasons:
        todo = [(n, f) for f in fracs for n in configs
                if not os.path.exists(table_path(f'{n}@c{f:g}', yr))]
        if not todo:
            print(f'=== {yr}: every cut table cached', flush=True)
            continue
        pitches = FR.load_season(yr)
        base_all = [p for p in pitches if lp.is_eligible_baseline(p)]
        scor_all = [p for p in pitches if lp._is_scorable(p)]
        dates = sorted({p['Game Date'] for p in base_all if p['Game Date']})
        for f in fracs:
            cut = set(dates[:max(1, int(round(len(dates) * f)))])
            base_c = [p for p in base_all if p['Game Date'] in cut]
            scor_c = [p for p in scor_all if p['Game Date'] in cut]
            tg = targets(base_all, cut, rv_x)       # x_2h / rv_2h = after the cutoff
            print(f'=== {yr} cut {f:g}: {len(cut)} of {len(dates)} dates, '
                  f'{len(base_c)} baseline pitches', flush=True)
            for name in [n for n, ff in todo if ff == f]:
                t1 = time.time()
                extra = {k: getattr(lp, k) for k in configs[name] if k not in FR.ORIG}
                FR.apply(configs[name])
                try:
                    sc = score_config(base_c, scor_c, cut)
                finally:
                    FR.restore()
                    for k, v in extra.items():
                        setattr(lp, k, v)
                df = pd.DataFrame.from_dict({k: {**sc[k], **tg.get(k, {})} for k in sc}, orient='index')
                df.index = pd.MultiIndex.from_tuples(df.index, names=['pitcher', 'throws'])
                tmp = table_path(f'{name}@c{f:g}', yr) + '.tmp'
                df.to_pickle(tmp)
                os.replace(tmp, table_path(f'{name}@c{f:g}', yr))
                print(f'    {name:>10s} {len(df)} pitchers [{time.time() - t1:.0f}s]', flush=True)
        del pitches, base_all, scor_all
        gc.collect()


# ── summary ──────────────────────────────────────────────────────────────
def _r(x, y):
    x = x - x.mean(1, keepdims=True)
    y = y - y.mean(1, keepdims=True)
    return (x * y).sum(1) / np.sqrt((x * x).sum(1) * (y * y).sum(1))


def _partial(r_ly, r_ls, r_sy):
    return (r_ly - r_ls * r_sy) / np.sqrt((1 - r_ls ** 2) * (1 - r_sy ** 2))


GATE = os.path.join(ROOT, 'data', '_gate_v2')


def stuff_of(yr):
    """pitcher name -> OOF Stuff+ raw grade of season yr, or None."""
    fn = os.path.join(GATE, f'agg_SHIPPED_{yr}_s0.pkl')
    if os.path.exists(fn):
        return pd.read_pickle(fn)['py']['s'].astype(float)
    if yr == 2026:
        from pipeline.utils import AAA_TEAMS
        rows = json.load(open(os.path.join(ROOT, 'data', 'pitcher_leaderboard_rs.json')))
        best = {}
        for r in rows:
            if r.get('team') in AAA_TEAMS or r.get('stuffScore') is None:
                continue
            k = r['pitcher']
            if k not in best or (r.get('count') or 0) > best[k][0]:
                best[k] = (r.get('count') or 0, float(r['stuffScore']))
        return pd.Series({k: v[1] for k, v in best.items()}, dtype=float)
    return None


def with_stuff(v, yr):
    st = stuff_of(yr)
    if st is None:
        return v
    v = v.copy()
    v['stuff'] = st.reindex(v.index.get_level_values('pitcher')).values
    return v


def view(tab_y, tab_y1, test):
    """One row per pitcher: L_raw, L_ren (Loc+), x, rv (targets), velo."""
    if test == 'within':
        d = tab_y
        m = ((d['n_raw_1h'] >= base.MIN_SCORE) & (d['n_ren_1h'] >= base.MIN_SCORE)
             & (d['n_x_2h'] >= base.MIN_ACTUAL) & (d['n_velo_1h'] >= base.MIN_VELO))
        d = d[m]
        return pd.DataFrame({'L_raw': d['raw_1h'], 'L_ren': -d['ren_1h'],
                             'x': d['x_2h'], 'rv': d['rv_2h'], 'velo': d['velo_1h']})
    d = tab_y[(tab_y['n_raw_full'] >= MIN_NXT) & (tab_y['n_velo_full'] >= base.MIN_VELO)]
    n = tab_y1[tab_y1['n_x_full'] >= MIN_NXT]
    j = d.join(n[['x_full', 'rv_full']], rsuffix='_y1', how='inner')
    return pd.DataFrame({'L_raw': j['raw_full'], 'L_ren': -j['ren_full'],
                         'x': j['x_full_y1'], 'rv': j['rv_full_y1'], 'velo': j['velo_full']})


def compare(va, vb, rng):
    """va: candidate view, vb: shipped view (same targets). Point deltas and
    paired-bootstrap SEs for every (unit, target, plain | velo-partial), and
    the excess d_rv - rho * d_x."""
    j = va.join(vb[['L_raw', 'L_ren']], rsuffix='_b', how='inner')
    j = j.dropna(subset=[c for c in j.columns if c != 'stuff'])
    n = len(j)
    idx = np.vstack([np.arange(n)[None, :], rng.integers(0, n, size=(BOOT_B, n))])
    A = {c: j[c].values.astype(float)[idx] for c in j.columns}
    rho = _r(A['x'], A['rv'])
    out = {'n': n, 'rho': float(rho[0])}
    for u in ('raw', 'ren'):
        d = {}
        for tg in ('x', 'rv'):
            r_sy = _r(A['velo'], A[tg])
            ra, rb = _r(A[f'L_{u}'], A[tg]), _r(A[f'L_{u}_b'], A[tg])
            pa = _partial(ra, _r(A[f'L_{u}'], A['velo']), r_sy)
            pb = _partial(rb, _r(A[f'L_{u}_b'], A['velo']), r_sy)
            d[tg], dp = ra - rb, pa - pb
            out[f'{u}_{tg}'] = {'r_ship': float(rb[0]), 'd': float(d[tg][0]), 'se': float(d[tg][1:].std())}
            out[f'{u}_{tg}_part'] = {'r_ship': float(pb[0]), 'd': float(dp[0]), 'se': float(dp[1:].std())}
        ex = d['rv'] - rho * d['x']
        out[f'{u}_excess'] = {'d': float(ex[0]), 'se': float(ex[1:].std())}
    if 'stuff' in j.columns and j['stuff'].notna().sum() >= 100:
        k = j[j['stuff'].notna()]
        m = len(k)
        out['n_stuff'] = m
        idx = np.vstack([np.arange(m)[None, :], rng.integers(0, m, size=(BOOT_B, m))])
        A = {c: k[c].values.astype(float)[idx] for c in k.columns}
        for u in ('raw', 'ren'):
            tot = 0.0
            for tg in ('x', 'rv'):
                r_sy = _r(A['stuff'], A[tg])
                pa = _partial(_r(A[f'L_{u}'], A[tg]), _r(A[f'L_{u}'], A['stuff']), r_sy)
                pb = _partial(_r(A[f'L_{u}_b'], A[tg]), _r(A[f'L_{u}_b'], A['stuff']), r_sy)
                dp = pa - pb
                tot = tot + dp
                out[f'{u}_{tg}_pstuff'] = {'r_ship': float(pb[0]), 'd': float(dp[0]),
                                           'se': float(dp[1:].std())}
            out[f'{u}_avg_pstuff'] = {'d': float(tot[0] / 2), 'se': float((tot[1:] / 2).std())}
            # how much stuff the grade carries: |r(Loc+, Stuff+)| candidate minus shipped
            ca = np.abs(_r(A[f'L_{u}'], A['stuff'])) - np.abs(_r(A[f'L_{u}_b'], A['stuff']))
            out[f'{u}_rstuff'] = {'r_ship': float(np.abs(_r(A[f'L_{u}_b'], A['stuff']))[0]),
                                  'd': float(ca[0]), 'se': float(ca[1:].std())}
    return out


def pool(recs):
    d = np.array([r['d'] for r in recs]); se = np.array([r['se'] for r in recs])
    k = len(d)
    sb = float(np.sqrt((se ** 2).sum()) / k)
    return {'mean_d': float(d.mean()), 'se_boot': sb, 'z_boot': float(d.mean() / sb),
            'se_seasons': float(d.std(ddof=1) / math.sqrt(k)) if k > 1 else float('nan'),
            'wins': int((d > 0).sum()), 'k': k}


def grid_print(out):
    """The bandwidth surface: mean delta r vs shipped (x 10^4) and z, rows
    PHYS_X_IN, columns PHYS_Z_FRAC, for configs named x<bx>_z<bz>. Shipped
    is the zero cell."""
    import re
    cells = {}
    for key in out:
        if ':' not in key:
            continue
        test, name = key.split(':', 1)
        m = re.match(r'x([\d.]+)_z([\d.]+)$', name)
        if m:
            cells[(test, float(m.group(1)), float(m.group(2)))] = out[key]['all']
    if not cells:
        return
    sx, sz = FR.SHIPPED['PHYS_X_IN'], FR.SHIPPED['PHYS_Z_FRAC']
    xs = sorted({k[1] for k in cells} | {sx}); zs = sorted({k[2] for k in cells} | {sz})
    for test in ('within', 'next'):
        for metric, label in (('ren_x', 'rendered, luck-neutral xRV (the shipped decider for within)'),
                              ('ren_rv', 'rendered, ACTUAL RV'),
                              ('ren_rv_part', 'rendered, ACTUAL RV, FF velocity partialled'),
                              ('ren_x_pstuff', 'rendered, luck-neutral xRV, STUFF+ partialled'),
                              ('ren_rv_pstuff', 'rendered, ACTUAL RV, STUFF+ partialled'),
                              ('ren_rstuff', 'rendered, change in |r(Loc+, Stuff+)|'),
                              ('raw_x', 'raw, luck-neutral xRV'), ('raw_rv', 'raw, ACTUAL RV'),
                              ('ren_excess', 'rendered, excess d_rv - rho*d_x')):
            print(f'\n--- {test.upper()} | {label}: mean delta r x 1e4 (z) ---')
            print('  x_in \\ z ' + ''.join(f'{z:>13.2f}' for z in zs))
            for x in xs:
                row = f'  {x:>8.1f} '
                for z in zs:
                    if (x, z) == (sx, sz):
                        row += f'{"SHIPPED":>13s}'
                    elif (test, x, z) in cells and metric in cells[(test, x, z)]:
                        c = cells[(test, x, z)][metric]
                        row += f'{c["mean_d"] * 1e4:>+7.0f}({c["z_boot"]:>+4.1f})'
                    else:
                        row += f'{"":>13s}'
                print(row)


FAM_A = ('K_WHIFF', 'K_FOUL', 'K_XWCON', 'K_SWING_COLL', 'K_CS')
FAM_B = ('K_WH_COUNT', 'K_SWING_COUNT')
DECIDER = 'ren_avg_pstuff'
COLS4 = (('within', 'ren_x_pstuff'), ('within', 'ren_rv_pstuff'),
         ('next', 'ren_x_pstuff'), ('next', 'ren_rv_pstuff'))


def parse_name(name):
    """x<bx>_z<bz>[_a<kmA>_b<kmB>] -> (bx, bz, kmA, kmB) or None."""
    import re
    m = re.match(r'x([\d.]+)_z([\d.]+)(?:_a([\d.]+)_b([\d.]+))?$', name)
    if not m:
        return None
    return (float(m.group(1)), float(m.group(2)),
            float(m.group(3) or 1), float(m.group(4) or 1))


def ksurface_print(out):
    """Per bandwidth cell that has K variants: kmA (rows) x kmB (cols) of the
    decider (next, Stuff+ partialled, rendered, mean of both targets)."""
    cells = {}
    for key, rec in out.items():
        test, name = key.split(':', 1)
        pn = parse_name(name)
        if test == 'next' and pn and DECIDER in rec['all']:
            cells[pn] = rec['all'][DECIDER]
    sx, sz = FR.SHIPPED['PHYS_X_IN'], FR.SHIPPED['PHYS_Z_FRAC']
    for bx, bz in sorted({(k[0], k[1]) for k in cells if (k[2], k[3]) != (1, 1)}):
        A_ = sorted({k[2] for k in cells if k[:2] == (bx, bz)} | {1.0})
        B_ = sorted({k[3] for k in cells if k[:2] == (bx, bz)} | {1.0})
        print(f'\n--- K surface at {bx:g} in / {bz:g}: NEXT, Stuff+ partialled, rendered, mean of xRV and '
              f'actual RV; delta r x 1e4 (z) vs shipped ---')
        print('  kmA \\ kmB ' + ''.join(f'{b:>13g}' for b in B_))
        for a in A_:
            row = f'  {a:>9g} '
            for b in B_:
                if (bx, bz, a, b) == (sx, sz, 1.0, 1.0):
                    row += f'{"SHIPPED":>13s}'
                elif (bx, bz, a, b) in cells:
                    c = cells[(bx, bz, a, b)]
                    row += f'{c["mean_d"] * 1e4:>+7.0f}({c["z_boot"]:>+4.1f})'
                else:
                    row += f'{"":>13s}'
            print(row)


def loso_select(out):
    """Leave one pair out: argmax of the decider's mean over the other pairs,
    scored on the held-out pair. Candidates: every config with the decider
    on all five pairs, shipped included as delta 0."""
    per = {}
    for key, rec in out.items():
        test, name = key.split(':', 1)
        if test != 'next':
            continue
        d = {y: v[DECIDER]['d'] for y, v in rec['per_season'].items() if DECIDER in v}
        if len(d) == 5:
            per[name] = d
    if not per:
        return None
    ys = sorted(next(iter(per.values())))
    per['shipped'] = {y: 0.0 for y in ys}
    print(f'\n===== LEAVE-ONE-PAIR-OUT selection on the decider, {len(per)} candidates =====')
    held = []
    for y in ys:
        best = max(per, key=lambda n: np.mean([per[n][t] for t in ys if t != y]))
        held.append(per[best][y])
        print(f'  hold out {y}->{int(y) + 1}: picks {best:<24s} train mean '
              f'{np.mean([per[best][t] for t in ys if t != y]):+.4f}  held-out {per[best][y]:+.4f}')
    h = np.array(held)
    print(f'  held-out mean {h.mean():+.4f}  se (pairs) {h.std(ddof=1) / math.sqrt(len(h)):.4f}  '
          f'wins {int((h > 0).sum())}/{len(h)}')
    full = max(per, key=lambda n: np.mean(list(per[n].values())))
    print(f'  full-sample argmax: {full}  in-sample mean {np.mean(list(per[full].values())):+.4f}')
    return {'held_out': held, 'mean': float(h.mean()), 'full_argmax': full}


def summarize(baseline='shipped', only=None, out_path=None, cut=None):
    """baseline: the config every delta is taken against (default shipped).
    only: keep configs whose name starts with this prefix (plus baseline)."""
    names = sorted({f[4:-9] for f in os.listdir(CACHE) if f.startswith('tab_') and f.endswith('.pkl')})
    if cut is not None:
        tag = f'@c{cut:g}'
        baseline = 'shipped' + tag
        names = [n for n in names if n.endswith(tag) or n == 'shipped']
    else:
        names = [n for n in names if '@c' not in n]
    if baseline not in names:
        raise SystemExit(f'no tables for baseline {baseline}')
    if only:
        names = [n for n in names if n.startswith(only) or n in (baseline, 'shipped')]
    if baseline != 'shipped':
        print(f'##### BASELINE = {baseline}: every delta below is against it, not against shipped #####')
    seasons = sorted({int(f[-8:-4]) for f in os.listdir(CACHE) if f.startswith('tab_')})
    if 'shipped' not in names:
        raise SystemExit('no shipped tables: run with no --config first')
    T = {(n, y): pd.read_pickle(table_path(n, y)) for n in names for y in seasons
         if os.path.exists(table_path(n, y))}
    # validation: the within / raw / x column is the replicate's 'raw'
    ref = os.path.join(ROOT, 'data', '_loc_fullseason_replicate_widegrid.json')
    if os.path.exists(ref) and cut is None:
        old = json.load(open(ref))['full']
        for y in seasons:
            v = view(T[('shipped', y)], None, 'within')
            mine = base.pearson(list(v['L_raw']), list(v['x']))
            was = old.get(str(y), {}).get('w6_0.30', {})
            print(f'VALIDATE {y}: within raw r here {mine:+.4f} n {len(v)} | replicate 09-02 '
                  f'w6_0.30 {was.get("raw", float("nan")):+.4f} n {was.get("n")}')
    out = {}
    for test in ('within', 'next'):
        ys = seasons if test == 'within' else [y for y in seasons if y + 1 in seasons]
        print(f'\n===== {test.upper()}: delta vs shipped, paired bootstrap, pooled over {len(ys)} '
              f'{"seasons" if test == "within" else "pairs"} =====')
        ship = {y: with_stuff(view(T[(baseline, y)], T.get(('shipped', y + 1)), test), y)
                for y in ys}
        print('  shipped r by season (raw unit): ' + '  '.join(
            f'{y} x {base.pearson(list(ship[y]["L_raw"]), list(ship[y]["x"])):+.3f}'
            f'/rv {base.pearson(list(ship[y]["L_raw"]), list(ship[y]["rv"])):+.3f}'
            f' n {len(ship[y])}' for y in ys))
        for name in names:
            if name == baseline or (cut is not None and name == 'shipped'):
                continue
            per = {}
            for y in ys:
                if (name, y) not in T:
                    continue
                va = with_stuff(view(T[(name, y)], T.get(('shipped', y + 1)), test), y)
                per[y] = compare(va, ship[y], np.random.default_rng(0))
            if not per:
                continue
            rec = {'per_season': {str(y): v for y, v in per.items()},
                   'rho': float(np.mean([v['rho'] for v in per.values()]))}
            for tag, sel in (('all', list(per)), ('excl_partial', [y for y in per if not (test == 'next' and y == PARTIAL_Y)])):
                if tag == 'excl_partial' and (test == 'within' or len(sel) == len(per)):
                    continue
                keys = sorted({key for y in sel for key, v in per[y].items() if isinstance(v, dict)})
                rec[tag] = {key: pool([per[y][key] for y in sel if key in per[y]]) for key in keys}
            out[f'{test}:{name}'] = rec
            is_grid = name.startswith('x') and '_z' in name and '@c' not in name
            for u in (() if (is_grid and len(names) > 8) else ('raw', 'ren')):
                a = rec['all']
                print(f'  {name:>10s} {u:<3s} ' + ' | '.join(
                    f'{lab} {a[k]["mean_d"]:+.4f} se {a[k]["se_boot"]:.4f} z {a[k]["z_boot"]:+.1f} '
                    f'{a[k]["wins"]}/{a[k]["k"]}'
                    for lab, k in (('x', f'{u}_x'), ('rv', f'{u}_rv'), ('excess', f'{u}_excess'),
                                   ('x|velo', f'{u}_x_part'), ('rv|velo', f'{u}_rv_part'),
                                   ('x|stuff', f'{u}_x_pstuff'), ('rv|stuff', f'{u}_rv_pstuff'),
                                   ('d|r(L,stuff)|', f'{u}_rstuff')) if k in a))
    if baseline == 'shipped' and not only and cut is None:
        grid_print(out)
        ksurface_print(out)
        sel = loso_select(out)
        if sel:
            out['_loso'] = sel
    dest = out_path or (OUT if baseline == 'shipped' and not only and cut is None
                        else OUT.replace('.json', f'_{baseline}_{only or "all"}.json'))
    tmp = dest + '.tmp'
    json.dump(out, open(tmp, 'w'), indent=1)
    os.replace(tmp, dest)
    print(f'\nwrote {dest}')


NULL_NAME = 'x9_z0.55_a1000000_b1000000'     # every K x 1e6: no location content


def _resid(a, c):
    a = a - a.mean(1, keepdims=True)
    c = c - c.mean(1, keepdims=True)
    return a - ((a * c).sum(1, keepdims=True) / (c * c).sum(1, keepdims=True)) * c


def _partial2(L, y, c1, c2):
    """Row-wise partial r of L and y given c1 AND c2 (Gram-Schmidt)."""
    c2r = _resid(c2, c1)
    Lr = _resid(_resid(L, c1), c2r)
    yr = _resid(_resid(y, c1), c2r)
    return (Lr * yr).sum(1) / np.sqrt((Lr * Lr).sum(1) * (yr * yr).sum(1))


def summarize_null():
    """LOCATION-CONTENT objective (2026-09-17). A wide bandwidth wins the
    Stuff+-partialled objective by turning Loc+ into the count mix: the
    location-free grade (NULL_NAME) explains 58% of pitcher Loc+ variance at
    6/0.30, 71% at 9/0.55, 83% at 13/0.75, and every composite already holds
    the count mix through K% and xRV. So here the grade is scored with BOTH
    Stuff+ and the location-free grade partialled out: what is left is what
    the location surface itself says about the future. Next season and
    within season, rendered unit, both targets and their mean, paired
    bootstrap vs shipped."""
    import re
    names = sorted({f[4:-9] for f in os.listdir(CACHE) if f.startswith('tab_') and f.endswith('.pkl')
                    and '@c' not in f})
    names = [n for n in names if re.match(r'x[\d.]+_z[\d.]+$', n) or n == 'shipped']
    seasons = sorted({int(f[-8:-4]) for f in os.listdir(CACHE) if f.startswith('tab_')})
    T = {(n, y): pd.read_pickle(table_path(n, y)) for n in names + [NULL_NAME] for y in seasons
         if os.path.exists(table_path(n, y))}
    out = {}
    for test in ('next', 'within'):
        ys = seasons if test == 'within' else [y for y in seasons if y + 1 in seasons]
        col = 'ren_1h' if test == 'within' else 'ren_full'
        base_v = {}
        for y in ys:
            v = with_stuff(view(T[('shipped', y)], T.get(('shipped', y + 1)), test), y)
            v['null'] = -T[(NULL_NAME, y)][col].reindex(v.index)
            base_v[y] = v.dropna(subset=['L_ren', 'x', 'rv', 'stuff', 'null'])
        lv = np.mean([[ _partial2(base_v[y]['L_ren'].values[None, :].astype(float),
                                  base_v[y][tg].values[None, :].astype(float),
                                  base_v[y]['stuff'].values[None, :].astype(float),
                                  base_v[y]['null'].values[None, :].astype(float))[0] for tg in ('x', 'rv')]
                      for y in ys], axis=0)
        print(f'\n===== {test.upper()}: rendered Loc+ given Stuff+ AND the location-free grade =====')
        print(f'  shipped level: partial r {lv[0]:.3f} vs xRV, {lv[1]:.3f} vs actual RV '
              f'(n {" ".join(str(len(base_v[y])) for y in ys)})')
        for name in names:
            if name == 'shipped':
                continue
            per = []
            for y in ys:
                if (name, y) not in T:
                    continue
                b = base_v[y]
                a = -T[(name, y)][col].reindex(b.index)
                ok = a.notna().values
                b, a = b[ok], a[ok]
                n = len(b)
                rng = np.random.default_rng(0)
                idx = np.vstack([np.arange(n)[None, :], rng.integers(0, n, size=(BOOT_B, n))])
                A_ = {c: b[c].values.astype(float)[idx] for c in ('L_ren', 'x', 'rv', 'stuff', 'null')}
                La = a.values.astype(float)[idx]
                d = {tg: _partial2(La, A_[tg], A_['stuff'], A_['null'])
                         - _partial2(A_['L_ren'], A_[tg], A_['stuff'], A_['null']) for tg in ('x', 'rv')}
                d['avg'] = (d['x'] + d['rv']) / 2
                per.append({k: {'d': float(v[0]), 'se': float(v[1:].std())} for k, v in d.items()})
            out[f'{test}:{name}'] = {k: pool([p[k] for p in per]) for k in ('x', 'rv', 'avg')}
        cells = {}
        for key, rec in out.items():
            t_, name = key.split(':', 1)
            m = re.match(r'x([\d.]+)_z([\d.]+)$', name)
            if t_ == test and m:
                cells[(float(m.group(1)), float(m.group(2)))] = rec
        xs = sorted({k[0] for k in cells} | {FR.SHIPPED['PHYS_X_IN']})
        zs = sorted({k[1] for k in cells} | {FR.SHIPPED['PHYS_Z_FRAC']})
        for metric, label in (('avg', 'mean of xRV and actual RV'), ('rv', 'actual RV'), ('x', 'luck-neutral xRV')):
            print(f'  --- {label}: mean delta partial r x 1e4 (z) ---')
            print('  x_in \\ z ' + ''.join(f'{z:>13.2f}' for z in zs))
            for x in xs:
                row = f'  {x:>8.1f} '
                for z in zs:
                    if (x, z) == (FR.SHIPPED['PHYS_X_IN'], FR.SHIPPED['PHYS_Z_FRAC']):
                        row += f'{"SHIPPED":>13s}'
                    elif (x, z) in cells:
                        c = cells[(x, z)][metric]
                        row += f'{c["mean_d"] * 1e4:>+7.0f}({c["z_boot"]:>+4.1f})'
                    else:
                        row += f'{"":>13s}'
                print(row)
    dest = OUT.replace('.json', '_nullcontrol.json')
    tmp = dest + '.tmp'
    json.dump(out, open(tmp, 'w'), indent=1)
    os.replace(tmp, dest)
    print(f'\nwrote {dest}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['run', 'run-cut', 'summary', 'summary-null'])
    ap.add_argument('--fracs', default='0.125,0.25,0.375,0.5,0.75')
    ap.add_argument('--cut', type=float, default=None, help='summary: read the @c<f> tables')
    ap.add_argument('--config', action='append', default=[], help='name=PHYS_X_IN:PHYS_Z_FRAC')
    ap.add_argument('--kset', action='append', default=[], help='name=bx:bz:<7 K values>')
    ap.add_argument('--flag', action='append', default=[], help='name=ATTR:VALUE')
    ap.add_argument('--seasons', default=None)
    ap.add_argument('--baseline', default='shipped', help='summary: config the deltas are against')
    ap.add_argument('--only', default=None, help='summary: name prefix filter')
    a = ap.parse_args()
    if a.cmd == 'summary-null':
        return summarize_null()
    if a.cmd == 'summary':
        return summarize(a.baseline, a.only, cut=a.cut)
    configs = {'shipped': dict(FR.SHIPPED)}
    for spec in a.config:
        name, vals = spec.split('=', 1)
        v = [float(x) for x in vals.split(':')]
        bx, bz = v[0], v[1]
        ka = v[2] if len(v) > 2 else 1.0
        kb = v[3] if len(v) > 3 else ka
        cfg = {**FR.SHIPPED, 'PHYS_X_IN': bx, 'PHYS_Z_FRAC': bz}
        for k in FAM_A:
            cfg[k] = FR.SHIPPED[k] * ka
        for k in FAM_B:
            cfg[k] = FR.SHIPPED[k] * kb
        configs[name] = cfg
    for spec in a.kset:
        name, cfg = FR.parse_config(spec)
        configs[name] = cfg
    for spec in a.flag:
        name, kv = spec.split('=', 1)
        attr, val = kv.split(':', 1)
        if not hasattr(lp, attr):
            raise SystemExit(f'--flag {name}: pipeline.locplus has no attribute {attr}')
        cur = getattr(lp, attr)
        new = bool(int(val)) if isinstance(cur, bool) else type(cur)(val)
        if new == cur:
            raise SystemExit(f'--flag {name}: {attr} is already {cur!r}; nothing to test')
        configs[name] = {**FR.SHIPPED, attr: new}
    seasons = [int(s) for s in a.seasons.split(',')] if a.seasons else sorted(FR.SEASONS)
    print('shipped = ' + json.dumps(FR.SHIPPED), flush=True)
    if a.cmd == 'run-cut':
        return run_cut(configs, seasons, [float(x) for x in a.fracs.split(',')])
    run(configs, seasons)


if __name__ == '__main__':
    main()
