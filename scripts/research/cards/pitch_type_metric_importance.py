#!/usr/bin/env python3
"""pitch_type_metric_importance.py — which metrics matter most for each pitch type.

Wally, 2026-11-23, for the social pitcher card: find, across MLB, which shape metrics,
approach angles and outcome rates are most important per pitch type, so a card can note a
metric only when a pitcher's value stands out.

Unit: pitcher x pitch type x season, 200+ pitches of the type in season Y (the gate is on the
base season only). Target: the same unit's luck-neutral run value per 100 pitches in season
Y+1 (a ball in play priced by xwOBA, every other pitch by delta_run_exp), pitcher-positive.
Every unit with a Y+1 pitch counts, weighted by its Y+1 pitches; a unit that throws none in
Y+1 has no target and drops (survivor limit, stated in the output).

Per pitch type and metric, over the four pairs 2021->22 .. 2024->25:
  next   weighted r of the metric in Y with the target in Y+1 (mean of pairs, SE, same-sign pairs)
  beyond the same r with the card's present result items held equal (Whiff%, Strike%, xwOBAcon)
  same   weighted r with the SAME season's run value (shape metrics only: an outcome rate is
         part of the same season's run value, so that r is mechanical and is not printed)
  rep    r of the metric with itself in Y+1 (does it repeat)

Statcast caches 2021-2025 (tracked values). The zone is the plain rectangle (half width .83 ft),
an approximation that is good enough for a ranking. 2026 is left out: its pitch cache holds
weather-neutral values under the plain names, a different quantity.

  .venv/bin/python scripts/research/cards/pitch_type_metric_importance.py build
  .venv/bin/python scripts/research/cards/pitch_type_metric_importance.py report
"""
import gc
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CACHE = os.path.join(ROOT, 'data', '_card_metric_importance')
YEARS = [2021, 2022, 2023, 2024, 2025]
TYPES = ['FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS']
MERGE = {'KC': 'CU', 'CS': 'CU', 'SV': 'ST', 'FA': 'FF'}
MIN_N = 200
WOBA_SCALE = 1.24
SHAPE = ['velo', 'spin', 'ivb', 'hb', 'ext', 'arm', 'relz', 'vaa', 'nvaa', 'haa', 'nhaa', 'dvelo', 'divb', 'dhb']
OUTCOME = ['whiff', 'zwhiff', 'chase', 'zone', 'strike', 'csw', 'called', 'swing', 'zswing', 'gb', 'xwcon', 'k2']
LABEL = {'velo': 'Velocity', 'spin': 'Spin rate', 'ivb': 'IVB', 'hb': 'HB (arm side +)', 'ext': 'Extension', 'arm': 'Arm angle',
         'relz': 'Release height', 'vaa': 'VAA', 'nvaa': 'nVAA', 'haa': 'HAA (arm side +)', 'nhaa': 'nHAA', 'dvelo': 'Velo gap to FB',
         'divb': 'IVB gap to FB', 'dhb': 'HB gap to FB', 'whiff': 'Whiff%', 'zwhiff': 'Zone Whiff%', 'chase': 'Chase%', 'zone': 'Zone%',
         'strike': 'Strike%', 'csw': 'CSW%', 'called': 'Called strike%', 'swing': 'Swing%', 'zswing': 'Zone Swing%', 'gb': 'GB%',
         'xwcon': 'xwOBAcon', 'k2': 'Two-strike whiff%'}


def num(s):
    return pd.to_numeric(s, errors='coerce').to_numpy(dtype='float64', na_value=np.nan)


