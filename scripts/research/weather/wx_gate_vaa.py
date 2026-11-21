"""wx_gate_vaa.py -- Stuff+ gate (v2) with a neutral-environment approach angle.

RESEARCH ONLY. The gate frames keep `vaa_raw` and no game key, so the frames are rebuilt
from the pitch lists with VAA replaced by

    neutral VAA = VAA - (aP + bP * ride) * lnP - (aT + bT * ride) * lnT

(coefficients: data/_weather_audit/vaa2.json, wx_vaa2.py; ride = the pitch's neutral ride;
lnP / lnT = the game's air from pipeline/neutral_move.py). Everything else in a frame is
the installed baseline's, row for row, so the arm NVAA differs from SHIPPED in the approach
angle only. Frames go to data/_gate_v2_nvaa/; the installed SHIPPED aggregates are linked.

    build | run | summary
"""
import gc
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wx_gate_frames as F  # noqa: E402

G, NM = F.G, F.NM
ROOT = F.MAIN
BASE = G.CACHE
NEW = os.path.join(ROOT, 'data', '_gate_v2_nvaa')
FIT = json.load(open(os.path.join(ROOT, 'data', '_weather_audit', 'vaa2.json')))['fit']


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def neutralize(pk, store, key):
    air, n = {}, 0
    for p in pk:
        k = key(p)
        if k not in air:
            i = store.get(k) or {}
            air[k] = NM.game_air(i.get('elevationFt'), i.get('tempF'), i.get('condition'), i.get('venueId'), i.get('obs'), i.get('wind'))
        a, vaa, ride = air[k], fnum(p.get('VAA')), fnum(p.get('xIndVrtBrk'))
        if a is None or vaa is None or ride is None:
            continue
        p['VAA'] = vaa - (FIT['aP'] + FIT['bP'] * ride) * a['lnP'] - (FIT['aT'] + FIT['bT'] * ride) * a['lnT']
        n += 1
    return n


def build():
    os.makedirs(NEW, exist_ok=True)
    s25 = json.load(open(os.path.join(ROOT, 'data', 'game_weather_2025.json')))
    s26 = json.load(open(os.path.join(ROOT, 'data', 'game_weather_rs.json')))
    for y in G.SEASONS:
        out = os.path.join(NEW, f'season_{y}.pkl')
        if os.path.exists(out):
            print(f'  {y}: cached'); continue
        if y == 2026:
            pk = G.load_2026(); F.new_x_2026(pk); guts = (G.T.LG_WOBA, G.T.WOBA_SCALE)
            n = neutralize(pk, s26, lambda p: (p.get('PitchID') or '').split('_')[0])
        else:
            pk = pickle.load(open(G.T.HIST_PKL.format(year=y) if y != 2025 else G.T.PRIOR_PKL, 'rb')); guts = G.GUTS[y]
            n = neutralize(pk, s25, lambda p: str(int(p['_game_pk'])) if p.get('_game_pk') is not None else '')
        d = G._frame_from_pitches(pk, guts, y)
        del pk; gc.collect()
        old = pd.read_pickle(os.path.join(BASE, f'season_{y}.pkl'))
        d = F.align(d, old, y)
        # The baseline frames were built one step before the feed-temperature guard (4 games in
        # six seasons), so a few hundred rows may differ in movement. More than 0.5% is a real mismatch.
        diff = np.abs(d['ivb'].values.astype('float32') - old['ivb'].values.astype('float32')) > 0.051
        same = float(np.nanmean(diff)) <= 0.005
        print(f'  {y}: rows whose movement differs from the baseline frame: {int(np.nansum(diff))}', flush=True)
        dv = d['vaa_raw'].astype(float) - old['vaa_raw'].astype(float)
        print(f'  {y}: {len(d)} rows aligned, movement identical to the baseline frame: {same}; VAA neutralized on {n} pitches; '
              f'change mean {dv.mean():+.3f} sd {dv.std():.3f} deg', flush=True)
        if not same:
            sys.exit(f'{y}: the movement columns differ from the baseline frame. Not written.')
        d['l_loc'] = old['l_loc'].values
        d.to_pickle(out)
        del d, old; gc.collect()
    F._link(BASE, NEW, F.LINKS)
    F._link(BASE, NEW, [fn for fn in os.listdir(BASE) if fn.startswith('agg_SHIPPED_')])
    json.dump({'SHIPPED': json.load(open(os.path.join(BASE, 'results.json')))['SHIPPED']}, open(os.path.join(NEW, 'results.json'), 'w'))
    print('frames ready in', NEW)


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'build':
        build()
    else:
        G.CACHE = NEW; G.RESULTS = os.path.join(NEW, 'results.json')
        if cmd == 'run':
            spec = os.path.join(NEW, 'spec.json'); json.dump({'NVAA': {}}, open(spec, 'w'))
            G.run(spec, G.PAIRS, [0, 1, 2], None)
        else:
            G.summarize(['NVAA'])
