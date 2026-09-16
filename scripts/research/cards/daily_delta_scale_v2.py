#!/usr/bin/env python3
"""Day-to-day scales for the daily pitcher scan (scripts/tools/daily_pitcher_scan.py).

Extends daily_delta_scale.py (velo, usage) to the columns the scan flags:
release X (hand-signed), release Z, extension (mean-type columns, model
Var(d) = SD_day^2 + s^2/n), and whiff rate, chase rate, CSW (rate columns,
model Var(d) = c * p(1-p) + p(1-p)/n, the usage model).

Reads the 2021-2025 Statcast caches directly (they carry release point,
extension, description and plate coordinates). Whiff = swinging strikes over
swings (bunts excluded, per the repo rule). Chase = swings at out-of-zone
pitches over out-of-zone pitches; the zone here is the plain rectangle
(half-width 0.83 ft, sz_top/sz_bot) -- close to, not identical with, the
sheet's Savant-exact InZone, which is fine for a noise SCALE.

Each constant is reported per season as five independent replicates.

Then the threshold sweep: for a flag at |z| >= t on a mean-type column, the
share of flagged starts whose NEXT start (same pitcher, season, type) moved
the same direction by at least half a day-SD ("persisted"), against the
base rate of the same event over all starts. This is a precision curve, not
an optimum: there is no stated exchange rate between a missed change and a
false flag, so the shipped threshold is a convention read off the curve.
"""
import os, sys
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATA = os.path.join(ROOT, 'data')
PTS = ('FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS')
SWING = {'swinging_strike', 'swinging_strike_blocked', 'foul', 'foul_tip',
         'hit_into_play', 'hit_into_play_no_out', 'hit_into_play_score'}
WHIFF = {'swinging_strike', 'swinging_strike_blocked'}
CSW = WHIFF | {'called_strike'}

frames = []
for y in range(2021, 2026):
    d = pd.read_pickle(f'{DATA}/_statcast{y}_cache.pkl')
    d = d[['game_pk', 'pitcher', 'p_throws', 'pitch_type', 'release_speed',
           'release_pos_x', 'release_pos_z', 'release_extension', 'description',
           'plate_x', 'plate_z', 'sz_top', 'sz_bot', 'game_date', 'pfx_x', 'pfx_z', 'release_spin_rate']].copy()
    d['season'] = y
    frames.append(d)
d = pd.concat(frames, ignore_index=True); del frames
for c in ['release_speed', 'release_pos_x', 'release_pos_z', 'release_extension',
          'plate_x', 'plate_z', 'sz_top', 'sz_bot', 'pfx_x', 'pfx_z', 'release_spin_rate']:
    d[c] = pd.to_numeric(d[c], errors='coerce').astype('float64')
d = d[d.pitch_type.isin(PTS) & d.p_throws.isin(['L', 'R'])]
d['rx_s'] = d.release_pos_x * np.where(d.p_throws == 'R', 1.0, -1.0)
d['ivb'] = d.pfx_z * 12.0
d['hb_s'] = d.pfx_x * 12.0 * np.where(d.p_throws == 'R', 1.0, -1.0)
d['spin'] = d.release_spin_rate
d['swing'] = d.description.isin(SWING)
d['whiff'] = d.description.isin(WHIFF)
d['csw'] = d.description.isin(CSW)
d['inzone'] = (d.plate_x.abs() <= 0.83) & (d.plate_z >= d.sz_bot) & (d.plate_z <= d.sz_top)
d['ooz'] = ~d.inzone & d.plate_x.notna() & d.plate_z.notna()
d['chase'] = d.ooz & d.swing
d['gdate'] = pd.to_datetime(d.game_date)

key = ['pitcher', 'season', 'game_pk', 'pitch_type']
g = d.groupby(key)
st = g.agg(n=('release_speed', 'size'), gdate=('gdate', 'first'),
           velo_m=('release_speed', 'mean'), velo_s=('release_speed', 'std'),
           rx_m=('rx_s', 'mean'), rx_s=('rx_s', 'std'),
           rz_m=('release_pos_z', 'mean'), rz_s=('release_pos_z', 'std'),
           ext_m=('release_extension', 'mean'), ext_s=('release_extension', 'std'),
           ivb_m=('ivb', 'mean'), ivb_s=('ivb', 'std'), hb_m=('hb_s', 'mean'), hb_s=('hb_s', 'std'),
           spin_m=('spin', 'mean'), spin_s=('spin', 'std'),
           swings=('swing', 'sum'), whiffs=('whiff', 'sum'),
           csws=('csw', 'sum'), ooz=('ooz', 'sum'), chases=('chase', 'sum')).reset_index()
tot = d.groupby(['pitcher', 'season', 'game_pk']).size().rename('tc').reset_index()
szn = d.groupby(['pitcher', 'season', 'pitch_type']).agg(
    szn_n=('release_speed', 'size'), velo_z=('release_speed', 'mean'),
    rx_z=('rx_s', 'mean'), rz_z=('release_pos_z', 'mean'), ext_z=('release_extension', 'mean'),
    ivb_z=('ivb', 'mean'), hb_z=('hb_s', 'mean'), spin_z=('spin', 'mean'),
    szn_swings=('swing', 'sum'), szn_whiffs=('whiff', 'sum'), szn_csw=('csw', 'sum'),
    szn_ooz=('ooz', 'sum'), szn_chase=('chase', 'sum')).reset_index()