def season(y):
    d = pd.read_pickle(os.path.join(ROOT, 'data', f'_statcast{y}_cache.pkl'))
    f = pd.DataFrame({'pitcher': d['pitcher'].astype('int64').values, 'pt': d['pitch_type'].astype(object).map(lambda v: MERGE.get(v, v)).values,
                      'throws': d['p_throws'].astype(object).values, 'desc': d['description'].astype(object).values,
                      'bb': d['bb_type'].astype(object).values})
    for a, b in (('velo', 'release_speed'), ('spin', 'release_spin_rate'), ('ext', 'release_extension'), ('arm', 'arm_angle'),
                 ('relz', 'release_pos_z'), ('px', 'plate_x'), ('pz', 'plate_z'), ('top', 'sz_top'), ('bot', 'sz_bot'),
                 ('dre', 'delta_run_exp'), ('xw', 'estimated_woba_using_speedangle'), ('strikes', 'strikes')):
        f[a] = num(d[b])
    s = np.where(f['throws'] == 'R', 1.0, -1.0)
    f['ivb'] = num(d['pfx_z']) * 12.0
    f['hb'] = -num(d['pfx_x']) * 12.0 * s          # arm side positive for both hands
    vx0, vy0, vz0, ax, ay, az = (num(d[c]) for c in ('vx0', 'vy0', 'vz0', 'ax', 'ay', 'az'))
    del d
    gc.collect()
    vyf = -np.sqrt(np.maximum(vy0 ** 2 - 2.0 * ay * (50.0 - 17.0 / 12.0), 0.0))
    t = (vyf - vy0) / ay
    f['vaa'] = -np.degrees(np.arctan((vz0 + az * t) / vyf))
    f['haa'] = np.degrees(np.arctan((vx0 + ax * t) / vyf)) * s
    f = f[f['pt'].isin(TYPES) & f['throws'].isin(['L', 'R'])].copy()
    # nVAA / nHAA: the angle with the location removed, within pitch type (and hand for the side angle)
    f['zn'] = (f['pz'] - f['bot']) / (f['top'] - f['bot'])
    f['pxs'] = f['px'] * np.where(f['throws'] == 'R', 1.0, -1.0)
    for ang, loc, out in (('vaa', 'pz', 'nvaa'), ('haa', 'pxs', 'nhaa')):
        f[out] = np.nan
        for pt, g in f.groupby('pt'):
            ok = g[ang].notna() & g[loc].notna()
            b = np.polyfit(g.loc[ok, loc], g.loc[ok, ang], 1)
            f.loc[g.index, out] = g[ang] - (b[0] * g[loc] + b[1]) + g.loc[ok, ang].mean()
    swing = f['desc'].isin(['swinging_strike', 'swinging_strike_blocked', 'foul', 'foul_tip', 'hit_into_play', 'missed_bunt'])
    whiff = f['desc'].isin(['swinging_strike', 'swinging_strike_blocked', 'missed_bunt'])
    called = f['desc'] == 'called_strike'
    ball = f['desc'].isin(['ball', 'blocked_ball', 'automatic_ball', 'hit_by_pitch', 'pitchout'])
    inz = (f['px'].abs() <= 0.83) & (f['pz'] >= f['bot']) & (f['pz'] <= f['top'])
    bip = f['desc'] == 'hit_into_play'
    lg_xw = f.loc[bip, 'xw'].mean()
    f['val'] = np.where(bip & f['xw'].notna(), -(f['xw'] - lg_xw) / WOBA_SCALE, -f['dre'])
    f['val'] = f['val'] - f['val'].mean()
    for nm, col in (('sw', swing), ('wh', whiff), ('cs', called), ('ball', ball), ('inz', inz), ('bip', bip)):
        f[nm] = col.astype(float)
    f['two'] = (f['strikes'] == 2).astype(float)
    f['gbf'] = (f['bb'] == 'ground_ball').astype(float)
    g = f.groupby(['pitcher', 'pt'])
    u = g[['velo', 'spin', 'ivb', 'hb', 'ext', 'arm', 'relz', 'vaa', 'nvaa', 'haa', 'nhaa']].mean()
    u['n'] = g.size()
    u['throws'] = g['throws'].first()
    u['rv'] = g['val'].mean() * 100.0
    S = lambda c: g[c].sum()
    P = lambda a, b: (f[a] * f[b]).groupby([f['pitcher'], f['pt']]).sum()
    oz = (1.0 - f['inz']).rename('oz')
    f['oz'] = oz
    u['whiff'] = S('wh') / S('sw')
    u['zwhiff'] = P('wh', 'inz') / P('sw', 'inz')
    u['chase'] = P('sw', 'oz') / S('oz')
    u['zone'] = S('inz') / u['n']
    u['strike'] = 1.0 - S('ball') / u['n']
    u['csw'] = (S('cs') + S('wh')) / u['n']
    u['called'] = S('cs') / u['n']
    u['swing'] = S('sw') / u['n']
    u['zswing'] = P('sw', 'inz') / S('inz')
    u['gb'] = P('gbf', 'bip') / S('bip')
    u['xwcon'] = (f['xw'].where(bip)).groupby([f['pitcher'], f['pt']]).mean()
    u['k2'] = P('wh', 'two') / S('two')
    u['n_sw'], u['n_bip'], u['n_two'] = S('sw'), S('bip'), S('two')
    # gaps to the pitcher's primary fastball (most thrown of FF / SI / FC)
    fb = u[u.index.get_level_values('pt').isin(['FF', 'SI', 'FC'])].reset_index().sort_values('n').drop_duplicates('pitcher', keep='last').set_index('pitcher')
    pid = u.index.get_level_values('pitcher')
    for a in ('velo', 'ivb', 'hb'):
        u['d' + a] = u[a].values - fb[a].reindex(pid).values
    same = u.index.get_level_values('pt') == fb['pt'].reindex(pid).values
    u.loc[same, ['dvelo', 'divb', 'dhb']] = np.nan
    return u


def build():
    os.makedirs(CACHE, exist_ok=True)
    for y in YEARS:
        fn = os.path.join(CACHE, f'units_{y}.pkl')
        if os.path.exists(fn):
            continue
        u = season(y)
        u.to_pickle(fn + '.tmp')
        os.replace(fn + '.tmp', fn)
        print(f'{y}: {len(u):,} units, {(u.n >= MIN_N).sum():,} with {MIN_N}+ pitches; league nVAA by type '
              + ' '.join(f'{t} {u.loc[(slice(None), t), "nvaa"].mean():.2f}' for t in ('FF', 'SI', 'SL')), flush=True)
        gc.collect()


