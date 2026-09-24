#!/usr/bin/env python3
"""stuff_sweeper_diagnostics.py — two diagnostics for the sweeper validity gap.

Context: stuff_sweeper_validity.py (2026-09-23). ST Stuff+ carries to the next
season at r .11 against .28-.42 for every other type; noise, spread, labels
and the monotone velocity rule are ruled out; the model misses sweeper value.

D1  TYPE-ONLY MODEL. Is the one-model, pitch-type-agnostic design the cause?
    For each gate pair (Y, Y+1) the SHIPPED features are fit on ONE type's
    pitches from the training seasons (every season except Y and Y+1) and
    score that type's Y pitches. Controls: SL-only and CU-only, so a gain
    that every type-only model shows (a sample/fit effect) is not read as a
    sweeper effect. Diagnostic only: a type-only model breaks the shipped
    design (train_stuff.design docstring).

D2  SHAPE STABILITY. Is the cause pitch change between seasons? Unit shape
    change d = standardized Euclidean change of (velocity, ivb, hb) unit
    means, Y -> Y+1, each axis scaled by its between-pitcher SD within
    (pair, type). Validity of the SHIPPED grade within terciles of d, for
    ST and the SL/CU controls.

Validity everywhere: unit grade in Y (z-scored within pair on the analysis
units) vs unit xRV in Y+1 (pitcher-positive, demeaned within pair), units
>= 150 pitches both seasons. Paired pitcher bootstrap for deltas.

Output: data/_sweeper_diagnostics.json. Run from the repo root.
"""
import gc
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import xgboost as xgb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
import stuff_gate_v2 as G                               # noqa: E402

T = G.T
OUT = os.path.join(ROOT, 'data', '_sweeper_diagnostics.json')
PRED_DIR = os.path.join(ROOT, 'data', '_platoon_split')
TYPES = ['ST', 'SL', 'CU']
MIN_U = 150
SEED = 0
BOOT_B = 1000


def type_only_preds(frames):
    """(pair, type) -> Y-pitch predictions from a type-only fit, cached."""
    out = {}
    for Y, Y1 in G.PAIRS:
        path = os.path.join(PRED_DIR, f'typeonly_{Y}.pkl')
        if os.path.exists(path):
            out[Y] = pd.read_pickle(path)
            print(f'  {Y}: cached type-only predictions', flush=True)
            continue
        t0 = time.time()
        train_years = [y for y in G.SEASONS if y not in (Y, Y1)]
        slopes = G.fit_vaa_slopes([frames[y] for y in train_years])
        P = {y: G.prepare(frames[y], slopes) for y in train_years + [Y]}
        feats = G.variant_feats({})
        dY = P[Y]
        pred = pd.Series(np.nan, index=dY.index)
        for t in TYPES:
            parts = [P[y][P[y]['pitch_type'] == t] for y in train_years]
            Xtr = pd.concat([G.design(p, {}, feats) for p in parts], ignore_index=True)
            ytr = np.concatenate([p['target_xrv'].values for p in parts])
            params = T._params_for(Xtr)
            params['random_state'] = SEED
            m = xgb.XGBRegressor(**params)
            m.fit(Xtr, ytr)
            sel = (dY['pitch_type'] == t).values
            pred[sel] = m.predict(G.design(dY[sel], {}, feats))
            print(f'  {Y} {t}-only: {len(ytr)} training pitches [{time.time() - t0:.0f}s]', flush=True)
            del Xtr, ytr, m
        o = pd.DataFrame({'pitcher': dY['pitcher'].values, 'pitch_type': dY['pitch_type'].values,
                          'stuff_type': -pred.values})
        o.to_pickle(path)
        out[Y] = o
        del P
        gc.collect()
    return out


def zin(s):
    return (s - s.mean()) / s.std()


def corr(a, b):
    return float(np.corrcoef(a, b)[0, 1])


def boot_delta(g, fa, fb, B=BOOT_B, seed=13):
    """Paired pitcher bootstrap of r(fb) - r(fa); fa/fb take a frame -> r."""
    pits = g['pitcher'].unique()
    idx = {p: np.flatnonzero(g['pitcher'].values == p) for p in pits}
    rng = np.random.default_rng(seed)
    ds = []
    for _ in range(B):
        q = g.iloc[np.concatenate([idx[p] for p in rng.choice(pits, len(pits))])]
        ds.append(fb(q) - fa(q))
    return float(np.std(ds))


