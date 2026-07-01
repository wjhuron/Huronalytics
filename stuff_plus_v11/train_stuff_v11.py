"""train_stuff_v11.py — Stuff+ v11 trainer.

A from-scratch rebuild validated against v10 (scripts/stuff_lab*.py). Key
changes that won the experiments:
  - ONE pooled model across pitch types (not 9 per-type models)
  - ONE learned luck-neutral xRV target (not hand-weighted whiff/GB/contact)
  - lean feature set (no SSW residuals, no location, no overfit-prone extras)

Out-of-fold it predicts future luck-neutral run prevention at ~0.23, above the
persistence ceiling (~0.195) and far above v10's architecture (~0.02-0.06 in the
same harness). Reliability ~0.87.

Offline trainer (xgboost is fine here): trains on the cleaned pitch pickle,
scores every pitch, standardizes to 100 +/- 10 PER PITCH TYPE, aggregates to
(pitcher, team, pitch_type), and (optionally, with --inject) writes stuffScore +
stuffScore_pctl into the pitch leaderboard, exactly like v10. Stuff+ remains
force-hidden on the site until explicitly surfaced.

Usage:
    python3 stuff_plus_v11/train_stuff_v11.py            # train + save bundle/CSV
    python3 stuff_plus_v11/train_stuff_v11.py --inject    # also write into leaderboard
"""
import os, sys, math, json, pickle, argparse, warnings
from collections import defaultdict
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import GroupKFold
warnings.filterwarnings('ignore')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
HERE = os.path.dirname(os.path.abspath(__file__))
PKL = os.path.join(DATA, 'all_pitches_rs_cache.pkl')
LG_WOBA, WOBA_SCALE = 0.3169, 1.2393

SUPPORTED = {'FF', 'SI', 'SL', 'CH', 'ST', 'FC', 'CU', 'FS', 'SV', 'KC'}
FB_TYPES = {'FF', 'SI', 'FC'}
BASE_FEATS = ['velocity', 'ivb', 'hb', 'velo_diff', 'ivb_diff', 'hb_diff',
              'spin_rate', 'extension', 'arm_angle', 'rel_z', 'vaa', 'vaa_diff']
TUNED = dict(max_depth=4, n_estimators=800, learning_rate=0.025, min_child_weight=10,
             reg_lambda=1.5, subsample=0.8, colsample_bytree=0.8, n_jobs=-1, tree_method='hist')
# Pitcher-level standardization: 10 points per between-pitcher SD, mean shrunk
# toward the qualified-pool mean by K_SHRINK pseudo-pitches, qualify at QUAL_N.
K_SCALE, K_SHRINK, QUAL_N = 10, 100, 50

def sf(x):
    try: return float(x)
    except (TypeError, ValueError): return None

def build_df(pitches):
    # pass 1: per-pitcher primary fastball reference (handedness-normalized)
    fb = defaultdict(lambda: defaultdict(lambda: {'v': 0.0, 'iv': 0.0, 'hb': 0.0, 'vaa': 0.0, 'n': 0}))
    for p in pitches:
        pt, thr = p.get('Pitch Type'), p.get('Throws')
        if pt not in FB_TYPES or thr not in ('L', 'R'): continue
        v, iv, hb, vaa = sf(p.get('Velocity')), sf(p.get('IndVertBrk')), sf(p.get('HorzBrk')), sf(p.get('VAA'))
        if None in (v, iv, hb): continue
        s = 1.0 if thr == 'R' else -1.0
        a = fb[(p.get('Pitcher'), thr)][pt]
        a['v'] += v; a['iv'] += iv; a['hb'] += hb * s; a['vaa'] += (vaa or 0.0); a['n'] += 1
    primary = {}
    for k, bt in fb.items():
        b = max(bt.values(), key=lambda d: d['n']); n = b['n']
        primary[k] = {'v': b['v']/n, 'iv': b['iv']/n, 'hb': b['hb']/n, 'vaa': b['vaa']/n}

    rows = []
    for p in pitches:
        pt, thr, bats = p.get('Pitch Type'), p.get('Throws'), p.get('Bats')
        if pt not in SUPPORTED or thr not in ('L', 'R') or bats not in ('L', 'R'): continue
        v, spin = sf(p.get('Velocity')), sf(p.get('Spin Rate'))
        iv, hb_raw = sf(p.get('IndVertBrk')), sf(p.get('HorzBrk'))
        vaa, ext = sf(p.get('VAA')), sf(p.get('Extension'))
        arm, rel_z = sf(p.get('ArmAngle')), sf(p.get('RelPosZ'))
        if None in (v, iv, hb_raw, vaa, ext, rel_z): continue
        s = 1.0 if thr == 'R' else -1.0
        hb = hb_raw * s
        fbref = primary.get((p.get('Pitcher'), thr))
        if fbref:
            velo_diff = v - fbref['v']; ivb_diff = iv - fbref['iv']
            hb_diff = hb - fbref['hb']; vaa_diff = vaa - fbref['vaa']
        else:
            velo_diff = ivb_diff = hb_diff = vaa_diff = None
        desc = p.get('Description', '')
        is_bip = desc == 'In Play'
        xw, re = sf(p.get('xwOBA')), sf(p.get('RunExp'))
        if is_bip and xw is not None:
            target = (xw - LG_WOBA) / WOBA_SCALE
        elif re is not None:
            target = -re
        else:
            target = None
        rows.append({
            'pitcher': p.get('Pitcher'), 'team': p.get('PTeam'), 'throws': thr,
            'pitch_type': pt, 'platoon_same': 1 if bats == thr else 0,
            'velocity': v, 'ivb': iv, 'hb': hb, 'velo_diff': velo_diff,
            'ivb_diff': ivb_diff, 'hb_diff': hb_diff, 'spin_rate': spin,
            'extension': ext, 'arm_angle': arm, 'rel_z': rel_z, 'vaa': vaa,
            'vaa_diff': vaa_diff, 'target_xrv': target,
        })
    return pd.DataFrame(rows)

