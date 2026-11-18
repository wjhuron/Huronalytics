#!/usr/bin/env python3
"""locplus_two_number_build.py — research build of the two-number Loc+ split.

Shipped Loc+ ties a grade with no location input on next-season forecasting, and
its count level comes mostly from pricing a ball in play outside count currency
(2026-11-18 battery). This builds the candidate replacement and tests it:

  value v     expected hitter run value of the pitch (pipeline.locplus), under
                ship   shipped pricing
                anch   ball in play in count currency (BIP count anchor on)
  situation   the league mean of v for the pitch's (group, batter hand, pitcher
              hand, count): what an average location is worth there
  location    v minus situation: what THIS location adds

so v = situation + location, per pitch, and a pitcher's season means add up the
same way. Surfaces are built on the full season, as production builds them.

`build`  one table per season in data/_loc_two_number/: per (pitcher, hand) the
         season means of every part, and the same on odd and even game dates.
`report` (1) how the parts relate, (2) split-half reliability, (3) next-season
         partial r given Stuff+, pooled and within hand and role, (4) a
         leave-one-pair-out forecast: Stuff+ plus Loc channels, fit on four season
         pairs, scored on the fifth.

Pool: 300 pitches in season Y; every pitcher with a Y+1 pitch, weighted by Y+1
pitches (base-period gate). Stuff+ is the gate's out-of-sample SHIPPED grade.
DECIDERS, fixed before the run:
  location grade  next-season partial r given Stuff+, WITHIN hand and role, mean
                  of the xRV and actual-RV columns; reliability is a diagnostic.
  two channels    the held-out forecast with (Stuff+, location, situation) must
                  not lose to (Stuff+, shipped Loc+) on either target.

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/locplus_two_number_build.py build
  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/locplus_two_number_build.py report
"""
import gc
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'stuff'))
import pipeline.locplus as lp  # noqa: E402
import locplus_fullseason_replicate as FR  # noqa: E402
import locplus_count_calibration as CC  # noqa: E402

CACHE = os.path.join(ROOT, 'data', '_loc_two_number')
OUT = os.path.join(CACHE, 'report.json')
YEARS = list(range(2021, 2027))
PAIRS = YEARS[:-1]
PARTS = ('v_ship', 'v_anch', 'loc_ship', 'loc_anch', 'sit_ship', 'sit_anch')
B = 1000


def tab_path(y):
    return os.path.join(CACHE, f'parts_{y}.pkl')


def build():
    os.makedirs(CACHE, exist_ok=True)
    for y in YEARS:
        if os.path.exists(tab_path(y)):
            print(f'{y}: cached')
            continue
        pitches = FR.load_season(y)
        base_p = [p for p in pitches if lp.is_eligible_baseline(p)]
        S = lp.build_surfaces(base_p, FR.LG, FR.SCALE)
        off = lp.build_bip_count_offsets(base_p, FR.LG, FR.SCALE)
        dates = sorted({p['Game Date'] for p in base_p if p['Game Date']})
        par = {d: i % 2 for i, d in enumerate(dates)}
        rows = []
        for p in pitches:
            if not lp._is_scorable(p):
                continue
            v0 = lp.score_pitch(p, S)
            if v0 is None:
                continue
            v1 = CC.score(p, S, off, None)
            rows.append((p.get('Pitcher'), p.get('Throws'), lp.group_of(p), p.get('Bats'),
                         lp.get_count(p), par.get(p.get('Game Date'), 0), v0, v1))
        del pitches, base_p, S
        gc.collect()
        d = pd.DataFrame(rows, columns=['pitcher', 'throws', 'grp', 'bats', 'count', 'half', 'v_ship', 'v_anch'])
        cell = ['grp', 'bats', 'throws', 'count']
        for a in ('ship', 'anch'):
            d[f'sit_{a}'] = d.groupby(cell)[f'v_{a}'].transform('mean')
            d[f'loc_{a}'] = d[f'v_{a}'] - d[f'sit_{a}']
        g = d.groupby(['pitcher', 'throws'])
        t = g[list(PARTS)].mean()
        t['n'] = g.size()
        for h in (0, 1):
            gh = d[d['half'] == h].groupby(['pitcher', 'throws'])
            th = gh[list(PARTS)].mean().add_suffix(f'_h{h}')
            th[f'n_h{h}'] = gh.size()
            t = t.join(th)
        t.to_pickle(tab_path(y))
        print(f'{y}: {len(d)} pitches, {len(t)} pitchers; count-level SD of situation x100: '
              f'ship {100 * d.groupby("count")["sit_ship"].mean().std():.2f}, '
              f'anch {100 * d.groupby("count")["sit_anch"].mean().std():.2f}', flush=True)
        del d
        gc.collect()