def main():
    t0 = time.time()
    frames = {y: G.load_frame(y) for y in G.SEASONS}
    G.set_arm_side_sign(list(frames.values()))
    TO = type_only_preds(frames)

    rows = []
    for Y, Y1 in G.PAIRS:
        fY, fY1 = frames[Y], frames[Y1]
        base = pd.read_pickle(os.path.join(PRED_DIR, f'pred_{Y}.pkl'))
        if len(base) != len(fY) or not (base['pitcher'].values == fY['pitcher'].values).all():
            raise SystemExit(f'pred_{Y}.pkl is not row-aligned with season_{Y}; rebuild it')
        d = fY[['pitcher', 'pitch_type', 'velocity', 'ivb', 'hb']].assign(
            s=base['stuff'].values, s_type=TO[Y]['stuff_type'].values)
        d = d[d['pitch_type'].isin(TYPES)]
        uY = d.groupby(['pitcher', 'pitch_type']).agg(
            s=('s', 'mean'), s_type=('s_type', 'mean'), n=('s', 'size'),
            v=('velocity', 'mean'), iv=('ivb', 'mean'), hb=('hb', 'mean'))
        e = fY1[fY1['pitch_type'].isin(TYPES)].assign(t=-fY1['target_xrv'].astype(float))
        uY1 = e.groupby(['pitcher', 'pitch_type']).agg(
            t1=('t', 'mean'), n1=('t', 'size'), v1=('velocity', 'mean'),
            iv1=('ivb', 'mean'), hb1=('hb', 'mean'))
        j = uY.join(uY1, how='inner').reset_index()
        j = j[(j['n'] >= MIN_U) & (j['n1'] >= MIN_U)].copy()
        j['pair'] = Y
        for t, g in j.groupby('pitch_type'):
            m = j['pitch_type'] == t
            j.loc[m, 'zs'] = zin(g['s'])
            j.loc[m, 'zst'] = zin(g['s_type'])
            j.loc[m, 't1c'] = g['t1'] - g['t1'].mean()
            dd = 0.0
            for a, b in (('v', 'v1'), ('iv', 'iv1'), ('hb', 'hb1')):
                sd = pd.concat([g[a], g[b]]).std()
                dd = dd + ((g[b] - g[a]) / sd) ** 2
            j.loc[m, 'shape_d'] = np.sqrt(dd)
        rows.append(j)
    U = pd.concat(rows, ignore_index=True)

    out = {'D1_type_only': {}, 'D2_shape_stability': {}}
    print('\nD1 type-only model vs shipped (unit grade Y vs unit xRV Y+1):')
    print('type  units  shipped  type-only  delta   se     z   per-pair deltas')
    for t in TYPES:
        g = U[U['pitch_type'] == t].reset_index(drop=True)
        ra, rb = corr(g['zs'], g['t1c']), corr(g['zst'], g['t1c'])
        se = boot_delta(g, lambda q: corr(q['zs'], q['t1c']), lambda q: corr(q['zst'], q['t1c']))
        pp = {str(y): corr(h['zst'], h['t1c']) - corr(h['zs'], h['t1c']) for y, h in g.groupby('pair')}
        out['D1_type_only'][t] = {'units': int(len(g)), 'shipped': ra, 'type_only': rb,
                                  'delta': rb - ra, 'se': se, 'z': (rb - ra) / se, 'per_pair': pp,
                                  'r_between_grades': corr(g['zs'], g['zst'])}
        print(f'{t:4} {len(g):6}  {ra:7.3f}  {rb:9.3f}  {rb - ra:+.3f}  {se:.3f}  {(rb - ra) / se:+5.1f}  '
              + ' '.join(f'{v:+.3f}' for v in pp.values())
              + f'   r(shipped, type-only grade) {corr(g["zs"], g["zst"]):.2f}')

    print('\nD2 shipped validity by shape-change tercile (Y -> Y+1 change in velo/ivb/hb):')
    print('type  tercile  units  median_d  r(grade, next)')
    for t in TYPES:
        g = U[U['pitch_type'] == t].copy()
        g['terc'] = pd.qcut(g['shape_d'], 3, labels=['stable', 'middle', 'changed'])
        rec = {}
        for lab, h in g.groupby('terc', observed=True):
            rv = corr(h['zs'], h['t1c'])
            rec[str(lab)] = {'units': int(len(h)), 'median_d': float(h['shape_d'].median()), 'r': rv}
            print(f'{t:4}  {lab:<8} {len(h):5}  {h["shape_d"].median():8.2f}  {rv:.3f}')
        rec['median_d_all'] = float(g['shape_d'].median())
        out['D2_shape_stability'][t] = rec
    json.dump(out, open(OUT + '.tmp', 'w'), indent=1)
    os.replace(OUT + '.tmp', OUT)
    print(f'\nwrote {OUT} [{time.time() - t0:.0f}s]')


if __name__ == '__main__':
    main()
