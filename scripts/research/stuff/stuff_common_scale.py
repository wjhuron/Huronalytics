"""Stuff+ on a common (pitch-type agnostic) display scale, side by side with
the shipped per-type scale.

The model is already type agnostic; only the display anchor is per type:
atom = 100 + 10 * (raw - mu_type) / sd_type. This script inverts each shipped
(pitcher, team, pitch type) stuffScore back to its raw mean with the anchors in
data/stuff_bundle_info.json (written by CI on the same run as the leaderboard),
then re-anchors every unit on ONE scale:

  common = 100 + 10 * (raw - mu_all) / sd_all
  mu_all = pitch-weighted mean raw over qualified units (100 = the average MLB pitch)
  sd_all = SD of qualified unit means across all types pooled

Per-type rows invert exactly up to the integer-atom rounding (< 0.5 pt). The
overall common grade is the count-weighted mean of a pitcher's common rows.

Run from the repo root:  python3 scripts/research/stuff/stuff_common_scale.py
Writes data/_stuff_common_scale.json and data/_stuff_common_scale.csv.
"""
import json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATA = os.path.join(ROOT, 'data')
QUAL_N = 50          # same unit floor as train_stuff.QUAL_N
K_SCALE = 10

info = json.load(open(os.path.join(DATA, 'stuff_bundle_info.json')))
league = info['league']
pt = pd.DataFrame(json.load(open(os.path.join(DATA, 'pitch_leaderboard_rs.json'))))
pr = pd.DataFrame(json.load(open(os.path.join(DATA, 'pitcher_leaderboard_rs.json'))))

AAA = {'ROC', 'AAA'}
pt = pt[~pt['team'].isin(AAA) & pt['stuffScore'].notna()].copy()
pt = pt[pt['pitchType'].isin([k for k in league if not k.startswith('_')])]
combined = pt['team'].str.fullmatch(r'\d+TM')
mu = pt['pitchType'].map(lambda t: league[t]['mu'])
sd = pt['pitchType'].map(lambda t: league[t]['sd'])
pt['raw'] = mu + sd * (pt['stuffScore'] - 100) / K_SCALE

# Anchor pool: qualified units, combined (2TM..) rows out so no pitcher counts twice
pool = pt[(pt['count'] >= QUAL_N) & ~combined]
mu_all = float(np.average(pool['raw'], weights=pool['count']))
sd_all = float(pool['raw'].std())
pt['common'] = 100 + K_SCALE * (pt['raw'] - mu_all) / sd_all

# Validation: shipped overall Stuff+ vs count-weighted mean of shipped per-type rows
def wmean(g, col):
    return float(np.average(g[col], weights=g['count']))
ov = (pt.groupby(['pitcher', 'team'])
        .apply(lambda g: pd.Series({'pertype_wmean': wmean(g, 'stuffScore'),
                                    'common': wmean(g, 'common'),
                                    'n': int(g['count'].sum()),
                                    'ffsi_share': float(g.loc[g['pitchType'].isin(['FF', 'SI']), 'count'].sum() / g['count'].sum()),
                                    'fb_share': float(g.loc[g['pitchType'].isin(['FF', 'SI', 'FC']), 'count'].sum() / g['count'].sum())}),
               include_groups=False)
        .reset_index())
ov = ov.merge(pr[['pitcher', 'team', 'stuffScore', 'mlbId']], on=['pitcher', 'team'], how='left')
val_diff = (ov['stuffScore'] - ov['pertype_wmean']).abs()
print(f"validation: shipped overall vs weighted per-type mean, median |d| {val_diff.median():.3f}, "
      f"p95 {val_diff.quantile(.95):.3f}, n {val_diff.notna().sum()}")

print(f"\ncommon anchor: mu_all {mu_all:.5f}, sd_all {sd_all:.5f}  "
      f"(per-type sd range {min(v['sd'] for k,v in league.items() if not k.startswith('_')):.5f}"
      f"-{max(v['sd'] for k,v in league.items() if not k.startswith('_')):.5f})")

qual_units = pt[(pt['count'] >= QUAL_N) & ~combined]
by_type = (qual_units.groupby('pitchType')
           .agg(units=('common', 'size'),
                common_mean=('common', 'mean'), common_sd=('common', 'std'),
                common_p10=('common', lambda s: s.quantile(.1)),
                common_p90=('common', lambda s: s.quantile(.9)),
                pertype_mean=('stuffScore', 'mean'))
           .sort_values('common_mean'))
print('\nPer-type unit grades on the common scale (qualified units):')
print(by_type.round(1).to_string())

q = ov[(ov['n'] >= 1000) & ~ov['team'].str.fullmatch(r'\d+TM')].copy()
q['delta'] = q['common'] - q['stuffScore']
r_mix = float(np.corrcoef(q['delta'], q['fb_share'])[0, 1])
r_rank = float(q[['common', 'stuffScore']].corr(method='spearman').iloc[0, 1])
print(f"\nPitchers with 1000+ pitches: {len(q)}")
print(f"  Spearman(common, shipped) {r_rank:.3f}")
print(f"  SD common {q['common'].std():.1f} vs shipped {q['stuffScore'].std():.1f}")
print(f"  r(common - shipped, FF+SI+FC share) {r_mix:.3f}")
print(f"  |delta| median {q['delta'].abs().median():.1f}, p90 {q['delta'].abs().quantile(.9):.1f}")

q['rank_shipped'] = q['stuffScore'].rank(ascending=False).astype(int)
q['rank_common'] = q['common'].rank(ascending=False).astype(int)
cols = ['pitcher', 'team', 'n', 'fb_share', 'stuffScore', 'common', 'delta', 'rank_shipped', 'rank_common']
print('\nBiggest gainers on the common scale:')
print(q.sort_values('delta', ascending=False)[cols].head(12).round(2).to_string(index=False))
print('\nBiggest losers on the common scale:')
print(q.sort_values('delta')[cols].head(12).round(2).to_string(index=False))
print('\nTop 15 on the common scale:')
print(q.sort_values('common', ascending=False)[cols].head(15).round(2).to_string(index=False))

pt.to_csv(os.path.join(DATA, '_stuff_common_scale.csv'), index=False)
json.dump({'mu_all': mu_all, 'sd_all': sd_all, 'qual_n': QUAL_N,
           'bundle_version': info.get('version'),
           'by_type': by_type.round(3).reset_index().to_dict('records'),
           'pitchers_1000': {'n': len(q), 'spearman': r_rank, 'r_delta_fbshare': r_mix,
                             'sd_common': float(q['common'].std()),
                             'sd_shipped': float(q['stuffScore'].std())},
           'pitchers': q[cols].round(3).to_dict('records')},
          open(os.path.join(DATA, '_stuff_common_scale.json'), 'w'), indent=1)
