"""aaa_hdera_slope.py — hdERA's runs slope (DH_B) measured on Triple-A.

hdERA = anchor + DH_B * z(xwOBA against, shrunk at N0_XW PA), z over the
30+ IP pool, anchor = the pool's mean ERA (pipeline/eraplus.py). The MLB
DH_B (0.917) is the held-one-season-out OLS slope of same-season ERA on that
z, 30+ IP display population (era_build_dhera_phera.py section 3). This
script runs the same recipe on each level:

  MLB  2021-2025  data/_statcast{Y}_cache.pkl     (validation: must land near 0.917)
  AAA  2023-2025  data/_aaa_statcast{Y}_cache.pkl (Hawk-Eye reached AAA in 2023)
  AAA  2026       data/_milb2026/pitcher_pool_AAA.json (the card's own xwOBA and PA,
                  full regular season; the 2026 statcast cache stops on 08-18)

ERA, earned runs and outs come from the MLB Stats API season endpoint
(sportId 1 / 11), one combined row per pitcher per level. Cached under
data/_aaa_hdera/ (scratch).

Usage: python3 scripts/research/era/aaa_hdera_slope.py
Output: console + data/_aaa_hdera/slopes.json
"""
import json
import math
import os
import sys
import urllib.request

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from pipeline.eraplus import N0_XW, POOL_MIN_OUTS, DH_B  # noqa: E402

OUT = os.path.join(ROOT, 'data', '_aaa_hdera')
LEVELS = {'MLB': (1, [2021, 2022, 2023, 2024, 2025], '_statcast{}_cache.pkl'),
          'AAA': (11, [2023, 2024, 2025, 2026], '_aaa_statcast{}_cache.pkl')}
# PA outcomes outside Savant's wOBA denominator.
NOT_IN_DENOM = {'intent_walk', 'sac_bunt', 'catcher_interf', 'truncated_pa',
                'sac_bunt_double_play'}


def stats_api(sport, season):
    path = os.path.join(OUT, f'era_{sport}_{season}.json')
    if os.path.exists(path):
        return json.load(open(path))
    url = ('https://statsapi.mlb.com/api/v1/stats?stats=season&group=pitching'
           f'&sportId={sport}&season={season}&playerPool=All&limit=10000&gameType=R')
    with urllib.request.urlopen(url, timeout=60) as fh:
        js = json.load(fh)
    out = {}
    for sp in js['stats'][0]['splits']:
        st = sp['stat']
        out[str(sp['player']['id'])] = {'er': int(st.get('earnedRuns', 0)),
                                        'outs': int(st.get('outs', 0))}
    tmp = path + '.tmp'
    json.dump(out, open(tmp, 'w'))
    os.replace(tmp, path)
    return out


def xwoba_by_pitcher(cache):
    d = pd.read_pickle(os.path.join(ROOT, 'data', cache))
    if 'game_type' in d:
        d = d[d['game_type'].astype(str) == 'R']
    ev = d['events'].astype('string')
    d = d[ev.notna() & ~ev.isin(list(NOT_IN_DENOM))]
    x = pd.to_numeric(d['estimated_woba_using_speedangle'], errors='coerce') \
        .to_numpy(dtype='float64', na_value=np.nan)
    ok = ~np.isnan(x)
    g = pd.DataFrame({'p': d['pitcher'].astype('int64').to_numpy()[ok], 'x': x[ok]})
    agg = g.groupby('p')['x'].agg(['sum', 'count'])
    return {str(p): (r['sum'] / r['count'], int(r['count'])) for p, r in agg.iterrows()}


POOL_2026 = os.path.join(ROOT, 'data', '_milb2026', 'pitcher_pool_AAA.json')


def xwoba_from_card_pool():
    pool = json.load(open(POOL_2026))['pitchers']
    return {pid: (r['xwOBA'], r['pa']) for pid, r in pool.items()
            if r.get('xwOBA') is not None and r.get('pa')}


def season_units(sport, season, cache):
    era = stats_api(sport, season)
    xw = (xwoba_from_card_pool() if (sport, season) == (11, 2026)
          else xwoba_by_pitcher(cache.format(season)))
    pool = [(pid, xw[pid], era[pid]) for pid in xw
            if pid in era and era[pid]['outs'] >= POOL_MIN_OUTS]
    tot = sum(pa for _, (_, pa), _ in pool)
    lg = sum(v * pa for _, (v, pa), _ in pool) / tot
    shr = [(v * pa + N0_XW * lg) / (pa + N0_XW) for _, (v, pa), _ in pool]
    m = sum(shr) / len(shr)
    sd = (sum((s - m) ** 2 for s in shr) / len(shr)) ** 0.5
    eras = [e['er'] * 27.0 / e['outs'] for _, _, e in pool]
    units = [((s - m) / sd, y) for s, y in zip(shr, eras)]
    return {'season': season, 'n': len(pool), 'anchor': sum(eras) / len(eras),
            'lg_xw': lg, 'm': m, 'sd': sd, 'units': units}


def ols(units):
    n = len(units)
    mx = sum(u for u, _ in units) / n
    my = sum(y for _, y in units) / n
    sxx = sum((u - mx) ** 2 for u, _ in units)
    b = sum((u - mx) * (y - my) for u, y in units) / sxx
    return my - b * mx, b


def main():
    os.makedirs(OUT, exist_ok=True)
    res = {}
    for lvl, (sport, seasons, cache) in LEVELS.items():
        print(f'=== {lvl} ===')
        reps = [season_units(sport, s, cache) for s in seasons]
        per = []
        for r in reps:
            a, b = ols(r['units'])
            per.append(b)
            print(f"  {r['season']}: n {r['n']:4d}  anchor {r['anchor']:.3f}  lg_xw {r['lg_xw']:.4f}  "
                  f"m {r['m']:.4f}  sd {r['sd']:.4f}  own slope {b:+.3f}")
        loso = []
        for i, r in enumerate(reps):
            train = [u for j, q in enumerate(reps) if j != i for u in q['units']]
            a, b = ols(train)
            # held-out error of the production form: anchor_i + b * z
            err = math.sqrt(sum((r['anchor'] + b * z - y) ** 2 for z, y in r['units'])
                            / len(r['units']))
            loso.append(b)
            print(f"  hold out {r['season']}: slope {b:+.3f}  rmse {err:.3f}")
        mean_b = sum(loso) / len(loso)
        print(f'  LOSO slope mean {mean_b:+.3f}  range [{min(loso):+.3f}, {max(loso):+.3f}]'
              + (f'  (shipped MLB DH_B {DH_B})' if lvl == 'MLB' else ''))
        res[lvl] = {'loso_b': mean_b, 'loso': loso, 'own': per,
                    'seasons': [{k: v for k, v in r.items() if k != 'units'} for r in reps]}
    tmp = os.path.join(OUT, 'slopes.json.tmp')
    json.dump(res, open(tmp, 'w'), indent=1)
    os.replace(tmp, os.path.join(OUT, 'slopes.json'))


if __name__ == '__main__':
    main()
