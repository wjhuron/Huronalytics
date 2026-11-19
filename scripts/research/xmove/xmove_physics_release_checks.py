#!/usr/bin/env python3
"""xmove_physics_release_checks.py — what a release of the per-pitch physics expectation must settle.

  A  COVERAGE   which 2026 pitches carry every input, by level (MLB / ROC / AAA / other), and
                which lack only the arm angle (the fallback's pool)
  B  SCORING RULE   one model fit on ALL pitchers, against the research rule (each pitcher
                scored by a model that never saw him, five folds): how far apart are the two
                expectations for a pitcher's pitch type, and how much lower is the in-sample miss
  C  REPEATABILITY  the same fit twice, and once on one thread: are the predictions identical
  D  EXPORT     the fitted trees written as plain arrays and scored with numpy alone: does it
                equal scikit-learn's own predict, how large is the export, how long does it take

  .venv/bin/python scripts/research/xmove/xmove_physics_release_checks.py
"""
import json
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import xmove_physics_fit as PF  # noqa: E402
import xmove_cavalli_proto as CP  # noqa: E402

LEAVES, MSL, ROUNDS, LR = 10, 200, 200, 0.1
NEED = ['xIndVrtBrk', 'xHorzBrk', 'Velocity', 'Spin Rate', 'ArmAngle', 'Extension', 'RelPosZ', 'RelPosX']


def model():
    from sklearn.ensemble import HistGradientBoostingRegressor as H
    return H(max_iter=ROUNDS, learning_rate=LR, max_leaf_nodes=LEAVES, min_samples_leaf=MSL, early_stopping=False, random_state=0)


def export_trees(m):
    """Plain arrays of a fitted HistGradientBoostingRegressor: baseline + per-tree node tables."""
    trees = []
    for (pred,) in m._predictors:
        nd = pred.nodes
        trees.append({'f': nd['feature_idx'].astype(int).tolist(), 't': nd['num_threshold'].astype(float).tolist(),
                      'l': nd['left'].astype(int).tolist(), 'r': nd['right'].astype(int).tolist(),
                      'v': nd['value'].astype(float).tolist(), 'leaf': nd['is_leaf'].astype(int).tolist(),
                      'ml': nd['missing_go_to_left'].astype(int).tolist()})
    return {'base': float(np.ravel(m._baseline_prediction)[0]), 'trees': trees}


def predict_trees(ex, X):
    out = np.full(len(X), ex['base'])
    rows = np.arange(len(X))
    for t in ex['trees']:
        f, th, lf, rt, v, leaf = (np.asarray(t[k]) for k in ('f', 't', 'l', 'r', 'v', 'leaf'))
        node = np.zeros(len(X), dtype=np.int64)
        live = leaf[node] == 0
        while live.any():
            ix = rows[live]
            n = node[ix]
            go_left = X[ix, f[n]] <= th[n]
            node[ix] = np.where(go_left, lf[n], rt[n])
            live = leaf[node] == 0
        out += v[node]
    return out


