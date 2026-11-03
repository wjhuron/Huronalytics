#!/usr/bin/env python3
"""Pull Savant outfield range plays and join them to the game feed.

For every outfielder on either roster in the given batter's games, fetch
`player-services/range` for the season (every tracked OF opportunity that
fielder was credited with) and join each play to its pitch in the cached
game feed by `play_id`. The join adds the batter, the batted-ball line
(EV, LA, totalDistance, trajectory) and the pitch speed, and keys the row
the way the Sheets PitchID does (gamePk_AAA_PP, at-bat index + 1).

The plays are all of those fielders' plays, not only the batter's, so the
output doubles as a league training set for hang time:
    hang = opportunity_time - pitch flight, flight = 37.6 / velo (mph)

Raw range JSON caches per player in data/_range_cache/{id}_{season}.json;
feeds come from data/_feed_cache/{gamePk}.json.gz and are fetched with
curl -sfL when absent. Output: data/_range_plays_{season}.json.

Games come from the Sheets pitch cache (--batter) or from a Baseball Savant
search CSV (--csv, any season; game_pk and game_year columns).

Usage (from the repo root):
    python3 scripts/builders/range_plays_pull.py --batter "Wood, James" --season 2026
    python3 scripts/builders/range_plays_pull.py --csv ~/Downloads/savant_data.csv --season 2025
"""
import argparse
import gzip
import json
import os
import subprocess
import sys
import time

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO, 'data')
FEED_DIR = os.path.join(DATA, '_feed_cache')
RANGE_DIR = os.path.join(DATA, '_range_cache')
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'   # Savant 403s the default
OF_POS = {'LF', 'CF', 'RF'}


def curl_json(url):
    out = subprocess.run(['curl', '-sfL', '--retry', '3', '--retry-all-errors', '-A', UA, url],
                         capture_output=True, check=True).stdout
    return json.loads(out)


def load_feed(game_pk):
    path = os.path.join(FEED_DIR, f'{game_pk}.json.gz')
    if not os.path.exists(path):
        feed = curl_json(f'https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live')
        tmp = path + '.tmp'
        with gzip.open(tmp, 'wt') as f:
            json.dump(feed, f)
        os.replace(tmp, path)
    with gzip.open(path, 'rt') as f:
        return json.load(f)


def outfielders(feed):
    ids = set()
    for side in ('home', 'away'):
        for p in feed['liveData']['boxscore']['teams'][side]['players'].values():
            if {q.get('abbreviation') for q in p.get('allPositions', [])} & OF_POS:
                ids.add(p['person']['id'])
    return ids


def range_plays(pid, season):
    path = os.path.join(RANGE_DIR, f'{pid}_{season}.json')
    if not os.path.exists(path):
        rows = curl_json('https://baseballsavant.mlb.com/player-services/range'
                         f'?playerId={pid}&season={season}')
        if not isinstance(rows, list):
            raise ValueError(f'range for {pid}: expected a list, got {type(rows).__name__}')
        tmp = path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(rows, f)
        os.replace(tmp, path)
        time.sleep(0.3)
    with open(path) as f:
        return json.load(f)


def feed_index(feed):
    """play_id -> joined batted-ball fields for every pitch put in play."""
    gpk = feed['gamePk']
    idx = {}
    for ap in feed['liveData']['plays']['allPlays']:
        abi = ap['about']['atBatIndex']
        for e in ap['playEvents']:
            hd = e.get('hitData')
            if not e.get('isPitch') or not e.get('playId') or not hd:
                continue
            idx[e['playId']] = {
                'pitch_id': f'{gpk}_{abi + 1:03d}_{e.get("pitchNumber", 0):02d}',
                'batter_id': ap['matchup']['batter']['id'],
                'batter': ap['matchup']['batter']['fullName'],
                'ev': hd.get('launchSpeed'), 'la': hd.get('launchAngle'),
                'total_distance': hd.get('totalDistance'),
                'trajectory': hd.get('trajectory'),
                'pitch_mph': e.get('pitchData', {}).get('startSpeed'),
            }
    return idx


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--batter', help='Sheets name, "Last, First"')
    src.add_argument('--csv', help='Baseball Savant search CSV')
    ap.add_argument('--season', type=int, required=True)
    args = ap.parse_args()
    os.makedirs(RANGE_DIR, exist_ok=True)

    if args.csv:
        sv = pd.read_csv(os.path.expanduser(args.csv), low_memory=False,
                         usecols=['game_pk', 'game_year', 'bb_type'])
        sv = sv[(sv.game_year == args.season) & sv.bb_type.notna()]
        games = sorted({str(g) for g in sv.game_pk})
    else:
        pitches = pd.read_pickle(os.path.join(DATA, 'all_pitches_rs_cache.pkl'))
        games = sorted({p['PitchID'].split('_')[0] for p in pitches
                        if p.get('Batter') == args.batter and p.get('BBType')})
    if not games:
        sys.exit(f'No batted balls for the {args.season} games of this source.')
    ofs = set()
    for g in games:
        ofs |= outfielders(load_feed(int(g)))
    print(f'{len(games)} games, {len(ofs)} outfielders')

    plays = []
    for i, pid in enumerate(sorted(ofs), 1):
        for r in range_plays(pid, args.season):
            r['fielder_id'] = pid
            plays.append(r)
        if i % 25 == 0:
            print(f'  range {i}/{len(ofs)}  ({len(plays)} plays)')

    out, unjoined, indexes = [], 0, {}
    for r in plays:
        gpk = int(r['game_pk'])
        if gpk not in indexes:
            indexes[gpk] = feed_index(load_feed(gpk))
        j = indexes[gpk].get(r.get('play_id'))
        if j is None:
            unjoined += 1
            continue
        out.append({**r, **j})
    print(f'{len(plays)} range plays, {len(out)} joined to a feed pitch, '
          f'{unjoined} not joined')
    if unjoined > 0.02 * len(plays):
        sys.exit('More than 2% of range plays did not join; check the play_id key.')

    path = os.path.join(DATA, f'_range_plays_{args.season}.json')
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(out, f)
    os.replace(tmp, path)
    print(f'-> {path}')


if __name__ == '__main__':
    main()
