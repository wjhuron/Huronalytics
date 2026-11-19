#!/usr/bin/env python3
"""locplus_type_split_fit.py — should sweepers, splitters and knuckle curves have
their own Loc+ surfaces?

Shipped Loc+ scores ST/SV on the slider surfaces, FS/KN/SC on the changeup
surfaces and KC on the curveball surfaces. The only split test (ST, 2026-08-14)
ran at the pitcher level on quarter-season surfaces. This is the held-out,
pitch-level test at production sample size:

  surfaces built on ONE FULL SEASON score the pitches of an ADJACENT season
  (10 ordered pairs, 2021-2026), under
    grouped   the shipped GROUP map
    split     ST, FS and KC as groups of their own
  and the blend  v(w) = (1 - w) * grouped + w * split,  w in 0..1 by 0.25.

w is the partial-pooling strength: 0 is shipped, 1 is a full split. Squared
error against the pitch's actual hitter run value (-RunExp) and against the
luck-neutral value (xwOBA on contact), per pitch type. This objective cannot be
gamed by pooling: a surface that fits another pitch type loses on held-out
pitches of this one. Paired SE per pitch; pairs won.

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/locplus_type_split_fit.py
"""
import gc
import json
import math
import os
import pickle
import sys
from collections import defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline.locplus as lp  # noqa: E402
import locplus_fullseason_replicate as FR  # noqa: E402
from pipeline.sdplus import make_rv_xrv  # noqa: E402

CACHE = os.path.join(ROOT, 'data', '_loc_type_split')
OUT = os.path.join(ROOT, 'data', '_loc_type_split.json')
SPLIT = {'ST': 'ST', 'FS': 'FS', 'KC': 'KC'}
TYPES = ('ST', 'SL', 'SV', 'FS', 'CH', 'KC', 'CU')
WS = (0.0, 0.25, 0.5, 0.75, 1.0)
YEARS = list(range(2021, 2027))


def surf_path(y, arm):
    return os.path.join(CACHE, f'S_{arm}_{y}.pkl')


def build_all():
    os.makedirs(CACHE, exist_ok=True)
    lp.SHAPE_ON = False      # the test reads score_pitch (group surfaces); the class bundle is not needed here
    orig = dict(lp.GROUP)
    for y in YEARS:
        if all(os.path.exists(surf_path(y, a)) for a in ('g', 's')):
            continue
        base_p = [p for p in FR.load_season(y) if lp.is_eligible_baseline(p)]
        for arm in ('g', 's'):
            lp.GROUP.clear()
            lp.GROUP.update(orig)
            if arm == 's':
                lp.GROUP.update(SPLIT)
            S = lp.build_surfaces(base_p, FR.LG, FR.SCALE)
            pickle.dump(S, open(surf_path(y, arm), 'wb'))
        lp.GROUP.clear()
        lp.GROUP.update(orig)
        print(f'{y}: surfaces built ({len(base_p)} baseline pitches)', flush=True)
        del base_p
        gc.collect()


def main():
    build_all()
    orig = dict(lp.GROUP)
    acc = defaultdict(lambda: defaultdict(lambda: np.zeros(3)))   # [(type, target, w)][pair]
    for yb in YEARS:
        trains = [ya for ya in (yb - 1, yb + 1) if ya in YEARS]
        # 2026-11-19: score_pitch is in count currency since the Loc+ release, so the luck-neutral
        # target takes the test season's own ball-in-play count offsets (it was unanchored before).
        allp = [p for p in FR.load_season(yb) if lp.is_eligible_baseline(p)]
        rv_x = make_rv_xrv(FR.LG, FR.SCALE, count_offsets=lp.build_bip_count_offsets(allp, FR.LG, FR.SCALE))
        test = [p for p in allp if p.get('Pitch Type') in TYPES]
        del allp
        for ya in trains:
            Sg = pickle.load(open(surf_path(ya, 'g'), 'rb'))
            Ss = pickle.load(open(surf_path(ya, 's'), 'rb'))
            for p in test:
                lp.GROUP.clear(); lp.GROUP.update(orig)
                vg = lp.score_pitch(p, Sg)
                lp.GROUP.update(SPLIT)
                vs = lp.score_pitch(p, Ss)
                if vg is None or vs is None:
                    continue
                re = lp.safe_float(p.get('RunExp'))
                x = rv_x(p)
                pt = p['Pitch Type']
                for tg, y in (('rv', -re if re is not None else None), ('x', x)):
                    if y is None:
                        continue
                    e0 = (y - vg) ** 2
                    for w in WS[1:]:
                        e = (y - ((1 - w) * vg + w * vs)) ** 2 - e0
                        acc[(pt, tg, w)][(ya, yb)] += np.array([1.0, e, e * e])
            lp.GROUP.clear(); lp.GROUP.update(orig)
            del Sg, Ss
        print(f'test {yb}: scored {len(test)} pitches against {trains}', flush=True)
        del test
        gc.collect()
    out = {}
    for tg, lab in (('rv', 'actual run value'), ('x', 'luck-neutral run value')):
        print(f'\n{lab}: squared error per pitch x 1e4, blend minus grouped (negative = the split helps); z; pairs won')
        print(f'{"type":>6s}{"n":>9s}' + ''.join(f'{"w=" + str(w):>24s}' for w in WS[1:]))
        for pt in TYPES:
            row = None
            for w in WS[1:]:
                per = acc.get((pt, tg, w))
                if not per:
                    continue
                t = sum(per.values())
                n = t[0]
                e = t[1] / n
                se = math.sqrt(max(t[2] / n - e * e, 0.0) / n)
                wins = sum(1 for v in per.values() if v[0] and v[1] / v[0] < 0)
                out[f'{tg}:{pt}:{w}'] = {'n': int(n), 'e': e, 'se': se, 'wins': wins, 'pairs': len(per)}
                row = (row or f'{pt:>6s}{int(n):>9d}') + f'{e * 1e4:>+10.3f} ({(e / se if se else float("nan")):>+5.1f}) {wins:>2d}/{len(per)}'
            if row:
                print(row)
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
