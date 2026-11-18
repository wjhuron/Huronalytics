#!/usr/bin/env python3
"""hpera_new_inputs_build.py — per-pitcher inputs for refitting hpERA on the
candidate Stuff+ and Loc+ definitions of 2026-11-18.

Writes data/_era_new_inputs.json in the shape the ERA harness reads
({season: {mlb id: {...}}}, ids resolved from data/_era_targets.json names by
era_stuff_loso_v2.name_map; ambiguous names are dropped there):

  Stuff+ (raw, pitcher-positive mean per pitch), two arms: 'base' = shipped
  features, 'hand' = shipped + pitcher hand (is_lhp)
    stuff_{arm}_full   season Y, from the gate pair model fit on NEITHER Y nor Y+1
                       (cached aggregates; 2021-2025). The existing input used a
                       leave-one-season-out model, which has seen Y+1.
    stuff_{arm}_h1     pitches on or before the All-Star date, from a model fit on
                       the other five seasons (the rest-of-season target is in Y,
                       so Y is out of the fit). 2021-2026.
  Loc+ (hitter-positive mean per pitch, the harness's convention), from the
  season's own full-season surfaces:
    loc_ship_{scope}   shipped value (rebuilt; checks against _era_internal_cmdloc)
    loc_part_{scope}   location part, ball in play in count currency
    sit_{scope}        situation part on shipped pricing
  with n_{scope} pitch counts. MIN_N 50, as the existing builders.

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/era/hpera_new_inputs_build.py
"""
import gc
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
for sub in ('stuff', 'locplus'):
    sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', sub))
sys.path.insert(0, HERE)
import stuff_gate_v2 as G  # noqa: E402
import stuff_gate_v2_ext as E  # noqa: E402
from era_stuff_loso_v2 import name_map, TARGETS  # noqa: E402

OUT = os.path.join(ROOT, 'data', '_era_new_inputs.json')
PRED = os.path.join(ROOT, 'data', '_era_new_inputs_pred')
YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
ARMS = {'base': {}, 'hand': {'add': ['is_lhp']}}
MIN_N = 50


def put(res, y, name_to_vals, nm):
    miss = 0
    for name, vals in name_to_vals.items():
        pid = nm.get(str(name).lower())
        if pid is None:
            miss += 1
            continue
        res.setdefault(str(y), {}).setdefault(str(pid), {}).update(vals)
    return miss


def stuff_h1(res):
    os.makedirs(PRED, exist_ok=True)
    frames = {y: G.load_frame(y) for y in YEARS}
    G.set_arm_side_sign(list(frames.values()))
    for Y in YEARS:
        train = [y for y in YEARS if y != Y]
        todo = [a for a in ARMS if not os.path.exists(os.path.join(PRED, f'{a}_{Y}.npy'))]
        if todo:
            slopes = G.fit_vaa_slopes([frames[y] for y in train])
            P = {y: G.prepare(frames[y], slopes, 'true') for y in train + [Y]}
            for a in todo:
                spec = ARMS[a]
                feats = G.variant_feats(spec)
                Xtr = pd.concat([G.design(P[y], spec, feats) for y in train], ignore_index=True)
                ytr = np.concatenate([P[y]['target_xrv'].values for y in train])
                pred = G.fit_predict(Xtr, ytr, G.design(P[Y], spec, feats), spec, 0)
                np.save(os.path.join(PRED, f'{a}_{Y}.npy'), (-pred).astype('float32'))
                print(f'  fit {a} held-out {Y}', flush=True)
                del Xtr
            del P
            gc.collect()
        asg, nm = TARGETS[str(Y)]['asg'], name_map(Y)
        d = frames[Y][['pitcher', 'date']].copy()
        h1 = d['date'].astype(str).str[:10] <= asg
        for a in ARMS:
            d['s'] = np.load(os.path.join(PRED, f'{a}_{Y}.npy'))
            g = d[h1.values].groupby('pitcher')['s'].agg(['mean', 'size'])
            g = g[g['size'] >= MIN_N]
            miss = put(res, Y, {n: {f'stuff_{a}_h1': float(r['mean']), 'n_stuff_h1': int(r['size'])} for n, r in g.iterrows()}, nm)
        print(f'{Y}: stuff h1 for {len(g)} pitchers, {miss} unmatched names', flush=True)
    # full scope from the pair models (fit on neither Y nor Y+1)
    for Y in YEARS[:-1]:
        nm = name_map(Y)
        for a, fn in (('base', G.agg_path('SHIPPED', Y, 0)), ('hand', E.agg_path('LHP', Y, 0))):
            s = pd.read_pickle(fn)['pitch'][0]
            d = pd.DataFrame({'pitcher': frames[Y]['pitcher'].values, 's': s})
            g = d.groupby('pitcher')['s'].agg(['mean', 'size'])
            g = g[g['size'] >= MIN_N]
            put(res, Y, {n: {f'stuff_{a}_full': float(r['mean']), 'n_stuff_full': int(r['size'])} for n, r in g.iterrows()}, nm)
    del frames
    gc.collect()


