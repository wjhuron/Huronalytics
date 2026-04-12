#!/usr/bin/env python3
"""Data fetching: Google Sheets, MLB Stats API, FanGraphs, Savant, boxscore caching."""

import gspread
import json
import os
import time as time_module
import urllib.request
import urllib.parse

from guts import scrape_guts
from pipeline_utils import (
    DATA_DIR, MLB_TEAMS, ALL_TEAMS, TEAM_ABBREV_TO_ID,
    _today_et, _fullname_to_lastfirst,
)

# ── Config ───────────────────────────────────────────────────────────────
SPREADSHEET_IDS = {
    'AL': os.environ.get('SPREADSHEET_ID_AL', '1hzAtZ_Wqi8ZuUHaGvgjJcQMU5jj5CzGXuBtjYmPOj9U'),
    'NL': os.environ.get('SPREADSHEET_ID_NL', '1DH3NI-3bSXW7dl98tdg5uFgJ4O6aWRvRB_XnVb340YE'),
}
SERVICE_ACCOUNT_FILE = os.environ.get(
    'GOOGLE_SERVICE_ACCOUNT_FILE',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'service_account.json')
)

# ── Fallback constants ───────────────────────────────────────────────────
WOBA_WEIGHTS_FALLBACK = {
    'BB': 0.692, 'HBP': 0.723, '1B': 0.884, '2B': 1.256, '3B': 1.591, 'HR': 2.048,
}
FIP_CONSTANT_FALLBACK = 3.102

# ── MLB ID lookup ────────────────────────────────────────────────────────
MANUAL_MLB_IDS = {
    'Kayfus, CJ|CLE': 692216,
}

# ── Boxscore cache paths ────────────────────────────────────────────────
BOXSCORE_CACHE_PATH = os.path.join(DATA_DIR, 'boxscore_cache.json')
MILB_BOXSCORE_CACHE_PATH = os.path.join(DATA_DIR, 'milb_boxscore_cache.json')

# ── MiLB team configuration ─────────────────────────────────────────────
MILB_TEAMS_CONFIG = {
    'ROC': {
        'sport_id': 11,
        'search_name': 'Rochester',
        'api_name': 'Rochester Red Wings',
    },
}
MILB_TEAM_NAME_TO_ABBREV = {
    'Rochester Red Wings': 'ROC',
}

# ── Full team name → abbreviation ────────────────────────────────────────
TEAM_NAME_TO_ABBREV = {
    'Arizona Diamondbacks': 'ARI', 'Athletics': 'ATH', 'Atlanta Braves': 'ATL',
    'Baltimore Orioles': 'BAL', 'Boston Red Sox': 'BOS', 'Chicago Cubs': 'CHC',
    'Chicago White Sox': 'CWS', 'Cincinnati Reds': 'CIN', 'Cleveland Guardians': 'CLE',
    'Colorado Rockies': 'COL', 'Detroit Tigers': 'DET', 'Houston Astros': 'HOU',
    'Kansas City Royals': 'KCR', 'Los Angeles Angels': 'LAA', 'Los Angeles Dodgers': 'LAD',
    'Miami Marlins': 'MIA', 'Milwaukee Brewers': 'MIL', 'Minnesota Twins': 'MIN',
    'New York Mets': 'NYM', 'New York Yankees': 'NYY', 'Philadelphia Phillies': 'PHI',
    'Pittsburgh Pirates': 'PIT', 'San Diego Padres': 'SDP', 'San Francisco Giants': 'SFG',
    'Seattle Mariners': 'SEA', 'St. Louis Cardinals': 'STL', 'Tampa Bay Rays': 'TBR',
    'Texas Rangers': 'TEX', 'Toronto Blue Jays': 'TOR', 'Washington Nationals': 'WSH',
}


# ── HTTP helpers ─────────────────────────────────────────────────────────

def _fetch_with_retry(url, headers=None, timeout=15, retries=3):
    """Fetch URL with retry logic and exponential backoff."""
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers or {})
            return urllib.request.urlopen(req, timeout=timeout).read()
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time_module.sleep(2 ** attempt)
    raise last_err


