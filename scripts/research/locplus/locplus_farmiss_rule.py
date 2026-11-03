#!/usr/bin/env python3
"""locplus_farmiss_rule.py — should a FAR MISS be scored as a certain take?
(2026-09-19)

Loc+ clamps a pitch outside its grid (|PlateX| > 18 in, znorm outside
[-0.6, 1.6]) into the edge cell. In two-strike counts the edge cells are
chase locations, so a pitch three feet outside can grade 149 (Lord CH,
PitchID 823005_052_04) when nobody swings at it and its real value is the
count's ball value. The 2026-08-30 bounds sweep rejected a WIDER GRID at the
pitcher level. This script tests a different mechanism, a scoring RULE:

    beyond a cutoff, ExpRV = RV['ball'][count]        (a certain take)

Three cutoffs, swept separately and then together:
    FARMISS_X_IN   |PlateX| in inches from the plate centre
    FARMISS_Z_LO   zone-heights BELOW the bottom of the zone (znorm < -lo)
    FARMISS_Z_HI   zone-heights ABOVE the top of the zone   (znorm > 1 + hi)
Mode A scores with the rule on the shipped surfaces. Mode B also drops the
far pitches from the surface BUILD, so an edge cell describes only pitches
that are still scored from it; the count run values stay on the full
baseline in both modes (a far miss IS a ball, it must keep pricing balls).

Two objectives, because they answer different questions (failure log,
2026-09-02: cell fit decides a table, the pitcher objective decides a grade):

  calib   PITCH level, out of sample. Surfaces on even dates score odd dates
          and the reverse. Per distance band: swing rate, mean actual hitter
          RV, mean shipped ExpRV, mean ball value, and the paired squared-
          error difference (ball rule minus shipped). The cutoff is where the
          rule starts to beat the clamped cell; that crossing is an interior
          optimum of total squared error, and it cannot be gamed by pulling
          the cutoff inward, because inside the crossing the rule is WORSE.
  run     PITCHER level, through locplus_target_audit's protocol and tables
          (own cache, data/_loc_farmiss/, with its own `shipped` built in the
          same pass so 2026 pairs on the same pickle). Decider as declared
          there on 2026-09-17: next season, Stuff+ partialled, rendered unit,
          mean of xRV and actual RV, and no loss on the four Stuff+-partialled
          columns. CAUTION: this one CAN be gamed inward. Cutoff 0 turns Loc+
          into the count mix, which predicts well and holds no location. Read
          d|r(L,stuff)| beside every win, and never take a pitcher-level win
          at a cutoff the calib table says is wrong.

Usage (repo root):
  python3 scripts/research/locplus/locplus_farmiss_rule.py calib [--seasons 2021,2022]
  python3 scripts/research/locplus/locplus_farmiss_rule.py run --sweep x|lo|hi [--mode A|B|AB]
  python3 scripts/research/locplus/locplus_farmiss_rule.py run --combo name=x:lo:hi[:mode]
  python3 scripts/research/locplus/locplus_farmiss_rule.py run-cut --combo fmA_x24=24:-:- [--fracs 0.25,0.5,0.75]
  python3 scripts/research/locplus/locplus_farmiss_rule.py summary [--cut 0.5]
"""
import argparse
import gc
import json
import math
import os
import sys
import time
from collections import defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline.locplus as lp                           # noqa: E402
import locplus_fullseason_replicate as FR               # noqa: E402
import locplus_target_audit as TA                       # noqa: E402

CACHE = os.path.join(ROOT, 'data', '_loc_farmiss')
TA.CACHE = CACHE
TA.OUT = os.path.join(CACHE, 'summary.json')

# The SWEEP lives here, not in pipeline/locplus.py. The knobs are module
# attributes of lp so the audit's config setter can flip and restore them.
# NOT ADOPTED (2026-09-19): 27 in was wired into pipeline.locplus as
# FAR_MISS_X_IN, verified, and taken out the same day (it removes 4.5% of the
# inflated grades; the parked edit is data/_loc_farmiss/farmiss27_adoption.patch).
# If that constant ever exists in production, it is switched OFF here so
# `shipped` stays the pre-rule model and every table reproduces.
lp.FAR_MISS_X_IN = float('inf')
lp.FARMISS_X_IN = None
lp.FARMISS_Z_LO = None
lp.FARMISS_Z_HI = None
lp.FARMISS_BUILD = 0
_ORIG_SCORE = lp.score_pitch
_ORIG_BUILD = lp.build_surfaces
_RV_MEMO = {}

X_GRID = [10, 12, 14, 16, 18, 20, 22, 24, 27, 30, 36]
Z_GRID = [0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.25, 1.5, 2.0]


