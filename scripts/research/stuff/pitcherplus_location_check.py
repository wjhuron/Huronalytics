#!/usr/bin/env python3
"""pitcherplus_location_check.py — season Pitcher+ on the Loc+ release input.

Pitcher+ (pipeline/pitcherplus.py) takes locPlus at weight .06 and k 215. The Loc+
release (branch locplus-location) changes what that component is: the mean
LOCATION value (kernel 2 in / 0.12, count currency, minus the situation mean).
This runs the shipped Pitcher+ recipe on its own harness (pitcherplus_v14_audit:
panel S = odd/even game halves both directions, panel Y = year pairs 2021->22 ..
2024->25, target future xRV/100) with two loc series that differ only in the
Loc+ code, and the v18 Stuff+ series in both.

  build   data/_pplus_locplus_ship_1118.csv      shipped module, score_pitch
          data/_pplus_locplus_location_1118.csv  branch module, location_value
          Same rows, halves and surfaces rule as the archived
          pitcherplus_locplus_hist.py. The ship rebuild is checked against
          data/_pplus_locplus_hist.csv (built 2026-09-05).
  check   frozen formula r on both panels; the loc r = 0.5 crossing; the
          composite's curve in loc k (others at shipped); refit weights of the
          shipped six; the left-hander offset in Pitcher+ points.

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/stuff/pitcherplus_location_check.py build /path/to/branch
  PYTHONHASHSEED=0 .venv/bin/python scripts/research/stuff/pitcherplus_location_check.py check
"""
import gc
import importlib.util
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'misc'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'archive'))

DATA = os.path.join(ROOT, 'data')
CSV = {'ship': os.path.join(DATA, '_pplus_locplus_ship_1118.csv'),
       'location': os.path.join(DATA, '_pplus_locplus_location_1118.csv'),
       'shape': os.path.join(DATA, '_pplus_locplus_shape_1119.csv'),
       'far': os.path.join(DATA, '_pplus_locplus_far_1119.csv')}
STUFF_V18 = os.path.join(DATA, '_pplus_stuff_v18.csv')
OUT = os.path.join(DATA, '_pplus_location_check.json')
K_GRID = [30, 60, 100, 150, 215, 300, 450, 700, 1000, 2000]


def build(branch_path):
    import pitcherplus_locplus_hist as H      # archived builder: season_dicts, GUTS (read-only use)
    import pipeline.locplus as SHIP
    spec = importlib.util.spec_from_file_location('pipeline.locplus_branch', os.path.join(branch_path, 'pipeline', 'locplus.py'))
    BR = importlib.util.module_from_spec(spec)
    sys.modules['pipeline.locplus_branch'] = BR
    spec.loader.exec_module(BR)
    if not hasattr(BR, 'location_value'):
        sys.exit(f'{branch_path} has no location_value: not the Loc+ release branch. Nothing written.')
    rows = {'ship': [], 'location': []}
    for year in H.SEASONS:
        pitches = H.season_dicts(year)
        lg, scale = H.GUTS[year]
        scorable = [p for p in pitches if SHIP._is_scorable(p)]
        del pitches
        for tag, fn, S in (('ship', SHIP.score_pitch, SHIP.build_surfaces(scorable, lg, scale)),
                           ('location', BR.location_value, BR.build_surfaces(scorable, lg, scale))):
            acc = {}
            for p in scorable:
                v = fn(p, S)
                if v is None:
                    continue
                for h in ('full', p['half']):
                    a = acc.setdefault((p['pid'], h), [0.0, 0])
                    a[0] += v
                    a[1] += 1
            rows[tag] += [{'pid': pid, 'season': year, 'half': h, 'locRaw': -s / n, 'locN': n} for (pid, h), (s, n) in acc.items()]
            del S
            gc.collect()
        print(f'{year}: {len(scorable)} scorable pitches', flush=True)
        del scorable
        gc.collect()
    old = pd.read_csv(os.path.join(DATA, '_pplus_locplus_hist.csv'))
    for tag, rr in rows.items():
        d = pd.DataFrame(rr)
        d.to_csv(CSV[tag] + '.tmp', index=False)
        os.replace(CSV[tag] + '.tmp', CSV[tag])
        m = d.merge(old, on=['pid', 'season', 'half'], suffixes=('', '_old'))
        m = m[(m['half'] == 'full') & (m['locN'] >= 300)]
        print(f'wrote {CSV[tag]} ({len(d)} rows); against the 2026-09-05 series, full rows 300+: r '
              f'{np.corrcoef(m.locRaw, m.locRaw_old)[0, 1]:.4f}, max |diff| {(m.locRaw - m.locRaw_old).abs().max():.6f}')


