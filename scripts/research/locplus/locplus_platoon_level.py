"""How much of Loc+ is the batter-hand MATCHUP rather than location?

Loc+ scores each pitch on a league surface per (pitch group, batter hand,
pitcher hand), then standardizes within the pitch GROUP only. A pitch type that
is worse against opposite-hand hitters at every location (the sinker is the
suspect) therefore loses Loc+ in proportion to how often its pitcher throws it
to opposite-hand hitters, whatever he does with it.

This script measures that, read-only, on the local pickle:

  A. Location held fixed: every pitch is re-scored with the batter hand
     flipped. The mean of v(opposite) - v(same) at the pitch's own location,
     in Loc+ points (10 / group sigma), is the pure surface penalty for
     facing an opposite-hand hitter.
  B. Matchup level: L(g, b, t) = league mean ExpRV for (group, batter hand,
     pitcher hand). A hand-neutral ExpRV v' = v - L(g, b, t) + L(g, t)
     removes the batter-hand level and keeps everything else (location, count).
     Hand-neutral Loc+ is rebuilt with the shipped machinery (group anchors
     from _normalize_by_group, plain mean of integer atoms).
  C. Per (pitcher, type) unit and per pitcher: opposite-hand share, shipped
     Loc+ (replicated), hand-neutral Loc+, the difference, and r with
     opposite-hand share for both.

Validation: the replicated per-type Loc+ is compared with the shipped
pitch_leaderboard_rs.json value before anything else is read.

Run from the repo root:
    python3 scripts/research/locplus/locplus_platoon_level.py
Writes data/_loc_platoon_level.json.
"""
import json, math, os, pickle, sys
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from pipeline import locplus as L  # noqa: E402
from pipeline.utils import AAA_TEAMS  # noqa: E402

DATA = os.path.join(ROOT, 'data')

meta = json.load(open(os.path.join(DATA, 'metadata_rs.json')))
guts = meta['gutsConstants']
ALL = pickle.load(open(os.path.join(DATA, 'all_pitches_rs_cache.pkl'), 'rb'))
ep = {(p['Pitcher'], p['PTeam']) for p in ALL if p.get('Pitch Type') == 'EP'}
ALL = [p for p in ALL if (p.get('Pitcher'), p.get('PTeam')) not in ep]
MLB = [p for p in ALL if p.get('_source') == 'MLB' and p.get('PTeam') not in AAA_TEAMS]
print(f"pitches: {len(ALL)} total, {len(MLB)} MLB scored units source")

by_pitcher, by_pt = defaultdict(list), defaultdict(list)
for p in MLB:
    by_pitcher[(p['Pitcher'], p['PTeam'], p.get('Throws'))].append(p)
    by_pt[(p['Pitcher'], p['PTeam'], p.get('Pitch Type'), p.get('Throws'))].append(p)

pr, ptr, _meta, anchors = L.compute_loc_plus(
    ALL, by_pitcher, by_pt, lg_woba=guts['lgWOBA'], woba_scale=guts['wOBAScale'],
    return_anchors=True)
S, gA = anchors['surfaces'], anchors['pt']

# ── validation against the shipped per-type rows ──────────────────────────
ship = pd.DataFrame(json.load(open(os.path.join(DATA, 'pitch_leaderboard_rs.json'))))
ship = ship[ship['locPlus'].notna()]
mine = pd.DataFrame([{'pitcher': k[0], 'team': k[1], 'pitchType': k[2], 'loc_rep': v['locPlus']}
                     for k, v in ptr.items()])
val = ship.merge(mine, on=['pitcher', 'team', 'pitchType'])
d = (val['locPlus'] - val['loc_rep']).abs()
print(f"validation per-type Loc+: n {len(val)}, exact {np.mean(d < 0.05):.3f}, "
      f"median |d| {d.median():.3f}, max {d.max():.2f}")

# ── per-pitch frame ───────────────────────────────────────────────────────
FLIP = {'L': 'R', 'R': 'L'}
rows = []
for key, plist in by_pt.items():
    for p in plist:
        if not L._is_scorable(p):
            continue
        g = L.group_of(p)
        if g not in gA:
            continue
        v = L.score_pitch(p, S)
        if v is None:
            continue
        q = dict(p); q['Bats'] = FLIP[p['Bats']]
        vs = L.score_pitch(q, S)
        rows.append((key[0], key[1], key[2], p['Throws'], p['Bats'], g, v, vs))
df = pd.DataFrame(rows, columns=['pitcher', 'team', 'pt', 'throws', 'bats', 'grp', 'v', 'v_flip'])
df['opp'] = df['bats'] != df['throws']
df['sig'] = df['grp'].map(lambda g: gA[g][1])
df['mu'] = df['grp'].map(lambda g: gA[g][0])
df['g_ship'] = 100 - L.LOC_SCALE_K * (df['v'] - df['mu']) / df['sig']
print(f"scored MLB pitches: {len(df)}")

# A. location fixed: v(opp) - v(same) at each pitch's own location, in points
v_opp = np.where(df['opp'], df['v'], df['v_flip'])
v_same = np.where(df['opp'], df['v_flip'], df['v'])
df['fixed_pen'] = L.LOC_SCALE_K * (v_opp - v_same) / df['sig']   # + = worse vs opposite hand
# B. matchup levels
lev = df.groupby(['grp', 'bats', 'throws'])['v'].mean()
lev_t = df.groupby(['grp', 'throws'])['v'].mean()
df['L_gbt'] = [lev[(g, b, t)] for g, b, t in zip(df['grp'], df['bats'], df['throws'])]
df['L_gt'] = [lev_t[(g, t)] for g, t in zip(df['grp'], df['throws'])]
df['v_neu'] = df['v'] - df['L_gbt'] + df['L_gt']

