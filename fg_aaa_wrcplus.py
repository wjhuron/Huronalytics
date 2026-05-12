#!/usr/bin/env python3
"""fg_aaa_wrcplus.py — Scrape AAA hitter wRC+ from FanGraphs and cache it.

FanGraphs publishes the canonical AAA wRC+ using AAA-specific wOBA weights and
International League / Pacific Coast League park factors. Our own pipeline
computes wRC+ using MLB constants, which inflates ROC hitter wRC+ values by
roughly 10-20 points on average. For ROC hitter cards we want FG's number.

The minor-league leaderboard is rendered client-side, but the underlying JSON
endpoint is `https://www.fangraphs.com/api/leaders/minor-league/data`. The key
params are:
    level=1       AAA only
    stats=bat     hitters
    season=2026   current year
    org=          empty string = all 30 orgs
    type=1        standard stat type (returns wRC+ as 'wRC+' field)

Output cache: data/fg_aaa_wrcplus.json
    {
        "fetchedAt": "2026-05-11T15:42:00",
        "season": 2026,
        "players": { "<xMLBAMID>": {"wRCplus": 94, "pa": 156, "name": "Dylan Crews"} }
    }

Usage:
    python3 fg_aaa_wrcplus.py                # refresh for current year
    python3 fg_aaa_wrcplus.py --year 2026
"""

import argparse
import datetime
import json
import os
import urllib.request

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
CACHE_PATH = os.path.join(DATA_DIR, 'fg_aaa_wrcplus.json')

FG_API = 'https://www.fangraphs.com/api/leaders/minor-league/data'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/605.1.15 (KHTML, like Gecko) '
                  'Version/17.0 Safari/605.1.15',
    'Accept': 'application/json',
    'Referer': 'https://www.fangraphs.com/leaders/minor-league',
}


def fetch_aaa_hitters(year=2026, timeout=30):
    """Hit the FG minor-league API and return the raw list of rows.

    `org=` empty pulls every AAA org. `type=1` returns the standard stat
    dashboard which includes wRC+. `pageitems=5000` is well above the AAA
    population (~540) so one page is always enough.
    """
    params = (
        f'pos=all&level=1&lg=&stats=bat&qual=0&type=1'
        f'&season={year}&seasonEnd={year}'
        f'&org=&ind=0&splitTeam=false'
        f'&pageitems=5000&pagenum=1'
    )
    url = f'{FG_API}?{params}'
    req = urllib.request.Request(url, headers=HEADERS)
    body = urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8')
    rows = json.loads(body)
    if not isinstance(rows, list):
        raise RuntimeError(f'Unexpected response shape from FG: {type(rows).__name__}')
    return rows


def build_cache(year=2026):
    """Fetch and shape the cache. Drops rows without wRC+ or MLBAM id."""
    rows = fetch_aaa_hitters(year=year)
    players = {}
    for r in rows:
        mlbid = r.get('xMLBAMID')
        wrc = r.get('wRC+')
        if mlbid is None or wrc is None:
            continue
        players[str(int(mlbid))] = {
            'wRCplus': round(float(wrc)),
            'pa': int(r.get('PA') or 0),
            'name': r.get('PlayerName') or r.get('Name'),
        }
    return {
        'fetchedAt': datetime.datetime.now().isoformat(timespec='seconds'),
        'season': year,
        'players': players,
    }


def save_cache(cache, path=CACHE_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(cache, f, indent=2, sort_keys=True)
    return path


def load_cache(path=CACHE_PATH):
    """Return cached dict or None if missing/unreadable."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def is_stale(cache, max_age_hours=24):
    """True if cache is missing, malformed, or older than max_age_hours."""
    if not cache or 'fetchedAt' not in cache:
        return True
    try:
        fetched = datetime.datetime.fromisoformat(cache['fetchedAt'])
    except (ValueError, TypeError):
        return True
    age = datetime.datetime.now() - fetched
    return age.total_seconds() > max_age_hours * 3600


def refresh_if_stale(year=2026, max_age_hours=24, path=CACHE_PATH, verbose=False):
    """Refresh the cache if it's older than max_age_hours. Returns the cache
    dict (refreshed or current). Failures fall back to the existing cache."""
    cache = load_cache(path)
    if not is_stale(cache, max_age_hours):
        return cache
    try:
        if verbose:
            print(f'  FG AAA wRC+ cache stale — refreshing for season {year}')
        cache = build_cache(year=year)
        save_cache(cache, path)
        if verbose:
            print(f'  -> wrote {len(cache["players"])} AAA hitters to {path}')
    except Exception as e:
        if verbose:
            print(f'  WARNING: FG AAA wRC+ refresh failed ({type(e).__name__}: {e})')
        if cache is None:
            # No prior cache and refresh failed — return empty-but-valid shape
            return {'fetchedAt': '', 'season': year, 'players': {}}
    return cache


def main():
    parser = argparse.ArgumentParser(description='Refresh FG AAA wRC+ cache')
    parser.add_argument('--year', type=int, default=2026)
    parser.add_argument('--out', default=CACHE_PATH)
    args = parser.parse_args()

    print(f'Fetching FanGraphs AAA hitter wRC+ for {args.year}...')
    cache = build_cache(year=args.year)
    save_cache(cache, args.out)
    print(f'Wrote {len(cache["players"])} hitters to {args.out}')
    # Show a few rows for verification
    sample_ids = list(cache['players'].keys())[:5]
    print('Sample:')
    for mid in sample_ids:
        p = cache['players'][mid]
        print(f"  mlbId={mid}  {p['name']:25s}  PA={p['pa']:3d}  wRC+={p['wRCplus']}")


if __name__ == '__main__':
    main()
