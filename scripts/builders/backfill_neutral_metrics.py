"""backfill_neutral_metrics.py -- the sheet writer of the ten neutral-environment metric columns.

Columns (appended after the last column of every pitch tab, in this order):
    xVelocity  xSpinRate  xExtension  xArmAngle  xVAA  xHAA          (pitch side, model wm1)
    xDistance  xBatSpeed  xSwingLength  AirwOBA                      (hitter side, model hm1)
Each x column is the raw column with the weather effect removed; AirwOBA is the wOBA the
air added to a ball in play (pipeline/neutral_move.py; the math is there and nowhere
else). The raw columns are never written.

The tool is idempotent. Every run recomputes every row of every tab from the row's own raw
values, the row's xIndVrtBrk / xHorzBrk and the game's air (data/game_weather_rs.json), and
writes only the tabs where a cell differs. Run it:
  - once, to create the columns (the first APPLY=1 run adds them to each tab);
  - after scrapers/backfill_supplement.py or scrapers/backfill_full.py changed a raw value
    (ArmAngle arrives from Savant after the scrape, so its x cell is blank until then);
  - after scripts/builders/backfill_neutral_movement.py (the angles read its columns).

The columns go at the END of the tab on purpose: scripts/ci/sheets_write_grades.py writes
Stuff+ and Loc+ by position, so a column inserted before them would send grades into the
wrong cells.

A game with no air (no elevation in the weather record) keeps x equal to raw and is
listed. An approach angle with no neutral movement gets a blank x cell.

Dry run by default: prints the plan and a check of the result (the Coors gap of each
metric, raw against x, same pitcher and pitch type). APPLY=1 writes.

Usage: python3 scripts/builders/backfill_neutral_metrics.py
       APPLY=1 python3 scripts/builders/backfill_neutral_metrics.py
"""
import json
import os
import sys
import time
from collections import Counter, defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from pipeline import neutral_move as NM
from pipeline.fetch import (_gspread_client, DIVISION_WORKBOOK_IDS, EXTRA_TABS_WORKBOOK, SCRATCH_TABS,
                            read_sheet_with_retry, sheets_call_with_retry)
from pipeline.utils import MLB_TEAMS
from scrapers.sheet_precision import NUMBER_FORMATS, PRECISION, fmt

SIDECAR = os.path.join(ROOT, 'data', 'game_weather_rs.json')
APPLY = os.environ.get('APPLY') == '1'
XCOLS = NM.X_METRIC_COLUMNS + NM.X_HITTER_COLUMNS          # sheet order: the six pitch columns, then the four hitter ones
NEED = (('PitchID', 'Throws', 'xIndVrtBrk', 'xHorzBrk') + tuple(NM.METRIC_COLUMNS)
        + ('ExitVelo', 'LaunchAngle', 'BBType') + tuple(NM.HITTER_METRIC_COLUMNS))
COORS = 19
CHUNK = 15000                     # rows per write request


def col_letter(idx0):
    s, n = '', idx0 + 1
    while n:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def num(col):
    out = np.full(len(col), np.nan)
    for i, v in enumerate(col):
        if v not in ('', None):
            try:
                out[i] = float(v)
            except ValueError:
                pass
    return out


def plan_tab(rows, ci, air_by_pk):
    """Returns (new 6-column block of strings, changed cell count, modes, per-row arrays for the check)."""
    body = rows[1:]
    get = lambda k: [r[ci[k]] if ci[k] < len(r) else '' for r in body]
    pks = [p.split('_')[0] if '_' in p else '' for p in get('PitchID')]
    air = [air_by_pk.get(k) for k in pks]
    ln_p = np.array([a['lnP'] if a else np.nan for a in air], dtype=float)
    ln_t = np.array([a['lnT'] if a else np.nan for a in air], dtype=float)
    raw = {c: num(get(c)) for c in NM.METRIC_COLUMNS}
    throws = np.array(get('Throws'), dtype=object)
    out, modes = NM.neutral_metric_table(raw, throws, num(get('xIndVrtBrk')), num(get('xHorzBrk')), ln_p, ln_t)
    hraw = {c: num(get(c)) for c in NM.HITTER_METRIC_COLUMNS}
    bip = np.array([v not in ('', None) for v in get('BBType')])
    hout, hmodes = NM.neutral_hitter_table(hraw, num(get('ExitVelo')), num(get('LaunchAngle')), bip, ln_p, ln_t)
    out.update(hout); raw.update(hraw)
    modes = dict(modes, hitter_raw=hmodes['raw'], hitter_full=hmodes['full'])
    block = [[fmt(x, out[x][i]) for x in XCOLS] for i in range(len(body))]
    changed = 0
    for j, x in enumerate(XCOLS):
        if x in ci:
            changed += sum(1 for i, r in enumerate(body) if (r[ci[x]] if ci[x] < len(r) else '') != block[i][j])
        else:
            changed += sum(1 for row in block if row[j] != '')
    return block, changed, modes, dict(pks=pks, throws=throws, raw=raw, out=out, bip=bip, la=num(get('LaunchAngle')),
                                       pitcher=get('Pitcher') if 'Pitcher' in ci else [''] * len(body),
                                       pt=get('Pitch Type') if 'Pitch Type' in ci else [''] * len(body))


