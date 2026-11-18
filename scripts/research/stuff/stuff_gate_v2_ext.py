#!/usr/bin/env python3
"""stuff_gate_v2_ext.py — gate v2 arms the gate's spec file cannot express.

Same frames, prepare(), design(), params, aggregates and pair rule as
stuff_gate_v2.py (model fit on neither Y nor Y+1). Adds:

  label 'cneutral'   train on target minus its season mean for the count
  label 'evcount'    non-contact pitches take the season mean run value of
                     their (result class, count): base-out state leaves the label
  head 'swing_only'  train on swung-at pitches only; the grade is the expected
                     value GIVEN a swing (PitchingBot's stuff definition)
  head 'two_head'    P(swing) x value given swing + (1 - P) x value given take
  recency d          training rows weighted d ** |season - Y|
  fbhand             fastball reference per batter hand (Driveline 2024)
  identity K, params, drop: as in the gate
  rows f             a random share f of the training rows (sample-size control)

Count and result class come from stuff_gate_v2_sidecar.py. Aggregates go to
data/_gate_v2/ext/agg_{name}_{Y}_s{seed}.pkl in the gate's format, plus 'py1x'
(the Y+1 count-neutral target per pitcher). stuff_gate_ext_summary.py reads them.

VALIDATION: arm SHIPPED_CHK (seed 0) must reproduce the gate's cached SHIPPED
aggregate for the pair; the run stops if nxt_r differs by more than 1e-4.

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/stuff/stuff_gate_v2_ext.py --arms NOCROSS,CNEUT
"""
import argparse
import gc
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import xgboost as xgb

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stuff_gate_v2 as G  # noqa: E402

T = G.T
EXT = os.path.join(G.CACHE, 'ext')
ARMS = {
    'SHIPPED_CHK': {},
    'NOCROSS': {'drop': ['cross', 'cross_abs']},
    'NOARM': {'drop': ['arm_angle']},
    'CNEUT': {'label': 'cneutral'},
    'EVCNT': {'label': 'evcount'},
    'SWONLY': {'head': 'swing_only'},
    'TWOHEAD': {'head': 'two_head'},
    'REC08': {'recency': 0.8},
    'REC06': {'recency': 0.6},
    'FBHAND': {'fbhand': True},
    'IDENT3': {'identity': 3},
    'CAP_COARSE': {'params': {'n_estimators': 400, 'learning_rate': 0.05}},
    'CAP_FINE': {'params': {'n_estimators': 1600, 'learning_rate': 0.0125}},
    'SUB06': {'params': {'subsample': 0.6, 'colsample_bytree': 0.6}},
    # identity follow-ups (2026-11-18): is a feature's gain pitch physics or pitcher identity?
    'ROWS70': {'rows': 0.7},                      # sample-size control for IDENT3
    'IDENT3_NOH': {'identity': 3, 'drop': ['height']},
    'IDENT3_NOARM': {'identity': 3, 'drop': ['arm_angle']},
    'IDENT3_NOCROSS': {'identity': 3, 'drop': ['cross', 'cross_abs']},
    # left-hander level (2026-11-18): pitcher hand as a model feature, with and without identity.
    # Since v18 the gate default already holds is_lhp, so LHP differs from V18DEF only in
    # where the column sits.
    'LHP': {'add': ['is_lhp']},
    'IDENT3_LHP': {'identity': 3, 'add': ['is_lhp']},
    'V18DEF': {},                                 # the gate default after v18 (pitcher hand in the design)
}
EV_MIN = 50


def agg_path(name, Y, seed):
    return os.path.join(EXT, f'agg_{name}_{Y}_s{seed}.pkl')


def attach_sidecar(d, y):
    sc = pd.read_pickle(os.path.join(G.CACHE, f'sidecar_{y}.pkl'))
    if len(sc) != len(d):
        sys.exit(f'{y}: sidecar rows {len(sc)} != frame rows {len(d)}')
    d = d.copy()
    d['balls'], d['strikes'] = sc['balls'].values, sc['strikes'].values
    d['cls'], d['swing'] = sc['cls'].values, sc['swing'].values
    cnt = d['balls'] * 10 + d['strikes']
    # season mean of the target by count; rows with no count are left as they are
    cm = d.groupby(cnt)['target_xrv'].transform('mean')
    d['t_cn'] = d['target_xrv'] - cm.fillna(0.0)
    # count-only value of a non-contact pitch
    g = d.groupby([d['cls'], cnt])['target_xrv']
    ev, n = g.transform('mean'), g.transform('size')
    use = (d['cls'] != 'bip') & ev.notna() & (n >= EV_MIN)
    d['t_ev'] = np.where(use, ev, d['target_xrv'])
    return d


