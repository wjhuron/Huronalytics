"""backfill_neutral_movement.py -- rewrite the sheet x columns with the neutral-movement model.

Recomputes xIndVrtBrk / xHorzBrk on every pitch row of the six division workbooks
(plus the ROC / AAA / NEW tabs) from the row's own raw values, with
pipeline/neutral_move.py. The model needs, per game, measured weather and the feed
wind, so the weather sidecar (data/game_weather_rs.json) is upgraded first.

Steps
  1. Read every tab (PitchID, Throws, RTilt, Velocity, IndVertBrk, HorzBrk, the two x columns).
  2. Upgrade the sidecar for every game on the sheets: wind and start time from the feed,
     measured pressure / humidity / temperature from Open-Meteo. A game that already holds
     an ARCHIVE reading is left alone. SEED_DIR (optional) points at a research cache
     (game_obs.json + wind.json from scripts/research/weather/) to avoid ~2 requests a game.
  3. Compute the new values, print per-tab change counts, the change distribution and the
     count of each degrade mode.
  4. DRY RUN by default. APPLY=1 writes, after saving the current x columns to
     data/_xcol_backup_<timestamp>.pkl. Writes are USER_ENTERED, one column range per call.

The dry run touches no sheet. It does write the upgraded sidecar unless NO_SIDECAR=1.

Usage:
    python3 scripts/builders/backfill_neutral_movement.py            # dry run
    APPLY=1 python3 scripts/builders/backfill_neutral_movement.py    # write
"""
import json
import os
import pickle
import sys
import time
from collections import Counter
from datetime import datetime

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from pipeline import neutral_move as NM
from pipeline.fetch import _gspread_client, DIVISION_WORKBOOK_IDS, read_sheet_with_retry
from pipeline.utils import MLB_TEAMS
from scrapers import weather_obs
from scrapers.pitcher2026 import VENUE_ELEVATION_FT_OVERRIDE

SIDECAR = os.path.join(ROOT, 'data', 'game_weather_rs.json')
FEED = ('https://statsapi.mlb.com/api/v1.1/game/{pk}/feed/live?fields=gameData,datetime,dateTime,'
        'weather,temp,condition,wind,venue,id,name,location,elevation,defaultCoordinates,latitude,longitude')
APPLY = os.environ.get('APPLY') == '1'
HELD_CSV = os.path.expanduser('~/Downloads/neutral_backfill_held_rows.csv')


# Games whose held cells were reviewed and RELEASED (Wally, 2026-11-20): the x value was
# the wrong side. 816387 (2026-08-27, NEW tab): the feed reported 8 F, the old model
# turned that into a factor of 0.875, and all 61 held cells there equal 0.875 x raw
# while the raw values match the feed.
RELEASED_GAMES = {'816387'}


def old_x_disagrees(raw, old):
    """True when the x value on the sheet is not the raw value times any factor the old
    density model could produce (0.90 to 1.40; Mexico City is about 1.35). Such a cell was
    edited by hand on one side only, so recomputing x from raw would overwrite a decision
    (2026-11-20 dry run: 131 cells, e.g. a four-seam with raw HorzBrk -13.1 and x 5.3).
    Those cells are HELD: left as they are and listed for review. The band is a convention."""
    if raw is None or old is None:
        return False
    if abs(raw) < 2.0:
        return abs(old - raw) > 1.0
    return not (0.90 <= old / raw <= 1.40)
SEED_DIR = os.environ.get('SEED_DIR')
NEED = ('PitchID', 'Throws', 'RTilt', 'Velocity', 'IndVertBrk', 'HorzBrk', 'xIndVrtBrk', 'xHorzBrk')