# ── report helpers ─────────────────────────────────────────────────────────
def wmean(a, w):
    return (a * w).sum(1, keepdims=True) / w.sum(1, keepdims=True)


def wdemean(a, w, g):
    if g is None:
        return a - wmean(a, w)
    out = a.copy()
    for code in np.unique(g):
        m = (g == code)
        mw = m * w
        out = out - ((a * mw).sum(1, keepdims=True) / np.maximum(mw.sum(1, keepdims=True), 1e-12)) * m
    return out


def wcorr(a, b, w):
    return (w * a * b).sum(1) / np.sqrt((w * a * a).sum(1) * (w * b * b).sum(1))


def wpartial(L, y, s, w, g):
    L, y, s = wdemean(L, w, g), wdemean(y, w, g), wdemean(s, w, g)
    rly, rls, rsy = wcorr(L, y, w), wcorr(L, s, w), wcorr(s, y, w)
    return (rly - rls * rsy) / np.sqrt((1 - rls ** 2) * (1 - rsy ** 2))


def pair_frame(y, stuff_col='s_r', stuff_arm=None):
    """One row per pitcher for the pair (y, y+1): parts of season y (sign flipped so
    higher = better for the pitcher), Stuff+ of y, targets and pitches of y+1."""
    import stuff_gate_v2 as G
    import stuff_gate_v2_ext as E
    t = pd.read_pickle(tab_path(y))
    t = t[t['n'] >= 300].reset_index()
    t = t.sort_values('n').drop_duplicates('pitcher', keep='last').set_index('pitcher')
    a = pd.read_pickle(G.agg_path('SHIPPED', y, 0))
    j = a['py'].join(a['py1'], lsuffix='_y', rsuffix='_y1', how='inner')
    d = pd.DataFrame({'stuff': j['s_r'], 'x': j['t'], 'rv': j['rv'], 'w': j['n_y1']})
    if stuff_arm:
        d['stuff_arm'] = pd.read_pickle(E.agg_path(stuff_arm, y, 0))['py']['s_r'].reindex(d.index)
    for c in PARTS:
        d[c] = -t[c].reindex(d.index)
    d['hand'] = t['throws'].reindex(d.index)
    # the pitcher's own season-Y results (luck-neutral run value per pitch), the stand-in for
    # what K%, xRV and the other composite channels already hold
    import locplus_target_audit as TA
    au = pd.read_pickle(TA.table_path('shipped', y)).reset_index()
    au = au.sort_values('n_x_full').drop_duplicates('pitcher', keep='last').set_index('pitcher')
    d['xy'] = -au['x_full'].reindex(d.index)
    rm = G.role_map()[y + 1]
    d['role'] = [rm.get(p, 'NA') for p in d.index]
    d['lhp'] = (d['hand'] == 'L').astype(float)
    return d.dropna()


