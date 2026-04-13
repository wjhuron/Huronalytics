#!/usr/bin/env python3
"""Shared utility functions and constants for the leaderboard pipeline."""

import math
import os
from datetime import datetime, time

# ── Paths ────────────────────────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_SCRIPT_DIR, 'data')


# ── Strike zone constants ────────────────────────────────────────────────
BALL_RADIUS_FT = 1.45 / 12   # 1.45 inches = ~0.121 ft
ZONE_HALF_WIDTH = 0.83        # half plate (8.5") + ball radius (1.45") in feet

# ── Event classification sets ────────────────────────────────────────────
SWING_DESCRIPTIONS = {'Swinging Strike', 'Foul', 'In Play'}
HIT_EVENTS = {'Single', 'Double', 'Triple', 'Home Run'}
K_EVENTS = {'Strikeout', 'Strikeout Double Play'}
BB_EVENTS = {'Walk', 'Intent Walk'}
HBP_EVENTS = {'Hit By Pitch'}
SF_EVENTS = {'Sac Fly', 'Sac Fly Double Play'}
SH_EVENTS = {'Sac Bunt', 'Sac Bunt Double Play'}
CI_EVENTS = {'Catcher Interference'}
NON_PA_EVENTS = {
    'Caught Stealing 2B', 'Caught Stealing 3B', 'Caught Stealing Home',
    'Pickoff 1B', 'Pickoff 2B', 'Pickoff 3B',
    'Pickoff Caught Stealing 2B', 'Pickoff Caught Stealing 3B',
    'Pickoff Caught Stealing Home',
    'Runner Out', 'Wild Pitch', 'Game Advisory',
    'Stolen Base 2B', 'Stolen Base 3B', 'Stolen Base Home',
    'Balk', 'Passed Ball',
}
BUNT_BB_TYPES = {'bunt', 'bunt_grounder', 'bunt_popup', 'bunt_line_drive'}

# ── Team sets ────────────────────────────────────────────────────────────
MLB_TEAMS = {
    'ARI', 'ATH', 'ATL', 'BAL', 'BOS', 'CHC', 'CIN', 'CLE', 'COL', 'CWS',
    'DET', 'HOU', 'KCR', 'LAA', 'LAD', 'MIA', 'MIL', 'MIN', 'NYM', 'NYY',
    'PHI', 'PIT', 'SDP', 'SEA', 'SFG', 'STL', 'TBR', 'TEX', 'TOR', 'WSH',
    'WBC',
}
AAA_TEAMS = {'ROC'}
ALL_TEAMS = MLB_TEAMS | AAA_TEAMS

# ── Team abbreviation → MLB API team ID ──────────────────────────────────
TEAM_ABBREV_TO_ID = {
    'ARI': 109, 'ATL': 144, 'BAL': 110, 'BOS': 111, 'CHC': 112,
    'CWS': 145, 'CIN': 113, 'CLE': 114, 'COL': 115, 'DET': 116,
    'HOU': 117, 'KCR': 118, 'LAA': 108, 'LAD': 119, 'MIA': 146,
    'MIL': 158, 'MIN': 142, 'NYM': 121, 'NYY': 147, 'ATH': 133,
    'PHI': 143, 'PIT': 134, 'SDP': 135, 'SFG': 137, 'SEA': 136,
    'STL': 138, 'TBR': 139, 'TEX': 140, 'TOR': 141, 'WSH': 120,
}


# ── Pure utility functions ───────────────────────────────────────────────

def safe_float(val):
    """Convert a value to float, returning None if not possible."""
    if val is None or val == '':
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def normalize_date(val):
    """Normalize a date value to YYYY-MM-DD string."""
    if val is None or val == '':
        return None
    if isinstance(val, datetime):
        return val.strftime('%Y-%m-%d')
    s = str(val).strip()
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        return s[:10]
    parts = s.split('/')
    if len(parts) == 3:
        try:
            m, d, y = int(parts[0]), int(parts[1]), int(parts[2])
            return f"{y:04d}-{m:02d}-{d:02d}"
        except ValueError:
            pass
    return None


