#!/usr/bin/env python3
"""locplus_shape_split_fit.py — Loc+ surfaces that know the pitch's SHAPE class.

locplus_shape_interaction.py (2026-11-19) showed on the Stuff+ gate frames that
the value of a spot depends on the pitch's shape (held out 10/10; pitcher units
+.019 next-season r, 5/5), and that ONE variable carries about half of it:
induced vertical break for FF, FC, SL, CU, CH and horizontal break for SI.
This is the test in the REAL Loc+ code, at production sample size, with the same
design as locplus_type_split_fit.py:

  surfaces built on ONE FULL SEASON score the pitches of an ADJACENT season
  (10 ordered pairs, 2021-2026), under
    grouped   the shipped group map
    split     every group cut into K shape classes, each with its own surfaces
  and the blend  v(w) = (1 - w) * grouped + w * split,  w in 0.25 .. 1.

Shape classes. The class variable is IVB (inches) for FF, FC, SL, CU, CH and
arm-side HB for SI. The cut points are the season's own pitch-weighted quantiles
inside the group, so a class is RELATIVE ("top third of ride this season") and
the two movement sources (Statcast pfx for 2021-2025, the sheets for 2026) need
no common calibration. Arms:
    u2, u3   class from the pitcher's season MEAN for that pitch type, K = 2, 3
    p3       class from the pitch's own value, K = 3
A pitch with no movement value is left out of every arm, the grouped one too.

Objective: squared error against the actual hitter run value and against the
luck-neutral value in count currency, paired per pitch, per group; pairs won.
This objective cannot be gamed by splitting: a class surface that is only noise
loses on the held-out season.

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/locplus_shape_split_fit.py
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
import locplus_constants_multiseason as base  # noqa: E402
from pipeline.sdplus import make_rv_xrv  # noqa: E402

CACHE = os.path.join(ROOT, 'data', '_loc_shape_split')
OUT = os.path.join(ROOT, 'data', '_loc_shape_split.json')
YEARS = list(range(2021, 2027))
GROUPS = ('FF', 'SI', 'FC', 'SL', 'CU', 'CH')
VAR = {'FF': 'ivb', 'FC': 'ivb', 'SL': 'ivb', 'CU': 'ivb', 'CH': 'ivb', 'SI': 'hb'}
ARMS = {'u2': ('unit', 2), 'u3': ('unit', 3), 'p3': ('pitch', 3)}
WS = (0.25, 0.5, 0.75, 1.0)
UNIT_MIN = 20                 # a pitcher's type mean needs 20 pitches, else the pitch's own value classes it
ORIG_GROUP = dict(lp.GROUP)


def load(y):
    """Season pitches in Loc+ shape with '_ivb' and '_hb' (arm-side positive), '_pt0' = the tag."""
    if y == 2026:
        out = FR.load_season(y)
        for p in out:
            p['_ivb'] = lp.safe_float(p.get('IndVertBrk'))
            h = lp.safe_float(p.get('HorzBrk'))
            p['_hb'] = None if h is None else (h if p.get('Throws') == 'R' else -h)
            p['_pt0'] = p.get('Pitch Type')
        return out
    df = pickle.load(open(os.path.join(ROOT, FR.SEASONS[y]), 'rb'))
    cols = ['pitch_type', 'plate_x', 'plate_z', 'sz_top', 'sz_bot', 'balls', 'strikes', 'description', 'delta_run_exp',
            'estimated_woba_using_speedangle', 'stand', 'p_throws', 'player_name', 'game_date', 'release_speed', 'pfx_x', 'pfx_z']
    out = []
    for r in df[cols].itertuples(index=False):
        d = base.DMAP.get(r.description)
        if d is None or r.pitch_type is None:
            continue
        try:
            b, s = int(r.balls), int(r.strikes)
        except (TypeError, ValueError):
            continue
        if not (0 <= b <= 3 and 0 <= s <= 2):
            continue
        try:
            re = float(r.delta_run_exp)
            if re != re:
                re = None
        except (TypeError, ValueError):
            re = None
        thr = base._s(r.p_throws)
        px, pz = base._f(r.pfx_x), base._f(r.pfx_z)
        out.append({'Pitch Type': base._s(r.pitch_type), '_pt0': base._s(r.pitch_type), 'Bats': base._s(r.stand), 'Throws': thr,
                    'PlateX': base._f(r.plate_x), 'PlateZ': base._f(r.plate_z), 'SzTop': base._f(r.sz_top), 'SzBot': base._f(r.sz_bot),
                    'Count': f'{b}-{s}', 'Description': d, 'RunExp': (None if re is None else -re),
                    'xwOBA': base._f(r.estimated_woba_using_speedangle), 'Pitcher': base._s(r.player_name),
                    'Game Date': str(r.game_date)[:10], 'Velocity': base._f(r.release_speed), '_source': 'MLB', 'Event': None, 'BBType': None,
                    '_ivb': None if pz is None else pz * 12.0,
                    '_hb': None if px is None else (-px * 12.0 if thr == 'R' else px * 12.0)})
    del df
    gc.collect()
    return out


def label(pitches):
    """Attach p['_lab'][arm] = 'GROUP#class' for every arm. Returns the pitches that have a
    class value (the others are dropped from every arm)."""
    keep = []
    unit = defaultdict(lambda: [0.0, 0])
    for p in pitches:
        g = ORIG_GROUP.get(p['_pt0'])
        if g not in VAR:
            continue
        v = p['_ivb'] if VAR[g] == 'ivb' else p['_hb']
        if v is None:
            continue
        p['_g'], p['_v'] = g, v
        u = unit[(p.get('Pitcher'), p['_pt0'])]
        u[0] += v
        u[1] += 1
        keep.append(p)
    by = defaultdict(lambda: {'unit': [], 'pitch': []})
    for p in keep:
        s, n = unit[(p.get('Pitcher'), p['_pt0'])]
        p['_vu'] = s / n if n >= UNIT_MIN else p['_v']
        by[p['_g']]['unit'].append(p['_vu'])
        by[p['_g']]['pitch'].append(p['_v'])
    cuts = {(g, basis, K): np.quantile(np.array(d[basis]), [i / K for i in range(1, K)])
            for g, d in by.items() for basis, K in set(ARMS.values())}
    for p in keep:
        p['_lab'] = {}
        for arm, (basis, K) in ARMS.items():
            c = int(np.searchsorted(cuts[(p['_g'], basis, K)], p['_vu'] if basis == 'unit' else p['_v']))
            p['_lab'][arm] = f"{p['_g']}#{c}"
    return keep


def set_arm(pitches, arm):
    lp.GROUP.clear()
    lp.GROUP.update(ORIG_GROUP)
    if arm == 'g':
        for p in pitches:
            p['Pitch Type'] = p['_pt0']
        return
    K = ARMS[arm][1]
    lp.GROUP.update({f'{g}#{c}': f'{g}#{c}' for g in GROUPS for c in range(K)})
    for p in pitches:
        p['Pitch Type'] = p['_lab'][arm]


def surf_path(y, arm):
    return os.path.join(CACHE, f'S_{arm}_{y}.pkl')


def main():
    os.makedirs(CACHE, exist_ok=True)
    arms = ['g'] + list(ARMS)
    acc = defaultdict(lambda: defaultdict(lambda: np.zeros(3)))     # [(arm, group, target, w)][pair] = n, sum e, sum e^2
    for y in YEARS:
        if all(os.path.exists(surf_path(y, a)) for a in arms):
            continue
        ps = label([p for p in load(y) if lp.is_eligible_baseline(p)])
        for arm in arms:
            if not os.path.exists(surf_path(y, arm)):
                set_arm(ps, arm)
                S = lp.build_surfaces(ps, FR.LG, FR.SCALE)
                pickle.dump(S, open(surf_path(y, arm) + '.tmp', 'wb'))
                os.replace(surf_path(y, arm) + '.tmp', surf_path(y, arm))
                del S
        set_arm(ps, 'g')
        print(f'{y}: {len(ps)} classed baseline pitches, surfaces ready', flush=True)
        del ps
        gc.collect()
    for yb in YEARS:
        # one season in memory at a time (8 GB machine); the labels are a function of the season alone
        test = label([p for p in load(yb) if lp.is_eligible_baseline(p)])
        set_arm(test, 'g')
        rv_x = make_rv_xrv(FR.LG, FR.SCALE, count_offsets=lp.build_bip_count_offsets(test, FR.LG, FR.SCALE))
        y_rv = np.array([(lambda v: np.nan if v is None else -v)(lp.safe_float(p.get('RunExp'))) for p in test], float)
        y_x = np.array([(lambda v: np.nan if v is None else v)(rv_x(p)) for p in test], float)
        gcode = np.array([p['_g'] for p in test])
        for ya in (yb - 1, yb + 1):
            if ya not in YEARS:
                continue
            V = {}
            for arm in arms:
                set_arm(test, arm)
                S = pickle.load(open(surf_path(ya, arm), 'rb'))
                V[arm] = np.array([(lambda v: np.nan if v is None else v)(lp.score_pitch(p, S)) for p in test], float)
                del S
            set_arm(test, 'g')
            for arm in ARMS:
                for tg, yv in (('rv', y_rv), ('x', y_x)):
                    ok = np.isfinite(yv) & np.isfinite(V['g']) & np.isfinite(V[arm])
                    e0 = (yv - V['g']) ** 2
                    for w in WS:
                        e = (yv - ((1 - w) * V['g'] + w * V[arm])) ** 2 - e0
                        for g in ('ALL',) + GROUPS:
                            m = ok if g == 'ALL' else (ok & (gcode == g))
                            acc[(arm, g, tg, w)][(ya, yb)] += np.array([m.sum(), e[m].sum(), (e[m] ** 2).sum()])
            print(f'  {ya} -> {yb} scored', flush=True)
            gc.collect()
        del test
        gc.collect()
    out = {}
    for tg, lab in (('x', 'luck-neutral run value, count currency'), ('rv', 'actual run value')):
        for arm in ARMS:
            print(f'\n{lab} | arm {arm} ({ARMS[arm][0]} class, K {ARMS[arm][1]}): squared error x 1e4, blend minus grouped (negative = the classes help); z; pairs won')
            print(f'{"group":>6s}{"n":>10s}' + ''.join(f'{"w=" + str(w):>26s}' for w in WS))
            for g in ('ALL',) + GROUPS:
                row = None
                for w in WS:
                    per = acc[(arm, g, tg, w)]
                    t = sum(per.values())
                    n = t[0]
                    e = t[1] / n
                    se = math.sqrt(max(t[2] / n - e * e, 0.0) / n)
                    wins = sum(1 for v in per.values() if v[0] and v[1] / v[0] < 0)
                    out[f'{tg}:{arm}:{g}:{w}'] = {'n': int(n), 'e': e, 'se': se, 'wins': wins, 'pairs': len(per)}
                    row = (row or f'{g:>6s}{int(n):>10d}') + f'{e * 1e4:>+12.3f} ({(e / se if se else float("nan")):>+5.1f}) {wins:>2d}/{len(per)}'
                print(row)
    tmp = OUT + '.tmp'
    json.dump(out, open(tmp, 'w'), indent=1)
    os.replace(tmp, OUT)
    print(f'\nwrote {OUT}')


if __name__ == '__main__':
    main()
