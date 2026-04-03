#!/usr/bin/env python3
"""Process ST 2026 pitching and hitting data from Google Sheets into JSON files for the leaderboard website."""

import gspread
from google.oauth2.service_account import Credentials
import json
import math
import os
import time as time_module
import urllib.request
import urllib.parse
from datetime import datetime, time
from collections import defaultdict

SPREADSHEET_IDS = {
    'ST': '1hNILKCGBuyQKV6KPWawgkS1cu72672TBALi8iNBbIFo',   # ST 2026 (all 30 teams + WBC)
    'AL': '1hzAtZ_Wqi8ZuUHaGvgjJcQMU5jj5CzGXuBtjYmPOj9U',   # AL 2026 (15 AL teams)
    'NL': '1DH3NI-3bSXW7dl98tdg5uFgJ4O6aWRvRB_XnVb340YE',   # NL 2026 (15 NL teams)
}
SERVICE_ACCOUNT_FILE = os.path.join(os.path.dirname(__file__), 'service_account.json')
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

METRIC_COLS = [
    'Velocity', 'Spin Rate', 'IndVertBrk', 'HorzBrk',
    'RelPosZ', 'RelPosX', 'Extension', 'ArmAngle', 'VAA', 'HAA', 'VRA', 'HRA'
]

METRIC_KEYS = {
    'Velocity': 'velocity', 'Spin Rate': 'spinRate',
    'IndVertBrk': 'indVertBrk', 'HorzBrk': 'horzBrk',
    'RelPosZ': 'relPosZ', 'RelPosX': 'relPosX',
    'Extension': 'extension', 'ArmAngle': 'armAngle',
    'VAA': 'vaa', 'HAA': 'haa',
    'VRA': 'vra', 'HRA': 'hra',
}

PITCH_STAT_KEYS = ['strikePct', 'izPct', 'swStrRate', 'swStrPct', 'cswPct', 'izWhiffPct', 'chasePct', 'gbPct', 'fpsPct']
STAT_KEYS = ['strikePct', 'izPct', 'swStrRate', 'swStrPct', 'cswPct', 'izWhiffPct', 'chasePct', 'gbPct', 'kPct', 'bbPct', 'kbbPct', 'babip', 'fpsPct', 'twoStrikeWhiffPct']

# Metrics that get percentile ranks on the pitch leaderboard (per pitch type)
PITCH_PCTL_KEYS = list(METRIC_KEYS.values()) + ['nVAA', 'nHAA'] + PITCH_STAT_KEYS + ['runValue', 'rv100', 'wOBA', 'xBA', 'xSLG', 'xwOBA']

# Pitcher stats where lower is better (invert percentile)
PITCHER_INVERT_PCTL = {'bbPct', 'babip', 'era', 'fip', 'xFIP', 'siera'}

# --- Hitter Leaderboard constants ---
SWING_DESCRIPTIONS = {'Swinging Strike', 'Foul', 'In Play'}
HITTER_STAT_KEYS = [
    # Hitter Stats tab
    'avg', 'obp', 'slg', 'ops', 'iso', 'babip', 'kPct', 'bbPct',
    # Expected Stats
    'wOBA', 'xBA', 'xSLG', 'xwOBA', 'xwOBAcon', 'xwOBAsp',
    # Batted Ball tab
    'avgEVAll', 'medEV', 'ev75', 'maxEV', 'medLA', 'hardHitPct', 'barrelPct', 'laSweetSpotPct', 'sacqPct',
    'gbPct', 'ldPct', 'fbPct', 'puPct', 'hrFbPct',
    'pullPct', 'middlePct', 'oppoPct', 'airPullPct',
    # Swing Decisions tab
    'swingPct', 'izSwingPct', 'chasePct', 'izSwChase', 'contactPct', 'izContactPct', 'whiffPct',
    # Bat Tracking tab
    'batSpeed', 'swingLength', 'attackAngle', 'attackDirection', 'swingPathTilt',
    # Count-leverage stats
    'twoStrikeWhiffPct', 'firstPitchSwingPct',
    # Batted ball distance
    'avgFbDist', 'avgHrDist',
    # Squared-Up Rate
    'squaredUpPct',
    # Sprint Speed
    'sprintSpeed',
]
# Hitter stats where lower is better (invert percentile so low value = red/high pctl)
HITTER_INVERT_PCTL = {'swingPct', 'chasePct', 'whiffPct', 'gbPct', 'kPct', 'puPct', 'twoStrikeWhiffPct'}
BUNT_BB_TYPES = {'bunt', 'bunt_grounder', 'bunt_popup', 'bunt_line_drive'}

# Team abbreviation → MLB API team ID mapping
TEAM_ABBREV_TO_ID = {
    'ARI': 109, 'ATL': 144, 'BAL': 110, 'BOS': 111, 'CHC': 112,
    'CWS': 145, 'CIN': 113, 'CLE': 114, 'COL': 115, 'DET': 116,
    'HOU': 117, 'KCR': 118, 'LAA': 108, 'LAD': 119, 'MIA': 146,
    'MIL': 158, 'MIN': 142, 'NYM': 121, 'NYY': 147, 'ATH': 133,
    'PHI': 143, 'PIT': 134, 'SDP': 135, 'SFG': 137, 'SEA': 136,
    'STL': 138, 'TBR': 139, 'TEX': 140, 'TOR': 141, 'WSH': 120,
}

# --- PA event classification ---
HIT_EVENTS = {'Single', 'Double', 'Triple', 'Home Run'}
K_EVENTS = {'Strikeout', 'Strikeout Double Play'}
BB_EVENTS = {'Walk', 'Intent Walk'}
HBP_EVENTS = {'Hit By Pitch'}
SF_EVENTS = {'Sac Fly', 'Sac Fly Double Play'}
SH_EVENTS = {'Sac Bunt'}  # sacrifice bunts — PA but not AB, not in OBP denominator
CI_EVENTS = {'Catcher Interference'}
NON_PA_EVENTS = {
    'Caught Stealing 2B', 'Caught Stealing 3B', 'Caught Stealing Home',
    'Pickoff 1B', 'Pickoff 2B', 'Pickoff 3B',
    'Pickoff Caught Stealing 2B', 'Pickoff Caught Stealing 3B',
    'Pickoff Caught Stealing Home',
    'Runner Out', 'Wild Pitch', 'Game Advisory',
}

# 30 MLB team abbreviations (matching spreadsheet tab names)
MLB_TEAMS = {
    'ARI', 'ATH', 'ATL', 'BAL', 'BOS', 'CHC', 'CIN', 'CLE', 'COL', 'CWS',
    'DET', 'HOU', 'KCR', 'LAA', 'LAD', 'MIA', 'MIL', 'MIN', 'NYM', 'NYY',
    'PHI', 'PIT', 'SDP', 'SEA', 'SFG', 'STL', 'TBR', 'TEX', 'TOR', 'WSH',
    'WBC',
}

# Minor league / AAA teams (included in data but excluded from MLB percentile pool)
AAA_TEAMS = {'ROC'}
ALL_TEAMS = MLB_TEAMS | AAA_TEAMS

# --- wOBA weights and FIP constant — pulled live from FanGraphs Guts page ---
WOBA_WEIGHTS = None  # set at runtime by fetch_guts_constants()
FIP_CONSTANT = None  # set at runtime by fetch_guts_constants()
GUTS_EXTRA = None    # wOBAScale, lgWOBA, lgRPA — set at runtime


def fetch_guts_constants(year=2026):
    """Scrape wOBA weights and cFIP from FanGraphs Guts page."""
    import re as _re
    url = 'https://www.fangraphs.com/tools/guts'
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15',
        'Accept': 'text/html',
    })
    html = urllib.request.urlopen(req, timeout=15).read().decode('utf-8')
    match = _re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, _re.DOTALL)
    if not match:
        raise RuntimeError('Could not find __NEXT_DATA__ on FanGraphs Guts page')
    data = json.loads(match.group(1))
    queries = data['props']['pageProps']['dehydratedState']['queries']
    for q in queries:
        rows = q.get('state', {}).get('data', [])
        if isinstance(rows, list) and rows and isinstance(rows[0], dict) and 'Season' in rows[0]:
            for row in rows:
                if row.get('Season') == year:
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
    raise RuntimeError(f'Could not find {year} row in FanGraphs Guts data')


def fetch_sprint_speed(year=2026):
    """Fetch sprint speed leaderboard from Baseball Savant.
    Returns dict mapping MLB player ID (int) → sprint speed (float, ft/s)."""
    import csv
    import io
    url = (f'https://baseballsavant.mlb.com/leaderboard/sprint_speed'
           f'?type=raw&year={year}&position=&team=&min=10&csv=true')
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15',
        'Accept': 'text/csv',
    })
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        data = resp.read().decode('utf-8-sig')  # Handle BOM
        reader = csv.DictReader(io.StringIO(data))
        result = {}
        for row in reader:
            try:
                mlb_id = int(row.get('player_id') or 0)
                speed_str = row.get('sprint_speed') or row.get('hp_to_1b') or ''
                speed = float(speed_str) if speed_str else 0
                if mlb_id and speed > 0:
                    result[mlb_id] = round(speed, 1)
            except (ValueError, TypeError):
                continue
        print(f"  Sprint speed: fetched {len(result)} players from Savant ({year})")
        return result
    except Exception as e:
        print(f"  WARNING: Could not fetch sprint speed data: {e}")
        # Try previous year as fallback
        if year > 2024:
            print(f"  Trying {year - 1} as fallback...")
            return fetch_sprint_speed(year - 1)
        return {}


def fetch_park_factors(year=2026):
    """Scrape park factors from FanGraphs, return dict of team abbrev → factor (divided by 100)."""
    import re as _re
    url = f'https://www.fangraphs.com/guts.aspx?type=pf&teamid=0&season={year}'
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15',
        'Accept': 'text/html',
    })
    html = urllib.request.urlopen(req, timeout=15).read().decode('utf-8')
    match = _re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, _re.DOTALL)
    if not match:
        raise RuntimeError('Could not find __NEXT_DATA__ on FanGraphs park factors page')
    data = json.loads(match.group(1))
    # Map FanGraphs team names to our abbreviations
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
    queries = data['props']['pageProps']['dehydratedState']['queries']
    park_factors = {}
    for q in queries:
        rows = q.get('state', {}).get('data', [])
        if isinstance(rows, list) and rows and isinstance(rows[0], dict) and 'Team' in rows[0]:
            for row in rows:
                abbr = FG_TEAM_MAP.get(row['Team'])
                if abbr:
                    park_factors[abbr] = round(row['Basic (5yr)'] / 100, 4)
    print(f"  Park factors: {len(park_factors)} teams fetched")
    return park_factors


PARK_FACTORS = None  # set at runtime by fetch_park_factors()

WOBA_WEIGHTS_FALLBACK = {
    'BB': 0.705, 'HBP': 0.737, '1B': 0.905, '2B': 1.291, '3B': 1.639, 'HR': 2.116,
}
FIP_CONSTANT_FALLBACK = 3.213

# Strike zone: ball radius adjustment for "any part of ball touches zone"
BALL_RADIUS_FT = 1.45 / 12  # 1.45 inches = ~0.121 ft
ZONE_HALF_WIDTH = 0.83       # half plate (8.5") + ball radius (1.45") in feet


def compute_in_zone(p):
    """Compute InZone from PlateX, PlateZ, SzTop, SzBot with ball-radius adjustment."""
    px = safe_float(p.get('PlateX'))
    pz = safe_float(p.get('PlateZ'))
    top = safe_float(p.get('SzTop'))
    bot = safe_float(p.get('SzBot'))
    if any(v is None for v in [px, pz, top, bot]):
        return None
    if abs(px) <= ZONE_HALF_WIDTH and (bot - BALL_RADIUS_FT) <= pz <= (top + BALL_RADIUS_FT):
        return 'Yes'
    return 'No'


def break_tilt_to_minutes(val):
    """Convert a time value (clock notation) to total minutes (0-719).
    Handles time objects, datetime objects, and string formats like '12:23' or '1:17'."""
    if val is None:
        return None
    if isinstance(val, time):
        return val.hour * 60 + val.minute
    if isinstance(val, datetime):
        return val.hour * 60 + val.minute
    if isinstance(val, str) and ':' in val:
        try:
            parts = val.strip().split(':')
            h, m = int(parts[0]), int(parts[1])
            return h * 60 + m
        except (ValueError, IndexError):
            return None
    return None


def circular_mean_minutes(minute_values):
    """Circular mean for clock-face values (0-719 minutes = 12 hours)."""
    if not minute_values:
        return None
    angles = [m / 720.0 * 2 * math.pi for m in minute_values]
    sin_avg = sum(math.sin(a) for a in angles) / len(angles)
    cos_avg = sum(math.cos(a) for a in angles) / len(angles)
    avg_angle = math.atan2(sin_avg, cos_avg)
    if avg_angle < 0:
        avg_angle += 2 * math.pi
    avg_minutes = avg_angle / (2 * math.pi) * 720
    return round(avg_minutes)


def minutes_to_tilt_display(total_minutes):
    """Convert minutes back to H:MM display format."""
    if total_minutes is None:
        return None
    h = int(total_minutes) // 60
    m = int(total_minutes) % 60
    if h == 0:
        h = 12
    return f"{h}:{m:02d}"


def safe_float(val):
    """Convert a value to float, returning None if not possible."""
    if val is None or val == '':
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def safe_int(val):
    """Convert a value to int, returning None if not possible."""
    if val is None or val == '':
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def normalize_date(val):
    """Normalize a date value to YYYY-MM-DD string."""
    if val is None or val == '':
        return None
    if isinstance(val, datetime):
        return val.strftime('%Y-%m-%d')
    s = str(val).strip()
    # ISO format: 2026-03-05 or 2026-03-05T...
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        return s[:10]
    # US format: M/D/YYYY or MM/DD/YYYY
    parts = s.split('/')
    if len(parts) == 3:
        try:
            m, d, y = int(parts[0]), int(parts[1]), int(parts[2])
            return f"{y:04d}-{m:02d}-{d:02d}"
        except ValueError:
            pass
    return None


def avg(values):
    """Average a list of numbers, ignoring None."""
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def compute_expected_stats(pitches):
    """Compute wOBA, xBA, xSLG, xwOBA, xwOBAcon from pitch-level data.

    wOBA uses FanGraphs Guts linear weights applied to actual outcomes.
    xBA/xSLG/xwOBA use Statcast per-pitch expected values from the spreadsheet.

    wOBA     = (wBB×uBB + wHBP×HBP + w1B×1B + w2B×2B + w3B×3B + wHR×HR) / (AB + uBB + SF + HBP)
    xBA      = sum(xBA per BIP) / AB
    xSLG     = sum(xSLG per BIP) / AB
    xwOBA    = sum(xwOBA per PA) / (PA - IBB)
    xwOBAcon = sum(xwOBA per BIP) / count(BIPs)  — contact only, no K/BB/HBP
    """
    ab = 0
    ubb = 0
    hbp_count = 0
    sf = 0
    singles = 0
    doubles = 0
    triples = 0
    hr = 0
    xba_sum = 0.0
    xslg_sum = 0.0
    xwoba_sum = 0.0
    xwoba_denom = 0
    xwobacon_sum = 0.0
    xwobacon_denom = 0

    for p in pitches:
        event = p.get('Event')
        if not event or event in NON_PA_EVENTS:
            continue

        if event == 'Intent Walk':
            continue  # IBB excluded

        # xwOBA: every non-IBB PA event contributes
        xwoba_val = safe_float(p.get('xwOBA'))
        if xwoba_val is not None:
            xwoba_sum += xwoba_val
            xwoba_denom += 1

        # Track wOBA components
        if event in BB_EVENTS:
            ubb += 1
            continue
        elif event in HBP_EVENTS:
            hbp_count += 1
            continue
        elif event in SF_EVENTS:
            sf += 1
            # Sac flies are BIPs — accumulate for xwOBAcon
            xwobacon_sf = safe_float(p.get('xwOBA'))
            if xwobacon_sf is not None:
                xwobacon_sum += xwobacon_sf
                xwobacon_denom += 1
            continue
        elif event in SH_EVENTS or event in CI_EVENTS:
            continue

        # Regular AB outcome
        ab += 1
        if event == 'Single':
            singles += 1
        elif event == 'Double':
            doubles += 1
        elif event == 'Triple':
            triples += 1
        elif event == 'Home Run':
            hr += 1

        xba_val = safe_float(p.get('xBA'))
        xslg_val = safe_float(p.get('xSLG'))
        if xba_val is not None:
            xba_sum += xba_val
        if xslg_val is not None:
            xslg_sum += xslg_val

        # xwOBAcon: only BIPs (exclude strikeouts from AB outcomes)
        if event not in K_EVENTS:
            xwobacon_val = safe_float(p.get('xwOBA'))
            if xwobacon_val is not None:
                xwobacon_sum += xwobacon_val
                xwobacon_denom += 1

    result = {}

    # wOBA from Guts weights
    woba_denom = ab + ubb + sf + hbp_count
    if woba_denom > 0 and WOBA_WEIGHTS:
        woba_num = (WOBA_WEIGHTS['BB'] * ubb + WOBA_WEIGHTS['HBP'] * hbp_count +
                    WOBA_WEIGHTS['1B'] * singles + WOBA_WEIGHTS['2B'] * doubles +
                    WOBA_WEIGHTS['3B'] * triples + WOBA_WEIGHTS['HR'] * hr)
        result['wOBA'] = round(woba_num / woba_denom, 3)
    else:
        result['wOBA'] = None

    result['xBA'] = round(xba_sum / ab, 3) if ab > 0 else None
    result['xSLG'] = round(xslg_sum / ab, 3) if ab > 0 else None
    result['xwOBA'] = round(xwoba_sum / xwoba_denom, 3) if xwoba_denom > 0 else None
    result['xwOBAcon'] = round(xwobacon_sum / xwobacon_denom, 3) if xwobacon_denom > 0 else None
    return result


