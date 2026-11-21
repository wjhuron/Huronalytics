"""wx_gate_frames.py -- Stuff+ gate (v2) frames on the neutral-movement columns.

RESEARCH ONLY. The gate caches one frame per season (data/_gate_v2/season_{y}.pkl,
train_stuff.build_df output). This builds the same frames from the same pitches with
xIndVrtBrk / xHorzBrk replaced by the nm1 model, into a SEPARATE cache folder
(data/_gate_v2_nm1/), and links the shipped baseline's aggregates and lookup files
there. The gate then runs with its cache pointed at that folder, so the arm NEUTRAL
(the shipped design, new movement) pairs against the cached SHIPPED aggregates.

Each new frame must align row for row with the shipped frame (pitcher and velocity),
or the script stops: a paired comparison on different rows is not a comparison.

    build     write the frames (2021-2025 from --train-dir pickles, 2026 from the pitch cache)
    run       gate run of NEUTRAL, seeds 0,1,2
    summary   the gate summary for NEUTRAL

MAIN_ROOT (env) = the checkout that holds data/ and the gate; default: this repo.
"""
import gc
import importlib.util
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
THIS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
MAIN = os.environ.get('MAIN_ROOT', THIS_ROOT)
sys.path.insert(0, MAIN)
sys.path.insert(0, os.path.join(MAIN, 'scripts', 'research', 'stuff'))
import stuff_gate_v2 as G  # noqa: E402

_spec = importlib.util.spec_from_file_location('neutral_move_nm1', os.path.join(THIS_ROOT, 'pipeline', 'neutral_move.py'))
NM = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(NM)

OLD = G.CACHE
NEW = os.path.join(MAIN, 'data', '_gate_v2_nm1')
CTRL = os.path.join(MAIN, 'data', '_gate_v2_nm1_ctrl')
LINKS = ('pitcher_height.json', 'pitcher_hand.json', 'pitcher_role.json', 'fbref_offsets.json')


def new_x_2026(p26):
    side = json.load(open(os.path.join(THIS_ROOT, 'data', 'game_weather_rs.json')))
    air, modes = {}, {}
    for p in p26:
        pk = (p.get('PitchID') or '').split('_')[0]
        if pk not in air:
            i = side.get(pk) or {}
            air[pk] = NM.game_air(i.get('elevationFt'), i.get('tempF'), i.get('condition'), i.get('venueId'),
                                  i.get('obs'), i.get('wind'))
        try:
            ivb = None if p.get('IndVertBrk') in (None, '') else float(p['IndVertBrk'])
            hb = None if p.get('HorzBrk') in (None, '') else float(p['HorzBrk'])
            v = None if p.get('Velocity') in (None, '') else float(p['Velocity'])
        except (TypeError, ValueError):
            continue
        if ivb is None and hb is None:
            continue
        xi, xh, mode = NM.neutral_movement(ivb, hb, p.get('Throws'), p.get('RTilt'), v, air[pk])
        modes[mode] = modes.get(mode, 0) + 1
        if xi is not None:
            p['xIndVrtBrk'] = round(xi, 1)
        if xh is not None:
            p['xHorzBrk'] = round(xh, 1)
    print(f'  2026 neutral movement modes: {modes}', flush=True)


def align(d, old, y, max_skip=50):
    """Keep the rows of the rebuilt frame that pair, in order, with the shipped frame on
    (pitcher, velocity). The pitch cache can gain a few rows after a frame was stored;
    those rows are dropped here and counted. Stops if the shipped frame has a row the
    rebuilt one lacks, or if more than max_skip rows must go."""
    po, vo = old['pitcher'].values, old['velocity'].values.astype('float32')
    pn, vn = d['pitcher'].values, d['velocity'].values.astype('float32')
    same = lambda i, j: po[i] == pn[j] and (vo[i] == vn[j] or (np.isnan(vo[i]) and np.isnan(vn[j])))
    if len(po) == len(pn) and all(same(i, i) for i in range(0, len(po), 997)) and (po == pn).all():
        return d
    keep, j, skipped = [], 0, 0
    for i in range(len(po)):
        while j < len(pn) and not same(i, j):
            j += 1; skipped += 1
            if skipped > max_skip:
                sys.exit(f'{y}: more than {max_skip} rows of the rebuilt frame do not pair with the shipped frame. Not written.')
        if j >= len(pn):
            sys.exit(f'{y}: the shipped frame has rows the rebuilt frame lacks (at row {i}). Not written.')
        keep.append(j); j += 1
    print(f'  {y}: dropped {len(pn) - len(keep)} rows of the rebuilt frame that the shipped frame does not hold', flush=True)
    return d.iloc[keep].reset_index(drop=True)