tabA = []
for (g, t), sub in df.groupby(['grp', 'throws']):
    s = sub['sig'].iloc[0]
    opp = sub[sub['opp']]; same = sub[~sub['opp']]
    tabA.append({'grp': g, 'throws': t, 'n': len(sub), 'opp_share': round(sub['opp'].mean(), 3),
                 'level_gap_pts': round(L.LOC_SCALE_K * (opp['v'].mean() - same['v'].mean()) / s, 2),
                 'fixed_loc_pen_pts': round(sub['fixed_pen'].mean(), 2),
                 'fixed_pen_on_opp_locs': round(opp['fixed_pen'].mean(), 2),
                 'fixed_pen_on_same_locs': round(same['fixed_pen'].mean(), 2)})
tabA = pd.DataFrame(tabA)
print("\nA/B. Opposite-hand penalty per pitch, Loc+ points (+ = opposite hand graded worse)")
print("  level_gap = observed mean opp minus mean same (surface + where pitchers put it)")
print("  fixed_loc_pen = same location, batter flipped (surface only)")
print(tabA.to_string(index=False))

# neutral anchors with the shipped machinery
raw_neu = {}
for key, sub in df.groupby(['pitcher', 'team', 'pt', 'throws']):
    raw_neu[key] = {'raw_loc': float(sub['v_neu'].mean()), 'n_pitches': len(sub)}
_, nA = L._normalize_by_group(raw_neu, group_fn=lambda k: L.group_of_code(k[2]),
                              n_prior=L.N_PRIOR_PT, min_pool=L.MIN_POOL_PT,
                              pool_filter=lambda k: k[1] not in AAA_TEAMS,
                              return_anchors=True)
df['mu_n'] = df['grp'].map(lambda g: nA[g][0])
df['sig_n'] = df['grp'].map(lambda g: nA[g][1])
df['g_neu'] = 100 - L.LOC_SCALE_K * (df['v_neu'] - df['mu_n']) / df['sig_n']
df['a_ship'] = np.round(df['g_ship']).astype(int)   # half-to-even like int(round())
df['a_neu'] = np.round(df['g_neu']).astype(int)

def units(keys, min_n):
    u = (df.groupby(keys)
           .agg(n=('v', 'size'), opp_share=('opp', 'mean'),
                loc_ship=('a_ship', 'mean'), loc_neu=('a_neu', 'mean'),
                grp=('grp', 'first'))
           .reset_index())
    u = u[u['n'] >= min_n].copy()
    u['delta'] = u['loc_neu'] - u['loc_ship']
    return u

ut = units(['pitcher', 'team', 'pt', 'throws'], 100)
print("\nC. Per (pitcher, type) units with 100+ pitches")
out_c = []
for (g, t), sub in ut.groupby(['grp', 'throws']):
    if len(sub) < 15:
        continue
    out_c.append({'grp': g, 'throws': t, 'units': len(sub),
                  'opp_share_sd': round(sub['opp_share'].std(), 3),
                  'r_ship_opp': round(sub[['loc_ship', 'opp_share']].corr().iloc[0, 1], 3),
                  'r_neu_opp': round(sub[['loc_neu', 'opp_share']].corr().iloc[0, 1], 3),
                  'sd_ship': round(sub['loc_ship'].std(), 2),
                  'sd_delta': round(sub['delta'].std(), 2),
                  'p95_abs_delta': round(sub['delta'].abs().quantile(.95), 2),
                  'spearman': round(sub[['loc_ship', 'loc_neu']].corr('spearman').iloc[0, 1], 3)})
out_c = pd.DataFrame(out_c)
print(out_c.to_string(index=False))

si = ut[(ut['grp'] == 'SI')].sort_values('delta', ascending=False)
cols = ['pitcher', 'team', 'throws', 'n', 'opp_share', 'loc_ship', 'loc_neu', 'delta']
print("\nSinker units that gain most from a hand-neutral level:")
print(si[cols].head(12).round(2).to_string(index=False))
print("\nSinker units that lose most:")
print(si[cols].tail(8).round(2).to_string(index=False))

up = units(['pitcher', 'team', 'throws'], 1000)
si_share = (df[df['grp'] == 'SI'].groupby(['pitcher', 'team']).size()
            / df.groupby(['pitcher', 'team']).size()).rename('si_share').reset_index()
up = up.merge(si_share, on=['pitcher', 'team'], how='left').fillna({'si_share': 0.0})  # no sinker = share 0, a real value
print(f"\nOverall Loc+, pitchers with 1000+ pitches: n {len(up)}, "
      f"sd delta {up['delta'].std():.2f}, p95 |delta| {up['delta'].abs().quantile(.95):.2f}, "
      f"spearman {up[['loc_ship', 'loc_neu']].corr('spearman').iloc[0, 1]:.3f}, "
      f"r(ship, opp share) {up[['loc_ship', 'opp_share']].corr().iloc[0, 1]:.3f}, "
      f"r(neu, opp share) {up[['loc_neu', 'opp_share']].corr().iloc[0, 1]:.3f}")
print("Largest overall movers:")
up['absd'] = up['delta'].abs()
print(up.sort_values('absd', ascending=False)[cols + ['si_share']].head(12).round(2).to_string(index=False))

json.dump({'validation': {'n': int(len(val)), 'exact_share': float(np.mean(d < 0.05)),
                          'max_abs': float(d.max())},
           'tabA': tabA.to_dict('records'), 'tabC': out_c.to_dict('records'),
           'si_units': si[cols].round(3).to_dict('records'),
           'pitchers': up[cols + ['si_share']].round(3).to_dict('records')},
          open(os.path.join(DATA, '_loc_platoon_level.json'), 'w'), indent=1)
