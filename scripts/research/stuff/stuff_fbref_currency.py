#!/usr/bin/env python3
"""stuff_fbref_currency.py - the raw-vs-adjusted fastball reference gap (2026-09-24).

Until v17, train_stuff.build_df built the primary-fastball reference for
ivb_diff / hb_diff from RAW IndVertBrk/HorzBrk while the pitch side read the
density-adjusted xIndVrtBrk/xHorzBrk (since 2026-07-02). So production's diff
was

    ivb_adj(pitch) - ivb_raw(ref)  =  [ivb_adj(pitch) - ivb_adj(ref)]  +  offset
    offset = ivb_adj(ref) - ivb_raw(ref)

and the same for hb (hand-normalized). stuff_gate_v2.prepare() builds the
bracketed, consistent diff from the adjusted frame columns, so the gate
scored the consistent feature all along. This script writes the per-pitcher
offset for every gate season, with production's reference rule (most-thrown
FF/SI; FC only for FC_ANCHOR_PITCHERS or a pitcher with neither), so the
gate can rebuild production's pre-v17 mixed feature as a variant
(ivb_diff_rawref / hb_diff_rawref) without a frame rebuild.

    python3 scripts/research/stuff/stuff_fbref_currency.py

Writes data/_gate_v2/fbref_offsets.json: {season: {"pitcher|throws": [off_ivb, off_hb]}}.
2026 is limited to the dates the gate's season_2026.pkl frame holds.
"""
import json
import os
import pickle
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'stuff_plus'))
import train_stuff as T  # noqa: E402

CACHE = os.path.join(ROOT, 'data', '_gate_v2')
OUT = os.path.join(CACHE, 'fbref_offsets.json')
SEASONS = (2021, 2022, 2023, 2024, 2025, 2026)


def season_pitches(y):
    if y == 2026:
        frame = pd.read_pickle(os.path.join(CACHE, 'season_2026.pkl'))
        last = str(frame['date'].astype(str).max())[:10]
        del frame
        allp = pickle.load(open(os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl'), 'rb'))
        # the gate's load_2026 rule: MLB source rows, no eephus pitchers
        ep = {(p.get('Pitcher'), p.get('PTeam')) for p in allp if p.get('Pitch Type') == 'EP'}
        out = [p for p in allp if p.get('_source') == 'MLB'
               and (p.get('Pitcher'), p.get('PTeam')) not in ep
               and str(p.get('Game Date'))[:10] <= last]
        print(f'  2026: {len(out)} MLB pitches through {last} (the gate frame end)')
        return out
    path = T.PRIOR_PKL if y == 2025 else T.HIST_PKL.format(year=y)
    return pickle.load(open(path, 'rb'))


def offsets(pitches):
    """Per (pitcher, throws): adjusted minus raw reference movement, the
    reference being production's primary fastball. Pitches enter the
    reference only when all four movement values exist, so both means run
    over the same pitches."""
    acc = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0]))
    for p in pitches:
        pt, thr = p.get('Pitch Type'), p.get('Throws')
        if pt not in T.FB_TYPES or thr not in ('L', 'R'):
            continue
        v = T.sf(p.get('Velocity'))
        iv, hb = T.sf(p.get('IndVertBrk')), T.sf(p.get('HorzBrk'))
        xiv, xhb = T.sf(p.get('xIndVrtBrk')), T.sf(p.get('xHorzBrk'))
        if None in (v, iv, hb, xiv, xhb):
            continue
        s = 1.0 if thr == 'R' else -1.0
        a = acc[(p.get('Pitcher'), thr)][pt]
        a[0] += iv; a[1] += hb * s; a[2] += xiv; a[3] += xhb * s; a[4] += 1
    out = {}
    for (pit, thr), bt in acc.items():
        if pit in T.FC_ANCHOR_PITCHERS and 'FC' in bt:
            cand = {'FC': bt['FC']}
        else:
            cand = {pt: b for pt, b in bt.items() if pt in ('FF', 'SI')} or bt
        b = cand[max(cand, key=lambda pt: cand[pt][4])]
        n = b[4]
        out[f'{pit}|{thr}'] = [round((b[2] - b[0]) / n, 4), round((b[3] - b[1]) / n, 4)]
    return out


def main():
    res = {}
    for y in SEASONS:
        off = offsets(season_pitches(y))
        a = np.array(list(off.values()))
        print(f'  {y}: {len(off)} pitchers | offset IVB mean {a[:, 0].mean():+.3f} sd {a[:, 0].std():.3f} '
              f'max |{np.abs(a[:, 0]).max():.2f}| | HB mean {a[:, 1].mean():+.3f} sd {a[:, 1].std():.3f} '
              f'max |{np.abs(a[:, 1]).max():.2f}|', flush=True)
        res[str(y)] = off
    tmp = OUT + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(res, f)
    os.replace(tmp, OUT)
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
