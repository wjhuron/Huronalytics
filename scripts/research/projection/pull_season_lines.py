"""pull_season_lines.py: MLB season lines 2000-2026 for the aging curves.

One row per player-season (the bulk endpoint returns the season-combined line), both
groups, with birthDate and position from the person hydrate. Baseball age = age on
June 30 of the season. Cached per group-season in data/_proj/; an existing file is
reused, so a re-run only pulls what is missing. The live season is always re-pulled.

Triple-A (sportId 11) lines land as aaa_lines_{group}_{Y}.json with the same fields.

Usage: python3 scripts/research/projection/pull_season_lines.py [first last]
"""
import json
import os
import subprocess
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT = os.path.join(ROOT, 'data', '_proj')
LIVE = 2026
URL = ('https://statsapi.mlb.com/api/v1/stats?stats=season&group={g}&season={y}'
       '&sportId={s}&playerPool=ALL&limit=5000&hydrate=person')
SPORTS = {1: '', 11: 'aaa_'}     # MLB, Triple-A (file prefix)


def fetch(url):
    # curl -f so an HTTP error body never lands in the cache (CLAUDE.md)
    out = subprocess.run(['curl', '-sfL', '--retry', '3', url], capture_output=True, check=True)
    return json.loads(out.stdout)


def baseball_age(birth, season):
    b = date.fromisoformat(birth)
    ref = date(season, 6, 30)
    return ref.year - b.year - ((ref.month, ref.day) < (b.month, b.day))


def pull(group, season, sport=1):
    path = os.path.join(OUT, f'{SPORTS[sport]}lines_{group}_{season}.json')
    if os.path.exists(path) and season != LIVE:
        return path, None
    d = fetch(URL.format(g=group, y=season, s=sport))
    stat = d['stats'][0]
    rows = []
    for s in stat['splits']:
        p = s['player']
        birth = p.get('birthDate')
        rows.append({'id': p['id'], 'name': p.get('fullName'), 'birth': birth,
                     'age': baseball_age(birth, season) if birth else None,
                     'pos': (p.get('primaryPosition') or {}).get('abbreviation'),
                     'numTeams': s.get('numTeams'), 'team': (s.get('team') or {}).get('id'),
                     'parent': (s.get('team') or {}).get('parentOrgId'),
                     **s['stat']})
    if len(rows) != stat.get('totalSplits'):
        raise RuntimeError(f'{group} {season}: {len(rows)} rows of {stat.get("totalSplits")}; raise limit')
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(rows, f)
    os.replace(tmp, path)
    return path, len(rows)


if __name__ == '__main__':
    first, last = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) == 3 else (2000, LIVE)
    os.makedirs(OUT, exist_ok=True)
    for y in range(first, last + 1):
        for sport in SPORTS:
            for g in ('hitting', 'pitching'):
                path, n = pull(g, y, sport)
                print(SPORTS[sport] or 'mlb_', g, y, 'cached' if n is None else f'{n} rows')
