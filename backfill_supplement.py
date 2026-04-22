#!/usr/bin/env python3
"""
Backfill supplemental Statcast data into the Google Sheet.

Scans each team tab for rows that have a PitchID but are missing supplemental
columns (ArmAngle, BatSpeed, SwingLength, AttackAngle,
AttackDirection, SwingPathTilt). Downloads the Statcast Search CSV for the
relevant team/date ranges from Baseball Savant and fills in the empty cells.

Configuration: edit the variables below before running.
"""

import gspread
from google.oauth2.service_account import Credentials
import requests
import pandas as pd
from io import StringIO
import os
import time

# ── USER CONFIGURATION ──────────────────────────────────────────────────────
# Set date range (inclusive). Leave both as None to backfill all dates.
start_date = "2026-03-27"
end_date   = "2026-04-05"

# Set specific teams, or None for all teams.  e.g. ["BOS", "NYY"]
filter_teams = None
# ─────────────────────────────────────────────────────────────────────────────

SPREADSHEET_IDS = {
    'AL': '1hzAtZ_Wqi8ZuUHaGvgjJcQMU5jj5CzGXuBtjYmPOj9U',   # AL 2026
    'NL': '1DH3NI-3bSXW7dl98tdg5uFgJ4O6aWRvRB_XnVb340YE',   # NL 2026
}
SERVICE_ACCOUNT_FILE = os.path.join(os.path.dirname(__file__), 'service_account.json')

# Spreadsheet column name -> Statcast CSV column name
SUPPLEMENT_MAP = {
    'ArmAngle': 'arm_angle',
    'EffectiveVelo': 'effective_speed',
    'BatSpeed': 'bat_speed',
    'SwingLength': 'swing_length',
    'AttackAngle': 'attack_angle',
    'AttackDirection': 'attack_direction',
    'SwingPathTilt': 'swing_path_tilt',
    'RunExp': 'delta_pitcher_run_exp',
    'xBA': 'estimated_ba_using_speedangle',
    'xSLG': 'estimated_slg_using_speedangle',
    'xwOBA': 'estimated_woba_using_speedangle',
    'wOBAval': 'woba_value',
    'wOBAdom': 'woba_denom',
    'Barrel': 'launch_speed_angle',
    'Event': 'events',
    'Description': 'description',
    'ExitVelo': 'launch_speed',
    'LaunchAngle': 'launch_angle',
    'Distance': 'hit_distance_sc',
    'BBType': 'bb_type',
}

# Columns that store raw integer values from Statcast (no rounding needed)
INT_COLS = {'Barrel', 'Distance'}

# Columns that store free-form strings (no numeric coercion, custom translator).
STRING_COLS = {'Event', 'Description', 'BBType'}

# Columns where official Statcast data should always overwrite existing
# values AND fill blanks. Use this mode when the initial MLB Stats API
# download may have been missing the value (e.g., Statcast hadn't released
# bat speed yet at ingestion) and Statcast is the authoritative source.
ALWAYS_OVERWRITE_COLS = {'ArmAngle', 'Barrel', 'Description', 'ExitVelo',
                         'LaunchAngle', 'Distance', 'BBType'}

# Columns that only ever OVERWRITE existing values; they are never used to
# fill a blank cell. Intended for scoring-change corrections where the
# initial MLB Stats API download already populated the cell for every
# relevant pitch (Event is set on the final pitch of every PA).
OVERWRITE_ONLY_COLS = {'Event'}