def wr(x, y, w):
    ok = np.isfinite(x) & np.isfinite(y) & (w > 0)
    if ok.sum() < 25:
        return np.nan
    x, y, w = x[ok], y[ok], w[ok]
    mx, my = np.average(x, weights=w), np.average(y, weights=w)
    c = np.average((x - mx) * (y - my), weights=w)
    return c / np.sqrt(np.average((x - mx) ** 2, weights=w) * np.average((y - my) ** 2, weights=w))


def wresid(y, X, w):
    ok = np.isfinite(y) & np.isfinite(X).all(axis=1) & (w > 0)
    out = np.full(len(y), np.nan)
    if ok.sum() < 30:
        return out
    A = np.column_stack([np.ones(ok.sum()), X[ok]]) * np.sqrt(w[ok])[:, None]
    b = np.linalg.lstsq(A, y[ok] * np.sqrt(w[ok]), rcond=None)[0]
    out[ok] = y[ok] - np.column_stack([np.ones(ok.sum()), X[ok]]) @ b
    return out


def report():
    U = {y: pd.read_pickle(os.path.join(CACHE, f'units_{y}.pkl')) for y in YEARS}
    res, surv = {}, []
    for pt in TYPES:
        rows = {m: {'next': [], 'beyond': [], 'same': [], 'rep': []} for m in SHAPE + OUTCOME}
        nunits = 0
        for y in YEARS[:-1]:
            a = U[y].xs(pt, level='pt')
            a = a[a['n'] >= MIN_N]
            b = U[y + 1].xs(pt, level='pt')
            j = a.join(b[['rv', 'n'] + SHAPE + OUTCOME], rsuffix='_1', how='left')
            surv.append((len(a), j['n_1'].notna().sum()))
            j = j[j['n_1'].notna()]
            nunits += len(j)
            w1, w0 = j['n_1'].values.astype(float), j['n'].values.astype(float)
            card = j[['whiff', 'strike', 'xwcon']].values.astype(float)
            t_res = wresid(j['rv_1'].values, card, w1)
            for m in SHAPE + OUTCOME:
                x = j[m].values.astype(float)
                rows[m]['next'].append(wr(x, j['rv_1'].values, w1))
                rows[m]['beyond'].append(np.nan if m in ('whiff', 'strike', 'xwcon') else wr(wresid(x, card, w1), t_res, w1))
                rows[m]['same'].append(wr(x, j['rv'].values, w0) if m in SHAPE else np.nan)
                rows[m]['rep'].append(wr(x, j[m + '_1'].values, w1))
        out = {}
        for m, d in rows.items():
            o = {}
            for k, v in d.items():
                v = np.array(v, float)
                ok = np.isfinite(v)
                if ok.sum() < 3:
                    o[k] = None
                    continue
                mu = v[ok].mean()
                o[k] = (float(mu), float(v[ok].std(ddof=1) / np.sqrt(ok.sum())), int((np.sign(v[ok]) == np.sign(mu)).sum()), int(ok.sum()))
            out[m] = o
        res[pt] = {'units': nunits, 'metrics': out}
    tot, kept = sum(s[0] for s in surv), sum(s[1] for s in surv)
    print(f'Units with {MIN_N}+ pitches in Y: {tot:,}; with a pitch of the type in Y+1: {kept:,} ({kept / tot:.0%}). The rest have no target.')
    print('next = r with next-season run value per 100 (pitcher-positive: r > 0 means more of the metric is better).')
    print('beyond = the same with Whiff%, Strike% and xwOBAcon held equal. rep = the metric against itself next season.')
    f = lambda o, sig=True: '      -      ' if o is None else (f'{o[0]:+.2f} ({o[1]:.2f}) {o[2]}/{o[3]}' if sig else f'{o[0]:+.2f}')
    for pt in TYPES:
        M = res[pt]['metrics']
        order = sorted(M, key=lambda m: -abs(M[m]['next'][0]) if M[m]['next'] else 0)
        print(f'\n=== {pt}: {res[pt]["units"]} unit pairs ===')
        print(f'{"metric":<20s}{"next (se) pairs":>20s}{"beyond (se) pairs":>20s}{"same":>8s}{"rep":>7s}')
        for m in order:
            if M[m]['next'] is None:
                continue
            print(f'{LABEL[m]:<20s}{f(M[m]["next"]):>20s}{f(M[m]["beyond"]):>20s}{f(M[m]["same"], False):>8s}{f(M[m]["rep"], False):>7s}')
    json.dump(res, open(os.path.join(CACHE, 'report.json'), 'w'), indent=1)


if __name__ == '__main__':
    {'build': build, 'report': report}[sys.argv[1]]()
