#!/usr/bin/env python3
"""Stat computation: expected stats, pitch/hitter stats, micro-data, percentiles."""

import math
from collections import defaultdict

from pipeline_utils import (
    safe_float, median, is_barrel,
    spray_angle, spray_direction,
    SWING_DESCRIPTIONS, HIT_EVENTS, K_EVENTS, BB_EVENTS, HBP_EVENTS,
    SF_EVENTS, SH_EVENTS, CI_EVENTS, NON_PA_EVENTS, BUNT_BB_TYPES,
    ALL_TEAMS,
)

# ── Metric / leaderboard constants ───────────────────────────────────────

METRIC_COLS = [
    'Velocity', 'EffectiveVelo', 'Spin Rate', 'xIndVrtBrk', 'xHorzBrk',
    'RelPosZ', 'RelPosX', 'Extension', 'ArmAngle', 'VAA', 'HAA'
]

METRIC_KEYS = {
    'Velocity': 'velocity', 'EffectiveVelo': 'effectiveVelo',
    'Spin Rate': 'spinRate',
    'xIndVrtBrk': 'indVertBrk', 'xHorzBrk': 'horzBrk',
    'RelPosZ': 'relPosZ', 'RelPosX': 'relPosX',
    'Extension': 'extension', 'ArmAngle': 'armAngle',
    'VAA': 'vaa', 'HAA': 'haa',
}

PITCH_STAT_KEYS = ['strikePct', 'izPct', 'swStrRate', 'swStrPct', 'cswPct', 'izWhiffPct', 'chasePct', 'gbPct', 'fpsPct']
STAT_KEYS = ['strikePct', 'izPct', 'swStrRate', 'swStrPct', 'cswPct', 'izWhiffPct', 'chasePct', 'gbPct', 'kPct', 'bbPct', 'kbbPct', 'babip', 'fpsPct', 'twoStrikeWhiffPct', 'oneOneWinPct', 'earlyActionPct']

PITCH_PCTL_KEYS = list(METRIC_KEYS.values()) + ['nVAA', 'nHAA'] + PITCH_STAT_KEYS + ['runValue', 'rv100', 'xRunValue', 'xRv100', 'wOBA', 'xBA', 'xSLG', 'xwOBA', 'xwOBAcon', 'xwOBAsp']

PITCHER_INVERT_PCTL = {'bbPct', 'babip', 'era', 'fip', 'xFIP', 'siera'}

HITTER_STAT_KEYS = [
    'avg', 'obp', 'slg', 'ops', 'iso', 'babip', 'kPct', 'bbPct',
    'wOBA', 'xBA', 'xSLG', 'xwOBA', 'xwOBAcon', 'xwOBAsp', 'bbPlus',
    'avgEVAll', 'ev50', 'maxEV', 'hardHitPct', 'barrelPct',
    'gbPct', 'ldPct', 'fbPct', 'puPct', 'hrFbPct',
    'pullPct', 'middlePct', 'oppoPct', 'airPullPct',
    'swingPct', 'izSwingPct', 'chasePct', 'izSwChase', 'contactPct', 'izContactPct', 'whiffPct', 'pdPlus', 'sdPlus', 'ctPlus',
    'batSpeed', 'swingLength', 'attackAngle', 'attackDirection', 'swingPathTilt',
    'blastPct', 'idealAAPct',
    'twoStrikeWhiffPct', 'firstPitchSwingPct',
    'avgFbDist', 'avgHrDist',
    'sprintSpeed',
    'wRCplus', 'xWRCplus', 'hitterPlus',
    'runValue', 'xRunValue',
    'hr', 'sb',
]
HITTER_INVERT_PCTL = {'swingPct', 'chasePct', 'whiffPct', 'gbPct', 'kPct', 'puPct', 'twoStrikeWhiffPct'}

PITCHER_BB_KEYS = ['avgEVAgainst', 'maxEVAgainst', 'hardHitPct', 'barrelPctAgainst', 'ldPct', 'fbPct', 'puPct', 'hrFbPct', 'xwOBAsp']
PITCHER_BB_INVERT = {'avgEVAgainst', 'maxEVAgainst', 'hardHitPct', 'barrelPctAgainst', 'hrFbPct', 'xwOBAsp'}

