#!/usr/bin/env python3
"""stuff_sweeper_count.py — is the persistent part of sweeper results the
pitcher's COUNT USAGE?

Context: sweeper (ST) Stuff+ carries to the next season at r .12 against
.28-.42 for other types, while ST results persist (r .28). Noise, spread,
labels, the monotone rule, the one-model design, pitch change, Loc+
location and role are ruled out. The Stuff+ label is not count-anchored
(train_stuff.build_df note), so a pitcher who throws his sweeper mostly
with two strikes posts better results for reasons no physics grade can see,
and a count habit can persist.

Per pitch: target t (pitcher-positive, the build_df rule: xwOBA on balls in
play, RunExp otherwise, season Guts as in the gate). Count value
c = E[t | season, type, count] (league mean of the cell); count-adjusted
result ta = t - c. Unit (pitcher, type) means, units >= 150 pitches both
seasons, gate pairs, demeaned within (pair, type):

  t_persist      r(t_Y, t_Y+1)          raw result persistence
  cmix_persist   r(c_Y, c_Y+1)          is the count habit stable
  cmix_next      r(c_Y, t_Y+1)          count habit -> next-season result
  ta_persist     r(ta_Y, ta_Y+1)        persistence once count mix is out
  grade_next     r(grade_Y, t_Y+1)      Stuff+ (gate SHIPPED s0 unit grade)
  grade_next_ta  r(grade_Y, ta_Y+1)     Stuff+ vs the count-adjusted result
  sd_c / sd_t    unit SD of the count value vs of the result, runs/100

A second version uses (count x same-hand) cells for c.

Sources: 2021-2025 Statcast caches (regular season, EP throwers dropped);
2026 the sheets cache (MLB rows). Grades join by (pitcher name, pitch type)
to the gate aggregates; the join rate is printed.

Output: data/_sweeper_count.json. Run from the repo root.
"""
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
import stuff_plus.train_stuff as T                      # noqa: E402

GATE = os.path.join(ROOT, 'data', '_gate_v2')
OUT = os.path.join(ROOT, 'data', '_sweeper_count.json')
PAIRS = [2021, 2022, 2023, 2024, 2025]
TYPES = ['FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS']
GUTS = {2021: (0.314, 1.209), 2022: (0.310, 1.259), 2023: (0.318, 1.204),
        2024: (0.310, 1.242), 2025: (T.PRIOR_LG_WOBA, T.PRIOR_WOBA_SCALE)}
MIN_U = 150


def _num(s):
    return pd.to_numeric(s, errors='coerce').to_numpy(dtype='float64', na_value=np.nan)


def from_cache(y):
    df = pickle.load(open(os.path.join(ROOT, 'data', f'_statcast{y}_cache.pkl'), 'rb'))
    df = df[df['game_type'] == 'R']
    ep = set(df.loc[df['pitch_type'] == 'EP', 'pitcher'])
    df = df[~df['pitcher'].isin(ep)]
    lg, sc = GUTS[y]
    bip = df['description'].astype(str).values == 'hit_into_play'
    xw, dre = _num(df['estimated_woba_using_speedangle']), _num(df['delta_run_exp'])
    tgt = np.where(bip & np.isfinite(xw), (xw - lg) / sc, dre)     # batter-positive
    b, s = _num(df['balls']), _num(df['strikes'])
    out = pd.DataFrame({'pitcher': df['player_name'].astype(str).values,
                        'pitch_type': df['pitch_type'].astype(str).values,
                        'same': (df['stand'].astype(str).values == df['p_throws'].astype(str).values),
                        't': -tgt, 'b': b, 's': s})
    del df
    return out