def fbhand(d):
    """Differentials against the primary fastball thrown to THAT batter hand.
    A (pitcher, hand, batter side) with no fastball keeps the season reference."""
    d = d.copy()
    key = ['pitcher', 'throws', 'platoon_same']
    fb = d[d['pitch_type'].isin(T.FB_TYPES)]
    cnt = fb.groupby(key + ['pitch_type']).size()
    prim = {}
    for k, g in cnt.groupby(level=[0, 1, 2]):
        by = {pt: n for (_, _, _, pt), n in g.items()}
        if k[0] in T.FC_ANCHOR_PITCHERS and 'FC' in by:
            cand = {'FC': by['FC']}
        else:
            cand = {pt: n for pt, n in by.items() if pt in ('FF', 'SI')} or by
        prim[k] = max(cand, key=cand.get)
    kk = list(zip(d['pitcher'], d['throws'], d['platoon_same']))
    is_ref = (d['pitch_type'].values == np.array([prim.get(k) for k in kk], dtype=object))
    ref = d[is_ref].groupby(key)[['velocity', 'ivb', 'hb', 'vaa']].mean()
    ref.columns = ['r_v', 'r_iv', 'r_hb', 'r_vaa']
    j = d.join(ref, on=key)
    ok = j['r_v'].notna().values
    vd = (j['velocity'] - j['r_v']).values
    d['velo_diff_raw'] = np.where(ok, vd, d['velo_diff_raw'].values).astype('float32')
    d['velo_diff'] = d['velo_diff_raw'].where(~d['pitch_type'].isin(T.VD_MASK_TYPES))
    for c, a, r in (('ivb_diff', 'ivb', 'r_iv'), ('hb_diff', 'hb', 'r_hb'), ('vaa_diff', 'vaa', 'r_vaa')):
        d[c] = np.where(ok, (j[a] - j[r]).values, d[c].values).astype('float32')
    print(f'    fbhand: {ok.mean():.1%} of rows take a batter-hand reference', flush=True)
    return d


def params_for(X, spec, seed, clf=False):
    p = T._params_for(X)
    p.update(spec.get('params') or {})
    p['monotone_constraints'] = tuple(0 if clf else (-1 if c == T.MONO_FEAT else 0) for c in X.columns)
    p['random_state'] = seed
    return p


def fit_reg(Xtr, ytr, XY, spec, seed, w=None):
    m = xgb.XGBRegressor(**params_for(Xtr, spec, seed))
    m.fit(Xtr, ytr, sample_weight=w)
    out = m.predict(XY)
    del m
    return out


def fit_clf(Xtr, ytr, XY, spec, seed):
    m = xgb.XGBClassifier(**params_for(Xtr, spec, seed, clf=True))
    m.fit(Xtr, ytr)
    out = m.predict_proba(XY)[:, 1]
    del m
    return out


