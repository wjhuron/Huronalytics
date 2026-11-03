#!/usr/bin/env python3
"""Pull Savant's fielder start positions against one batter, by defensive team.

`/visuals/position_data?type=player_at_bat` (the Batter Positioning page)
returns one row per fielder (pos 3-9) per plate appearance: start x / y in
feet from home plate (rounded to 10; + x = right field), the runners-on
group ('0' none, '1' runner on first only, '27' other) and the infield
shaded flag. The rows carry NO game or at-bat key and are not in game
order, so they cannot be joined to count or pitcher; the only splits are
the ones the endpoint filters on. This pulls every season unfiltered and
once per opposing (defensive) team, and checks that the team pulls add up
to the unfiltered one.

Raw responses cache in data/_positioning/{id}_{season}_{opp|all}.json.
Output: data/_positioning_{id}.json, rows tagged with season and opp_id.

Usage (from the repo root):
    python3 scripts/builders/batter_positioning_pull.py --id 695578 --bats L \
        --seasons 2024 2025 2026
"""
import argparse
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(REPO, 'data', '_positioning')
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'   # Savant 403s the default
TEAMS = {108: 'LAA', 117: 'HOU', 133: 'ATH', 141: 'TOR', 144: 'ATL', 158: 'MIL',
         138: 'STL', 112: 'CHC', 109: 'ARI', 119: 'LAD', 137: 'SF', 114: 'CLE',
         136: 'SEA', 146: 'MIA', 121: 'NYM', 120: 'WSH', 110: 'BAL', 135: 'SD',
         143: 'PHI', 134: 'PIT', 140: 'TEX', 139: 'TB', 113: 'CIN', 111: 'BOS',
         115: 'COL', 118: 'KC', 116: 'DET', 142: 'MIN', 145: 'CWS', 147: 'NYY'}


def fetch(pid, bats, season, opp):
    path = os.path.join(CACHE, f'{pid}_{season}_{opp or "all"}.json')
    if not os.path.exists(path):
        url = ('https://baseballsavant.mlb.com/visuals/position_data?type=player_at_bat'
               f'&player_id={pid}&teamId=&opponent={opp or ""}&firstBase=&shift='
               f'&season={season}&attempts=25&batSide={bats}')
        out = subprocess.run(['curl', '-sfL', '--retry', '3', '-A', UA, url],
                             capture_output=True, check=True).stdout
        data = json.loads(out)
        if 'positionData' not in data:
            raise ValueError(f'{url}: no positionData key')
        tmp = path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(data, f)
        os.replace(tmp, path)
        time.sleep(0.3)
    with open(path) as f:
        return [r for r in json.load(f)['positionData'] if r.get('bat_side') == bats]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--id', type=int, required=True, help='MLB id of the batter')
    ap.add_argument('--bats', choices=('L', 'R'), required=True)
    ap.add_argument('--seasons', type=int, nargs='+', required=True)
    args = ap.parse_args()
    os.makedirs(CACHE, exist_ok=True)

    rows = []
    for season in args.seasons:
        total = fetch(args.id, args.bats, season, None)
        n_team = 0
        for opp, abbr in TEAMS.items():
            part = fetch(args.id, args.bats, season, opp)
            n_team += len(part)
            for r in part:
                rows.append({**r, 'season': season, 'opp_id': opp, 'opp': abbr})
        print(f'{season}: {len(total) // 7} PA unfiltered, {n_team // 7} PA across teams')
        if n_team != len(total):
            sys.exit(f'{season}: team pulls hold {n_team} rows against {len(total)} '
                     'unfiltered; the opponent split is not a partition.')

    path = os.path.join(REPO, 'data', f'_positioning_{args.id}.json')
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(rows, f)
    os.replace(tmp, path)
    print(f'{len(rows)} rows -> {path}')


if __name__ == '__main__':
    main()