def design(df):
    dum = pd.get_dummies(df['pitch_type'], prefix='pt')
    return pd.concat([df[BASE_FEATS].reset_index(drop=True), dum.reset_index(drop=True),
                      df[['platoon_same']].reset_index(drop=True)], axis=1)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--inject', action='store_true', help='write stuffScore into the pitch leaderboard')
    args = ap.parse_args()

    print('loading pitches ...', flush=True)
    D = pickle.load(open(PKL, 'rb'))
    pitches = [p for p in D if p.get('_source') == 'MLB']
    df = build_df(pitches)
    df = df[df['target_xrv'].notna()].reset_index(drop=True)
    print(f'  {len(df)} training pitches, {df.pitcher.nunique()} pitchers')

    X = design(df); y = df['target_xrv'].values

    # OOF sanity check (pitcher-grouped) — confirms it reproduces the harness
    oof = np.full(len(df), np.nan); groups = df['pitcher'].values
    for tr, te in GroupKFold(n_splits=4).split(X, y, groups):
        mm = xgb.XGBRegressor(**TUNED); mm.fit(X.iloc[tr], y[tr]); oof[te] = mm.predict(X.iloc[te])
    df['_oof_stuff'] = -oof

    # production model: train on all data, score all pitches
    model = xgb.XGBRegressor(**TUNED); model.fit(X, y)
    df['stuff_raw'] = -model.predict(X)

    # Standardize at the PITCHER level (proper "+"-stat spread: SD=10 between
    # pitchers, not between pitches — averaging pitch-level z-scores collapses
    # the spread). The scale (mu, sd) is fixed from the qualified pool (>=QUAL_N
    # of that pitch type); each pitcher's mean is then shrunk toward the pool
    # mean by K_SHRINK pseudo-pitches so small samples fall toward 100 instead
    # of showing noise flukes. High-sample arms are essentially unaffected.
    def _standardize(grp_keys, qual_min):
        a = df.groupby(grp_keys)['stuff_raw'].agg(rawmean='mean', n='size').reset_index()
        a['stuff_mean'] = 100.0
        scale = {}
        groups = a.groupby('pitch_type') if 'pitch_type' in grp_keys else [('ALL', a)]
        for key, sub in groups:
            q = sub[sub['n'] >= qual_min]
            base = q if len(q) >= 5 else sub
            mu, sd = float(base['rawmean'].mean()), float(base['rawmean'].std())
            scale[key] = {'mu': mu, 'sd': sd, 'nqual': int(len(q))}
            if sd > 0:
                adj = (sub['n'] * sub['rawmean'] + K_SHRINK * mu) / (sub['n'] + K_SHRINK)
                a.loc[sub.index, 'stuff_mean'] = (100 + K_SCALE * (adj - mu) / sd).clip(40, 180)
        a['stuff_mean'] = a['stuff_mean'].round(1)
        return a, scale

    agg, league = _standardize(['pitcher', 'team', 'pitch_type'], QUAL_N)
    agg.to_csv(os.path.join(HERE, 'pitcher_stuff_v11.csv'), index=False)
    overall, overall_scale = _standardize(['pitcher', 'team', 'throws'], 2 * QUAL_N)
    league['_overall'] = overall_scale['ALL']

    # save bundle
    with open(os.path.join(HERE, 'stuff_models_v11.pkl'), 'wb') as f:
        pickle.dump({'model': model, 'features': list(X.columns), 'base_feats': BASE_FEATS,
                     'league': league, 'params': TUNED, 'version': 'v11'}, f)

    # report
    from numpy import corrcoef
    g = df.groupby(['pitcher', 'pitch_type'])
    recs = []
    for key, grp in g:
        if len(grp) >= 50:
            recs.append((grp['_oof_stuff'].mean(), grp['target_xrv'].mean()))
    xs = np.array([r[0] for r in recs]); ys = np.array([r[1] for r in recs])
    print(f'  OOF stuff vs same-period xRV (descriptive): r = {corrcoef(xs, ys)[0,1]:+.3f}')
    print('\n  top arsenals by mean Stuff+ (n>=200):')
    top = agg[agg.n >= 200].sort_values('stuff_mean', ascending=False).head(10)
    for _, r in top.iterrows():
        print(f"    {r.pitcher:24s} {r.pitch_type:3s} {r.stuff_mean:5.1f}  (n={r.n})")
    print(f'\n  saved bundle + pitcher_stuff_v11.csv to {HERE}')

    if args.inject:
        inject(agg, overall)
    else:
        print('  (skipped leaderboard injection; run with --inject to surface)')

