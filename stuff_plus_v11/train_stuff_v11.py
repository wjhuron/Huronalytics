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
scores every MLB pitch OUT-OF-FOLD (pitcher-grouped, so no pitcher's own
outcomes train the model that scores him), standardizes to 100 +/- 10 PER
PITCH TYPE, aggregates to (pitcher, team, pitch_type), and (optionally, with
--inject) writes stuffScore + stuffScore_pctl into the pitch leaderboard.

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
sys.path.insert(0, ROOT)
try:
    from pipeline_utils import AAA_TEAMS
except Exception:
    AAA_TEAMS = {'ROC'}

SUPPORTED = {'FF', 'SI', 'SL', 'CH', 'ST', 'FC', 'CU', 'FS', 'SV', 'KC'}
FB_TYPES = {'FF', 'SI', 'FC'}
# 2026-07-02 config (validated: scripts/phase2b_stuff_experiments.py):
# - rel_x (hand-normalized release side) added ALONE — earlier labs only
#   tested it bundled with HAA; solo it wins (rel +0.004, pred +0.007) and
#   every public reference model carries it
# - movement features are the DENSITY-ADJUSTED xIndVrtBrk/xHorzBrk (flat on
#   the harness, adopted for coherence: the model's ivb is now the same
#   quantity the site displays, and altitude pitchers stop eating a
#   systematic stuff penalty for their home air)
# - monotone velocity constraint (rel +0.008, pred flat): more velo, same
#   everything else, never grades worse — kills sparse-region artifacts
BASE_FEATS = ['velocity', 'ivb', 'hb', 'velo_diff', 'ivb_diff', 'hb_diff',
              'spin_rate', 'extension', 'arm_angle', 'rel_z', 'vaa', 'vaa_diff',
              'rel_x']
TUNED = dict(max_depth=4, n_estimators=800, learning_rate=0.025, min_child_weight=10,
             reg_lambda=1.5, subsample=0.8, colsample_bytree=0.8, n_jobs=-1, tree_method='hist')
MONO_FEAT = 'velocity'


def _params_for(X):
    """TUNED + the monotone velocity constraint mapped to X's columns."""
    p = dict(TUNED)
    p['monotone_constraints'] = tuple(-1 if c == MONO_FEAT else 0 for c in X.columns)
    return p
# Pitcher-level standardization: 10 points per between-pitcher SD, mean shrunk
# toward the qualified-pool mean by K_SHRINK pseudo-pitches, qualify at QUAL_N.
K_SCALE, K_SHRINK, QUAL_N = 10, 100, 50

def sf(x):
    try: return float(x)
    except (TypeError, ValueError): return None

