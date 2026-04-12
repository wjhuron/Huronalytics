#!/usr/bin/env python3
"""Process pitching and hitting data from Google Sheets into JSON files for the leaderboard website."""

import gspread
from google.oauth2.service_account import Credentials
import json
import math
import os
import sys
import time as time_module
from datetime import datetime
from collections import defaultdict

# ── Pipeline modules ─────────────────────────────────────────────────────
from pipeline_utils import (
    safe_float, normalize_date, _today_et, avg, median, round_metric,
    is_barrel, spray_angle, spray_direction,
    break_tilt_to_minutes, circular_mean_minutes, minutes_to_tilt_display,
    compute_in_zone, outs_to_ip_str, outs_to_ip_float, ip_str_to_float,
    DATA_DIR,
    SWING_DESCRIPTIONS, HIT_EVENTS, K_EVENTS, BB_EVENTS, HBP_EVENTS,
    SF_EVENTS, SH_EVENTS, CI_EVENTS, NON_PA_EVENTS, BUNT_BB_TYPES,
    MLB_TEAMS, AAA_TEAMS, ALL_TEAMS, TEAM_ABBREV_TO_ID,
    BALL_RADIUS_FT, ZONE_HALF_WIDTH,
)
from pipeline_fetch import (
    fetch_guts_constants, fetch_sprint_speed, fetch_park_factors,
    read_pitches_from_sheet,
    lookup_mlb_id, load_mlb_id_cache, save_mlb_id_cache,
    fetch_and_aggregate_boxscores, fetch_and_aggregate_milb_boxscores,
    SPREADSHEET_IDS, SERVICE_ACCOUNT_FILE,
    WOBA_WEIGHTS_FALLBACK, FIP_CONSTANT_FALLBACK,
)
from pipeline_compute import (
    compute_expected_stats, compute_stats, compute_xrv,
    compute_pitcher_batted_ball, compute_hitter_stats,
    compute_percentile_ranks, compute_percentile_ranks_with_aaa,
    METRIC_COLS, METRIC_KEYS, PITCH_STAT_KEYS, STAT_KEYS,
    PITCH_PCTL_KEYS, PITCHER_INVERT_PCTL,
    HITTER_STAT_KEYS, HITTER_INVERT_PCTL,
    PITCHER_BB_KEYS, PITCHER_BB_INVERT,
)


# ── Runtime state (set in main) ──────────────────────────────────────────
WOBA_WEIGHTS = None
FIP_CONSTANT = None
GUTS_EXTRA = None
PARK_FACTORS = None