def compute_stats(pitches):
    """Compute IZ%, Whiff%, CSW%, Chase%, GB%, K%, BB%, K-BB%, BABIP from a list of pitch dicts."""
    total = len(pitches)
    if total == 0:
        empty = {k: None for k in STAT_KEYS}
        empty['nSwings'] = 0
        empty['nBip'] = 0
        empty['pa'] = 0
        return empty

    iz = sum(1 for p in pitches if p.get('InZone') == 'Yes')
    swings = sum(1 for p in pitches if p['Description'] in SWING_DESCRIPTIONS)
    whiffs = sum(1 for p in pitches if p['Description'] == 'Swinging Strike')
    csw = sum(1 for p in pitches if p['Description'] in ('Called Strike', 'Swinging Strike'))

    iz_pitches = [p for p in pitches if p.get('InZone') == 'Yes']
    iz_swings = sum(1 for p in iz_pitches if p['Description'] in SWING_DESCRIPTIONS)
    iz_whiffs = sum(1 for p in iz_pitches if p['Description'] == 'Swinging Strike')
    ooz = [p for p in pitches if p.get('InZone') == 'No']
    ooz_swung = sum(1 for p in ooz if p['Description'] in ('Swinging Strike', 'In Play', 'Foul'))

    # GB% — exclude bunts from denominator
    bip = [p for p in pitches if p.get('BBType') is not None and p.get('BBType') not in BUNT_BB_TYPES]
    gb = sum(1 for p in bip if p.get('BBType') == 'ground_ball')

    # K%, BB%, BABIP — count true plate appearances (exclude non-PA events)
    pa_pitches = [p for p in pitches if p.get('Event') and p['Event'] not in NON_PA_EVENTS]
    n_pa = len(pa_pitches)
    n_h = sum(1 for p in pa_pitches if p['Event'] in HIT_EVENTS)
    n_hr = sum(1 for p in pa_pitches if p['Event'] == 'Home Run')
    n_k = sum(1 for p in pa_pitches if p['Event'] in K_EVENTS)
    n_bb_all = sum(1 for p in pa_pitches if p['Event'] in BB_EVENTS)
    n_ibb = sum(1 for p in pa_pitches if p['Event'] == 'Intent Walk')
    n_bb = n_bb_all - n_ibb  # BB% excludes IBB (matches FanGraphs methodology)
    n_hbp = sum(1 for p in pa_pitches if p['Event'] in HBP_EVENTS)
    n_sf = sum(1 for p in pa_pitches if p['Event'] in SF_EVENTS)
    n_sh = sum(1 for p in pa_pitches if p['Event'] in SH_EVENTS)
    n_ci = sum(1 for p in pa_pitches if p['Event'] in CI_EVENTS)
    n_ab = n_pa - n_bb_all - n_hbp - n_sf - n_sh - n_ci  # AB uses all BB (including IBB)
    k_pct = n_k / n_pa if n_pa > 0 else None
    bb_pct = n_bb / n_pa if n_pa > 0 else None  # excludes IBB
    kbb_pct = round(k_pct - bb_pct, 4) if k_pct is not None and bb_pct is not None else None

    # BABIP = (H - HR) / (AB - K - HR + SF)
    babip_denom = n_ab - n_k - n_hr + n_sf
    babip = round((n_h - n_hr) / babip_denom, 3) if babip_denom > 0 else None

    # Strike% — total strikes / total pitches
    BALL_DESCRIPTIONS = {'Ball', 'Intent Ball', 'Hit By Pitch', 'Pitchout'}
    n_strikes = sum(1 for p in pitches if p.get('Description') not in BALL_DESCRIPTIONS)
    strike_pct = n_strikes / total if total > 0 else None

    # Run Value (RunExp) — sum of delta_pitcher_run_exp
    # Positive = good for pitcher, negative = bad
    rv_values = [safe_float(p.get('RunExp')) for p in pitches]
    rv_values = [v for v in rv_values if v is not None]
    run_value = round(sum(rv_values), 1) if rv_values else None

    # FPS% — first pitch strike rate (count == "0-0")
    # A strike = called strike, swinging strike, foul, or in play
    first_pitches = [p for p in pitches if p.get('Count') == '0-0']
    fps_strikes = sum(1 for p in first_pitches
                      if p.get('Description') in ('Called Strike', 'Swinging Strike', 'Foul', 'In Play'))
    fps_pct = fps_strikes / len(first_pitches) if first_pitches else None

    # 2-Strike Whiff% — whiff rate on pitches with 2 strikes
    two_strike_pitches = [p for p in pitches if p.get('Count') and p['Count'].split('-')[1] == '2']
    two_strike_swings = sum(1 for p in two_strike_pitches if p['Description'] in SWING_DESCRIPTIONS)
    two_strike_whiffs = sum(1 for p in two_strike_pitches if p['Description'] == 'Swinging Strike')
    two_strike_whiff_pct = two_strike_whiffs / two_strike_swings if two_strike_swings > 0 else None

    return {
        'pa': n_pa,
        'strikePct': strike_pct,
        'izPct': iz / total,
        'swStrRate': whiffs / total if total > 0 else None,
        'swStrPct': whiffs / swings if swings > 0 else None,
        'cswPct': csw / total,
        'izWhiffPct': iz_whiffs / iz_swings if iz_swings > 0 else None,
        'chasePct': ooz_swung / len(ooz) if ooz else None,
        'gbPct': gb / len(bip) if bip else None,
        'nSwings': swings,
        'nBip': len(bip),
        'kPct': k_pct,
        'bbPct': bb_pct,
        'kbbPct': kbb_pct,
        'babip': babip,
        'fpsPct': fps_pct,
        'twoStrikeWhiffPct': two_strike_whiff_pct,
        'runValue': run_value,
    }


def round_metric(key, value):
    """Round a metric value according to its type."""
    if value is None:
        return None
    if key == 'Spin Rate':
        return round(value)
    if key in ('VAA', 'HAA', 'VRA', 'HRA'):
        return round(value, 2)
    return round(value, 1)