def build_df(pitches):
    # pass 1: per-pitcher primary fastball reference (handedness-normalized).
    # VAA gets its own count: a pitch missing VAA must not dilute the mean
    # toward 0 by incrementing the shared n while contributing 0.0.
    fb = defaultdict(lambda: defaultdict(lambda: {'v': 0.0, 'iv': 0.0, 'hb': 0.0, 'vaa': 0.0, 'n': 0, 'n_vaa': 0}))
    for p in pitches:
        pt, thr = p.get('Pitch Type'), p.get('Throws')
        if pt not in FB_TYPES or thr not in ('L', 'R'): continue
        v, iv, hb, vaa = sf(p.get('Velocity')), sf(p.get('IndVertBrk')), sf(p.get('HorzBrk')), sf(p.get('VAA'))
        if None in (v, iv, hb): continue
        s = 1.0 if thr == 'R' else -1.0
        a = fb[(p.get('Pitcher'), thr)][pt]
        a['v'] += v; a['iv'] += iv; a['hb'] += hb * s; a['n'] += 1
        if vaa is not None:
            a['vaa'] += vaa; a['n_vaa'] += 1
    primary = {}
    for k, bt in fb.items():
        b = max(bt.values(), key=lambda d: d['n']); n = b['n']
        primary[k] = {'v': b['v']/n, 'iv': b['iv']/n, 'hb': b['hb']/n,
                      'vaa': (b['vaa']/b['n_vaa']) if b['n_vaa'] else None}

    # Per-pitcher arm-angle averages, used as a real-time placeholder when arm
    # angle hasn't backfilled yet (it lags games ~1-2 days). Arm angle is nearly
    # constant per pitcher, so his own per-pitch-type average (or overall average
    # for a brand-new pitch) is essentially the real value; the actual number
    # replaces it on the next run after backfill. ROC has no arm history so this
    # fills nothing there (ROC uses the no-arm companion model instead).
    arm_pt = defaultdict(lambda: [0.0, 0]); arm_all = defaultdict(lambda: [0.0, 0])
    for p in pitches:
        aa = sf(p.get('ArmAngle'))
        if aa is None: continue
        pit = p.get('Pitcher'); pt0 = p.get('Pitch Type')
        arm_pt[(pit, pt0)][0] += aa; arm_pt[(pit, pt0)][1] += 1
        arm_all[pit][0] += aa; arm_all[pit][1] += 1
    def _arm_placeholder(pit, pt0):
        a = arm_pt.get((pit, pt0))
        if a and a[1]: return a[0] / a[1]
        a = arm_all.get(pit)
        return a[0] / a[1] if (a and a[1]) else None

    rows = []
    for p in pitches:
        pt, thr, bats = p.get('Pitch Type'), p.get('Throws'), p.get('Bats')
        if pt not in SUPPORTED or thr not in ('L', 'R') or bats not in ('L', 'R'): continue
        v, spin = sf(p.get('Velocity')), sf(p.get('Spin Rate'))
        # density-adjusted movement (pipeline_fetch backfills these from raw
        # when the adjustment hasn't landed, so coverage matches raw)
        iv, hb_raw = sf(p.get('xIndVrtBrk')), sf(p.get('xHorzBrk'))
        vaa, ext = sf(p.get('VAA')), sf(p.get('Extension'))
        arm, rel_z = sf(p.get('ArmAngle')), sf(p.get('RelPosZ'))
        rel_x_raw = sf(p.get('RelPosX'))
        if arm is None:                       # real-time placeholder until backfill
            arm = _arm_placeholder(p.get('Pitcher'), pt)
        if None in (v, iv, hb_raw, vaa, ext, rel_z, rel_x_raw): continue
        s = 1.0 if thr == 'R' else -1.0
        hb = hb_raw * s
        rel_x = rel_x_raw * s
        fbref = primary.get((p.get('Pitcher'), thr))
        if fbref:
            velo_diff = v - fbref['v']; ivb_diff = iv - fbref['iv']
            hb_diff = hb - fbref['hb']
            vaa_diff = (vaa - fbref['vaa']) if fbref['vaa'] is not None else None
        else:
            velo_diff = ivb_diff = hb_diff = vaa_diff = None
        desc = p.get('Description', '')
        is_bip = desc == 'In Play'
        xw, re = sf(p.get('xwOBA')), sf(p.get('RunExp'))
        # NOTE: the BIP branch is deliberately NOT count-anchored (unlike the
        # displayed xRV and the SD+/CT+ cell tables). Tested 2026-07-03:
        # anchoring the target dropped reliability 0.876->0.863 and pred
        # 0.213->0.175 — same failure mode as Loc+ (the count-state term
        # correlates with pitch usage/count-mix, which is contamination for
        # a skill-isolation model). Scope rule: anchor value-accounting and
        # decision metrics; never skill-isolation models.
        if is_bip and xw is not None:
            target = (xw - LG_WOBA) / WOBA_SCALE
        elif re is not None:
            target = -re
        else:
            target = None
        rows.append({
            'pitcher': p.get('Pitcher'), 'team': p.get('PTeam'), 'throws': thr,
            'date': p.get('Game Date'),
            'pitch_type': pt, 'platoon_same': 1 if bats == thr else 0,
            'velocity': v, 'ivb': iv, 'hb': hb, 'velo_diff': velo_diff,
            'ivb_diff': ivb_diff, 'hb_diff': hb_diff, 'spin_rate': spin,
            'extension': ext, 'arm_angle': arm, 'rel_z': rel_z, 'rel_x': rel_x,
            'vaa': vaa, 'vaa_diff': vaa_diff, 'target_xrv': target,
        })
    return pd.DataFrame(rows)

def design(df, feats=BASE_FEATS):
    dum = pd.get_dummies(df['pitch_type'], prefix='pt')
    return pd.concat([df[feats].reset_index(drop=True), dum.reset_index(drop=True),
                      df[['platoon_same']].reset_index(drop=True)], axis=1)

