#!/usr/bin/env python3
"""stuff_gate_v2_sidecar.py — count and pitch-result columns aligned to the gate
v2 season frames (data/_gate_v2/season_{y}.pkl), which keep neither.

The frames are train_stuff.build_df output in pitch order, filtered to rows with
a target. This rebuilds that row order (same pickles, same build_df call), checks
it against the stored frame on velocity and target, and writes
data/_gate_v2/sidecar_{y}.pkl with one row per frame row:
  balls, strikes   from the Statcast cache row the gate's own join maps to
                   (2021-2024 in order, 2025 fingerprint), 2026 from Count
  cls              'ball' | 'cs' | 'whiff' | 'foul' | 'bip' | 'hbp' | 'other'
  swing            1 for whiff / foul / bip, 0 for ball / cs / hbp, NaN other
Bunts are 'other' (the SD+ model rule: bunts are not swings there).

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/stuff/stuff_gate_v2_sidecar.py
"""
import gc
import os
import pickle
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stuff_gate_v2 as G  # noqa: E402

T = G.T
CLS = {
    'ball': 'ball', 'blocked_ball': 'ball', 'Ball': 'ball', 'automatic_ball': 'ball',
    'called_strike': 'cs', 'Called Strike': 'cs', 'automatic_strike': 'cs',
    'swinging_strike': 'whiff', 'swinging_strike_blocked': 'whiff', 'foul_tip': 'whiff',
    'Swinging Strike': 'whiff',
    'foul': 'foul', 'Foul': 'foul',
    'In Play': 'bip', 'hit_into_play': 'bip',
    'hit_by_pitch': 'hbp', 'Hit By Pitch': 'hbp',
}
SWING = {'whiff': 1.0, 'foul': 1.0, 'bip': 1.0, 'ball': 0.0, 'cs': 0.0, 'hbp': 0.0}


def out_path(y):
    return os.path.join(G.CACHE, f'sidecar_{y}.pkl')


def build(y):
    if y == 2026:
        pk = G.load_2026()
        guts = (T.LG_WOBA, T.WOBA_SCALE)
        bs = {}
        for p in pk:
            c = str(p.get('Count') or '')
            if len(c) == 3 and c[1] == '-' and c[0].isdigit() and c[2].isdigit():
                bs[p.get('PitchID')] = (float(c[0]), float(c[2]))
        desc = {p.get('PitchID'): p.get('Description') for p in pk}
    else:
        path = T.HIST_PKL.format(year=y) if y != 2025 else T.PRIOR_PKL
        pk = pickle.load(open(path, 'rb'))
        guts = G.GUTS[y]
        df = pickle.load(open(G.cache_path(y), 'rb'))
        rows = G._rows_fingerprint(pk, df) if y == 2025 else G._rows_ordered(pk, df, y)
        balls, strikes = G._col(df, 'balls'), G._col(df, 'strikes')
        pos = {lab: i for i, lab in enumerate(df.index)}
        bs, desc = {}, {}
        for i, (p, j) in enumerate(zip(pk, rows)):
            pid = f'{y}_{i}'
            p['PitchID'] = pid
            desc[pid] = p.get('Description')
            if j is not None:
                k = pos[j]
                if np.isfinite(balls[k]) and np.isfinite(strikes[k]):
                    bs[pid] = (float(balls[k]), float(strikes[k]))
        del df
        gc.collect()
    saved, lg, sc = T.NVAA_SLOPES, T.LG_WOBA, T.WOBA_SCALE
    T.NVAA_SLOPES = {}
    T.LG_WOBA, T.WOBA_SCALE = guts
    try:
        d = T.build_df(pk)
    finally:
        T.LG_WOBA, T.WOBA_SCALE = lg, sc
        T.NVAA_SLOPES = saved
    d = d[d['target_xrv'].notna()].reset_index(drop=True)
    fr = pd.read_pickle(G.season_path(y))
    if len(fr) != len(d):
        sys.exit(f'{y}: rebuilt {len(d)} rows, stored frame has {len(fr)}. Not written.')
    v0 = pd.to_numeric(d['velocity'], errors='coerce').values.astype('float32')
    t0 = pd.to_numeric(d['target_xrv'], errors='coerce').values
    same_v = np.allclose(v0, fr['velocity'].values.astype('float32'), equal_nan=True)
    same_p = bool((d['pitcher'].values == fr['pitcher'].values).all())
    same_t = np.allclose(t0, fr['target_xrv'].values, equal_nan=True)
    if not same_v:
        # 2026 only: the sheet values move after a frame is built (precision sweeps,
        # backfills). Accept the alignment when the pitcher sequence is identical on every
        # row and under 0.5% of velocities moved; otherwise stop. (2026-11-18: 717 of
        # 711,106 moved, max 5.5 mph, single-row corrections; a row shift would move
        # nearly all of them.)
        dv = np.abs(v0 - fr['velocity'].values.astype('float32'))
        nbad, mx = int(np.nansum(dv > 1e-4)), float(np.nanmax(dv))
        print(f'{y}: velocity differs on {nbad} of {len(d)} rows (max {mx:.2f} mph)', flush=True)
        # Measured 2026-11-24 against the frames of 2026-11-21: almost every row differs, by
        # 0.01 mph at most in 2021 and under 0.005 mph in 2022-2025. The cause is not
        # established (stored precision, or a neutral-value rebuild). A row shift moves
        # velocities by several mph, so a largest difference under 0.05 mph with the pitcher
        # sequence identical on every row is still an aligned frame.
        same_v = (y == 2026 and nbad < 0.005 * len(d)) or mx < 0.05
    if not (same_v and same_p):
        sys.exit(f'{y}: rebuilt rows do not match the stored frame on pitcher/velocity '
                 f'(velocity {same_v}, pitcher {same_p}). Not written.')
    if not same_t:
        # Row order holds (pitcher and velocity match on every row). The target can move
        # when the live Guts or a backfilled xwOBA changed after the frame was built; the
        # sidecar carries no target, so only the alignment matters. Said out loud.
        dt = np.abs(t0 - fr['target_xrv'].values)
        print(f'{y}: target differs from the stored frame on {int((dt > 1e-9).sum())} rows '
              f'(max {np.nanmax(dt):.5f}, r {np.corrcoef(t0, fr["target_xrv"].values)[0, 1]:.6f}); '
              f'rows align on pitcher and velocity, sidecar written', flush=True)
    cls = d['pid'].map(desc).map(CLS).fillna('other')
    out = pd.DataFrame({
        'balls': [bs.get(p, (np.nan, np.nan))[0] for p in d['pid']],
        'strikes': [bs.get(p, (np.nan, np.nan))[1] for p in d['pid']],
        'cls': cls.values,
    })
    out['swing'] = out['cls'].map(SWING)
    tmp = out_path(y) + '.tmp'
    out.to_pickle(tmp)
    os.replace(tmp, out_path(y))
    print(f'{y}: {len(out)} rows, count on {out["balls"].notna().mean():.1%}, '
          f'classes {out["cls"].value_counts().to_dict()}', flush=True)
    del pk, d, fr, out
    gc.collect()


if __name__ == '__main__':
    for y in G.SEASONS:
        if os.path.exists(out_path(y)):
            print(f'{y}: cached')
            continue
        build(y)
