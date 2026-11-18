#!/usr/bin/env python3
"""locplus_two_number_prototype.py — the two-number Loc+ split as research columns
for one season, beside shipped Loc+. Writes CSVs only; no shipped artifact moves.

Per pitch, on the full-season surfaces (as production):
  v_anch     expected hitter run value with the ball in play in count currency
  situation  league mean of v_anch for the pitch's (group, batter hand, pitcher
             hand, count)
  location   v_anch minus situation

Rendered like every other Loc+ number: an integer atom per pitch, 100 = the
average unit of the pitch's group and 10 points = one SD between units (unit =
pitcher x hand x pitch type, 60+ pitches), and a displayed value = the plain mean
of atoms.
  Location+   100 - 10 * (location - mu_g) / sd_g     where he put the ball
  Situation+  100 - 10 * (situation - mu_g) / sd_g    the counts and matchups he threw in
A second situation column uses SHIPPED pricing (situationPlus_shipPricing). That one
carried the next-season forecast in the 2026-11-18 build; the anchored one does not,
and it still shows the pricing error left at three-ball counts.
The two do not add up to shipped Loc+ in points: each has its own SD.

VALIDATION: the script also re-renders shipped Loc+ from the same pitches and
prints its agreement with locPlus in data/pitcher_leaderboard_rs.json.

Outputs (data/_loc_two_number/ and a copy in ~/Downloads):
  locplus_split_pitchers_{year}.csv, locplus_split_pitch_types_{year}.csv

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/locplus_two_number_prototype.py [2026]
"""
import json
import os
import shutil
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline.locplus as lp  # noqa: E402
import locplus_fullseason_replicate as FR  # noqa: E402
import locplus_count_calibration as CC  # noqa: E402

CACHE = os.path.join(ROOT, 'data', '_loc_two_number')
DOWN = os.path.expanduser('~/Downloads')
MIN_POOL = lp.MIN_POOL_PT


def atoms(d, col):
    """Integer atom per pitch for a value column, anchored per group on unit means."""
    u = d.groupby(['pitcher', 'throws', 'pt', 'grp'])[col].agg(['mean', 'size']).reset_index()
    q = u[u['size'] >= MIN_POOL]
    anc = q.groupby('grp')['mean'].agg(mu='mean', sd=lambda s: float(np.sqrt(((s - s.mean()) ** 2).mean())))
    j = d.join(anc, on='grp')
    a = np.rint(100.0 - lp.LOC_SCALE_K * (j[col] - j['mu']) / j['sd'])
    return a.where(j['sd'] > 1e-12)


