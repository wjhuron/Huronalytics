"""augment_training_neutral_movement.py -- put the neutral-movement x columns on the
prior-season Stuff+ training pickles (data/_pitches{year}_training.pkl, 2021-2025).

The pickles carry the raw movement (IndVertBrk / HorzBrk), SpinAxis, Velocity, Throws and
_game_pk, which is everything pipeline/neutral_move.py needs per pitch. Per game it needs
measured weather and the feed wind, so data/game_weather_2025.json (the 2021-2025 weather
record, despite its name) is upgraded first, with the same routine the sheet backfill uses.

Nothing is fitted here. The x columns are overwritten with the model's values, rounded to
0.1 like the sheet columns. A game with no elevation keeps x equal to raw and is reported.

    --data-dir DIR   where the pickles are read (default: the repo's data/)
    --out-dir DIR    where the updated pickles are written (default: in place, through a
                     temp file; the first in-place run keeps <name>.pre_nm1.bak)
    --years 2021 ... which seasons (default 2021-2025)
    SEED_DIR=...     research cache with game_obs.json + wind.json (skips ~2 requests a game)

After a real run: REPUBLISH the release assets, or CI retrains on the old columns
(root CLAUDE.md failure log). This script does not upload anything.

Usage: python3 scripts/builders/augment_training_neutral_movement.py --out-dir /some/scratch
"""
import argparse
import json
import os
import pickle
import shutil
import sys
from collections import Counter

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline import neutral_move as NM
from backfill_neutral_movement import upgrade_sidecar

STORE = os.path.join(ROOT, 'data', 'game_weather_2025.json')
COORS = 19


def sf(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float('nan')


def apply_to_pitches(D, store, label=''):
    """Overwrite xIndVrtBrk / xHorzBrk on training-pickle dicts (in place). D rows need
    _game_pk, Throws, IndVertBrk, HorzBrk, Velocity and SpinAxis (a row without a spin
    axis gets the exponents and wind only). Returns the mode counts."""
    n = len(D)
    pk = np.array([int(p['_game_pk']) if p.get('_game_pk') is not None else -1 for p in D])
    air = {}
    for k in np.unique(pk):
        info = store.get(str(int(k))) or {}
        air[int(k)] = NM.game_air(info.get('elevationFt'), info.get('tempF'), info.get('condition'),
                                  info.get('venueId'), info.get('obs'), info.get('wind'))
    get = lambda key: np.array([(air[int(k)] or {}).get(key, np.nan) if air[int(k)] else np.nan for k in pk], dtype=float)
    ln_p, ln_t, head, cross = get('lnP'), get('lnT'), get('head'), get('cross')
    has_air = np.isfinite(ln_p)
    measured = np.array([bool(air[int(k)]) and air[int(k)]['source'] == 'measured' for k in pk])
    throws = np.array([p.get('Throws') or '' for p in D])
    hand_ok = np.isin(throws, ('L', 'R')); rhp = throws == 'R'
    ivb = np.array([sf(p.get('IndVertBrk')) for p in D]); hb = np.array([sf(p.get('HorzBrk')) for p in D])
    axis = np.array([sf(p.get('SpinAxis')) for p in D]); velo = np.array([sf(p.get('Velocity')) for p in D])
    run = np.where(rhp, hb, -hb)
    ok = has_air & hand_ok
    z = np.zeros(n)
    n_run, n_ride, has_cell = NM.neutral_components(run, ivb, rhp, axis, velo, np.where(ok, ln_p, z), np.where(ok, ln_t, z),
                                                    np.where(ok, head, z), np.where(ok, cross, z))
    new_ivb = np.where(ok, n_ride, ivb); new_hb = np.where(ok, np.where(rhp, n_run, -n_run), hb)
    tracked = np.isfinite(ivb) & np.isfinite(hb)
    modes = Counter()
    modes['raw (no elevation or no hand)'] = int((tracked & ~ok).sum())
    modes['standard (no measured weather)'] = int((tracked & ok & ~measured).sum())
    modes['no_cell (no spin axis or velocity)'] = int((tracked & ok & measured & ~has_cell).sum())
    modes['full'] = int((tracked & ok & measured & has_cell).sum())
    old_ivb = np.array([sf(p.get('xIndVrtBrk')) for p in D]); old_hb = np.array([sf(p.get('xHorzBrk')) for p in D])
    for i, p in enumerate(D):
        if np.isfinite(ivb[i]):
            p['xIndVrtBrk'] = round(float(new_ivb[i]), 1)
        if np.isfinite(hb[i]):
            p['xHorzBrk'] = round(float(new_hb[i]), 1)
    d_ride = new_ivb - old_ivb; d_run = np.where(rhp, new_hb - old_hb, -(new_hb - old_hb))
    venue = np.array([(store.get(str(int(k))) or {}).get('venueId') or -1 for k in pk])
    ff = tracked & np.array([p.get('Pitch Type') == 'FF' for p in D])
    print(f'{label}: {n} pitches | ' + ', '.join(f'{v} {k}' for k, v in modes.items() if v))
    if np.isfinite(d_ride[tracked]).any():
        print(f'   change vs the old x columns, inches: ride mean {np.nanmean(d_ride[tracked]):+.2f} sd {np.nanstd(d_ride[tracked]):.2f} | '
              f'run mean {np.nanmean(d_run[tracked]):+.2f} sd {np.nanstd(d_run[tracked]):.2f} | '
              f'four-seam ride at Coors {np.nanmean(d_ride[ff & (venue == COORS)]) if (ff & (venue == COORS)).any() else float("nan"):+.2f}')
    return modes


def one_year(year, data_dir, out_dir, store):
    src = os.path.join(data_dir, f'_pitches{year}_training.pkl')
    with open(src, 'rb') as f:
        D = pickle.load(f)
    modes = apply_to_pitches(D, store, str(year))
    dst_dir = out_dir or data_dir
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, f'_pitches{year}_training.pkl')
    if not out_dir and not os.path.exists(src + '.pre_nm1.bak'):
        shutil.copy2(src, src + '.pre_nm1.bak')
    tmp = dst + '.tmp'
    with open(tmp, 'wb') as f:
        pickle.dump(D, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, dst)
    return modes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-dir', default=os.path.join(ROOT, 'data'))
    ap.add_argument('--out-dir', default=None)
    ap.add_argument('--years', nargs='*', type=int, default=[2021, 2022, 2023, 2024, 2025])
    ap.add_argument('--no-store-write', action='store_true', help='do not write the upgraded weather record')
    a = ap.parse_args()
    with open(STORE) as f:
        store = json.load(f)
    pks = set()
    for y in a.years:
        with open(os.path.join(a.data_dir, f'_pitches{y}_training.pkl'), 'rb') as f:
            pks |= {str(int(p['_game_pk'])) for p in pickle.load(f) if p.get('_game_pk') is not None}
    store = upgrade_sidecar(store, sorted(pks))
    if not a.no_store_write:
        tmp = STORE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(store, f, indent=0, sort_keys=True)
        os.replace(tmp, STORE)
    total = Counter()
    for y in a.years:
        total.update(one_year(y, a.data_dir, a.out_dir, store))
    print('TOTAL: ' + ', '.join(f'{v} {k}' for k, v in total.items()))
    print('Owed after a real run: republish the release assets, then the Stuff+ retrain.')


if __name__ == '__main__':
    main()