# Statcast `events` code -> MLB Stats API event string (the format Wally's
# sheet already stores, produced by Pitcher2026.py via play.result.event).
# Only scoring-change-relevant codes are mapped. Statcast's generic
# `field_out` is intentionally OMITTED: MLB Stats API keeps Groundout /
# Flyout / Lineout / Pop Out as distinct events, and we have no way to
# disambiguate from Statcast alone. A missing mapping means "skip; do not
# overwrite the existing sheet value."
STATCAST_TO_MLB_EVENT = {
    'single': 'Single',
    'double': 'Double',
    'triple': 'Triple',
    'home_run': 'Home Run',
    'strikeout': 'Strikeout',
    'strikeout_double_play': 'Strikeout Double Play',
    'walk': 'Walk',
    'intent_walk': 'Intent Walk',
    'hit_by_pitch': 'Hit By Pitch',
    'sac_fly': 'Sac Fly',
    'sac_fly_double_play': 'Sac Fly Double Play',
    'sac_bunt': 'Sac Bunt',
    'sac_bunt_double_play': 'Sac Bunt Double Play',
    'catcher_interf': 'Catcher Interference',
    'field_error': 'Field Error',
    'fielders_choice': 'Fielders Choice',
    'fielders_choice_out': 'Fielders Choice Out',
    'grounded_into_double_play': 'Grounded Into DP',
    'double_play': 'Double Play',
    'triple_play': 'Triple Play',
    'force_out': 'Forceout',
}

# Statcast `description` code -> MLB Stats API simplified description (the
# format Pitcher2026.simplify_description produces). Only standard pitch
# outcomes are mapped; unknown codes are skipped rather than overwritten.
STATCAST_TO_MLB_DESCRIPTION = {
    'ball': 'Ball',
    'blocked_ball': 'Ball',
    'automatic_ball': 'Ball',
    'intent_ball': 'Intent Ball',
    'pitchout': 'Pitchout',
    'called_strike': 'Called Strike',
    'automatic_strike': 'Called Strike',
    'swinging_strike': 'Swinging Strike',
    'swinging_strike_blocked': 'Swinging Strike',
    'foul_tip': 'Swinging Strike',
    'foul': 'Foul',
    'hit_into_play': 'In Play',
    'hit_by_pitch': 'Hit By Pitch',
    'foul_bunt': 'Foul Bunt',
    'bunt_foul_tip': 'Bunt Foul Tip',
    'missed_bunt': 'Missed Bunt',
    'swinging_pitchout': 'Swinging Pitchout',
    'foul_pitchout': 'Foul Pitchout',
}

# Statcast `bb_type` code -> Wally's sheet BBType value. MLB Stats API
# returns the same four trajectory labels, so the mapping is an identity
# for the four Statcast values. Bunt variants (bunt_grounder, bunt_popup,
# bunt_line_drive, bunt) are not present in Statcast — the CSV only
# classifies bunts by their landed trajectory. The overwrite logic below
# preserves existing bunt-* values rather than flattening them.
STATCAST_TO_MLB_BBTYPE = {
    'ground_ball': 'ground_ball',
    'line_drive': 'line_drive',
    'fly_ball': 'fly_ball',
    'popup': 'popup',
}

# Per-column rounding (default is 1 decimal for anything not listed)
ROUND_DECIMALS = {
    'ArmAngle': 1,
    'EffectiveVelo': 1,
    'BatSpeed': 1,
    'SwingLength': 1,
    'AttackAngle': 1,
    'AttackDirection': 1,
    'SwingPathTilt': 1,
    'RunExp': 3,
    'xBA': 3,
    'xSLG': 3,
    'xwOBA': 3,
    'wOBAval': 3,
    'wOBAdom': 3,
    'ExitVelo': 1,
    'LaunchAngle': 1,
}

# Team abbreviation mapping: spreadsheet tab name -> Statcast Search abbreviation
STATCAST_TEAM_MAP = {
    'ATH': 'OAK',
    'KCR': 'KC',
    'SDP': 'SD',
    'SFG': 'SF',
    'TBR': 'TB',
}

MLB_TEAMS = {
    'ARI', 'ATH', 'ATL', 'BAL', 'BOS', 'CHC', 'CIN', 'CLE', 'COL', 'CWS',
    'DET', 'HOU', 'KCR', 'LAA', 'LAD', 'MIA', 'MIL', 'MIN', 'NYM', 'NYY',
    'PHI', 'PIT', 'SDP', 'SEA', 'SFG', 'STL', 'TBR', 'TEX', 'TOR', 'WSH',
    'ROC',
}


def date_in_range(date_str):
    """Check if a date string falls within the configured range (inclusive)."""
    if start_date is None and end_date is None:
        return True
    if start_date and date_str < start_date:
        return False
    if end_date and date_str > end_date:
        return False
    return True