def from_sheets():
    allp = pickle.load(open(os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl'), 'rb'))
    ep = {(p.get('Pitcher'), p.get('PTeam')) for p in allp if p.get('Pitch Type') == 'EP'}
    rec = []
    for p in allp:
        if p.get('_source') != 'MLB' or (p.get('Pitcher'), p.get('PTeam')) in ep:
            continue
        xw, re = T.sf(p.get('xwOBA')), T.sf(p.get('RunExp'))
        if p.get('Description') == 'In Play' and xw is not None:
            tgt = (xw - T.LG_WOBA) / T.WOBA_SCALE
        elif re is not None:
            tgt = -re
        else:
            continue
        c = p.get('Count')
        bb, ss = (c.split('-') if isinstance(c, str) and '-' in c else (None, None))
        rec.append((p.get('Pitcher'), p.get('Pitch Type'), p.get('Bats') == p.get('Throws'),
                    -tgt, bb, ss))
    del allp
    out = pd.DataFrame(rec, columns=['pitcher', 'pitch_type', 'same', 't', 'b', 's'])
    out['b'] = pd.to_numeric(out['b'], errors='coerce')
    out['s'] = pd.to_numeric(out['s'], errors='coerce')
    return out


def season(y):
    f = from_sheets() if y == 2026 else from_cache(y)
    f = f[f['pitch_type'].isin(TYPES) & np.isfinite(f['t']) & f['b'].between(0, 3) & f['s'].between(0, 2)].copy()
    f['count'] = (f['b'] * 3 + f['s']).astype(int)
    f['c'] = f.groupby(['pitch_type', 'count'])['t'].transform('mean')
    f['c2'] = f.groupby(['pitch_type', 'count', 'same'])['t'].transform('mean')
    f['ta'], f['ta2'] = f['t'] - f['c'], f['t'] - f['c2']
    return f.groupby(['pitcher', 'pitch_type']).agg(
        t=('t', 'mean'), c=('c', 'mean'), c2=('c2', 'mean'), ta=('ta', 'mean'),
        ta2=('ta2', 'mean'), n=('t', 'size'))


def r(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    return float(np.corrcoef(a[m], b[m])[0, 1]) if m.sum() > 10 else float('nan')


def main():
    S = {y: season(y) for y in range(2021, 2027)}
    rows, joins = [], {}
    for Y in PAIRS:
        j = S[Y].join(S[Y + 1], rsuffix='_1', how='inner')
        j = j[(j['n'] >= MIN_U) & (j['n_1'] >= MIN_U)].reset_index()
        a = pd.read_pickle(os.path.join(GATE, f'agg_SHIPPED_{Y}_s0.pkl'))['uy'][['s_r']].reset_index()
        j = j.merge(a, on=['pitcher', 'pitch_type'], how='left')
        st = j[j['pitch_type'] == 'ST']
        joins[str(Y)] = {'all': float(j['s_r'].notna().mean()), 'ST': float(st['s_r'].notna().mean())}
        j['pair'] = Y
        rows.append(j)
    U = pd.concat(rows, ignore_index=True)
    cols = ['t', 'c', 'c2', 'ta', 'ta2', 's_r', 't_1', 'c_1', 'c2_1', 'ta_1', 'ta2_1']
    for c in cols:
        U[c] = U[c] - U.groupby(['pair', 'pitch_type'])[c].transform('mean')
    print('grade join rate by pair: ' + ', '.join(f"{k} {v['all']:.0%} (ST {v['ST']:.0%})" for k, v in joins.items()))
    out = {'grade_join': joins, 'types': {}}
    print('\ntype units  tPers  cmixPers  cmix>nxt  taPers  ta2Pers  grade>nxt  grade>ta  grade>ta2   sd_c  sd_t')
    for t in TYPES:
        g = U[U['pitch_type'] == t]
        gg = g[g['s_r'].notna()]
        rec = {'units': int(len(g)), 'units_graded': int(len(gg)),
               't_persist': r(g['t'].values, g['t_1'].values),
               'cmix_persist': r(g['c'].values, g['c_1'].values),
               'cmix_next': r(g['c'].values, g['t_1'].values),
               'ta_persist': r(g['ta'].values, g['ta_1'].values),
               'ta2_persist': r(g['ta2'].values, g['ta2_1'].values),
               'grade_next': r(gg['s_r'].values, gg['t_1'].values),
               'grade_next_ta': r(gg['s_r'].values, gg['ta_1'].values),
               'grade_next_ta2': r(gg['s_r'].values, gg['ta2_1'].values),
               'sd_c_runs100': float(g['c'].std() * 100), 'sd_t_runs100': float(g['t'].std() * 100)}
        out['types'][t] = rec
        print(f"{t:4} {len(g):5}  {rec['t_persist']:.3f}  {rec['cmix_persist']:8.3f}  {rec['cmix_next']:8.3f}  "
              f"{rec['ta_persist']:.3f}  {rec['ta2_persist']:7.3f}  {rec['grade_next']:9.3f}  "
              f"{rec['grade_next_ta']:8.3f}  {rec['grade_next_ta2']:9.3f}  {rec['sd_c_runs100']:5.2f}  "
              f"{rec['sd_t_runs100']:4.2f}")
    json.dump(out, open(OUT + '.tmp', 'w'), indent=1)
    os.replace(OUT + '.tmp', OUT)
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