def generate_micro_data(all_pitches):
    """Generate micro-aggregate data for client-side date and opponent-hand filtering.

    Groups pitches by (person, date, opponent_hand) with summable counts.
    Returns a dict with compact arrays-of-arrays format for JSON serialization.

    Filter-responsive stats (recomputed client-side when date/hand filters change):
      Pitcher: velocity, spin, movement, nVAA/nHAA, whiff%, chase%, strike%, xIVB/xHB, etc.
      Hitter: EV, barrel%, hard-hit%, GB%, swing%, chase%, contact%, bat speed, etc.

    Season-level stats (NOT recomputed by filters — use pre-agg values):
      medLA, ldPct/fbPct/puPct, pullPct/middlePct/oppoPct, izSwingPct, izSwChase,
      contactPct, izContactPct, attackAngle/attackDirection/swingPathTilt,
      twoStrikeWhiffPct, firstPitchSwingPct, sprintSpeed, nCompSwings,
      runValue/rv100 (pitchers), xBA/xSLG/xwOBA/xwOBAcon (require Statcast model).
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
    #  42:sumPlateZ 43:nPlateZ
    #  44:sumTiltSin 45:sumTiltCos 46:nTilt
    #  47:sumPlateX 48:nPlateX
    #  49:sumEffVelo 50:nEffVelo
    # ==========================================================
    METRIC_OFFSETS = [
        ('Velocity', 22), ('Spin Rate', 24), ('xIndVrtBrk', 26),
        ('xHorzBrk', 28), ('RelPosZ', 30), ('RelPosX', 32),
        ('Extension', 34), ('ArmAngle', 36), ('VAA', 38), ('HAA', 40),
        ('PlateZ', 42), ('PlateX', 47), ('EffectiveVelo', 49),
    ]

    pitch_micro = defaultdict(lambda: [0.0] * 51)

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
            c[44] += math.sin(angle)
            c[45] += math.cos(angle)
            c[46] += 1

    pitch_rows = []
    for (pi, ti, throws, pti, di, bh), c in pitch_micro.items():
        row = [pi, ti, throws, pti, di, bh]
        # 22 integer/float counts (0-21)
        for i in range(22):
            row.append(int(c[i]))
        # 13 metric sum/count pairs
        for col_name, offset in METRIC_OFFSETS:
            row.append(round(c[offset], 2))       # metric sum
            row.append(int(c[offset + 1]))         # metric count
        # Tilt sin/cos
        row.append(round(c[44], 6))  # sumTiltSin
        row.append(round(c[45], 6))  # sumTiltCos
        row.append(int(c[46]))       # nTilt
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

        hc_x = safe_float(p.get('HC_X'))
        hc_y = safe_float(p.get('HC_Y'))
        pitcher_bip_rows.append([
            pi_idx[pitcher],
            tm_idx[team],
            dt_idx[date],
            batter_hand,
            round(ev, 1) if ev is not None else None,
            round(la, 1) if la is not None else None,
            bb_code,
            round(hc_x, 2) if hc_x is not None else None,
            round(hc_y, 2) if hc_y is not None else None,
            batter_hand,
        ])
    print(f"  Pitcher BIP records: {len(pitcher_bip_rows)}")

    # ==========================================================
    #  Hitter micro-aggs
    #  Key: (hitterIdx, teamIdx, bats, dateIdx, pitcherHand)
    #  bats = actual batting side for these pitches (R/L)
    #  Values: 47 count fields
    #  0:n  1:pa  2:h  3:db  4:tp  5:hr  6:bb  7:hbp  8:sf  9:sh  10:ci  11:k
    #  12:swings  13:whiffs  14:izPitches  15:oozPitches
    #  16:izSwings  17:oozSwings  18:contact
    #  19:izSwNonBunt  20:izContact
    #  21:bip  22:gb  23:ld  24:fb  25:pu
    #  26:barrels  27:nSpray  28:pull  29:center  30:oppo  31:airPull
    #  32:hardHit  33:nHrBip  34:ldHr
    #  35:twoStrikeSwings  36:twoStrikeWhiffs
    #  37:firstPitchAppearances  38:firstPitchSwings
    #  39:xBA_sum  40:xBA_count  41:xSLG_sum  42:xSLG_count
    #  43:xwOBA_sum  44:xwOBA_count  45:xwOBAcon_sum  46:xwOBAcon_count
    # ==========================================================
    hitter_micro = defaultdict(lambda: [0.0] * 49)

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

        # Contact excluding bunts (for contactPct)
        if desc in SWING_DESCRIPTIONS and bb_type not in BUNT_BB_TYPES:
            c[47] += 1  # swingsNonBunt
        if desc in ('Foul', 'In Play') and bb_type not in BUNT_BB_TYPES:
            c[48] += 1  # contactNonBunt

        # Batted ball data (non-bunt BIPs)
        if bb_type and bb_type not in BUNT_BB_TYPES:
            c[21] += 1  # bip
            if bb_type == 'ground_ball':  c[22] += 1  # gb
            if bb_type == 'line_drive':   c[23] += 1  # ld
            if bb_type == 'fly_ball':     c[24] += 1  # fb
            if bb_type == 'popup':        c[25] += 1  # pu

            # Barrel, hard-hit, HR on BIP
            ev = safe_float(p.get('ExitVelo'))
            la = safe_float(p.get('LaunchAngle'))
            barrel_val = str(p.get('Barrel', '')).strip()
            if barrel_val == '6' or (barrel_val == '' and is_barrel(ev, la)):
                c[26] += 1
            if ev is not None and ev >= 95:
                c[32] += 1  # hardHit
            if event == 'Home Run':
                c[33] += 1  # nHrBip
                if bb_type == 'line_drive':
                    c[34] += 1  # ldHr (line-drive HRs)

            # Spray direction
            hc_x = safe_float(p.get('HC_X'))
            hc_y = safe_float(p.get('HC_Y'))
            sa = spray_angle(hc_x, hc_y)
            sd = spray_direction(sa, bats)
            if sd:
                c[27] += 1  # nSpray
                if sd in ('pull', 'pull_side'):    c[28] += 1
                if sd in ('center_pull', 'center_oppo'):  c[29] += 1
                if sd in ('oppo_side', 'oppo'):    c[30] += 1
                if sd in ('pull', 'pull_side') and bb_type in ('line_drive', 'fly_ball', 'popup'):
                    c[31] += 1  # airPull

            # Expected stats from Statcast per-pitch values (BIP only: xBA, xSLG, xwOBAcon)
            xba_val = safe_float(p.get('xBA'))
            xslg_val = safe_float(p.get('xSLG'))
            xwobacon_val = safe_float(p.get('xwOBA'))
            if xba_val is not None:
                c[39] += xba_val; c[40] += 1
            if xslg_val is not None:
                c[41] += xslg_val; c[42] += 1
            if xwobacon_val is not None:
                c[45] += xwobacon_val; c[46] += 1

        # xwOBA: assigned to ALL PA events (K, BB, HBP, BIP), not just BIPs
        if event and event not in NON_PA_EVENTS and event != 'Intent Walk':
            xwoba_val = safe_float(p.get('xwOBA'))
            if xwoba_val is not None:
                c[43] += xwoba_val; c[44] += 1

        # Count-leverage stats (outside BIP block — applies to all pitches)
        count_str = p.get('Count', '')
        if count_str:
            strikes = count_str.split('-')[1] if '-' in count_str else ''
            if strikes == '2':
                if desc in SWING_DESCRIPTIONS:
                    c[35] += 1  # twoStrikeSwings
                if desc == 'Swinging Strike':
                    c[36] += 1  # twoStrikeWhiffs
            if count_str == '0-0':
                c[37] += 1  # firstPitchAppearances
                if desc in SWING_DESCRIPTIONS:
                    c[38] += 1  # firstPitchSwings

    hitter_rows = []
    for (hi, ti, bats, di, ph), c in hitter_micro.items():
        row = [hi, ti, bats, di, ph]
        for i in range(49):
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
        bat_side = p.get('Bats')
        if not bat_side:
            bat_side = 'R'  # default to RHB if Bats field missing
        hitter_bip_rows.append([
            hi_idx[batter],
            tm_idx[team],
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
    #  Same 47 count fields as hitter micro
    # ==========================================================
    hitter_pitch_micro = defaultdict(lambda: [0.0] * 49)

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

        # Contact excluding bunts (for contactPct)
        if desc in SWING_DESCRIPTIONS and bb_type not in BUNT_BB_TYPES:
            c[47] += 1  # swingsNonBunt
        if desc in ('Foul', 'In Play') and bb_type not in BUNT_BB_TYPES:
            c[48] += 1  # contactNonBunt

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
            if event == 'Home Run':
                c[33] += 1  # nHrBip
                if bb_type == 'line_drive':
                    c[34] += 1  # ldHr

            hc_x = safe_float(p.get('HC_X'))
            hc_y = safe_float(p.get('HC_Y'))
            sa = spray_angle(hc_x, hc_y)
            sd = spray_direction(sa, bats)
            if sd:
                c[27] += 1
                if sd in ('pull', 'pull_side'):    c[28] += 1
                if sd in ('center_pull', 'center_oppo'):  c[29] += 1
                if sd in ('oppo_side', 'oppo'):    c[30] += 1
                if sd in ('pull', 'pull_side') and bb_type in ('line_drive', 'fly_ball', 'popup'):
                    c[31] += 1

            # Expected stats from Statcast per-pitch values (BIP only: xBA, xSLG, xwOBAcon)
            xba_val = safe_float(p.get('xBA'))
            xslg_val = safe_float(p.get('xSLG'))
            xwobacon_val = safe_float(p.get('xwOBA'))
            if xba_val is not None:
                c[39] += xba_val; c[40] += 1
            if xslg_val is not None:
                c[41] += xslg_val; c[42] += 1
            if xwobacon_val is not None:
                c[45] += xwobacon_val; c[46] += 1

        # xwOBA: assigned to ALL PA events (K, BB, HBP, BIP), not just BIPs
        if event and event not in NON_PA_EVENTS and event != 'Intent Walk':
            xwoba_val = safe_float(p.get('xwOBA'))
            if xwoba_val is not None:
                c[43] += xwoba_val; c[44] += 1

        # Count-leverage stats
        count_str = p.get('Count', '')
        if count_str:
            strikes = count_str.split('-')[1] if '-' in count_str else ''
            if strikes == '2':
                if desc in SWING_DESCRIPTIONS:
                    c[35] += 1  # twoStrikeSwings
                if desc == 'Swinging Strike':
                    c[36] += 1  # twoStrikeWhiffs
            if count_str == '0-0':
                c[37] += 1  # firstPitchAppearances
                if desc in SWING_DESCRIPTIONS:
                    c[38] += 1  # firstPitchSwings

    hitter_pitch_rows = []
    for (hi, ti, bats, pti, di, ph), c in hitter_pitch_micro.items():
        row = [hi, ti, bats, pti, di, ph]
        for i in range(49):
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
            tm_idx[team],
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

        key = (pi_idx[pitcher], tm_idx[team], pt_idx[pitch_type], dt_idx[date])
        velo_trend[key][0] += velo
        velo_trend[key][1] += 1

    velo_trend_rows = []
    for (pi, ti, pti, di), (s, n) in velo_trend.items():
        velo_trend_rows.append([pi, ti, pti, di, round(s, 1), n])
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
        'pitcherBipCols': ['pitcherIdx', 'teamIdx', 'dateIdx', 'batterHand', 'exitVelo', 'launchAngle', 'bbType', 'hcX', 'hcY', 'bats'],
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
            'sumPlateZ', 'nPlateZ',
            'sumPlateX', 'nPlateX',
            'sumEffVelo', 'nEffVelo',
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
            'hardHit', 'nHrBip', 'ldHr',
            'twoStrikeSwings', 'twoStrikeWhiffs',
            'firstPitchAppearances', 'firstPitchSwings',
            'xBA_sum', 'xBA_count', 'xSLG_sum', 'xSLG_count',
            'xwOBA_sum', 'xwOBA_count', 'xwOBAcon_sum', 'xwOBAcon_count',
        ],
        'hitterMicro': hitter_rows,
        'hitterBipCols': ['hitterIdx', 'teamIdx', 'dateIdx', 'pitcherHand', 'batSide', 'exitVelo', 'launchAngle', 'hcX', 'hcY', 'bbType', 'event', 'distance', 'wOBAval'],
        'hitterBip': hitter_bip_rows,
        'hitterPitchCols': [
            'hitterIdx', 'teamIdx', 'bats', 'pitchTypeIdx', 'dateIdx', 'pitcherHand',
            'n', 'pa', 'h', 'db', 'tp', 'hr', 'bb', 'hbp', 'sf', 'sh', 'ci', 'k',
            'swings', 'whiffs', 'izPitches', 'oozPitches', 'izSwings', 'oozSwings',
            'contact', 'izSwNonBunt', 'izContact',
            'bip', 'gb', 'ld', 'fb', 'pu',
            'barrels', 'nSpray', 'pull', 'center', 'oppo', 'airPull',
            'hardHit', 'nHrBip', 'ldHr',
            'twoStrikeSwings', 'twoStrikeWhiffs',
            'firstPitchAppearances', 'firstPitchSwings',
            'xBA_sum', 'xBA_count', 'xSLG_sum', 'xSLG_count',
            'xwOBA_sum', 'xwOBA_count', 'xwOBAcon_sum', 'xwOBAcon_count',
        ],
        'hitterPitchMicro': hitter_pitch_rows,
        'hitterPitchBipCols': ['hitterIdx', 'teamIdx', 'pitchTypeIdx', 'dateIdx', 'pitcherHand', 'exitVelo', 'launchAngle'],
        'hitterPitchBip': hitter_pitch_bip_rows,
        'veloTrendCols': ['pitcherIdx', 'teamIdx', 'pitchTypeIdx', 'dateIdx', 'sumVelo', 'nVelo'],
        'veloTrend': velo_trend_rows,
    }


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
                'vaaRegressions': {},
                'haaRegressions': {},
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
            # Don't remap AAA-source pitches — these hitters are actually playing in AAA
            if p.get('_source') == 'AAA':
                continue
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

    # --- Reclassify CF (Cut-Fastball) → FF or FC ---
    # CF is not a real Statcast classification. Remap to FF by default,
    # except specific pitchers whose "CF" is really a cutter (FC).
    CF_TO_FC_PITCHERS = {
        'Ashcraft, Graham', 'Doval, Camilo', 'Fluharty, Mason',
        'Funderburk, Kody', 'Jansen, Kenley', 'Maton, Phil',
    }
    cf_to_ff = 0
    cf_to_fc = 0
    for p in all_pitches:
        if p.get('Pitch Type') == 'CF':
            pitcher = p.get('Pitcher', '')
            if pitcher in CF_TO_FC_PITCHERS:
                p['Pitch Type'] = 'FC'
                cf_to_fc += 1
            else:
                p['Pitch Type'] = 'FF'
                cf_to_ff += 1
    if cf_to_ff or cf_to_fc:
        print(f"  Reclassified CF: {cf_to_ff} → FF, {cf_to_fc} → FC")

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
        row.update(compute_expected_stats(pitches, woba_weights=WOBA_WEIGHTS))
        row.update(compute_xrv(pitches,
                                lg_woba=GUTS_EXTRA.get('lgWOBA') if GUTS_EXTRA else None,
                                woba_scale=GUTS_EXTRA.get('wOBAScale') if GUTS_EXTRA else None))
        # RV/100 and xRV/100 for this pitch type (raw — rounded at final output step)
        if row.get('runValue') is not None and row.get('count', 0) > 0:
            row['rv100'] = row['runValue'] / row['count'] * 100
        else:
            row['rv100'] = None
        if row.get('xRunValue') is not None and row.get('count', 0) > 0:
            row['xRv100'] = row['xRunValue'] / row['count'] * 100
        else:
            row['xRv100'] = None

        # Per-hand splits at pitch type level (for platoon toggle)
        for hand_label, hand_val in [('_vsL', 'L'), ('_vsR', 'R')]:
            hand_pitches = [p for p in pitches if p.get('Bats') == hand_val]
            if hand_pitches:
                hand_bb = compute_pitcher_batted_ball(hand_pitches)
                hand_ex = compute_expected_stats(hand_pitches, woba_weights=WOBA_WEIGHTS)
                for sk in ['avgEVAgainst', 'maxEVAgainst', 'hardHitPct', 'barrelPctAgainst',
                           'ldPct', 'fbPct', 'puPct', 'hrFbPct']:
                    if sk in hand_bb and hand_bb[sk] is not None:
                        row[sk + hand_label] = hand_bb[sk]
                for sk in ['wOBA', 'xBA', 'xSLG', 'xwOBA', 'xwOBAcon']:
                    if sk in hand_ex and hand_ex[sk] is not None:
                        row[sk + hand_label] = hand_ex[sk]

        pitch_leaderboard.append(row)

    # --- Regression helper functions ---
    def fit_linear_regression(pairs, label):
        """Fit y = slope*x + intercept, return dict with coefficients or None."""
        if len(pairs) < 30:
            return None
        n = len(pairs)
        sum_x = sum(p[0] for p in pairs)
        sum_y = sum(p[1] for p in pairs)
        sum_xy = sum(p[0] * p[1] for p in pairs)
        sum_x2 = sum(p[0] ** 2 for p in pairs)
        mean_x = sum_x / n
        mean_y = sum_y / n
        denom = sum_x2 - n * mean_x ** 2
        if abs(denom) < 1e-10:
            return None
        slope = (sum_xy - n * mean_x * mean_y) / denom
        intercept = mean_y - slope * mean_x
        ss_res = sum((p[1] - (slope * p[0] + intercept)) ** 2 for p in pairs)
        ss_tot = sum((p[1] - mean_y) ** 2 for p in pairs)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        print(f"  {label}: slope={slope:.4f}, intercept={intercept:.4f}, R²={r2:.4f} (n={n})")
        return {'slope': slope, 'intercept': intercept, 'r2': r2, 'n': n}

    def mat_inv_general(M):
        """Invert a square matrix via Gauss-Jordan elimination with partial pivoting."""
        n = len(M)
        aug = [list(M[i]) + [1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
        for col in range(n):
            max_row = col
            for r in range(col + 1, n):
                if abs(aug[r][col]) > abs(aug[max_row][col]):
                    max_row = r
            aug[col], aug[max_row] = aug[max_row], aug[col]
            if abs(aug[col][col]) < 1e-12:
                return None
            for r in range(col + 1, n):
                f = aug[r][col] / aug[col][col]
                for c in range(2 * n):
                    aug[r][c] -= f * aug[col][c]
        for col in range(n - 1, -1, -1):
            piv = aug[col][col]
            for c in range(2 * n):
                aug[col][c] /= piv
            for r in range(col):
                f = aug[r][col]
                for c in range(2 * n):
                    aug[r][c] -= f * aug[col][c]
        return [aug[i][n:] for i in range(n)]

    def mvn_conditional(model_params, rel_values):
        """Compute E[IVB, HB | regressors] using MVN conditional distribution.
        model_params: dict with 'mu' (list) and 'cov' (list of lists).
        rel_values: list of regressor values (length = len(mu) - 2).
        Returns [xIVB, xHB] or None."""
        mu = model_params['mu']
        cov = model_params['cov']
        n_acc = 2  # IVB, HB
        n_rel = len(mu) - n_acc
        if len(rel_values) != n_rel:
            return None
        sigma_rel = [[cov[n_acc + i][n_acc + j] for j in range(n_rel)] for i in range(n_rel)]
        sigma_rel_inv = mat_inv_general(sigma_rel)
        if sigma_rel_inv is None:
            return None
        r_diff = [rel_values[k] - mu[n_acc + k] for k in range(n_rel)]
        sri_rdiff = [sum(sigma_rel_inv[i][j] * r_diff[j] for j in range(n_rel)) for i in range(n_rel)]
        mu_bar = []
        for a in range(n_acc):
            adj = sum(cov[a][n_acc + b] * sri_rdiff[b] for b in range(n_rel))
            mu_bar.append(mu[a] + adj)
        return mu_bar

    def fit_mvn_models(all_pitches):
        """Fit MVN models per (pitchType, throws) for expected movement.
        MLB model: [IVB, HB, ArmAngle, Extension, Velocity]
        ROC model: [IVB, HB, RelPosZ, RelPosX, Extension, Velocity]
        Returns dict keyed by 'pitchType_throws' with 'mlb' and/or 'roc' sub-models."""
        groups_mlb = defaultdict(list)
        groups_roc = defaultdict(list)
        for p in all_pitches:
            pt = p.get('Pitch Type') or p.get('TaggedPitchType')
            throws = p.get('Throws')
            ivb = safe_float(p.get('xIndVrtBrk'))
            hb = safe_float(p.get('xHorzBrk'))
            if not pt or not throws or ivb is None or hb is None:
                continue
            key = pt + '_' + throws
            aa = safe_float(p.get('ArmAngle'))
            ext = safe_float(p.get('Extension'))
            velo = safe_float(p.get('Velocity'))
            rel_z = safe_float(p.get('RelPosZ'))
            rel_x = safe_float(p.get('RelPosX'))
            if aa is not None and ext is not None and velo is not None:
                groups_mlb[key].append([ivb, hb, aa, ext, velo])
            if rel_z is not None and rel_x is not None and ext is not None and velo is not None:
                groups_roc[key].append([ivb, hb, rel_z, rel_x, ext, velo])

        def compute_mu_cov(data):
            n = len(data)
            k = len(data[0])
            mu = [sum(row[i] for row in data) / n for i in range(k)]
            cov = [[0.0] * k for _ in range(k)]
            for row in data:
                for i in range(k):
                    for j in range(k):
                        cov[i][j] += (row[i] - mu[i]) * (row[j] - mu[j])
            for i in range(k):
                for j in range(k):
                    cov[i][j] /= (n - 1)
            return mu, cov

        models = {}
        all_keys = set(list(groups_mlb.keys()) + list(groups_roc.keys()))
        for key in sorted(all_keys):
            model = {}
            if key in groups_mlb and len(groups_mlb[key]) >= 30:
                mu, cov = compute_mu_cov(groups_mlb[key])
                model['mlb'] = {'mu': mu, 'cov': cov, 'n': len(groups_mlb[key])}
            if key in groups_roc and len(groups_roc[key]) >= 30:
                mu, cov = compute_mu_cov(groups_roc[key])
                model['roc'] = {'mu': mu, 'cov': cov, 'n': len(groups_roc[key])}
            if model:
                models[key] = model
        return models

    # --- Fit VAA ~ PlateZ regressions per pitch type (MLB only) ---
    # Per-pitch-type slopes capture that different pitches have different VAA~PlateZ relationships
    vaa_reg_by_pt = defaultdict(list)  # pitch_type -> [(plateZ, vaa)]
    for p in all_pitches:
        if p.get('_source', 'MLB') != 'MLB':
            continue
        pt = p.get('Pitch Type') or p.get('TaggedPitchType')
        vaa_val = safe_float(p.get('VAA'))
        pz_val = safe_float(p.get('PlateZ'))
        if pt and vaa_val is not None and pz_val is not None:
            vaa_reg_by_pt[pt].append((pz_val, vaa_val))

    print("\nVAA ~ PlateZ regressions (per pitch type):")
    vaa_regressions = {}  # pitch_type -> {slope, intercept, leagueAvgPlateZ}
    for pt in sorted(vaa_reg_by_pt.keys()):
        pairs = vaa_reg_by_pt[pt]
        result = fit_linear_regression(pairs, f"VAA~PlateZ {pt}")
        if result:
            mean_pz = sum(p[0] for p in pairs) / len(pairs)
            vaa_regressions[pt] = {
                'slope': result['slope'],
                'intercept': result['intercept'],
                'leagueAvgPlateZ': mean_pz,
            }

    # Compute nVAA for each pitch leaderboard row using per-pitch-type slope
    for row in pitch_leaderboard:
        if row.get('vaa') is not None:
            pt = row['pitchType']
            reg = vaa_regressions.get(pt)
            if reg:
                key = (row['pitcher'], row['team'], row['pitchType'], row.get('throws'))
                pitches_for_row = pitch_groups[key]
                pz_vals = [safe_float(p.get('PlateZ')) for p in pitches_for_row]
                pz_vals = [v for v in pz_vals if v is not None]
                if pz_vals:
                    avg_pz = sum(pz_vals) / len(pz_vals)
                    row['nVAA'] = round(row['vaa'] - reg['slope'] * (avg_pz - reg['leagueAvgPlateZ']), 2)
                else:
                    row['nVAA'] = None
            else:
                row['nVAA'] = None
        else:
            row['nVAA'] = None

    # --- Fit HAA ~ PlateX regressions per pitch type (MLB only) ---
    # Per-pitch-type slopes are critical: breaking balls (SL slope ~3.6, ST ~4.9) vs fastballs (SI ~0.17)
    haa_reg_by_pt = defaultdict(list)  # pitch_type -> [(plateX, haa)]
    for p in all_pitches:
        if p.get('_source', 'MLB') != 'MLB':
            continue
        pt = p.get('Pitch Type') or p.get('TaggedPitchType')
        haa_val = safe_float(p.get('HAA'))
        px_val = safe_float(p.get('PlateX'))
        if pt and haa_val is not None and px_val is not None:
            haa_reg_by_pt[pt].append((px_val, haa_val))

    print("\nHAA ~ PlateX regressions (per pitch type):")
    haa_regressions = {}  # pitch_type -> {slope, intercept, leagueAvgPlateX}
    for pt in sorted(haa_reg_by_pt.keys()):
        pairs = haa_reg_by_pt[pt]
        result = fit_linear_regression(pairs, f"HAA~PlateX {pt}")
        if result:
            mean_px = sum(p[0] for p in pairs) / len(pairs)
            haa_regressions[pt] = {
                'slope': result['slope'],
                'intercept': result['intercept'],
                'leagueAvgPlateX': mean_px,
            }

    # Compute nHAA for each pitch leaderboard row using per-pitch-type slope
    for row in pitch_leaderboard:
        if row.get('haa') is not None:
            pt = row['pitchType']
            reg = haa_regressions.get(pt)
            if reg:
                key = (row['pitcher'], row['team'], row['pitchType'], row.get('throws'))
                pitches_for_row = pitch_groups[key]
                px_vals = [safe_float(p.get('PlateX')) for p in pitches_for_row]
                px_vals = [v for v in px_vals if v is not None]
                if px_vals:
                    avg_px = sum(px_vals) / len(px_vals)
                    row['nHAA'] = round(row['haa'] - reg['slope'] * (avg_px - reg['leagueAvgPlateX']), 2)
                else:
                    row['nHAA'] = None
            else:
                row['nHAA'] = None
        else:
            row['nHAA'] = None

    # --- Fit MVN expected movement models per pitch type + handedness ---
    mvn_models = fit_mvn_models(all_pitches)
    print(f"\nMVN models fitted for {len(mvn_models)} pitch-type+hand groups")
    for mvn_key, mvn_sub in sorted(mvn_models.items()):
        mlb_n = mvn_sub.get('mlb', {}).get('n', 0)
        roc_n = mvn_sub.get('roc', {}).get('n', 0)
        print(f"  {mvn_key}: MLB n={mlb_n}, ROC n={roc_n}")

    def compute_expected_movement(pitch_type, throws, arm_angle, extension, velocity, rel_z, rel_x):
        """Compute xIVB and xHB using MVN conditional model per pitch type + handedness.
        Tries MLB model (ArmAngle, Extension, Velocity) first,
        falls back to ROC model (RelPosZ, RelPosX, Extension, Velocity)."""
        mvn_key = (pitch_type or '') + '_' + (throws or '')
        pt_model = mvn_models.get(mvn_key)
        if not pt_model:
            return None, None
        if pt_model.get('mlb') and arm_angle is not None and extension is not None and velocity is not None:
            result = mvn_conditional(pt_model['mlb'], [arm_angle, extension, velocity])
            if result:
                return result[0], result[1]
        if pt_model.get('roc') and rel_z is not None and rel_x is not None and extension is not None and velocity is not None:
            result = mvn_conditional(pt_model['roc'], [rel_z, rel_x, extension, velocity])
            if result:
                return result[0], result[1]
        return None, None

    # Compute xIVB/xHB (expected) and IVBOE/HBOE (residual) for each pitch leaderboard row
    for row in pitch_leaderboard:
        xivb, xhb = compute_expected_movement(
            row.get('pitchType'), row.get('throws'),
            row.get('armAngle'), row.get('extension'), row.get('velocity'),
            row.get('relPosZ'), row.get('relPosX')
        )
        if xivb is not None:
            row['xIVB'] = round(xivb, 1)
            if row.get('indVertBrk') is not None:
                row['ivbOE'] = round(row['indVertBrk'] - xivb, 1)
            else:
                row['ivbOE'] = None
        else:
            row['xIVB'] = None
            row['ivbOE'] = None
        if xhb is not None:
            row['xHB'] = round(xhb, 1)
            if row.get('horzBrk') is not None:
                row['hbOE'] = round(row['horzBrk'] - xhb, 1)
            else:
                row['hbOE'] = None
        else:
            row['xHB'] = None
            row['hbOE'] = None

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

    PITCHER_METRIC_COLS = ['RelPosZ', 'RelPosX', 'Extension', 'ArmAngle', 'VAA', 'HAA']
    PITCHER_METRIC_PCTL_KEYS = [METRIC_KEYS[c] for c in PITCHER_METRIC_COLS]
    EXPECTED_KEYS = ['wOBA', 'xBA', 'xSLG', 'xwOBA', 'xwOBAcon']
    EXPECTED_PITCHER_INVERT = {'wOBA', 'xBA', 'xSLG', 'xwOBA', 'xwOBAcon'}
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
        row.update(compute_expected_stats(pitches, woba_weights=WOBA_WEIGHTS))

        # Per-hand splits for stats not in micro data (2K Whiff%, plate disc, batted ball, expected)
        for hand_label, hand_val in [('_vsL', 'L'), ('_vsR', 'R')]:
            hand_pitches = [p for p in pitches if p.get('Bats') == hand_val]
            if hand_pitches:
                hand_stats = compute_stats(hand_pitches)
                hand_bb = compute_pitcher_batted_ball(hand_pitches)
                hand_ex = compute_expected_stats(hand_pitches, woba_weights=WOBA_WEIGHTS)
                for suffix_key in ['twoStrikeWhiffPct', 'fpsPct',
                                   'strikePct', 'izPct', 'swStrPct', 'cswPct',
                                   'izWhiffPct', 'chasePct', 'kPct', 'bbPct', 'kbbPct',
                                   'babip', 'gbPct']:
                    if suffix_key in hand_stats:
                        row[suffix_key + hand_label] = hand_stats[suffix_key]
                for suffix_key in ['avgEV', 'maxEV', 'hardHitPct', 'barrelPct',
                                   'gbPct_bb', 'ldPct', 'fbPct', 'puPct', 'hrFbPct']:
                    if suffix_key in hand_bb:
                        row[suffix_key + hand_label] = hand_bb[suffix_key]
                for suffix_key in ['wOBA', 'xBA', 'xSLG', 'xwOBA', 'xwOBAcon']:
                    if suffix_key in hand_ex:
                        row[suffix_key + hand_label] = hand_ex[suffix_key]

        # Fastball velo: average velo of most-used fastball (FF/SI)
        fb_types = {'FF', 'SI'}
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

    # Recompute pitcher runValue as sum of raw (unrounded) per-pitch-type runValues.
    # Rounding only happens at the final step to avoid accumulation error.
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
            row['runValue'] = pitch_rv_by_pitcher[pk]

    # Recompute pitcher xRunValue as sum of raw per-pitch-type xRunValues
    pitch_xrv_by_pitcher = {}
    for pr in pitch_leaderboard:
        pk = pr['pitcher'] + '|' + pr['team']
        if pr.get('xRunValue') is not None:
            if pk not in pitch_xrv_by_pitcher:
                pitch_xrv_by_pitcher[pk] = 0.0
            pitch_xrv_by_pitcher[pk] += pr['xRunValue']
    for row in pitcher_leaderboard:
        pk = row['pitcher'] + '|' + row['team']
        if pk in pitch_xrv_by_pitcher:
            row['xRunValue'] = pitch_xrv_by_pitcher[pk]

    # Compute RV/100 and xRV/100 from raw values before rounding
    for row in pitcher_leaderboard:
        if row.get('runValue') is not None and row.get('count', 0) > 0:
            row['rv100'] = row['runValue'] / row['count'] * 100
        else:
            row['rv100'] = None
        if row.get('xRunValue') is not None and row.get('count', 0) > 0:
            row['xRv100'] = row['xRunValue'] / row['count'] * 100
        else:
            row['xRv100'] = None

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
        ivb = safe_float(p.get('xIndVrtBrk'))
        hb = safe_float(p.get('xHorzBrk'))
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
            # Per-pitch expected movement from MVN conditional model
            ext_val = safe_float(p.get('Extension'))
            throws_val = p.get('Throws')
            xivb_val, xhb_val = compute_expected_movement(pt, throws_val, aa_val, ext_val, velo, rel_z, rel_x)
            if xivb_val is not None:
                detail['xivb'] = round(xivb_val, 1)
            if xhb_val is not None:
                detail['xhb'] = round(xhb_val, 1)
            pitch_details[pitcher + '|' + (team or '')].append(detail)
    print(f"Pitch details: {sum(len(v) for v in pitch_details.values())} pitches for {len(pitch_details)} pitchers")

    # --- League Averages per pitch type (weighted by pitch count, MLB only) ---
    pt_groups = defaultdict(list)
    for row in pitch_leaderboard:
        pt_groups[row['pitchType']].append(row)

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
    # Build both hand-specific (spray_dir, la_bin, bats) and pooled (spray_dir, la_bin) tables.
    # Hand-specific captures L/R differences in HR-range zones (park geometry, defensive positioning).
    # Pooled serves as fallback when hand-specific bins are too thin.
    _empty_bin = lambda: {'woba_sum': 0.0, 'woba_denom': 0.0, 'xwoba_sum': 0.0, 'xwoba_count': 0, 'count': 0}
    sacq_bins_hand = {}   # (spray_dir, la_bin_idx, bats) → accumulators
    sacq_bins_pooled = {} # (spray_dir, la_bin_idx) → accumulators
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
        la_bin_idx = None
        for bi, (lo, hi) in enumerate(LA_BINS):
            if lo <= la < hi:
                la_bin_idx = bi
                break
        if la_bin_idx is None:
            continue
        # Accumulate into both hand-specific and pooled bins
        for key, table in [((direction, la_bin_idx, bats), sacq_bins_hand),
                           ((direction, la_bin_idx), sacq_bins_pooled)]:
            if key not in table:
                table[key] = _empty_bin()
            table[key]['count'] += 1
            if woba_val is not None and woba_dom is not None and woba_dom > 0:
                table[key]['woba_sum'] += woba_val
                table[key]['woba_denom'] += woba_dom
            if xwoba_val is not None:
                table[key]['xwoba_sum'] += xwoba_val
                table[key]['xwoba_count'] += 1

    def _finalize_bins(bins):
        table = {}
        for key, data in bins.items():
            woba = data['woba_sum'] / data['woba_denom'] if data['woba_denom'] > 0 else None
            xwobacon = data['xwoba_sum'] / data['xwoba_count'] if data['xwoba_count'] > 0 else None
            quality = (data['count'] >= SACQ_MIN_BIP and woba is not None and woba >= SACQ_QUALITY_THRESHOLD)
            table[key] = {
                'woba': round(woba, 3) if woba is not None else None,
                'xwobacon': round(xwobacon, 3) if xwobacon is not None else None,
                'quality': quality,
                'count': data['count'],
            }
        return table

    sacq_zone_hand = _finalize_bins(sacq_bins_hand)
    sacq_zone_pooled = _finalize_bins(sacq_bins_pooled)

    def sacq_lookup(direction, la_bin_idx, bats_val):
        """Look up zone wOBA: try hand-specific first, fall back to pooled."""
        hand_info = sacq_zone_hand.get((direction, la_bin_idx, bats_val))
        if hand_info and hand_info['count'] >= SACQ_MIN_BIP and hand_info['woba'] is not None:
            return hand_info['woba']
        pooled_info = sacq_zone_pooled.get((direction, la_bin_idx))
        if pooled_info and pooled_info['count'] >= SACQ_MIN_BIP and pooled_info['woba'] is not None:
            return pooled_info['woba']
        return None

    # Build serializable zone data for frontend (hand-specific + pooled)
    sacq_zones_output = []
    for (direction, la_bin_idx, bats_key), info in sorted(sacq_zone_hand.items(), key=lambda x: (x[0][2], x[0][0], x[0][1])):
        lo, hi = LA_BINS[la_bin_idx]
        sacq_zones_output.append({
            'spray': direction,
            'laMin': lo if lo > -999 else None,
            'laMax': hi if hi < 999 else None,
            'laBin': la_bin_idx,
            'bats': bats_key,
            'woba': info['woba'],
            'xwobacon': info['xwobacon'],
            'quality': info['quality'],
            'count': info['count'],
        })
    # Also include pooled bins (bats=null) as fallback for frontend
    for (direction, la_bin_idx), info in sorted(sacq_zone_pooled.items(), key=lambda x: (x[0][0], x[0][1])):
        lo, hi = LA_BINS[la_bin_idx]
        sacq_zones_output.append({
            'spray': direction,
            'laMin': lo if lo > -999 else None,
            'laMax': hi if hi < 999 else None,
            'laBin': la_bin_idx,
            'bats': None,
            'woba': info['woba'],
            'xwobacon': info['xwobacon'],
            'quality': info['quality'],
            'count': info['count'],
        })
    n_hand_quality = sum(1 for v in sacq_zone_hand.values() if v['quality'])
    n_pooled_quality = sum(1 for v in sacq_zone_pooled.values() if v['quality'])
    print(f"  SACQ zones: {len(sacq_zone_hand)} hand-specific ({n_hand_quality} quality), "
          f"{len(sacq_zone_pooled)} pooled ({n_pooled_quality} quality)")

    # --- Helper: compute xwOBAsp for a list of pitches using sacq_lookup ---
    def compute_xwobasp(pitches):
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
            zone_woba = sacq_lookup(direction, la_bin_idx, bats_val)
            if zone_woba is not None:
                xwobasp_sum += zone_woba
                xwobasp_count += 1
        return round(xwobasp_sum / xwobasp_count, 3) if xwobasp_count > 0 else None

    # --- Compute xwOBAsp for each pitcher (second pass, requires sacq_zone_table) ---
    pitcher_pitch_lookup = {}
    for (pitcher, team, throws), pitches in pitcher_groups.items():
        pitcher_pitch_lookup[(pitcher, team)] = pitches

    for row in pitcher_leaderboard:
        pitches = pitcher_pitch_lookup.get((row['pitcher'], row['team']), [])
        row['xwOBAsp'] = compute_xwobasp(pitches)

    # --- Compute xwOBAsp per pitch type for pitch_leaderboard ---
    pitch_type_lookup = {}
    for (pitcher, team, pitch_type, throws), pitches in pitch_groups.items():
        pitch_type_lookup[(pitcher, team, pitch_type)] = pitches

    for row in pitch_leaderboard:
        pitches = pitch_type_lookup.get((row['pitcher'], row['team'], row['pitchType']), [])
        row['xwOBAsp'] = compute_xwobasp(pitches)

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
        row.update(compute_expected_stats(pitches, woba_weights=WOBA_WEIGHTS))
        row.update(compute_xrv(pitches,
                                lg_woba=GUTS_EXTRA.get('lgWOBA') if GUTS_EXTRA else None,
                                woba_scale=GUTS_EXTRA.get('wOBAScale') if GUTS_EXTRA else None,
                                negate=True))

        row['xwOBAsp'] = compute_xwobasp(pitches)

        hitter_leaderboard.append(row)

    # --- Merge Sprint Speed from Baseball Savant ---
    sprint_speeds = fetch_sprint_speed()
    sprint_merged = 0
    for row in hitter_leaderboard:
        mlb_id = row.get('mlbId')
        if mlb_id and mlb_id in sprint_speeds:
            ss = sprint_speeds[mlb_id]
            row['sprintSpeed'] = ss['speed']
            row['nCompRuns'] = ss['competitive_runs']
            row['sprintQual'] = ss['competitive_runs'] >= 10
            sprint_merged += 1
        else:
            row['sprintSpeed'] = None
            row['nCompRuns'] = 0
            row['sprintQual'] = False
    print(f"  Sprint speed merged for {sprint_merged}/{len(hitter_leaderboard)} hitters")

    # Flag hitters with sufficient BIP for batted ball percentile qualification
    for row in hitter_leaderboard:
        row['bipQual'] = (row.get('nBip') or 0) >= 20

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
        'wOBA', 'xBA', 'xSLG', 'xwOBA', 'xwOBAcon', 'xwOBAsp',
        'ev50', 'maxEV', 'hardHitPct', 'barrelPct',
        'gbPct', 'ldPct', 'fbPct', 'hrFbPct',
        'pullPct', 'oppoPct',
        'swingPct', 'izSwingPct', 'chasePct', 'contactPct', 'izContactPct', 'whiffPct',
        'runValue', 'rv100', 'xRunValue', 'xRv100',
    ]
    HITTER_PITCH_INVERT_PCTL = {'swingPct', 'chasePct', 'whiffPct', 'gbPct'}

    PITCH_CATEGORIES = {
        'Hard': ['FF', 'SI'],
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
            row.update(compute_expected_stats(pt_pitches, woba_weights=WOBA_WEIGHTS))
            row.update(compute_xrv(pt_pitches,
                                    lg_woba=GUTS_EXTRA.get('lgWOBA') if GUTS_EXTRA else None,
                                    woba_scale=GUTS_EXTRA.get('wOBAScale') if GUTS_EXTRA else None,
                                    negate=True))
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
        row_all.update(compute_expected_stats(pitches, woba_weights=WOBA_WEIGHTS))
        row_all.update(compute_xrv(pitches,
                                    lg_woba=GUTS_EXTRA.get('lgWOBA') if GUTS_EXTRA else None,
                                    woba_scale=GUTS_EXTRA.get('wOBAScale') if GUTS_EXTRA else None,
                                    negate=True))
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
                row_cat.update(compute_expected_stats(cat_pitches, woba_weights=WOBA_WEIGHTS))
                row_cat.update(compute_xrv(cat_pitches,
                                            lg_woba=GUTS_EXTRA.get('lgWOBA') if GUTS_EXTRA else None,
                                            woba_scale=GUTS_EXTRA.get('wOBAScale') if GUTS_EXTRA else None,
                                            negate=True))
                hitter_pitch_leaderboard.append(row_cat)

    # Compute rv100 and xRv100 for hitter pitch leaderboard rows
    for row in hitter_pitch_leaderboard:
        if row.get('runValue') is not None and row.get('count', 0) > 0:
            row['rv100'] = row['runValue'] / row['count'] * 100
        else:
            row['rv100'] = None
        if row.get('xRunValue') is not None and row.get('count', 0) > 0:
            row['xRv100'] = row['xRunValue'] / row['count'] * 100
        else:
            row['xRv100'] = None

    # Compute xwOBAsp per pitch type for hitter_pitch_leaderboard
    for row in hitter_pitch_leaderboard:
        pt = row['pitchType']
        hitter_pitches = hitter_groups.get((row['hitter'], row['team']), [])
        if pt == 'All':
            pt_pitches = hitter_pitches
        elif pt in PITCH_CATEGORIES:
            cat_set = set(PITCH_CATEGORIES[pt])
            pt_pitches = [p for p in hitter_pitches if p.get('Pitch Type') in cat_set]
        else:
            pt_pitches = [p for p in hitter_pitches if p.get('Pitch Type') == pt]
        row['xwOBAsp'] = compute_xwobasp(pt_pitches)

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
    bip_stats = {'avgEVAll', 'ev50', 'maxEV', 'medLA', 'hardHitPct', 'barrelPct',
                 'xwOBAcon', 'xwOBAsp',
                 'gbPct', 'ldPct', 'fbPct', 'puPct',
                 'pullPct', 'middlePct', 'oppoPct', 'airPullPct'}
    # Bat tracking stats weighted by nCompSwings
    comp_swing_stats = {'batSpeed', 'swingLength', 'attackAngle', 'attackDirection', 'swingPathTilt',
                        'blastPct', 'idealAAPct'}
    for stat in HITTER_STAT_KEYS:
        if stat in pa_stats:
            weight_key = 'pa'
        elif stat in bip_stats:
            weight_key = 'nBip'
        elif stat in comp_swing_stats:
            weight_key = 'nCompSwings'
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
        'vaaRegressions': {pt: {'slope': round(r['slope'], 6), 'intercept': round(r['intercept'], 6),
                                  'leagueAvgPlateZ': round(r['leagueAvgPlateZ'], 6)}
                           for pt, r in vaa_regressions.items()},
        'haaRegressions': {pt: {'slope': round(r['slope'], 6), 'intercept': round(r['intercept'], 6),
                                  'leagueAvgPlateX': round(r['leagueAvgPlateX'], 6)}
                           for pt, r in haa_regressions.items()},
        'sacqZones': sacq_zones_output,
        'mvnModels': {
            key: {
                variant: {
                    'mu': [round(v, 6) for v in model['mu']],
                    'cov': [[round(v, 6) for v in row] for row in model['cov']],
                    'n': model['n']
                }
                for variant, model in sub.items()
            }
            for key, sub in mvn_models.items()
        },
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
                box_1b = max(0, box_h - box_2b - box_3b - box_hr)
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
        if ip_float > 0 and FIP_CONSTANT is not None:
            row['fip'] = round(((13 * hr + 3 * (bb + hbp) - 2 * so) / ip_float) + FIP_CONSTANT, 2)
        else:
            row['fip'] = None

        # xFIP: FB includes popups
        n_bip = row.get('nBip', 0) or 0
        fb_pct = row.get('fbPct') or 0
        pu_pct = row.get('puPct') or 0
        fb_count = round((fb_pct + pu_pct) * n_bip)  # fly balls + popups
        if ip_float > 0 and FIP_CONSTANT is not None:
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
    metadata['sieraConstant'] = round(siera_constant, 4)

    # Second pass: apply SIERA constant and clean up
    for row in pitcher_leaderboard:
        if row.get('_siera_raw') is not None:
            row['siera'] = round(row['_siera_raw'] + siera_constant, 2)
        else:
            row['siera'] = None
        row.pop('_siera_raw', None)
        row.pop('_box', None)

    # Compute ERA league average (total_outs and total_er computed above)
    if total_outs > 0:
        total_ip = total_outs / 3.0
        metadata['pitcherLeagueAverages']['era'] = round(total_er * 9 / total_ip, 2)

    # HR/9 league average — weighted by IP (MLB only)
    hr9_pairs = [(r['hr9'], ip_str_to_float(r.get('ip'))) for r in pitcher_leaderboard
                 if r.get('hr9') is not None and r.get('ip') is not None and ip_str_to_float(r['ip']) > 0 and not r.get('_isROC')]
    if hr9_pairs:
        total_w = sum(w for _, w in hr9_pairs)
        metadata['pitcherLeagueAverages']['hr9'] = round(sum(v * w for v, w in hr9_pairs) / total_w, 2) if total_w > 0 else None

    # FIP, xFIP, SIERA league averages — weighted by IP (MLB only)
    for stat in ['fip', 'xFIP', 'siera']:
        pairs = [(r[stat], ip_str_to_float(r.get('ip'))) for r in pitcher_leaderboard
                 if r.get(stat) is not None and r.get('ip') is not None and ip_str_to_float(r['ip']) > 0 and not r.get('_isROC')]
        if pairs:
            total_w = sum(w for _, w in pairs)
            metadata['pitcherLeagueAverages'][stat] = round(sum(v * w for v, w in pairs) / total_w, 2) if total_w > 0 else None

    # ==========================================================
    # CONSOLIDATED PERCENTILE COMPUTATION
    # All stats are now computed, all boxscore merges done, all derived stats (FIP, wRC+, etc.) set.
    # Compute all percentiles in a single pass, then apply all inversions.
    # ==========================================================
    print("\n--- Computing percentiles (single pass) ---")

    # 1. Pitch-type percentiles (grouped by pitch type)
    pt_groups = defaultdict(list)
    for row in pitch_leaderboard:
        pt_groups[row['pitchType']].append(row)
    for metric in PITCH_PCTL_KEYS:
        for pt, pt_rows in pt_groups.items():
            compute_percentile_ranks_with_aaa(pt_rows, metric, min_count=0)

    # 2. Pitcher percentiles (all stats including boxscore-derived)
    PITCHER_ALL_PCTL = (STAT_KEYS + PITCHER_METRIC_PCTL_KEYS + PITCHER_BB_KEYS
                        + EXPECTED_KEYS + ['fbVelo', 'runValue', 'rv100', 'xRunValue', 'xRv100', 'era', 'hr9', 'fip', 'xFIP', 'siera'])
    for stat in PITCHER_ALL_PCTL:
        compute_percentile_ranks_with_aaa(pitcher_leaderboard, stat, min_count=0)

    # 3. Hitter percentiles (all stats including boxscore-derived)
    for stat in HITTER_STAT_KEYS + EXPECTED_KEYS:
        compute_percentile_ranks_with_aaa(hitter_leaderboard, stat)

    # 4. Hitter pitch-type percentiles (grouped by pitch type)
    hpt_groups = defaultdict(list)
    for row in hitter_pitch_leaderboard:
        hpt_groups[row['pitchType']].append(row)
    for pt, pt_rows in hpt_groups.items():
        for stat in HITTER_PITCH_PCTL_KEYS:
            compute_percentile_ranks_with_aaa(pt_rows, stat)

    # ==========================================================
    # CONSOLIDATED INVERSIONS
    # ==========================================================

    # Pitch inversions: VAA/nVAA for non-fastball, expected stats for all
    VAA_NO_INVERT_TYPES = {'FF', 'FC'}
    for pt, pt_rows in pt_groups.items():
        if pt not in VAA_NO_INVERT_TYPES:
            for row in pt_rows:
                if row.get('vaa_pctl') is not None:
                    row['vaa_pctl'] = 100 - row['vaa_pctl']
                if row.get('nVAA_pctl') is not None:
                    row['nVAA_pctl'] = 100 - row['nVAA_pctl']
    for row in pitch_leaderboard:
        for stat in ('wOBA', 'xBA', 'xSLG', 'xwOBA', 'xwOBAcon', 'xwOBAsp'):
            pctl_key = stat + '_pctl'
            if row.get(pctl_key) is not None:
                row[pctl_key] = 100 - row[pctl_key]

    # Pitcher inversions
    PITCHER_ALL_INVERT = PITCHER_INVERT_PCTL | PITCHER_BB_INVERT | EXPECTED_PITCHER_INVERT | {'era', 'hr9', 'fip', 'xFIP', 'siera'}
    for row in pitcher_leaderboard:
        for stat in PITCHER_ALL_INVERT:
            pctl_key = stat + '_pctl'
            if row.get(pctl_key) is not None:
                row[pctl_key] = 100 - row[pctl_key]

    # Hitter inversions
    for row in hitter_leaderboard:
        for stat in HITTER_INVERT_PCTL:
            pctl_key = stat + '_pctl'
            if row.get(pctl_key) is not None:
                row[pctl_key] = 100 - row[pctl_key]

    # Hitter pitch-type inversions
    for row in hitter_pitch_leaderboard:
        for stat in HITTER_PITCH_INVERT_PCTL:
            pctl_key = stat + '_pctl'
            if row.get(pctl_key) is not None:
                row[pctl_key] = 100 - row[pctl_key]

    print("  Percentiles computed and inversions applied.")

    # Final rounding step for runValue/rv100/xRunValue/xRv100 — applied after
    # percentiles so percentile ranks use exact values, but output uses display precision.
    for row in pitch_leaderboard:
        if row.get('runValue') is not None:
            row['runValue'] = round(row['runValue'], 1)
        if row.get('rv100') is not None:
            row['rv100'] = round(row['rv100'], 2)
        if row.get('xRunValue') is not None:
            row['xRunValue'] = round(row['xRunValue'], 1)
        if row.get('xRv100') is not None:
            row['xRv100'] = round(row['xRv100'], 2)
    for row in pitcher_leaderboard:
        if row.get('runValue') is not None:
            row['runValue'] = round(row['runValue'], 1)
        if row.get('rv100') is not None:
            row['rv100'] = round(row['rv100'], 2)
        if row.get('xRunValue') is not None:
            row['xRunValue'] = round(row['xRunValue'], 1)
        if row.get('xRv100') is not None:
            row['xRv100'] = round(row['xRv100'], 2)
    for row in hitter_leaderboard:
        if row.get('runValue') is not None:
            row['runValue'] = round(row['runValue'], 1)
        if row.get('xRunValue') is not None:
            row['xRunValue'] = round(row['xRunValue'], 1)
    for row in hitter_pitch_leaderboard:
        if row.get('runValue') is not None:
            row['runValue'] = round(row['runValue'], 1)
        if row.get('rv100') is not None:
            row['rv100'] = round(row['rv100'], 2)
        if row.get('xRunValue') is not None:
            row['xRunValue'] = round(row['xRunValue'], 1)
        if row.get('xRv100') is not None:
            row['xRv100'] = round(row['xRv100'], 2)

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

    # Preserve Stuff+ scores from existing pitch leaderboard (injected by train_stuff_v10.py)
    pitch_json_path = os.path.join(DATA_DIR, f'pitch_leaderboard{suffix}.json')
    if os.path.exists(pitch_json_path):
        try:
            with open(pitch_json_path) as f:
                existing = json.load(f)
            stuff_map = {}
            for row in existing:
                if row.get('stuffScore') is not None:
                    key = (row.get('pitcher'), row.get('team'), row.get('pitchType'))
                    stuff_map[key] = {
                        'stuffScore': row['stuffScore'],
                        'stuffScore_pctl': row.get('stuffScore_pctl')
                    }
            if stuff_map:
                n_merged = 0
                for row in result['pitch_leaderboard']:
                    key = (row.get('pitcher'), row.get('team'), row.get('pitchType'))
                    if key in stuff_map:
                        row['stuffScore'] = stuff_map[key]['stuffScore']
                        if stuff_map[key]['stuffScore_pctl'] is not None:
                            row['stuffScore_pctl'] = stuff_map[key]['stuffScore_pctl']
                        n_merged += 1
                print(f"  Preserved Stuff+ scores: {n_merged}/{len(stuff_map)} rows merged")
        except (json.JSONDecodeError, KeyError):
            print("  Warning: could not read existing Stuff+ scores")

    with open(pitch_json_path, 'w') as f:
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


def write_embedded_js(rs_result):
    """Write data_embedded.js with window.RS_DATA."""
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
        print(f"\n  *** WARNING: Could not fetch Guts data ({e}) ***")
        print(f"  *** Using 2025 FALLBACK values — wOBA weights may be inaccurate! ***\n")
        WOBA_WEIGHTS = WOBA_WEIGHTS_FALLBACK.copy()
        FIP_CONSTANT = FIP_CONSTANT_FALLBACK
        # Fallback league-level constants (2025 season estimates)
        GUTS_EXTRA = {'wOBAScale': 1.25, 'lgWOBA': 0.317, 'lgRPA': 0.119}

    # Propagate wOBA weights to pipeline_compute module
    # WOBA_WEIGHTS passed explicitly to compute_expected_stats calls

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
    sa_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if sa_json:
        try:
            sa_info = json.loads(sa_json)
        except json.JSONDecodeError as e:
            print(f"FATAL: GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON: {e}")
            sys.exit(1)
        creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    else:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    gc = gspread.authorize(creds)

    # Read Regular Season data
    print("\n=== Reading Regular Season data ===")
    rs_pitches = read_pitches_from_sheet(gc, SPREADSHEET_IDS['AL'])
    rs_pitches += read_pitches_from_sheet(gc, SPREADSHEET_IDS['NL'], extra_tabs={'ROC', 'AAA'})
    print(f"  Read {len(rs_pitches)} RS pitches")

    # Shared MLB ID cache
    mlb_id_cache_path = os.path.join(DATA_DIR, 'mlb_id_cache.json')
    mlb_id_cache = load_mlb_id_cache(mlb_id_cache_path)

    # Process Regular Season
    print("\n" + "=" * 60)
    print("=== Processing Regular Season ===")
    print("=" * 60)
    rs_result = process_game_type(rs_pitches, 'RS', mlb_id_cache, mlb_id_cache_path)

    # Save shared MLB ID cache
    save_mlb_id_cache(mlb_id_cache, mlb_id_cache_path)

    # Write output files
    print("\n--- Writing output files ---")
    write_json_outputs(rs_result, '_rs')
    write_embedded_js(rs_result)

    print(f"\nOutput written to {DATA_DIR}/")
    print(f"  RS: {len(rs_result['pitcher_leaderboard'])} pitchers, "
          f"{len(rs_result['pitch_leaderboard'])} pitch rows, "
          f"{len(rs_result['hitter_leaderboard'])} hitters")

    # Final integrity checks
    warnings = []
    for r in rs_result['pitcher_leaderboard']:
        if r.get('era') is not None and r['era'] < 0:
            warnings.append(f"Negative ERA: {r.get('pitcher')} = {r['era']}")
    for r in rs_result['hitter_leaderboard']:
        w = r.get('wOBA')
        if w is not None and (w < 0 or w > 1.0):
            warnings.append(f"wOBA out of bounds: {r.get('hitter')} = {w}")
        a = r.get('avg')
        if a is not None and (a < 0 or a > 1.0):
            warnings.append(f"AVG out of bounds: {r.get('hitter')} = {a}")
    if warnings:
        print(f"\n*** DATA INTEGRITY WARNINGS ({len(warnings)}) ***")
        for w in warnings[:20]:
            print(f"  - {w}")
        if os.environ.get('CI'):
            print("FATAL: Data integrity checks failed in CI — aborting.")
            sys.exit(1)
    else:
        print("  Data integrity checks passed.")


if __name__ == '__main__':
    main()