def download_statcast(team_tab, date_min, date_max, session):
    """Download Statcast Search CSV for a team and date range.
    Returns a dict keyed by (game_pk, at_bat_number, pitch_number) -> row dict."""
    statcast_team = STATCAST_TEAM_MAP.get(team_tab, team_tab)
    print(f"    Downloading Statcast for {team_tab} ({statcast_team}) "
          f"{date_min} to {date_max}...")

    url = "https://baseballsavant.mlb.com/statcast_search/csv"
    params = {
        'all': 'true',
        'type': 'details',
        'game_date_gt': date_min,
        'game_date_lt': date_max,
        'team': statcast_team,
        'player_type': 'pitcher',
        'min_pitches': '0',
        'min_results': '0',
        'sort_col': 'pitches',
        'sort_order': 'desc',
    }

    try:
        response = session.get(url, params=params, timeout=120)
        if response.status_code != 200:
            print(f"    Statcast returned status {response.status_code}")
            return None

        csv_text = response.text
        if not csv_text or csv_text.strip() == '' or 'No Results' in csv_text[:100]:
            print(f"    No Statcast data available yet")
            return None

        df = pd.read_csv(StringIO(csv_text))
        if df.empty:
            print(f"    Empty DataFrame")
            return None

        # Verify merge keys exist
        for col in ['game_pk', 'at_bat_number', 'pitch_number']:
            if col not in df.columns:
                print(f"    Missing merge key: {col}")
                return None

        # Build lookup dict keyed by PitchID components
        lookup = {}
        statcast_cols = list(SUPPLEMENT_MAP.values())
        available = [c for c in statcast_cols if c in df.columns]

        for _, row in df.iterrows():
            key = (
                str(int(row['game_pk'])),
                str(int(row['at_bat_number'])),
                str(int(row['pitch_number'])),
            )
            data = {}
            for sheet_col, csv_col in SUPPLEMENT_MAP.items():
                if csv_col in df.columns:
                    val = row[csv_col]
                    if pd.notna(val):
                        # String columns: translate Statcast code to Wally's
                        # sheet format. Unmapped codes (generic `field_out`,
                        # unknown pitch descriptions, etc.) are skipped so the
                        # downstream overwrite leaves the existing sheet value
                        # alone rather than clobbering it with something lossy.
                        if sheet_col in STRING_COLS:
                            if sheet_col == 'Event':
                                mapped = STATCAST_TO_MLB_EVENT.get(str(val).strip())
                                if mapped:
                                    data[sheet_col] = mapped
                            elif sheet_col == 'Description':
                                mapped = STATCAST_TO_MLB_DESCRIPTION.get(str(val).strip())
                                if mapped:
                                    data[sheet_col] = mapped
                            elif sheet_col == 'BBType':
                                mapped = STATCAST_TO_MLB_BBTYPE.get(str(val).strip())
                                if mapped:
                                    data[sheet_col] = mapped
                            else:
                                data[sheet_col] = str(val)
                            continue
                        # Integer columns: store raw value (e.g., Barrel 1-6 scale)
                        if sheet_col in INT_COLS:
                            data[sheet_col] = str(int(float(val)))
                            continue
                        fval = float(val)
                        # Filter out sub-50 bat speed (check swings / artifacts)
                        if sheet_col == 'BatSpeed' and fval < 50:
                            continue
                        decimals = ROUND_DECIMALS.get(sheet_col, 1)
                        fval = round(fval, decimals)
                        data[sheet_col] = f"{fval:.{decimals}f}"
                    elif sheet_col in ALWAYS_OVERWRITE_COLS:
                        # For overwrite cols, store empty to clear estimates
                        # when official data says the value is blank/null
                        data[sheet_col] = ''
            # Build Runners from on_1b/on_2b/on_3b
            if all(c in df.columns for c in ['on_1b', 'on_2b', 'on_3b']):
                bases = []
                if pd.notna(row.get('on_1b')): bases.append('1')
                if pd.notna(row.get('on_2b')): bases.append('2')
                if pd.notna(row.get('on_3b')): bases.append('3')
                data['Runners'] = '+'.join(bases) if bases else '0'
            if data:
                lookup[key] = data

        print(f"    Got {len(lookup)} pitches with supplement data "
              f"(columns: {available})")
        return lookup

    except requests.exceptions.Timeout:
        print(f"    Timeout downloading Statcast data")
        return None
    except Exception as e:
        print(f"    Error: {e}")
        return None


