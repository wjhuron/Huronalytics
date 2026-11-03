"""pull_fg_projections.py: full FanGraphs preseason projections (Steamer, ZiPS) for the head-to-head.

The trade-value archive (data/steamer_preseason/) kept only WAR and PA. This pulls the whole payload
(wOBA, Batting / BaseRunning / Fielding / Positional / Replacement runs, ERA, FIP, K/BB, IP, ...) so
our projection can be compared with FanGraphs component by component against what actually happened.

Archived preseason finals use year-suffixed tokens (type=steamer_{year}, zips_{year}; see
scripts/tradevalue/tradevalue_steamerhist.py). The NEXT season's live projection is type=steamer /
type=zips. Cloudflare passes a plain tool UA and challenges a browser one. Quantile columns
(q10..q90, tt_q*) are dropped to keep the files small.

Output: data/_proj/fg/{system}_{year}_{bat|pit}.json, and actual_{year}_{bat|pit}.json (FanGraphs actual seasons
2018-2026: wOBA, Batting / BaseRunning / Fielding / Positional / Replacement runs, WAR) (scratch).
Usage: python3 scripts/research/projection/pull_fg_projections.py
"""
import json
import os
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT = os.path.join(ROOT, 'data', '_proj', 'fg')
URL = 'https://www.fangraphs.com/api/projections?type={t}&stats={s}&pos=all&team=0&players=0&lg=all'
JOBS = [('steamer', y) for y in range(2018, 2027)] + [('zips', y) for y in range(2020, 2027)] + [('steamer', 2027), ('zips', 2027)]
LIVE = 2027


def token(system, year):
    return system if year == LIVE else f'{system}_{year}'


def pull(system, year, stats):
    path = os.path.join(OUT, f'{system}_{year}_{stats}.json')
    if os.path.exists(path):
        return 'cached'
    body = subprocess.run(['curl', '-sfL', '--retry', '3', '-A', 'huronalytics-tradevalue/1.0', '-H', 'Accept: application/json',
                           URL.format(t=token(system, year), s=stats)], capture_output=True)
    if body.returncode != 0:
        return f'FAILED (curl {body.returncode})'
    rows = json.loads(body.stdout)
    if not isinstance(rows, list) or len(rows) < 100:
        return f'empty ({len(rows) if isinstance(rows, list) else type(rows).__name__})'
    keep = [{k: v for k, v in r.items() if not (k.startswith('q') and k[1:].isdigit()) and not k.startswith('tt_q')} for r in rows]
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(keep, f)
    os.replace(tmp, path)
    time.sleep(2)
    return f'{len(keep)} rows'


# ── actual seasons (the truth for baserunning, fielding and WAR in the head-to-heads) ──
ACT_URL = ('https://www.fangraphs.com/api/leaders/major-league/data?pos=all&stats={s}&lg=all&qual=0'
           '&season={y}&season1={y}&ind=0&pageitems=5000&type=8')
ACT_KEEP = ('xMLBAMID', 'PlayerName', 'PA', 'wOBA', 'Batting', 'BaseRunning', 'Fielding', 'Positional', 'Replacement',
            'Offense', 'Defense', 'WAR', 'Pos', 'IP', 'GS', 'G', 'ERA', 'FIP', 'TBF')


def pull_actual(year, stats):
    path = os.path.join(OUT, f'actual_{year}_{stats}.json')
    if os.path.exists(path) and year != 2026:
        return 'cached'
    body = subprocess.run(['curl', '-sfL', '--compressed', '--retry', '3', '-A', 'huronalytics-tradevalue/1.0', '-H', 'Accept: application/json',
                           ACT_URL.format(s=stats, y=year)], capture_output=True)
    if body.returncode != 0:
        return f'FAILED (curl {body.returncode})'
    rows = json.loads(body.stdout).get('data') or []
    if len(rows) < 100:
        return f'empty ({len(rows)})'
    keep = [{k: r.get(k) for k in ACT_KEEP if k in r} for r in rows]
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(keep, f)
    os.replace(tmp, path)
    time.sleep(2)
    return f'{len(keep)} rows'


def main_actual():
    for y in range(2018, 2027):
        print('actual', y, {s: pull_actual(y, s) for s in ('bat', 'pit')}, flush=True)


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    for system, year in JOBS:
        print(system, year, {s: pull(system, year, s) for s in ('bat', 'pit')}, flush=True)
    main_actual()