def geom(p):
    g = p.get('_fm')
    if g is None:
        px = lp.safe_float(p.get('PlateX'))
        g = p['_fm'] = (abs(px) * 12.0 if px is not None else None, lp._znorm(p))
    return g


def is_far(p):
    dx, zn = geom(p)
    if dx is None or zn is None:
        return False
    cx, lo, hi = lp.FARMISS_X_IN, lp.FARMISS_Z_LO, lp.FARMISS_Z_HI
    return ((cx is not None and dx > cx) or (lo is not None and zn < -lo)
            or (hi is not None and zn > 1.0 + hi))


def _rule_on():
    return not (lp.FARMISS_X_IN is None and lp.FARMISS_Z_LO is None and lp.FARMISS_Z_HI is None)


def score_pitch(p, S):
    v = _ORIG_SCORE(p, S)
    if v is None or not _rule_on() or not is_far(p):
        return v
    return S['RV']['ball'].get(lp.get_count(p), 0.0)


def build_surfaces(baseline, lg_woba, woba_scale):
    if not (lp.FARMISS_BUILD and _rule_on()):
        return _ORIG_BUILD(baseline, lg_woba, woba_scale)
    key = (id(baseline), len(baseline))
    if key not in _RV_MEMO:
        _RV_MEMO.clear()
        _RV_MEMO[key] = _ORIG_BUILD(baseline, lg_woba, woba_scale)['RV']
    S = _ORIG_BUILD([p for p in baseline if not is_far(p)], lg_woba, woba_scale)
    S['RV'] = _RV_MEMO[key]
    return S


lp.score_pitch = score_pitch
lp.build_surfaces = build_surfaces


def cfg(x=None, lo=None, hi=None, build=0):
    return {**FR.SHIPPED, 'FARMISS_X_IN': x, 'FARMISS_Z_LO': lo, 'FARMISS_Z_HI': hi,
            'FARMISS_BUILD': build}


# ── calib: pitch level, out of sample ───────────────────────────────────
X_BANDS = [(a, a + 2) for a in range(8, 30, 2)] + [(30, 36), (36, 999)]
Z_BANDS = [(0.0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 0.8),
           (0.8, 1.0), (1.0, 1.25), (1.25, 1.5), (1.5, 2.0), (2.0, 99.0)]
# Fine bands around the crossings, each with a tail band, for the cumulative
# objective G(c) = sum over bands at or beyond c of n * e (total squared error
# of the rule minus shipped when the cutoff is c). argmin G is the cutoff.
X_FINE = [(a, a + 1) for a in range(12, 26)] + [(26, 999)]
LO_FINE = [(round(0.05 * a, 2), round(0.05 * a + 0.05, 2)) for a in range(8, 24)] + [(1.2, 99.0)]
HI_FINE = [(round(0.05 * a, 2), round(0.05 * a + 0.05, 2)) for a in range(4, 16)] + [(0.8, 99.0)]
FINE = {'x_fine': X_FINE, 'lo_fine': LO_FINE, 'hi_fine': HI_FINE}


