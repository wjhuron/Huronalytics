"""Append Pitcher2026 download output directly into the AL 2026 / NL 2026
Google Sheets workbooks.

Usage:
    from sheets_append import push_csv_to_sheets
    push_csv_to_sheets(combined_df)

The dataframe is grouped by `PTeam`, and each group is appended to the tab
matching that team in the appropriate workbook (NL 2026 or AL 2026). For ROC
downloads the data already has PTeam normalized to {'ROC', 'AAA'} by
Pitcher2026.py, so it splits cleanly across the ROC and AAA tabs in NL 2026.

Behavior:
- The dataframe's header row is NOT pushed. The destination tabs already have
  headers in row 1; new rows go into the first blank line below the existing
  data.
- Each appended block is formatted Helvetica Neue, size 8, centered, to match
  the existing data in the sheet.

One-time auth setup:
    1. In Google Cloud Console, create (or pick) a project.
    2. Enable the Google Sheets API for that project.
    3. Create OAuth 2.0 Client ID credentials of type "Desktop app".
    4. Download the JSON, save it to ~/.config/gspread/credentials.json.
    5. First run will open a browser for consent. The token is cached at
       ~/.config/gspread/authorized_user.json — subsequent runs are silent.
"""

import os
import sys
import math

import pandas as pd

# Workbook IDs (hardcoded for 2026)
SHEETS_NL = '1DH3NI-3bSXW7dl98tdg5uFgJ4O6aWRvRB_XnVb340YE'
SHEETS_AL = '1hzAtZ_Wqi8ZuUHaGvgjJcQMU5jj5CzGXuBtjYmPOj9U'

NL_TEAMS = {'ARI', 'ATL', 'CHC', 'CIN', 'COL', 'LAD', 'MIA', 'MIL',
            'NYM', 'PHI', 'PIT', 'SDP', 'SFG', 'STL', 'WSH'}
AL_TEAMS = {'BAL', 'BOS', 'CWS', 'CLE', 'DET', 'HOU', 'KCR', 'LAA',
            'MIN', 'NYY', 'ATH', 'SEA', 'TBR', 'TEX', 'TOR'}

# ROC + AAA both live in NL 2026
ROC_AAA_TEAMS = {'ROC', 'AAA'}


def _workbook_id_for_team(team):
    if team in NL_TEAMS or team in ROC_AAA_TEAMS:
        return SHEETS_NL
    if team in AL_TEAMS:
        return SHEETS_AL
    return None


def _get_client():
    """Return an authorized gspread client. First call will open a browser
    if no cached token exists."""
    try:
        import gspread
    except ImportError:
        raise RuntimeError(
            "gspread is required for sheets push. Install with: pip install gspread"
        )

    cred_path = os.path.expanduser('~/.config/gspread/credentials.json')
    if not os.path.exists(cred_path):
        raise RuntimeError(
            f"OAuth client config not found at {cred_path}.\n"
            "One-time setup:\n"
            "  1. Google Cloud Console → enable Google Sheets API for any project.\n"
            "  2. Create OAuth 2.0 Client ID, type 'Desktop app'.\n"
            "  3. Download JSON, save as ~/.config/gspread/credentials.json"
        )
    return gspread.oauth()  # uses ~/.config/gspread/{credentials,authorized_user}.json


def _col_letter(n):
    """1-indexed column number to A1 letter (1 → 'A', 27 → 'AA', etc.)."""
    s = ''
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _df_to_rows(df):
    """Convert a dataframe to a list-of-lists suitable for gspread. NaN /
    NaT / pd.NA become empty strings (Sheets shows blank rather than '#N/A')."""
    out = []
    for row in df.itertuples(index=False, name=None):
        cleaned = []
        for v in row:
            if v is None:
                cleaned.append('')
            elif isinstance(v, float) and math.isnan(v):
                cleaned.append('')
            elif pd.isna(v):
                cleaned.append('')
            else:
                cleaned.append(v)
        out.append(cleaned)
    return out


def push_team_data(df, team, gc=None, verbose=True):
    """Append `df` (already filtered to one team's rows) to the sheet tab
    named `team` in whichever workbook owns that team.

    Returns (next_row, n_appended) on success, or None if skipped.
    """
    wb_id = _workbook_id_for_team(team)
    if wb_id is None:
        if verbose:
            print(f"  [sheets] team {team!r} not in NL/AL/ROC mapping; skipping")
        return None

    if gc is None:
        gc = _get_client()
    wb = gc.open_by_key(wb_id)

    try:
        ws = wb.worksheet(team)
    except Exception as e:
        if verbose:
            print(f"  [sheets] tab {team!r} not found in workbook ({e}); skipping")
        return None

    rows = _df_to_rows(df)
    if not rows:
        return None

    # First blank row in column A. Header row 1 stays untouched. Using
    # col_values('A') is more reliable than get_all_values() because trailing
    # blank rows are correctly trimmed.
    col_a = ws.col_values(1)
    next_row = len(col_a) + 1
    if next_row < 2:
        next_row = 2  # never overwrite a (possibly missing) header row

    end_row = next_row + len(rows) - 1
    end_col = _col_letter(len(df.columns))
    range_name = f"A{next_row}:{end_col}{end_row}"

    ws.update(range_name, rows, value_input_option='USER_ENTERED')
    ws.format(range_name, {
        'textFormat': {'fontFamily': 'Helvetica Neue', 'fontSize': 8},
        'horizontalAlignment': 'CENTER',
    })

    if verbose:
        wb_label = 'NL 2026' if wb_id == SHEETS_NL else 'AL 2026'
        print(f"  [sheets] {team}: appended {len(rows)} rows to {wb_label} → "
              f"{team} (rows {next_row}-{end_row})")
    return next_row, len(rows)


def push_csv_to_sheets(df, verbose=True):
    """Group `df` by PTeam and push each group to its sheet tab.

    Most downloads have a single PTeam — one tab gets one update. ROC
    downloads (after Pitcher2026.py normalization) have PTeam ∈ {ROC, AAA},
    so they split cleanly across the ROC and AAA tabs of NL 2026.
    """
    if 'PTeam' not in df.columns:
        if verbose:
            print("  [sheets] dataframe has no PTeam column; skipping push")
        return

    # Drop rows with no PTeam — they can't be routed
    valid = df.dropna(subset=['PTeam'])
    valid = valid[valid['PTeam'].astype(str).str.strip() != '']
    if len(valid) == 0:
        if verbose:
            print("  [sheets] no rows with a PTeam value; skipping push")
        return

    gc = _get_client()  # auth once for all groups
    for team, group in valid.groupby('PTeam', sort=False):
        push_team_data(group, str(team), gc=gc, verbose=verbose)
