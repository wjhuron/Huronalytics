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

SPREADSHEET_ID = '1hNILKCGBuyQKV6KPWawgkS1cu72672TBALi8iNBbIFo'
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

PITCH_STAT_KEYS = ['izPct', 'swStrRate', 'swStrPct', 'cswPct', 'izWhiffPct', 'chasePct', 'gbPct', 'fpsPct']
STAT_KEYS = ['izPct', 'swStrRate', 'swStrPct', 'cswPct', 'izWhiffPct', 'chasePct', 'gbPct', 'kPct', 'bbPct', 'kbbPct', 'babip', 'fpsPct']

# Metrics that get percentile ranks on the pitch leaderboard (per pitch type)
PITCH_PCTL_KEYS = list(METRIC_KEYS.values()) + ['nVAA', 'nHAA'] + PITCH_STAT_KEYS

# Pitcher stats where lower is better (invert percentile)
PITCHER_INVERT_PCTL = {'bbPct', 'babip'}

# --- Hitter Leaderboard constants ---
SWING_DESCRIPTIONS = {'Swinging Strike', 'Foul', 'In Play'}
HITTER_STAT_KEYS = [
    # Hitter Stats tab
    'avg', 'obp', 'slg', 'ops', 'iso', 'babip', 'kPct', 'bbPct',
    # Batted Ball tab
    'medEV', 'ev75', 'maxEV', 'medLA', 'hardHitPct', 'barrelPct', 'laSweetSpotPct',
    'gbPct', 'ldPct', 'fbPct', 'puPct', 'hrFbPct',
    'pullPct', 'middlePct', 'oppoPct', 'airPullPct',
    # Swing Decisions tab
    'swingPct', 'izSwingPct', 'chasePct', 'izSwChase', 'contactPct', 'izContactPct', 'whiffPct',
]
# Hitter stats where lower is better (invert percentile so low value = red/high pctl)
HITTER_INVERT_PCTL = {'swingPct', 'chasePct', 'whiffPct', 'gbPct', 'kPct', 'puPct'}
BUNT_BB_TYPES = {'bunt', 'bunt_grounder', 'bunt_popup', 'bunt_line_drive'}

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
    n_bb = sum(1 for p in pa_pitches if p['Event'] in BB_EVENTS)
    n_hbp = sum(1 for p in pa_pitches if p['Event'] in HBP_EVENTS)
    n_sf = sum(1 for p in pa_pitches if p['Event'] in SF_EVENTS)
    n_sh = sum(1 for p in pa_pitches if p['Event'] in SH_EVENTS)
    n_ci = sum(1 for p in pa_pitches if p['Event'] in CI_EVENTS)
    n_ab = n_pa - n_bb - n_hbp - n_sf - n_sh - n_ci
    k_pct = n_k / n_pa if n_pa > 0 else None
    bb_pct = n_bb / n_pa if n_pa > 0 else None
    kbb_pct = round(k_pct - bb_pct, 4) if k_pct is not None and bb_pct is not None else None

    # BABIP = (H - HR) / (AB - K - HR + SF)
    babip_denom = n_ab - n_k - n_hr + n_sf
    babip = round((n_h - n_hr) / babip_denom, 3) if babip_denom > 0 else None

    # FPS% — first pitch strike rate (count == "0-0")
    # A strike = called strike, swinging strike, foul, or in play
    first_pitches = [p for p in pitches if p.get('Count') == '0-0']
    fps_strikes = sum(1 for p in first_pitches
                      if p.get('Description') in ('Called Strike', 'Swinging Strike', 'Foul', 'In Play'))
    fps_pct = fps_strikes / len(first_pitches) if first_pitches else None

    return {
        'pa': n_pa,
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
    """Statcast barrel definition.
    EV >= 98 mph, then LA must be within a range that expands with velocity."""
    if ev is None or la is None:
        return False
    if ev < 98:
        return False
    lower_la = max(8, 26 - (ev - 98))
    upper_la = min(50, 30 + 1.2 * (ev - 98))
    return lower_la <= la <= upper_la


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

    # Barrel rate
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
        empty.update({'pa': 0, 'nSwings': 0, 'nBip': 0,
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
    n_bb = sum(1 for p in pa_pitches if p['Event'] in BB_EVENTS)
    n_hbp = sum(1 for p in pa_pitches if p['Event'] in HBP_EVENTS)
    n_sf = sum(1 for p in pa_pitches if p['Event'] in SF_EVENTS)
    n_sh = sum(1 for p in pa_pitches if p['Event'] in SH_EVENTS)
    n_ci = sum(1 for p in pa_pitches if p['Event'] in CI_EVENTS)
    n_k = sum(1 for p in pa_pitches if p['Event'] in K_EVENTS)

    # AB = PA - BB - HBP - SF - SH - CI
    n_ab = n_pa - n_bb - n_hbp - n_sf - n_sh - n_ci

    # === Traditional batting stats ===
    batting_avg = round(n_h / n_ab, 3) if n_ab > 0 else None
    obp_denom = n_ab + n_bb + n_hbp + n_sf
    obp = round((n_h + n_bb + n_hbp) / obp_denom, 3) if obp_denom > 0 else None
    tb = n_1b + 2 * n_2b + 3 * n_3b + 4 * n_hr
    slg = round(tb / n_ab, 3) if n_ab > 0 else None
    ops = round(obp + slg, 3) if obp is not None and slg is not None else None
    xbh = n_2b + n_3b + n_hr

    # K% and BB% (per PA)
    k_pct = n_k / n_pa if n_pa > 0 else None
    bb_pct = n_bb / n_pa if n_pa > 0 else None

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

    # Barrels: need EV and LA on all batted balls
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
        if p.get('PTeam') and p['PTeam'] in MLB_TEAMS:
            team_set.add(p['PTeam'])
        d = normalize_date(p.get('Game Date'))
        if d:
            date_set.add(d)
        if p.get('Pitch Type'):
            pitch_type_set.add(p['Pitch Type'])

    for p in all_pitches:
        if p.get('Batter'):
            hitter_set.add(p['Batter'])
        if p.get('BTeam') and p['BTeam'] in MLB_TEAMS:
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
    pitcher_micro = defaultdict(lambda: [0] * 26)

    for p in all_pitches:
        pitcher = p.get('Pitcher')
        team = p.get('PTeam')
        throws = p.get('Throws')
        date = normalize_date(p.get('Game Date'))
        batter_hand = p.get('Bats')

        if not pitcher or not team or team not in MLB_TEAMS:
            continue
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
            if event in BB_EVENTS:       c[13] += 1  # bb
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
    # ==========================================================
    METRIC_OFFSETS = [
        ('Velocity', 22), ('Spin Rate', 24), ('IndVertBrk', 26),
        ('HorzBrk', 28), ('RelPosZ', 30), ('RelPosX', 32),
        ('Extension', 34), ('ArmAngle', 36), ('VAA', 38), ('HAA', 40),
        ('VRA', 42), ('HRA', 44), ('PlateZ', 46),
    ]

    pitch_micro = defaultdict(lambda: [0.0] * 51)

    for p in all_pitches:
        pitcher = p.get('Pitcher')
        team = p.get('PTeam')
        throws = p.get('Throws')
        pitch_type = p.get('Pitch Type')
        date = normalize_date(p.get('Game Date'))
        batter_hand = p.get('Bats')

        if not pitcher or not team or team not in MLB_TEAMS or not pitch_type:
            continue
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
        tilt_min = break_tilt_to_minutes(p.get('Break Tilt'))
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

        if not pitcher or not team or team not in MLB_TEAMS:
            continue
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

        if not batter or not team or team not in MLB_TEAMS:
            continue
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
            if event in BB_EVENTS:       c[6] += 1   # bb
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
            if is_barrel(ev, la):
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
        for i in range(36):
            val = c[i]
            row.append(round(val, 4) if isinstance(val, float) and val != int(val) else int(val))
        hitter_rows.append(row)

    # ==========================================================
    #  Hitter BIP records (for median EV, EV50, maxEV, medLA)
    #  [hitterIdx, dateIdx, pitcherHand, exitVelo, launchAngle]
    # ==========================================================
    hitter_bip_rows = []
    for p in all_pitches:
        batter = p.get('Batter')
        team = p.get('BTeam')
        date = normalize_date(p.get('Game Date'))
        pitcher_hand = p.get('Throws')
        bb_type = p.get('BBType')

        if not batter or not team or team not in MLB_TEAMS:
            continue
        if not date or not pitcher_hand:
            continue
        if not bb_type or bb_type in BUNT_BB_TYPES:
            continue

        ev = safe_float(p.get('ExitVelo'))
        la = safe_float(p.get('LaunchAngle'))
        if ev is None and la is None:
            continue

        hitter_bip_rows.append([
            hi_idx[batter],
            dt_idx[date],
            pitcher_hand,
            round(ev, 1) if ev is not None else None,
            round(la, 1) if la is not None else None,
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

        if not batter or not team or team not in MLB_TEAMS:
            continue
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
            if is_barrel(ev, la):
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
        for i in range(36):
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

        if not batter or not team or team not in MLB_TEAMS:
            continue
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
            'izSw', 'izWh', 'firstPitches', 'firstPitchStrikes', 'fb', 'nHrBip', 'ldHr', 'pu',
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
        'hitterBipCols': ['hitterIdx', 'dateIdx', 'pitcherHand', 'exitVelo', 'launchAngle'],
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
    in the percentile pool. Rows below the threshold get pctl = None."""
    pctl_key = metric_key + '_pctl'
    valid = [(i, rows[i][metric_key]) for i in range(len(rows))
             if rows[i].get(metric_key) is not None
             and (min_count == 0 or (rows[i].get(count_key) or 0) >= min_count)]

    if len(valid) < 2:
        for row in rows:
            row[pctl_key] = 50 if (row.get(metric_key) is not None
                                   and (min_count == 0 or (row.get(count_key) or 0) >= min_count)) else None
        return

    values = [v for _, v in valid]
    n = len(values)

    for idx, val in valid:
        below = sum(1 for x in values if x < val)
        equal = sum(1 for x in values if x == val)
        pctl = (below + 0.5 * (equal - 1)) / max(1, n - 1) * 100
        rows[idx][pctl_key] = max(0, min(100, round(pctl)))

    # Set None for rows that don't have the metric or don't qualify
    for row in rows:
        if pctl_key not in row:
            row[pctl_key] = None


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    print(f"Connecting to Google Sheets...")
    scopes = ['https://www.googleapis.com/auth/spreadsheets.readonly']
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)
    print(f"Spreadsheet: {sh.title} ({len(sh.worksheets())} sheets)")

    # Read all pitches from all sheets (including WBC as 31st team)
    all_pitches = []
    for i, ws in enumerate(sh.worksheets()):
        if ws.title not in MLB_TEAMS:
            print(f"  Skipping {ws.title} (not a team sheet)")
            continue
        print(f"  Reading {ws.title}...")
        if i > 0:
            time_module.sleep(1.5)
        rows = read_sheet_with_retry(ws)
        if not rows:
            continue
        header = rows[0]
        col_idx = {name: i for i, name in enumerate(header) if name}

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

            all_pitches.append(pitch)

    print(f"Read {len(all_pitches)} pitches from {len(sh.worksheets())} sheets")

    # --- Recompute InZone from PlateX/PlateZ/SzTop/SzBot with ball-radius adjustment ---
    for p in all_pitches:
        p['InZone'] = compute_in_zone(p)

    # --- Map non-MLB BTeams to MLB teams where possible ---
    # Build MLB team lookup: batter name → MLB team (only from pitches where BTeam is an MLB team)
    mlb_hitter_teams = {}
    for p in all_pitches:
        batter = p.get('Batter')
        b_team = p.get('BTeam')
        if batter and b_team and b_team in MLB_TEAMS:
            mlb_hitter_teams[batter] = b_team

    # Remap non-MLB BTeams in all_pitches (e.g., when BOS plays Venezuela in ST)
    remapped_count = 0
    for p in all_pitches:
        b_team = p.get('BTeam')
        if b_team and b_team not in MLB_TEAMS:
            batter = p.get('Batter')
            if batter and batter in mlb_hitter_teams:
                p['BTeam'] = mlb_hitter_teams[batter]
                remapped_count += 1
    if remapped_count:
        print(f"  Remapped {remapped_count} non-MLB BTeam entries in regular data")

    # Collect unique teams (MLB only) and pitch types
    all_teams = sorted(set(
        [p['PTeam'] for p in all_pitches if p.get('PTeam') and p['PTeam'] in MLB_TEAMS] +
        [p['BTeam'] for p in all_pitches if p.get('BTeam') and p['BTeam'] in MLB_TEAMS]
    ))
    all_pitch_types = sorted(set(p['Pitch Type'] for p in all_pitches if p.get('Pitch Type')))

    # --- Lookup MLB IDs for all pitchers and hitters ---
    print("\n--- Looking up MLB player IDs ---")
    mlb_id_cache_path = os.path.join(DATA_DIR, 'mlb_id_cache.json')
    if os.path.exists(mlb_id_cache_path):
        with open(mlb_id_cache_path, 'r') as f:
            mlb_id_cache = json.load(f)
    else:
        mlb_id_cache = {}

    # Team abbreviation → MLB API team ID mapping
    TEAM_ABBREV_TO_ID = {
        'ARI': 109, 'ATL': 144, 'BAL': 110, 'BOS': 111, 'CHC': 112,
        'CWS': 145, 'CIN': 113, 'CLE': 114, 'COL': 115, 'DET': 116,
        'HOU': 117, 'KCR': 118, 'LAA': 108, 'LAD': 119, 'MIA': 146,
        'MIL': 158, 'MIN': 142, 'NYM': 121, 'NYY': 147, 'ATH': 133,
        'PHI': 143, 'PIT': 134, 'SDP': 135, 'SFG': 137, 'SEA': 136,
        'STL': 138, 'TBR': 139, 'TEX': 140, 'TOR': 141, 'WSH': 120,
    }

    def lookup_mlb_id(player_name, team_abbrev):
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
            lookup_mlb_id(name, team)
            new_lookups += 1
            if new_lookups % 20 == 0:
                time_module.sleep(0.5)  # Rate limit
                print(f"  Looked up {new_lookups} players...")

    # Save cache
    with open(mlb_id_cache_path, 'w') as f:
        json.dump(mlb_id_cache, f, indent=2)
    print(f"  MLB ID cache: {len(mlb_id_cache)} entries ({new_lookups} new lookups)")

    # Helper to get cached MLB ID
    def get_mlb_id(name, team):
        return mlb_id_cache.get(f"{name}|{team}")

    # --- Count total pitches per pitcher (for usage%) ---
    pitcher_total = defaultdict(int)
    for p in all_pitches:
        pitcher_total[(p['Pitcher'], p['PTeam'])] += 1

    # --- Pitch Leaderboard: group by (Pitcher, PTeam, Pitch Type) ---
    pitch_groups = defaultdict(list)
    for p in all_pitches:
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
        tilt_minutes = [break_tilt_to_minutes(p.get('Break Tilt')) for p in pitches]
        tilt_minutes = [m for m in tilt_minutes if m is not None]
        avg_tilt = circular_mean_minutes(tilt_minutes)
        row['breakTilt'] = minutes_to_tilt_display(avg_tilt)
        row['breakTiltMinutes'] = avg_tilt

        row.update(compute_stats(pitches))
        pitch_leaderboard.append(row)

    # --- Fit VAA ~ PlateZ regression for normalized VAA ---
    # Collect all pitches with both VAA and PlateZ
    vaa_plateZ_pairs = []
    for p in all_pitches:
        vaa_val = safe_float(p.get('VAA'))
        pz_val = safe_float(p.get('PlateZ'))
        if vaa_val is not None and pz_val is not None:
            vaa_plateZ_pairs.append((pz_val, vaa_val))

    # Simple linear regression: VAA = slope * PlateZ + intercept
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
        # R-squared
        ss_res = sum((pair[1] - (vaa_slope * pair[0] + vaa_intercept)) ** 2 for pair in vaa_plateZ_pairs)
        ss_tot = sum((pair[1] - mean_y) ** 2 for pair in vaa_plateZ_pairs)
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        league_avg_plateZ = mean_x  # average PlateZ across all pitches
        print(f"\nVAA ~ PlateZ regression: slope={vaa_slope:.4f}, intercept={vaa_intercept:.4f}, "
              f"R²={r_squared:.4f}, league avg PlateZ={league_avg_plateZ:.4f} (n={n_reg})")
    else:
        vaa_slope = 0.0
        vaa_intercept = 0.0
        league_avg_plateZ = 0.0
        print("\nWARNING: Not enough data for VAA ~ PlateZ regression")

    # Compute nVAA for each pitch leaderboard row
    # nVAA = VAA - slope * (pitcher_avgPlateZ - league_avgPlateZ)
    # This adjusts VAA to what it would be at league-average pitch height
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

    # --- Fit HAA ~ PlateX regression for normalized HAA ---
    # Same approach as nVAA but for horizontal approach angle vs horizontal location
    haa_plateX_pairs = []
    for p in all_pitches:
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
    # nHAA = HAA - slope * (pitcher_avgPlateX - league_avgPlateX)
    # This adjusts HAA to what it would be at league-average horizontal location
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

    for pt, pt_rows in pt_groups.items():
        for metric in PITCH_PCTL_KEYS:
            compute_percentile_ranks(pt_rows, metric, min_count=15)

    # --- Invert VAA and nVAA percentiles for non-fastball pitch types ---
    # FF/FC: closer to 0 (e.g. -3) = red (default: higher value = higher pctl = red) — no inversion
    # All others: further from 0 (e.g. -10) = red (lower value = red) — invert
    VAA_NO_INVERT_TYPES = {'FF', 'FC'}
    for pt, pt_rows in pt_groups.items():
        if pt not in VAA_NO_INVERT_TYPES:
            for row in pt_rows:
                if row.get('vaa_pctl') is not None:
                    row['vaa_pctl'] = 100 - row['vaa_pctl']
                if row.get('nVAA_pctl') is not None:
                    row['nVAA_pctl'] = 100 - row['nVAA_pctl']

    # --- Compute Stuff Score ---
    # Average of velocity and spin rate percentiles within pitch type
    for row in pitch_leaderboard:
        vp = row.get('velocity_pctl')
        sp = row.get('spinRate_pctl')
        if vp is not None and sp is not None:
            row['stuffScore'] = round((vp + sp) / 2)
        else:
            row['stuffScore'] = None

    # Compute percentile of stuff score within pitch type
    for pt, pt_rows in pt_groups.items():
        compute_percentile_ranks(pt_rows, 'stuffScore')

    pitch_leaderboard.sort(key=lambda r: r['count'], reverse=True)
    print(f"Pitch leaderboard: {len(pitch_leaderboard)} rows")

    # --- Pitcher Leaderboard: group by (Pitcher, PTeam) ---
    pitcher_groups = defaultdict(list)
    for p in all_pitches:
        key = (p['Pitcher'], p['PTeam'], p.get('Throws'))
        pitcher_groups[key].append(p)

    PITCHER_METRIC_COLS = ['RelPosZ', 'RelPosX', 'Extension', 'VAA', 'HAA', 'VRA', 'HRA']
    pitcher_leaderboard = []
    for (pitcher, team, throws), pitches in pitcher_groups.items():
        row = {
            'pitcher': pitcher,
            'team': team,
            'throws': throws,
            'count': len(pitches),
            'mlbId': get_mlb_id(pitcher, team),
        }
        # Average release/approach metrics across all pitches for this pitcher
        for col in PITCHER_METRIC_COLS:
            values = [safe_float(p.get(col)) for p in pitches]
            key_name = METRIC_KEYS[col]
            row[key_name] = round_metric(col, avg(values))
        row.update(compute_stats(pitches))
        # Batted-ball-against stats
        row.update(compute_pitcher_batted_ball(pitches))

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
            # Pick the fastball type with most pitches
            primary_fb_type = max(fb_pitches_by_type, key=lambda t: len(fb_pitches_by_type[t]))
            fb_velos = fb_pitches_by_type[primary_fb_type]
            row['fbVelo'] = round(sum(fb_velos) / len(fb_velos), 1) if fb_velos else None
            row['primaryFbType'] = primary_fb_type
        else:
            row['fbVelo'] = None
            row['primaryFbType'] = None

        pitcher_leaderboard.append(row)

    # Compute percentiles for pitcher leaderboard (across all pitchers)
    # 75-pitch qualifying threshold for rate stats; fbVelo and extension are exempt
    MIN_PITCHES_PCTL = 75
    PITCHER_PCTL_EXEMPT = {'fbVelo', 'extension'}
    PITCHER_METRIC_PCTL_KEYS = [METRIC_KEYS[c] for c in PITCHER_METRIC_COLS]
    for stat in STAT_KEYS + PITCHER_METRIC_PCTL_KEYS + PITCHER_BB_KEYS + ['fbVelo']:
        mc = 0 if stat in PITCHER_PCTL_EXEMPT else MIN_PITCHES_PCTL
        compute_percentile_ranks(pitcher_leaderboard, stat, min_count=mc)

    # Invert percentiles where lower is better
    for row in pitcher_leaderboard:
        for stat in PITCHER_INVERT_PCTL | PITCHER_BB_INVERT:
            pctl_key = stat + '_pctl'
            if row.get(pctl_key) is not None:
                row[pctl_key] = 100 - row[pctl_key]

    pitcher_leaderboard.sort(key=lambda r: r['count'], reverse=True)
    print(f"Pitcher leaderboard: {len(pitcher_leaderboard)} rows")

    # --- Pitch Details: individual pitch data for scatter plots + velo distribution ---
    pitch_details = defaultdict(list)
    for p in all_pitches:
        pitcher = p.get('Pitcher')
        team = p.get('PTeam')
        pt = p.get('Pitch Type')
        ivb = safe_float(p.get('IndVertBrk'))
        hb = safe_float(p.get('HorzBrk'))
        velo = safe_float(p.get('Velocity'))
        spin = safe_float(p.get('Spin Rate'))
        tilt = p.get('Break Tilt')
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
            if rel_x is not None:
                detail['rx'] = round(rel_x, 2)
            if rel_z is not None:
                detail['rz'] = round(rel_z, 2)
            # Game date — for game log filter on player pages
            gd_val = normalize_date(p.get('Game Date'))
            if gd_val:
                detail['gd'] = gd_val
            # Pitch location, strike zone, batter hand, count — for heat maps & count table
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
            pitch_details[pitcher + '|' + (team or '')].append(detail)
    print(f"Pitch details: {sum(len(v) for v in pitch_details.values())} pitches for {len(pitch_details)} pitchers")

    # --- League Averages per pitch type ---
    league_avgs = {}
    for pt, pt_rows in pt_groups.items():
        avgs = {}
        for metric in list(METRIC_KEYS.values()):
            vals = [r[metric] for r in pt_rows if r.get(metric) is not None]
            if vals:
                avgs[metric] = round(sum(vals) / len(vals), 2)
        for stat in PITCH_STAT_KEYS:
            vals = [r[stat] for r in pt_rows if r.get(stat) is not None]
            if vals:
                avgs[stat] = round(sum(vals) / len(vals), 4)
        tilts = [r['breakTiltMinutes'] for r in pt_rows if r.get('breakTiltMinutes') is not None]
        if tilts:
            avgs['breakTiltMinutes'] = circular_mean_minutes(tilts)
            avgs['breakTilt'] = minutes_to_tilt_display(avgs['breakTiltMinutes'])
        avgs['count'] = len(pt_rows)
        league_avgs[pt] = avgs

    # League averages for pitcher leaderboard (across all pitchers)
    pitcher_league_avgs = {}
    for stat in STAT_KEYS + PITCHER_METRIC_PCTL_KEYS:
        vals = [r[stat] for r in pitcher_leaderboard if r.get(stat) is not None]
        if vals:
            pitcher_league_avgs[stat] = round(sum(vals) / len(vals), 4)
    pitcher_league_avgs['count'] = len(pitcher_leaderboard)

    # ======================================================================
    #  HITTER LEADERBOARD (derived from same unified spreadsheet)
    # ======================================================================
    print(f"\n--- Hitter Leaderboard ---")

    # Group by (Batter, BTeam) — includes WBC hitter pitches remapped to MLB teams
    # Only include hitters with an MLB team (country-only hitters excluded)
    # Switch hitters (who bat from both sides) are combined with stands = "S"
    hitter_groups = defaultdict(list)
    for p in all_pitches:
        batter = p.get('Batter')
        b_team = p.get('BTeam')
        if batter and b_team and b_team in MLB_TEAMS:
            hitter_groups[(batter, b_team)].append(p)

    hitter_leaderboard = []
    for (hitter, team), pitches in hitter_groups.items():
        # Determine bats side: if multiple sides seen, mark as Switch
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
        }
        row.update(compute_hitter_stats(pitches))
        hitter_leaderboard.append(row)

    # Compute percentiles across all hitters
    for stat in HITTER_STAT_KEYS:
        compute_percentile_ranks(hitter_leaderboard, stat)

    # Invert percentiles where lower is better (Swing%, Chase%, Whiff%, GB%)
    for row in hitter_leaderboard:
        for stat in HITTER_INVERT_PCTL:
            pctl_key = stat + '_pctl'
            if row.get(pctl_key) is not None:
                row[pctl_key] = 100 - row[pctl_key]

    hitter_leaderboard.sort(key=lambda r: r.get('pa', 0), reverse=True)
    print(f"Hitter leaderboard: {len(hitter_leaderboard)} rows")

    # --- Hitter pitch details: per-hitter breakdown by pitch type faced ---
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
        # Sort by count desc
        details.sort(key=lambda x: x['count'], reverse=True)
        hitter_pitch_details[hitter + '|' + (team or '')] = details

    # --- Hitter pitch-type leaderboard: flatten into one row per hitter-pitch-type ---
    HITTER_PITCH_PCTL_KEYS = [
        'avg', 'slg', 'iso',
        'medEV', 'ev75', 'maxEV', 'medLA', 'barrelPct',
        'gbPct', 'ldPct', 'fbPct',
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

        # Per-pitch-type rows
        for pt, pt_pitches in pt_map.items():
            row = {
                'hitter': hitter,
                'team': team,
                'stands': stands,
                'pitchType': pt,
                'count': len(pt_pitches),
                'seenPct': round(len(pt_pitches) / total_count, 4) if total_count else 0,
                'mlbId': get_mlb_id(hitter, team),
            }
            row.update(compute_hitter_stats(pt_pitches))
            hitter_pitch_leaderboard.append(row)

        # "All" combined row
        row_all = {
            'hitter': hitter,
            'team': team,
            'stands': stands,
            'pitchType': 'All',
            'count': total_count,
            'seenPct': 1.0,
            'mlbId': get_mlb_id(hitter, team),
        }
        row_all.update(compute_hitter_stats(pitches))
        hitter_pitch_leaderboard.append(row_all)

        # Category combined rows (Hard, Breaking, Offspeed)
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
                }
                row_cat.update(compute_hitter_stats(cat_pitches))
                hitter_pitch_leaderboard.append(row_cat)

    # Compute percentiles per pitch type
    pt_groups = defaultdict(list)
    for row in hitter_pitch_leaderboard:
        pt_groups[row['pitchType']].append(row)

    for pt, pt_rows in pt_groups.items():
        for stat in HITTER_PITCH_PCTL_KEYS:
            compute_percentile_ranks(pt_rows, stat, min_count=15)

    # Invert percentiles where lower is better
    for row in hitter_pitch_leaderboard:
        for stat in HITTER_PITCH_INVERT_PCTL:
            pctl_key = stat + '_pctl'
            if row.get(pctl_key) is not None:
                row[pctl_key] = 100 - row[pctl_key]

    hitter_pitch_leaderboard.sort(key=lambda r: r.get('count', 0), reverse=True)
    print(f"Hitter pitch leaderboard: {len(hitter_pitch_leaderboard)} rows")

    # Hitter league averages
    hitter_league_avgs = {}
    for stat in HITTER_STAT_KEYS:
        vals = [r[stat] for r in hitter_leaderboard if r.get(stat) is not None]
        if vals:
            hitter_league_avgs[stat] = round(sum(vals) / len(vals), 4)
    hitter_league_avgs['count'] = len(hitter_leaderboard)

    # --- Metadata ---
    metadata = {
        'teams': all_teams,
        'pitchTypes': all_pitch_types,
        'generatedAt': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'totalPitches': len(all_pitches),
        'totalPitchers': len(pitcher_leaderboard),
        'totalHitters': len(hitter_leaderboard),
        'leagueAverages': league_avgs,
        'pitcherLeagueAverages': pitcher_league_avgs,
        'hitterLeagueAverages': hitter_league_avgs,
        'vaaRegression': {
            'slope': round(vaa_slope, 6),
            'intercept': round(vaa_intercept, 6),
            'leagueAvgPlateZ': round(league_avg_plateZ, 6),
        },
    }

    # Write JSON files
    with open(os.path.join(DATA_DIR, 'pitch_leaderboard.json'), 'w') as f:
        json.dump(pitch_leaderboard, f)
    with open(os.path.join(DATA_DIR, 'pitcher_leaderboard.json'), 'w') as f:
        json.dump(pitcher_leaderboard, f)
    with open(os.path.join(DATA_DIR, 'hitter_leaderboard.json'), 'w') as f:
        json.dump(hitter_leaderboard, f)
    with open(os.path.join(DATA_DIR, 'hitter_pitch_leaderboard.json'), 'w') as f:
        json.dump(hitter_pitch_leaderboard, f)
    with open(os.path.join(DATA_DIR, 'metadata.json'), 'w') as f:
        json.dump(metadata, f, indent=2)

    # Write embedded JS fallback (for file:// usage)
    with open(os.path.join(DATA_DIR, 'data_embedded.js'), 'w') as f:
        f.write('// Auto-generated — do not edit\n')
        f.write('window.PITCH_DATA = ')
        json.dump(pitch_leaderboard, f)
        f.write(';\n')
        f.write('window.PITCHER_DATA = ')
        json.dump(pitcher_leaderboard, f)
        f.write(';\n')
        f.write('window.HITTER_DATA = ')
        json.dump(hitter_leaderboard, f)
        f.write(';\n')
        f.write('window.METADATA = ')
        json.dump(metadata, f)
        f.write(';\n')
        f.write('window.PITCH_DETAILS = ')
        json.dump(pitch_details, f)
        f.write(';\n')
        f.write('window.HITTER_PITCH_DETAILS = ')
        json.dump(hitter_pitch_details, f)
        f.write(';\n')
        f.write('window.HITTER_PITCH_LB = ')
        json.dump(hitter_pitch_leaderboard, f)
        f.write(';\n')

    # --- Generate micro-aggregate data for date/hand filtering ---
    print(f"\n--- Generating micro-aggregate data ---")
    micro_data = generate_micro_data(all_pitches)

    micro_path = os.path.join(DATA_DIR, 'micro_data.json')
    with open(micro_path, 'w') as f:
        json.dump(micro_data, f, separators=(',', ':'))

    # Also append to embedded JS for file:// usage
    with open(os.path.join(DATA_DIR, 'data_embedded.js'), 'a') as f:
        f.write('window.MICRO_DATA = ')
        json.dump(micro_data, f, separators=(',', ':'))
        f.write(';\n')

    print(f"  micro_data.json ({len(micro_data['pitcherMicro'])} pitcher, "
          f"{len(micro_data['pitchMicro'])} pitch, "
          f"{len(micro_data['hitterMicro'])} hitter micro-aggs, "
          f"{len(micro_data['pitcherBip'])} pitcher BIP, "
          f"{len(micro_data['hitterBip'])} hitter BIP records)")

    print(f"\nOutput written to {DATA_DIR}/")
    print(f"  pitch_leaderboard.json  ({len(pitch_leaderboard)} rows)")
    print(f"  pitcher_leaderboard.json ({len(pitcher_leaderboard)} rows)")
    print(f"  hitter_leaderboard.json  ({len(hitter_leaderboard)} rows)")
    print(f"  metadata.json")
    print(f"  data_embedded.js")


if __name__ == '__main__':
    main()