def sf(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def col_letter(idx0):
    s, n = '', idx0 + 1
    while n:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def upgrade_sidecar(store, pks):
    """Make every game's entry carry wind, the feed temperature and an archive reading."""
    seed_obs, seed_wind = {}, {}
    if SEED_DIR:
        with open(os.path.join(SEED_DIR, 'game_obs.json')) as f:
            seed_obs = json.load(f)
        with open(os.path.join(SEED_DIR, 'wind.json')) as f:
            seed_wind = json.load(f)
        print(f'seed cache: {len(seed_obs)} measured games, {len(seed_wind)} wind strings')
    s = requests.Session()
    counts = Counter()
    for i, pk in enumerate(pks):
        info = store.get(pk) or {}
        obs = info.get('obs')
        if obs and obs.get('source') == 'archive' and 'wind' in info:
            counts['already complete'] += 1
            continue
        closed = (info.get('condition') or '').strip().lower() in NM.ROOF_CLOSED_CONDITIONS
        seeded = seed_obs.get(pk)
        # The seed is usable when the entry already has its elevation; a closed-roof
        # entry needs no feed temperature (the old sidecar stored the 72 F clamp there).
        if seeded and info.get('elevationFt') is not None and (pk in seed_wind or closed):
            info['obs'] = dict(p_hpa=seeded['p_hpa'], tempF=seeded['tempF'], rh=seeded['rh'], source='archive')
            info['wind'] = seed_wind.get(pk)
            if closed:
                info['tempF'] = None            # the stored value was the clamp, not a feed reading
            counts['seeded'] += 1
        else:
            try:
                r = s.get(FEED.format(pk=pk), timeout=20)
                r.raise_for_status()
                gd = r.json().get('gameData', {})
            except (requests.RequestException, ValueError) as e:
                print(f'  game {pk}: feed request failed ({e}); entry left as it was')
                counts['feed failed'] += 1
                continue
            w, venue = gd.get('weather', {}), gd.get('venue', {})
            elev = (venue.get('location') or {}).get('elevation')
            if elev is None:
                elev = VENUE_ELEVATION_FT_OVERRIDE.get(venue.get('id'))
            info.update(venueId=venue.get('id'), condition=w.get('condition'), tempF=sf(w.get('temp')),
                        wind=w.get('wind'), elevationFt=sf(elev))
            if info['elevationFt'] is not None:
                lat, lon = weather_obs.venue_coords(venue)
                got = weather_obs.fetch_measured(lat, lon, info['elevationFt'],
                                                 (gd.get('datetime') or {}).get('dateTime'), pk)
                if got:
                    info['obs'] = got
            counts['fetched'] += 1
            time.sleep(0.2)
        store[pk] = info
        if (i + 1) % 250 == 0:
            print(f'  sidecar {i + 1}/{len(pks)}', flush=True)
    for pk in pks:
        info = store.get(pk) or {}
        air = NM.game_air(info.get('elevationFt'), info.get('tempF'), info.get('condition'),
                          info.get('venueId'), info.get('obs'), info.get('wind'))
        info.pop('factor', None)                 # the retired single-exponent factor
        info.update(rho=round(air['rho'], 5) if air else None, lnP=round(air['lnP'], 6) if air else None,
                    lnT=round(air['lnT'], 6) if air else None, source=air['source'] if air else None,
                    model=NM.load_coefficients().get('version'))
        store[pk] = info
    print('sidecar upgrade: ' + ', '.join(f'{v} {k}' for k, v in counts.items()))
    return store


def main():
    gc = _gspread_client()
    try:
        with open(SIDECAR) as f:
            store = json.load(f)
    except (FileNotFoundError, ValueError):
        store = {}
    tab_rows, all_pks = [], set()
    for name, wid in DIVISION_WORKBOOK_IDS.items():
        extra = {'ROC', 'AAA', 'NEW'} if name == 'NLE2026' else set()
        sh = gc.open_by_key(wid)
        print(f'{sh.title}:')
        for ws in sh.worksheets():
            tab = ws.title
            if tab not in MLB_TEAMS and tab not in extra:
                continue
            rows = read_sheet_with_retry(ws)
            time.sleep(0.6)
            if not rows:
                continue
            ci = {n: i for i, n in enumerate(rows[0]) if n}
            if any(k not in ci for k in NEED):
                print(f'  {tab}: missing columns, SKIPPED ({[k for k in NEED if k not in ci]})')
                continue
            for row in rows[1:]:
                pid = row[ci['PitchID']] if ci['PitchID'] < len(row) else ''
                if pid and '_' in pid and pid.split('_')[0].isdigit():
                    all_pks.add(pid.split('_')[0])
            tab_rows.append((ws, tab, rows, ci))
            print(f'  {tab}: {len(rows) - 1} rows read')

    store = upgrade_sidecar(store, sorted(all_pks))
    if os.environ.get('NO_SIDECAR') != '1':
        tmp = SIDECAR + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(store, f, indent=0, sort_keys=True)
        os.replace(tmp, SIDECAR)
    air_by_pk = {}
    for pk in all_pks:
        info = store.get(pk) or {}
        air_by_pk[pk] = NM.game_air(info.get('elevationFt'), info.get('tempF'), info.get('condition'),
                                    info.get('venueId'), info.get('obs'), info.get('wind'))
    no_elev = sorted(pk for pk, a in air_by_pk.items() if a is None)
    if no_elev:
        print(f'WARNING: {len(no_elev)} games have NO elevation; their x values stay equal to raw: {no_elev[:12]}'
              f'{" ..." if len(no_elev) > 12 else ""}. Add the parks to VENUE_ELEVATION_FT_OVERRIDE.')

    plans, backup, deltas, modes, total = [], {}, {'xIndVrtBrk': [], 'xHorzBrk': []}, Counter(), 0
    held = []
    for ws, tab, rows, ci in tab_rows:
        n = len(rows) - 1
        new = {'xIndVrtBrk': [['xIndVrtBrk']], 'xHorzBrk': [['xHorzBrk']]}
        old = {'xIndVrtBrk': [], 'xHorzBrk': []}
        changed = 0
        for row in rows[1:]:
            cell = lambda k: row[ci[k]] if ci[k] < len(row) else ''
            pid = cell('PitchID')
            pk = pid.split('_')[0] if pid and '_' in pid else None
            ivb, hb = sf(cell('IndVertBrk')), sf(cell('HorzBrk'))
            if ivb is None and hb is None:
                x_ivb = x_hb = None
            else:
                x_ivb, x_hb, mode = NM.neutral_movement(ivb, hb, cell('Throws'), cell('RTilt'),
                                                        sf(cell('Velocity')), air_by_pk.get(pk))
                modes[mode] += 1
            for key, val, raw in (('xIndVrtBrk', x_ivb, ivb), ('xHorzBrk', x_hb, hb)):
                was = cell(key)
                old[key].append(was)
                if val is None:
                    new[key].append([''])
                    continue
                val = round(val, 1)
                was_f = sf(was)
                if pk not in RELEASED_GAMES and old_x_disagrees(raw, was_f):
                    held.append((tab, pid, cell('Game Date') if 'Game Date' in ci else '', cell('Pitcher') if 'Pitcher' in ci else '',
                                 cell('Pitch Type') if 'Pitch Type' in ci else '', key, raw, was_f, val))
                    new[key].append([was_f])
                    continue
                new[key].append([val])
                if was_f is None or abs(was_f - val) > 0.049:
                    changed += 1
                    if was_f is not None:
                        deltas[key].append(val - was_f)
        total += changed
        backup[f'{ws.spreadsheet.title}|{tab}'] = old
        plans.append((ws, tab, n, ci, new, changed))
        print(f'  planned {tab}: {changed} changed cells / {2 * n}')

    print(f'\nTOTAL: {total} changed cells across {len(plans)} tabs')
    print('degrade modes (pitches): ' + ', '.join(f"{v} '{k}'" for k, v in sorted(modes.items())))
    for key, ds in deltas.items():
        if ds:
            ds = sorted(ds)
            print(f'{key} change (new - old, inches): min {ds[0]:.1f}  p5 {ds[len(ds) // 20]:.1f}  median {ds[len(ds) // 2]:.1f}  '
                  f'p95 {ds[-len(ds) // 20]:.1f}  max {ds[-1]:.1f}')
    if held:
        import csv
        with open(HELD_CSV, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['Tab', 'PitchID', 'Game Date', 'Pitcher', 'Pitch Type', 'Column', 'Raw', 'x on sheet (kept)', 'x from model'])
            w.writerows(held)
        print(f'HELD: {len(held)} cells whose x value disagrees with the raw value were left as they are: {HELD_CSV}')
    if not APPLY:
        print('\nDRY RUN: no sheet was written. Set APPLY=1 to write.')
        return

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    bpath = os.path.join(ROOT, 'data', f'_xcol_backup_{stamp}.pkl')
    with open(bpath, 'wb') as f:
        pickle.dump(backup, f)
    print(f'backup of the old x columns: {bpath}')
    for ws, tab, n, ci, new, changed in plans:
        if changed == 0:
            print(f'  {tab}: no changes, skipped')
            continue
        for key in ('xIndVrtBrk', 'xHorzBrk'):
            letter = col_letter(ci[key])
            ws.update(values=new[key], range_name=f'{letter}1:{letter}{n + 1}', value_input_option='USER_ENTERED')
            time.sleep(1.0)
        print(f'  wrote {tab} ({changed} changed cells)', flush=True)
    print('\nBackfill complete. Owed next: process_data, the Stuff+ retrain, both expected-movement fits.')


if __name__ == '__main__':
    main()
