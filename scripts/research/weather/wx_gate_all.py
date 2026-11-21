"""wx_gate_all.py -- Stuff+ gate (v2) with ALL six weather-sensitive inputs neutral.

RESEARCH ONLY. Stuff+ reads velocity, spin rate, extension, arm angle and the approach
angle as tracked. Since 2026-11-21 the site, the cards and the reports show the neutral
values (pipeline/neutral_move.py, model wm1). This arm answers one question: does Stuff+
forecast as well when it reads the neutral values too? The frames are rebuilt from the
pitch lists with the six metrics replaced; everything else is the installed baseline's,
row for row. Frames go to data/_gate_v2_wm1/; the installed SHIPPED aggregates are linked.

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
NEW = os.path.join(ROOT, 'data', '_gate_v2_wm1')


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def neutralize(pk, store, key):
    """Replace the six weather-sensitive metrics of every pitch with the neutral value, in
    place, with the shipped model (pipeline/neutral_move.py, wm1). The plain key is written
    and any `<column>_raw` key removed, so train_stuff's `_tracked` reader sees the neutral
    value: this arm is Stuff+ as it would be if it read what the site shows."""
    air, n = {}, 0
    for p in pk:
        k = key(p)
        if k not in air:
            i = store.get(k) or {}
            air[k] = NM.game_air(i.get('elevationFt'), i.get('tempF'), i.get('condition'), i.get('venueId'), i.get('obs'), i.get('wind'))
        raw = {c: fnum(NM.raw_metric(p, c)) for c in NM.METRIC_COLUMNS}
        out, mode = NM.neutral_metrics(raw, p.get('Throws'), fnum(p.get('xIndVrtBrk')), fnum(p.get('xHorzBrk')), air[k])
        for c, (xcol, _) in NM.METRIC_COLUMNS.items():
            p.pop(c + NM.RAW_SUFFIX, None)
            if raw[c] is not None:
                # an approach angle with no neutral movement keeps its tracked value here:
                # a blank would drop the pitch from the frame and break the row alignment
                p[c] = out[xcol] if out[xcol] is not None else raw[c]
        n += mode == 'full'
    return n


def align(d, old, y, max_skip=50, tol=0.75):
    """wx_gate_frames.align pairs rows on (pitcher, velocity), and this arm CHANGES velocity
    (by 0.4 mph at most on the 2026 sheets). Same walk, with the velocity test loosened to
    `tol` mph. Rows are in the same order in both frames, so the pitcher test does the work."""
    po, vo = old['pitcher'].values, old['velocity'].values.astype('float32')
    pn, vn = d['pitcher'].values, d['velocity'].values.astype('float32')
    same = lambda i, j: po[i] == pn[j] and (abs(vo[i] - vn[j]) <= tol or (np.isnan(vo[i]) and np.isnan(vn[j])))
    keep, j, skipped = [], 0, 0
    for i in range(len(po)):
        while j < len(pn) and not same(i, j):
            j += 1; skipped += 1
            if skipped > max_skip:
                sys.exit(f'{y}: more than {max_skip} rows of the rebuilt frame do not pair with the shipped frame (row {i}). Not written.')
        if j >= len(pn):
            sys.exit(f'{y}: the shipped frame has rows the rebuilt frame lacks (at row {i}). Not written.')
        keep.append(j); j += 1
    print(f'  {y}: dropped {len(pn) - len(keep)} rows of the rebuilt frame that the shipped frame does not hold', flush=True)
    return d.iloc[keep].reset_index(drop=True)


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
        d = align(d, old, y)
        # The baseline frames were built one step before the feed-temperature guard (4 games in
        # six seasons), so a few hundred rows may differ in movement. More than 0.5% is a real mismatch.
        diff = np.abs(d['ivb'].values.astype('float32') - old['ivb'].values.astype('float32')) > 0.051
        same = float(np.nanmean(diff)) <= 0.005
        print(f'  {y}: rows whose movement differs from the baseline frame: {int(np.nansum(diff))}', flush=True)
        dv = d['vaa_raw'].astype(float) - old['vaa_raw'].astype(float)
        dvel = d['velocity'].astype(float) - old['velocity'].astype(float)
        print(f'  {y}: velocity change mean {dvel.mean():+.3f} sd {dvel.std():.3f} max abs {dvel.abs().max():.2f} mph', flush=True)
        print(f'  {y}: {len(d)} rows aligned, movement identical to the baseline frame: {same}; six metrics neutral on {n} pitches; '
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
            spec = os.path.join(NEW, 'spec.json'); json.dump({'WM1': {}}, open(spec, 'w'))
            G.run(spec, G.PAIRS, [0, 1, 2], None)
        else:
            G.summarize(['WM1'])
