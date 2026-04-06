#!/usr/bin/env python3
"""
Backfill PlateTime from the MLB Live Feed API into Google Sheets.

PlateTime (pitchData.plateTime) is not available in the Statcast Search CSV,
so it must be pulled from the live feed for each game. This script:

1. Reads each team tab to find rows with PitchID but missing PlateTime.
2. Groups needed rows by game_pk.
3. Fetches the live feed for each game.
4. Matches pitches by (game_pk, at_bat_number, pitch_number).
5. Writes PlateTime values back to the sheet.

Configuration: edit start_date / end_date / filter_teams below.
"""

import gspread
from google.oauth2.service_account import Credentials
import requests
import os
import time

# ── USER CONFIGURATION ──────────────────────────────────────────────────────
start_date = None       # e.g. "2026-03-27" or None for all
end_date   = None       # e.g. "2026-04-06" or None for all
filter_teams = None     # e.g. ["HOU", "NYY"] or None for all
# ─────────────────────────────────────────────────────────────────────────────

SERVICE_ACCOUNT_FILE = os.path.join(os.path.dirname(__file__), 'service_account.json')

SPREADSHEET_IDS = {
    'AL': '1hzAtZ_Wqi8ZuUHaGvgjJcQMU5jj5CzGXuBtjYmPOj9U',
    'NL': '1DH3NI-3bSXW7dl98tdg5uFgJ4O6aWRvRB_XnVb340YE',
}

MLB_TEAMS = {
    'ARI', 'ATH', 'ATL', 'BAL', 'BOS', 'CHC', 'CIN', 'CLE', 'COL', 'CWS',
    'DET', 'HOU', 'KCR', 'LAA', 'LAD', 'MIA', 'MIL', 'MIN', 'NYM', 'NYY',
    'PHI', 'PIT', 'SDP', 'SEA', 'SFG', 'STL', 'TBR', 'TEX', 'TOR', 'WSH',
    'ROC',
}


def date_in_range(date_str):
    if start_date is None and end_date is None:
        return True
    if start_date and date_str < start_date:
        return False
    if end_date and date_str > end_date:
        return False
    return True


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


def fetch_platetime_from_game(game_pk, session):
    """Fetch the live feed for a game and return a dict of
    (game_pk, at_bat_number, pitch_number) -> plate_time."""
    url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
    try:
        r = session.get(url, timeout=30)
        if r.status_code != 200:
            print(f"      Game {game_pk}: HTTP {r.status_code}")
            return {}
        data = r.json()
    except Exception as e:
        print(f"      Game {game_pk}: error {e}")
        return {}

    lookup = {}
    all_plays = data.get('liveData', {}).get('plays', {}).get('allPlays', [])

    for play in all_plays:
        at_bat_number = play.get('atBatIndex', 0) + 1  # 1-indexed to match Statcast

        for event in play.get('playEvents', []):
            if not event.get('isPitch', False):
                continue

            pitch_number = event.get('pitchNumber')
            plate_time = event.get('pitchData', {}).get('plateTime')

            if pitch_number is not None and plate_time is not None:
                key = (str(game_pk), str(at_bat_number), str(pitch_number))
                lookup[key] = round(plate_time, 3)

    return lookup


def main():
    print(f"Backfilling PlateTime from MLB Live Feed")
    print(f"Date range: {start_date or '(all)'} to {end_date or '(all)'}")
    if filter_teams:
        print(f"Teams: {', '.join(sorted(filter_teams))}")

    scopes = ['https://www.googleapis.com/auth/spreadsheets']
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    gc = gspread.authorize(creds)

    session = requests.Session()

    total_filled = 0

    for sheet_label, sheet_id in SPREADSHEET_IDS.items():
        sh = gc.open_by_key(sheet_id)
        print(f"\n{'='*60}")
        print(f"[{sheet_label}] {sh.title}")
        print(f"{'='*60}")

        for i, ws in enumerate(sh.worksheets()):
            tab_name = ws.title.upper()

            if tab_name not in MLB_TEAMS:
                continue
            if filter_teams and tab_name not in filter_teams:
                continue

            print(f"\n  [{tab_name}]")
            if i > 0:
                time.sleep(1.5)

            rows = read_sheet_with_retry(ws)
            if not rows or len(rows) < 2:
                print(f"    Empty sheet")
                continue

            header = rows[0]
            col_idx = {name: j for j, name in enumerate(header) if name}

            pid_col = col_idx.get('PitchID')
            pt_col = col_idx.get('PlateTime')
            date_col = col_idx.get('Game Date')

            if pid_col is None:
                print(f"    No PitchID column — skipping")
                continue
            if pt_col is None:
                print(f"    No PlateTime column — skipping")
                continue

            # Find rows that need PlateTime
            needs_fill = []  # (row_1based, pitch_id)
            game_pks = set()

            for r_idx, row in enumerate(rows[1:], start=2):
                pid = row[pid_col] if pid_col < len(row) else ''
                if not pid or '_' not in pid:
                    continue

                # Date filter
                if date_col is not None:
                    gd = row[date_col] if date_col < len(row) else ''
                    if not date_in_range(gd):
                        continue

                # Check if PlateTime is empty
                pt_val = row[pt_col] if pt_col < len(row) else ''
                if pt_val.strip():
                    continue  # already has a value

                needs_fill.append((r_idx, pid))
                # Extract game_pk from PitchID (format: gamepk_atbat_pitch)
                parts = pid.split('_')
                if len(parts) == 3:
                    game_pks.add(parts[0])

            if not needs_fill:
                print(f"    All rows have PlateTime — nothing to do")
                continue

            print(f"    {len(needs_fill)} rows need PlateTime "
                  f"across {len(game_pks)} games")

            # Fetch PlateTime from live feed for each game
            all_lookups = {}
            for gi, gp in enumerate(sorted(game_pks)):
                if gi > 0:
                    time.sleep(0.5)  # polite to MLB API
                lookup = fetch_platetime_from_game(gp, session)
                all_lookups.update(lookup)
                if (gi + 1) % 10 == 0:
                    print(f"      Fetched {gi + 1}/{len(game_pks)} games...")

            print(f"    Got PlateTime for {len(all_lookups)} pitches "
                  f"from {len(game_pks)} games")

            # Match and prepare cell updates
            cells_to_update = []

            for r_idx, pid in needs_fill:
                parts = pid.split('_')
                if len(parts) != 3:
                    continue
                # Strip zero-padding from at_bat and pitch numbers
                key = (parts[0], str(int(parts[1])), str(int(parts[2])))

                pt_value = all_lookups.get(key)
                if pt_value is not None:
                    cells_to_update.append(gspread.Cell(
                        row=r_idx,
                        col=pt_col + 1,  # 1-indexed
                        value=f"{pt_value:.3f}",
                    ))

            if cells_to_update:
                print(f"    Writing {len(cells_to_update)} PlateTime values...")
                # Batch write in chunks of 5000 (gspread limit)
                for chunk_start in range(0, len(cells_to_update), 5000):
                    chunk = cells_to_update[chunk_start:chunk_start + 5000]
                    ws.update_cells(chunk, value_input_option='RAW')
                    if chunk_start + 5000 < len(cells_to_update):
                        time.sleep(2)
                total_filled += len(cells_to_update)
                time.sleep(2)
            else:
                print(f"    No matching PlateTime data found")

    print(f"\nDone. Filled PlateTime for {total_filled} rows total.")


if __name__ == '__main__':
    main()