szn_tot = d.groupby(['pitcher', 'season']).size().rename('szn_tc').reset_index()
st = st.merge(tot).merge(szn).merge(szn_tot)
st = st[(st.tc >= 30) & (st.szn_tc >= 500) & (st.n >= 6) & (st.szn_n >= 50)].copy()
st = st.sort_values(['pitcher', 'season', 'pitch_type', 'gdate'])
st.to_pickle(os.environ.get('DDS_ST_OUT', '/dev/null')) if os.environ.get('DDS_ST_OUT') else None

def mean_scale(col, label, unit):
    print(f'\n=== {label}: SD_day per pitch type ({unit}) ===')
    v = st[st[f'{col}_s'].notna() & st[f'{col}_m'].notna()].copy()
    v['d'] = v[f'{col}_m'] - v[f'{col}_z']
    v['samp'] = v[f'{col}_s'] ** 2 / v.n
    rows, out = [], {}
    for pt in PTS:
        q = v[v.pitch_type == pt]
        if len(q) < 300: continue
        r = {'pt': pt, 'starts': len(q)}
        for yr, qq in [('ALL', q)] + [(y, q[q.season == y]) for y in range(2021, 2026)]:
            r[str(yr)] = np.nan if len(qq) < 200 else np.sqrt(max(qq.d.var() - qq.samp.mean(), 0.0))
        rows.append(r); out[pt] = r['ALL']
    print(pd.DataFrame(rows).set_index('pt').round(4).to_string())
    return out, v

def rate_scale(num, den, label):
    print(f'\n=== {label}: overdispersion c per pitch type (day var = c * p(1-p)) ===')
    v = st[st[den] >= 5].copy()
    v['p_obs'] = v[num] / v[den]
    v['p_base'] = v[f'szn_{num}' if f'szn_{num}' in v else num] / v[f'szn_{den}' if f'szn_{den}' in v else den]
    v = v[(v.p_base > 0.02) & (v.p_base < 0.98)]
    v['d'] = v.p_obs - v.p_base
    v['binom'] = v.p_base * (1 - v.p_base) / v[den]
    rows, out = [], {}
    for pt in PTS:
        q = v[v.pitch_type == pt]
        if len(q) < 300: continue
        r = {'pt': pt, 'starts': len(q), 'med_p': q.p_base.median()}
        for yr, qq in [('ALL', q)] + [(y, q[q.season == y]) for y in range(2021, 2026)]:
            r[str(yr)] = np.nan if len(qq) < 200 else \
                (qq.d.var() - qq.binom.mean()) / (qq.p_base * (1 - qq.p_base)).mean()
        rows.append(r); out[pt] = r['ALL']
    print(pd.DataFrame(rows).set_index('pt').round(4).to_string())
    q = v
    c_all = (q.d.var() - q.binom.mean()) / (q.p_base * (1 - q.p_base)).mean()
    print(f'pooled c: {c_all:.4f}')
    return out, c_all

results = {}
for col, label, unit in [('velo', 'VELO', 'mph'), ('rx', 'RELEASE X (hand-signed)', 'ft'),
                         ('rz', 'RELEASE Z', 'ft'), ('ext', 'EXTENSION', 'ft'),
                         ('ivb', 'IVB', 'in'), ('hb', 'HB (hand-signed)', 'in'), ('spin', 'SPIN', 'rpm')]:
    sc, v = mean_scale(col, label, unit)
    results[col] = sc
    # threshold sweep on persistence
    v['sd_day'] = v.pitch_type.map(sc)
    v = v[v.sd_day.notna()].copy()
    v['z'] = v.d / np.sqrt(v.sd_day ** 2 + v.samp)
    v['d_next'] = v.groupby(['pitcher', 'season', 'pitch_type']).d.shift(-1)
    v = v[v.d_next.notna()]
    persist = (np.sign(v.d_next) == np.sign(v.d)) & (v.d_next.abs() >= 0.5 * v.sd_day)
    print(f'  persistence sweep ({label}): base rate {persist.mean()*100:.1f}% of all starts')
    print('   t    flagged%   persisted%   flags/1000 starts')
    for t in (1.0, 1.5, 2.0, 2.5, 3.0, 3.5):
        f = v.z.abs() >= t
        print(f'  {t:.1f}   {f.mean()*100:6.2f}   {persist[f].mean()*100:8.1f}      {f.mean()*1000:6.1f}')

st_sw = st.rename(columns={'szn_swings': 'szn_swings', 'szn_whiffs': 'szn_whiffs'})
for num, den, label in [('whiffs', 'swings', 'WHIFF RATE'), ('chases', 'ooz', 'CHASE RATE'), ('csws', 'n', 'CSW')]:
    if num == 'csws':
        st['szn_csws'] = st['szn_csw']; st['szn_n_'] = st['szn_n']
        v = st.copy(); v['csws_'] = v.csws
    if num == 'chases':
        st['szn_chases'] = st['szn_chase']
    c, c_all = rate_scale(num, den, label)
    results[num] = {'per_type': c, 'pooled': c_all}

import json
json.dump(results, open(f'{DATA}/_daily_scan_scales.json', 'w'), indent=1, default=float)
print('\nwrote data/_daily_scan_scales.json')
