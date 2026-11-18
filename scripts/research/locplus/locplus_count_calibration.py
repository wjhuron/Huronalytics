#!/usr/bin/env python3
"""locplus_count_calibration.py — are the Loc+ count terms right, PITCH by pitch?

Loc+ prices a whiff, a foul, a called strike and a ball in count-specific run
value, but a ball in play in wOBA above average (the count anchor is off), and
its foul surface has no count term. Both were judged only at the pitcher level.
This is the pitch-level, out-of-sample check (the 2026-09-19 calib protocol):
surfaces built on even dates score odd dates, and the reverse.

Arms (same surfaces, one term changed):
  ship    pipeline.locplus as shipped
  anch    BIP_COUNT_ANCHOR on: the ball-in-play value takes the count's
          run-expectancy offset, so all five branches share one currency
  foulc   foul probability scaled by the count's league foul-per-swing rate
          over the overall rate (a level term, as the swing and whiff count
          priors are), capped so whiff + foul <= 1
  both    anch + foulc

Yardstick: squared error against the pitch's ACTUAL hitter run value (-RunExp).
Actual run value is in run-expectancy currency for every outcome, so it can
judge a currency term; the luck-neutral target cannot (its contact branch is
the unanchored quantity itself). Reported: arm minus ship, per pitch x 1e4,
with a paired SE, by season, and by strikes and by count. Also the mean
expected against the mean actual value by count (calibration in the mean).

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/locplus_count_calibration.py
"""
import gc
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline.locplus as lp  # noqa: E402
import locplus_fullseason_replicate as FR  # noqa: E402

OUT = os.path.join(ROOT, 'data', '_loc_count_calibration.json')
ARMS = ('anch', 'foulc', 'both')
FOUL_DESC = {'Foul'}


def foul_mult(train):
    sw, fl = defaultdict(int), defaultdict(int)
    for p in train:
        if p.get('Description') in lp.SWING_DESC:
            c = lp.get_count(p)
            sw[c] += 1
            if p.get('Description') in FOUL_DESC:
                fl[c] += 1
    tot = sum(fl.values()) / max(sum(sw.values()), 1)
    return {c: (fl[c] / sw[c]) / tot for c in sw if sw[c] >= 200 and tot > 0}


def score(p, S, anchor_off, fmult):
    """lp.score_pitch with an optional count anchor table and foul multiplier."""
    key = (lp.group_of(p), p.get('Bats'), p.get('Throws'))
    if key not in S['WH']:
        return None
    c = lp.get_count(p)
    px = lp.safe_float(p.get('PlateX'))
    zn = lp._znorm(p)
    if c is None or px is None or zn is None:
        return None
    i, j = lp._xbin(px), lp._zbin(zn)
    psw = S['SW'][key][c][i][j]
    pwh = S['WH'][key][c][i][j]
    pfl = S['FL'][key][i][j]
    if fmult is not None:
        pfl = min(pfl * fmult.get(c, 1.0), max(0.0, 1.0 - pwh))
    pbip = max(0.0, 1.0 - pwh - pfl)
    vbip = S['XW'][key][i][j] + S['XWOFF'].get(c, 0.0) + (anchor_off.get(c, 0.0) if anchor_off else 0.0)
    pcs = S['PCS'][p['Bats']][c][i][j]
    RV = S['RV']
    sv = pwh * RV['whiff'].get(c, 0.0) + pfl * RV['foul'].get(c, 0.0) + pbip * vbip
    tv = pcs * RV['cs'].get(c, 0.0) + (1 - pcs) * RV['ball'].get(c, 0.0)
    return psw * sv + (1 - psw) * tv


def main():
    acc = defaultdict(lambda: defaultdict(lambda: np.zeros(3)))   # [(arm, slice)][yr] = n, sum e, sum e^2
    cal = defaultdict(lambda: np.zeros(6))                        # [count] n, actual, ship, anch, foulc, both
    for yr in range(2021, 2027):
        pitches = FR.load_season(yr)
        base_p = [p for p in pitches if lp.is_eligible_baseline(p)]
        del pitches
        dates = sorted({p['Game Date'] for p in base_p if p['Game Date']})
        par = {d: i % 2 for i, d in enumerate(dates)}
        for fold in (0, 1):
            train = [p for p in base_p if par.get(p['Game Date']) != fold]
            S = lp.build_surfaces(train, FR.LG, FR.SCALE)
            off = lp.build_bip_count_offsets(train, FR.LG, FR.SCALE)
            fm = foul_mult(train)
            for p in base_p:
                if par.get(p['Game Date']) != fold:
                    continue
                re = lp.safe_float(p.get('RunExp'))
                v0 = lp.score_pitch(p, S)
                if re is None or v0 is None:
                    continue
                y = -re
                c = lp.get_count(p)
                vs = {'anch': score(p, S, off, None), 'foulc': score(p, S, None, fm), 'both': score(p, S, off, fm)}
                e0 = (y - v0) ** 2
                cal[c] += np.array([1.0, y, v0, vs['anch'], vs['foulc'], vs['both']])
                for a in ARMS:
                    e = (y - vs[a]) ** 2 - e0          # < 0: the arm fits better
                    rec = np.array([1.0, e, e * e])
                    for sl in ('all', f's{c[1]}' if isinstance(c, tuple) else f's{str(c)[-1]}', f'c{c}'):
                        acc[(a, sl)][yr] += rec
            del train, S
            gc.collect()
        print(f'{yr}: done ({len(base_p)} baseline pitches)', flush=True)
        del base_p
        gc.collect()
    out = {}
    slices = sorted({k[1] for k in acc}, key=lambda s: (s[0] != 'a', s[0] != 's', s))
    print('\narm minus shipped, squared error per pitch x 1e4 (negative = the arm fits better); z; seasons the arm wins')
    print(f'{"slice":>10s}' + ''.join(f'{a:>26s}' for a in ARMS))
    for sl in slices:
        row = f'{sl:>10s}'
        for a in ARMS:
            per = acc[(a, sl)]
            t = sum(per.values())
            n = t[0]
            e = t[1] / n
            se = math.sqrt(max(t[2] / n - e * e, 0.0) / n)
            wins = sum(1 for v in per.values() if v[0] and v[1] / v[0] < 0)
            out[f'{a}:{sl}'] = {'n': int(n), 'e': e, 'se': se, 'wins': wins, 'seasons': len(per)}
            row += f'{e * 1e4:>+10.3f} ({(e / se if se else float("nan")):>+6.1f}) {wins}/{len(per)}'
        print(row)
    print('\nmean value by count, runs per 100 pitches (hitter-positive): actual, then each arm minus actual')
    print(f'{"count":>8s}{"n":>9s}{"actual":>9s}{"ship":>9s}{"anch":>9s}{"foulc":>9s}{"both":>9s}')
    for c in sorted(cal, key=str):
        t = cal[c]
        n = t[0]
        out[f'cal:{c}'] = {'n': int(n), 'actual': t[1] / n, 'ship': t[2] / n, 'anch': t[3] / n,
                           'foulc': t[4] / n, 'both': t[5] / n}
        print(f'{str(c):>8s}{int(n):>9d}{100 * t[1] / n:>+9.2f}' + ''.join(f'{100 * (t[k] - t[1]) / n:>+9.2f}' for k in (2, 3, 4, 5)))
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