def _link(src_dir, dst_dir, names):
    for fn in names:
        dst = os.path.join(dst_dir, fn)
        if os.path.islink(dst) or os.path.exists(dst):
            os.remove(dst)
        os.symlink(os.path.join(src_dir, fn), dst)


def build(train_dir):
    """NEW: every season on the nm1 columns. CTRL: the shipped frames for 2021-2025 and a
    2026 frame rebuilt from TODAY's pitch cache with the shipped columns. The stored 2026
    frame cannot be the control: the cache gained and changed rows after it was written
    (2026-11-20: 2 more rows, about 900 shifted), so the control and the new arm are both
    built from the same 2026 pitch list and differ in the movement columns only."""
    os.makedirs(NEW, exist_ok=True); os.makedirs(CTRL, exist_ok=True)
    for y in G.SEASONS:
        out = os.path.join(NEW, f'season_{y}.pkl')
        if os.path.exists(out) and (y != 2026 or os.path.exists(os.path.join(CTRL, 'season_2026.pkl'))):
            print(f'  {y}: cached'); continue
        if y == 2026:
            pk = G.load_2026(); guts = (G.T.LG_WOBA, G.T.WOBA_SCALE)
            old = G._frame_from_pitches(pk, guts, y)
            old.to_pickle(os.path.join(CTRL, 'season_2026.pkl'))
            new_x_2026(pk)
            d = G._frame_from_pitches(pk, guts, y)
            # a pitch with raw movement and a blank shipped x value enters the new frame only
            d = align(d, old, y)
        else:
            pk = pickle.load(open(os.path.join(train_dir, f'_pitches{y}_training.pkl'), 'rb')); guts = G.GUTS[y]
            d = G._frame_from_pitches(pk, guts, y)
            old = pd.read_pickle(os.path.join(OLD, f'season_{y}.pkl'))
            d = align(d, old, y)
            d['l_loc'] = old['l_loc'].values
        del pk; gc.collect()
        dv = (d['ivb'].astype(float) - old['ivb'].astype(float)); dh = (d['hb'].astype(float) - old['hb'].astype(float))
        print(f'  {y}: {len(d)} rows aligned; ivb change mean {dv.mean():+.2f} sd {dv.std():.2f}, hb change mean {dh.mean():+.2f} sd {dh.std():.2f}', flush=True)
        d.to_pickle(out)
        del d, old; gc.collect()
    _link(OLD, NEW, LINKS); _link(OLD, CTRL, LINKS)
    _link(OLD, CTRL, [f'season_{y}.pkl' for y in G.SEASONS if y != 2026])
    for d_ in (NEW, CTRL):
        if not os.path.exists(os.path.join(d_, 'results.json')):
            json.dump({}, open(os.path.join(d_, 'results.json'), 'w'))
    print('frames ready:', NEW, 'and', CTRL)


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'build':
        build(sys.argv[2])
    elif cmd == 'ctrl':
        # the shipped design on the control frames; its aggregates become the baseline of NEW
        G.CACHE = CTRL; G.RESULTS = os.path.join(CTRL, 'results.json')
        spec = os.path.join(CTRL, 'spec_empty.json'); json.dump({}, open(spec, 'w'))
        G.run(spec, G.PAIRS, [0, 1, 2], None)
        _link(CTRL, NEW, [fn for fn in os.listdir(CTRL) if fn.startswith('agg_SHIPPED_')])
        res = json.load(open(os.path.join(NEW, 'results.json')))
        res['SHIPPED'] = json.load(open(G.RESULTS))['SHIPPED']
        json.dump(res, open(os.path.join(NEW, 'results.json'), 'w'))
        ref = json.load(open(os.path.join(OLD, 'results.json')))['SHIPPED']
        print('control against the stored baseline, nxt_r by pair (seed 0): ' + '  '.join(
            f'{y}: {res["SHIPPED"][y]["0"]["nxt_r"]:.4f} vs {ref[y]["0"]["nxt_r"]:.4f}' for y in sorted(ref)))
    else:
        G.CACHE = NEW; G.RESULTS = os.path.join(NEW, 'results.json')
        if cmd == 'run':
            spec = os.path.join(NEW, 'spec_neutral.json')
            json.dump({'NEUTRAL': {}}, open(spec, 'w'))
            G.run(spec, G.PAIRS, [0, 1, 2], None)
        elif cmd == 'summary':
            G.summarize(['NEUTRAL'])