# ── FanGraphs / Savant data ─────────────────────────────────────────────

def fetch_guts_constants(year=2026):
    """Scrape wOBA weights and cFIP from FanGraphs Guts page."""
    row = scrape_guts(year)
    weights = {
        'BB': round(row['wBB'], 3),
        'HBP': round(row['wHBP'], 3),
        '1B': round(row['w1B'], 3),
        '2B': round(row['w2B'], 3),
        '3B': round(row['w3B'], 3),
        'HR': round(row['wHR'], 3),
    }
    cfip = round(row['cFIP'], 3)
    guts_extra = {
        'wOBAScale': round(row['wOBAScale'], 4),
        'lgWOBA': round(row['wOBA'], 4),
        'lgRPA': round(row['R/PA'], 4),
    }
    print(f"  FanGraphs Guts {year}: wBB={weights['BB']}, wHBP={weights['HBP']}, "
          f"w1B={weights['1B']}, w2B={weights['2B']}, w3B={weights['3B']}, "
          f"wHR={weights['HR']}, cFIP={cfip}")
    print(f"  wOBA Scale={guts_extra['wOBAScale']}, League wOBA={guts_extra['lgWOBA']}, "
          f"League R/PA={guts_extra['lgRPA']}")
    return weights, cfip, guts_extra


def fetch_sprint_speed(year=2026):
    """Fetch sprint speed leaderboard from Baseball Savant."""
    import csv
    import io
    url = (f'https://baseballsavant.mlb.com/leaderboard/sprint_speed'
           f'?type=raw&year={year}&position=&team=&min=1&csv=true')
    try:
        raw = _fetch_with_retry(url, headers={
            'User-Agent': 'Huronalytics-Leaderboard/1.0 (baseball research; https://huronalytics.com)',
            'Accept': 'text/csv',
        }, timeout=30)
        data = raw.decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(data))
        result = {}
        for row in reader:
            try:
                mlb_id = int(row.get('player_id') or 0)
                speed_str = row.get('sprint_speed') or row.get('hp_to_1b') or ''
                speed = float(speed_str) if speed_str else 0
                comp_runs = int(row.get('competitive_runs') or 0)
                if mlb_id and speed > 0:
                    result[mlb_id] = {'speed': round(speed, 1), 'competitive_runs': comp_runs}
            except (ValueError, TypeError):
                continue
        qualified = sum(1 for v in result.values() if v['competitive_runs'] >= 10)
        print(f"  Sprint speed: fetched {len(result)} players from Savant ({year}), {qualified} qualified (≥10 runs)")
        return result
    except Exception as e:
        print(f"  WARNING: Could not fetch sprint speed data ({type(e).__name__}): {e}")
        return {}


def fetch_park_factors(year=2026):
    """Scrape park factors from FanGraphs."""
    import re as _re
    url = f'https://www.fangraphs.com/guts.aspx?type=pf&teamid=0&season={year}'
    html = _fetch_with_retry(url, headers={
        'User-Agent': 'Huronalytics-Leaderboard/1.0 (baseball research; https://huronalytics.com)',
        'Accept': 'text/html',
    }, timeout=15).decode('utf-8')
    match = _re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, _re.DOTALL)
    if not match:
        raise RuntimeError('Could not find __NEXT_DATA__ on FanGraphs park factors page')
    data = json.loads(match.group(1))
    props = data.get('props', {})
    page_props = props.get('pageProps', {})
    dehydrated = page_props.get('dehydratedState', {})
    queries = dehydrated.get('queries', [])
    if not queries:
        raise RuntimeError('FanGraphs park factors page structure changed — no queries in __NEXT_DATA__')
    FG_TEAM_MAP = {
        'Angels': 'LAA', 'Orioles': 'BAL', 'Red Sox': 'BOS', 'White Sox': 'CWS',
        'Guardians': 'CLE', 'Tigers': 'DET', 'Royals': 'KCR', 'Twins': 'MIN',
        'Yankees': 'NYY', 'Athletics': 'ATH', 'Mariners': 'SEA', 'Rays': 'TBR',
        'Rangers': 'TEX', 'Blue Jays': 'TOR',
        'Diamondbacks': 'ARI', 'Braves': 'ATL', 'Cubs': 'CHC', 'Reds': 'CIN',
        'Rockies': 'COL', 'Marlins': 'MIA', 'Astros': 'HOU', 'Dodgers': 'LAD',
        'Brewers': 'MIL', 'Nationals': 'WSH', 'Mets': 'NYM', 'Phillies': 'PHI',
        'Pirates': 'PIT', 'Cardinals': 'STL', 'Padres': 'SDP', 'Giants': 'SFG',
    }
    park_factors = {}
    for q in queries:
        rows = q.get('state', {}).get('data', [])
        if isinstance(rows, list) and rows and isinstance(rows[0], dict) and 'Team' in rows[0]:
            for row in rows:
                team_name = row.get('Team')
                if not team_name:
                    continue
                abbr = FG_TEAM_MAP.get(team_name)
                basic = row.get('Basic (5yr)')
                if abbr and basic is not None:
                    park_factors[abbr] = round(basic / 100, 4)
    print(f"  Park factors: {len(park_factors)} teams fetched")
    return park_factors