def main():
    y = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    pitches = FR.load_season(y)
    base_p = [p for p in pitches if lp.is_eligible_baseline(p)]
    S = lp.build_surfaces(base_p, FR.LG, FR.SCALE)
    off = lp.build_bip_count_offsets(base_p, FR.LG, FR.SCALE)
    rows = []
    for p in pitches:
        if not lp._is_scorable(p):
            continue
        v0 = lp.score_pitch(p, S)
        if v0 is None:
            continue
        c = lp.get_count(p)
        rows.append((p.get('Pitcher'), p.get('Throws'), p.get('PTeam'), p.get('Pitch Type'), lp.group_of(p),
                     p.get('Bats'), f'{c[0]}-{c[1]}', v0, CC.score(p, S, off, None)))
    del pitches, base_p
    d = pd.DataFrame(rows, columns=['pitcher', 'throws', 'team', 'pt', 'grp', 'bats', 'count', 'v_ship', 'v_anch'])
    d['situation'] = d.groupby(['grp', 'bats', 'throws', 'count'])['v_anch'].transform('mean')
    d['location'] = d['v_anch'] - d['situation']
    # the situation on SHIPPED pricing: the version that carries the forecast (2026-11-18 build)
    d['situation_ship'] = d.groupby(['grp', 'bats', 'throws', 'count'])['v_ship'].transform('mean')
    d['a_ship'], d['a_loc'], d['a_sit'] = atoms(d, 'v_ship'), atoms(d, 'location'), atoms(d, 'situation')
    d['a_sit_ship'] = atoms(d, 'situation_ship')

    print('mean atom by count (shipped | Location+ | Situation+):')
    print(d.groupby('count')[['a_ship', 'a_loc', 'a_sit', 'a_sit_ship']].mean().round(1).T.to_string())
    print('\nmean atom by pitcher hand and batter side:')
    d['side'] = np.where(d['bats'] == d['throws'], 'same', 'opp')
    print(d.groupby(['throws', 'side'])[['a_ship', 'a_loc', 'a_sit']].mean().round(1).to_string())

    def table(keys):
        g = d.groupby(keys)
        t = g[['a_ship', 'a_loc', 'a_sit', 'a_sit_ship']].mean().round(1)
        t.columns = ['locPlus_rebuilt', 'locationPlus', 'situationPlus', 'situationPlus_shipPricing']
        t['pitches'] = g.size()
        t['teams'] = g['team'].agg(lambda s: '/'.join(sorted(set(x for x in s if x))))
        return t.reset_index()

    P = table(['pitcher', 'throws'])
    T = table(['pitcher', 'throws', 'pt']).rename(columns={'pt': 'pitchType'})
    if y == 2026:
        lb = json.load(open(os.path.join(ROOT, 'data', 'pitcher_leaderboard_rs.json')))
        from pipeline.utils import AAA_TEAMS
        best = {}
        for r in lb:
            if r.get('team') in AAA_TEAMS or r.get('locPlus') is None:
                continue
            k = r['pitcher']
            if k not in best or (r.get('count') or 0) > best[k][0]:
                best[k] = (r.get('count') or 0, r['locPlus'])
        P['locPlus_shipped'] = P['pitcher'].map({k: v[1] for k, v in best.items()})
        P['n_shipped'] = P['pitcher'].map({k: v[0] for k, v in best.items()})
        m = P[(P['pitches'] >= 300) & P['locPlus_shipped'].notna() & (P['n_shipped'] == P['pitches'])]
        diff = (m['locPlus_rebuilt'] - m['locPlus_shipped']).abs()
        print(f'\nVALIDATION: rebuilt shipped Loc+ against the leaderboard, {len(m)} pitchers with 300+ pitches and the '
              f'same pitch count: r {np.corrcoef(m.locPlus_rebuilt, m.locPlus_shipped)[0, 1]:.4f}, '
              f'median |diff| {diff.median():.2f}, max {diff.max():.2f}, exact {int((diff < 0.05).sum())}')
        m2 = P[(P['pitches'] >= 300) & P['locPlus_shipped'].notna()]
        print(f'  all {len(m2)} with 300+ pitches (pitch counts may differ): r '
              f'{np.corrcoef(m2.locPlus_rebuilt, m2.locPlus_shipped)[0, 1]:.4f}, median |diff| '
              f'{(m2.locPlus_rebuilt - m2.locPlus_shipped).abs().median():.2f}')
    q = P[P['pitches'] >= 300]
    print(f'\n{len(q)} pitchers with 300+ pitches: SD rebuilt {q.locPlus_rebuilt.std():.2f}, Location+ {q.locationPlus.std():.2f}, '
          f'Situation+ {q.situationPlus.std():.2f}; r(Location+, Situation+) {np.corrcoef(q.locationPlus, q.situationPlus)[0, 1]:.2f}, '
          f'r(Location+, shipped) {np.corrcoef(q.locationPlus, q.locPlus_rebuilt)[0, 1]:.2f}, '
          f'r(Situation+, shipped) {np.corrcoef(q.situationPlus, q.locPlus_rebuilt)[0, 1]:.2f}')
    q2 = q[q['pitches'] >= 1000].copy()
    q2['move'] = q2['locationPlus'] - q2['locPlus_rebuilt']
    cols = ['pitcher', 'throws', 'pitches', 'locPlus_rebuilt', 'locationPlus', 'situationPlus']
    print('\nlargest Location+ ABOVE shipped (1,000+ pitches):'); print(q2.sort_values('move').tail(8)[cols].to_string(index=False))
    print('\nlargest Location+ BELOW shipped (1,000+ pitches):'); print(q2.sort_values('move').head(8)[cols].to_string(index=False))
    print('\ntop 8 Location+ (1,000+ pitches):'); print(q2.sort_values('locationPlus').tail(8)[cols].to_string(index=False))
    os.makedirs(CACHE, exist_ok=True)
    for name, t in ((f'locplus_split_pitchers_{y}.csv', P.sort_values('pitches', ascending=False)),
                    (f'locplus_split_pitch_types_{y}.csv', T.sort_values(['pitcher', 'pitches'], ascending=[True, False]))):
        fn = os.path.join(CACHE, name)
        t.to_csv(fn + '.tmp', index=False)
        os.replace(fn + '.tmp', fn)
        shutil.copyfile(fn, os.path.join(DOWN, name))
        print(f'wrote {fn} and a copy in ~/Downloads')


if __name__ == '__main__':
    main()
