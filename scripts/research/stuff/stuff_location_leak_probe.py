#!/usr/bin/env python3
"""Stuff+ location-leak probe (2026-09-08).

Prompt: Tom Kim (@tomdoyo, 2026-09-08) argues a stuff model with no
location input is still partly a location model: the label carries location
value, and survival selects slower arms with better locations (Berkson), so
E[outcome | physics] includes E[location value | physics]. This measures how
much of the shipped Stuff+ is location value, on 2026.

Design (2026 MLB only, pitcher-grouped 8-fold OOF, shipped TUNED params and
BASE_FEATS, the SAME folds for every arm):
  A  y = target_xrv            the shipped label (batter-positive)
  B  y = target_xrv - l_loc    location-adjusted label, shipped constraints
  C  y = l_loc                 location value from physics, NO monotone
                               velocity constraint (the shipped -1 constraint
                               would suppress the very slope being measured)
l_loc = Loc+ per-pitch expected RV (locplus.score_pitch, the xRVOE location
term) centred within (group, bats, throws, count): count and platoon levels
stay in the label, only the location deviation leaves.

Reads:  data/all_pitches_rs_cache.pkl, data/pitch_leaderboard_rs.json,
        data/pitcher_leaderboard_rs.json, data/pitcher_heights.json
Writes: data/_stuff_locleak_oof.pkl (OOF cache), data/_stuff_locleak_2026.json

Run from the repo root:
    python3 scripts/research/stuff/stuff_location_leak_probe.py
    python3 scripts/research/stuff/stuff_location_leak_probe.py --analyze
"""
import argparse
import json
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import GroupKFold

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, ROOT)
import stuff_plus.train_stuff as T                      # noqa: E402
from pipeline import locplus as LOC                     # noqa: E402
from pipeline.utils import get_count, AAA_TEAMS         # noqa: E402

DATA = os.path.join(ROOT, 'data')
OOF_PATH = os.path.join(DATA, '_stuff_locleak_oof.pkl')
OUT_PATH = os.path.join(DATA, '_stuff_locleak_2026.json')
N_SPLITS = 8
UNIT_MIN = 100      # pitches per (pitcher, team, type) unit to report
QUAL = 50           # train_stuff QUAL_N: units that set the type scale
PIT_MIN = 300       # pitches per pitcher for the pitcher-level table
HALF_MIN = 50       # early/late unit gate (the battery convention)
MAIN_TYPES = ['FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS']


def pear(a, b):
    a = np.asarray(a, float); b = np.asarray(b, float)
    m = ~np.isnan(a) & ~np.isnan(b)
    if m.sum() < 5:
        return float('nan')
    return float(np.corrcoef(a[m], b[m])[0, 1])


def load_frame():
    print('loading pitches ...', flush=True)
    D = pickle.load(open(T.PKL, 'rb'))
    _ep = {(p.get('Pitcher'), p.get('PTeam')) for p in D if p.get('Pitch Type') == 'EP'}
    pitches = [p for p in D if p.get('_source') == 'MLB'
               and (p.get('Pitcher'), p.get('PTeam')) not in _ep]
    roc = [p for p in D if p.get('_source') in ('ROC', 'AAA')]
    df_full = T.build_df(pitches, arm_fallback=T._arm_means(roc))
    df = df_full[df_full['target_xrv'].notna()].reset_index(drop=True)
    print(f'  {len(df)} training pitches, {df.pitcher.nunique()} pitchers', flush=True)

    print('building Loc+ surfaces ...', flush=True)
    baseline = [p for p in pitches if LOC.is_eligible_baseline(p)]
    S = LOC.build_surfaces(baseline, T.LG_WOBA, T.WOBA_SCALE)
    recs = []
    for p in baseline:
        v = LOC.score_pitch(p, S)
        if v is None or not p.get('PitchID'):
            continue
        recs.append((p['PitchID'], v, LOC.group_of(p), p.get('Bats'),
                     p.get('Throws'), get_count(p)))
    L = pd.DataFrame(recs, columns=['pid', 'exprv', 'grp', 'bats', 'thr', 'count'])
    L = L.drop_duplicates('pid')
    L['cell_mean'] = L.groupby(['grp', 'bats', 'thr', 'count'])['exprv'].transform('mean')
    L['l_loc'] = L['exprv'] - L['cell_mean']
    df = df.merge(L[['pid', 'exprv', 'l_loc']], on='pid', how='left')
    n_missing = int(df['l_loc'].isna().sum())
    df = df[df['l_loc'].notna()].reset_index(drop=True)
    print(f'  location term joined: {len(df)} rows, {n_missing} training rows '
          f'without a Loc+ score dropped (bunts, excluded descriptions, no zone)',
          flush=True)
    return df, n_missing