# ── Google Sheets reading ────────────────────────────────────────────────

def read_sheet_with_retry(ws, max_retries=3):
    """Read a worksheet with retry logic for rate limiting (429 errors)."""
    for attempt in range(max_retries):
        try:
            return ws.get_all_values()
        except gspread.exceptions.APIError as e:
            if '429' in str(e) and attempt < max_retries - 1:
                wait = 30 * (attempt + 1)
                print(f"    Rate limited, waiting {wait}s...")
                time_module.sleep(wait)
            else:
                raise


def read_pitches_from_sheet(gc, sheet_id, extra_tabs=None):
    """Read all pitches from a single Google Sheets spreadsheet. Returns a list of pitch dicts."""
    pitches = []
    extra_tabs = extra_tabs or set()
    sh = gc.open_by_key(sheet_id)
    print(f"  {sh.title} ({len(sh.worksheets())} tabs)")
    for i, ws in enumerate(sh.worksheets()):
        tab_name = ws.title
        is_extra = tab_name in extra_tabs
        if tab_name not in MLB_TEAMS and not is_extra:
            print(f"    Skipping {tab_name} (not a team sheet)")
            continue
        print(f"    Reading {ws.title}...")
        if i > 0:
            time_module.sleep(0.5)
        rows = read_sheet_with_retry(ws)
        if not rows:
            continue
        header = rows[0]
        col_idx = {name: idx for idx, name in enumerate(header) if name}

        for row in rows[1:]:
            pitcher = row[col_idx['Pitcher']] if 'Pitcher' in col_idx else None
            if not pitcher:
                continue
            pitch = {}
            for col_name, idx in col_idx.items():
                val = row[idx] if idx < len(row) else None
                if val == '':
                    val = None
                pitch[col_name] = val
            pitch['_source'] = tab_name if is_extra else 'MLB'
            # Fallback: use raw movement if adjusted values not yet backfilled
            if pitch.get('xIndVrtBrk') is None and pitch.get('IndVertBrk') is not None:
                pitch['xIndVrtBrk'] = pitch['IndVertBrk']
            if pitch.get('xHorzBrk') is None and pitch.get('HorzBrk') is not None:
                pitch['xHorzBrk'] = pitch['HorzBrk']
            pitches.append(pitch)
    return pitches


# ── MLB ID lookup ────────────────────────────────────────────────────────

def load_mlb_id_cache(cache_path):
    if os.path.exists(cache_path):
        with open(cache_path, 'r') as f:
            return json.load(f)
    return {}


def save_mlb_id_cache(cache, cache_path):
    with open(cache_path, 'w') as f:
        json.dump(cache, f, indent=2)