# ROC/AAA has no arm angle (0% populated), so ROC pitchers are scored with a
# companion model trained on the same MLB data minus arm_angle, then anchored to
# the MLB (no-arm) distribution. This applies ONLY to ROC; MLB keeps the full model.
NOARM_FEATS = [f for f in BASE_FEATS if f != 'arm_angle']

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--inject', action='store_true', help='write stuffScore into the pitch leaderboard')
    args = ap.parse_args()

    print('loading pitches ...', flush=True)
    D = pickle.load(open(PKL, 'rb'))
    pitches = [p for p in D if p.get('_source') == 'MLB']
    roc_pitches = [p for p in D if p.get('_source') in ('ROC', 'AAA')]
    df = build_df(pitches)
    df = df[df['target_xrv'].notna()].reset_index(drop=True)
    print(f'  {len(df)} training pitches, {df.pitcher.nunique()} pitchers')

    X = design(df); y = df['target_xrv'].values

    # Production MLB scores are OUT-OF-FOLD (pitcher-grouped): a pitcher's own
    # 2026 outcomes never train the model that scores his pitches. In-sample
    # scoring inflated descriptive r from 0.22 to 0.42 by absorbing pitcher
    # luck through his unique feature cluster (median 2.7, p90 8 Stuff+ pts on
    # qualified units) — the shipped number must come from the validated path.
    groups = df['pitcher'].values
    def _oof_predict(Xd, n_splits=8):
        oof = np.full(len(y), np.nan)
        pp = _params_for(Xd)
        for tr, te in GroupKFold(n_splits=n_splits).split(Xd, y, groups):
            mm = xgb.XGBRegressor(**pp); mm.fit(Xd.iloc[tr], y[tr]); oof[te] = mm.predict(Xd.iloc[te])
        return -oof
    df['stuff_raw'] = _oof_predict(X)

    # full-data model: kept in the bundle for scoring pitches outside the
    # training set (ROC uses the no-arm companion; any future out-of-sample
    # scoring uses this). It no longer scores MLB leaderboard rows.
    model = xgb.XGBRegressor(**_params_for(X)); model.fit(X, y)

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

    # ── ROC/AAA: no-arm companion model, scored against the MLB baseline. This
    #    ONLY affects ROC; MLB above is untouched (keeps real arm angle). ──
    Xna = design(df, NOARM_FEATS)
    model_na = xgb.XGBRegressor(**_params_for(Xna)); model_na.fit(Xna, y)
    # MLB anchor distribution for ROC is also OOF, so the mu/sd the ROC scores
    # are ranked against carry no in-sample luck inflation. ROC pitches are not
    # in the training set, so model_na's predictions on ROC are truly OOS.
    df['raw_na'] = _oof_predict(Xna)

    def _na_scale(keys, qual_min):
        a = df.groupby(keys)['raw_na'].agg(rawmean='mean', n='size').reset_index()
        out = {}
        groups = a.groupby('pitch_type') if 'pitch_type' in keys else [('ALL', a)]
        for key, sub in groups:
            q = sub[sub['n'] >= qual_min]; base = q if len(q) >= 5 else sub
            out[key] = {'mu': float(base['rawmean'].mean()), 'sd': float(base['rawmean'].std())}
        return out
    na_pt = _na_scale(['pitcher', 'team', 'pitch_type'], QUAL_N)
    na_ov = _na_scale(['pitcher', 'team', 'throws'], 2 * QUAL_N)['ALL']

    roc_df = build_df(roc_pitches)   # target_xrv is None at ROC — we only score
    if len(roc_df):
        Xroc = design(roc_df, NOARM_FEATS).reindex(columns=Xna.columns, fill_value=0)
        roc_df['raw_na'] = -model_na.predict(Xroc)

        def _score_roc(keys, scale, per_type):
            a = roc_df.groupby(keys)['raw_na'].agg(rawmean='mean', n='size').reset_index()
            a['stuff_mean'] = 100.0
            groups = a.groupby('pitch_type') if per_type else [('ALL', a)]
            for key, sub in groups:
                sc = scale.get(key) if per_type else scale
                if not sc or not np.isfinite(sc.get('sd', np.nan)) or sc['sd'] <= 0:
                    continue
                mu, sd = sc['mu'], sc['sd']
                adj = (sub['n'] * sub['rawmean'] + K_SHRINK * mu) / (sub['n'] + K_SHRINK)
                a.loc[sub.index, 'stuff_mean'] = (100 + K_SCALE * (adj - mu) / sd).clip(40, 180)
            a['stuff_mean'] = a['stuff_mean'].round(1)
            return a
        roc_agg = _score_roc(['pitcher', 'team', 'pitch_type'], na_pt, True)
        roc_overall = _score_roc(['pitcher', 'team', 'throws'], na_ov, False)
        agg = pd.concat([agg, roc_agg], ignore_index=True)
        overall = pd.concat([overall, roc_overall], ignore_index=True)
        print(f'  ROC (no-arm, vs MLB baseline): {len(roc_agg)} pitch-type rows, '
              f'{len(roc_overall)} pitchers')

    # save bundle
    with open(os.path.join(HERE, 'stuff_models_v11.pkl'), 'wb') as f:
        pickle.dump({'model': model, 'features': list(X.columns), 'base_feats': BASE_FEATS,
                     'league': league, 'params': TUNED, 'version': 'v11',
                     'model_na': model_na, 'noarm_feats': NOARM_FEATS,
                     'na_pt_scale': na_pt, 'na_ov_scale': na_ov}, f)

    # report + metric history (drift visibility: every retrain appends its
    # OOF descriptive r and split-half reliability to data/, which CI
    # commits — see "They Don't Make Pitch Models Like They Used To" for
    # why watching these decay matters)
    from numpy import corrcoef
    g = df.groupby(['pitcher', 'pitch_type'])
    recs = []
    for key, grp in g:
        if len(grp) >= 50:
            recs.append((grp['stuff_raw'].mean(), grp['target_xrv'].mean()))
    xs = np.array([r[0] for r in recs]); ys = np.array([r[1] for r in recs])
    oof_desc_r = float(corrcoef(xs, ys)[0, 1])
    print(f'  OOF stuff vs same-period xRV (descriptive): r = {oof_desc_r:+.3f}')

    # split-half reliability of OOF stuff (odd/even calendar dates)
    date_order = {d: i for i, d in enumerate(sorted(df['date'].dropna().unique()))}
    df['_half'] = df['date'].map(date_order).fillna(0).astype(int) % 2
    a0, a1 = [], []
    for key, grp in df.groupby(['pitcher', 'throws', 'pitch_type']):
        h0, h1 = grp[grp._half == 0], grp[grp._half == 1]
        if len(h0) >= 40 and len(h1) >= 40:
            a0.append(h0['stuff_raw'].mean()); a1.append(h1['stuff_raw'].mean())
    rel = float(corrcoef(np.array(a0), np.array(a1))[0, 1]) if len(a0) >= 5 else float('nan')
    print(f'  OOF split-half reliability (>=40/half): r = {rel:+.3f} (n={len(a0)})')

    hist = os.path.join(DATA, 'stuff_metrics_history.csv')
    latest_date = max((d for d in df['date'].dropna()), default='')
    new_file = not os.path.exists(hist)
    with open(hist, 'a') as f:
        if new_file:
            f.write('through_date,n_pitches,n_pitchers,oof_descriptive_r,oof_splithalf_r,n_rel_units\n')
        f.write(f'{latest_date},{len(df)},{df.pitcher.nunique()},'
                f'{oof_desc_r:.4f},{rel:.4f},{len(a0)}\n')
    print('\n  top arsenals by mean Stuff+ (n>=200):')
    top = agg[agg.n >= 200].sort_values('stuff_mean', ascending=False).head(10)
    for _, r in top.iterrows():
        print(f"    {r.pitcher:24s} {r.pitch_type:3s} {r.stuff_mean:5.1f}  (n={r.n})")
    print(f'\n  saved bundle + pitcher_stuff_v11.csv to {HERE}')

    if args.inject:
        inject(agg, overall, league)
    else:
        print('  (skipped leaderboard injection; run with --inject to surface)')

