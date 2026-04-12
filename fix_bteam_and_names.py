#!/usr/bin/env python3
"""
Two tasks:
1. Find batters with both an MLB team and a country in BTeam, update all country instances to MLB team.
2. Find potential name duplicates due to accents or Jr./Sr. suffixes and write a report.
"""

import gspread
from google.oauth2.service_account import Credentials
import os
import time
import unicodedata
import re
from collections import defaultdict

SPREADSHEET_ID = '1hNILKCGBuyQKV6KPWawgkS1cu72672TBALi8iNBbIFo'
SERVICE_ACCOUNT_FILE = os.path.join(os.path.dirname(__file__), 'service_account.json')

MLB_TEAMS = {
    'ARI', 'ATH', 'ATL', 'BAL', 'BOS', 'CHC', 'CIN', 'CLE', 'COL', 'CWS',
    'DET', 'HOU', 'KCR', 'LAA', 'LAD', 'MIA', 'MIL', 'MIN', 'NYM', 'NYY',
    'PHI', 'PIT', 'SDP', 'SEA', 'SFG', 'STL', 'TBR', 'TEX', 'TOR', 'WSH',
}


def strip_accents(s):
    """Remove accents from a string (e.g., Vázquez -> Vazquez)."""
    nfkd = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in nfkd if not unicodedata.category(c).startswith('M'))