def lookup_mlb_id(player_name, team_abbrev, mlb_id_cache):
    """Look up MLB player ID using the MLB Stats API, matching by name and team."""
    cache_key = f"{player_name}|{team_abbrev}"
    if cache_key in MANUAL_MLB_IDS:
        mlb_id_cache[cache_key] = MANUAL_MLB_IDS[cache_key]
        return MANUAL_MLB_IDS[cache_key]
    if cache_key in mlb_id_cache:
        return mlb_id_cache[cache_key]

    parts = player_name.split(', ')
    if len(parts) == 2:
        search_name = f"{parts[1]} {parts[0]}"
    else:
        search_name = player_name

    try:
        url = f"https://statsapi.mlb.com/api/v1/people/search?names={urllib.parse.quote(search_name)}&sportIds=1,11,12,13,14&hydrate=currentTeam&limit=25"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        team_id = TEAM_ABBREV_TO_ID.get(team_abbrev)
        people = data.get('people', [])

        if team_id and people:
            for person in people:
                ct = person.get('currentTeam', {})
                parent = ct.get('parentOrgId') or ct.get('id')
                if parent == team_id or ct.get('id') == team_id:
                    mlb_id = person['id']
                    mlb_id_cache[cache_key] = mlb_id
                    return mlb_id

        if people:
            last_name = parts[0] if len(parts) == 2 else player_name.split()[-1]
            for person in people:
                if person.get('lastName', '').lower() == last_name.lower():
                    mlb_id = person['id']
                    mlb_id_cache[cache_key] = mlb_id
                    return mlb_id
            # Do NOT fall back to people[0] — wrong-player matches are worse than no match
            print(f"  Warning: MLB ID lookup found no team/name match for {player_name} ({team_abbrev})")

    except Exception as e:
        print(f"  Warning: MLB ID lookup failed for {player_name} ({team_abbrev}): {e}")

    mlb_id_cache[cache_key] = None
    return None


# ── Boxscore fetching and caching ────────────────────────────────────────

def load_boxscore_cache():
    if os.path.exists(BOXSCORE_CACHE_PATH):
        with open(BOXSCORE_CACHE_PATH) as f:
            return json.load(f)
    return {}


def save_boxscore_cache(cache):
    with open(BOXSCORE_CACHE_PATH, 'w') as f:
        json.dump(cache, f)


def load_milb_boxscore_cache():
    if os.path.exists(MILB_BOXSCORE_CACHE_PATH):
        with open(MILB_BOXSCORE_CACHE_PATH) as f:
            return json.load(f)
    return {}


def save_milb_boxscore_cache(cache):
    with open(MILB_BOXSCORE_CACHE_PATH, 'w') as f:
        json.dump(cache, f)


def fetch_milb_game_pks_for_date(date_str, sport_id=11, team_filter=None):
    """Fetch MiLB game PKs for a given date, optionally filtered by team name substring."""
    url = f"https://statsapi.mlb.com/api/v1/schedule?date={date_str}&sportId={sport_id}&gameType=R"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        game_pks = []
        for date_data in data.get('dates', []):
            for game in date_data.get('games', []):
                if game.get('status', {}).get('abstractGameState') != 'Final':
                    continue
                if team_filter:
                    away_name = game.get('teams', {}).get('away', {}).get('team', {}).get('name', '')
                    home_name = game.get('teams', {}).get('home', {}).get('team', {}).get('name', '')
                    if team_filter not in away_name and team_filter not in home_name:
                        continue
                game_pks.append(game['gamePk'])
        return game_pks
    except Exception as e:
        print(f"    Error fetching MiLB schedule for {date_str}: {e}")
        return []


def fetch_game_pks_for_date(date_str):
    """Fetch all MLB game PKs for a given date from the schedule API."""
    url = f"https://statsapi.mlb.com/api/v1/schedule?date={date_str}&sportId=1&gameType=R,F,D,L,W"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        game_pks = []
        for date_data in data.get('dates', []):
            for game in date_data.get('games', []):
                if game.get('status', {}).get('abstractGameState') == 'Final':
                    game_pks.append(game['gamePk'])
        return game_pks
    except Exception as e:
        print(f"    Error fetching schedule for {date_str}: {e}")
        return []