# ── Stat computation functions ───────────────────────────────────────────

def compute_expected_stats(pitches, woba_weights=None):
    """Compute wOBA, xBA, xSLG, xwOBA, xwOBAcon from pitch-level data.

    wOBA uses FanGraphs Guts linear weights applied to actual outcomes.
    xBA/xSLG/xwOBA use Statcast per-pitch expected values from the spreadsheet.
    """
    weights = woba_weights

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
            continue

        xwoba_val = safe_float(p.get('xwOBA'))
        if xwoba_val is not None:
            xwoba_sum += xwoba_val
            xwoba_denom += 1

        if event in BB_EVENTS:
            ubb += 1
            continue
        elif event in HBP_EVENTS:
            hbp_count += 1
            continue
        elif event in SF_EVENTS:
            sf += 1
            xwobacon_val = safe_float(p.get('xwOBA'))
            if xwobacon_val is not None:
                xwobacon_sum += xwobacon_val
                xwobacon_denom += 1
            continue
        elif event in SH_EVENTS or event in CI_EVENTS:
            continue

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

        if event not in K_EVENTS:
            xwobacon_val = safe_float(p.get('xwOBA'))
            if xwobacon_val is not None:
                xwobacon_sum += xwobacon_val
                xwobacon_denom += 1

    result = {}

    woba_denom = ab + ubb + sf + hbp_count
    if woba_denom > 0 and weights:
        woba_num = (weights['BB'] * ubb + weights['HBP'] * hbp_count +
                    weights['1B'] * singles + weights['2B'] * doubles +
                    weights['3B'] * triples + weights['HR'] * hr)
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

    bip = [p for p in pitches if p.get('BBType') is not None and p.get('BBType') not in BUNT_BB_TYPES]
    gb = sum(1 for p in bip if p.get('BBType') == 'ground_ball')

    pa_pitches = [p for p in pitches if p.get('Event') and p['Event'] not in NON_PA_EVENTS]
    n_pa = len(pa_pitches)
    n_h = sum(1 for p in pa_pitches if p['Event'] in HIT_EVENTS)
    n_hr = sum(1 for p in pa_pitches if p['Event'] == 'Home Run')
    n_k = sum(1 for p in pa_pitches if p['Event'] in K_EVENTS)
    n_bb_all = sum(1 for p in pa_pitches if p['Event'] in BB_EVENTS)
    n_ibb = sum(1 for p in pa_pitches if p['Event'] == 'Intent Walk')
    n_bb = n_bb_all - n_ibb
    n_hbp = sum(1 for p in pa_pitches if p['Event'] in HBP_EVENTS)
    n_sf = sum(1 for p in pa_pitches if p['Event'] in SF_EVENTS)
    n_sh = sum(1 for p in pa_pitches if p['Event'] in SH_EVENTS)
    n_ci = sum(1 for p in pa_pitches if p['Event'] in CI_EVENTS)
    n_ab = n_pa - n_bb_all - n_hbp - n_sf - n_sh - n_ci
    k_pct = n_k / n_pa if n_pa > 0 else None
    bb_pct = n_bb / n_pa if n_pa > 0 else None
    kbb_pct = round(k_pct - bb_pct, 4) if k_pct is not None and bb_pct is not None else None

    babip_denom = n_ab - n_k - n_hr + n_sf
    babip = round((n_h - n_hr) / babip_denom, 3) if babip_denom > 0 else None

    BALL_DESCRIPTIONS = {'Ball', 'Intent Ball', 'Hit By Pitch', 'Pitchout'}
    n_strikes = sum(1 for p in pitches if p.get('Description') not in BALL_DESCRIPTIONS)
    strike_pct = n_strikes / total if total > 0 else None

    rv_values = [safe_float(p.get('RunExp')) for p in pitches]
    rv_values = [v for v in rv_values if v is not None]
    run_value = sum(rv_values) if rv_values else None

    first_pitches = [p for p in pitches if p.get('Count') == '0-0']
    fps_strikes = sum(1 for p in first_pitches
                      if p.get('Description') in ('Called Strike', 'Swinging Strike', 'Foul', 'In Play'))
    fps_pct = fps_strikes / len(first_pitches) if first_pitches else None

    two_strike_pitches = [p for p in pitches if '-' in p.get('Count', '') and p['Count'].split('-')[1] == '2']
    two_strike_swings = sum(1 for p in two_strike_pitches if p['Description'] in SWING_DESCRIPTIONS)
    two_strike_whiffs = sum(1 for p in two_strike_pitches if p['Description'] == 'Swinging Strike')
    two_strike_whiff_pct = two_strike_whiffs / two_strike_swings if two_strike_swings > 0 else None

    one_one_pitches = [p for p in pitches if p.get('Count') == '1-1']
    one_one_wins = sum(1 for p in one_one_pitches if p.get('Description') not in BALL_DESCRIPTIONS)
    one_one_win_pct = one_one_wins / len(one_one_pitches) if one_one_pitches else None

    early_action = 0
    for p in pitches:
        ev = p.get('Event')
        if ev and ev not in NON_PA_EVENTS:
            pid = p.get('PitchID') or ''
            parts = pid.split('_')
            if len(parts) == 3:
                try:
                    if int(parts[2]) <= 3:
                        early_action += 1
                except ValueError:
                    pass
    early_action_pct = early_action / n_pa if n_pa > 0 else None

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
        'oneOneWinPct': one_one_win_pct,
        'earlyActionPct': early_action_pct,
        'runValue': run_value,
    }


