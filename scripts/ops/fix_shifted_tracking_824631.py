#!/usr/bin/env python3
"""fix_shifted_tracking_824631.py -- one-off repair, 2026-11-20 (approved by Wally).

PIT @ CHC 2026-09-11, Trent Thornton, 9th inning. At scrape time the feed carried a
one-pitch shift: the tracking of the Triolo pitch (95.0 mph, spin 2215) sat on the
Mangum pitch, and the Triolo pitch had none. MLB corrected the feed later: the Mangum
pitch is the 80.7 mph sweeper, the Triolo pitch has its own tracking. The 2026-09-29
review accepted only the raw IndVertBrk / HorzBrk for the Mangum row and recorded every
other corrected cell as rejected, which left sweeper movement (4.0 / -13.1) on a row
with fastball velocity, spin, release point and x movement.

This writes, for PitchIDs 824631_076_01 and 824631_077_01, exactly the cells the
ledger holds as rejected (the corrected feed values, parsed by the scraper), sets the
Mangum row's Pitch Type to ST, and removes those ledger entries so the backfill does
not refuse the same values again. PlateX / PlateZ, ArmAngle and the other Savant
columns already match the corrected feed and are not touched. The Triolo row keeps
its FF tag (the feed says SI; Wally's tag stands).

Rows are located by PitchID, never by a cached row number.

  python3 scripts/ops/fix_shifted_tracking_824631.py            # dry run
  python3 scripts/ops/fix_shifted_tracking_824631.py --apply
"""
import argparse
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import gspread

from scrapers.pitcher2026 import BaseballSavantFocusedDownloader
from scrapers.sheets_append import _workbook_id_for_team, apply_block_format

GAME_PK = 824631
PIDS = ('824631_076_01', '824631_077_01')
PITCH_TYPE = {'824631_076_01': 'ST'}
LEDGER = os.path.join(ROOT, 'data', 'backfill_decisions.json')
# the corrected feed must still say this, or the script stops
EXPECT = {'824631_076_01': {'Velocity': 80.7, 'IndVertBrk': 4.0, 'HorzBrk': -13.1},
          '824631_077_01': {'Velocity': 95.0, 'IndVertBrk': 11.9, 'HorzBrk': 5.2}}


class _NoSidecar(BaseballSavantFocusedDownloader):
    def _record_game_weather(self, game_pk, info):      # a repair must not rewrite the weather record
        pass


def cell(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ''
    return v if isinstance(v, str) else (int(v) if isinstance(v, float) and v.is_integer() and abs(v) > 200 else v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    ledger = json.load(open(LEDGER))
    keys = [k for k in ledger['decisions'] if k.split('|')[0] in PIDS]
    cols_by_pid = {pid: sorted(k.split('|')[1] for k in keys if k.startswith(pid + '|')) for pid in PIDS}
    print('ledger entries to clear:', {p: len(c) for p, c in cols_by_pid.items()})

    df = _NoSidecar(download_dir=os.path.join(ROOT, 'data', '_feed_cache')).download_game_data(GAME_PK)
    feed = {r['PitchID']: r for _, r in df.iterrows() if r['PitchID'] in PIDS}
    for pid, want in EXPECT.items():
        for col, val in want.items():
            if abs(float(feed[pid][col]) - val) > 1e-6:
                raise SystemExit(f'{pid} {col}: the feed now says {feed[pid][col]}, expected {val}. Abort.')

    gc = gspread.service_account()
    ws = gc.open_by_key(_workbook_id_for_team('CHC')).worksheet('CHC')
    rows = ws.get_all_values()
    ci = {n: i for i, n in enumerate(rows[0])}
    cells, touched_rows = [], []
    for pid in PIDS:
        hits = [i for i, r in enumerate(rows[1:], start=2) if r[ci['PitchID']] == pid]
        if len(hits) != 1:
            raise SystemExit(f'{pid}: expected exactly 1 row, found {len(hits)}. Abort.')
        r_i = hits[0]; r = rows[r_i - 1]
        if r[ci['Pitcher']] != 'Thornton, Trent':
            raise SystemExit(f'{pid}: row {r_i} is {r[ci["Pitcher"]]}, not Thornton. Abort.')
        touched_rows.append(r_i)
        write = {c: cell(feed[pid][c]) for c in cols_by_pid[pid]}
        if pid in PITCH_TYPE:
            write['Pitch Type'] = PITCH_TYPE[pid]
        print(f'\n{pid}  row {r_i}  ({r[ci["Batter"]]})')
        for c in sorted(write):
            rej = ledger['decisions'].get(f'{pid}|{c}', {}).get('rejected')
            print(f'   {c:12s} {r[ci[c]]!r:>10} -> {write[c]!r:<10}' + (f'   (review saw {rej})' if rej else ''))
            cells.append(gspread.Cell(r_i, ci[c] + 1, write[c]))
    if not args.apply:
        print(f'\nDRY RUN: {len(cells)} cells and {len(keys)} ledger entries would change. Pass --apply.')
        return
    ws.update_cells(cells, value_input_option='USER_ENTERED')
    for r_i in touched_rows:
        apply_block_format(ws, rows[0], r_i, r_i, verbose=False)
    for k in keys:
        del ledger['decisions'][k]
    tmp = LEDGER + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(ledger, f, indent=1, sort_keys=True)
    os.replace(tmp, LEDGER)
    print(f'\nwrote {len(cells)} cells, cleared {len(keys)} ledger entries')
    back = ws.get_all_values()
    for r_i in touched_rows:
        r = back[r_i - 1]
        print('  read back:', {c: r[ci[c]] for c in ('PitchID', 'Pitch Type', 'Velocity', 'Spin Rate', 'RTilt', 'OTilt', 'IndVertBrk',
                                                    'HorzBrk', 'xIndVrtBrk', 'xHorzBrk', 'RelPosX', 'RelPosZ', 'Extension', 'VAA', 'ExitVelo')})


if __name__ == '__main__':
    main()
