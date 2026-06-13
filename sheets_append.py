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

One-time auth setup (service account — preferred, headless, never expires):
    1. Google Cloud Console → pick/create a project.
    2. Enable the Google Sheets API for that project.
    3. IAM & Admin → Service Accounts → Create service account.
    4. On the new account: Keys → Add key → JSON → download.
    5. Save the JSON to ~/.config/gspread/service_account.json.
    6. Open the downloaded JSON, copy the "client_email" value, and share
       BOTH the "AL 2026" and "NL 2026" workbooks with that email as
       Editor (the same way you'd share with a person).

    The service account has no token expiry and needs no browser, so the
    pipeline runs unattended forever.

Legacy fallback (interactive OAuth — used only if no service_account.json):
    Desktop OAuth client at ~/.config/gspread/credentials.json, browser
    consent cached at ~/.config/gspread/authorized_user.json. NOTE: if the
    OAuth consent screen is in "Testing" status, Google revokes the refresh
    token after 7 days ("invalid_grant: Token has been expired or revoked"),
    which is exactly why the service-account path above is preferred.
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
    """Return an authorized gspread client.

    Prefers a service account (headless, no token expiry) at gspread's
    conventional path ~/.config/gspread/service_account.json. Falls back to
    interactive OAuth only if no service-account key is present, so an
    in-progress migration never hard-breaks the pipeline.
    """
    try:
        import gspread
    except ImportError:
        raise RuntimeError(
            "gspread is required for sheets push. Install with: pip install gspread"
        )

    sa_path = os.path.expanduser('~/.config/gspread/service_account.json')
    if os.path.exists(sa_path):
        # Service account: no browser, no 7-day refresh-token expiry. The
        # AL 2026 / NL 2026 workbooks must each be shared (Editor) with the
        # account's client_email or gspread raises APIError 403 / 404.
        return gspread.service_account(filename=sa_path)

    # Fallback: interactive OAuth (Desktop client). Breaks every 7 days if
    # the OAuth consent screen is in "Testing" status — see module docstring.
    cred_path = os.path.expanduser('~/.config/gspread/credentials.json')
    if not os.path.exists(cred_path):
        raise RuntimeError(
            "No Google Sheets credentials found.\n"
            "Preferred (headless, never expires) — save a service-account "
            f"key to {sa_path}:\n"
            "  1. Google Cloud Console → enable the Google Sheets API.\n"
            "  2. IAM & Admin → Service Accounts → Create; add a JSON key.\n"
            "  3. Save the JSON to the path above.\n"
            "  4. Share the AL 2026 and NL 2026 Sheets (Editor) with the\n"
            "     service account's client_email.\n"
            f"Or legacy OAuth — save a Desktop OAuth client to {cred_path}."
        )
    return gspread.oauth()  # uses ~/.config/gspread/{credentials,authorized_user}.json


def _col_letter(n):
    """1-indexed column number to A1 letter (1 → 'A', 27 → 'AA', etc.)."""
    s = ''
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _paste_number_formats_from_row(ws, src_row_1idx, dest_start_1idx, dest_end_1idx, n_cols):
    """Paste the cell formatting (incl. number format) from a single existing
    row onto a destination range. Used right after appending new data so the
    new rows inherit the column-specific number formats already set up on the
    sheet — e.g. Velocity (`0.0`), Extension (`0.00`), PlateX (`0.000`),
    RTilt/OTilt (`h:mm`). Without this, appended cells default to "Automatic"
    and round values like 82.0 render as 82.

    Safe to call only when there's at least one existing data row to copy from
    (i.e. dest_start_1idx > src_row_1idx). The destination range can be any
    number of rows — the Sheets API repeats the source format to fill it.
    """
    # 0-indexed conversion. endRowIndex is exclusive.
    src_row_0 = src_row_1idx - 1
    request = {
        'copyPaste': {
            'source': {
                'sheetId': ws.id,
                'startRowIndex': src_row_0,
                'endRowIndex': src_row_0 + 1,
                'startColumnIndex': 0,
                'endColumnIndex': n_cols,
            },
            'destination': {
                'sheetId': ws.id,
                'startRowIndex': dest_start_1idx - 1,
                'endRowIndex': dest_end_1idx,
                'startColumnIndex': 0,
                'endColumnIndex': n_cols,
            },
            'pasteType': 'PASTE_FORMAT',
            'pasteOrientation': 'NORMAL',
        }
    }
    ws.spreadsheet.batch_update({'requests': [request]})


# Columns whose string values would otherwise be misparsed by USER_ENTERED.
# Baseball counts like "1-0" get parsed as the date "January 0" and stored
# as date serials (46022, 46023, …) — the cell then displays as "46023"
# instead of "1-0". Prefixing each value with a leading apostrophe forces
# Sheets to store the cell as text; the apostrophe is hidden in the rendered
# display and downstream readers still see "1-0".
TEXT_FORCE_COLUMNS = {'Count'}


# Columns where we explicitly enforce a number format on every appended block,
# independent of what row 2 happens to look like. The format-paste-from-row-2
# step inherits most column formats correctly, but some tabs have row 2 cells
# with the format missing or wrong — e.g. AAA's row 2 RTilt was empty, which
# caused the whole RTilt column to render as raw decimals (0.0986) instead of
# clock times (2:22). Enforcing these by name makes the push robust to any
# tab's row 2 state.
EXPLICIT_NUMBER_FORMATS = {
    'RTilt': {'type': 'TIME',   'pattern': 'h:mm'},
    'OTilt': {'type': 'TIME',   'pattern': 'h:mm'},
}


def _force_text_for_columns(df, cols):
    """Prefix non-empty string values in `cols` with `'` so Sheets'
    USER_ENTERED parser treats them as text and skips number/date coercion.
    Returns a copy of `df`; never mutates the caller's dataframe.
    """
    cols_present = [c for c in cols if c in df.columns]
    if not cols_present:
        return df
    df = df.copy()
    for c in cols_present:
        df[c] = df[c].apply(lambda v: f"'{v}" if isinstance(v, str) and v else v)
    return df


def _df_to_rows(df):
    """Convert a dataframe to a list-of-lists suitable for gspread. NaN /
    NaT / pd.NA become empty strings (Sheets shows blank rather than '#N/A').
    numpy scalar types (int64/float64/bool_) are converted to Python natives
    so the result is JSON-serializable for gspread's API call."""
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
            elif hasattr(v, 'item'):
                # numpy scalar (int64, float64, bool_, etc.) → Python native
                cleaned.append(v.item())
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

    # Force text storage for columns whose values would be misparsed by
    # USER_ENTERED (e.g. Count "1-0" → date serial 46023).
    df = _force_text_for_columns(df, TEXT_FORCE_COLUMNS)

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

    # Grow the tab's grid if the new block would run past its last row.
    # Sheets tabs have a fixed row count (new tabs default to 1000), and
    # ws.update() with a range beyond that ceiling fails with "exceeds grid
    # limits" — the same wall that forces the manual "add 1000 rows" step.
    # Resize first, with a 1000-row buffer so back-to-back pushes don't have
    # to resize every single time.
    if end_row > ws.row_count:
        ws.add_rows(end_row - ws.row_count + 1000)

    ws.update(range_name, rows, value_input_option='USER_ENTERED')

    # Inherit per-column number formats from an existing data row so values
    # like Velocity 82.0 don't display as "82" (Automatic format strips
    # trailing zeros). Row 2 is the canonical source — it's the first data
    # row Wally set up with per-column formats. Only safe when there's at
    # least one existing data row above the new block.
    if next_row > 2:
        try:
            _paste_number_formats_from_row(
                ws, src_row_1idx=2,
                dest_start_1idx=next_row, dest_end_1idx=end_row,
                n_cols=len(df.columns),
            )
        except Exception as e:
            if verbose:
                print(f"  [sheets] number-format paste failed "
                      f"({type(e).__name__}: {e}); continuing")

    # Match the existing data rows in the sheet:
    #   font Helvetica Neue 8, center horiz, top vert, SOLID 1px borders all sides.
    #   Column A (Game Date) is additionally bold.
    _SOLID = {'style': 'SOLID', 'width': 1}
    base_fmt = {
        'textFormat': {'fontFamily': 'Helvetica Neue', 'fontSize': 8},
        'horizontalAlignment': 'CENTER',
        'verticalAlignment': 'TOP',
        'borders': {
            'top':    _SOLID,
            'bottom': _SOLID,
            'left':   _SOLID,
            'right':  _SOLID,
        },
    }
    ws.format(range_name, base_fmt)
    # Bold pass on column A (Game Date) — second call overrides textFormat
    # for that column while preserving the rest of base_fmt.
    col_a_range = f'A{next_row}:A{end_row}'
    ws.format(col_a_range, {
        **base_fmt,
        'textFormat': {**base_fmt['textFormat'], 'bold': True},
    })

    # Explicitly enforce number formats on columns we don't want to rely on
    # row 2 having set up correctly. Currently: RTilt + OTilt (TIME h:mm) —
    # AAA's row 2 had RTilt empty, which made the whole RTilt column render
    # as raw decimals after a push. This pass guarantees the right format
    # regardless of row 2's state on any tab.
    for col_name, fmt_spec in EXPLICIT_NUMBER_FORMATS.items():
        if col_name not in df.columns:
            continue
        col_idx_1 = df.columns.get_loc(col_name) + 1
        col_a1 = _col_letter(col_idx_1)
        rng = f'{col_a1}{next_row}:{col_a1}{end_row}'
        try:
            ws.format(rng, {'numberFormat': fmt_spec})
        except Exception as e:
            if verbose:
                print(f"  [sheets] failed to apply {fmt_spec} to {col_name} "
                      f"({type(e).__name__}: {e}); continuing")

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

    Teams with no NL/AL/ROC mapping (FCL / complex-league or international
    games) can't be routed to a workbook. They're collected and returned so
    the caller can fall back to a local CSV instead of silently dropping the
    data. Auth is deferred until a mappable team is found, so an all-unmapped
    push needs no Google credentials at all.

    Returns the list of unmapped (un-pushed) team names.
    """
    if 'PTeam' not in df.columns:
        if verbose:
            print("  [sheets] dataframe has no PTeam column; skipping push")
        return []

    # Drop rows with no PTeam — they can't be routed
    valid = df.dropna(subset=['PTeam'])
    valid = valid[valid['PTeam'].astype(str).str.strip() != '']
    if len(valid) == 0:
        if verbose:
            print("  [sheets] no rows with a PTeam value; skipping push")
        return []

    gc = None  # lazy: only authenticate once we hit a mappable team
    unmapped = []
    for team, group in valid.groupby('PTeam', sort=False):
        team = str(team)
        if _workbook_id_for_team(team) is None:
            if verbose:
                print(f"  [sheets] team {team!r} not in NL/AL/ROC mapping; "
                      f"skipping push (will write CSV)")
            unmapped.append(team)
            continue
        if gc is None:
            gc = _get_client()  # auth once, shared across the mappable groups
        push_team_data(group, team, gc=gc, verbose=verbose)
    return unmapped