def main():
    with open(f'{ROOT}/data/all_pitches_rs_cache.pkl', 'rb') as fh:
        rows = pickle.load(fh)
    keep = ['Pitcher', 'Throws', 'Pitch Type', '_source', 'RTilt', 'PTeam'] + NEED
    df = pd.DataFrame([{k: r.get(k) for k in keep} for r in rows])
    del rows
    for c in NEED:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df['axis'] = df['RTilt'].map(CP.clock_to_deg)
    df['lvl'] = df['_source'].fillna('MLB')
    core = ['xIndVrtBrk', 'xHorzBrk', 'Velocity', 'Spin Rate', 'axis', 'Extension']
    print('A. COVERAGE (2026 pickle): pitches with a pitch type and hand')
    df = df[df['Pitch Type'].notna() & df['Throws'].isin(['L', 'R'])]
    print(f'{"level":<8s}{"pitches":>10s}{"all inputs":>12s}{"all but arm angle":>19s}{"no spin or axis":>17s}{"no movement":>13s}')
    for lv, g in df.groupby('lvl'):
        full = g[core + ['ArmAngle']].notna().all(axis=1)
        noaa = g[core].notna().all(axis=1) & g['ArmAngle'].isna()
        nospin = g[['Spin Rate', 'axis']].isna().any(axis=1) & g[['xIndVrtBrk', 'xHorzBrk', 'Velocity']].notna().all(axis=1)
        nomove = g[['xIndVrtBrk', 'xHorzBrk']].isna().any(axis=1)
        print(f'{str(lv):<8s}{len(g):>10,d}{full.mean():>12.1%}{noaa.mean():>19.1%}{nospin.mean():>17.1%}{nomove.mean():>13.1%}')
    noaa_all = df[core].notna().all(axis=1) & df['ArmAngle'].isna()
    print(f'   of the pitches that lack only the arm angle, {df.loc[noaa_all, ["RelPosZ", "RelPosX"]].notna().all(axis=1).mean():.1%} have a release point')

    m26 = df[(df['lvl'] == 'MLB') & df['Pitch Type'].isin(PF.PTS)].dropna(subset=NEED + ['axis']).reset_index(drop=True)
    s = np.where(m26['Throws'] == 'R', 1.0, -1.0)
    A = PF.build(m26, np.radians(m26['axis'].values.astype('f8') * s), s)
    X = np.column_stack([A[c] for c in PF.BASE])
    n = len(X)

    print(f'\nB. SCORING RULE ({n:,} MLB pitches)')
    t = time.time()
    mi, mh = model().fit(X, A['ivb']), model().fit(X, A['hb_s'])
    fit_s = time.time() - t
    ai, ah = mi.predict(X), mh.predict(X)
    r = PF.fit_predict(A, PF.BASE, LEAVES, MSL, ROUNDS, LR, 5, hands='pool')[ROUNDS]
    ma, _ = PF.metrics(A, ai, ah)
    mo, _ = PF.metrics(A, *r)
    print(f'   miss (RMSE, in): model fit on all pitchers {ma["rmse"]:.3f}; each pitcher held out {mo["rmse"]:.3f}')
    u = pd.DataFrame({'p': A['pitcher'], 'pt': A['pt'], 'di': ai - r[0], 'dh': ah - r[1]}).groupby(['p', 'pt']).agg(n=('di', 'size'), di=('di', 'mean'), dh=('dh', 'mean'))
    for floor in (30, 150):
        g = u[u['n'] >= floor]
        d = np.hypot(g['di'], g['dh'])
        print(f'   expectation of a pitcher\'s pitch type, all-pitchers model minus held-out model ({floor}+ pitches, {len(g)} units): '
              f'median {d.median():.2f} in, 90th pct {d.quantile(.9):.2f}, 99th pct {d.quantile(.99):.2f}, max {d.max():.2f}')
    oi, oh = A['ivb'] - ai, A['hb_s'] - ah
    ho_i, ho_h = A['ivb'] - r[0], A['hb_s'] - r[1]
    ua = pd.DataFrame({'p': A['pitcher'], 'pt': A['pt'], 'a': oi, 'b': ho_i, 'c': oh, 'd': ho_h}).groupby(['p', 'pt']).agg(n=('a', 'size'), a=('a', 'mean'), b=('b', 'mean'), c=('c', 'mean'), d=('d', 'mean'))
    ua = ua[ua['n'] >= 150]
    print(f'   arrows of those units: SD ride {ua.a.std():.2f} (all) against {ua.b.std():.2f} (held out); run {ua.c.std():.2f} against {ua.d.std():.2f}; '
          f'r {np.corrcoef(ua.a, ua.b)[0, 1]:.3f} / {np.corrcoef(ua.c, ua.d)[0, 1]:.3f}')

    print('\nC. REPEATABILITY')
    b2 = model().fit(X, A['ivb']).predict(X)
    print(f'   same fit twice: largest difference {np.abs(b2 - ai).max():.2e} in')
    try:
        from threadpoolctl import threadpool_limits
        with threadpool_limits(limits=1):
            b3 = model().fit(X, A['ivb']).predict(X)
        print(f'   one thread against all threads: largest difference {np.abs(b3 - ai).max():.2e} in')
    except ImportError:
        print('   threadpoolctl not installed: thread-count check not run')

    print('\nD. EXPORT')
    ex_i, ex_h = export_trees(mi), export_trees(mh)
    blob = json.dumps({'ivb': ex_i, 'hb': ex_h}, separators=(',', ':'))
    back = json.loads(blob)
    t = time.time()
    pi = predict_trees(back['ivb'], X)
    np_s = time.time() - t
    ph = predict_trees(back['hb'], X)
    print(f'   numpy scoring from the exported arrays against scikit-learn predict: largest difference ride {np.abs(pi - ai).max():.2e} in, run {np.abs(ph - ah).max():.2e} in')
    print(f'   export size {len(blob) / 1024:.0f} KB of JSON for both targets; fit {fit_s:.0f} s for both targets; numpy scoring {np_s:.0f} s per target on {n:,} pitches')
    print(f'   any missing-value branch used: {any(any(t["ml"]) for t in ex_i["trees"])} (inputs carry no missing values)')


if __name__ == '__main__':
    main()
