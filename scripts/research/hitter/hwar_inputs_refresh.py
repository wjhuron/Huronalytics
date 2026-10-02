"""hwar_inputs_refresh.py: re-pull one season's team-harness and positional inputs into data/_hwar_team/.

  standings_{Y}_by_id.json   club id -> name, W, L, RS, RA, G      (MLB Stats API standings)
  innings_{Y}.json           fielding innings by player-position    (MLB Stats API, group=fielding)
  oaa_{Y}_pos{3..9}.csv      Savant OAA / range runs AT each position (numeric pos only; text pos serves HTML)

The 2026-09-14 files were pulled by hand mid-season; this makes the end-of-season refresh
repeatable. Each file is built to a temp path and moved, and each is checked for the shape the
harness reads before it replaces the old one.

Usage: python3 scripts/research/hitter/hwar_inputs_refresh.py 2026
"""
import csv
import io
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
D = os.path.join(ROOT, 'data', '_hwar_team')
STANDINGS = 'https://statsapi.mlb.com/api/v1/standings?leagueId=103,104&season={y}'
INNINGS = 'https://statsapi.mlb.com/api/v1/stats?stats=season&group=fielding&season={y}&sportId=1&playerPool=ALL&limit=10000'
OAA = ('https://baseballsavant.mlb.com/leaderboard/outs_above_average?type=Fielder&startYear={y}&endYear={y}'
       '&split=no&team=&range=year&min=1&pos={p}&roles=&viz=hide&csv=true')


def get(url):
    return subprocess.run(['curl', '-sfL', '--retry', '3', url], capture_output=True, check=True).stdout


def write(path, body):
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(body)
    os.replace(tmp, path)


def main(y):
    st = json.loads(get(STANDINGS.format(y=y)))
    clubs = {}
    for rec in st['records']:
        for t in rec['teamRecords']:
            clubs[t['team']['id']] = {'name': t['team']['name'], 'w': t['wins'], 'l': t['losses'],
                                      'rs': t['runsScored'], 'ra': t['runsAllowed'], 'g': t['wins'] + t['losses']}
    if len(clubs) != 30:
        raise RuntimeError(f'standings {y}: {len(clubs)} clubs')
    write(os.path.join(D, f'standings_{y}_by_id.json'), json.dumps(clubs).encode())
    print('standings', y, 'games', sum(c['g'] for c in clubs.values()) / 2)

    inn = get(INNINGS.format(y=y))
    s = json.loads(inn)['stats'][0]
    if len(s['splits']) != s.get('totalSplits'):
        raise RuntimeError(f'innings {y}: {len(s["splits"])} of {s.get("totalSplits")}')
    write(os.path.join(D, f'innings_{y}.json'), inn)
    print('innings', y, len(s['splits']), 'player-positions')

    for p in range(3, 10):
        body = get(OAA.format(y=y, p=p))
        rows = list(csv.DictReader(io.StringIO(body.decode('utf-8-sig'))))
        if len(rows) < 20 or 'fielding_runs_prevented' not in rows[0]:
            raise RuntimeError(f'oaa {y} pos {p}: {len(rows)} rows; Savant served something else')
        write(os.path.join(D, f'oaa_{y}_pos{p}.csv'), body)
        print('oaa', y, 'pos', p, len(rows), 'fielders')


if __name__ == '__main__':
    main(int(sys.argv[1]))
