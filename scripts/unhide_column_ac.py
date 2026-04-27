#!/usr/bin/env python3
"""Unhide column AC on every tab of AL 2026 and NL 2026 spreadsheets.

AC is the 29th column (0-indexed: 28). Unhiding an already-visible column
is a no-op on the Sheets side, so this is safe to re-run.

Usage: python3 scripts/unhide_column_ac.py
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Locate service account (tries env var, script's parent, then ~/Huronalytics)
SA_CANDIDATES = [
    os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE'),
    str(ROOT / 'service_account.json'),
    str(Path.home() / 'Huronalytics' / 'service_account.json'),
]
SA_PATH = next((p for p in SA_CANDIDATES if p and Path(p).exists()), None)
if not SA_PATH:
    raise FileNotFoundError(f"service_account.json not found in: {SA_CANDIDATES}")

import gspread
from google.oauth2.service_account import Credentials
from pipeline_fetch import SPREADSHEET_IDS

COL_AC_INDEX = 28  # zero-indexed; AC is the 29th column

def main():
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive',
    ]
    creds = Credentials.from_service_account_file(SA_PATH, scopes=scopes)
    gc = gspread.authorize(creds)

    total_tabs = 0
    for label, sheet_id in SPREADSHEET_IDS.items():
        sh = gc.open_by_key(sheet_id)
        tabs = sh.worksheets()
        print(f"{label}: {sh.title} ({len(tabs)} tabs)")

        requests = [
            {
                'updateDimensionProperties': {
                    'range': {
                        'sheetId': ws.id,
                        'dimension': 'COLUMNS',
                        'startIndex': COL_AC_INDEX,
                        'endIndex': COL_AC_INDEX + 1,
                    },
                    'properties': {'hiddenByUser': False},
                    'fields': 'hiddenByUser',
                }
            }
            for ws in tabs
        ]
        sh.batch_update({'requests': requests})
        tab_names = ', '.join(ws.title for ws in tabs)
        print(f"  unhid AC on: {tab_names}")
        total_tabs += len(tabs)

    print(f"\nDone. Column AC unhidden across {total_tabs} tabs.")


if __name__ == '__main__':
    main()