def calib(seasons):
    os.makedirs(CACHE, exist_ok=True)
    acc = defaultdict(lambda: defaultdict(lambda: np.zeros(8)))   # [(dim, band)][yr]
    for yr in seasons:
        t0 = time.time()
        pitches = FR.load_season(yr)
        base_p = [p for p in pitches if lp.is_eligible_baseline(p)]
        dates = sorted({p['Game Date'] for p in base_p if p['Game Date']})
        par = {d: i % 2 for i, d in enumerate(dates)}
        for fold in (0, 1):
            S = _ORIG_BUILD([p for p in base_p if par.get(p['Game Date']) != fold], FR.LG, FR.SCALE)
            for p in base_p:
                if par.get(p['Game Date']) != fold:
                    continue
                re = lp.safe_float(p.get('RunExp'))
                v = _ORIG_SCORE(p, S)
                if re is None or v is None:
                    continue
                y = -re
                b = S['RV']['ball'].get(lp.get_count(p), 0.0)
                dx, zn = geom(p)
                sw = 1.0 if p.get('Description') in lp.SWING_DESC else 0.0
                px = lp.safe_float(p.get('PlateX'))
                inside = (px < 0) == (p.get('Bats') == 'R')
                e = (y - b) ** 2 - (y - v) ** 2          # > 0: shipped fits better
                rec = np.array([1.0, sw, y, v, b, e, e * e, 0.0])
                keys = []
                if -0.6 <= zn <= 1.6:                    # vertical inside the grid
                    for lo_, hi_ in X_BANDS:
                        if lo_ <= dx < hi_:
                            keys += [('x', (lo_, hi_)), ('x_in' if inside else 'x_out', (lo_, hi_))]
                    keys += [('x_fine', b_) for b_ in X_FINE if b_[0] <= dx < b_[1]]
                if dx <= 18.0:                           # horizontal inside the grid
                    m_lo, m_hi = -zn, zn - 1.0
                    keys += [('lo_fine', b_) for b_ in LO_FINE if b_[0] <= m_lo < b_[1]]
                    keys += [('hi_fine', b_) for b_ in HI_FINE if b_[0] <= m_hi < b_[1]]
                    for lo_, hi_ in Z_BANDS:
                        if lo_ <= m_lo < hi_:
                            keys.append(('lo', (lo_, hi_)))
                        if lo_ <= m_hi < hi_:
                            keys.append(('hi', (lo_, hi_)))
                for k in keys:
                    acc[k][yr] += rec
        print(f'=== {yr}: calib done, {len(base_p)} baseline pitches ({time.time() - t0:.0f}s)', flush=True)
        del pitches, base_p
        gc.collect()
    out = {}
    for dim, unit in (('x', 'in from centre'), ('x_in', 'in, toward the hitter'), ('x_out', 'in, away'),
                      ('lo', 'zone-heights below the zone'), ('hi', 'zone-heights above the zone')):
        print(f'\n--- {dim} ({unit}); e = SE(ball rule) - SE(shipped), per pitch x 1e4; e < 0 means the rule fits better')
        print(f'  {"band":>13s}{"n":>9s}{"swing":>8s}{"actual":>9s}{"shipped":>9s}{"ball":>9s}'
              f'{"e x1e4":>9s}{"se":>7s}{"z":>7s}{"seasons rule wins":>19s}')
        for band in (X_BANDS if dim.startswith('x') else Z_BANDS):
            per = acc.get((dim, band))
            if not per:
                continue
            t = sum(per.values())
            n = t[0]
            if n < 1:
                continue
            e = t[5] / n
            se = math.sqrt(max(t[6] / n - e * e, 0.0) / n)
            wins = sum(1 for v in per.values() if v[0] and v[5] / v[0] < 0)
            print(f'  {band[0]:>5g}-{band[1]:<7g}{int(n):>9d}{t[1] / n:>8.3f}{t[2] / n:>+9.4f}{t[3] / n:>+9.4f}'
                  f'{t[4] / n:>+9.4f}{e * 1e4:>+9.2f}{se * 1e4:>7.2f}{(e / se if se else float("nan")):>+7.1f}'
                  f'{wins:>12d}/{len(per)}')
            out[f'{dim}:{band[0]}-{band[1]}'] = {
                'n': int(n), 'swing': t[1] / n, 'actual': t[2] / n, 'shipped': t[3] / n, 'ball': t[4] / n,
                'e': e, 'se': se, 'rule_wins': wins, 'seasons': len(per),
                'per_season': {str(y): {'n': int(v[0]), 'e': v[5] / v[0]} for y, v in per.items() if v[0]}}
    for dim, bands in FINE.items():
        yrs = sorted({y for b_ in bands for y in acc.get((dim, b_), {})})
        print(f'\n--- {dim}: G(c) = total squared error (runs^2), rule minus shipped, if the cutoff is c; argmin = cutoff')
        print(f'  {"cutoff c":>9s}{"band n":>9s}{"band e x1e4":>13s}{"G(c) all":>11s}' + ''.join(f'{y:>9d}' for y in yrs))
        G = {y: 0.0 for y in yrs}
        rows = []
        for b_ in reversed(bands):
            per = acc.get((dim, b_), {})
            for y in yrs:
                G[y] += per[y][5] if y in per else 0.0
            t = sum(per.values()) if per else np.zeros(8)
            rows.append((b_[0], int(t[0]), (t[5] / t[0] if t[0] else float('nan')), dict(G)))
        for c_, n_, e_, g_ in reversed(rows):
            print(f'  {c_:>9g}{n_:>9d}{e_ * 1e4:>+13.2f}{sum(g_.values()):>+11.1f}'
                  + ''.join(f'{g_[y]:>+9.1f}' for y in yrs))
        best = {y: min(rows, key=lambda r: r[3][y])[0] for y in yrs}
        allb = min(rows, key=lambda r: sum(r[3].values()))[0]
        print(f'  argmin G: pooled {allb:g}; by season ' + ', '.join(f'{y} {best[y]:g}' for y in yrs))
        out[f'{dim}:argmin'] = {'pooled': allb, 'by_season': {str(y): best[y] for y in yrs}}
    dest = os.path.join(CACHE, 'calib.json')
    json.dump(out, open(dest + '.tmp', 'w'), indent=1)
    os.replace(dest + '.tmp', dest)
    print(f'\nwrote {dest}')