def coors_check(parts, venue_by_pk):
    """Coors minus elsewhere, same (pitcher, pitch type), raw against x. Printed, not gated:
    the models were tested on held-out seasons in the research; this only shows that the
    sheet numbers behave the same way (a sign error would show as a gap that GROWS)."""
    acc = defaultdict(lambda: defaultdict(lambda: [0.0, 0, 0.0, 0, 0.0, 0, 0.0, 0]))
    for p in parts:
        at = np.array([venue_by_pk.get(k) == COORS for k in p['pks']])
        s_arm = np.where(p['throws'] == 'R', -1.0, 1.0)
        for col, (xcol, key) in NM.METRIC_COLUMNS.items():
            r, x = p['raw'][col], p['out'][xcol]
            if key == 'haa_arm':
                r, x = r * s_arm, x * s_arm
            ok = np.isfinite(r) & np.isfinite(x)
            for i in np.where(ok)[0]:
                a = acc[col][(p['pitcher'][i], p['pt'][i])]
                o = 0 if at[i] else 4
                a[o] += r[i]; a[o + 1] += 1; a[o + 2] += x[i]; a[o + 3] += 1
    print('\nCHECK: Coors minus elsewhere, same pitcher and pitch type (25 or more pitches each side)')
    for col in NM.METRIC_COLUMNS:
        w = g_raw = g_x = 0.0
        n = 0
        for a in acc[col].values():
            if a[1] >= 25 and a[5] >= 25:
                wt = 1 / (1 / a[1] + 1 / a[5])
                g_raw += wt * (a[0] / a[1] - a[4] / a[5]); g_x += wt * (a[2] / a[3] - a[6] / a[7])
                w += wt; n += 1
        if w:
            print(f'  {col:10s} raw {g_raw / w:+8.3f}   x {g_x / w:+8.3f}   ({n} pitcher pitch types)')


def add_columns(ws, header):
    """Append the x columns that the tab does not have. Returns the new header."""
    missing = [x for x in XCOLS if x not in header]
    if not missing:
        return header
    have = [x for x in XCOLS if x in header]
    # The tab may hold a leading part of XCOLS (the six pitch columns came first). Anything
    # else (a gap, another order, columns after them) is repaired by hand, never guessed.
    if have + missing != XCOLS or (have and header[-len(have):] != have):
        raise SystemExit(f'{ws.title}: the x columns on the tab ({have}) are not a leading part of {XCOLS} at the end of '
                         f'the header. Repair the header by hand before a write.')
    start = len(header)
    need = start + len(missing)
    if ws.col_count < need:
        sheets_call_with_retry(lambda: ws.add_cols(need - ws.col_count))
    rng = f'{col_letter(start)}1:{col_letter(need - 1)}1'
    sheets_call_with_retry(lambda: ws.update(values=[missing], range_name=rng, value_input_option='USER_ENTERED'))
    reqs = [{'copyPaste': {                                   # the look of the last old column, header and data
        'source': {'sheetId': ws.id, 'startColumnIndex': start - 1, 'endColumnIndex': start},
        'destination': {'sheetId': ws.id, 'startColumnIndex': start, 'endColumnIndex': need},
        'pasteType': 'PASTE_FORMAT', 'pasteOrientation': 'NORMAL'}}]
    for j, x in enumerate(missing):
        reqs.append({'repeatCell': {
            'range': {'sheetId': ws.id, 'startRowIndex': 1, 'startColumnIndex': start + j, 'endColumnIndex': start + j + 1},
            'cell': {'userEnteredFormat': {'numberFormat': NUMBER_FORMATS[x]}},
            'fields': 'userEnteredFormat.numberFormat'}})
    sheets_call_with_retry(lambda: ws.spreadsheet.batch_update({'requests': reqs}))
    return header + missing