def fetch_boxscore(game_pk):
    """Fetch boxscore data for a single game. Returns dict with pitcher and hitter stats."""
    url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            box = json.loads(resp.read())
    except Exception as e:
        print(f"    Error fetching boxscore for game {game_pk}: {e}")
        return None

    result = {'gamePk': game_pk, 'pitchers': [], 'hitters': []}

    for side in ['away', 'home']:
        team_data = box.get('teams', {}).get(side, {})
        team_name = team_data.get('team', {}).get('name', '')
        team_abbrev = TEAM_NAME_TO_ABBREV.get(team_name, team_name)
        pitcher_ids = team_data.get('pitchers', [])
        batter_ids = team_data.get('batters', [])
        players = team_data.get('players', {})

        for idx, pid in enumerate(pitcher_ids):
            p = players.get(f'ID{pid}', {})
            full_name = p.get('person', {}).get('fullName', '')
            stats = p.get('stats', {}).get('pitching', {})
            if not stats:
                continue
            last_first = p.get('person', {}).get('lastFirstName', '')
            if not last_first and full_name:
                last_first = _fullname_to_lastfirst(full_name)
            result['pitchers'].append({
                'name': last_first,
                'mlbId': pid,
                'team': team_abbrev,
                'g': 1,
                'gs': 1 if idx == 0 else 0,
                'outs': stats.get('outs', 0),
                'w': stats.get('wins', 0),
                'l': stats.get('losses', 0),
                'sv': stats.get('saves', 0),
                'hld': stats.get('holds', 0),
                'er': stats.get('earnedRuns', 0),
                'r': stats.get('runs', 0),
                'h': stats.get('hits', 0),
                'hr': stats.get('homeRuns', 0),
                'so': stats.get('strikeOuts', 0),
                'bb': stats.get('baseOnBalls', 0),
                'hbp': stats.get('hitByPitch', 0),
                'ibb': stats.get('intentionalWalks', 0),
                'tbf': stats.get('battersFaced', 0),
                'pitchesThrown': stats.get('pitchesThrown', 0),
                'balls': stats.get('balls', 0),
                'strikes': stats.get('strikes', 0),
                'doubles': stats.get('doubles', 0),
                'triples': stats.get('triples', 0),
                'groundOuts': stats.get('groundOuts', 0),
                'flyOuts': stats.get('flyOuts', 0),
                'popOuts': stats.get('popOuts', 0),
                'lineOuts': stats.get('lineOuts', 0),
                'airOuts': stats.get('airOuts', 0),
                'wp': stats.get('wildPitches', 0),
                'bk': stats.get('balks', 0),
                'ir': stats.get('inheritedRunners', 0),
                'irs': stats.get('inheritedRunnersScored', 0),
            })

        for pid in batter_ids:
            p = players.get(f'ID{pid}', {})
            batting = p.get('stats', {}).get('batting', {})
            if not batting or batting.get('plateAppearances', 0) == 0:
                continue
            full_name = p.get('person', {}).get('fullName', '')
            last_first = p.get('person', {}).get('lastFirstName', '')
            if not last_first and full_name:
                last_first = _fullname_to_lastfirst(full_name)
            result['hitters'].append({
                'name': last_first,
                'mlbId': pid,
                'team': team_abbrev,
                'g': 1,
                'pa': batting.get('plateAppearances', 0),
                'ab': batting.get('atBats', 0),
                'h': batting.get('hits', 0),
                'r': batting.get('runs', 0),
                'doubles': batting.get('doubles', 0),
                'triples': batting.get('triples', 0),
                'hr': batting.get('homeRuns', 0),
                'rbi': batting.get('rbi', 0),
                'tb': batting.get('totalBases', 0),
                'sb': batting.get('stolenBases', 0),
                'cs': batting.get('caughtStealing', 0),
                'bb': batting.get('baseOnBalls', 0),
                'ibb': batting.get('intentionalWalks', 0),
                'hbp': batting.get('hitByPitch', 0),
                'so': batting.get('strikeOuts', 0),
                'sacBunts': batting.get('sacBunts', 0),
                'sacFlies': batting.get('sacFlies', 0),
                'groundOuts': batting.get('groundOuts', 0),
                'flyOuts': batting.get('flyOuts', 0),
                'popOuts': batting.get('popOuts', 0),
                'lineOuts': batting.get('lineOuts', 0),
            })

    return result