def compute_xrv(pitches, lg_woba=None, woba_scale=None, negate=False):
    """Compute expected run value (xRV).

    For BIP pitches with xwOBA: uses (xwOBA - lgWOBA) / wOBAScale
    (hitter perspective: positive = above-average contact).
    For all other pitches: uses -RunExp to convert from pitcher perspective
    (RunExp in sheets is positive = good for pitcher) to hitter perspective.

    The raw total is hitter-perspective (positive = good for hitter).
    negate=False (default, for pitchers): flips to pitcher perspective
    (positive = good for pitcher, i.e. runs saved).
    negate=True (for hitters): keeps hitter perspective (positive = good for hitter).
    """
    xrv_values = []
    has_guts = lg_woba is not None and woba_scale is not None and woba_scale != 0
    for p in pitches:
        is_bip = p.get('Description') == 'In Play'
        xwoba_val = safe_float(p.get('xwOBA')) if is_bip else None
        if is_bip and xwoba_val is not None and has_guts:
            xrv_values.append((xwoba_val - lg_woba) / woba_scale)
        else:
            rv = safe_float(p.get('RunExp'))
            if rv is not None:
                xrv_values.append(-rv)
    if not xrv_values:
        return {'xRunValue': None}
    total = sum(xrv_values)
    return {'xRunValue': -total if not negate else total}


def compute_pitcher_batted_ball(pitches):
    """Compute batted-ball-against stats for a pitcher."""
    bip = [p for p in pitches if p.get('BBType') is not None and p.get('BBType') not in BUNT_BB_TYPES]
    n_bip = len(bip)
    if n_bip == 0:
        return {
            'avgEVAgainst': None, 'maxEVAgainst': None,
            'hardHitPct': None, 'barrelPctAgainst': None,
            'ldPct': None, 'fbPct': None, 'puPct': None,
            'hrFbPct': None,
        }

    ev_vals = [safe_float(p.get('ExitVelo')) for p in bip]
    ev_valid = [v for v in ev_vals if v is not None]
    avg_ev = round(sum(ev_valid) / len(ev_valid), 1) if ev_valid else None
    max_ev = round(max(ev_valid), 1) if ev_valid else None

    hard_hit = sum(1 for v in ev_valid if v >= 95)
    hard_hit_pct = hard_hit / len(ev_valid) if ev_valid else None

    has_barrel_col = any(str(p.get('Barrel', '')).strip() != '' for p in bip)
    if has_barrel_col:
        barrels = sum(1 for p in bip if str(p.get('Barrel', '')).strip() == '6')
    else:
        ev_la_pairs = [(safe_float(p.get('ExitVelo')), safe_float(p.get('LaunchAngle')))
                       for p in bip
                       if safe_float(p.get('ExitVelo')) is not None
                       and safe_float(p.get('LaunchAngle')) is not None]
        barrels = sum(1 for ev, la in ev_la_pairs if is_barrel(ev, la))
    barrel_pct = barrels / len(ev_valid) if ev_valid else None

    ld = sum(1 for p in bip if p.get('BBType') == 'line_drive')
    fb = sum(1 for p in bip if p.get('BBType') == 'fly_ball')
    pu = sum(1 for p in bip if p.get('BBType') == 'popup')

    n_hr_bb = sum(1 for p in bip if p.get('Event') == 'Home Run')
    fb_for_hrfb = fb + pu
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