def _pctl(sc, pool):
    below = sum(1 for x in pool if x < sc); equal = sum(1 for x in pool if x == sc)
    return round((below + 0.5 * equal) / len(pool) * 100)

def inject(agg, overall):
    """Write stuffScore into BOTH leaderboards. Percentiles use the same
    qualified pool as Loc+ (rows where locPlus_pctl is not None): per-pitch-type
    Stuff+ ranks within its pitch type, overall Stuff+ ranks across pitchers.
    Values are shown for all rows; color/pctl only for qualified rows."""
    # ── per-pitch-type -> pitch_leaderboard ──
    pl_path = os.path.join(DATA, 'pitch_leaderboard_rs.json')
    pl = json.load(open(pl_path))
    look = {(r.pitcher, r.team, r.pitch_type): r.stuff_mean for r in agg.itertuples()}
    for row in pl:
        row['stuffScore'] = look.get((row['pitcher'], row['team'], row['pitchType']))
    qual_by_pt = defaultdict(list)
    for row in pl:
        if row.get('stuffScore') is not None and row.get('locPlus_pctl') is not None:
            qual_by_pt[row['pitchType']].append(row['stuffScore'])
    n_pl = 0
    for row in pl:
        sc = row.get('stuffScore'); pt = row['pitchType']
        if sc is not None: n_pl += 1
        if sc is not None and row.get('locPlus_pctl') is not None and qual_by_pt.get(pt):
            row['stuffScore_pctl'] = _pctl(sc, qual_by_pt[pt])
        else:
            row['stuffScore_pctl'] = None
    json.dump(pl, open(pl_path, 'w'))

    # ── overall -> pitcher_leaderboard ──
    pp_path = os.path.join(DATA, 'pitcher_leaderboard_rs.json')
    pp = json.load(open(pp_path))
    olook = {(r.pitcher, r.team, r.throws): r.stuff_mean for r in overall.itertuples()}
    for row in pp:
        row['stuffScore'] = olook.get((row['pitcher'], row['team'], row.get('throws')))
    qpool = [row['stuffScore'] for row in pp
             if row.get('stuffScore') is not None and row.get('locPlus_pctl') is not None]
    n_pp = 0
    for row in pp:
        sc = row.get('stuffScore')
        if sc is not None: n_pp += 1
        if sc is not None and row.get('locPlus_pctl') is not None and qpool:
            row['stuffScore_pctl'] = _pctl(sc, qpool)
        else:
            row['stuffScore_pctl'] = None
    json.dump(pp, open(pp_path, 'w'))
    print(f'  injected stuffScore: pitch-level {n_pl}/{len(pl)} rows, '
          f'pitcher-level {n_pp}/{len(pp)} rows (qualified pool = {len(qpool)})')

if __name__ == '__main__':
    main()
