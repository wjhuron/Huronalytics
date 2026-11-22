"""milb2026_neutral_movement.py -- put the neutral-movement x columns on the 2026 MiLB corpus.

The corpus (data/_milb2026/milb2026_pitches.csv.gz, built by milb2026_pull.py) stored
xIndVrtBrk / xHorzBrk from the retired single-exponent model, and 19% of its pitches had
no adjustment at all (parks with no elevation). This recomputes both columns for every
row from the row's own raw values with pipeline/neutral_move.py, after the corpus weather
record (data/_milb2026/game_weather.json) is upgraded with measured weather and wind, by
the same routine the sheet backfill uses.

The corpus is read and written in chunks (8 GB machine). The old file stays beside the new
one as milb2026_pitches.csv.gz.pre_nm1.bak on the first run. Nothing else in a row changes.

    SEED_DIR=data/_weather_audit   reuse the research weather cache where it has the game
    --dry                          count modes and changes, write nothing but the weather record

After a real run: rebuild the AAA pitcher pool (scripts/research/cards/aaa_pitcher_pool.py).

Usage: python3 scripts/builders/milb2026_neutral_movement.py [--dry]
"""
import argparse
import gzip
import json
import os
import shutil
import sys
from collections import Counter

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline import neutral_move as NM
from scrapers import sheet_precision as SP
from backfill_neutral_movement import upgrade_sidecar

OUT = os.path.join(ROOT, 'data', '_milb2026')
CORPUS = os.path.join(OUT, 'milb2026_pitches.csv.gz')
WEATHER = os.path.join(OUT, 'game_weather.json')


def num(s):
    return pd.to_numeric(s, errors='coerce').to_numpy(dtype='float64', na_value=np.nan)


def fmt(v, raw_blank):
    out = np.where(np.isfinite(v), np.char.mod('%.1f', np.nan_to_num(v)), '')
    return np.where(raw_blank, '', out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()
    with open(WEATHER) as f:
        store = json.load(f)
    pks = set()
    for ch in pd.read_csv(CORPUS, usecols=['PitchID'], dtype=str, keep_default_na=False, chunksize=300_000):
        pks |= {p.split('_')[0] for p in ch['PitchID'] if '_' in p and p.split('_')[0].isdigit()}
    print(f'{len(pks)} corpus games', flush=True)
    store = upgrade_sidecar(store, sorted(pks))
    tmp = WEATHER + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(store, f)
    os.replace(tmp, WEATHER)
    air = {}
    for pk in pks:
        i = store.get(pk) or {}
        air[pk] = NM.game_air(i.get('elevationFt'), i.get('tempF'), i.get('condition'), i.get('venueId'), i.get('obs'), i.get('wind'))
    no_elev = sorted({(store.get(pk) or {}).get('venueId') for pk in pks if air[pk] is None}, key=str)
    if no_elev:
        print(f'WARNING: venues with NO elevation (their pitches stay raw): {no_elev}')
    modes, deltas = Counter(), []
    metric_modes = Counter()
    out_tmp = CORPUS + '.tmp'
    writer = None if a.dry else gzip.open(out_tmp, 'wt', newline='')
    first = True
    for ch in pd.read_csv(CORPUS, dtype=str, keep_default_na=False, chunksize=100_000):
        pk = ch['PitchID'].str.split('_').str[0]
        get = lambda key: np.array([(air.get(k) or {}).get(key, np.nan) if air.get(k) else np.nan for k in pk], dtype=float)
        ln_p, ln_t, head, cross = get('lnP'), get('lnT'), get('head'), get('cross')
        measured = np.array([bool(air.get(k)) and air[k]['source'] == 'measured' for k in pk])
        thr = ch['Throws'].to_numpy(); rhp = thr == 'R'; hand_ok = np.isin(thr, ('L', 'R'))
        ivb, hb, velo = num(ch['IndVertBrk']), num(ch['HorzBrk']), num(ch['Velocity'])
        axis = np.array([NM.tilt_to_axis(t) for t in ch['RTilt']])
        ok = np.isfinite(ln_p) & hand_ok
        z = np.zeros(len(ch))
        n_run, n_ride, has_cell = NM.neutral_components(np.where(rhp, hb, -hb), ivb, rhp, axis, velo, np.where(ok, ln_p, z),
                                                        np.where(ok, ln_t, z), np.where(ok, head, z), np.where(ok, cross, z))
        new_ivb = np.where(ok, n_ride, ivb); new_hb = np.where(ok, np.where(rhp, n_run, -n_run), hb)
        tracked = np.isfinite(ivb) & np.isfinite(hb)
        modes['raw'] += int((tracked & ~ok).sum()); modes['standard'] += int((tracked & ok & ~measured).sum())
        modes['no_cell'] += int((tracked & ok & measured & ~has_cell).sum()); modes['full'] += int((tracked & ok & measured & has_cell).sum())
        old = num(ch['xIndVrtBrk'])
        d = np.round(new_ivb, 1) - old
        deltas.append(d[np.isfinite(d)])
        # The six neutral metric columns (model wm1), from the row's raw values and the
        # x movement at the depth the file holds. No air for the game: x equals raw.
        xm, mm = NM.neutral_metric_table({c: num(ch[c]) for c in NM.METRIC_COLUMNS}, thr, np.round(new_ivb, 1),
                                         np.round(new_hb, 1), np.where(np.isfinite(ln_p), ln_p, np.nan), ln_t)
        metric_modes.update(mm)
        # The hitter side (model hm1): carry distance, bat speed, swing length, air value.
        hx, _hm = NM.neutral_hitter_table({c: num(ch[c]) for c in NM.HITTER_METRIC_COLUMNS}, num(ch['ExitVelo']), num(ch['LaunchAngle']),
                                          (ch['BBType'].to_numpy() != ''), np.where(np.isfinite(ln_p), ln_p, np.nan), ln_t)
        xm.update(hx)
        if writer is not None:
            ch['xIndVrtBrk'] = fmt(new_ivb, ~np.isfinite(ivb)); ch['xHorzBrk'] = fmt(new_hb, ~np.isfinite(hb))
            for xcol, v in xm.items():
                ch[xcol] = [SP.fmt(xcol, x) for x in v]
            ch.to_csv(writer, index=False, header=first)
            first = False
    if writer is not None:
        writer.close()
    d = np.concatenate(deltas)
    print('modes (pitches): ' + ', '.join(f"{v} '{k}'" for k, v in modes.items()))
    print('neutral metric modes (pitches): ' + ', '.join(f"{v} '{k}'" for k, v in metric_modes.items()))
    print(f'xIndVrtBrk change vs the stored column, inches: mean {d.mean():+.2f} sd {d.std():.2f} p5 {np.percentile(d, 5):+.1f} p95 {np.percentile(d, 95):+.1f}')
    if a.dry:
        print('DRY RUN: the corpus was not written.')
        return
    if not os.path.exists(CORPUS + '.pre_wm1.bak'):
        shutil.copy2(CORPUS, CORPUS + '.pre_wm1.bak')
    os.replace(out_tmp, CORPUS)
    print('corpus written. Owed next: scripts/research/cards/aaa_pitcher_pool.py')


if __name__ == '__main__':
    main()