def compute_hitter_stats(pitches):
    """Compute hitter stats from a list of pitch dicts for all hitter leaderboard tabs."""
    total = len(pitches)
    if total == 0:
        empty = {k: None for k in HITTER_STAT_KEYS}
        empty.update({'pa': 0, 'nSwings': 0, 'nBip': 0, 'nCompSwings': 0,
                      'doubles': 0, 'triples': 0, 'hr': 0, 'xbh': 0})
        return empty

    pa_pitches = [p for p in pitches if p.get('Event') and p['Event'] not in NON_PA_EVENTS]
    n_pa = len(pa_pitches)

    n_2b = sum(1 for p in pa_pitches if p['Event'] == 'Double')
    n_3b = sum(1 for p in pa_pitches if p['Event'] == 'Triple')
    n_h = sum(1 for p in pa_pitches if p['Event'] in HIT_EVENTS)
    n_hr = sum(1 for p in pa_pitches if p['Event'] == 'Home Run')
    n_k = sum(1 for p in pa_pitches if p['Event'] in K_EVENTS)
    n_bb_all = sum(1 for p in pa_pitches if p['Event'] in BB_EVENTS)
    n_hbp = sum(1 for p in pa_pitches if p['Event'] in HBP_EVENTS)
    n_sf = sum(1 for p in pa_pitches if p['Event'] in SF_EVENTS)
    n_sh = sum(1 for p in pa_pitches if p['Event'] in SH_EVENTS)
    n_ci = sum(1 for p in pa_pitches if p['Event'] in CI_EVENTS)

    n_ab = n_pa - n_bb_all - n_hbp - n_sf - n_sh - n_ci
    xbh = n_2b + n_3b + n_hr
    babip_denom = n_ab - n_k - n_hr + n_sf
    babip = round((n_h - n_hr) / babip_denom, 3) if babip_denom > 0 else None

    n_swings = sum(1 for p in pitches if p['Description'] in SWING_DESCRIPTIONS)
    whiffs = sum(1 for p in pitches if p['Description'] == 'Swinging Strike')

    iz_pitches = [p for p in pitches if p.get('InZone') == 'Yes']
    ooz_pitches = [p for p in pitches if p.get('InZone') == 'No']
    iz_swings = sum(1 for p in iz_pitches if p['Description'] in SWING_DESCRIPTIONS)
    iz_whiffs = sum(1 for p in iz_pitches if p['Description'] == 'Swinging Strike')
    ooz_swings = sum(1 for p in ooz_pitches if p['Description'] in SWING_DESCRIPTIONS)

    iz_swing_pct = iz_swings / len(iz_pitches) if iz_pitches else None
    chase_pct = ooz_swings / len(ooz_pitches) if ooz_pitches else None

    swings_non_bunt = sum(1 for p in pitches
                          if p['Description'] in SWING_DESCRIPTIONS
                          and p.get('BBType') not in BUNT_BB_TYPES)
    contact_non_bunt = sum(1 for p in pitches
                           if p['Description'] in ('Foul', 'In Play')
                           and p.get('BBType') not in BUNT_BB_TYPES)
    contact_pct = contact_non_bunt / swings_non_bunt if swings_non_bunt > 0 else None

    iz_swings_non_bunt = sum(1 for p in iz_pitches
                             if p['Description'] in SWING_DESCRIPTIONS
                             and p.get('BBType') not in BUNT_BB_TYPES)
    iz_contact = sum(1 for p in iz_pitches
                     if p['Description'] in ('Foul', 'In Play')
                     and p.get('BBType') not in BUNT_BB_TYPES)
    iz_contact_pct = iz_contact / iz_swings_non_bunt if iz_swings_non_bunt > 0 else None

    bip = [p for p in pitches if p.get('BBType') is not None and p.get('BBType') not in BUNT_BB_TYPES]
    n_bip = len(bip)
    gb = sum(1 for p in bip if p.get('BBType') == 'ground_ball')
    ld = sum(1 for p in bip if p.get('BBType') == 'line_drive')
    fb = sum(1 for p in bip if p.get('BBType') == 'fly_ball')
    pu = sum(1 for p in bip if p.get('BBType') == 'popup')

    all_evs = [safe_float(p.get('ExitVelo')) for p in bip]
    all_evs = [v for v in all_evs if v is not None]
    ev50 = None
    if all_evs:
        sorted_evs = sorted(all_evs, reverse=True)
        top_half = sorted_evs[:max(1, len(sorted_evs) // 2)]
        ev50 = round(sum(top_half) / len(top_half), 1)

    has_barrel_col = any(str(p.get('Barrel', '')).strip() != '' for p in bip)
    if has_barrel_col:
        barrels = sum(1 for p in bip if str(p.get('Barrel', '')).strip() == '6')
    else:
        ev_la_all = [(safe_float(p.get('ExitVelo')), safe_float(p.get('LaunchAngle')))
                     for p in bip
                     if safe_float(p.get('ExitVelo')) is not None
                     and safe_float(p.get('LaunchAngle')) is not None]
        barrels = sum(1 for ev, la in ev_la_all if is_barrel(ev, la))

    all_la = [safe_float(p.get('LaunchAngle')) for p in bip
              if safe_float(p.get('LaunchAngle')) is not None]

    spray_data = []
    for p in bip:
        hc_x = safe_float(p.get('HC_X'))
        hc_y = safe_float(p.get('HC_Y'))
        angle = spray_angle(hc_x, hc_y)
        direction = spray_direction(angle, p.get('Bats'))
        if direction:
            spray_data.append((direction, p.get('BBType')))
    n_spray = len(spray_data)
    pull = sum(1 for d, _ in spray_data if d in ('pull', 'pull_side'))
    center = sum(1 for d, _ in spray_data if d in ('center_pull', 'center_oppo'))
    oppo = sum(1 for d, _ in spray_data if d in ('oppo_side', 'oppo'))
    air_pull = sum(1 for d, bb in spray_data if d in ('pull', 'pull_side') and bb in ('line_drive', 'fly_ball'))

    ev_valid = [safe_float(p.get('ExitVelo')) for p in bip]
    ev_valid = [v for v in ev_valid if v is not None]
    hard_hit = sum(1 for v in ev_valid if v >= 95)
    hard_hit_pct = hard_hit / len(ev_valid) if ev_valid else None

    n_hr_fb = sum(1 for p in bip if p.get('Event') == 'Home Run')
    fb_for_hrfb = fb + pu
    hr_fb_pct = round(n_hr_fb / fb_for_hrfb, 4) if fb_for_hrfb > 0 else None

    two_strike_pitches = [p for p in pitches if '-' in p.get('Count', '') and p['Count'].split('-')[1] == '2']
    two_strike_swings = sum(1 for p in two_strike_pitches if p['Description'] in SWING_DESCRIPTIONS)
    two_strike_whiffs = sum(1 for p in two_strike_pitches if p['Description'] == 'Swinging Strike')
    two_strike_whiff_pct = two_strike_whiffs / two_strike_swings if two_strike_swings > 0 else None

    first_pitches_h = [p for p in pitches if p.get('Count') == '0-0']
    first_pitch_swings = sum(1 for p in first_pitches_h if p['Description'] in SWING_DESCRIPTIONS)
    first_pitch_swing_pct = first_pitch_swings / len(first_pitches_h) if first_pitches_h else None

    fb_distances = [safe_float(p.get('Distance')) for p in bip if p.get('BBType') == 'fly_ball']
    fb_distances = [d for d in fb_distances if d is not None]
    avg_fb_dist = round(sum(fb_distances) / len(fb_distances), 0) if fb_distances else None

    hr_distances = [safe_float(p.get('Distance')) for p in bip if p.get('Event') == 'Home Run']
    hr_distances = [d for d in hr_distances if d is not None]
    avg_hr_dist = round(sum(hr_distances) / len(hr_distances), 0) if hr_distances else None

    bs_vals = []
    sl_vals = []
    aa_vals = []
    ad_vals = []
    spt_vals = []
    for p in pitches:
        bs = safe_float(p.get('BatSpeed'))
        if bs is not None and bs >= 50:
            bs_vals.append(bs)
            sl = safe_float(p.get('SwingLength'))
            if sl is not None: sl_vals.append(sl)
            aa = safe_float(p.get('AttackAngle'))
            if aa is not None: aa_vals.append(aa)
            ad = safe_float(p.get('AttackDirection'))
            if ad is not None: ad_vals.append(ad)
            spt = safe_float(p.get('SwingPathTilt'))
            if spt is not None: spt_vals.append(spt)

    n_blasts = 0
    n_blast_eligible = 0
    n_ideal_aa = 0
    for p in pitches:
        bs = safe_float(p.get('BatSpeed'))
        if bs is None or bs < 50:
            continue
        aa = safe_float(p.get('AttackAngle'))
        if aa is not None and 5 <= aa <= 20:
            n_ideal_aa += 1
        ev = safe_float(p.get('ExitVelo'))
        velo = safe_float(p.get('Velocity'))
        if ev is not None and velo is not None:
            n_blast_eligible += 1
            max_ev = 0.2 * velo + 1.2 * bs
            if bs >= 75 and ev >= 0.80 * max_ev:
                n_blasts += 1

    return {
        'pa': n_pa,
        'ab': n_ab,
        'nSwings': n_swings,
        'nBip': n_bip,
        'doubles': n_2b,
        'triples': n_3b,
        'hr': n_hr,
        'xbh': xbh,
        'avgEVAll': round(sum(ev_valid) / len(ev_valid), 1) if ev_valid else None,
        'ev50': ev50,
        'maxEV': round(max(ev_valid), 1) if ev_valid else None,
        'medLA': round(median(all_la), 1) if all_la else None,
        'hardHitPct': round(hard_hit_pct, 4) if hard_hit_pct is not None else None,
        'babip': babip,
        'barrelPct': barrels / len(ev_valid) if ev_valid else None,
        'gbPct': gb / n_bip if n_bip > 0 else None,
        'ldPct': ld / n_bip if n_bip > 0 else None,
        'fbPct': fb / n_bip if n_bip > 0 else None,
        'puPct': pu / n_bip if n_bip > 0 else None,
        'hrFbPct': hr_fb_pct,
        'pullPct': pull / n_spray if n_spray > 0 else None,
        'middlePct': center / n_spray if n_spray > 0 else None,
        'oppoPct': oppo / n_spray if n_spray > 0 else None,
        'airPullPct': air_pull / n_bip if n_bip > 0 else None,
        'swingPct': n_swings / total if total > 0 else None,
        'izSwingPct': iz_swing_pct,
        'chasePct': chase_pct,
        'izSwChase': round(iz_swing_pct - chase_pct, 4) if iz_swing_pct is not None and chase_pct is not None else None,
        'contactPct': contact_pct,
        'izContactPct': iz_contact_pct,
        'whiffPct': whiffs / n_swings if n_swings > 0 else None,
        'izWhiffPct': iz_whiffs / iz_swings if iz_swings > 0 else None,
        'runValue': (lambda vals: -sum(vals) if vals else None)([v for v in (safe_float(p.get('RunExp')) for p in pitches) if v is not None]),
        'batSpeed': round(sum(bs_vals) / len(bs_vals), 1) if bs_vals else None,
        'swingLength': round(sum(sl_vals) / len(sl_vals), 1) if sl_vals else None,
        'attackAngle': round(sum(aa_vals) / len(aa_vals), 1) if aa_vals else None,
        'attackDirection': round(sum(ad_vals) / len(ad_vals), 1) if ad_vals else None,
        'swingPathTilt': round(sum(spt_vals) / len(spt_vals), 1) if spt_vals else None,
        'nCompSwings': len(bs_vals),
        'blastPct': round(n_blasts / n_blast_eligible, 4) if n_blast_eligible > 0 else None,
        'idealAAPct': round(n_ideal_aa / len(bs_vals), 4) if bs_vals else None,
        'twoStrikeWhiffPct': two_strike_whiff_pct,
        'firstPitchSwingPct': first_pitch_swing_pct,
        'avgFbDist': avg_fb_dist,
        'avgHrDist': avg_hr_dist,
    }


# ── Percentile computation ───────────────────────────────────────────────

def compute_percentile_ranks(rows, metric_key, min_count=0, count_key='count'):
    """Compute percentile rank (0-100) for each row's metric value.
    Uses the 'mean rank' method for ties.  O(n log n) via sort + bisect."""
    import bisect
    pctl_key = metric_key + '_pctl'
    valid = [(i, rows[i][metric_key]) for i in range(len(rows))
             if rows[i].get(metric_key) is not None
             and (min_count == 0 or (rows[i].get(count_key) or 0) >= min_count)]

    if len(valid) < 2:
        for row in rows:
            row[pctl_key] = 50 if row.get(metric_key) is not None else None
        return

    sorted_vals = sorted(v for _, v in valid)
    n = len(sorted_vals)

    def _pctl_from_sorted(val, denom):
        below = bisect.bisect_left(sorted_vals, val)
        above = bisect.bisect_right(sorted_vals, val)
        equal = above - below
        return max(0, min(100, round((below + 0.5 * (equal - 1)) / max(1, denom - 1) * 100)))

    for idx, val in valid:
        rows[idx][pctl_key] = _pctl_from_sorted(val, n)

    if min_count > 0:
        for i, row in enumerate(rows):
            if pctl_key in row:
                continue
            val = row.get(metric_key)
            if val is None:
                row[pctl_key] = None
                continue
            row[pctl_key] = _pctl_from_sorted(val, n)

    for row in rows:
        if pctl_key not in row:
            row[pctl_key] = None


def compute_percentile_ranks_with_aaa(rows, metric_key, min_count=0, count_key='count'):
    """Compute percentiles from an MLB pool of one row per player (combined 2TM/3TM
    rows replace their per-team rows), then interpolate AAA rows and the per-team
    rows of multi-team players against the pool."""
    pctl_key = metric_key + '_pctl'

    def _player_key(r):
        return r.get('pitcher') or r.get('hitter')

    combined_players = {_player_key(r) for r in rows if r.get('_isCombined')}

    mlb_rows = []
    interp_rows = []
    for r in rows:
        if r.get('_isROC'):
            interp_rows.append(r)
            continue
        if not r.get('_isCombined') and _player_key(r) in combined_players:
            interp_rows.append(r)
            continue
        mlb_rows.append(r)

    compute_percentile_ranks(mlb_rows, metric_key, min_count, count_key)

    mlb_values = sorted([r[metric_key] for r in mlb_rows
                         if r.get(metric_key) is not None
                         and (min_count == 0 or (r.get(count_key) or 0) >= min_count)])
    n = len(mlb_values)

    import bisect
    for row in interp_rows:
        val = row.get(metric_key)
        if val is None:
            row[pctl_key] = None
            continue
        if n < 2:
            row[pctl_key] = 50
            continue
        below = bisect.bisect_left(mlb_values, val)
        above = bisect.bisect_right(mlb_values, val)
        equal = above - below
        pctl = (below + 0.5 * equal) / n * 100
        row[pctl_key] = max(0, min(100, round(pctl)))


# ── Micro-data generation ────────────────────────────────────────────────
# generate_micro_data is imported from process_data.py for now, as it's
# tightly coupled with the micro-data format (800+ lines).
# It will be moved here in a follow-up refactor.