def median(values):
    """Compute median, ignoring None values."""
    nums = sorted(v for v in values if v is not None)
    if not nums:
        return None
    n = len(nums)
    if n % 2 == 1:
        return nums[n // 2]
    return (nums[n // 2 - 1] + nums[n // 2]) / 2


def is_barrel(ev, la):
    """Statcast barrel definition from baseballr code_barrel (EV >= 98 per MLB glossary).
    Four conditions: LA<=50, EV>=98, EV*1.5-LA>=117, EV+LA>=123."""
    if ev is None or la is None:
        return False
    return (la <= 50 and ev >= 98 and
            ev * 1.5 - la >= 117 and
            ev + la >= 123)


def compute_pitcher_batted_ball(pitches):
    """Compute batted-ball-against stats for a pitcher: Avg EV, Hard-Hit%, Barrel%, LD%, FB%, PU%."""
    bip = [p for p in pitches if p.get('BBType') is not None and p.get('BBType') not in BUNT_BB_TYPES]
    n_bip = len(bip)
    if n_bip == 0:
        return {
            'avgEVAgainst': None, 'maxEVAgainst': None,
            'hardHitPct': None, 'barrelPctAgainst': None,
            'ldPct': None, 'fbPct': None, 'puPct': None,
            'hrFbPct': None,
        }

    # Exit velo stats (all BIP, not just positive LA)
    ev_vals = [safe_float(p.get('ExitVelo')) for p in bip]
    ev_valid = [v for v in ev_vals if v is not None]
    avg_ev = round(sum(ev_valid) / len(ev_valid), 1) if ev_valid else None
    max_ev = round(max(ev_valid), 1) if ev_valid else None

    # Hard-hit: EV >= 95 mph
    hard_hit = sum(1 for v in ev_valid if v >= 95)
    hard_hit_pct = hard_hit / n_bip if n_bip > 0 else None

    # Barrel rate — use Barrel column (1-6 scale, 6=barrel) if available, else formula
    has_barrel_col = any(str(p.get('Barrel', '')).strip() != '' for p in bip)
    if has_barrel_col:
        barrels = sum(1 for p in bip if str(p.get('Barrel', '')).strip() == '6')
    else:
        ev_la_pairs = [(safe_float(p.get('ExitVelo')), safe_float(p.get('LaunchAngle')))
                       for p in bip
                       if safe_float(p.get('ExitVelo')) is not None
                       and safe_float(p.get('LaunchAngle')) is not None]
        barrels = sum(1 for ev, la in ev_la_pairs if is_barrel(ev, la))
    barrel_pct = barrels / n_bip if n_bip > 0 else None

    # Batted ball type breakdown
    ld = sum(1 for p in bip if p.get('BBType') == 'line_drive')
    fb = sum(1 for p in bip if p.get('BBType') == 'fly_ball')
    pu = sum(1 for p in bip if p.get('BBType') == 'popup')

    # HR/FB ratio — denominator = fly balls + popups + line drive HRs
    n_hr_bb = sum(1 for p in bip if p.get('Event') == 'Home Run')
    ld_hr = sum(1 for p in bip if p.get('Event') == 'Home Run' and p.get('BBType') == 'line_drive')
    fb_for_hrfb = fb + pu + ld_hr
    hr_fb_pct = round(n_hr_bb / fb_for_hrfb, 4) if fb_for_hrfb > 0 else None

    return {
        'avgEVAgainst': avg_ev,
        'maxEVAgainst': max_ev,
        'hardHitPct': round(hard_hit_pct, 4) if hard_hit_pct is not None else None,
        'barrelPctAgainst': round(barrel_pct, 4) if barrel_pct is not None else None,
        'ldPct': round(ld / n_bip, 4) if n_bip > 0 else None,
        'fbPct': round(fb / n_bip, 4) if n_bip > 0 else None,
        'puPct': round(pu / n_bip, 4) if n_bip > 0 else None,
        'hrFbPct': hr_fb_pct,
    }


PITCHER_BB_KEYS = ['avgEVAgainst', 'maxEVAgainst', 'hardHitPct', 'barrelPctAgainst', 'ldPct', 'fbPct', 'puPct', 'hrFbPct']
PITCHER_BB_INVERT = {'avgEVAgainst', 'maxEVAgainst', 'hardHitPct', 'barrelPctAgainst', 'hrFbPct'}


def spray_angle(hc_x, hc_y):
    """Compute spray angle in degrees. 0 = center, negative = left field, positive = right field."""
    if hc_x is None or hc_y is None:
        return None
    hp_x, hp_y = 125.42, 198.27
    dx = hc_x - hp_x
    dy = hp_y - hc_y
    if dy <= 0:
        return None
    return math.atan2(dx, dy) * (180 / math.pi)


def spray_direction(angle, stands):
    """Classify as 'pull', 'center', or 'oppo' based on spray angle and batter side."""
    if angle is None or not stands:
        return None
    if stands == 'R':
        if angle < -15:
            return 'pull'
        elif angle > 15:
            return 'oppo'
        else:
            return 'center'
    else:  # L
        if angle > 15:
            return 'pull'
        elif angle < -15:
            return 'oppo'
        else:
            return 'center'


def compute_hitter_stats(pitches):
    """Compute hitter stats from a list of pitch dicts for all three hitter leaderboard tabs:
    Hitter Stats (AVG/OBP/SLG/OPS), Batted Ball Metrics, and Swing Decisions."""
    total = len(pitches)
    if total == 0:
        empty = {k: None for k in HITTER_STAT_KEYS}
        empty.update({'pa': 0, 'nSwings': 0, 'nBip': 0, 'nCompSwings': 0,
                      'doubles': 0, 'triples': 0, 'hr': 0, 'xbh': 0})
        return empty

    # === PA and batting event counts ===
    # PA = pitches with an Event, excluding non-PA events (pickoffs, caught stealings, etc.)
    pa_pitches = [p for p in pitches if p.get('Event') and p['Event'] not in NON_PA_EVENTS]
    n_pa = len(pa_pitches)

    n_h = sum(1 for p in pa_pitches if p['Event'] in HIT_EVENTS)
    n_2b = sum(1 for p in pa_pitches if p['Event'] == 'Double')
    n_3b = sum(1 for p in pa_pitches if p['Event'] == 'Triple')
    n_hr = sum(1 for p in pa_pitches if p['Event'] == 'Home Run')
    n_1b = n_h - n_2b - n_3b - n_hr
    n_bb_all = sum(1 for p in pa_pitches if p['Event'] in BB_EVENTS)
    n_ibb = sum(1 for p in pa_pitches if p['Event'] == 'Intent Walk')
    n_bb = n_bb_all - n_ibb  # BB% excludes IBB (matches FanGraphs methodology)
    n_hbp = sum(1 for p in pa_pitches if p['Event'] in HBP_EVENTS)
    n_sf = sum(1 for p in pa_pitches if p['Event'] in SF_EVENTS)
    n_sh = sum(1 for p in pa_pitches if p['Event'] in SH_EVENTS)
    n_ci = sum(1 for p in pa_pitches if p['Event'] in CI_EVENTS)
    n_k = sum(1 for p in pa_pitches if p['Event'] in K_EVENTS)

    # AB = PA - all BB (including IBB) - HBP - SF - SH - CI
    n_ab = n_pa - n_bb_all - n_hbp - n_sf - n_sh - n_ci

    # === Traditional batting stats ===
    batting_avg = round(n_h / n_ab, 3) if n_ab > 0 else None
    obp_denom = n_ab + n_bb_all + n_hbp + n_sf  # OBP uses all BB including IBB
    obp = round((n_h + n_bb_all + n_hbp) / obp_denom, 3) if obp_denom > 0 else None
    tb = n_1b + 2 * n_2b + 3 * n_3b + 4 * n_hr
    slg = round(tb / n_ab, 3) if n_ab > 0 else None
    ops = round(obp + slg, 3) if obp is not None and slg is not None else None
    xbh = n_2b + n_3b + n_hr

    # K% and BB% (per PA — BB% excludes IBB)
    k_pct = n_k / n_pa if n_pa > 0 else None
    bb_pct = n_bb / n_pa if n_pa > 0 else None  # excludes IBB

    # ISO = SLG - AVG
    iso = round(slg - batting_avg, 3) if slg is not None and batting_avg is not None else None

    # BABIP = (H - HR) / (AB - K - HR + SF)
    babip_denom = n_ab - n_k - n_hr + n_sf
    babip = round((n_h - n_hr) / babip_denom, 3) if babip_denom > 0 else None

    # === Swing metrics ===
    n_swings = sum(1 for p in pitches if p['Description'] in SWING_DESCRIPTIONS)
    whiffs = sum(1 for p in pitches if p['Description'] == 'Swinging Strike')

    # In-zone / Out-of-zone
    iz_pitches = [p for p in pitches if p.get('InZone') == 'Yes']
    ooz_pitches = [p for p in pitches if p.get('InZone') == 'No']
    iz_swings = sum(1 for p in iz_pitches if p['Description'] in SWING_DESCRIPTIONS)
    iz_whiffs = sum(1 for p in iz_pitches if p['Description'] == 'Swinging Strike')
    ooz_swings = sum(1 for p in ooz_pitches if p['Description'] in SWING_DESCRIPTIONS)

    iz_swing_pct = iz_swings / len(iz_pitches) if iz_pitches else None
    chase_pct = ooz_swings / len(ooz_pitches) if ooz_pitches else None

    # Contact%: overall contact rate — (Foul + In Play) / Swings
    contact = sum(1 for p in pitches if p['Description'] in ('Foul', 'In Play'))
    contact_pct = contact / n_swings if n_swings > 0 else None

    # IZCT%: in-zone contact rate — (IZ Foul + IZ non-bunt In Play) / IZ swings (excl bunt BIP)
    iz_swings_non_bunt = sum(1 for p in iz_pitches
                             if p['Description'] in SWING_DESCRIPTIONS
                             and p.get('BBType') not in BUNT_BB_TYPES)
    iz_contact = sum(1 for p in iz_pitches
                     if p['Description'] in ('Foul', 'In Play')
                     and p.get('BBType') not in BUNT_BB_TYPES)
    iz_contact_pct = iz_contact / iz_swings_non_bunt if iz_swings_non_bunt > 0 else None

    # === Batted ball metrics (excluding bunts) ===
    bip = [p for p in pitches if p.get('BBType') is not None and p.get('BBType') not in BUNT_BB_TYPES]
    n_bip = len(bip)
    gb = sum(1 for p in bip if p.get('BBType') == 'ground_ball')
    ld = sum(1 for p in bip if p.get('BBType') == 'line_drive')
    fb = sum(1 for p in bip if p.get('BBType') == 'fly_ball')
    pu = sum(1 for p in bip if p.get('BBType') == 'popup')

    # Exit Velocity & Launch Angle (only LA > 0 for EV stats)
    ev_la_pos = [(safe_float(p.get('ExitVelo')), safe_float(p.get('LaunchAngle')))
                 for p in bip
                 if safe_float(p.get('LaunchAngle')) is not None and safe_float(p.get('LaunchAngle')) > 0
                 and safe_float(p.get('ExitVelo')) is not None]
    evs_pos = [ev for ev, la in ev_la_pos]

    # EV75: average of top 25% hardest hit balls (75th percentile and above, LA > 0)
    ev75 = None
    if evs_pos:
        sorted_evs = sorted(evs_pos, reverse=True)
        top_quarter = sorted_evs[:max(1, len(sorted_evs) // 4)]
        ev75 = round(sum(top_quarter) / len(top_quarter), 1)

    # Barrels — use Barrel column (1-6 scale, 6=barrel) if available, else formula
    has_barrel_col = any(str(p.get('Barrel', '')).strip() != '' for p in bip)
    if has_barrel_col:
        barrels = sum(1 for p in bip if str(p.get('Barrel', '')).strip() == '6')
    else:
        ev_la_all = [(safe_float(p.get('ExitVelo')), safe_float(p.get('LaunchAngle')))
                     for p in bip
                     if safe_float(p.get('ExitVelo')) is not None
                     and safe_float(p.get('LaunchAngle')) is not None]
        barrels = sum(1 for ev, la in ev_la_all if is_barrel(ev, la))

    # Median launch angle on ALL batted balls
    all_la = [safe_float(p.get('LaunchAngle')) for p in bip
              if safe_float(p.get('LaunchAngle')) is not None]

    # Spray stats (Pull%, Middle%, Oppo%, AirPull%)
    spray_data = []
    for p in bip:
        hc_x = safe_float(p.get('HC_X'))
        hc_y = safe_float(p.get('HC_Y'))
        angle = spray_angle(hc_x, hc_y)
        direction = spray_direction(angle, p.get('Bats'))
        if direction:
            spray_data.append((direction, p.get('BBType')))
    n_spray = len(spray_data)
    pull = sum(1 for d, _ in spray_data if d == 'pull')
    center = sum(1 for d, _ in spray_data if d == 'center')
    oppo = sum(1 for d, _ in spray_data if d == 'oppo')
    air_pull = sum(1 for d, bb in spray_data if d == 'pull' and bb in ('line_drive', 'fly_ball', 'popup'))

    # Hard-hit: EV >= 95 mph
    ev_valid = [safe_float(p.get('ExitVelo')) for p in bip]
    ev_valid = [v for v in ev_valid if v is not None]
    hard_hit = sum(1 for v in ev_valid if v >= 95)
    hard_hit_pct = hard_hit / n_bip if n_bip > 0 else None

    # LA Sweet-Spot%: launch angle between 8° and 32°
    sweet_spot = sum(1 for la in all_la if 8 <= la <= 32)
    la_sweet_spot_pct = sweet_spot / len(all_la) if all_la else None

    # HR/FB ratio for hitters — denominator = fly balls + popups + line drive HRs
    n_hr_fb = sum(1 for p in bip if p.get('Event') == 'Home Run')
    ld_hr = sum(1 for p in bip if p.get('Event') == 'Home Run' and p.get('BBType') == 'line_drive')
    fb_for_hrfb = fb + pu + ld_hr
    hr_fb_pct = round(n_hr_fb / fb_for_hrfb, 4) if fb_for_hrfb > 0 else None

    # === Count-leverage stats ===
    # 2-Strike Whiff%: whiff rate when hitter has 2 strikes
    two_strike_pitches = [p for p in pitches if p.get('Count') and p['Count'].split('-')[1] == '2']
    two_strike_swings = sum(1 for p in two_strike_pitches if p['Description'] in SWING_DESCRIPTIONS)
    two_strike_whiffs = sum(1 for p in two_strike_pitches if p['Description'] == 'Swinging Strike')
    two_strike_whiff_pct = two_strike_whiffs / two_strike_swings if two_strike_swings > 0 else None

    # First-Pitch Swing%: % of PAs where hitter swings on first pitch (count "0-0")
    first_pitches_h = [p for p in pitches if p.get('Count') == '0-0']
    first_pitch_swings = sum(1 for p in first_pitches_h if p['Description'] in SWING_DESCRIPTIONS)
    first_pitch_swing_pct = first_pitch_swings / len(first_pitches_h) if first_pitches_h else None

    # === Batted ball distance ===
    # Avg fly ball distance (fly_ball only, not popups/LD)
    fb_distances = [safe_float(p.get('Distance')) for p in bip if p.get('BBType') == 'fly_ball']
    fb_distances = [d for d in fb_distances if d is not None]
    avg_fb_dist = round(sum(fb_distances) / len(fb_distances), 0) if fb_distances else None

    # Avg HR distance
    hr_distances = [safe_float(p.get('Distance')) for p in bip if p.get('Event') == 'Home Run']
    hr_distances = [d for d in hr_distances if d is not None]
    avg_hr_dist = round(sum(hr_distances) / len(hr_distances), 0) if hr_distances else None

    # === Squared-Up Rate ===
    # % of competitive swings where exitVelo >= 0.80 × batSpeed × 1.23
    # Uses per-pitch BatSpeed and ExitVelo on BIPs with competitive swings
    squared_up = 0
    squared_eligible = 0
    for p in bip:
        bs = safe_float(p.get('BatSpeed'))
        ev_sq = safe_float(p.get('ExitVelo'))
        if bs is not None and bs >= 50 and ev_sq is not None:
            squared_eligible += 1
            threshold = 0.80 * bs * 1.23
            if ev_sq >= threshold:
                squared_up += 1
    squared_up_pct = squared_up / squared_eligible if squared_eligible > 0 else None

    # Bat Tracking — only competitive swings (BatSpeed >= 50)
    bs_vals = [safe_float(p.get('BatSpeed')) for p in pitches if safe_float(p.get('BatSpeed')) is not None and safe_float(p.get('BatSpeed')) >= 50]
    sl_vals = [safe_float(p.get('SwingLength')) for p in pitches if safe_float(p.get('SwingLength')) is not None and safe_float(p.get('BatSpeed')) is not None and safe_float(p.get('BatSpeed')) >= 50]
    aa_vals = [safe_float(p.get('AttackAngle')) for p in pitches if safe_float(p.get('AttackAngle')) is not None and safe_float(p.get('BatSpeed')) is not None and safe_float(p.get('BatSpeed')) >= 50]
    ad_vals = [safe_float(p.get('AttackDirection')) for p in pitches if safe_float(p.get('AttackDirection')) is not None and safe_float(p.get('BatSpeed')) is not None and safe_float(p.get('BatSpeed')) >= 50]
    spt_vals = [safe_float(p.get('SwingPathTilt')) for p in pitches if safe_float(p.get('SwingPathTilt')) is not None and safe_float(p.get('BatSpeed')) is not None and safe_float(p.get('BatSpeed')) >= 50]

    return {
        # Info / counts
        'pa': n_pa,
        'ab': n_ab,
        'nSwings': n_swings,
        'nBip': n_bip,
        # Hitter Stats tab
        'avg': batting_avg,
        'obp': obp,
        'slg': slg,
        'ops': ops,
        'doubles': n_2b,
        'triples': n_3b,
        'hr': n_hr,
        'xbh': xbh,
        'kPct': k_pct,
        'bbPct': bb_pct,
        'iso': iso,
        'babip': babip,
        # Batted Ball tab
        'avgEVAll': round(sum(ev_valid) / len(ev_valid), 1) if ev_valid else None,
        # Note: key is 'medEV' for historical reasons but this is actually mean EV (LA > 0)
        'medEV': round(sum(evs_pos) / len(evs_pos), 1) if evs_pos else None,
        'ev75': ev75,
        'maxEV': round(max(evs_pos), 1) if evs_pos else None,
        'medLA': round(median(all_la), 1) if all_la else None,
        'hardHitPct': round(hard_hit_pct, 4) if hard_hit_pct is not None else None,
        'barrelPct': barrels / n_bip if n_bip > 0 else None,
        'laSweetSpotPct': round(la_sweet_spot_pct, 4) if la_sweet_spot_pct is not None else None,
        'gbPct': gb / n_bip if n_bip > 0 else None,
        'ldPct': ld / n_bip if n_bip > 0 else None,
        'fbPct': fb / n_bip if n_bip > 0 else None,
        'puPct': pu / n_bip if n_bip > 0 else None,
        'hrFbPct': hr_fb_pct,
        'pullPct': pull / n_spray if n_spray > 0 else None,
        'middlePct': center / n_spray if n_spray > 0 else None,
        'oppoPct': oppo / n_spray if n_spray > 0 else None,
        'airPullPct': air_pull / n_spray if n_spray > 0 else None,
        # Swing Decisions tab
        'swingPct': n_swings / total if total > 0 else None,
        'izSwingPct': iz_swing_pct,
        'chasePct': chase_pct,
        'izSwChase': round(iz_swing_pct - chase_pct, 4) if iz_swing_pct is not None and chase_pct is not None else None,
        'contactPct': contact_pct,
        'izContactPct': iz_contact_pct,
        'whiffPct': whiffs / n_swings if n_swings > 0 else None,
        'izWhiffPct': iz_whiffs / iz_swings if iz_swings > 0 else None,
        # Run Value — negate pitcher RunExp so positive = good for hitter
        'runValue': (lambda vals: round(-sum(vals), 1) if vals else None)([v for v in (safe_float(p.get('RunExp')) for p in pitches) if v is not None]),
        # Bat Tracking — averages of competitive swings (BatSpeed >= 50)
        'batSpeed': round(sum(bs_vals) / len(bs_vals), 1) if bs_vals else None,
        'swingLength': round(sum(sl_vals) / len(sl_vals), 1) if sl_vals else None,
        'attackAngle': round(sum(aa_vals) / len(aa_vals), 1) if aa_vals else None,
        'attackDirection': round(sum(ad_vals) / len(ad_vals), 1) if ad_vals else None,
        'swingPathTilt': round(sum(spt_vals) / len(spt_vals), 1) if spt_vals else None,
        'nCompSwings': len(bs_vals),  # competitive swings count
        # Count-leverage stats
        'twoStrikeWhiffPct': two_strike_whiff_pct,
        'firstPitchSwingPct': first_pitch_swing_pct,
        # Batted ball distance
        'avgFbDist': avg_fb_dist,
        'avgHrDist': avg_hr_dist,
        # Squared-Up Rate
        'squaredUpPct': squared_up_pct,
    }


def generate_micro_data(all_pitches):
    """Generate micro-aggregate data for client-side date and opponent-hand filtering.

    Groups pitches by (person, date, opponent_hand) with summable counts.
    Returns a dict with compact arrays-of-arrays format for JSON serialization.
    """
    # --- Build lookup tables ---
    pitcher_set = set()
    hitter_set = set()
    team_set = set()
    date_set = set()
    pitch_type_set = set()

    for p in all_pitches:
        if p.get('Pitcher'):
            pitcher_set.add(p['Pitcher'])
        if p.get('PTeam') and p['PTeam'] in ALL_TEAMS:
            team_set.add(p['PTeam'])
        d = normalize_date(p.get('Game Date'))
        if d:
            date_set.add(d)
        if p.get('Pitch Type'):
            pitch_type_set.add(p['Pitch Type'])

    for p in all_pitches:
        if p.get('Batter'):
            hitter_set.add(p['Batter'])
        if p.get('BTeam') and p['BTeam'] in ALL_TEAMS:
            team_set.add(p['BTeam'])
        d = normalize_date(p.get('Game Date'))
        if d:
            date_set.add(d)

    pitchers = sorted(pitcher_set)
    hitters = sorted(hitter_set)
    teams = sorted(team_set)
    dates = sorted(date_set)
    pitch_types = sorted(pitch_type_set)

    pi_idx = {name: i for i, name in enumerate(pitchers)}
    hi_idx = {name: i for i, name in enumerate(hitters)}
    tm_idx = {name: i for i, name in enumerate(teams)}
    dt_idx = {d: i for i, d in enumerate(dates)}
    pt_idx = {pt: i for i, pt in enumerate(pitch_types)}

    # ==========================================================
    #  Pitcher micro-aggs
    #  Key: (pitcherIdx, teamIdx, throws, dateIdx, batterHand)
    #  Values: 24 count fields
    #  0:n  1:iz  2:sw  3:wh  4:csw  5:ooz  6:oozSw  7:bip  8:gb
    #  9:pa  10:h  11:hr  12:k  13:bb  14:hbp  15:sf  16:sh  17:ci
    #  18:izSw  19:izWh  20:firstPitches  21:firstPitchStrikes
    #  22:fb (fly balls)  23:nHrBip (HR on BIP, for HR/FB)  24:ldHr (line-drive HRs)
    #  25:pu (popups, for HR/FB denominator)
    # ==========================================================
    pitcher_micro = defaultdict(lambda: [0] * 27)

    for p in all_pitches:
        pitcher = p.get('Pitcher')
        team = p.get('PTeam')
        throws = p.get('Throws')
        date = normalize_date(p.get('Game Date'))
        batter_hand = p.get('Bats')

        if not pitcher or not team or team not in ALL_TEAMS:
            continue
        if p.get('_roc_hitter_pitch'):
            continue  # Skip AAA pitchers facing ROC hitters
        if not date or not batter_hand:
            continue

        key = (pi_idx[pitcher], tm_idx[team], throws or '', dt_idx[date], batter_hand)
        c = pitcher_micro[key]

        c[0] += 1  # n
        in_zone = p.get('InZone') == 'Yes'
        if in_zone:
            c[1] += 1  # iz
        desc = p.get('Description', '')
        if desc in SWING_DESCRIPTIONS:
            c[2] += 1  # sw
            if in_zone:
                c[18] += 1  # izSw
        if desc == 'Swinging Strike':
            c[3] += 1  # wh
            if in_zone:
                c[19] += 1  # izWh
        if desc in ('Called Strike', 'Swinging Strike'):
            c[4] += 1  # csw
        if p.get('InZone') == 'No':
            c[5] += 1  # ooz
            if desc in ('Swinging Strike', 'In Play', 'Foul'):
                c[6] += 1  # oozSw
        if desc not in ('Ball', 'Intent Ball', 'Hit By Pitch', 'Pitchout'):
            c[26] += 1  # nStrikes
        bb_type = p.get('BBType')
        if bb_type and bb_type not in BUNT_BB_TYPES:
            c[7] += 1  # bip
            if bb_type == 'ground_ball':
                c[8] += 1  # gb
            if bb_type == 'fly_ball':
                c[22] += 1  # fb (fly balls for HR/FB)
            if bb_type == 'popup':
                c[25] += 1  # pu (popups for HR/FB)
            if p.get('Event') == 'Home Run':
                c[23] += 1  # nHrBip (HR on BIP)
                if bb_type == 'line_drive':
                    c[24] += 1  # ldHr (line-drive HRs for HR/FB denominator)
        event = p.get('Event')
        if event and event not in NON_PA_EVENTS:
            c[9] += 1   # pa
            if event in HIT_EVENTS:      c[10] += 1  # h
            if event == 'Home Run':      c[11] += 1  # hr
            if event in K_EVENTS:        c[12] += 1  # k
            if event in BB_EVENTS:       c[13] += 1  # bb (all walks including IBB)
            if event in HBP_EVENTS:      c[14] += 1  # hbp
            if event in SF_EVENTS:       c[15] += 1  # sf
            if event in SH_EVENTS:       c[16] += 1  # sh
            if event in CI_EVENTS:       c[17] += 1  # ci
        # FPS counts (first pitch of PA: count == "0-0")
        if p.get('Count') == '0-0':
            c[20] += 1  # firstPitches
            if desc in ('Called Strike', 'Swinging Strike', 'Foul', 'In Play'):
                c[21] += 1  # firstPitchStrikes

    pitcher_rows = []
    for (pi, ti, throws, di, bh), c in pitcher_micro.items():
        pitcher_rows.append([pi, ti, throws, di, bh] + c)

    # ==========================================================
    #  Pitch micro-aggs
    #  Key: (pitcherIdx, teamIdx, throws, pitchTypeIdx, dateIdx, batterHand)
    #  Values: 22 count fields + 29 metric fields = 51 fields
    #  0:n  1:iz  2:sw  3:wh  4:csw  5:ooz  6:oozSw  7:bip  8:gb
    #  9:pa  10:h  11:hr  12:k  13:bb  14:hbp  15:sf  16:sh  17:ci
    #  18:izSw  19:izWh  20:firstPitches  21:firstPitchStrikes
    #  Metric fields (offset from 22):
    #  22:sumVelo 23:nVelo  24:sumSpin 25:nSpin  26:sumIVB 27:nIVB
    #  28:sumHB 29:nHB  30:sumRelZ 31:nRelZ  32:sumRelX 33:nRelX
    #  34:sumExt 35:nExt  36:sumArmAngle 37:nArmAngle
    #  38:sumVAA 39:nVAA  40:sumHAA 41:nHAA
    #  42:sumVRA 43:nVRA  44:sumHRA 45:nHRA
    #  46:sumPlateZ 47:nPlateZ
    #  48:sumTiltSin 49:sumTiltCos 50:nTilt
    #  51:sumPlateX 52:nPlateX
    # ==========================================================
    METRIC_OFFSETS = [
        ('Velocity', 22), ('Spin Rate', 24), ('IndVertBrk', 26),
        ('HorzBrk', 28), ('RelPosZ', 30), ('RelPosX', 32),
        ('Extension', 34), ('ArmAngle', 36), ('VAA', 38), ('HAA', 40),
        ('VRA', 42), ('HRA', 44), ('PlateZ', 46), ('PlateX', 51),
    ]

    pitch_micro = defaultdict(lambda: [0.0] * 53)

    for p in all_pitches:
        pitcher = p.get('Pitcher')
        team = p.get('PTeam')
        throws = p.get('Throws')
        pitch_type = p.get('Pitch Type')
        date = normalize_date(p.get('Game Date'))
        batter_hand = p.get('Bats')

        if not pitcher or not team or team not in ALL_TEAMS or not pitch_type:
            continue
        if p.get('_roc_hitter_pitch'):
            continue  # Skip AAA pitchers facing ROC hitters
        if not date or not batter_hand:
            continue

        key = (pi_idx[pitcher], tm_idx[team], throws or '',
               pt_idx[pitch_type], dt_idx[date], batter_hand)
        c = pitch_micro[key]

        # Same 22 count fields as pitcher (0-21), plus fly ball/HR counts don't apply at pitch level
        c[0] += 1
        in_zone = p.get('InZone') == 'Yes'
        if in_zone:
            c[1] += 1
        desc = p.get('Description', '')
        if desc in SWING_DESCRIPTIONS:
            c[2] += 1
            if in_zone:
                c[18] += 1  # izSw
        if desc == 'Swinging Strike':
            c[3] += 1
            if in_zone:
                c[19] += 1  # izWh
        if desc in ('Called Strike', 'Swinging Strike'):
            c[4] += 1
        if p.get('InZone') == 'No':
            c[5] += 1
            if desc in ('Swinging Strike', 'In Play', 'Foul'):
                c[6] += 1
        bb_type = p.get('BBType')
        if bb_type and bb_type not in BUNT_BB_TYPES:
            c[7] += 1
            if bb_type == 'ground_ball':
                c[8] += 1
        event = p.get('Event')
        if event and event not in NON_PA_EVENTS:
            c[9] += 1
            if event in HIT_EVENTS:      c[10] += 1
            if event == 'Home Run':      c[11] += 1
            if event in K_EVENTS:        c[12] += 1
            if event in BB_EVENTS:       c[13] += 1
            if event in HBP_EVENTS:      c[14] += 1
            if event in SF_EVENTS:       c[15] += 1
            if event in SH_EVENTS:       c[16] += 1
            if event in CI_EVENTS:       c[17] += 1

        # FPS counts (first pitch of PA: count == "0-0")
        if p.get('Count') == '0-0':
            c[20] += 1  # firstPitches
            if desc in ('Called Strike', 'Swinging Strike', 'Foul', 'In Play'):
                c[21] += 1  # firstPitchStrikes

        # Metric sums
        for col_name, offset in METRIC_OFFSETS:
            val = safe_float(p.get(col_name))
            if val is not None:
                c[offset] += val
                c[offset + 1] += 1

        # Break Tilt (circular sin/cos components)
        tilt_min = break_tilt_to_minutes(p.get('OTilt') or p.get('Break Tilt'))
        if tilt_min is not None:
            angle = tilt_min / 720.0 * 2 * math.pi
            c[48] += math.sin(angle)
            c[49] += math.cos(angle)
            c[50] += 1

    pitch_rows = []
    for (pi, ti, throws, pti, di, bh), c in pitch_micro.items():
        row = [pi, ti, throws, pti, di, bh]
        # 22 integer/float counts (0-21)
        for i in range(22):
            row.append(int(c[i]))
        # 13 metric sum/count pairs (including PlateZ and ArmAngle)
        for col_name, offset in METRIC_OFFSETS:
            row.append(round(c[offset], 2))       # metric sum
            row.append(int(c[offset + 1]))         # metric count
        # Tilt sin/cos
        row.append(round(c[48], 6))  # sumTiltSin
        row.append(round(c[49], 6))  # sumTiltCos
        row.append(int(c[50]))       # nTilt
        pitch_rows.append(row)

    # ==========================================================
    #  Pitcher BIP records (for avgEV, maxEV, hardHit%, barrel%, LD%, FB%, PU%)
    #  [pitcherIdx, dateIdx, batterHand, exitVelo, launchAngle, bbType]
    #  bbType encoded: 0=ground_ball, 1=line_drive, 2=fly_ball, 3=popup
    # ==========================================================
    BB_TYPE_CODE = {'ground_ball': 0, 'line_drive': 1, 'fly_ball': 2, 'popup': 3}
    pitcher_bip_rows = []
    for p in all_pitches:
        pitcher = p.get('Pitcher')
        team = p.get('PTeam')
        date = normalize_date(p.get('Game Date'))
        batter_hand = p.get('Bats')
        bb_type = p.get('BBType')

        if not pitcher or not team or team not in ALL_TEAMS:
            continue
        if p.get('_roc_hitter_pitch'):
            continue  # Skip AAA pitchers facing ROC hitters
        if not date or not batter_hand:
            continue
        if not bb_type or bb_type in BUNT_BB_TYPES:
            continue

        ev = safe_float(p.get('ExitVelo'))
        la = safe_float(p.get('LaunchAngle'))
        if ev is None and la is None:
            continue

        bb_code = BB_TYPE_CODE.get(bb_type, -1)
        if bb_code < 0:
            continue

        pitcher_bip_rows.append([
            pi_idx[pitcher],
            dt_idx[date],
            batter_hand,
            round(ev, 1) if ev is not None else None,
            round(la, 1) if la is not None else None,
            bb_code,
        ])
    print(f"  Pitcher BIP records: {len(pitcher_bip_rows)}")

    # ==========================================================
    #  Hitter micro-aggs
    #  Key: (hitterIdx, teamIdx, bats, dateIdx, pitcherHand)
    #  bats = actual batting side for these pitches (R/L)
    #  Values: 36 count fields
    #  0:n  1:pa  2:h  3:db  4:tp  5:hr  6:bb  7:hbp  8:sf  9:sh  10:ci  11:k
    #  12:swings  13:whiffs  14:izPitches  15:oozPitches
    #  16:izSwings  17:oozSwings  18:contact
    #  19:izSwNonBunt  20:izContact
    #  21:bip  22:gb  23:ld  24:fb  25:pu
    #  26:barrels  27:nSpray  28:pull  29:center  30:oppo  31:airPull
    #  32:hardHit  33:laSweetSpot  34:nLaValid  35:nHrBip  36:ldHr
    # ==========================================================
    hitter_micro = defaultdict(lambda: [0.0] * 37)

    for p in all_pitches:
        batter = p.get('Batter')
        team = p.get('BTeam')
        bats = p.get('Bats')
        date = normalize_date(p.get('Game Date'))
        pitcher_hand = p.get('Throws')

        if not batter or not team or team not in ALL_TEAMS:
            continue
        if p.get('_roc_pitcher_pitch'):
            continue  # Skip AAA hitters facing ROC pitchers
        if not date or not pitcher_hand or not bats:
            continue

        key = (hi_idx[batter], tm_idx[team], bats, dt_idx[date], pitcher_hand)
        c = hitter_micro[key]

        c[0] += 1  # n (total pitches)
        desc = p.get('Description', '')
        bb_type = p.get('BBType')
        in_zone = p.get('InZone')

        # PA and event counts
        event = p.get('Event')
        if event and event not in NON_PA_EVENTS:
            c[1] += 1   # pa
            if event in HIT_EVENTS:      c[2] += 1   # h
            if event == 'Double':        c[3] += 1   # db
            if event == 'Triple':        c[4] += 1   # tp
            if event == 'Home Run':      c[5] += 1   # hr
            if event in BB_EVENTS:       c[6] += 1   # bb (all walks including IBB)
            if event in HBP_EVENTS:      c[7] += 1   # hbp
            if event in SF_EVENTS:       c[8] += 1   # sf
            if event in SH_EVENTS:       c[9] += 1   # sh
            if event in CI_EVENTS:       c[10] += 1  # ci
            if event in K_EVENTS:        c[11] += 1  # k

        # Swing counts
        if desc in SWING_DESCRIPTIONS:
            c[12] += 1  # swings
        if desc == 'Swinging Strike':
            c[13] += 1  # whiffs

        # Zone-based counts
        if in_zone == 'Yes':
            c[14] += 1  # izPitches
            if desc in SWING_DESCRIPTIONS:
                c[16] += 1  # izSwings
                # izSwNonBunt: exclude bunt BIPs from IZ swing count
                if bb_type not in BUNT_BB_TYPES:  # None not in set → True
                    c[19] += 1
            if desc in ('Foul', 'In Play'):
                if bb_type not in BUNT_BB_TYPES:
                    c[20] += 1  # izContact
        elif in_zone == 'No':
            c[15] += 1  # oozPitches
            if desc in SWING_DESCRIPTIONS:
                c[17] += 1  # oozSwings

        # Contact (overall)
        if desc in ('Foul', 'In Play'):
            c[18] += 1

        # Batted ball data (non-bunt BIPs)
        if bb_type and bb_type not in BUNT_BB_TYPES:
            c[21] += 1  # bip
            if bb_type == 'ground_ball':  c[22] += 1  # gb
            if bb_type == 'line_drive':   c[23] += 1  # ld
            if bb_type == 'fly_ball':     c[24] += 1  # fb
            if bb_type == 'popup':        c[25] += 1  # pu

            # Barrel, hard-hit, LA sweet-spot, HR on BIP
            ev = safe_float(p.get('ExitVelo'))
            la = safe_float(p.get('LaunchAngle'))
            barrel_val = str(p.get('Barrel', '')).strip()
            if barrel_val == '6' or (barrel_val == '' and is_barrel(ev, la)):
                c[26] += 1
            if ev is not None and ev >= 95:
                c[32] += 1  # hardHit
            if la is not None:
                c[34] += 1  # nLaValid
                if 8 <= la <= 32:
                    c[33] += 1  # laSweetSpot
            if event == 'Home Run':
                c[35] += 1  # nHrBip
                if bb_type == 'line_drive':
                    c[36] += 1  # ldHr (line-drive HRs)

            # Spray direction
            hc_x = safe_float(p.get('HC_X'))
            hc_y = safe_float(p.get('HC_Y'))
            sa = spray_angle(hc_x, hc_y)
            sd = spray_direction(sa, bats)
            if sd:
                c[27] += 1  # nSpray
                if sd == 'pull':    c[28] += 1
                if sd == 'center':  c[29] += 1
                if sd == 'oppo':    c[30] += 1
                if sd == 'pull' and bb_type in ('line_drive', 'fly_ball', 'popup'):
                    c[31] += 1  # airPull


    hitter_rows = []
    for (hi, ti, bats, di, ph), c in hitter_micro.items():
        row = [hi, ti, bats, di, ph]
        for i in range(37):
            val = c[i]
            row.append(round(val, 4) if isinstance(val, float) and val != int(val) else int(val))
        hitter_rows.append(row)

    # ==========================================================
    #  Hitter BIP records (for EV, LA, spray chart, batted ball stats)
    #  [hitterIdx, dateIdx, pitcherHand, exitVelo, launchAngle, hcX, hcY, bbType, event]
    #  bbType: 0=ground_ball, 1=line_drive, 2=fly_ball, 3=popup
    #  event: 0=out, 1=single, 2=double, 3=triple, 4=hr, 5=error/fc
    # ==========================================================
    BB_TYPE_ENCODE = {'ground_ball': 0, 'line_drive': 1, 'fly_ball': 2, 'popup': 3}
    EVENT_ENCODE = {
        'Single': 1, 'Double': 2, 'Triple': 3, 'Home Run': 4,
        'Field Error': 5, "Fielder's Choice": 5, "Fielder's Choice Out": 5,
    }
    hitter_bip_rows = []
    for p in all_pitches:
        batter = p.get('Batter')
        team = p.get('BTeam')
        date = normalize_date(p.get('Game Date'))
        pitcher_hand = p.get('Throws')
        bb_type = p.get('BBType')

        if not batter or not team or team not in ALL_TEAMS:
            continue
        if p.get('_roc_pitcher_pitch'):
            continue  # Skip AAA hitters facing ROC pitchers
        if not date or not pitcher_hand:
            continue
        if not bb_type or bb_type in BUNT_BB_TYPES:
            continue

        ev = safe_float(p.get('ExitVelo'))
        la = safe_float(p.get('LaunchAngle'))
        hc_x = safe_float(p.get('HC_X'))
        hc_y = safe_float(p.get('HC_Y'))
        if ev is None and la is None and hc_x is None and hc_y is None:
            continue
        bb_enc = BB_TYPE_ENCODE.get(bb_type, 0)
        ev_enc = EVENT_ENCODE.get(p.get('Event'), 0)

        dist = safe_float(p.get('Distance'))
        woba_val = safe_float(p.get('wOBAval'))
        bat_side = p.get('Bats') or 'R'
        hitter_bip_rows.append([
            hi_idx[batter],
            dt_idx[date],
            pitcher_hand,
            bat_side,
            round(ev, 1) if ev is not None else None,
            round(la, 1) if la is not None else None,
            int(round(hc_x)) if hc_x is not None else None,
            int(round(hc_y)) if hc_y is not None else None,
            bb_enc,
            ev_enc,
            int(round(dist)) if dist is not None else None,
            round(woba_val, 3) if woba_val is not None else None,
        ])

    # ==========================================================
    #  Hitter-Pitch micro-aggs (same counts as hitter micro, but keyed with pitch type)
    #  Key: (hitterIdx, teamIdx, bats, pitchTypeIdx, dateIdx, pitcherHand)
    #  Same 36 count fields as hitter micro
    # ==========================================================
    hitter_pitch_micro = defaultdict(lambda: [0.0] * 37)

    for p in all_pitches:
        batter = p.get('Batter')
        team = p.get('BTeam')
        bats = p.get('Bats')
        pitch_type = p.get('Pitch Type')
        date = normalize_date(p.get('Game Date'))
        pitcher_hand = p.get('Throws')

        if not batter or not team or team not in ALL_TEAMS:
            continue
        if p.get('_roc_pitcher_pitch'):
            continue  # Skip AAA hitters facing ROC pitchers
        if not date or not pitcher_hand or not bats or not pitch_type:
            continue

        key = (hi_idx[batter], tm_idx[team], bats, pt_idx[pitch_type], dt_idx[date], pitcher_hand)
        c = hitter_pitch_micro[key]

        c[0] += 1  # n
        desc = p.get('Description', '')
        bb_type = p.get('BBType')
        in_zone = p.get('InZone')

        event = p.get('Event')
        if event and event not in NON_PA_EVENTS:
            c[1] += 1   # pa
            if event in HIT_EVENTS:      c[2] += 1
            if event == 'Double':        c[3] += 1
            if event == 'Triple':        c[4] += 1
            if event == 'Home Run':      c[5] += 1
            if event in BB_EVENTS:       c[6] += 1
            if event in HBP_EVENTS:      c[7] += 1
            if event in SF_EVENTS:       c[8] += 1
            if event in SH_EVENTS:       c[9] += 1
            if event in CI_EVENTS:       c[10] += 1
            if event in K_EVENTS:        c[11] += 1

        if desc in SWING_DESCRIPTIONS:
            c[12] += 1  # swings
        if desc == 'Swinging Strike':
            c[13] += 1  # whiffs

        if in_zone == 'Yes':
            c[14] += 1  # izPitches
            if desc in SWING_DESCRIPTIONS:
                c[16] += 1  # izSwings
                if bb_type not in BUNT_BB_TYPES:
                    c[19] += 1  # izSwNonBunt
            if desc in ('Foul', 'In Play'):
                if bb_type not in BUNT_BB_TYPES:
                    c[20] += 1  # izContact
        elif in_zone == 'No':
            c[15] += 1  # oozPitches
            if desc in SWING_DESCRIPTIONS:
                c[17] += 1  # oozSwings

        if desc in ('Foul', 'In Play'):
            c[18] += 1  # contact

        if bb_type and bb_type not in BUNT_BB_TYPES:
            c[21] += 1  # bip
            if bb_type == 'ground_ball':  c[22] += 1
            if bb_type == 'line_drive':   c[23] += 1
            if bb_type == 'fly_ball':     c[24] += 1
            if bb_type == 'popup':        c[25] += 1

            ev = safe_float(p.get('ExitVelo'))
            la = safe_float(p.get('LaunchAngle'))
            barrel_val = str(p.get('Barrel', '')).strip()
            if barrel_val == '6' or (barrel_val == '' and is_barrel(ev, la)):
                c[26] += 1
            if ev is not None and ev >= 95:
                c[32] += 1  # hardHit
            if la is not None:
                c[34] += 1  # nLaValid
                if 8 <= la <= 32:
                    c[33] += 1  # laSweetSpot
            if event == 'Home Run':
                c[35] += 1  # nHrBip
                if bb_type == 'line_drive':
                    c[36] += 1  # ldHr (line-drive HRs)

            hc_x = safe_float(p.get('HC_X'))
            hc_y = safe_float(p.get('HC_Y'))
            sa = spray_angle(hc_x, hc_y)
            sd = spray_direction(sa, bats)
            if sd:
                c[27] += 1
                if sd == 'pull':    c[28] += 1
                if sd == 'center':  c[29] += 1
                if sd == 'oppo':    c[30] += 1
                if sd == 'pull' and bb_type in ('line_drive', 'fly_ball', 'popup'):
                    c[31] += 1

    hitter_pitch_rows = []
    for (hi, ti, bats, pti, di, ph), c in hitter_pitch_micro.items():
        row = [hi, ti, bats, pti, di, ph]
        for i in range(37):
            val = c[i]
            row.append(round(val, 4) if isinstance(val, float) and val != int(val) else int(val))
        hitter_pitch_rows.append(row)

    # Hitter-Pitch BIP records (with pitch type)
    # [hitterIdx, pitchTypeIdx, dateIdx, pitcherHand, exitVelo, launchAngle]
    hitter_pitch_bip_rows = []
    for p in all_pitches:
        batter = p.get('Batter')
        team = p.get('BTeam')
        pitch_type = p.get('Pitch Type')
        date = normalize_date(p.get('Game Date'))
        pitcher_hand = p.get('Throws')
        bb_type = p.get('BBType')

        if not batter or not team or team not in ALL_TEAMS:
            continue
        if p.get('_roc_pitcher_pitch'):
            continue  # Skip AAA hitters facing ROC pitchers
        if not date or not pitcher_hand or not pitch_type:
            continue
        if not bb_type or bb_type in BUNT_BB_TYPES:
            continue

        ev = safe_float(p.get('ExitVelo'))
        la = safe_float(p.get('LaunchAngle'))
        if ev is None and la is None:
            continue

        hitter_pitch_bip_rows.append([
            hi_idx[batter],
            pt_idx[pitch_type],
            dt_idx[date],
            pitcher_hand,
            round(ev, 1) if ev is not None else None,
            round(la, 1) if la is not None else None,
        ])

    # ==========================================================
    #  Velocity trend sparklines (sparse time-series)
    #  Key: (pitcherIdx, pitchTypeIdx, dateIdx)
    #  Values: [sumVelo, nVelo]
    # ==========================================================
    velo_trend = defaultdict(lambda: [0.0, 0])
    for p in all_pitches:
        pitcher = p.get('Pitcher')
        team = p.get('PTeam')
        pitch_type = p.get('Pitch Type')
        date = normalize_date(p.get('Game Date'))
        velo = safe_float(p.get('Velocity'))

        if not pitcher or not team or team not in ALL_TEAMS or not pitch_type:
            continue
        if p.get('_roc_hitter_pitch'):
            continue
        if not date or velo is None:
            continue

        key = (pi_idx[pitcher], pt_idx[pitch_type], dt_idx[date])
        velo_trend[key][0] += velo
        velo_trend[key][1] += 1

    velo_trend_rows = []
    for (pi, pti, di), (s, n) in velo_trend.items():
        velo_trend_rows.append([pi, pti, di, round(s, 1), n])
    print(f"  Velocity trend rows: {len(velo_trend_rows)}")

    # ==========================================================
    #  Build output
    # ==========================================================
    return {
        'lookups': {
            'pitchers': pitchers,
            'hitters': hitters,
            'teams': teams,
            'dates': dates,
            'pitchTypes': pitch_types,
        },
        'pitcherCols': [
            'pitcherIdx', 'teamIdx', 'throws', 'dateIdx', 'batterHand',
            'n', 'iz', 'sw', 'wh', 'csw', 'ooz', 'oozSw', 'bip', 'gb',
            'pa', 'h', 'hr', 'k', 'bb', 'hbp', 'sf', 'sh', 'ci',
            'izSw', 'izWh', 'firstPitches', 'firstPitchStrikes', 'fb', 'nHrBip', 'ldHr', 'pu', 'nStrikes',
        ],
        'pitcherMicro': pitcher_rows,
        'pitcherBipCols': ['pitcherIdx', 'dateIdx', 'batterHand', 'exitVelo', 'launchAngle', 'bbType'],
        'pitcherBip': pitcher_bip_rows,
        'pitchCols': [
            'pitcherIdx', 'teamIdx', 'throws', 'pitchTypeIdx', 'dateIdx', 'batterHand',
            'n', 'iz', 'sw', 'wh', 'csw', 'ooz', 'oozSw', 'bip', 'gb',
            'pa', 'h', 'hr', 'k', 'bb', 'hbp', 'sf', 'sh', 'ci',
            'izSw', 'izWh', 'firstPitches', 'firstPitchStrikes',
            'sumVelo', 'nVelo', 'sumSpin', 'nSpin', 'sumIVB', 'nIVB',
            'sumHB', 'nHB', 'sumRelZ', 'nRelZ', 'sumRelX', 'nRelX',
            'sumExt', 'nExt', 'sumArmAngle', 'nArmAngle',
            'sumVAA', 'nVAA', 'sumHAA', 'nHAA',
            'sumVRA', 'nVRA', 'sumHRA', 'nHRA',
            'sumPlateZ', 'nPlateZ',
            'sumPlateX', 'nPlateX',
            'sumTiltSin', 'sumTiltCos', 'nTilt',
        ],
        'pitchMicro': pitch_rows,
        'hitterCols': [
            'hitterIdx', 'teamIdx', 'bats', 'dateIdx', 'pitcherHand',
            'n', 'pa', 'h', 'db', 'tp', 'hr', 'bb', 'hbp', 'sf', 'sh', 'ci', 'k',
            'swings', 'whiffs', 'izPitches', 'oozPitches', 'izSwings', 'oozSwings',
            'contact', 'izSwNonBunt', 'izContact',
            'bip', 'gb', 'ld', 'fb', 'pu',
            'barrels', 'nSpray', 'pull', 'center', 'oppo', 'airPull',
            'hardHit', 'laSweetSpot', 'nLaValid', 'nHrBip', 'ldHr',
        ],
        'hitterMicro': hitter_rows,
        'hitterBipCols': ['hitterIdx', 'dateIdx', 'pitcherHand', 'batSide', 'exitVelo', 'launchAngle', 'hcX', 'hcY', 'bbType', 'event', 'distance', 'wOBAval'],
        'hitterBip': hitter_bip_rows,
        'hitterPitchCols': [
            'hitterIdx', 'teamIdx', 'bats', 'pitchTypeIdx', 'dateIdx', 'pitcherHand',
            'n', 'pa', 'h', 'db', 'tp', 'hr', 'bb', 'hbp', 'sf', 'sh', 'ci', 'k',
            'swings', 'whiffs', 'izPitches', 'oozPitches', 'izSwings', 'oozSwings',
            'contact', 'izSwNonBunt', 'izContact',
            'bip', 'gb', 'ld', 'fb', 'pu',
            'barrels', 'nSpray', 'pull', 'center', 'oppo', 'airPull',
            'hardHit', 'laSweetSpot', 'nLaValid', 'nHrBip', 'ldHr',
        ],
        'hitterPitchMicro': hitter_pitch_rows,
        'hitterPitchBipCols': ['hitterIdx', 'pitchTypeIdx', 'dateIdx', 'pitcherHand', 'exitVelo', 'launchAngle'],
        'hitterPitchBip': hitter_pitch_bip_rows,
        'veloTrendCols': ['pitcherIdx', 'pitchTypeIdx', 'dateIdx', 'sumVelo', 'nVelo'],
        'veloTrend': velo_trend_rows,
    }


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


def compute_percentile_ranks(rows, metric_key, min_count=0, count_key='count'):
    """Compute percentile rank (0-100) for each row's metric value.
    Uses the 'mean rank' method for ties.
    If min_count > 0, only rows with row[count_key] >= min_count participate
    in the percentile pool. Sub-minimum rows are interpolated into the qualified
    pool so they still get a percentile value (displayed as unqualified/gray)."""
    pctl_key = metric_key + '_pctl'
    valid = [(i, rows[i][metric_key]) for i in range(len(rows))
             if rows[i].get(metric_key) is not None
             and (min_count == 0 or (rows[i].get(count_key) or 0) >= min_count)]

    if len(valid) < 2:
        for row in rows:
            row[pctl_key] = 50 if row.get(metric_key) is not None else None
        return

    values = [v for _, v in valid]
    n = len(values)

    # Compute percentiles for qualified rows (ranked among themselves)
    for idx, val in valid:
        below = sum(1 for x in values if x < val)
        equal = sum(1 for x in values if x == val)
        pctl = (below + 0.5 * (equal - 1)) / max(1, n - 1) * 100
        rows[idx][pctl_key] = max(0, min(100, round(pctl)))

    # Interpolate sub-minimum rows into the qualified pool
    if min_count > 0:
        for i, row in enumerate(rows):
            if pctl_key in row:
                continue  # Already computed above
            val = row.get(metric_key)
            if val is None:
                row[pctl_key] = None
                continue
            below = sum(1 for x in values if x < val)
            equal = sum(1 for x in values if x == val)
            pctl = (below + 0.5 * equal) / n * 100
            row[pctl_key] = max(0, min(100, round(pctl)))

    # Set None for rows that don't have the metric
    for row in rows:
        if pctl_key not in row:
            row[pctl_key] = None


def compute_percentile_ranks_with_aaa(rows, metric_key, min_count=0, count_key='count'):
    """Compute percentiles from MLB-only pool, then interpolate AAA players into that distribution.
    AAA players (rows with _isROC=True) are excluded from the MLB percentile pool but
    receive percentile values based on where they'd fall in the MLB distribution."""
    pctl_key = metric_key + '_pctl'

    mlb_rows = [r for r in rows if not r.get('_isROC')]
    aaa_rows = [r for r in rows if r.get('_isROC')]

    # Step 1: compute normal percentiles on MLB-only pool
    compute_percentile_ranks(mlb_rows, metric_key, min_count, count_key)

    # Step 2: interpolate AAA rows into MLB distribution
    mlb_values = sorted([r[metric_key] for r in mlb_rows
                         if r.get(metric_key) is not None
                         and (min_count == 0 or (r.get(count_key) or 0) >= min_count)])
    n = len(mlb_values)

    for row in aaa_rows:
        val = row.get(metric_key)
        if val is None:
            row[pctl_key] = None
            continue
        if n < 2:
            row[pctl_key] = 50
            continue
        below = sum(1 for x in mlb_values if x < val)
        equal = sum(1 for x in mlb_values if x == val)
        pctl = (below + 0.5 * equal) / n * 100
        row[pctl_key] = max(0, min(100, round(pctl)))


def load_mlb_id_cache(cache_path):
    """Load MLB ID cache from disk."""
    if os.path.exists(cache_path):
        with open(cache_path, 'r') as f:
            return json.load(f)
    return {}


def save_mlb_id_cache(cache, cache_path):
    """Save MLB ID cache to disk."""
    with open(cache_path, 'w') as f:
        json.dump(cache, f, indent=2)


def lookup_mlb_id(player_name, team_abbrev, mlb_id_cache):
    """Look up MLB player ID using the MLB Stats API, matching by name and team."""
    cache_key = f"{player_name}|{team_abbrev}"
    if cache_key in mlb_id_cache:
        return mlb_id_cache[cache_key]

    # Parse "Last, First" format
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

        # Try to match by team first
        if team_id and people:
            for person in people:
                ct = person.get('currentTeam', {})
                parent = ct.get('parentOrgId') or ct.get('id')
                if parent == team_id or ct.get('id') == team_id:
                    mlb_id = person['id']
                    mlb_id_cache[cache_key] = mlb_id
                    return mlb_id

        # Fallback: first result with matching last name
        if people:
            last_name = parts[0] if len(parts) == 2 else player_name.split()[-1]
            for person in people:
                if person.get('lastName', '').lower() == last_name.lower():
                    mlb_id = person['id']
                    mlb_id_cache[cache_key] = mlb_id
                    return mlb_id
            # Last resort: first result
            mlb_id = people[0]['id']
            mlb_id_cache[cache_key] = mlb_id
            return mlb_id

    except Exception as e:
        print(f"  Warning: MLB ID lookup failed for {player_name} ({team_abbrev}): {e}")

    mlb_id_cache[cache_key] = None
    return None


def read_pitches_from_sheet(gc, sheet_id, extra_tabs=None):
    """Read all pitches from a single Google Sheets spreadsheet. Returns a list of pitch dicts.
    extra_tabs: optional set of additional tab names to read (e.g. {'ROC', 'AAA'}).
    Pitches from extra_tabs are tagged with _source=tab_name; MLB pitches get _source='MLB'."""
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
                # Convert empty strings to None
                if val == '':
                    val = None
                pitch[col_name] = val

            pitch['_source'] = tab_name if is_extra else 'MLB'
            pitches.append(pitch)
    return pitches


# ---- Boxscore Data ----

BOXSCORE_CACHE_PATH = os.path.join(DATA_DIR, 'boxscore_cache.json')
MILB_BOXSCORE_CACHE_PATH = os.path.join(DATA_DIR, 'milb_boxscore_cache.json')

# MiLB team configuration for boxscore fetching
# Maps leaderboard team abbreviation -> config for MLB Stats API schedule lookup
MILB_TEAMS_CONFIG = {
    'ROC': {
        'sport_id': 11,        # AAA = sportId 11
        'search_name': 'Rochester',  # Match in schedule API team names
        'api_name': 'Rochester Red Wings',  # Full name in API
    },
}

# Maps MLB Stats API MiLB team full name -> leaderboard abbreviation
MILB_TEAM_NAME_TO_ABBREV = {
    'Rochester Red Wings': 'ROC',
}

# Full team name to abbreviation (for matching boxscore team names)
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


def _fullname_to_lastfirst(full_name):
    """Convert 'First Last' to 'Last, First'. Simple split — handles most cases."""
    parts = full_name.strip().split()
    if len(parts) <= 1:
        return full_name
    # Handle suffixes
    suffixes = {'jr.', 'jr', 'sr.', 'sr', 'ii', 'iii', 'iv', 'v'}
    suffix = ''
    if len(parts) > 2 and parts[-1].lower().rstrip('.') in suffixes:
        suffix = ' ' + parts.pop()
    return parts[-1] + suffix + ', ' + ' '.join(parts[:-1])


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


def fetch_and_aggregate_milb_boxscores(game_dates, team_abbrev):
    """Fetch MiLB boxscores for a specific AAA team. Returns aggregated pitcher and hitter stats."""
    config = MILB_TEAMS_CONFIG.get(team_abbrev)
    if not config:
        return {}, {}, {}, {}

    cache = load_milb_boxscore_cache()
    new_fetches = 0
    cache_key_prefix = team_abbrev + '|'

    import datetime as _dt
    today = _dt.date.today().isoformat()
    yesterday = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
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

    # Aggregate — only include players from the target team
    pitcher_agg = {}
    hitter_agg = {}
    pitcher_id_map = {}
    hitter_id_map = {}

    # Build set of accepted team names for this MiLB team
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
                # Remap MiLB API team name to our abbreviation
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

    result = {'pitchers': [], 'hitters': []}

    for side in ['away', 'home']:
        team_data = box.get('teams', {}).get(side, {})
        team_name = team_data.get('team', {}).get('name', '')
        team_abbrev = TEAM_NAME_TO_ABBREV.get(team_name, team_name)
        pitcher_ids = team_data.get('pitchers', [])
        batter_ids = team_data.get('batters', [])
        players = team_data.get('players', {})

        # Pitchers
        for idx, pid in enumerate(pitcher_ids):
            p = players.get(f'ID{pid}', {})
            full_name = p.get('person', {}).get('fullName', '')
            stats = p.get('stats', {}).get('pitching', {})
            if not stats:
                continue
            # Get "Last, First" name — try lastFirstName, fall back to lookup
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

        # Hitters
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


def fetch_and_aggregate_boxscores(game_dates):
    """Fetch boxscores for all game dates, using cache. Returns aggregated pitcher and hitter stats."""
    cache = load_boxscore_cache()
    new_fetches = 0

    # Find dates we need to fetch
    # Always re-fetch dates from the last 2 days (games may have finished since last run)
    import datetime as _dt
    today = _dt.date.today().isoformat()
    yesterday = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
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
                time_module.sleep(0.1)  # Rate limit
            time_module.sleep(0.5)
        save_boxscore_cache(cache)
        print(f"  Fetched {new_fetches} boxscores, cache now has {len(cache)} dates")
    else:
        print(f"  All {len(game_dates)} game dates already cached")

    # Aggregate across all dates that are in our game_dates set
    pitcher_agg = {}  # key: "name|team" -> accumulated stats
    hitter_agg = {}
    # MLB ID → name|team key (for fallback matching on compound last names)
    pitcher_id_map = {}  # mlbId -> "name|team"
    hitter_id_map = {}

    for d in game_dates:
        if d not in cache:
            continue
        for box in cache[d]:
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


def outs_to_ip_str(outs):
    """Convert total outs to IP string notation (e.g., 19 outs -> '6.1')."""
    full = outs // 3
    remainder = outs % 3
    return f"{full}.{remainder}"


def outs_to_ip_float(outs):
    """Convert outs to float for calculations like ERA (19 outs -> 6.333...)."""
    return outs / 3.0


def process_game_type(all_pitches, label, mlb_id_cache, mlb_id_cache_path):
    """Process a set of pitches into all leaderboard outputs.

    Args:
        all_pitches: list of pitch dicts
        label: 'ST' or 'RS' (for logging)
        mlb_id_cache: shared MLB ID cache dict (mutated in place)
        mlb_id_cache_path: path to MLB ID cache file

    Returns a dict with all outputs: pitcher_leaderboard, pitch_leaderboard,
    hitter_leaderboard, hitter_pitch_leaderboard, metadata, micro_data,
    pitch_details, hitter_pitch_details.
    """
    if not all_pitches:
        print(f"  No pitches for {label}, returning empty results")
        return {
            'pitcher_leaderboard': [],
            'pitch_leaderboard': [],
            'hitter_leaderboard': [],
            'hitter_pitch_leaderboard': [],
            'metadata': {
                'teams': [],
                'pitchTypes': [],
                'generatedAt': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'totalPitches': 0,
                'totalPitchers': 0,
                'totalHitters': 0,
                'leagueAverages': {},
                'pitcherLeagueAverages': {},
                'hitterLeagueAverages': {},
                'vaaRegression': {'slope': 0, 'intercept': 0, 'leagueAvgPlateZ': 0},
                'haaRegression': {'slope': 0, 'intercept': 0, 'leagueAvgPlateX': 0},
                'sacqZones': [],
            },
            'micro_data': {
                'lookups': {'pitchers': [], 'hitters': [], 'teams': [], 'dates': [], 'pitchTypes': []},
                'pitcherCols': [], 'pitcherMicro': [],
                'pitcherBipCols': [], 'pitcherBip': [],
                'pitchCols': [], 'pitchMicro': [],
                'hitterCols': [], 'hitterMicro': [],
                'hitterBipCols': [], 'hitterBip': [],
                'hitterPitchCols': [], 'hitterPitchMicro': [],
                'hitterPitchBipCols': [], 'hitterPitchBip': [],
            },
            'pitch_details': {},
            'hitter_pitch_details': {},
        }

    # --- Recompute InZone from PlateX/PlateZ/SzTop/SzBot with ball-radius adjustment ---
    for p in all_pitches:
        p['InZone'] = compute_in_zone(p)

    # --- Map non-MLB BTeams to MLB teams where possible ---
    mlb_hitter_teams = {}
    for p in all_pitches:
        batter = p.get('Batter')
        b_team = p.get('BTeam')
        if batter and b_team and b_team in MLB_TEAMS:
            mlb_hitter_teams[batter] = b_team

    remapped_count = 0
    for p in all_pitches:
        b_team = p.get('BTeam')
        if b_team and b_team not in MLB_TEAMS:
            batter = p.get('Batter')
            if batter and batter in mlb_hitter_teams:
                p['BTeam'] = mlb_hitter_teams[batter]
                remapped_count += 1
    if remapped_count:
        print(f"  Remapped {remapped_count} non-MLB BTeam entries")

    # --- Tag ROC/AAA pitches to prevent cross-contamination ---
    # ROC tab pitches: only the pitcher side matters (batters are AAA opponents)
    # AAA tab pitches: only the hitter side matters (pitchers are AAA opponents)
    roc_pitcher_count = 0
    roc_hitter_count = 0
    for p in all_pitches:
        source = p.get('_source', 'MLB')
        if source == 'ROC':
            p['_roc_pitcher_pitch'] = True  # Pitcher is ROC, batter is AAA opponent
            roc_pitcher_count += 1
        elif source == 'AAA':
            p['_roc_hitter_pitch'] = True   # Hitter is ROC, pitcher is AAA opponent
            # Normalize BTeam to 'ROC' if it's 'AAA'
            if p.get('BTeam') == 'AAA':
                p['BTeam'] = 'ROC'
            roc_hitter_count += 1
    if roc_pitcher_count or roc_hitter_count:
        print(f"  Tagged {roc_pitcher_count} ROC pitcher pitches, {roc_hitter_count} ROC hitter pitches")

    # Collect unique teams (MLB + AAA) and pitch types
    all_teams = sorted(set(
        [p['PTeam'] for p in all_pitches if p.get('PTeam') and p['PTeam'] in ALL_TEAMS] +
        [p['BTeam'] for p in all_pitches if p.get('BTeam') and p['BTeam'] in ALL_TEAMS]
    ))
    all_pitch_types = sorted(set(p['Pitch Type'] for p in all_pitches if p.get('Pitch Type')))

    # --- Lookup MLB IDs for all pitchers and hitters ---
    print(f"\n--- Looking up MLB player IDs ({label}) ---")

    # Helper to get cached MLB ID
    def get_mlb_id(name, team):
        return mlb_id_cache.get(f"{name}|{team}")

    # Build unique pitcher/hitter lists
    unique_pitchers = set()
    unique_hitters = set()
    for p in all_pitches:
        pitcher = p.get('Pitcher')
        pteam = p.get('PTeam')
        if pitcher and pteam:
            unique_pitchers.add((pitcher, pteam))
        batter = p.get('Batter')
        bteam = p.get('BTeam')
        if batter and bteam:
            unique_hitters.add((batter, bteam))

    # Look up all unique players
    all_unique = unique_pitchers | unique_hitters
    new_lookups = 0
    for name, team in sorted(all_unique):
        cache_key = f"{name}|{team}"
        if cache_key not in mlb_id_cache:
            lookup_mlb_id(name, team, mlb_id_cache)
            new_lookups += 1
            if new_lookups % 20 == 0:
                time_module.sleep(0.5)  # Rate limit
                print(f"  Looked up {new_lookups} players...")

    # Save cache incrementally
    save_mlb_id_cache(mlb_id_cache, mlb_id_cache_path)
    print(f"  MLB ID cache: {len(mlb_id_cache)} entries ({new_lookups} new lookups)")

    # --- Exclude position players (anyone who threw EP/Eephus) ---
    ep_pitchers = set()
    for p in all_pitches:
        if p.get('Pitch Type') == 'EP':
            ep_pitchers.add((p['Pitcher'], p['PTeam']))
    if ep_pitchers:
        print(f"  Excluding {len(ep_pitchers)} position player(s): {', '.join(n for n, _ in ep_pitchers)}")

    # --- Count total pitches per pitcher (for usage%) ---
    pitcher_total = defaultdict(int)
    for p in all_pitches:
        if (p['Pitcher'], p['PTeam']) in ep_pitchers:
            continue
        if p.get('_roc_hitter_pitch'):
            continue  # Skip AAA pitchers facing ROC hitters
        pitcher_total[(p['Pitcher'], p['PTeam'])] += 1

    # --- Pitch Leaderboard: group by (Pitcher, PTeam, Pitch Type) ---
    pitch_groups = defaultdict(list)
    for p in all_pitches:
        if (p['Pitcher'], p['PTeam']) in ep_pitchers:
            continue
        if p.get('_roc_hitter_pitch'):
            continue  # Skip AAA pitchers facing ROC hitters
        key = (p['Pitcher'], p['PTeam'], p['Pitch Type'], p.get('Throws'))
        pitch_groups[key].append(p)

    pitch_leaderboard = []
    for (pitcher, team, pitch_type, throws), pitches in pitch_groups.items():
        if not pitch_type:
            continue

        total_for_pitcher = pitcher_total[(pitcher, team)]

        row = {
            'pitcher': pitcher,
            'team': team,
            'throws': throws,
            'pitchType': pitch_type,
            'count': len(pitches),
            'usagePct': round(len(pitches) / total_for_pitcher, 4) if total_for_pitcher > 0 else None,
            'mlbId': get_mlb_id(pitcher, team),
            '_isROC': team in AAA_TEAMS,
        }

        # Average metrics
        for col in METRIC_COLS:
            values = [safe_float(p.get(col)) for p in pitches]
            key_name = METRIC_KEYS[col]
            row[key_name] = round_metric(col, avg(values))

        # Max velocity
        velos = [safe_float(p.get('Velocity')) for p in pitches]
        velos = [v for v in velos if v is not None]
        row['maxVelo'] = round(max(velos), 1) if velos else None

        # Break Tilt (circular mean)
        tilt_minutes = [break_tilt_to_minutes(p.get('OTilt') or p.get('Break Tilt')) for p in pitches]
        tilt_minutes = [m for m in tilt_minutes if m is not None]
        avg_tilt = circular_mean_minutes(tilt_minutes)
        row['breakTilt'] = minutes_to_tilt_display(avg_tilt)
        row['breakTiltMinutes'] = avg_tilt

        row.update(compute_stats(pitches))
        row.update(compute_pitcher_batted_ball(pitches))
        row.update(compute_expected_stats(pitches))
        # RV/100 for this pitch type
        if row.get('runValue') is not None and row.get('count', 0) > 0:
            row['rv100'] = round(row['runValue'] / row['count'] * 100, 2)
        else:
            row['rv100'] = None
        pitch_leaderboard.append(row)

    # --- Fit VAA ~ PlateZ regression for normalized VAA (MLB only) ---
    vaa_plateZ_pairs = []
    for p in all_pitches:
        if p.get('_source', 'MLB') != 'MLB':
            continue  # Exclude ROC/AAA from regression
        vaa_val = safe_float(p.get('VAA'))
        pz_val = safe_float(p.get('PlateZ'))
        if vaa_val is not None and pz_val is not None:
            vaa_plateZ_pairs.append((pz_val, vaa_val))

    if len(vaa_plateZ_pairs) > 10:
        n_reg = len(vaa_plateZ_pairs)
        sum_x = sum(pair[0] for pair in vaa_plateZ_pairs)
        sum_y = sum(pair[1] for pair in vaa_plateZ_pairs)
        sum_xy = sum(pair[0] * pair[1] for pair in vaa_plateZ_pairs)
        sum_x2 = sum(pair[0] ** 2 for pair in vaa_plateZ_pairs)
        mean_x = sum_x / n_reg
        mean_y = sum_y / n_reg
        denom = sum_x2 - n_reg * mean_x ** 2
        if abs(denom) > 1e-10:
            vaa_slope = (sum_xy - n_reg * mean_x * mean_y) / denom
            vaa_intercept = mean_y - vaa_slope * mean_x
        else:
            vaa_slope = 0.0
            vaa_intercept = mean_y
        ss_res = sum((pair[1] - (vaa_slope * pair[0] + vaa_intercept)) ** 2 for pair in vaa_plateZ_pairs)
        ss_tot = sum((pair[1] - mean_y) ** 2 for pair in vaa_plateZ_pairs)
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        league_avg_plateZ = mean_x
        print(f"\nVAA ~ PlateZ regression: slope={vaa_slope:.4f}, intercept={vaa_intercept:.4f}, "
              f"R²={r_squared:.4f}, league avg PlateZ={league_avg_plateZ:.4f} (n={n_reg})")
    else:
        vaa_slope = 0.0
        vaa_intercept = 0.0
        league_avg_plateZ = 0.0
        print("\nWARNING: Not enough data for VAA ~ PlateZ regression")

    # Compute nVAA for each pitch leaderboard row
    for row in pitch_leaderboard:
        if row.get('vaa') is not None:
            key = (row['pitcher'], row['team'], row['pitchType'], row.get('throws'))
            pitches_for_row = pitch_groups[key]
            pz_vals = [safe_float(p.get('PlateZ')) for p in pitches_for_row]
            pz_vals = [v for v in pz_vals if v is not None]
            if pz_vals:
                avg_pz = sum(pz_vals) / len(pz_vals)
                row['nVAA'] = round(row['vaa'] - vaa_slope * (avg_pz - league_avg_plateZ), 2)
            else:
                row['nVAA'] = None
        else:
            row['nVAA'] = None

    # --- Fit HAA ~ PlateX regression for normalized HAA (MLB only) ---
    haa_plateX_pairs = []
    for p in all_pitches:
        if p.get('_source', 'MLB') != 'MLB':
            continue  # Exclude ROC/AAA from regression
        haa_val = safe_float(p.get('HAA'))
        px_val = safe_float(p.get('PlateX'))
        if haa_val is not None and px_val is not None:
            haa_plateX_pairs.append((px_val, haa_val))

    if len(haa_plateX_pairs) > 10:
        n_reg_h = len(haa_plateX_pairs)
        sum_x_h = sum(pair[0] for pair in haa_plateX_pairs)
        sum_y_h = sum(pair[1] for pair in haa_plateX_pairs)
        sum_xy_h = sum(pair[0] * pair[1] for pair in haa_plateX_pairs)
        sum_x2_h = sum(pair[0] ** 2 for pair in haa_plateX_pairs)
        mean_x_h = sum_x_h / n_reg_h
        mean_y_h = sum_y_h / n_reg_h
        denom_h = sum_x2_h - n_reg_h * mean_x_h ** 2
        if abs(denom_h) > 1e-10:
            haa_slope = (sum_xy_h - n_reg_h * mean_x_h * mean_y_h) / denom_h
            haa_intercept = mean_y_h - haa_slope * mean_x_h
        else:
            haa_slope = 0.0
            haa_intercept = mean_y_h
        ss_res_h = sum((pair[1] - (haa_slope * pair[0] + haa_intercept)) ** 2 for pair in haa_plateX_pairs)
        ss_tot_h = sum((pair[1] - mean_y_h) ** 2 for pair in haa_plateX_pairs)
        r_squared_h = 1 - ss_res_h / ss_tot_h if ss_tot_h > 0 else 0
        league_avg_plateX = mean_x_h
        print(f"HAA ~ PlateX regression: slope={haa_slope:.4f}, intercept={haa_intercept:.4f}, "
              f"R²={r_squared_h:.4f}, league avg PlateX={league_avg_plateX:.4f} (n={n_reg_h})")
    else:
        haa_slope = 0.0
        haa_intercept = 0.0
        league_avg_plateX = 0.0
        print("\nWARNING: Not enough data for HAA ~ PlateX regression")

    # Compute nHAA for each pitch leaderboard row
    for row in pitch_leaderboard:
        if row.get('haa') is not None:
            key = (row['pitcher'], row['team'], row['pitchType'], row.get('throws'))
            pitches_for_row = pitch_groups[key]
            px_vals = [safe_float(p.get('PlateX')) for p in pitches_for_row]
            px_vals = [v for v in px_vals if v is not None]
            if px_vals:
                avg_px = sum(px_vals) / len(px_vals)
                row['nHAA'] = round(row['haa'] - haa_slope * (avg_px - league_avg_plateX), 2)
            else:
                row['nHAA'] = None
        else:
            row['nHAA'] = None

    # --- Compute percentiles per pitch type ---
    pt_groups = defaultdict(list)
    for row in pitch_leaderboard:
        pt_groups[row['pitchType']].append(row)

    # CF pairs with FF for velocity, spin rate, VAA, HAA percentiles
    # For these metrics, CF and FF are computed together in a combined pool
    CF_FF_PAIRED_METRICS = {'velocity', 'spinRate', 'vaa', 'haa', 'nVAA', 'nHAA'}

    for metric in PITCH_PCTL_KEYS:
        if metric in CF_FF_PAIRED_METRICS:
            # Combined FF+CF pool for this metric
            ff_cf_rows = pt_groups.get('FF', []) + pt_groups.get('CF', [])
            if ff_cf_rows:
                compute_percentile_ranks_with_aaa(ff_cf_rows, metric, min_count=0)
            # All other pitch types get their own pool
            for pt, pt_rows in pt_groups.items():
                if pt not in ('FF', 'CF'):
                    compute_percentile_ranks_with_aaa(pt_rows, metric, min_count=0)
        else:
            for pt, pt_rows in pt_groups.items():
                compute_percentile_ranks_with_aaa(pt_rows, metric, min_count=0)

    # --- Invert VAA and nVAA percentiles for non-fastball pitch types ---
    # CF is paired with FF for VAA, so no inversion needed for CF either
    VAA_NO_INVERT_TYPES = {'FF', 'FC', 'CF'}
    for pt, pt_rows in pt_groups.items():
        if pt not in VAA_NO_INVERT_TYPES:
            for row in pt_rows:
                if row.get('vaa_pctl') is not None:
                    row['vaa_pctl'] = 100 - row['vaa_pctl']
                if row.get('nVAA_pctl') is not None:
                    row['nVAA_pctl'] = 100 - row['nVAA_pctl']

    # Invert wOBA/xBA/xSLG/xwOBA percentiles (lower is better for pitchers)
    for row in pitch_leaderboard:
        for stat in ('wOBA', 'xBA', 'xSLG', 'xwOBA'):
            pctl_key = stat + '_pctl'
            if row.get(pctl_key) is not None:
                row[pctl_key] = 100 - row[pctl_key]

    # --- Compute Pitch Tunneling Distances ---
    # For each pitcher, find primary fastball (FF/SI/CF with most pitches),
    # then compute tunnel distance (inches) from that fastball to each secondary pitch.
    # Tunnel point is ~23.5 feet from plate.
    FASTBALL_TYPES = {'FF', 'SI', 'CF'}
    GRAVITY = 32.174  # ft/s²
    TUNNEL_DIST_FROM_PLATE = 23.5  # feet — approximate tunnel point

    # Group pitch leaderboard rows by pitcher
    pitcher_pitch_map = defaultdict(list)
    for row in pitch_leaderboard:
        pk = row['pitcher'] + '|' + row['team']
        pitcher_pitch_map[pk].append(row)

    for pk, pt_rows in pitcher_pitch_map.items():
        # Find primary fastball
        fb_rows = [r for r in pt_rows if r['pitchType'] in FASTBALL_TYPES]
        if not fb_rows:
            for r in pt_rows:
                r['tunnelDist'] = None
            continue
        fb_row = max(fb_rows, key=lambda r: r['count'])

        fb_velo = fb_row.get('velocity')
        fb_ext = fb_row.get('extension')
        fb_relZ = fb_row.get('relPosZ')
        fb_relX = fb_row.get('relPosX')
        fb_ivb = fb_row.get('indVertBrk')
        fb_hb = fb_row.get('horzBrk')

        if fb_velo is None or fb_ext is None or fb_relZ is None or fb_relX is None:
            for r in pt_rows:
                r['tunnelDist'] = None
            continue

        # Estimate vertical/horizontal velocity components from movement
        # Release distance from plate
        fb_release_dist = 60.5 - fb_ext
        fb_velo_fps = fb_velo * 1.467  # mph → ft/s
        fb_flight_time = fb_release_dist / fb_velo_fps if fb_velo_fps > 0 else 0.4
        # Approximate initial vertical velocity: solve for vz given that ball drops from relZ
        # to ~2.5 ft (avg strike zone center) with IVB. IVB is total vertical break relative to gravity.
        # Simplified: use IVB/HB as total deviation in inches over full flight, compute rate.
        fb_ivb_ft = (fb_ivb or 0) / 12.0  # inches → feet
        fb_hb_ft = (fb_hb or 0) / 12.0

        # Time from release to tunnel point
        tunnel_travel = fb_release_dist - TUNNEL_DIST_FROM_PLATE
        fb_t_tunnel = tunnel_travel / fb_velo_fps if fb_velo_fps > 0 else 0.1
        # Fraction of total flight at tunnel point
        fb_frac = fb_t_tunnel / fb_flight_time if fb_flight_time > 0 else 0

        # Position at tunnel point (linear interpolation of movement)
        fb_z_tunnel = fb_relZ - (GRAVITY / 2) * fb_t_tunnel ** 2 + fb_ivb_ft * fb_frac
        fb_x_tunnel = fb_relX + fb_hb_ft * fb_frac

        # Mark fastball row
        fb_row['tunnelDist'] = 0.0

        # Compute for each secondary pitch
        for r in pt_rows:
            if r is fb_row:
                continue
            sec_velo = r.get('velocity')
            sec_ext = r.get('extension')
            sec_relZ = r.get('relPosZ')
            sec_relX = r.get('relPosX')
            sec_ivb = r.get('indVertBrk')
            sec_hb = r.get('horzBrk')

            if sec_velo is None or sec_ext is None or sec_relZ is None or sec_relX is None:
                r['tunnelDist'] = None
                continue

            sec_release_dist = 60.5 - sec_ext
            sec_velo_fps = sec_velo * 1.467
            sec_flight_time = sec_release_dist / sec_velo_fps if sec_velo_fps > 0 else 0.4
            sec_ivb_ft = (sec_ivb or 0) / 12.0
            sec_hb_ft = (sec_hb or 0) / 12.0

            sec_tunnel_travel = sec_release_dist - TUNNEL_DIST_FROM_PLATE
            sec_t_tunnel = sec_tunnel_travel / sec_velo_fps if sec_velo_fps > 0 else 0.1
            sec_frac = sec_t_tunnel / sec_flight_time if sec_flight_time > 0 else 0

            sec_z_tunnel = sec_relZ - (GRAVITY / 2) * sec_t_tunnel ** 2 + sec_ivb_ft * sec_frac
            sec_x_tunnel = sec_relX + sec_hb_ft * sec_frac

            # Euclidean distance in inches
            dist_ft = math.sqrt((fb_z_tunnel - sec_z_tunnel) ** 2 + (fb_x_tunnel - sec_x_tunnel) ** 2)
            r['tunnelDist'] = round(dist_ft * 12, 1)  # convert feet → inches

    print(f"  Computed tunnel distances for {len(pitcher_pitch_map)} pitchers")

    pitch_leaderboard.sort(key=lambda r: r['count'], reverse=True)
    print(f"Pitch leaderboard: {len(pitch_leaderboard)} rows")

    # --- Pitcher Leaderboard: group by (Pitcher, PTeam) ---
    pitcher_groups = defaultdict(list)
    for p in all_pitches:
        if (p['Pitcher'], p['PTeam']) in ep_pitchers:
            continue
        if p.get('_roc_hitter_pitch'):
            continue  # Skip AAA pitchers facing ROC hitters
        key = (p['Pitcher'], p['PTeam'], p.get('Throws'))
        pitcher_groups[key].append(p)

    PITCHER_METRIC_COLS = ['RelPosZ', 'RelPosX', 'Extension', 'ArmAngle', 'VAA', 'HAA', 'VRA', 'HRA']
    pitcher_leaderboard = []
    for (pitcher, team, throws), pitches in pitcher_groups.items():
        row = {
            'pitcher': pitcher,
            'team': team,
            'throws': throws,
            'count': len(pitches),
            'mlbId': get_mlb_id(pitcher, team),
            '_isROC': team in AAA_TEAMS,
        }
        for col in PITCHER_METRIC_COLS:
            values = [safe_float(p.get(col)) for p in pitches]
            key_name = METRIC_KEYS[col]
            row[key_name] = round_metric(col, avg(values))
        row.update(compute_stats(pitches))
        row.update(compute_pitcher_batted_ball(pitches))
        row.update(compute_expected_stats(pitches))

        # Fastball velo: average velo of most-used fastball (FF/SI/CF)
        fb_types = {'FF', 'SI', 'CF'}
        fb_pitches_by_type = defaultdict(list)
        for p in pitches:
            pt = p.get('Pitch Type')
            if pt in fb_types:
                v = safe_float(p.get('Velocity'))
                if v is not None:
                    fb_pitches_by_type[pt].append(v)
        if fb_pitches_by_type:
            primary_fb_type = max(fb_pitches_by_type, key=lambda t: len(fb_pitches_by_type[t]))
            fb_velos = fb_pitches_by_type[primary_fb_type]
            row['fbVelo'] = round(sum(fb_velos) / len(fb_velos), 1) if fb_velos else None
            row['primaryFbType'] = primary_fb_type
        else:
            row['fbVelo'] = None
            row['primaryFbType'] = None

        pitcher_leaderboard.append(row)

    # Recompute pitcher runValue as sum of rounded per-pitch-type runValues
    # so that the overall matches the sum of displayed per-pitch values
    pitch_rv_by_pitcher = {}
    for pr in pitch_leaderboard:
        pk = pr['pitcher'] + '|' + pr['team']
        if pr.get('runValue') is not None:
            if pk not in pitch_rv_by_pitcher:
                pitch_rv_by_pitcher[pk] = 0.0
            pitch_rv_by_pitcher[pk] += pr['runValue']
    for row in pitcher_leaderboard:
        pk = row['pitcher'] + '|' + row['team']
        if pk in pitch_rv_by_pitcher:
            row['runValue'] = round(pitch_rv_by_pitcher[pk], 1)

    # Compute RV/100 (run value per 100 pitches) for pitcher leaderboard
    for row in pitcher_leaderboard:
        if row.get('runValue') is not None and row.get('count', 0) > 0:
            row['rv100'] = round(row['runValue'] / row['count'] * 100, 2)
        else:
            row['rv100'] = None

    # Compute pitch mix entropy: -Σ(p × log₂(p)) for each pitcher's pitch usage distribution
    # Build usage fractions from pitch_leaderboard
    pitcher_usage = defaultdict(list)
    for pr in pitch_leaderboard:
        pk = pr['pitcher'] + '|' + pr['team']
        if pr.get('usagePct') is not None and pr['usagePct'] > 0:
            pitcher_usage[pk].append(pr['usagePct'])
    for row in pitcher_leaderboard:
        pk = row['pitcher'] + '|' + row['team']
        fracs = pitcher_usage.get(pk, [])
        if len(fracs) >= 2:
            entropy = -sum(p * math.log2(p) for p in fracs if p > 0)
            row['pitchEntropy'] = round(entropy, 2)
        else:
            row['pitchEntropy'] = None

    # Compute percentiles for pitcher leaderboard
    # All pitchers get percentiles (frontend qualifying logic controls coloring)
    PITCHER_METRIC_PCTL_KEYS = [METRIC_KEYS[c] for c in PITCHER_METRIC_COLS]
    EXPECTED_KEYS = ['wOBA', 'xBA', 'xSLG', 'xwOBA', 'xwOBAcon']
    EXPECTED_PITCHER_INVERT = {'wOBA', 'xBA', 'xSLG', 'xwOBA', 'xwOBAcon'}  # lower is better for pitchers
    for stat in STAT_KEYS + PITCHER_METRIC_PCTL_KEYS + PITCHER_BB_KEYS + EXPECTED_KEYS + ['fbVelo', 'runValue', 'rv100', 'pitchEntropy']:
        compute_percentile_ranks_with_aaa(pitcher_leaderboard, stat, min_count=0)

    for row in pitcher_leaderboard:
        for stat in PITCHER_INVERT_PCTL | PITCHER_BB_INVERT | EXPECTED_PITCHER_INVERT:
            pctl_key = stat + '_pctl'
            if row.get(pctl_key) is not None:
                row[pctl_key] = 100 - row[pctl_key]

    pitcher_leaderboard.sort(key=lambda r: r['count'], reverse=True)
    print(f"Pitcher leaderboard: {len(pitcher_leaderboard)} rows")

    # --- Pitch Details ---
    pitch_details = defaultdict(list)
    for p in all_pitches:
        pitcher = p.get('Pitcher')
        team = p.get('PTeam')
        if (pitcher, team) in ep_pitchers:
            continue
        pt = p.get('Pitch Type')
        ivb = safe_float(p.get('IndVertBrk'))
        hb = safe_float(p.get('HorzBrk'))
        velo = safe_float(p.get('Velocity'))
        spin = safe_float(p.get('Spin Rate'))
        tilt = p.get('OTilt') or p.get('Break Tilt')
        rel_x = safe_float(p.get('RelPosX'))
        rel_z = safe_float(p.get('RelPosZ'))
        if pitcher and pt and ivb is not None and hb is not None:
            detail = {
                'pt': pt,
                'ivb': round(ivb, 1),
                'hb': round(hb, 1),
            }
            if velo is not None:
                detail['v'] = round(velo, 1)
            if spin is not None:
                detail['sp'] = int(round(spin))
            if tilt and str(tilt).strip():
                detail['tl'] = str(tilt).strip()
            # Description (pitch outcome) — short codes for space efficiency
            desc_raw = p.get('Description', '')
            DESC_MAP = {
                'Swinging Strike': 'SS', 'Called Strike': 'CS', 'Foul': 'F',
                'In Play': 'IP', 'Ball': 'B', 'Hit By Pitch': 'HBP',
                'Intent Ball': 'IB', 'Pitchout': 'PO',
            }
            desc_code = DESC_MAP.get(desc_raw, '')
            if desc_code:
                detail['d'] = desc_code
            if rel_x is not None:
                detail['rx'] = round(rel_x, 2)
            if rel_z is not None:
                detail['rz'] = round(rel_z, 2)
            gd_val = normalize_date(p.get('Game Date'))
            if gd_val:
                detail['gd'] = gd_val
            px_val = safe_float(p.get('PlateX'))
            pz_val = safe_float(p.get('PlateZ'))
            szt_val = safe_float(p.get('SzTop'))
            szb_val = safe_float(p.get('SzBot'))
            bh_val = p.get('Bats')
            cnt_val = p.get('Count')
            if px_val is not None:
                detail['px'] = round(px_val, 2)
            if pz_val is not None:
                detail['pz'] = round(pz_val, 2)
            if szt_val is not None:
                detail['szt'] = round(szt_val, 2)
            if szb_val is not None:
                detail['szb'] = round(szb_val, 2)
            if bh_val:
                detail['bh'] = bh_val
            if cnt_val:
                detail['cnt'] = cnt_val
            aa_val = safe_float(p.get('ArmAngle'))
            if aa_val is not None:
                detail['aa'] = round(aa_val, 1)
            pitch_details[pitcher + '|' + (team or '')].append(detail)
    print(f"Pitch details: {sum(len(v) for v in pitch_details.values())} pitches for {len(pitch_details)} pitchers")

    # --- League Averages per pitch type (weighted by pitch count, MLB only) ---
    league_avgs = {}
    for pt, pt_rows_all in pt_groups.items():
        pt_rows = [r for r in pt_rows_all if not r.get('_isROC')]  # Exclude ROC from league averages
        avgs = {}
        total_count = sum(r.get('count', 0) for r in pt_rows)
        # Pitch metrics: weighted average by count
        for metric in list(METRIC_KEYS.values()):
            pairs = [(r[metric], r.get('count', 0)) for r in pt_rows if r.get(metric) is not None and r.get('count', 0) > 0]
            if pairs:
                avgs[metric] = round(sum(v * w for v, w in pairs) / sum(w for _, w in pairs), 2)
        # Rate stats: weighted average by count
        for stat in PITCH_STAT_KEYS:
            pairs = [(r[stat], r.get('count', 0)) for r in pt_rows if r.get(stat) is not None and r.get('count', 0) > 0]
            if pairs:
                avgs[stat] = round(sum(v * w for v, w in pairs) / sum(w for _, w in pairs), 4)
        tilts = [r['breakTiltMinutes'] for r in pt_rows if r.get('breakTiltMinutes') is not None]
        if tilts:
            avgs['breakTiltMinutes'] = circular_mean_minutes(tilts)
            avgs['breakTilt'] = minutes_to_tilt_display(avgs['breakTiltMinutes'])
        # Expected stats: weighted by PA (from compute_stats)
        for stat in ['xBA', 'xSLG', 'xwOBA']:
            pairs = [(r[stat], r.get('pa', 0)) for r in pt_rows if r.get(stat) is not None and r.get('pa', 0) > 0]
            if pairs:
                avgs[stat] = round(sum(v * w for v, w in pairs) / sum(w for _, w in pairs), 4)
        avgs['count'] = len(pt_rows)
        league_avgs[pt] = avgs

    # League averages for pitcher leaderboard (weighted by count/TBF, MLB only)
    pitcher_lb_mlb = [r for r in pitcher_leaderboard if not r.get('_isROC')]
    pitcher_league_avgs = {}
    for stat in STAT_KEYS + PITCHER_METRIC_PCTL_KEYS:
        # Use TBF as weight for rate stats, count (pitches) for pitch metrics
        weight_key = 'pa' if stat in ('kPct', 'bbPct', 'kbbPct', 'babip') else 'count'
        pairs = [(r[stat], r.get(weight_key, 0)) for r in pitcher_lb_mlb if r.get(stat) is not None and r.get(weight_key, 0) > 0]
        if pairs:
            pitcher_league_avgs[stat] = round(sum(v * w for v, w in pairs) / sum(w for _, w in pairs), 4)
    # ERA league avg computed after boxscore merge (ERA not available yet at this point)
    # Batted ball stats: weighted by nBip
    for stat in PITCHER_BB_KEYS:
        pairs = [(r[stat], r.get('nBip', 0)) for r in pitcher_lb_mlb if r.get(stat) is not None and r.get('nBip', 0) > 0]
        if pairs:
            pitcher_league_avgs[stat] = round(sum(v * w for v, w in pairs) / sum(w for _, w in pairs), 4)
    # Expected stats: weighted by PA
    for stat in EXPECTED_KEYS:
        pairs = [(r[stat], r.get('pa', 0)) for r in pitcher_lb_mlb if r.get(stat) is not None and r.get('pa', 0) > 0]
        if pairs:
            pitcher_league_avgs[stat] = round(sum(v * w for v, w in pairs) / sum(w for _, w in pairs), 4)
    pitcher_league_avgs['count'] = len(pitcher_lb_mlb)

    # ======================================================================
    #  HITTER LEADERBOARD
    # ======================================================================
    print(f"\n--- Hitter Leaderboard ({label}) ---")

    hitter_groups = defaultdict(list)
    for p in all_pitches:
        if p.get('_roc_pitcher_pitch'):
            continue  # Skip AAA hitters facing ROC pitchers
        batter = p.get('Batter')
        b_team = p.get('BTeam')
        if batter and b_team and b_team in ALL_TEAMS:
            hitter_groups[(batter, b_team)].append(p)

    # --- Compute SACQ zone table (league-wide LA × spray → wOBA) ---
    LA_BINS = [(-999, 0), (0, 5), (5, 10), (10, 15), (15, 20), (20, 25),
               (25, 30), (30, 35), (35, 40), (40, 50), (50, 999)]
    SACQ_MIN_BIP = 20
    SACQ_QUALITY_THRESHOLD = 0.500

    # Collect all BIPs with spray + wOBA data (MLB only — exclude ROC/AAA pitches)
    sacq_bins = {}  # (spray_dir, la_bin_idx) → {'woba_sum', 'woba_denom', 'xwoba_sum', 'xwoba_count', 'count'}
    for p in all_pitches:
        if p.get('_source', 'MLB') != 'MLB':
            continue  # Exclude ROC/AAA pitches from SACQ zone computation
        bb_type = p.get('BBType')
        if not bb_type or bb_type in BUNT_BB_TYPES:
            continue
        hc_x = safe_float(p.get('HC_X'))
        hc_y = safe_float(p.get('HC_Y'))
        la = safe_float(p.get('LaunchAngle'))
        woba_val = safe_float(p.get('wOBAval'))
        woba_dom = safe_float(p.get('wOBAdom'))
        xwoba_val = safe_float(p.get('xwOBA'))
        bats = p.get('Bats')
        if la is None or hc_x is None or hc_y is None or not bats:
            continue
        angle = spray_angle(hc_x, hc_y)
        direction = spray_direction(angle, bats)
        if not direction:
            continue
        # Find LA bin
        la_bin_idx = None
        for bi, (lo, hi) in enumerate(LA_BINS):
            if lo <= la < hi:
                la_bin_idx = bi
                break
        if la_bin_idx is None:
            continue
        key = (direction, la_bin_idx)
        if key not in sacq_bins:
            sacq_bins[key] = {'woba_sum': 0.0, 'woba_denom': 0.0, 'xwoba_sum': 0.0, 'xwoba_count': 0, 'count': 0}
        sacq_bins[key]['count'] += 1
        if woba_val is not None and woba_dom is not None and woba_dom > 0:
            sacq_bins[key]['woba_sum'] += woba_val
            sacq_bins[key]['woba_denom'] += woba_dom
        if xwoba_val is not None:
            sacq_bins[key]['xwoba_sum'] += xwoba_val
            sacq_bins[key]['xwoba_count'] += 1

    # Compute wOBA and xwOBAcon per bin, flag quality bins
    sacq_zone_table = {}
    for key, data in sacq_bins.items():
        woba = data['woba_sum'] / data['woba_denom'] if data['woba_denom'] > 0 else None
        xwobacon = data['xwoba_sum'] / data['xwoba_count'] if data['xwoba_count'] > 0 else None
        quality = (data['count'] >= SACQ_MIN_BIP and woba is not None and woba >= SACQ_QUALITY_THRESHOLD)
        sacq_zone_table[key] = {
            'woba': round(woba, 3) if woba is not None else None,
            'xwobacon': round(xwobacon, 3) if xwobacon is not None else None,
            'quality': quality,
            'count': data['count'],
        }

    # Build serializable zone data for frontend
    sacq_zones_output = []
    for (direction, la_bin_idx), info in sorted(sacq_zone_table.items(), key=lambda x: (x[0][0], x[0][1])):
        lo, hi = LA_BINS[la_bin_idx]
        sacq_zones_output.append({
            'spray': direction,
            'laMin': lo if lo > -999 else None,
            'laMax': hi if hi < 999 else None,
            'laBin': la_bin_idx,
            'woba': info['woba'],
            'xwobacon': info['xwobacon'],
            'quality': info['quality'],
            'count': info['count'],
        })
    print(f"  SACQ zones: {len(sacq_zones_output)} bins, "
          f"{sum(1 for z in sacq_zones_output if z['quality'])} quality bins")

    hitter_leaderboard = []
    for (hitter, team), pitches in hitter_groups.items():
        stands_set = set(p.get('Bats') for p in pitches if p.get('Bats'))
        if len(stands_set) > 1:
            stands = 'S'
        elif len(stands_set) == 1:
            stands = stands_set.pop()
        else:
            stands = None

        row = {
            'hitter': hitter,
            'team': team,
            'stands': stands,
            'count': len(pitches),
            'mlbId': get_mlb_id(hitter, team),
            '_isROC': team in AAA_TEAMS,
        }
        row.update(compute_hitter_stats(pitches))
        row.update(compute_expected_stats(pitches))

        # Compute SACQ% and xwOBAsp for this hitter
        sacq_quality_bips = 0
        sacq_eligible_bips = 0
        xwobasp_sum = 0.0
        xwobasp_count = 0
        for p in pitches:
            bb_type = p.get('BBType')
            if not bb_type or bb_type in BUNT_BB_TYPES:
                continue
            hc_x = safe_float(p.get('HC_X'))
            hc_y = safe_float(p.get('HC_Y'))
            la_val = safe_float(p.get('LaunchAngle'))
            bats_val = p.get('Bats')
            if la_val is None or hc_x is None or hc_y is None or not bats_val:
                continue
            angle = spray_angle(hc_x, hc_y)
            direction = spray_direction(angle, bats_val)
            if not direction:
                continue
            la_bin_idx = None
            for bi, (lo, hi) in enumerate(LA_BINS):
                if lo <= la_val < hi:
                    la_bin_idx = bi
                    break
            if la_bin_idx is None:
                continue
            zone_key = (direction, la_bin_idx)
            zone_info = sacq_zone_table.get(zone_key)
            if zone_info and zone_info['count'] >= SACQ_MIN_BIP and zone_info['woba'] is not None:
                sacq_eligible_bips += 1
                if zone_info['quality']:
                    sacq_quality_bips += 1
                # xwOBAsp: accumulate the zone's league-avg wOBA for this BIP
                xwobasp_sum += zone_info['woba']
                xwobasp_count += 1
        row['sacqPct'] = round(sacq_quality_bips / sacq_eligible_bips, 4) if sacq_eligible_bips > 0 else None
        row['xwOBAsp'] = round(xwobasp_sum / xwobasp_count, 3) if xwobasp_count > 0 else None

        hitter_leaderboard.append(row)

    # --- Merge Sprint Speed from Baseball Savant ---
    sprint_speeds = fetch_sprint_speed()
    sprint_merged = 0
    for row in hitter_leaderboard:
        mlb_id = row.get('mlbId')
        if mlb_id and mlb_id in sprint_speeds:
            row['sprintSpeed'] = sprint_speeds[mlb_id]
            sprint_merged += 1
        else:
            row['sprintSpeed'] = None
    print(f"  Sprint speed merged for {sprint_merged}/{len(hitter_leaderboard)} hitters")

    # Flag hitters with sufficient BIP for batted ball percentile qualification
    for row in hitter_leaderboard:
        row['bipQual'] = (row.get('nBip') or 0) >= 20

    # BIP-dependent stats require min 20 BIP for percentile pool
    HITTER_BIP_PCTL_STATS = {
        'avgEVAll', 'medEV', 'ev75', 'maxEV', 'medLA',
        'hardHitPct', 'barrelPct', 'laSweetSpotPct', 'sacqPct',
        'xBA', 'xSLG', 'xwOBA', 'xwOBAcon', 'xwOBAsp',
        'babip', 'gbPct', 'ldPct', 'fbPct', 'puPct', 'hrFbPct',
        'pullPct', 'middlePct', 'oppoPct', 'airPullPct',
    }
    for stat in HITTER_STAT_KEYS + EXPECTED_KEYS:
        if stat in HITTER_BIP_PCTL_STATS:
            compute_percentile_ranks_with_aaa(hitter_leaderboard, stat, min_count=20, count_key='nBip')
        else:
            compute_percentile_ranks_with_aaa(hitter_leaderboard, stat)

    for row in hitter_leaderboard:
        for stat in HITTER_INVERT_PCTL:
            pctl_key = stat + '_pctl'
            if row.get(pctl_key) is not None:
                row[pctl_key] = 100 - row[pctl_key]

    hitter_leaderboard.sort(key=lambda r: r.get('pa', 0), reverse=True)
    print(f"Hitter leaderboard: {len(hitter_leaderboard)} rows")

    # --- Hitter pitch details ---
    hitter_pitch_details = {}
    for (hitter, team), pitches in hitter_groups.items():
        pt_map = defaultdict(list)
        for p in pitches:
            pt = p.get('Pitch Type')
            if pt:
                pt_map[pt].append(p)

        details = []
        for pt, pt_pitches in sorted(pt_map.items()):
            entry = {
                'pitchType': pt,
                'count': len(pt_pitches),
            }
            entry.update(compute_hitter_stats(pt_pitches))
            details.append(entry)
        details.sort(key=lambda x: x['count'], reverse=True)
        hitter_pitch_details[hitter + '|' + (team or '')] = details

    # --- Hitter pitch-type leaderboard ---
    HITTER_PITCH_PCTL_KEYS = [
        'avg', 'slg', 'iso',
        'wOBA', 'xBA', 'xSLG', 'xwOBA',
        'medEV', 'ev75', 'maxEV', 'medLA', 'hardHitPct', 'barrelPct', 'laSweetSpotPct',
        'gbPct', 'ldPct', 'fbPct', 'hrFbPct',
        'pullPct', 'oppoPct',
        'swingPct', 'izSwingPct', 'chasePct', 'contactPct', 'izContactPct', 'whiffPct',
    ]
    HITTER_PITCH_INVERT_PCTL = {'swingPct', 'chasePct', 'whiffPct', 'gbPct'}

    PITCH_CATEGORIES = {
        'Hard': ['FF', 'SI', 'CF'],
        'Breaking': ['FC', 'SL', 'ST', 'CU', 'SV'],
        'Offspeed': ['CH', 'FS', 'KN'],
    }

    hitter_pitch_leaderboard = []
    for (hitter, team), pitches in hitter_groups.items():
        total_count = len(pitches)
        stands_set = set(p.get('Bats') for p in pitches if p.get('Bats'))
        stands = 'S' if len(stands_set) > 1 else (stands_set.pop() if stands_set else None)

        pt_map = defaultdict(list)
        for p in pitches:
            pt = p.get('Pitch Type')
            if pt:
                pt_map[pt].append(p)

        is_roc = team in AAA_TEAMS
        for pt, pt_pitches in pt_map.items():
            row = {
                'hitter': hitter,
                'team': team,
                'stands': stands,
                'pitchType': pt,
                'count': len(pt_pitches),
                'seenPct': round(len(pt_pitches) / total_count, 4) if total_count else 0,
                'mlbId': get_mlb_id(hitter, team),
                '_isROC': is_roc,
            }
            row.update(compute_hitter_stats(pt_pitches))
            row.update(compute_expected_stats(pt_pitches))
            hitter_pitch_leaderboard.append(row)

        row_all = {
            'hitter': hitter,
            'team': team,
            'stands': stands,
            'pitchType': 'All',
            'count': total_count,
            'seenPct': 1.0,
            'mlbId': get_mlb_id(hitter, team),
            '_isROC': is_roc,
        }
        row_all.update(compute_hitter_stats(pitches))
        row_all.update(compute_expected_stats(pitches))
        hitter_pitch_leaderboard.append(row_all)

        for cat_name, cat_types in PITCH_CATEGORIES.items():
            cat_pitches = []
            cat_seen = 0.0
            for ct in cat_types:
                if ct in pt_map:
                    cat_pitches.extend(pt_map[ct])
                    cat_seen += len(pt_map[ct]) / total_count if total_count else 0
            if len(cat_pitches) > 0:
                row_cat = {
                    'hitter': hitter,
                    'team': team,
                    'stands': stands,
                    'pitchType': cat_name,
                    'count': len(cat_pitches),
                    'seenPct': round(cat_seen, 4),
                    'mlbId': get_mlb_id(hitter, team),
                    '_isROC': is_roc,
                }
                row_cat.update(compute_hitter_stats(cat_pitches))
                row_cat.update(compute_expected_stats(cat_pitches))
                hitter_pitch_leaderboard.append(row_cat)

    # Compute percentiles per pitch type for hitter pitch LB
    hpt_groups = defaultdict(list)
    for row in hitter_pitch_leaderboard:
        hpt_groups[row['pitchType']].append(row)

    HITTER_PITCH_BIP_PCTL_STATS = {
        'avg', 'slg', 'iso',
        'wOBA', 'xBA', 'xSLG', 'xwOBA',
        'medEV', 'ev75', 'maxEV', 'medLA', 'hardHitPct', 'barrelPct', 'laSweetSpotPct',
        'gbPct', 'ldPct', 'fbPct', 'hrFbPct', 'pullPct', 'oppoPct',
    }
    for pt, pt_rows in hpt_groups.items():
        for stat in HITTER_PITCH_PCTL_KEYS:
            if stat in HITTER_PITCH_BIP_PCTL_STATS:
                compute_percentile_ranks_with_aaa(pt_rows, stat, min_count=20, count_key='nBip')
            else:
                compute_percentile_ranks_with_aaa(pt_rows, stat, min_count=0)

    for row in hitter_pitch_leaderboard:
        for stat in HITTER_PITCH_INVERT_PCTL:
            pctl_key = stat + '_pctl'
            if row.get(pctl_key) is not None:
                row[pctl_key] = 100 - row[pctl_key]

    hitter_pitch_leaderboard.sort(key=lambda r: r.get('count', 0), reverse=True)
    print(f"Hitter pitch leaderboard: {len(hitter_pitch_leaderboard)} rows")

    # Hitter league averages (weighted by PA for rate stats, nBip for batted ball stats, MLB only)
    hitter_lb_mlb = [r for r in hitter_leaderboard if not r.get('_isROC')]
    hitter_league_avgs = {}
    # Rate stats weighted by PA
    pa_stats = {'avg', 'obp', 'slg', 'ops', 'iso', 'babip', 'kPct', 'bbPct', 'hrFbPct',
                'wOBA', 'xBA', 'xSLG', 'xwOBA',
                'swingPct', 'izSwingPct', 'chasePct', 'izSwChase', 'contactPct', 'izContactPct', 'whiffPct'}
    # Batted ball stats weighted by nBip
    bip_stats = {'avgEVAll', 'medEV', 'ev75', 'maxEV', 'medLA', 'hardHitPct', 'barrelPct',
                 'laSweetSpotPct', 'sacqPct', 'xwOBAcon', 'xwOBAsp',
                 'gbPct', 'ldPct', 'fbPct', 'puPct',
                 'pullPct', 'middlePct', 'oppoPct', 'airPullPct'}
    for stat in HITTER_STAT_KEYS:
        if stat in pa_stats:
            weight_key = 'pa'
        elif stat in bip_stats:
            weight_key = 'nBip'
        else:
            weight_key = 'pa'  # default
        pairs = [(r[stat], r.get(weight_key, 0)) for r in hitter_lb_mlb if r.get(stat) is not None and r.get(weight_key, 0) > 0]
        if pairs:
            hitter_league_avgs[stat] = round(sum(v * w for v, w in pairs) / sum(w for _, w in pairs), 4)
    hitter_league_avgs['count'] = len(hitter_lb_mlb)

    # --- Metadata ---
    metadata = {
        'teams': all_teams,
        'pitchTypes': all_pitch_types,
        'generatedAt': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'totalPitches': len([p for p in all_pitches if p.get('_source', 'MLB') == 'MLB']),
        'totalPitchers': len(pitcher_lb_mlb),
        'totalHitters': len(hitter_lb_mlb),
        'rocTeams': sorted(AAA_TEAMS),
        'leagueAverages': league_avgs,
        'pitcherLeagueAverages': pitcher_league_avgs,
        'hitterLeagueAverages': hitter_league_avgs,
        'vaaRegression': {
            'slope': round(vaa_slope, 6),
            'intercept': round(vaa_intercept, 6),
            'leagueAvgPlateZ': round(league_avg_plateZ, 6),
        },
        'haaRegression': {
            'slope': round(haa_slope, 6),
            'intercept': round(haa_intercept, 6),
            'leagueAvgPlateX': round(league_avg_plateX, 6),
        },
        'sacqZones': sacq_zones_output,
    }

    # --- Generate micro-aggregate data ---
    print(f"\n--- Generating micro-aggregate data ({label}) ---")
    micro_data = generate_micro_data(all_pitches)
    print(f"  micro_data: {len(micro_data['pitcherMicro'])} pitcher, "
          f"{len(micro_data['pitchMicro'])} pitch, "
          f"{len(micro_data['hitterMicro'])} hitter micro-aggs, "
          f"{len(micro_data['pitcherBip'])} pitcher BIP, "
          f"{len(micro_data['hitterBip'])} hitter BIP records")

    # --- Boxscore Data: G, GS, IP, W, L, SV, HLD, TBF, ERA, HR/9 for pitchers; G, PA, AB, TB, SB, CS for hitters ---
    mlb_game_dates = sorted(set(normalize_date(p.get('Game Date')) for p in all_pitches
                                if normalize_date(p.get('Game Date')) and p.get('_source', 'MLB') == 'MLB'))
    game_dates = mlb_game_dates  # Used later for FIP/ERA calculations
    if mlb_game_dates:
        print(f"\n--- Fetching boxscore data ({label}) ---")
        pitcher_box, hitter_box, pitcher_id_map, hitter_id_map = fetch_and_aggregate_boxscores(mlb_game_dates)
        print(f"  Boxscore pitchers: {len(pitcher_box)}, hitters: {len(hitter_box)}")

        # Fetch MiLB boxscores for AAA teams (ROC, etc.)
        for milb_team in sorted(AAA_TEAMS):
            milb_dates = sorted(set(normalize_date(p.get('Game Date')) for p in all_pitches
                                    if normalize_date(p.get('Game Date')) and p.get('_source') in (milb_team, 'AAA')))
            if milb_dates:
                print(f"\n--- Fetching MiLB boxscore data for {milb_team} ({label}) ---")
                mp, mh, mpi, mhi = fetch_and_aggregate_milb_boxscores(milb_dates, milb_team)
                print(f"  MiLB boxscore {milb_team}: {len(mp)} pitchers, {len(mh)} hitters")
                pitcher_box.update(mp)
                hitter_box.update(mh)
                pitcher_id_map.update(mpi)
                hitter_id_map.update(mhi)

        # Merge pitcher boxscore stats
        for row in pitcher_leaderboard:
            key = row['pitcher'] + '|' + row['team']
            box = pitcher_box.get(key)
            # Fallback: match by MLB ID for compound last names (e.g. "Woods Richardson" vs "Richardson")
            if not box and row.get('mlbId'):
                alt_key = pitcher_id_map.get(row['mlbId'])
                if alt_key:
                    box = pitcher_box.get(alt_key)
            if box:
                row['g'] = box['g']
                row['gs'] = box['gs']
                row['ip'] = outs_to_ip_str(box['outs'])
                row['w'] = box['w']
                row['l'] = box['l']
                row['sv'] = box['sv']
                row['hld'] = box['hld']
                row['tbf'] = box['tbf']  # Override pitch-data TBF with official boxscore TBF
                ip_float = outs_to_ip_float(box['outs'])
                row['era'] = round(box['er'] * 9 / ip_float, 2) if ip_float > 0 else None
                row['hr9'] = round(box['hr'] * 9 / ip_float, 2) if ip_float > 0 else None
                row['_box_er'] = box['er']  # raw ER for league avg calc (includes 0-IP pitchers)
                # Store raw boxscore counts for FIP/xFIP/SIERA (computed below)
                row['_box'] = box
            else:
                row['g'] = None
                row['gs'] = None
                row['ip'] = None
                row['w'] = None
                row['l'] = None
                row['sv'] = None
                row['hld'] = None
                row['era'] = None
                row['hr9'] = None

        # Merge hitter boxscore stats
        for row in hitter_leaderboard:
            key = row['hitter'] + '|' + row['team']
            box = hitter_box.get(key)
            # Fallback: match by MLB ID for compound last names
            if not box and row.get('mlbId'):
                alt_key = hitter_id_map.get(row['mlbId'])
                if alt_key:
                    box = hitter_box.get(alt_key)
            if box:
                row['g'] = box['g']
                row['pa'] = box['pa']  # Override with official PA
                row['ab'] = box['ab']  # Override with official AB
                row['tb'] = box['tb']
                row['sb'] = box['sb']
                row['cs'] = box['cs']
                total_attempts = box['sb'] + box['cs']
                row['sbPct'] = round(box['sb'] / total_attempts * 100, 1) if total_attempts > 0 else None

                # Recompute batting stats using boxscore counts (fixes IBB not in pitch data)
                box_h = box.get('h', 0)
                box_bb = box.get('bb', 0)  # includes IBB
                box_ibb = box.get('ibb', 0)
                box_hbp = box.get('hbp', 0)
                box_sf = box.get('sacFlies', 0)
                box_ab = box['ab']
                box_pa = box['pa']
                box_hr = box.get('hr', 0)
                box_2b = box.get('doubles', 0)
                box_3b = box.get('triples', 0)
                box_1b = box_h - box_2b - box_3b - box_hr
                box_tb = box['tb']
                box_so = box.get('so', 0)

                # AVG, OBP, SLG, OPS
                row['avg'] = round(box_h / box_ab, 3) if box_ab > 0 else None
                obp_denom = box_ab + box_bb + box_hbp + box_sf
                row['obp'] = round((box_h + box_bb + box_hbp) / obp_denom, 3) if obp_denom > 0 else None
                row['slg'] = round(box_tb / box_ab, 3) if box_ab > 0 else None
                row['ops'] = round(row['obp'] + row['slg'], 3) if row['obp'] is not None and row['slg'] is not None else None
                row['iso'] = round(row['slg'] - row['avg'], 3) if row['slg'] is not None and row['avg'] is not None else None

                # Doubles, triples, HR, XBH from boxscore
                row['doubles'] = box_2b
                row['triples'] = box_3b
                row['hr'] = box_hr
                row['xbh'] = box_2b + box_3b + box_hr

                # K% and BB% (BB% excludes IBB, matching FanGraphs)
                box_ubb = box_bb - box_ibb
                row['kPct'] = round(box_so / box_pa, 4) if box_pa > 0 else None
                row['bbPct'] = round(box_ubb / box_pa, 4) if box_pa > 0 else None

                # BABIP = (H - HR) / (AB - K - HR + SF)
                babip_denom = box_ab - box_so - box_hr + box_sf
                row['babip'] = round((box_h - box_hr) / babip_denom, 3) if babip_denom > 0 else None

                # wOBA from boxscore counts + FanGraphs Guts weights
                if WOBA_WEIGHTS:
                    woba_denom = box_ab + box_ubb + box_sf + box_hbp
                    if woba_denom > 0:
                        woba_num = (WOBA_WEIGHTS['BB'] * box_ubb + WOBA_WEIGHTS['HBP'] * box_hbp +
                                    WOBA_WEIGHTS['1B'] * box_1b + WOBA_WEIGHTS['2B'] * box_2b +
                                    WOBA_WEIGHTS['3B'] * box_3b + WOBA_WEIGHTS['HR'] * box_hr)
                        row['wOBA'] = round(woba_num / woba_denom, 3)
                    else:
                        row['wOBA'] = None
            else:
                row['g'] = None
                row['tb'] = None
                row['sb'] = None
                row['cs'] = None
                row['sbPct'] = None

    # Compute wRC and wRC+ for each hitter (after boxscore merge so wOBA is from official stats)
    # wRC  = (((wOBA - lgWOBA) / wOBAScale) + lgRPA) * PA
    # wRC+ = ((wRAA/PA + lgRPA) + (lgRPA - PF * lgRPA)) / lgR/PA * 100
    if GUTS_EXTRA:
        woba_scale = GUTS_EXTRA['wOBAScale']
        lg_woba = GUTS_EXTRA['lgWOBA']
        lg_rpa = GUTS_EXTRA['lgRPA']
        park_factors = PARK_FACTORS or {}
        for row in hitter_leaderboard:
            woba = row.get('wOBA')
            pa = row.get('pa') or 0
            if woba is not None and pa > 0 and woba_scale > 0:
                wraa_per_pa = (woba - lg_woba) / woba_scale
                row['wRC'] = round((wraa_per_pa + lg_rpa) * pa, 2)
                # wRC+
                pf = park_factors.get(row['team'], 1.0)
                numerator = wraa_per_pa + lg_rpa + (lg_rpa - pf * lg_rpa)
                if lg_rpa > 0:
                    row['wRCplus'] = round(numerator / lg_rpa * 100)
                else:
                    row['wRCplus'] = None
                # xWRC+ (same formula but using xwOBA instead of wOBA)
                xwoba = row.get('xwOBA')
                if xwoba is not None:
                    xwraa_per_pa = (xwoba - lg_woba) / woba_scale
                    xnumerator = xwraa_per_pa + lg_rpa + (lg_rpa - pf * lg_rpa)
                    row['xWRCplus'] = round(xnumerator / lg_rpa * 100) if lg_rpa > 0 else None
                else:
                    row['xWRCplus'] = None
            else:
                row['wRC'] = None
                row['wRCplus'] = None
                row['xWRCplus'] = None

    # Compute total ER and outs for league ERA (needed for SIERA constant calibration)
    # Use ALL MLB pitchers from boxscore data (including EP pitchers excluded from leaderboard)
    # Exclude MiLB teams from league-wide calculations
    total_outs = 0
    total_er = 0
    for box_key, box in pitcher_box.items():
        # box_key format: "Name|TEAM" — skip MiLB teams
        box_team = box_key.split('|')[-1] if '|' in box_key else ''
        if box_team in AAA_TEAMS:
            continue
        total_outs += box.get('outs', 0)
        total_er += box.get('er', 0)

    # --- Compute FIP, xFIP, SIERA ---
    # FIP_CONSTANT and WOBA_WEIGHTS are set globally from FanGraphs Guts page

    # Compute league HR/FB% for xFIP
    # FB includes popups (fly_ball + popup from Statcast BBType)
    # HR from ALL MLB pitchers' boxscore data (including EP pitchers excluded from leaderboard)
    total_hr_lg = sum(box['hr'] for k, box in pitcher_box.items()
                      if k.split('|')[-1] not in AAA_TEAMS)
    total_fb_lg = 0
    for row in pitcher_leaderboard:
        if row.get('_isROC'):
            continue
        n_bip = row.get('nBip', 0) or 0
        if n_bip > 0:
            fb_pct = row.get('fbPct') or 0
            pu_pct = row.get('puPct') or 0
            total_fb_lg += round((fb_pct + pu_pct) * n_bip)
    lg_hr_fb = total_hr_lg / total_fb_lg if total_fb_lg > 0 else 0.105  # fallback to historical avg
    print(f"  League HR/FB%: {lg_hr_fb:.3f} ({total_hr_lg} HR / {total_fb_lg} FB+PU)")

    # First pass: compute FIP, xFIP, and raw SIERA (without constant) for each pitcher
    siera_ip_pairs = []  # (raw_siera, ip_float) for constant calibration
    for row in pitcher_leaderboard:
        box = row.get('_box')
        if not box:
            row['fip'] = None
            row['xFIP'] = None
            row['_siera_raw'] = None
            continue

        ip_float = outs_to_ip_float(box['outs'])
        hr = box['hr']
        bb = box['bb']
        hbp = box['hbp']
        so = box['so']
        tbf = box['tbf']

        # FIP = ((13*HR)+(3*(BB+HBP))-(2*K))/IP + constant
        if ip_float > 0:
            row['fip'] = round(((13 * hr + 3 * (bb + hbp) - 2 * so) / ip_float) + FIP_CONSTANT, 2)
        else:
            row['fip'] = None

        # xFIP: FB includes popups
        n_bip = row.get('nBip', 0) or 0
        fb_pct = row.get('fbPct') or 0
        pu_pct = row.get('puPct') or 0
        fb_count = round((fb_pct + pu_pct) * n_bip)  # fly balls + popups
        if ip_float > 0:
            expected_hr = fb_count * lg_hr_fb
            row['xFIP'] = round(((13 * expected_hr + 3 * (bb + hbp) - 2 * so) / ip_float) + FIP_CONSTANT, 2)
        else:
            row['xFIP'] = None

        # SIERA (raw, without constant — constant calibrated below)
        # netGB = GB - FB (where FB includes popups)
        # -/+ 4.920 term: minus if GB >= FB, plus if FB > GB
        gb_pct_val = row.get('gbPct') or 0
        gb_count = round(gb_pct_val * n_bip)
        if tbf > 0 and ip_float > 0:
            so_pa = so / tbf
            bb_pa = bb / tbf
            net_gb_pa = (gb_count - fb_count) / tbf
            # SP/RP ratio: fraction of IP as starter
            gs = box.get('gs', 0) or 0
            g = box.get('g', 1) or 1
            ip_sp_ratio = min(gs / g, 1.0) if g > 0 else 0.0
            # Sign for 4.920 term: minus if GB >= FB, plus if FB > GB
            sign_4920 = -1.0 if gb_count >= fb_count else 1.0
            raw_siera = (
                - 15.518 * so_pa
                + 9.146 * (so_pa ** 2)
                + 8.648 * bb_pa
                + 27.252 * (bb_pa ** 2)
                - 2.298 * net_gb_pa
                + sign_4920 * 4.920 * (net_gb_pa ** 2)
                - 4.036 * so_pa * bb_pa
                + 5.155 * so_pa * net_gb_pa
                + 4.546 * bb_pa * net_gb_pa
                + 0.367 * ip_sp_ratio
            )
            row['_siera_raw'] = raw_siera
            if not row.get('_isROC'):
                siera_ip_pairs.append((raw_siera, ip_float))
        else:
            row['_siera_raw'] = None

    # Calibrate SIERA constant so league-average SIERA = league-average ERA
    # (same principle as cFIP for FIP)
    if siera_ip_pairs and total_outs > 0:
        total_ip_siera = sum(ip for _, ip in siera_ip_pairs)
        weighted_raw = sum(raw * ip for raw, ip in siera_ip_pairs) / total_ip_siera if total_ip_siera > 0 else 0
        league_era = total_er * 9 / (total_outs / 3.0) if total_outs > 0 else 4.00
        siera_constant = league_era - weighted_raw
    else:
        siera_constant = 5.77  # fallback
    print(f"  SIERA constant: {siera_constant:.3f}")

    # Second pass: apply SIERA constant and clean up
    for row in pitcher_leaderboard:
        if row.get('_siera_raw') is not None:
            row['siera'] = round(row['_siera_raw'] + siera_constant, 2)
        else:
            row['siera'] = None
        row.pop('_siera_raw', None)
        row.pop('_box', None)

    # Compute percentiles for boxscore-derived stats (ERA, HR/9, FIP, xFIP, SIERA)
    # These are set AFTER the initial percentile pass, so need a second pass
    BOXSCORE_PCTL_KEYS = ['era', 'hr9', 'fip', 'xFIP', 'siera']
    BOXSCORE_INVERT = {'era', 'hr9', 'fip', 'xFIP', 'siera'}
    for stat in BOXSCORE_PCTL_KEYS:
        compute_percentile_ranks_with_aaa(pitcher_leaderboard, stat, min_count=0)
    for row in pitcher_leaderboard:
        for stat in BOXSCORE_INVERT:
            pctl_key = stat + '_pctl'
            if row.get(pctl_key) is not None:
                row[pctl_key] = 100 - row[pctl_key]

    # Compute ERA league average (total_outs and total_er computed above)
    if total_outs > 0:
        total_ip = total_outs / 3.0
        metadata['pitcherLeagueAverages']['era'] = round(total_er * 9 / total_ip, 2)

    # HR/9 league average — weighted by IP (MLB only)
    hr9_pairs = [(r['hr9'], float(r.get('ip', 0))) for r in pitcher_leaderboard
                 if r.get('hr9') is not None and r.get('ip') is not None and float(r['ip']) > 0 and not r.get('_isROC')]
    if hr9_pairs:
        total_w = sum(w for _, w in hr9_pairs)
        metadata['pitcherLeagueAverages']['hr9'] = round(sum(v * w for v, w in hr9_pairs) / total_w, 2) if total_w > 0 else None

    # FIP, xFIP, SIERA league averages — weighted by IP (MLB only)
    for stat in ['fip', 'xFIP', 'siera']:
        pairs = [(r[stat], float(r.get('ip', 0))) for r in pitcher_leaderboard
                 if r.get(stat) is not None and r.get('ip') is not None and float(r['ip']) > 0 and not r.get('_isROC')]
        if pairs:
            total_w = sum(w for _, w in pairs)
            metadata['pitcherLeagueAverages'][stat] = round(sum(v * w for v, w in pairs) / total_w, 2) if total_w > 0 else None

    return {
        'pitcher_leaderboard': pitcher_leaderboard,
        'pitch_leaderboard': pitch_leaderboard,
        'hitter_leaderboard': hitter_leaderboard,
        'hitter_pitch_leaderboard': hitter_pitch_leaderboard,
        'metadata': metadata,
        'micro_data': micro_data,
        'pitch_details': pitch_details,
        'hitter_pitch_details': hitter_pitch_details,
    }


def write_json_outputs(result, suffix):
    """Write JSON output files with the given suffix."""
    def strip_internal_keys(rows):
        return [{k: v for k, v in row.items() if not k.startswith('_')} for row in rows]
    with open(os.path.join(DATA_DIR, f'pitch_leaderboard{suffix}.json'), 'w') as f:
        json.dump(strip_internal_keys(result['pitch_leaderboard']), f)
    with open(os.path.join(DATA_DIR, f'pitcher_leaderboard{suffix}.json'), 'w') as f:
        json.dump(strip_internal_keys(result['pitcher_leaderboard']), f)
    with open(os.path.join(DATA_DIR, f'hitter_leaderboard{suffix}.json'), 'w') as f:
        json.dump(strip_internal_keys(result['hitter_leaderboard']), f)
    with open(os.path.join(DATA_DIR, f'hitter_pitch_leaderboard{suffix}.json'), 'w') as f:
        json.dump(strip_internal_keys(result['hitter_pitch_leaderboard']), f)
    with open(os.path.join(DATA_DIR, f'metadata{suffix}.json'), 'w') as f:
        json.dump(result['metadata'], f, indent=2)
    with open(os.path.join(DATA_DIR, f'micro_data{suffix}.json'), 'w') as f:
        json.dump(result['micro_data'], f, separators=(',', ':'))
    print(f"  Wrote JSON files with suffix '{suffix}'")


def write_embedded_js(st_result, rs_result):
    """Write data_embedded.js with window.ST_DATA and window.RS_DATA."""
    def build_data_obj(result):
        # Strip internal _-prefixed keys from all leaderboard rows
        def strip_internal(rows):
            return [{k: v for k, v in row.items() if not k.startswith('_')} for row in rows]
        # Strip _pctl keys from hitter pitch LB for embedding
        hitter_pitch_lb_slim = []
        for row in result['hitter_pitch_leaderboard']:
            slim = {k: v for k, v in row.items() if not k.endswith('_pctl') and not k.startswith('_')}
            hitter_pitch_lb_slim.append(slim)
        return {
            'pitcherData': strip_internal(result['pitcher_leaderboard']),
            'pitchData': strip_internal(result['pitch_leaderboard']),
            'hitterData': strip_internal(result['hitter_leaderboard']),
            'hitterPitchData': hitter_pitch_lb_slim,
            'metadata': result['metadata'],
            'microData': result['micro_data'],
            'pitchDetails': result['pitch_details'],
            'hitterPitchDetails': result['hitter_pitch_details'],
        }

    with open(os.path.join(DATA_DIR, 'data_embedded.js'), 'w') as f:
        f.write('// Auto-generated — do not edit\n')
        f.write('window.ST_DATA = ')
        json.dump(build_data_obj(st_result), f, separators=(',', ':'))
        f.write(';\n')
        f.write('window.RS_DATA = ')
        json.dump(build_data_obj(rs_result), f, separators=(',', ':'))
        f.write(';\n')
    print("  Wrote data_embedded.js")


def main():
    global WOBA_WEIGHTS, FIP_CONSTANT, GUTS_EXTRA, PARK_FACTORS
    os.makedirs(DATA_DIR, exist_ok=True)

    # Fetch live wOBA weights and FIP constant from FanGraphs
    print("Fetching FanGraphs Guts constants...")
    try:
        WOBA_WEIGHTS, FIP_CONSTANT, GUTS_EXTRA = fetch_guts_constants(2026)
    except Exception as e:
        print(f"  WARNING: Could not fetch Guts data ({e}), using fallback values")
        WOBA_WEIGHTS = WOBA_WEIGHTS_FALLBACK.copy()
        FIP_CONSTANT = FIP_CONSTANT_FALLBACK
        GUTS_EXTRA = {'wOBAScale': 1.2982, 'lgWOBA': 0.3088, 'lgRPA': 0.1142}

    # Fetch park factors
    print("Fetching FanGraphs park factors...")
    try:
        PARK_FACTORS = fetch_park_factors(2026)
    except Exception as e:
        print(f"  WARNING: Could not fetch park factors ({e}), defaulting to 1.0")
        PARK_FACTORS = {}

    # Connect to Google Sheets
    print("Connecting to Google Sheets...")
    scopes = ['https://www.googleapis.com/auth/spreadsheets.readonly']
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    gc = gspread.authorize(creds)

    # Read data separately
    # Skip ST spreadsheet — ST data is already cached and won't change
    print("\n=== Skipping Spring Training read (cached) ===")
    st_pitches = []

    print("\n=== Reading Regular Season data ===")
    rs_pitches = read_pitches_from_sheet(gc, SPREADSHEET_IDS['AL'])
    rs_pitches += read_pitches_from_sheet(gc, SPREADSHEET_IDS['NL'], extra_tabs={'ROC', 'AAA'})
    print(f"  Read {len(rs_pitches)} RS pitches")

    # Shared MLB ID cache
    mlb_id_cache_path = os.path.join(DATA_DIR, 'mlb_id_cache.json')
    mlb_id_cache = load_mlb_id_cache(mlb_id_cache_path)

    # Process each game type independently
    print("\n" + "=" * 60)
    print("=== Processing Spring Training ===")
    print("=" * 60)
    st_result = process_game_type(st_pitches, 'ST', mlb_id_cache, mlb_id_cache_path)

    print("\n" + "=" * 60)
    print("=== Processing Regular Season ===")
    print("=" * 60)
    rs_result = process_game_type(rs_pitches, 'RS', mlb_id_cache, mlb_id_cache_path)

    # Save shared MLB ID cache
    save_mlb_id_cache(mlb_id_cache, mlb_id_cache_path)

    # Write separate output files
    print("\n--- Writing output files ---")
    write_json_outputs(st_result, '_st')
    write_json_outputs(rs_result, '_rs')

    # Write combined embedded JS
    write_embedded_js(st_result, rs_result)

    print(f"\nOutput written to {DATA_DIR}/")
    print(f"  ST: {len(st_result['pitcher_leaderboard'])} pitchers, "
          f"{len(st_result['pitch_leaderboard'])} pitch rows, "
          f"{len(st_result['hitter_leaderboard'])} hitters")
    print(f"  RS: {len(rs_result['pitcher_leaderboard'])} pitchers, "
          f"{len(rs_result['pitch_leaderboard'])} pitch rows, "
          f"{len(rs_result['hitter_leaderboard'])} hitters")


if __name__ == '__main__':
    main()