# ── run / summary: pitcher level ────────────────────────────────────────
def build_configs(a):
    configs = {'shipped': cfg()}
    modes = [m for m in a.mode]
    for sw in a.sweep:
        grid = X_GRID if sw == 'x' else Z_GRID
        for g in grid:
            for m in modes:
                configs[f'fm{m}_{sw}{g:g}'] = cfg(**{sw: g}, build=int(m == 'B'))
    for spec in a.combo:
        name, vals = spec.split('=', 1)
        v = vals.split(':')
        f = [None if s in ('', '-') else float(s) for s in v[:3]]
        configs[name] = cfg(x=f[0], lo=f[1], hi=f[2], build=int(len(v) > 3 and v[3] == 'B'))
    return configs


def validate_shipped(seasons):
    """The patched module with every cutoff None must reproduce the audit's own
    cached shipped tables (2026 excepted: its pickle moved on)."""
    import pandas as pd
    old_dir = os.path.join(ROOT, 'data', '_loc_target_audit')
    for yr in seasons:
        a, b = TA.table_path('shipped', yr), os.path.join(old_dir, f'tab_shipped_{yr}.pkl')
        if not (os.path.exists(a) and os.path.exists(b)):
            continue
        A, B = pd.read_pickle(a), pd.read_pickle(b)
        same = A.index.equals(B.index)
        d = float(np.nanmax(np.abs(A.values.astype(float) - B.values.astype(float)))) if same else float('nan')
        print(f'VALIDATE shipped {yr}: index equal {same}, max |diff| vs audit cache {d:.3g}'
              + ('   (2026 pickle refreshed since the audit; a difference is expected)' if yr == 2026 else ''))


def compact(path):
    out = json.load(open(path))
    cols = [('next', 'ren_avg_pstuff', 'DECIDER'), ('next', 'ren_x_pstuff', 'nx x|st'),
            ('next', 'ren_rv_pstuff', 'nx rv|st'), ('within', 'ren_x_pstuff', 'wi x|st'),
            ('within', 'ren_rv_pstuff', 'wi rv|st'), ('within', 'ren_x', 'wi x (old)'),
            ('next', 'ren_rstuff', 'd|r(L,St)|')]
    names = sorted({k.split(':', 1)[1] for k in out if ':' in k})
    print('\n===== compact: mean delta r x 1e4 (z, wins) vs shipped; rendered unit =====')
    print(f'  {"config":>16s} ' + ''.join(f'{c[2]:>19s}' for c in cols))
    for n in names:
        row = f'  {n:>16s} '
        for test, key, _ in cols:
            c = out.get(f'{test}:{n}', {}).get('all', {}).get(key)
            row += (f'{c["mean_d"] * 1e4:>+8.1f}({c["z_boot"]:>+4.1f},{c["wins"]}/{c["k"]})' if c else f'{"":>19s}')
        print(row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['calib', 'run', 'run-cut', 'summary'])
    ap.add_argument('--fracs', default='0.25,0.5,0.75', help='run-cut: share of the season dates')
    ap.add_argument('--cut', type=float, default=None, help='summary: read the @c<f> tables')
    ap.add_argument('--sweep', action='append', default=[], choices=['x', 'lo', 'hi'])
    ap.add_argument('--mode', default='A', help='A, B or AB')
    ap.add_argument('--combo', action='append', default=[], help='name=x:lo:hi[:B]  (- for off)')
    ap.add_argument('--seasons', default=None)
    a = ap.parse_args()
    seasons = [int(s) for s in a.seasons.split(',')] if a.seasons else sorted(FR.SEASONS)
    if a.cmd == 'calib':
        return calib(seasons)
    if a.cmd == 'summary':
        if a.cut is not None:
            TA.summarize(only='fm', cut=a.cut)
            return compact(TA.OUT.replace('.json', f'_shipped@c{a.cut:g}_fm.json'))
        validate_shipped(seasons)
        TA.summarize(only='fm')
        return compact(TA.OUT.replace('.json', '_shipped_fm.json'))
    if a.cmd == 'run-cut':
        # production sample size: surfaces, anchors and the grade stop at the cutoff date
        return TA.run_cut(build_configs(a), seasons, [float(x) for x in a.fracs.split(',')])
    TA.run(build_configs(a), seasons)


if __name__ == '__main__':
    main()