def fetch_and_aggregate_milb_boxscores(game_dates, team_abbrev):
    """Fetch MiLB boxscores for a specific AAA team. Returns aggregated pitcher and hitter stats."""
    config = MILB_TEAMS_CONFIG.get(team_abbrev)
    if not config:
        return {}, {}, {}, {}

    cache = load_milb_boxscore_cache()
    new_fetches = 0
    cache_key_prefix = team_abbrev + '|'

    import datetime as _dt
    _et = _today_et()
    today = _et.isoformat()
    yesterday = (_et - _dt.timedelta(days=1)).isoformat()
    recent_dates = {today, yesterday}

    dates_to_fetch = []
    for d in sorted(game_dates):
        ck = cache_key_prefix + d
        if ck not in cache or d in recent_dates:
            dates_to_fetch.append(d)

    if dates_to_fetch:
        print(f"  Fetching MiLB boxscores for {team_abbrev}: {len(dates_to_fetch)} date(s): {dates_to_fetch}")
        for d in dates_to_fetch:
            ck = cache_key_prefix + d
            game_pks = fetch_milb_game_pks_for_date(d, sport_id=config['sport_id'],
                                                      team_filter=config['search_name'])
            cache[ck] = []
            for gpk in game_pks:
                box = fetch_boxscore(gpk)
                if box:
                    cache[ck].append(box)
                    new_fetches += 1
                time_module.sleep(0.1)
            time_module.sleep(0.5)
        save_milb_boxscore_cache(cache)
        print(f"  Fetched {new_fetches} MiLB boxscores for {team_abbrev}")
    else:
        print(f"  All {len(game_dates)} MiLB game dates for {team_abbrev} already cached")

    pitcher_agg = {}
    hitter_agg = {}
    pitcher_id_map = {}
    hitter_id_map = {}

    accepted_names = set()
    for full_name, abbrev in MILB_TEAM_NAME_TO_ABBREV.items():
        if abbrev == team_abbrev:
            accepted_names.add(full_name)

    for d in game_dates:
        ck = cache_key_prefix + d
        if ck not in cache:
            continue
        for box in cache[ck]:
            for p in box.get('pitchers', []):
                p_team = MILB_TEAM_NAME_TO_ABBREV.get(p['team'], p['team'])
                if p_team != team_abbrev:
                    continue
                key = p['name'] + '|' + team_abbrev
                if key not in pitcher_agg:
                    pitcher_agg[key] = {
                        'g': 0, 'gs': 0, 'outs': 0, 'w': 0, 'l': 0, 'sv': 0, 'hld': 0,
                        'er': 0, 'r': 0, 'h': 0, 'hr': 0, 'so': 0, 'bb': 0, 'hbp': 0, 'ibb': 0,
                        'tbf': 0, 'pitchesThrown': 0, 'balls': 0, 'strikes': 0,
                        'doubles': 0, 'triples': 0,
                        'groundOuts': 0, 'flyOuts': 0, 'popOuts': 0, 'lineOuts': 0, 'airOuts': 0,
                        'wp': 0, 'bk': 0, 'ir': 0, 'irs': 0,
                    }
                a = pitcher_agg[key]
                for k in a:
                    a[k] += p.get(k, 0)
                if p.get('mlbId'):
                    pitcher_id_map[p['mlbId']] = key

            for h in box.get('hitters', []):
                h_team = MILB_TEAM_NAME_TO_ABBREV.get(h['team'], h['team'])
                if h_team != team_abbrev:
                    continue
                key = h['name'] + '|' + team_abbrev
                if key not in hitter_agg:
                    hitter_agg[key] = {
                        'g': 0, 'pa': 0, 'ab': 0, 'h': 0, 'r': 0,
                        'doubles': 0, 'triples': 0, 'hr': 0, 'rbi': 0,
                        'tb': 0, 'sb': 0, 'cs': 0,
                        'bb': 0, 'ibb': 0, 'hbp': 0, 'so': 0,
                        'sacBunts': 0, 'sacFlies': 0,
                        'groundOuts': 0, 'flyOuts': 0, 'popOuts': 0, 'lineOuts': 0,
                    }
                a = hitter_agg[key]
                for k in a:
                    a[k] += h.get(k, 0)
                if h.get('mlbId'):
                    hitter_id_map[h['mlbId']] = key

    return pitcher_agg, hitter_agg, pitcher_id_map, hitter_id_map