def fit_arms(df):
    X = T.design(df)
    yA = df['target_xrv'].values.astype(float)
    yC = df['l_loc'].values.astype(float)
    yB = yA - yC
    groups = df['pitcher'].values
    pp = T._params_for(X); pp['random_state'] = 0
    pp_free = dict(T.TUNED); pp_free['random_state'] = 0
    oof = {k: np.full(len(df), np.nan) for k in 'ABC'}
    arms = (('A', yA, pp), ('B', yB, pp), ('C', yC, pp_free))
    for f, (tr, te) in enumerate(GroupKFold(n_splits=N_SPLITS).split(X, yA, groups)):
        for k, y, params in arms:
            t = time.time()
            m = xgb.XGBRegressor(**params)
            m.fit(X.iloc[tr], y[tr])
            oof[k][te] = m.predict(X.iloc[te])
            print(f'  fold {f + 1}/{N_SPLITS} arm {k}: {time.time() - t:.0f}s', flush=True)
    return oof


def _scale(u, col, qual_col='n'):
    """Per-type (mu, sd) from qualified units, train_stuff._standardize rule."""
    out = {}
    for pt, sub in u.groupby('pitch_type'):
        q = sub[sub[qual_col] >= QUAL]
        base = q if len(q) >= 5 else sub
        out[pt] = (float(base[col].mean()), float(base[col].std()))
    return out