def _is_combined_team(t):
    return isinstance(t, str) and t.endswith('TM') and t[:-2].isdigit()


def _combo_score(parts, mu, sd):
    """Exact combined-arsenal Stuff+ for a 2TM/3TM row: pool the pitcher's MLB
    stint RAW predictions (n-weighted mean), then re-standardize at the COMBINED n
    against the league mu/sd — re-shrinking with the full-season sample rather than
    averaging the already-shrunk stint scores (which over-shrinks). Replicates
    _standardize's math exactly. `parts` is a list of (rawmean, n) per stint."""
    if not parts or mu is None or sd is None or sd <= 0:
        return None
    tot_n = sum(n for _rm, n in parts)
    if tot_n <= 0:
        return None
    combined_rawmean = sum(rm * n for rm, n in parts) / tot_n
    adj = (tot_n * combined_rawmean + K_SHRINK * mu) / (tot_n + K_SHRINK)
    return round(min(180.0, max(40.0, 100 + K_SCALE * (adj - mu) / sd)), 1)


def _pctl(sc, pool):
    below = sum(1 for x in pool if x < sc); equal = sum(1 for x in pool if x == sc)
    return round((below + 0.5 * equal) / len(pool) * 100)

def inject(agg, overall, league):
    """Write stuffScore into BOTH leaderboards.

    Percentile convention (site standard, aligned 2026-07-02): the pool that
    DEFINES the distribution is MLB rows with >=25 pitches (per pitch type at
    pitch level; overall at pitcher level), excluding combined 2TM/3TM rows
    (their stints already represent them). EVERY row with a score gets a
    rank stored — including ROC and low-sample rows — and qualification is a
    render-only coloring gate applied by leaderboard.js. Previously the rank
    existed only where locPlus_pctl existed, which silently coupled Stuff+
    coloring to Loc+ qualification settings."""
    # ── per-pitch-type -> pitch_leaderboard ──
    pl_path = os.path.join(DATA, 'pitch_leaderboard_rs.json')
    pl = json.load(open(pl_path))
    look = {(r.pitcher, r.team, r.pitch_type): r.stuff_mean for r in agg.itertuples()}
    # Pool a pitcher's MLB per-team RAW predictions to score the combined 2TM/3TM row.
    pool_pt = defaultdict(list)
    for r in agg.itertuples():
        if r.team not in AAA_TEAMS and not _is_combined_team(r.team):
            pool_pt[(r.pitcher, r.pitch_type)].append((r.rawmean, r.n))
    for row in pl:
        key = (row['pitcher'], row['team'], row['pitchType'])
        if key in look:
            row['stuffScore'] = look[key]
        elif _is_combined_team(row['team']):
            sc = league.get(row['pitchType'])
            row['stuffScore'] = _combo_score(
                pool_pt.get((row['pitcher'], row['pitchType'])),
                sc['mu'] if sc else None, sc['sd'] if sc else None)
        else:
            row['stuffScore'] = None
    # Pool: MLB rows with >=25 pitches of the type; combined 2TM/3TM rows
    # excluded from the POOL (their stints already represent them). Every
    # scored row gets a rank; coloring is gated at render time.
    qual_by_pt = defaultdict(list)
    for row in pl:
        if (row.get('stuffScore') is not None and (row.get('count') or 0) >= 25
                and row.get('team') not in AAA_TEAMS and not _is_combined_team(row['team'])):
            qual_by_pt[row['pitchType']].append(row['stuffScore'])
    n_pl = 0
    for row in pl:
        sc = row.get('stuffScore'); pt = row['pitchType']
        if sc is not None: n_pl += 1
        if sc is not None and qual_by_pt.get(pt):
            row['stuffScore_pctl'] = _pctl(sc, qual_by_pt[pt])
        else:
            row['stuffScore_pctl'] = None
    json.dump(pl, open(pl_path, 'w'))

    # ── overall -> pitcher_leaderboard ──
    pp_path = os.path.join(DATA, 'pitcher_leaderboard_rs.json')
    pp = json.load(open(pp_path))
    olook = {(r.pitcher, r.team, r.throws): r.stuff_mean for r in overall.itertuples()}
    pool_ov = defaultdict(list)
    for r in overall.itertuples():
        if r.team not in AAA_TEAMS and not _is_combined_team(r.team):
            pool_ov[(r.pitcher, r.throws)].append((r.rawmean, r.n))
    ov_scale = league.get('_overall')
    for row in pp:
        key = (row['pitcher'], row['team'], row.get('throws'))
        if key in olook:
            row['stuffScore'] = olook[key]
        elif _is_combined_team(row['team']):
            row['stuffScore'] = _combo_score(
                pool_ov.get((row['pitcher'], row.get('throws'))),
                ov_scale['mu'] if ov_scale else None, ov_scale['sd'] if ov_scale else None)
        else:
            row['stuffScore'] = None
    qpool = [row['stuffScore'] for row in pp
             if row.get('stuffScore') is not None and (row.get('count') or 0) >= 25
             and row.get('team') not in AAA_TEAMS and not _is_combined_team(row['team'])]
    n_pp = 0
    for row in pp:
        sc = row.get('stuffScore')
        if sc is not None: n_pp += 1
        if sc is not None and qpool:
            row['stuffScore_pctl'] = _pctl(sc, qpool)
        else:
            row['stuffScore_pctl'] = None
    json.dump(pp, open(pp_path, 'w'))
    print(f'  injected stuffScore: pitch-level {n_pl}/{len(pl)} rows, '
          f'pitcher-level {n_pp}/{len(pp)} rows (qualified pool = {len(qpool)})')

if __name__ == '__main__':
    main()
