"""How much of the Stuff+ gap between pitch types is COUNT DEPLOYMENT?

The Stuff+ model has no count feature, and its per-pitch target is not
count-anchored on balls in play (train_stuff.build_df: a BIP is valued as
(xwOBA - lgwOBA) / wOBAScale, every other pitch as -RunExp, both batter-
positive). The mean target therefore differs by count, and a pitch type thrown
mostly in some counts inherits that count level through the physics that
identify it. On a common display scale that level would read as "stuff".

Per season this script computes, per pitch type (pitcher-positive, so higher
is better, and in common-scale Stuff+ points of 10 / sd_all):

  raw        mean target of the type, minus the all-pitch mean
  cnt_adj    mean of (target - league mean target in that count)
  reweight   type's per-count means re-weighted to the league count mix
  deploy     raw - cnt_adj: the part of the type gap that is count level

sd_all is the pooled between-unit SD of the 2026 common-scale analysis
(data/_stuff_common_scale.json), so the points read on that scale.

Run from the repo root:  python3 scripts/research/stuff/stuff_count_deployment.py
Writes data/_stuff_count_deployment.json.
"""
import json, os, pickle, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATA = os.path.join(ROOT, 'data')
TYPES = ['FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'KC', 'CH', 'FS']

common = json.load(open(os.path.join(DATA, '_stuff_common_scale.json')))
SD_ALL = common['sd_all']


def frame_2026():
    meta = json.load(open(os.path.join(DATA, 'metadata_rs.json')))['gutsConstants']
    D = pickle.load(open(os.path.join(DATA, 'all_pitches_rs_cache.pkl'), 'rb'))
    ep = {(p['Pitcher'], p['PTeam']) for p in D if p.get('Pitch Type') == 'EP'}
    rows = []
    for p in D:
        if p.get('_source') != 'MLB' or (p['Pitcher'], p['PTeam']) in ep:
            continue
        if p.get('Event') == 'Intent Walk' or not p.get('Description'):
            continue
        rows.append((p.get('Pitch Type'), p.get('Count'), p.get('Description'),
                     p.get('xwOBA'), p.get('RunExp')))
    del D
    df = pd.DataFrame(rows, columns=['pt', 'count', 'desc', 'xw', 're'])
    df['xw'] = pd.to_numeric(df['xw'], errors='coerce')
    df['re'] = pd.to_numeric(df['re'], errors='coerce')
    bip = (df['desc'] == 'In Play') & df['xw'].notna()
    # same branches as train_stuff.build_df, batter-positive
    df['t'] = np.where(bip, (df['xw'] - meta['lgWOBA']) / meta['wOBAScale'], -df['re'])
    return df


def frame_statcast(path, lg=0.3169, scale=1.2393):
    # lg/scale: the Loc+ replicate's constants for prior seasons; a level
    # constant on BIP only, which the count-adjusted column does not depend on
    # beyond the BIP share per count
    sc = pd.read_pickle(path)
    sc = sc[['pitch_type', 'balls', 'strikes', 'description', 'delta_run_exp',
             'estimated_woba_using_speedangle', 'bb_type']]
    xw = pd.to_numeric(sc['estimated_woba_using_speedangle'], errors='coerce').to_numpy('float64', na_value=np.nan)
    dre = pd.to_numeric(sc['delta_run_exp'], errors='coerce').to_numpy('float64', na_value=np.nan)
    # BIP on bb_type, never on xwOBA presence (strikeouts and walks carry it)
    bip = (sc['description'].astype(str) == 'hit_into_play').to_numpy() & sc['bb_type'].notna().to_numpy() & ~np.isnan(xw)
    t = np.where(bip, (xw - lg) / scale, dre)       # statcast delta_run_exp is offense-positive
    df = pd.DataFrame({'pt': sc['pitch_type'].astype(str).to_numpy(),
                       'count': sc['balls'].astype(str).to_numpy() + '-' + sc['strikes'].astype(str).to_numpy(),
                       't': t})
    del sc
    return df


def measure(df, label):
    df = df[df['t'].notna() & df['count'].isin([f'{b}-{s}' for b in range(4) for s in range(3)])].copy()
    df['v'] = -df['t']                               # pitcher-positive
    lvl = df.groupby('count')['v'].mean()
    lg_mix = df['count'].value_counts(normalize=True)
    df['v_adj'] = df['v'] - df['count'].map(lvl)
    m_all = df['v'].mean()
    out = []
    for pt in TYPES:
        sub = df[df['pt'] == pt]
        if len(sub) < 2000:
            continue
        per_c = sub.groupby('count')['v'].mean()
        rew = float((per_c * lg_mix.reindex(per_c.index)).sum() / lg_mix.reindex(per_c.index).sum())
        raw = (sub['v'].mean() - m_all) * 10 / SD_ALL
        adj = sub['v_adj'].mean() * 10 / SD_ALL
        out.append({'season': label, 'pt': pt, 'n': int(len(sub)),
                    'two_strike_share': round(float(sub['count'].str.endswith('-2').mean()), 3),
                    'raw': round(raw, 2), 'cnt_adj': round(adj, 2),
                    'reweight': round((rew - m_all) * 10 / SD_ALL, 2),
                    'deploy': round(raw - adj, 2)})
    t = pd.DataFrame(out)
    lv = ((lvl - m_all) * 10 / SD_ALL).round(2)
    print(f"\n=== {label}: {len(df)} pitches; count level in points (pitcher-positive):")
    print('  ' + '  '.join(f'{c} {v:+.1f}' for c, v in lv.items()))
    print(t.drop(columns='season').to_string(index=False))
    spread_raw = t['raw'].max() - t['raw'].min()
    spread_adj = t['cnt_adj'].max() - t['cnt_adj'].min()
    print(f"  type spread raw {spread_raw:.1f} pts, count-adjusted {spread_adj:.1f} pts")
    return t, lv


res = []
levels = {}
for label, fn in (('2026', frame_2026),
                  ('2025', lambda: frame_statcast(os.path.join(DATA, '_statcast2025_full_cache.pkl'))),
                  ('2024', lambda: frame_statcast(os.path.join(DATA, '_statcast2024_cache.pkl')))):
    t, lv = measure(fn(), label)
    res.append(t)
    levels[label] = lv.to_dict()
allr = pd.concat(res)
json.dump({'sd_all': SD_ALL, 'by_type': allr.to_dict('records'), 'count_levels': levels},
          open(os.path.join(DATA, '_stuff_count_deployment.json'), 'w'), indent=1)