def analyze(df, oof, n_missing):
    for k in 'ABC':
        df[f'raw{k}'] = -oof[k]            # pitcher-positive
    df['lloc_pp'] = -df['l_loc']           # pitcher-positive location value
    res = {'n_rows': int(len(df)), 'n_pitchers': int(df.pitcher.nunique()),
           'n_rows_without_loc': n_missing, 'splits': N_SPLITS}

    # ── 1. pitch level: is location value predictable from physics? ──
    res['pitch'] = {}
    allr = dict(n=int(len(df)), sd_lloc_100=float(df.l_loc.std() * 100),
                r_velo_lloc=pear(df.velocity, df.l_loc),
                r_C_lloc=pear(-df.rawC, df.l_loc),
                sd_C_100=float(df.rawC.std() * 100),
                sd_A_100=float(df.rawA.std() * 100),
                r_A_C=pear(df.rawA, df.rawC))
    res['pitch']['ALL'] = allr
    for pt in MAIN_TYPES:
        s = df[df.pitch_type == pt]
        res['pitch'][pt] = dict(
            n=int(len(s)), sd_lloc_100=float(s.l_loc.std() * 100),
            r_velo_lloc=pear(s.velocity, s.l_loc),
            r_C_lloc=pear(-s.rawC, s.l_loc),
            sd_C_100=float(s.rawC.std() * 100),
            sd_A_100=float(s.rawA.std() * 100),
            r_A_C=pear(s.rawA, s.rawC))

    # ── 2. units (pitcher, team, type) ──
    u = (df.groupby(['pitcher', 'team', 'pitch_type'])
           .agg(n=('rawA', 'size'), A=('rawA', 'mean'), B=('rawB', 'mean'),
                C=('rawC', 'mean'), lloc=('lloc_pp', 'mean'),
                velo=('velocity', 'mean'), throws=('throws', 'first'))
           .reset_index())
    u = u[u.n >= UNIT_MIN].reset_index(drop=True)
    scA = _scale(u, 'A'); scB = _scale(u, 'B')
    u['A_pts'] = [100 + 10 * (a - scA[pt][0]) / scA[pt][1] for a, pt in zip(u.A, u.pitch_type)]
    # B on A's spread so the adjustment reads in shipped Stuff+ points
    u['B_pts'] = [100 + 10 * (b - scB[pt][0]) / scA[pt][1] for b, pt in zip(u.B, u.pitch_type)]
    u['adj_pts'] = u.A_pts - u.B_pts
    u['adj_100'] = (u.A - u.B) * 100

    lb = json.load(open(os.path.join(DATA, 'pitch_leaderboard_rs.json')))
    lbm = {(r['pitcher'], r['team'], r['pitchType']): r for r in lb}
    u['lb_loc'] = [lbm.get((p, t, pt), {}).get('locPlus') for p, t, pt in zip(u.pitcher, u.team, u.pitch_type)]
    u['lb_stuff'] = [lbm.get((p, t, pt), {}).get('stuffScore') for p, t, pt in zip(u.pitcher, u.team, u.pitch_type)]
    u['lb_loc'] = pd.to_numeric(u.lb_loc, errors='coerce')
    u['lb_stuff'] = pd.to_numeric(u.lb_stuff, errors='coerce')

    res['unit'] = {}
    def _unit_block(s):
        return dict(
            n_units=int(len(s)),
            sdA_100=float(s.A.std() * 100), sdB_100=float(s.B.std() * 100),
            sdC_100=float(s.C.std() * 100), sd_adj_100=float(s.adj_100.std()),
            sd_adj_pts=float(s.adj_pts.std()),
            median_abs_adj_pts=float(s.adj_pts.abs().median()),
            p90_abs_adj_pts=float(s.adj_pts.abs().quantile(0.9)),
            n_moved_5plus=int((s.adj_pts.abs() >= 5).sum()),
            r_A_B=pear(s.A, s.B), r_adj_C=pear(s.adj_100, s.C),
            r_adj_lloc=pear(s.adj_100, s.lloc), r_adj_velo=pear(s.adj_100, s.velo),
            r_A_velo=pear(s.A, s.velo), r_B_velo=pear(s.B, s.velo),
            r_velo_lloc=pear(s.velo, s.lloc),
            r_A_lloc=pear(s.A, s.lloc), r_B_lloc=pear(s.B, s.lloc),
            r_A_lbLoc=pear(s.A, s.lb_loc), r_B_lbLoc=pear(s.B, s.lb_loc),
            r_adj_lbLoc=pear(s.adj_100, s.lb_loc),
            r_A_lbStuff=pear(s.A, s.lb_stuff), r_B_lbStuff=pear(s.B, s.lb_stuff))
    res['unit']['ALL'] = _unit_block(u[u.pitch_type.isin(MAIN_TYPES)])
    for pt in MAIN_TYPES:
        s = u[u.pitch_type == pt]
        if len(s) >= 20:
            res['unit'][pt] = _unit_block(s)
    movers = u[u.pitch_type.isin(MAIN_TYPES)].sort_values('adj_pts')
    cols = ['pitcher', 'team', 'pitch_type', 'n', 'velo', 'A_pts', 'B_pts', 'adj_pts', 'lb_stuff', 'lb_loc']
    res['unit_movers_down'] = movers.tail(12)[cols].round(1).to_dict('records')[::-1]
    res['unit_movers_up'] = movers.head(12)[cols].round(1).to_dict('records')

    # ── 3. pitcher level (per-pitch grades on the type scale, plain mean) ──
    df['gA'] = [100 + 10 * (a - scA[pt][0]) / scA[pt][1] if pt in scA else np.nan
                for a, pt in zip(df.rawA, df.pitch_type)]
    df['gB'] = [100 + 10 * (b - scB[pt][0]) / scA[pt][1] if pt in scB else np.nan
                for b, pt in zip(df.rawB, df.pitch_type)]
    P = (df.groupby(['pitcher', 'team'])
           .agg(n=('gA', 'size'), A=('gA', 'mean'), B=('gB', 'mean'),
                lloc=('lloc_pp', 'mean'), C=('rawC', 'mean'))
           .reset_index())
    P = P[P.n >= PIT_MIN].reset_index(drop=True)
    P['adj'] = P.A - P.B
    plb = json.load(open(os.path.join(DATA, 'pitcher_leaderboard_rs.json')))
    plbm = {(r['pitcher'], r['team']): r for r in plb}
    for k in ('locPlus', 'commandPlus', 'fbVelo', 'stuffScore', 'xRv100'):
        P[k] = pd.to_numeric([plbm.get((p, t), {}).get(k) for p, t in zip(P.pitcher, P.team)], errors='coerce')
    res['pitcher'] = dict(
        n=int(len(P)), sd_adj_pts=float(P.adj.std()),
        median_abs_adj=float(P.adj.abs().median()), p90_abs_adj=float(P.adj.abs().quantile(0.9)),
        n_moved_3plus=int((P.adj.abs() >= 3).sum()),
        r_A_B=pear(P.A, P.B),
        r_A_shippedStuff=pear(P.A, P.stuffScore), r_B_shippedStuff=pear(P.B, P.stuffScore),
        r_A_Loc=pear(P.A, P.locPlus), r_B_Loc=pear(P.B, P.locPlus),
        r_A_Cmd=pear(P.A, P.commandPlus), r_B_Cmd=pear(P.B, P.commandPlus),
        r_adj_Loc=pear(P.adj, P.locPlus), r_adj_Cmd=pear(P.adj, P.commandPlus),
        r_adj_fbVelo=pear(P.adj, P.fbVelo), r_adj_lloc=pear(P.adj, P.lloc),
        r_A_xRv100=pear(P.A, P.xRv100), r_B_xRv100=pear(P.B, P.xRv100),
        r_fbVelo_Loc=pear(P.fbVelo, P.locPlus), r_fbVelo_Cmd=pear(P.fbVelo, P.commandPlus))
    pm = P.sort_values('adj')
    pcols = ['pitcher', 'team', 'n', 'A', 'B', 'adj', 'stuffScore', 'locPlus', 'commandPlus', 'fbVelo']
    res['pitcher_movers_down'] = pm.tail(12)[pcols].round(1).to_dict('records')[::-1]
    res['pitcher_movers_up'] = pm.head(12)[pcols].round(1).to_dict('records')

    # ── 4. early/late within 2026 (diagnostic only; not the ship gate) ──
    med = df['date'].dropna().sort_values().iloc[len(df) // 2]
    df['period'] = np.where(df['date'] <= med, 'early', 'late')
    e = df[df.period == 'early'].groupby(['pitcher', 'team', 'pitch_type']).agg(
        n=('rawA', 'size'), A=('rawA', 'mean'), B=('rawB', 'mean'),
        tA=('target_xrv', 'mean'), tB=('rawB', 'size'))
    l = df[df.period == 'late'].groupby(['pitcher', 'team', 'pitch_type']).agg(
        n=('rawA', 'size'), A=('rawA', 'mean'), B=('rawB', 'mean'),
        t_raw=('target_xrv', 'mean'),
        t_adj=('target_xrv', lambda s: float('nan')))
    late_adj = (df[df.period == 'late'].assign(tadj=lambda d: d.target_xrv - d.l_loc)
                .groupby(['pitcher', 'team', 'pitch_type'])['tadj'].mean())
    l['t_adj'] = late_adj
    j = e.join(l, lsuffix='_e', rsuffix='_l', how='inner')
    j = j[(j.n_e >= HALF_MIN) & (j.n_l >= HALF_MIN)]
    res['early_late'] = dict(
        n_units=int(len(j)), split_date=str(med),
        rel_A=pear(j.A_e, j.A_l), rel_B=pear(j.B_e, j.B_l),
        pred_A_rawTarget=-pear(j.A_e, j.t_raw), pred_B_rawTarget=-pear(j.B_e, j.t_raw),
        pred_A_adjTarget=-pear(j.A_e, j.t_adj), pred_B_adjTarget=-pear(j.B_e, j.t_adj))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--analyze', action='store_true', help='reuse the OOF cache')
    args = ap.parse_args()
    df, n_missing = load_frame()
    if args.analyze and os.path.exists(OOF_PATH):
        c = pickle.load(open(OOF_PATH, 'rb'))
        if c['pids'] != df['pid'].tolist():
            sys.exit('OOF cache does not match the current frame; rerun without --analyze')
        oof = c['oof']
    else:
        t0 = time.time()
        oof = fit_arms(df)
        print(f'  fits done in {(time.time() - t0) / 60:.1f} min', flush=True)
        with open(OOF_PATH, 'wb') as f:
            pickle.dump({'pids': df['pid'].tolist(), 'oof': oof}, f)
    res = analyze(df, oof, n_missing)
    with open(OUT_PATH, 'w') as f:
        json.dump(res, f, indent=1, default=float)
    print(json.dumps({k: v for k, v in res.items() if k in ('pitch', 'unit', 'pitcher', 'early_late')},
                     indent=1, default=float))
    print(f'wrote {OUT_PATH}')


if __name__ == '__main__':
    main()