def loc_parts(res):
    import pipeline.locplus as lp
    import locplus_fullseason_replicate as FR
    import locplus_count_calibration as CC
    for Y in YEARS:
        pitches = FR.load_season(Y)
        base_p = [p for p in pitches if lp.is_eligible_baseline(p)]
        S = lp.build_surfaces(base_p, FR.LG, FR.SCALE)
        off = lp.build_bip_count_offsets(base_p, FR.LG, FR.SCALE)
        asg, nm = TARGETS[str(Y)]['asg'], name_map(Y)
        rows = []
        for p in pitches:
            if not lp._is_scorable(p):
                continue
            v0 = lp.score_pitch(p, S)
            if v0 is None:
                continue
            rows.append((p.get('Pitcher'), lp.group_of(p), p.get('Bats'), p.get('Throws'), lp.get_count(p),
                         str(p.get('Game Date'))[:10] <= asg, v0, CC.score(p, S, off, None)))
        del pitches, base_p, S
        gc.collect()
        d = pd.DataFrame(rows, columns=['pitcher', 'grp', 'bats', 'throws', 'count', 'h1', 'v_ship', 'v_anch'])
        cell = ['grp', 'bats', 'throws', 'count']
        d['sit'] = d.groupby(cell)['v_ship'].transform('mean')
        d['loc_part'] = d['v_anch'] - d.groupby(cell)['v_anch'].transform('mean')
        for scope, sub in (('full', d), ('h1', d[d['h1']])):
            g = sub.groupby('pitcher').agg(loc_ship=('v_ship', 'mean'), loc_part=('loc_part', 'mean'),
                                           sit=('sit', 'mean'), n=('v_ship', 'size'))
            g = g[g['n'] >= MIN_N]
            miss = put(res, Y, {n: {f'loc_ship_{scope}': float(r.loc_ship), f'loc_part_{scope}': float(r.loc_part),
                                    f'sit_{scope}': float(r.sit), f'n_loc_{scope}': int(r.n)} for n, r in g.iterrows()}, nm)
        print(f'{Y}: loc parts for {len(g)} pitchers (h1), {miss} unmatched names', flush=True)
        del d
        gc.collect()


def main():
    res = {}
    stuff_h1(res)
    loc_parts(res)
    # check the rebuilt shipped loc against the existing ERA input
    old = json.load(open(os.path.join(ROOT, 'data', '_era_internal_cmdloc.json')))
    for y in ('2022', '2024'):
        a, b = [], []
        for pid, r in res.get(y, {}).items():
            o = old.get(y, {}).get(pid, {})
            if 'loc_ship_full' in r and 'loc_full' in o and r['n_loc_full'] >= 300:
                a.append(r['loc_ship_full']); b.append(o['loc_full'])
        print(f'check {y}: rebuilt shipped loc vs _era_internal_cmdloc, n {len(a)}, r {np.corrcoef(a, b)[0, 1]:.4f}')
    tmp = OUT + '.tmp'
    json.dump(res, open(tmp, 'w'))
    os.replace(tmp, OUT)
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