def main():
    assert all(x in PRECISION for x in XCOLS)
    with open(SIDECAR) as f:
        store = json.load(f)
    gc = _gspread_client()
    tabs = []
    for name, wid in DIVISION_WORKBOOK_IDS.items():
        extra = ({'ROC', 'AAA'} | set(SCRATCH_TABS)) if name == EXTRA_TABS_WORKBOOK else set()
        sh = sheets_call_with_retry(lambda: gc.open_by_key(wid))
        print(f'{sh.title}:', flush=True)
        for ws in sheets_call_with_retry(sh.worksheets):
            if ws.title not in MLB_TEAMS and ws.title not in extra:
                continue
            rows = read_sheet_with_retry(ws)
            time.sleep(0.6)
            if not rows or len(rows) < 2:
                continue
            ci = {n: i for i, n in enumerate(rows[0]) if n}
            if any(k not in ci for k in NEED):
                print(f'  {ws.title}: missing columns, SKIPPED ({[k for k in NEED if k not in ci]})')
                continue
            tabs.append((ws, rows, ci))
            print(f'  {ws.title}: {len(rows) - 1} rows read', flush=True)

    air_by_pk, venue_by_pk, no_air = {}, {}, set()
    for ws, rows, ci in tabs:
        for r in rows[1:]:
            pid = r[ci['PitchID']] if ci['PitchID'] < len(r) else ''
            pk = pid.split('_')[0] if '_' in pid else ''
            if not pk or pk in air_by_pk:
                continue
            info = store.get(pk) or {}
            air_by_pk[pk] = NM.game_air(info.get('elevationFt'), info.get('tempF'), info.get('condition'),
                                        info.get('venueId'), info.get('obs'), info.get('wind'))
            venue_by_pk[pk] = info.get('venueId')
            if air_by_pk[pk] is None:
                no_air.add(pk)
    if no_air:
        print(f'WARNING: {len(no_air)} games have NO air in {SIDECAR}; their x values stay equal to raw: '
              f'{sorted(no_air)[:12]}{" ..." if len(no_air) > 12 else ""}. '
              f'Repair: scripts/builders/backfill_neutral_movement.py (it completes the weather record).')

    plans, parts, modes, total = [], [], Counter(), 0
    for ws, rows, ci in tabs:
        block, changed, m, part = plan_tab(rows, ci, air_by_pk)
        modes.update(m); total += changed
        plans.append((ws, rows, ci, block, changed)); parts.append(part)
        print(f'  planned {ws.title}: {changed} cells to write / {len(XCOLS) * (len(rows) - 1)}'
              f'{"" if all(x in ci for x in XCOLS) else "  (columns to add: " + str(len([x for x in XCOLS if x not in ci])) + ")"}')
    print(f'\nTOTAL: {total} cells to write across {len(plans)} tabs')
    print('modes (pitches): ' + ', '.join(f"{v} '{k}'" for k, v in sorted(modes.items())))
    pairs = [(c, x) for c, (x, _) in NM.METRIC_COLUMNS.items()] + list(NM.HITTER_METRIC_COLUMNS.items())
    for col, xcol in pairs:
        d = np.concatenate([p['out'][xcol] - p['raw'][col] for p in parts])
        d = d[np.isfinite(d)]
        if len(d):
            print(f'  {xcol:10s} x - raw: mean {d.mean():+.4f}  sd {d.std():.4f}  p1 {np.percentile(d, 1):+.3f}  p99 {np.percentile(d, 99):+.3f}  n {len(d)}')
    coors_check(parts, venue_by_pk)
    av = np.concatenate([p['out'][NM.AIR_VALUE_COLUMN] for p in parts])
    at = np.concatenate([[venue_by_pk.get(k) == COORS for k in p['pks']] for p in parts])
    la = np.concatenate([p['la'] for p in parts]); ok = np.isfinite(av)
    print(f'\n{NM.AIR_VALUE_COLUMN}: {int(ok.sum())} balls in play, mean {np.mean(av[ok]):+.4f}; air balls (LA 10+) mean '
          f'{np.mean(av[ok & (la >= 10)]):+.4f}, at Coors {np.mean(av[ok & (la >= 10) & at]):+.4f}, elsewhere {np.mean(av[ok & (la >= 10) & ~at]):+.4f}')
    if not APPLY:
        print('\nDRY RUN: no sheet was written. Set APPLY=1 to write.')
        return

    for ws, rows, ci, block, changed in plans:
        if changed == 0:
            print(f'  {ws.title}: no changes, skipped')
            continue
        header = add_columns(ws, rows[0])
        first = header.index(XCOLS[0])
        if header[first:first + len(XCOLS)] != XCOLS:
            raise SystemExit(f'{ws.title}: the x metric columns are not adjacent and in order; no write.')
        a, b = col_letter(first), col_letter(first + len(XCOLS) - 1)
        for s in range(0, len(block), CHUNK):
            part = block[s:s + CHUNK]
            rng = f'{a}{s + 2}:{b}{s + 1 + len(part)}'
            sheets_call_with_retry(lambda: ws.update(values=part, range_name=rng, value_input_option='USER_ENTERED'))
            time.sleep(1.0)
        print(f'  wrote {ws.title} ({changed} cells)', flush=True)
    print('\nBackfill complete.')


if __name__ == '__main__':
    main()
