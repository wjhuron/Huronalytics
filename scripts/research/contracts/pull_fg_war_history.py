"""pull_fg_war_history.py: FanGraphs actual seasons 2016-2026 (WAR, PA, IP, GS, G, Pos) with BOTH ids.

The free-agent trackers carry the FanGraphs playerid only; the contract model needs each player's
three seasons before the signing. Output: data/_fa_contracts/actual_{year}_{bat|pit}.json (scratch).
Usage: python3 scripts/research/contracts/pull_fg_war_history.py
"""
import json
import os
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT = os.path.join(ROOT, 'data', '_fa_contracts')
URL = ('https://www.fangraphs.com/api/leaders/major-league/data?pos=all&stats={s}&lg=all&qual=0'
       '&season={y}&season1={y}&ind=0&pageitems=5000&type=8')
KEEP = ('playerid', 'xMLBAMID', 'PlayerName', 'PA', 'WAR', 'Pos', 'IP', 'GS', 'G', 'SV', 'HLD')


def pull(year, stats):
    path = os.path.join(OUT, f'actual_{year}_{stats}.json')
    if os.path.exists(path):
        return 'cached'
    body = subprocess.run(['curl', '-sfL', '--compressed', '--retry', '3', '-A', 'huronalytics-tradevalue/1.0',
                           '-H', 'Accept: application/json', URL.format(s=stats, y=year)], capture_output=True)
    if body.returncode != 0:
        raise SystemExit(f'{year} {stats}: curl failed ({body.returncode})')
    rows = json.loads(body.stdout).get('data') or []
    if len(rows) < 100:
        raise SystemExit(f'{year} {stats}: only {len(rows)} rows')
    keep = [{k: r.get(k) for k in KEEP if k in r} for r in rows]
    with open(path + '.tmp', 'w') as f:
        json.dump(keep, f)
    os.replace(path + '.tmp', path)
    time.sleep(2)
    return f'{len(keep)} rows'


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    for y in range(2016, 2027):
        print(y, {s: pull(y, s) for s in ('bat', 'pit')}, flush=True)