def _today_et():
    """Return today's date in US Eastern time (MLB schedule reference timezone)."""
    import datetime as _dt
    try:
        from zoneinfo import ZoneInfo
        return _dt.datetime.now(ZoneInfo('America/New_York')).date()
    except ImportError:
        return _dt.date.today()


def avg(values):
    """Average a list of numbers, ignoring None."""
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def median(values):
    """Compute median, ignoring None values."""
    nums = sorted(v for v in values if v is not None)
    if not nums:
        return None
    n = len(nums)
    if n % 2 == 1:
        return nums[n // 2]
    return (nums[n // 2 - 1] + nums[n // 2]) / 2


def round_metric(key, value):
    """Round a metric value according to its type."""
    if value is None:
        return None
    if key == 'Spin Rate':
        return round(value)
    if key in ('VAA', 'HAA'):
        return round(value, 2)
    return round(value, 1)


def is_barrel(ev, la):
    """Statcast barrel definition (MLB glossary / baseballr code_barrel).
    Five conditions: LA in [8,50], EV>=98, EV*1.5-LA>=117, EV+LA>=124."""
    if ev is None or la is None:
        return False
    return (la >= 8 and la <= 50 and ev >= 98 and
            ev * 1.5 - la >= 117 and
            ev + la >= 124)


# ── Spray angle functions ────────────────────────────────────────────────

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
    """Classify spray direction into 6 equal 15° bins based on spray angle and batter side."""
    if angle is None or not stands:
        return None
    if stands == 'R':
        if angle < -30:
            return 'pull'
        elif angle < -15:
            return 'pull_side'
        elif angle < 0:
            return 'center_pull'
        elif angle < 15:
            return 'center_oppo'
        elif angle < 30:
            return 'oppo_side'
        else:
            return 'oppo'
    else:  # L
        if angle > 30:
            return 'pull'
        elif angle > 15:
            return 'pull_side'
        elif angle > 0:
            return 'center_pull'
        elif angle > -15:
            return 'center_oppo'
        elif angle > -30:
            return 'oppo_side'
        else:
            return 'oppo'


# ── Break Tilt / clock-face functions ────────────────────────────────────

def break_tilt_to_minutes(val):
    """Convert a time value (clock notation) to total minutes (0-719)."""
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


# ── Strike zone ──────────────────────────────────────────────────────────

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


# ── IP conversion ────────────────────────────────────────────────────────

def outs_to_ip_str(outs):
    """Convert total outs to IP string notation (e.g., 19 outs -> '6.1')."""
    full = outs // 3
    remainder = outs % 3
    return f"{full}.{remainder}"


def outs_to_ip_float(outs):
    """Convert outs to float for calculations like ERA (19 outs -> 6.333...)."""
    return outs / 3.0


def ip_str_to_float(ip_str):
    """Convert baseball IP string to float. '6.1' -> 6.333, '6.2' -> 6.667, '6.0' -> 6.0."""
    if not ip_str:
        return 0.0
    parts = str(ip_str).split('.')
    full = int(parts[0])
    thirds = int(parts[1]) if len(parts) > 1 and parts[1] else 0
    return full + thirds / 3.0


# ── Name formatting ──────────────────────────────────────────────────────

def _fullname_to_lastfirst(full_name):
    """Convert 'First Last' to 'Last, First'. Simple split — handles most cases."""
    parts = full_name.strip().split()
    if len(parts) <= 1:
        return full_name
    suffixes = {'jr.', 'jr', 'sr.', 'sr', 'ii', 'iii', 'iv', 'v'}
    suffix = ''
    if len(parts) > 2 and parts[-1].lower().rstrip('.') in suffixes:
        suffix = ' ' + parts.pop()
    return parts[-1] + suffix + ', ' + ' '.join(parts[:-1])