def fetch_and_aggregate_boxscores(game_dates):
    """Fetch boxscores for all game dates, using cache. Returns aggregated pitcher and hitter stats."""
    cache = load_boxscore_cache()
    new_fetches = 0

    import datetime as _dt
    _et = _today_et()
    today = _et.isoformat()
    yesterday = (_et - _dt.timedelta(days=1)).isoformat()
    recent_dates = {today, yesterday}

    dates_to_fetch = []
    for d in sorted(game_dates):
        if d not in cache or d in recent_dates:
            dates_to_fetch.append(d)

    if dates_to_fetch:
        print(f"  Fetching boxscores for {len(dates_to_fetch)} new date(s): {dates_to_fetch}")
        for d in dates_to_fetch:
            game_pks = fetch_game_pks_for_date(d)
            cache[d] = []
            for gpk in game_pks:
                box = fetch_boxscore(gpk)
                if box:
                    cache[d].append(box)
                    new_fetches += 1
                time_module.sleep(0.1)
            time_module.sleep(0.5)
        save_boxscore_cache(cache)
        print(f"  Fetched {new_fetches} boxscores, cache now has {len(cache)} dates")
    else:
        print(f"  All {len(game_dates)} game dates already cached")

    pitcher_agg = {}
    hitter_agg = {}
    pitcher_id_map = {}
    hitter_id_map = {}
    seen_game_pks = set()

    for d in game_dates:
        if d not in cache:
            continue
        for box in cache[d]:
            gpk = box.get('gamePk')
            if gpk and gpk in seen_game_pks:
                continue
            if gpk:
                seen_game_pks.add(gpk)
            for p in box.get('pitchers', []):
                key = p['name'] + '|' + p['team']
                if key not in pitcher_agg:
                    pitcher_agg[key] = {
                        'g': 0, 'gs': 0, 'outs': 0, 'w': 0, 'l': 0, 'sv': 0, 'hld': 0,
                        'er': 0, 'r': 0, 'h': 0, 'hr': 0, 'so': 0, 'bb': 0, 'hbp': 0, 'ibb': 0,
                        'tbf': 0, 'pitchesThrown': 0, 'balls': 0, 'strikes': 0,
                        'doubles': 0, 'triples': 0,
                        'groundOuts': 0, 'flyOuts': 0, 'popOuts': 0, 'lineOuts': 0, 'airOuts': 0,
                        'wp': 0, 'bk': 0, 'ir': 0, 'irs': 0,
                    }
                a = pitcher_agg[key]
                for k in a:
                    a[k] += p.get(k, 0)
                if p.get('mlbId'):
                    pitcher_id_map[p['mlbId']] = key

            for h in box.get('hitters', []):
                key = h['name'] + '|' + h['team']
                if key not in hitter_agg:
                    hitter_agg[key] = {
                        'g': 0, 'pa': 0, 'ab': 0, 'h': 0, 'r': 0,
                        'doubles': 0, 'triples': 0, 'hr': 0, 'rbi': 0,
                        'tb': 0, 'sb': 0, 'cs': 0,
                        'bb': 0, 'ibb': 0, 'hbp': 0, 'so': 0,
                        'sacBunts': 0, 'sacFlies': 0,
                        'groundOuts': 0, 'flyOuts': 0, 'popOuts': 0, 'lineOuts': 0,
                    }
                a = hitter_agg[key]
                for k in a:
                    a[k] += h.get(k, 0)
                if h.get('mlbId'):
                    hitter_id_map[h['mlbId']] = key

    return pitcher_agg, hitter_agg, pitcher_id_map, hitter_id_map