def report():
    rng = np.random.default_rng(0)
    out = {}
    # (1) structure and (2) reliability, per season
    print('per season, pitchers with 300+ pitches: share of the variance of v that is situation; r(location, situation); '
          'split-half r (150+ per half)')
    print(f'{"year":>6s}{"n":>5s} | {"sit share ship":>15s}{"sit share anch":>15s} | {"r(loc,sit) ship":>16s}{"anch":>7s} | '
          f'{"rel v_ship":>11s}{"loc_ship":>10s}{"loc_anch":>10s}{"sit_ship":>10s}{"sit_anch":>10s}')
    for y in YEARS:
        t = pd.read_pickle(tab_path(y))
        q = t[t['n'] >= 300]
        h = t[(t['n_h0'] >= 150) & (t['n_h1'] >= 150)]
        rel = {c: float(np.corrcoef(h[f'{c}_h0'], h[f'{c}_h1'])[0, 1]) for c in PARTS}
        rec = {'n': int(len(q)),
               'share_ship': float(np.corrcoef(q.v_ship, q.sit_ship)[0, 1] ** 2),
               'share_anch': float(np.corrcoef(q.v_anch, q.sit_anch)[0, 1] ** 2),
               'r_ls_ship': float(np.corrcoef(q.loc_ship, q.sit_ship)[0, 1]),
               'r_ls_anch': float(np.corrcoef(q.loc_anch, q.sit_anch)[0, 1]), 'rel': rel}
        out[f'struct:{y}'] = rec
        print(f'{y:>6d}{rec["n"]:>5d} | {rec["share_ship"]:>15.2f}{rec["share_anch"]:>15.2f} | {rec["r_ls_ship"]:>16.2f}'
              f'{rec["r_ls_anch"]:>7.2f} | {rel["v_ship"]:>11.2f}{rel["loc_ship"]:>10.2f}{rel["loc_anch"]:>10.2f}'
              f'{rel["sit_ship"]:>10.2f}{rel["sit_anch"]:>10.2f}')
    # (3) next-season partial r given Stuff+
    frames = {y: pair_frame(y) for y in PAIRS}
    per = defaultdict(list)
    for y, d in frames.items():
        d = d[d['role'] != 'NA']
        n = len(d)
        idx = np.vstack([np.arange(n)[None, :], rng.integers(0, n, size=(B, n))])
        V = {c: d[c].values.astype(float)[idx] for c in list(PARTS) + ['stuff', 'x', 'rv', 'w']}
        codes = {'pooled': None, 'hand': pd.factorize(d['hand'])[0][idx],
                 'hand_role': pd.factorize(d['hand'] + d['role'])[0][idx]}
        for fr, g in codes.items():
            for c in PARTS:
                r = sum(wpartial(V[c], V[tg], V['stuff'], V['w'], g) for tg in ('x', 'rv')) / 2
                per[(fr, c)].append((float(r[0]), float(r[1:].std())))
            for a, b in (('loc_anch', 'loc_ship'), ('loc_anch', 'v_ship'), ('sit_anch', 'sit_ship')):
                dd = sum(wpartial(V[a], V[tg], V['stuff'], V['w'], g) - wpartial(V[b], V[tg], V['stuff'], V['w'], g)
                         for tg in ('x', 'rv')) / 2
                per[(fr, f'{a}-{b}')].append((float(dd[0]), float(dd[1:].std())))
    print('\nnext season, partial r given Stuff+, mean of the xRV and actual-RV columns (mean of 5 pairs, se, pairs > 0)')
    for (fr, c), vs in per.items():
        m, se = np.mean([v[0] for v in vs]), np.sqrt(sum(v[1] ** 2 for v in vs)) / len(vs)
        out[f'nxt:{fr}:{c}'] = {'mean': float(m), 'se': float(se), 'pos': int(sum(v[0] > 0 for v in vs))}
        print(f'  {fr:>10s} {c:<22s} {m:+.4f} ({se:.4f}) {sum(v[0] > 0 for v in vs)}/5')
    # (4) leave-one-pair-out forecast
    models = {
        'A stuff + shipped Loc+': ['stuff', 'v_ship'],
        'B stuff + location(anch)': ['stuff', 'loc_anch'],
        'C stuff + location(anch) + situation(ship)': ['stuff', 'loc_anch', 'sit_ship'],
        'D stuff + location(anch) + situation(anch)': ['stuff', 'loc_anch', 'sit_anch'],
        'E stuff + location(ship) + situation(ship)': ['stuff', 'loc_ship', 'sit_ship'],
        'F stuff + LHP + location(anch) + situation(anch)': ['stuff', 'lhp', 'loc_anch', 'sit_anch'],
        'G stuff + LHP + location(anch)': ['stuff', 'lhp', 'loc_anch'],
        'H stuff + LHP': ['stuff', 'lhp'],
        'I stuff only': ['stuff'],
        'J stuff + results + shipped Loc+': ['stuff', 'xy', 'v_ship'],
        'K stuff + results + location(anch)': ['stuff', 'xy', 'loc_anch'],
        'L stuff + results + location(anch) + situation(ship)': ['stuff', 'xy', 'loc_anch', 'sit_ship'],
        'M stuff + results': ['stuff', 'xy'],
        'N stuff + results + LHP + location(anch)': ['stuff', 'xy', 'lhp', 'loc_anch'],
        'O stuff + results + LHP': ['stuff', 'xy', 'lhp'],
        'P stuff + results + LHP + situation(ship)': ['stuff', 'xy', 'lhp', 'sit_ship'],
        'Q stuff + results + LHP + situation(anch)': ['stuff', 'xy', 'lhp', 'sit_anch'],
        'R stuff + results + LHP + location(anch) + situation(ship)': ['stuff', 'xy', 'lhp', 'loc_anch', 'sit_ship'],
        'S stuff + LHP + shipped Loc+': ['stuff', 'lhp', 'v_ship'],
    }

    def fit(tr, cols, tg):
        X = np.column_stack([np.ones(len(tr))] + [tr[c].values for c in cols])
        sw = np.sqrt(tr['w'].values)
        return np.linalg.lstsq(X * sw[:, None], tr[tg].values * sw, rcond=None)[0]

    def pred(te, cols, beta):
        return np.column_stack([np.ones(len(te))] + [te[c].values for c in cols]) @ beta

    print('\nleave-one-pair-out forecast: weighted r of the prediction with the held-out pair, mean of 5; '
          'delta vs A with a paired bootstrap se; pairs won')
    print(f'{"model":<62s}{"xRV r":>8s}{"d vs A":>26s}{"RV r":>8s}{"d vs A":>26s}')
    for name, cols in models.items():
        row = f'{name:<62s}'
        for tg in ('x', 'rv'):
            rs, ds, ses = [], [], []
            for y in PAIRS:
                tr = pd.concat([frames[o] for o in PAIRS if o != y])
                te = frames[y]
                pa = pred(te, cols, fit(tr, cols, tg))
                pb = pred(te, models['A stuff + shipped Loc+'], fit(tr, models['A stuff + shipped Loc+'], tg))
                n = len(te)
                idx = np.vstack([np.arange(n)[None, :], rng.integers(0, n, size=(B, n))])
                w, yv = te['w'].values[idx], te[tg].values[idx]
                ra = wcorr(wdemean(pa[idx], w, None), wdemean(yv, w, None), w)
                rb = wcorr(wdemean(pb[idx], w, None), wdemean(yv, w, None), w)
                rs.append(float(ra[0])); ds.append(float((ra - rb)[0])); ses.append(float((ra - rb)[1:].std()))
            se = np.sqrt(np.sum(np.square(ses))) / len(ses)
            out[f'fc:{name}:{tg}'] = {'r': float(np.mean(rs)), 'd': float(np.mean(ds)), 'se': float(se),
                                      'won': int(sum(x > 0 for x in ds))}
            row += f'{np.mean(rs):>8.4f}{f"{np.mean(ds):+.4f} ({se:.4f}) {sum(x > 0 for x in ds)}/5":>26s}'
        print(row)
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    {'build': build, 'report': report}[sys.argv[1]]()