def build_shape(branch_path, tag='shape', ref_tag='location'):
    """Branch locplus-shape (2026-11-19): the shape-class grade needs the movement fields,
    so the season dicts are rebuilt here with IndVertBrk and HorzBrk (sheet convention:
    -pfx_x). Two series from the BRANCH module on the same pitches: 'location' (its bundle
    without the class part = the released grade; checked against the 2026-11-18 series) and
    'shape'. Only the shape CSV is written."""
    import pitcherplus_locplus_hist as H
    import leaderboard_metric_battery as bat
    sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'locplus'))
    import locplus_shape_loader as SL
    BR = SL.branch(branch_path)
    rows, ref = [], []
    for year in H.SEASONS:
        df = bat.load_season(year).reset_index(drop=True)
        df = bat.add_half(df, 'pitcher').reset_index(drop=True)
        ev = df['events'].fillna('')
        desc = df['description'].fillna('').map(lambda d: H.DESC_MAP.get(d, d))
        recs = pd.DataFrame({
            'pid': df['pitcher'], 'half': df['half'], 'Description': desc,
            'Count': df['balls'].fillna(-1).astype(int).astype(str) + '-' + df['strikes'].fillna(-1).astype(int).astype(str),
            'PlateX': df['plate_x'], 'PlateZ': df['plate_z'], 'SzTop': df['sz_top'], 'SzBot': df['sz_bot'],
            'Bats': df['stand'], 'Throws': df['p_throws'], 'Pitch Type': df['pitch_type'],
            'BBType': np.where(ev.isin(H.SH_EV), 'bunt', df['bb_type'].fillna('')),
            'Event': np.where(ev == 'intent_walk', 'Intent Walk', ''), 'RunExp': df['rv'],
            'xwOBA': df['estimated_woba_using_speedangle'],
            'IndVertBrk': df['pfx_z'] * 12.0, 'HorzBrk': -df['pfx_x'] * 12.0})
        recs['_source'] = 'MLB'
        pitches = recs.to_dict('records')
        del df, recs
        lg, scale = H.GUTS[year]
        scorable = [p for p in pitches if BR._is_scorable(p)]
        del pitches
        S = BR.build_surfaces(scorable, lg, scale)
        S0 = {k: v for k, v in S.items() if k != 'SHAPE'}
        for store, bundle in ((ref, S0), (rows, S)):
            acc = {}
            for p in scorable:
                v = BR.location_value(p, bundle)
                if v is None:
                    continue
                for h in ('full', p['half']):
                    a = acc.setdefault((p['pid'], h), [0.0, 0])
                    a[0] += v
                    a[1] += 1
            store += [{'pid': pid, 'season': year, 'half': h, 'locRaw': -s / n, 'locN': n} for (pid, h), (s, n) in acc.items()]
        print(f'{year}: {len(scorable)} scorable pitches', flush=True)
        del scorable, S, S0
        gc.collect()
    d, r = pd.DataFrame(rows), pd.DataFrame(ref)
    d.to_csv(CSV[tag] + '.tmp', index=False)
    os.replace(CSV[tag] + '.tmp', CSV[tag])
    old = pd.read_csv(CSV[ref_tag])
    for lab, t in (('branch grade without the newest part', r), ('branch grade', d)):
        m = t.merge(old, on=['pid', 'season', 'half'], suffixes=('', '_old'))
        m = m[(m['half'] == 'full') & (m['locN'] >= 300)]
        print(f'{lab} against the reference series ({ref_tag}), full rows 300+: r {np.corrcoef(m.locRaw, m.locRaw_old)[0, 1]:.4f}, '
              f'max |diff| {(m.locRaw - m.locRaw_old).abs().max():.6f}')
    print(f'wrote {CSV[tag]} ({len(d)} rows)')