def run(arms, pairs, seed):
    os.makedirs(EXT, exist_ok=True)
    frames = {y: G.load_frame(y) for y in G.SEASONS}
    G.set_arm_side_sign(list(frames.values()))
    for Y, Y1 in pairs:
        todo = [a for a in arms if not os.path.exists(agg_path(a, Y, seed))]
        if not todo:
            print(f'=== pair {Y}->{Y1}: all cached', flush=True)
            continue
        train_years = [y for y in G.SEASONS if y not in (Y, Y1)]
        print(f'\n=== pair {Y}->{Y1} (train {train_years}) ===', flush=True)
        slopes = G.fit_vaa_slopes([frames[y] for y in train_years])
        P = {y: attach_sidecar(G.prepare(frames[y], slopes, 'true'), y) for y in train_years + [Y, Y1]}
        PH = None
        gc.collect()
        for name in todo:
            spec = ARMS[name]
            t0 = time.time()
            Q = P
            if spec.get('fbhand'):
                if PH is None:
                    PH = {y: fbhand(P[y]) for y in P}
                Q = PH
            feats = G.variant_feats(spec)
            Xtr = pd.concat([G.design(Q[y], spec, feats) for y in train_years], ignore_index=True)
            col = {'cneutral': 't_cn', 'evcount': 't_ev'}.get(spec.get('label'), 'target_xrv')
            ytr = np.concatenate([Q[y][col].values.astype(float) for y in train_years])
            dY = Q[Y]
            XY = G.design(dY, spec, feats)
            w = None
            if spec.get('recency'):
                w = np.concatenate([np.full(len(Q[y]), float(spec['recency']) ** abs(y - Y)) for y in train_years])
            head = spec.get('head')
            if head:
                sw = np.concatenate([Q[y]['swing'].values.astype(float) for y in train_years])
                ms, mt = sw == 1.0, sw == 0.0
                v_sw = fit_reg(Xtr[ms], ytr[ms], XY, spec, seed)
                if head == 'swing_only':
                    pred = v_sw
                else:
                    v_tk = fit_reg(Xtr[mt], ytr[mt], XY, spec, seed)
                    known = ms | mt
                    p_sw = fit_clf(Xtr[known], sw[known].astype(int), XY, spec, seed)
                    pred = p_sw * v_sw + (1.0 - p_sw) * v_tk
            elif spec.get('identity'):
                K = int(spec['identity'])
                rng = np.random.default_rng(1000 + seed)
                ptr = np.concatenate([Q[y]['pitcher'].values for y in train_years])
                pits = np.array(sorted(dY['pitcher'].unique()))
                fold_of = dict(zip(pits, rng.permutation(len(pits)) % K))
                fy = dY['pitcher'].map(fold_of).values
                ftr = np.array([fold_of.get(p, -1) for p in ptr])
                pred = np.full(len(dY), np.nan, dtype='float32')
                for k in range(K):
                    keep = ftr != k
                    pred[fy == k] = fit_reg(Xtr[keep], ytr[keep], XY[fy == k], spec, seed)
            elif spec.get('rows'):
                keep = np.random.default_rng(1000 + seed).random(len(Xtr)) < float(spec['rows'])
                pred = fit_reg(Xtr[keep], ytr[keep], XY, spec, seed)
            else:
                pred = fit_reg(Xtr, ytr, XY, spec, seed, w)
            agg = G.aggregates(dY.assign(stuff=-pred), Q[Y1])
            met = G.metrics_from(agg)
            d1 = Q[Y1]
            agg['py1x'] = d1.assign(_cn=-d1['t_cn']).groupby('pitcher').agg(tcn=('_cn', 'mean'))
            if name == 'SHIPPED_CHK' and os.path.exists(G.agg_path('SHIPPED', Y, seed)):
                ref = G.metrics_from(pd.read_pickle(G.agg_path('SHIPPED', Y, seed)))
                diff = abs(met['nxt_r'] - ref['nxt_r'])
                print(f'  VALIDATION {Y}: ext nxt_r {met["nxt_r"]:.5f} vs gate SHIPPED {ref["nxt_r"]:.5f} '
                      f'(diff {diff:.6f})', flush=True)
                if diff > 1e-4:
                    sys.exit('ext driver does not reproduce the gate. Stopped.')
            tmp = agg_path(name, Y, seed) + '.tmp'
            pd.to_pickle(agg, tmp)
            os.replace(tmp, agg_path(name, Y, seed))
            print(f'  {name:<12} s{seed} nxt raw {met["nxt_r"]:.4f} rend {met["nxt_r_rend"]:.4f} '
                  f'rv {met["nxt_rv_r"]:.4f} rel {met["rel"]:.4f} [{time.time() - t0:.0f}s]', flush=True)
            del Xtr, XY, agg, ytr, pred
            gc.collect()
        del P, PH
        gc.collect()


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--arms', required=True)
    ap.add_argument('--pairs', default='2021,2022,2023,2024,2025')
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    arms = a.arms.split(',')
    for x in arms:
        if x not in ARMS:
            sys.exit(f'unknown arm {x}')
    run(arms, [(int(y), int(y) + 1) for y in a.pairs.split(',')], a.seed)