def read_sheet_with_retry(ws, max_retries=3):
    for attempt in range(max_retries):
        try:
            return ws.get_all_values()
        except gspread.exceptions.APIError as e:
            if '429' in str(e) and attempt < max_retries - 1:
                wait = 30 * (attempt + 1)
                print(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                raise


def main():
    print(f"Date range: {start_date or '(all)'} to {end_date or '(all)'}")
    if filter_teams:
        print(f"Teams: {', '.join(sorted(filter_teams))}")

    scopes = ['https://www.googleapis.com/auth/spreadsheets']
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    gc = gspread.authorize(creds)

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
        'Accept': 'text/csv',
    })

    total_filled = 0

    for sheet_label, sheet_id in SPREADSHEET_IDS.items():
        sh = gc.open_by_key(sheet_id)
        print(f"\n{'='*60}")
        print(f"[{sheet_label}] {sh.title}")
        print(f"{'='*60}")

        for i, ws in enumerate(sh.worksheets()):
            tab_name = ws.title.upper()

            # Skip WBC and non-MLB tabs
            if tab_name not in MLB_TEAMS:
                continue
            if filter_teams and tab_name not in filter_teams:
                continue

            print(f"\n[{ws.title}]")
            if i > 0:
                time.sleep(1.5)

            rows = read_sheet_with_retry(ws)
            if not rows or len(rows) < 2:
                print(f"  Empty sheet")
                continue

            header = rows[0]
            col_idx = {name: j for j, name in enumerate(header) if name}

            # Verify required columns exist
            pitch_id_col = col_idx.get('PitchID')
            if pitch_id_col is None:
                print(f"  No PitchID column — skipping")
                continue

            # Find supplement column indices (SUPPLEMENT_MAP + Runners)
            supp_col_idx = {}
            for sheet_col in SUPPLEMENT_MAP:
                if sheet_col in col_idx:
                    supp_col_idx[sheet_col] = col_idx[sheet_col]
            if 'Runners' in col_idx:
                supp_col_idx['Runners'] = col_idx['Runners']
            if not supp_col_idx:
                print(f"  No supplement columns found — skipping")
                continue

            # Find rows that need filling:
            # PitchID exists AND (at least one supplement column is empty
            # OR has an always-overwrite column that might contain an estimate)
            needs_fill = []  # (row_index_1based, pitch_id, cols_to_update)
            legacy_barrel_fixes = []  # Cells to convert "yes" -> "6"
            game_dates = set()
            date_col = col_idx.get('Game Date')

            for r_idx, row in enumerate(rows[1:], start=2):
                pid = row[pitch_id_col] if pitch_id_col < len(row) else ''
                if not pid or '_' not in pid:
                    continue

                # Convert legacy Barrel "yes" -> "6" on ALL rows (not date-filtered)
                if 'Barrel' in supp_col_idx:
                    barrel_val = row[supp_col_idx['Barrel']] if supp_col_idx['Barrel'] < len(row) else ''
                    if barrel_val.strip().lower() == 'yes':
                        legacy_barrel_fixes.append(gspread.Cell(
                            row=r_idx,
                            col=supp_col_idx['Barrel'] + 1,
                            value='6',
                        ))

                # Apply date range filter for supplement backfill
                if date_col is not None:
                    gd = row[date_col] if date_col < len(row) else ''
                    if not date_in_range(gd):
                        continue

                # Check which supplement columns need updating:
                # - Empty columns need filling (but NOT for OVERWRITE_ONLY_COLS)
                # - ALWAYS_OVERWRITE_COLS need updating even if they have a value
                #   (the existing value may be an estimate that official data should replace)
                # - OVERWRITE_ONLY_COLS update existing values only (for scoring
                #   corrections like hit↔error); never used to fill a blank cell.
                # Entries are (sheet_col, existing_val) so the write loop can
                # apply column-specific guards (e.g., preserve 'bunt' BBType).
                cols_to_update = []
                for sheet_col, c_idx in supp_col_idx.items():
                    val = row[c_idx] if c_idx < len(row) else ''
                    is_empty = (val == '' or val is None)
                    if is_empty and sheet_col in OVERWRITE_ONLY_COLS:
                        continue
                    if is_empty:
                        cols_to_update.append((sheet_col, ''))
                    elif sheet_col in ALWAYS_OVERWRITE_COLS or sheet_col in OVERWRITE_ONLY_COLS:
                        cols_to_update.append((sheet_col, val))

                if cols_to_update:
                    needs_fill.append((r_idx, pid, cols_to_update))
                    if date_col is not None:
                        gd = row[date_col] if date_col < len(row) else ''
                        if gd:
                            game_dates.add(gd)

            # Write legacy barrel "yes" -> "6" conversions regardless of other work
            if legacy_barrel_fixes:
                print(f"  Converting {len(legacy_barrel_fixes)} Barrel values "
                      f"from 'yes' to '6'...")
                ws.update_cells(legacy_barrel_fixes, value_input_option='RAW')
                total_filled += len(legacy_barrel_fixes)
                time.sleep(2)

            if not needs_fill:
                print(f"  All rows filled — nothing to do")
                continue

            print(f"  {len(needs_fill)} rows need supplement data "
                  f"(dates: {sorted(game_dates)})")

            # Download Statcast data for this team's date range
            if not game_dates:
                print(f"  No game dates found — skipping")
                continue

            date_min = min(game_dates)
            date_max = max(game_dates)

            time.sleep(3)  # Be polite to Baseball Savant
            lookup = download_statcast(ws.title, date_min, date_max, session)

            if lookup is None:
                print(f"  No Statcast data available — skipping")
                continue

            # Match and prepare cell updates
            cells_to_update = []
            filled_count = 0

            for r_idx, pid, cols_to_update in needs_fill:
                # Split PitchID: game_pk_atbat(zero-padded)_pitch(zero-padded)
                # Strip padding to match Statcast lookup keys (unpadded ints)
                parts = pid.split('_')
                if len(parts) != 3:
                    continue
                key = (parts[0], str(int(parts[1])), str(int(parts[2])))

                statcast_row = lookup.get(key, {})
                row_filled = False

                for sheet_col, existing_val in cols_to_update:
                    if sheet_col in statcast_row:
                        val = statcast_row[sheet_col]
                        # Don't write empty values for overwrite cols —
                        # that would erase data when official data isn't ready yet
                        if not val and (sheet_col in ALWAYS_OVERWRITE_COLS
                                        or sheet_col in OVERWRITE_ONLY_COLS):
                            continue
                        # BBType guard: preserve existing bunt-* values.
                        # Pitcher2026 classifies bunts as 'bunt' / 'bunt_grounder' /
                        # 'bunt_popup' / 'bunt_line_drive' using MLB Stats API
                        # trajectory; Statcast's bb_type flattens those into the
                        # landed trajectory (ground_ball, popup, etc.). Overwriting
                        # would lose the bunt signal.
                        if sheet_col == 'BBType' and existing_val and str(existing_val).startswith('bunt'):
                            continue
                        # Skip if overwrite value is identical to existing
                        if existing_val and str(val) == str(existing_val):
                            continue
                        cell = gspread.Cell(
                            row=r_idx,
                            col=supp_col_idx[sheet_col] + 1,  # 1-indexed
                            value=val,
                        )
                        cells_to_update.append(cell)
                        row_filled = True

                if row_filled:
                    filled_count += 1

            if cells_to_update:
                # Batch update (gspread handles chunking)
                print(f"  Writing {len(cells_to_update)} cells "
                      f"({filled_count} rows with new data)...")
                ws.update_cells(cells_to_update, value_input_option='RAW')
                total_filled += filled_count
                time.sleep(2)  # Rate limit buffer after write
            else:
                print(f"  No matching Statcast data for empty rows "
                      f"(data may not be processed yet)")

    print(f"\nDone. Filled supplement data for {total_filled} rows total.")


if __name__ == '__main__':
    main()