def normalize_name(name):
    """Normalize a name for comparison: strip accents, remove Jr./Sr./II/III, lowercase."""
    name = strip_accents(name).lower().strip()
    # Remove common suffixes
    name = re.sub(r'\s+(jr\.?|sr\.?|ii|iii|iv)$', '', name)
    # Remove trailing periods/commas
    name = name.rstrip('.,')
    return name


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
    # Use read-write scope
    scopes = ['https://www.googleapis.com/auth/spreadsheets']
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)
    print(f"Spreadsheet: {sh.title} ({len(sh.worksheets())} sheets)")

    # ===== PASS 1: Read all data, build Batter -> MLB team mapping =====
    print("\n--- Pass 1: Reading all sheets to build MLB team mapping ---")
    # batter_teams[name] = set of BTeam values seen
    batter_teams = defaultdict(set)
    # All (batter_name, bteam) pairs for name duplicate check
    all_batter_entries = []

    for i, ws in enumerate(sh.worksheets()):
        print(f"  Reading {ws.title}...")
        if i > 0:
            time.sleep(1.5)
        rows = read_sheet_with_retry(ws)
        if not rows:
            continue
        header = rows[0]
        col_idx = {name: j for j, name in enumerate(header) if name}

        batter_col = col_idx.get('Batter')
        bteam_col = col_idx.get('BTeam')
        if batter_col is None or bteam_col is None:
            print(f"    Skipping {ws.title} (no Batter/BTeam columns)")
            continue

        for row in rows[1:]:
            batter = row[batter_col] if batter_col < len(row) else ''
            bteam = row[bteam_col] if bteam_col < len(row) else ''
            if batter and bteam:
                batter_teams[batter].add(bteam)
                all_batter_entries.append((batter, bteam))

    # Build mapping: batters who have both MLB and country teams
    batter_mlb_map = {}  # batter_name -> MLB team
    batters_with_country = []
    for batter, teams in batter_teams.items():
        mlb = [t for t in teams if t in MLB_TEAMS]
        non_mlb = [t for t in teams if t not in MLB_TEAMS]
        if mlb and non_mlb:
            # Has both MLB and country
            mlb_team = mlb[0]  # Should only have one MLB team
            batter_mlb_map[batter] = mlb_team
            batters_with_country.append((batter, mlb_team, non_mlb))

    print(f"\nFound {len(batters_with_country)} batters with both MLB and country teams:")
    for batter, mlb_team, countries in sorted(batters_with_country):
        print(f"  {batter}: {mlb_team} + {', '.join(countries)}")

    # ===== PASS 2: Update country BTeams to MLB teams =====
    print(f"\n--- Pass 2: Updating BTeam values in spreadsheet ---")
    total_updates = 0

    for i, ws in enumerate(sh.worksheets()):
        if i > 0:
            time.sleep(1.5)
        rows = read_sheet_with_retry(ws)
        if not rows:
            continue
        header = rows[0]
        col_idx = {name: j for j, name in enumerate(header) if name}

        batter_col = col_idx.get('Batter')
        bteam_col = col_idx.get('BTeam')
        if batter_col is None or bteam_col is None:
            continue

        # Collect cells that need updating (row, col, new_value)
        # gspread uses 1-indexed rows and columns
        updates = []
        for r_idx, row in enumerate(rows[1:], start=2):  # start=2 because row 1 is header
            batter = row[batter_col] if batter_col < len(row) else ''
            bteam = row[bteam_col] if bteam_col < len(row) else ''
            if batter in batter_mlb_map and bteam not in MLB_TEAMS and bteam:
                updates.append({
                    'row': r_idx,
                    'col': bteam_col + 1,  # gspread is 1-indexed
                    'old': bteam,
                    'new': batter_mlb_map[batter],
                    'batter': batter,
                })

        if updates:
            print(f"  {ws.title}: {len(updates)} cells to update")
            # Batch update using cell list
            cells_to_update = []
            for u in updates:
                cell = gspread.Cell(row=u['row'], col=u['col'], value=u['new'])
                cells_to_update.append(cell)

            # gspread batch update (max ~50k cells per call)
            ws.update_cells(cells_to_update, value_input_option='RAW')
            total_updates += len(updates)
            time.sleep(2)  # Rate limit buffer after write
        else:
            print(f"  {ws.title}: no updates needed")

    print(f"\nTotal cells updated: {total_updates}")

    # ===== TASK 2: Check for name duplicates (accents, Jr./Sr.) =====
    print(f"\n--- Task 2: Checking for potential name duplicates ---")

    # Group batters by normalized name
    # Key: normalized name -> list of (original_name, set of MLB teams)
    name_groups = defaultdict(lambda: defaultdict(set))
    for batter, teams in batter_teams.items():
        mlb = [t for t in teams if t in MLB_TEAMS]
        norm = normalize_name(batter)
        for t in mlb:
            name_groups[norm][batter].add(t)

    # Find groups where multiple original names map to the same normalized name
    duplicates = []
    for norm_name, originals in name_groups.items():
        if len(originals) < 2:
            continue
        # Check if the names are actually different (not just same player on different teams)
        original_names = list(originals.keys())
        # Only flag if the original names differ (accent/suffix differences)
        unique_names = set(original_names)
        if len(unique_names) > 1:
            entries = []
            for name, teams in originals.items():
                entries.append((name, sorted(teams)))
            duplicates.append((norm_name, entries))

    # Write report
    report_path = os.path.join(os.path.dirname(__file__), 'name_duplicates_report.txt')
    with open(report_path, 'w') as f:
        f.write("Potential Batter Name Duplicates Report\n")
        f.write("=" * 50 + "\n")
        f.write("These batters have similar names that may be the same person.\n")
        f.write("Differences may be due to accents, Jr./Sr. suffixes, etc.\n")
        f.write("Players with the exact same name on different MLB teams are excluded.\n\n")

        if not duplicates:
            f.write("No potential duplicates found.\n")
            print("  No potential duplicates found.")
        else:
            f.write(f"Found {len(duplicates)} potential duplicate group(s):\n\n")
            print(f"  Found {len(duplicates)} potential duplicate group(s):")
            for norm_name, entries in sorted(duplicates):
                f.write(f"Normalized: \"{norm_name}\"\n")
                for name, teams in entries:
                    f.write(f"  \"{name}\" — Teams: {', '.join(teams)}\n")
                f.write("\n")
                # Also print to console
                print(f"    \"{norm_name}\":")
                for name, teams in entries:
                    print(f"      \"{name}\" — {', '.join(teams)}")

    print(f"\nReport written to: {report_path}")


if __name__ == '__main__':
    main()