def check(tags=('ship', 'location')):
    import pitcherplus_v14_audit as A
    import pitcherplus_k_sweep as KS
    import pitcherplus_v18_hand_check as HC
    ps = A.ps
    hm, rng = HC.hands(), np.random.default_rng(0)
    ship_k = {f: k for f, _w, k in A.SHIPPED}
    res = {}
    for tag in tags:
        ps.LOC_CSV = CSV[tag]
        t = A.load_tables(STUFF_V18)
        r_s, r_y = A.frozen_eval(t)
        r, nh, cross, n = KS.crossing(t, 'locRaw')
        sweep = []
        for k in K_GRID:
            km = dict(ship_k)
            km['locRaw'] = float(k)
            sweep.append((k,) + KS.eval_k(t, km))
        # the composite with the loc term removed (weight 0): what the component adds
        keep = A.SHIPPED
        A.SHIPPED = tuple((f, (0.0 if f == 'locRaw' else w), k) for f, w, k in keep)
        try:
            n_s, n_y = A.frozen_eval(t)
        finally:
            A.SHIPPED = keep
        res[tag] = {'r_S': r_s, 'r_Y': r_y, 'noloc_S': n_s, 'noloc_Y': n_y, 'half_r': r, 'half_n': nh, 'crossing': cross,
                    'sweep': sweep, 'hand': HC.offset(HC.pairs_table(t), hm, rng), 'w': HC.refit_weights(t)}
    print(f'\n{"loc series":<10s}{"frozen r_S":>11s}{"r_Y":>8s}{"mean":>8s} | {"no loc r_S":>11s}{"r_Y":>8s} | {"loc half r":>11s}{"crossing":>9s} | '
          f'{"L-R gap":>8s}{"LHP offset":>11s}{"se":>6s}')
    for tag, r in res.items():
        h = r['hand']
        print(f'{tag:<10s}{r["r_S"]:>11.4f}{r["r_Y"]:>8.4f}{(r["r_S"] + r["r_Y"]) / 2:>8.4f} | {r["noloc_S"]:>11.4f}{r["noloc_Y"]:>8.4f} | '
              f'{r["half_r"]:>11.3f}{r["crossing"]:>9.0f} | {h["gap_L_minus_R"]:>+8.2f}{h["offset_pts"]:>+11.2f}{h["se"]:>6.2f}')
    print('\ncomposite r by loc k (other five at shipped k; shipped loc k 215):')
    print(f'{"k":>6s}' + ''.join(f'{tag + " r_S":>14s}{tag + " r_Y":>14s}' for tag in res))
    for i, k in enumerate(K_GRID):
        print(f'{k:>6d}' + ''.join(f'{res[tag]["sweep"][i][1]:>14.4f}{res[tag]["sweep"][i][2]:>14.4f}' for tag in res))
    print('\nrefit weights of the shipped six (normalized; shipped: stuff .20 loc .06 k .21 izwhiff .19 xrv .23 gb .12)')
    for tag, r in res.items():
        for lab in ('S', 'Y'):
            print(f'  {tag:<9s} panel {lab}: ' + '  '.join(f'{k} {v:+.3f}' for k, v in r['w'][lab].items()))
    tmp = OUT + '.tmp'
    json.dump(res, open(tmp, 'w'), indent=1, default=float)
    os.replace(tmp, OUT)
    print(f'\nwrote {OUT}')


if __name__ == '__main__':
    if sys.argv[1] == 'build':
        build(sys.argv[2])
    elif sys.argv[1] == 'build_shape':
        build_shape(sys.argv[2])
    elif sys.argv[1] == 'check_shape':
        OUT = OUT.replace('.json', '_shape.json')
        check(('location', 'shape'))
    elif sys.argv[1] == 'build_far':          # branch locplus-farmiss: the reference is the shape series
        build_shape(sys.argv[2], 'far', 'shape')
    elif sys.argv[1] == 'check_far':
        OUT = OUT.replace('.json', '_far.json')
        check(('shape', 'far'))
    else:
        check()
