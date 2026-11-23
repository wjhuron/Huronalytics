#!/usr/bin/env python3
"""social_evidence_tint.py — can Strike%, Whiff% and Loc+ on the season social card take the
xRV/100 column's evidence tint, and with what shrink constant?

The card tints one cell (pitcher x batter hand x pitch type). Today Strike% and Whiff% rank the
RAW value in a pool of cells over a hard gate (100 pitches, 40 swings) and a cell under the gate
has no tint; Loc+ tints by the grade value over a gate of 125 pitches. The evidence rule is
    shrunk deviation = (cell value - group mean) x n / (n + K)
placed on the SD of real differences between cells of the group (pitcher hand, batter hand,
pitch type). This script measures, per metric:

  A  K. Two readings. (1) The fixed point of social_xrv_gate.py: the cell size at which a cell
     of about that size has a split-half reliability of .50. (2) A sweep: each cell is split in
     two random halves, half A is shrunk with K and scored against half B's raw value
     (denominator-weighted squared error). The sweep is the objective that decides: it is the
     accuracy of the number the tint shows, and no K can improve it by removing information
     (K -> infinity scores the group mean, K = 0 the raw value).
  B  HELD-OUT RULE TEST. K is chosen on five seasons and scored on the sixth, against the
     card's present rule (raw value over the gate, the group mean under it) and the raw value
     with no gate. Six replicates for Strike% and Whiff%.
  C  SPREAD. The SD of real differences by season, the scale the tint reads.

Strike% and Whiff% are rebuilt for 2021-2025 from the Statcast caches and for 2026 from the
pitch pickle (MLB rows). Loc+ has per-pitch values only in the 2026 pickle, so its numbers are
ONE season and carry no replicate. A bunt in play counts as a swing in the Statcast seasons
(the cache has no bunt flag); the pickle season follows the same rule so the six are alike.

  .venv/bin/python scripts/research/cards/social_evidence_tint.py
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pitch_type_metric_importance as M  # noqa: E402

YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
SEEDS = 10
KGRID = {'strike': [50, 75, 90, 100, 110, 120, 130, 150, 200, 300, 400, 500, 650, 800, 1000, 1300, 1700, 2500],
         'whiff': [20, 30, 35, 40, 45, 50, 60, 80, 100, 130, 160, 200, 250, 325, 425, 600, 900],
         'loc': [25, 50, 75, 100, 115, 130, 150, 170, 200, 300, 400, 500, 650, 800, 1000, 1300]}
GATE = {'strike': 100, 'whiff': 40, 'loc': 125}                  # the card's present gates
BANDS = {'strike': [(100, 150), (150, 200), (200, 300), (300, 400), (400, 500), (500, 650), (650, 850), (850, 1200), (1200, 99999)],
         'whiff': [(40, 60), (60, 80), (80, 110), (110, 150), (150, 200), (200, 275), (275, 375), (375, 550), (550, 99999)],
         'loc': [(100, 150), (150, 200), (200, 300), (300, 400), (400, 500), (500, 650), (650, 850), (850, 1200), (1200, 99999)]}
SC_SWING = {'swinging_strike', 'swinging_strike_blocked', 'foul', 'foul_tip', 'hit_into_play', 'missed_bunt', 'bunt_foul_tip'}
SC_WHIFF = {'swinging_strike', 'swinging_strike_blocked', 'foul_tip', 'missed_bunt', 'bunt_foul_tip'}
SC_BALL = {'ball', 'blocked_ball', 'automatic_ball', 'hit_by_pitch', 'pitchout'}
PK_SWING = {'Swinging Strike', 'Foul', 'In Play', 'Missed Bunt', 'Bunt Foul Tip'}
PK_WHIFF = {'Swinging Strike', 'Missed Bunt', 'Bunt Foul Tip'}
PK_BALL = {'Ball', 'Intent Ball', 'Hit By Pitch', 'Pitchout'}


def load(y):
    if y == 2026:
        with open(os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl'), 'rb') as fh:
            rows = pickle.load(fh)
        f = pd.DataFrame([{'pitcher': r.get('Pitcher'), 'throws': r.get('Throws'), 'stand': r.get('Bats'),
                           'pt': M.MERGE.get(r.get('Pitch Type'), r.get('Pitch Type')), 'd': r.get('Description'), 'loc': r.get('Loc+')}
                          for r in rows if r.get('_source', 'MLB') == 'MLB'])
        del rows
        f['loc'] = pd.to_numeric(f['loc'], errors='coerce')
        f['swing'], f['whiffed'], f['strike'] = f['d'].isin(PK_SWING), f['d'].isin(PK_WHIFF), (~f['d'].isin(PK_BALL)).astype(float)
    else:
        d = pd.read_pickle(os.path.join(ROOT, 'data', f'_statcast{y}_cache.pkl'))
        ds = d['description'].astype(object)
        f = pd.DataFrame({'pitcher': d['pitcher'].astype('int64').values.astype(str), 'throws': d['p_throws'].astype(object).values,
                          'stand': d['stand'].astype(object).values, 'pt': d['pitch_type'].astype(object).map(lambda v: M.MERGE.get(v, v)).values,
                          'swing': ds.isin(SC_SWING).values, 'whiffed': ds.isin(SC_WHIFF).values, 'strike': (~ds.isin(SC_BALL)).values.astype(float)})
        f['loc'] = np.nan
        del d
    f = f[f['pt'].isin(M.TYPES) & f['stand'].isin(['L', 'R']) & f['throws'].isin(['L', 'R'])].copy()
    f['cell'] = str(y) + '|' + f['pitcher'].astype(str) + '|' + f['stand'] + '|' + f['pt']
    f['grp'] = str(y) + '|' + f['throws'] + '|' + f['stand'] + '|' + f['pt']
    return f


def events(f, metric):
    """The metric's denominator events: one row each, value v centred on the group mean."""
    if metric == 'strike':
        e = f[['cell', 'grp']].assign(v=f['strike'].values)
    elif metric == 'whiff':
        e = f.loc[f['swing'], ['cell', 'grp']].assign(v=f.loc[f['swing'], 'whiffed'].astype(float).values)
    else:
        e = f.loc[f['loc'].notna(), ['cell', 'grp']].assign(v=f.loc[f['loc'].notna(), 'loc'].values)
    e['v'] = e['v'] - e.groupby('grp')['v'].transform('mean')
    return e


def halves(e):
    """Per seed: one row per cell with the centred half means, half sizes and the full size."""
    n = e.groupby('cell')['v'].size().rename('n')
    out = []
    for seed in range(SEEDS):
        h = np.random.default_rng(seed).integers(0, 2, len(e))
        t = e.assign(h=h).groupby(['cell', 'h'])['v'].agg(['mean', 'size']).unstack('h').dropna()
        t.columns = ['m0', 'm1', 's0', 's1']
        out.append(t.join(n))
    return out


def band_stats(hs, lo, hi):
    rs, nh, cells, med = [], [], 0, np.nan
    for t in hs:
        t = t[(t['n'] >= lo) & (t['n'] < hi) & (t['s0'] >= 10) & (t['s1'] >= 10)]
        if len(t) < 40:
            return None
        w = 2.0 / (1.0 / t['s0'] + 1.0 / t['s1'])
        rs.append(M.wr(t['m0'].values, t['m1'].values, w.values))
        nh.append(len(t) / (1.0 / w).sum())
        cells, med = len(t), float(t['n'].median())
    r = float(np.mean(rs))
    k = float(np.mean(nh)) * (1 - r) / r if r > 0 else np.inf
    return {'cells': cells, 'median_n': med, 'r': r, 'k': k, 'rel': med / (med + k)}


def fixed_point(hs, bands):
    rr = [b for b in (band_stats(hs, lo, hi) for lo, hi in bands) if b]
    xs, ys = [b['median_n'] for b in rr], [b['rel'] for b in rr]
    st = next((xs[i] + (0.5 - ys[i]) * (xs[i + 1] - xs[i]) / (ys[i + 1] - ys[i]) for i in range(len(xs) - 1) if ys[i] < 0.5 <= ys[i + 1]), None)
    return rr, st


def sse(hs, pred):
    """Mean over seeds of the s1-weighted squared error of pred(m0, s0) against m1, both directions."""
    tot, w = 0.0, 0.0
    for t in hs:
        t = t[(t['s0'] >= 5) & (t['s1'] >= 5)]
        for a, sa, b, sb in ((t['m0'], t['s0'], t['m1'], t['s1']), (t['m1'], t['s1'], t['m0'], t['s0'])):
            tot += float((sb * (pred(a, sa) - b) ** 2).sum())
            w += float(sb.sum())
    return tot / w


def spread(e, k, min_n):
    c = e.groupby(['grp', 'cell'])['v'].agg(['mean', 'size']).reset_index()
    c = c[c['size'] >= min_n]
    return float(np.sqrt((c['mean'] ** 2 * c['size'] / (c['size'] + k)).mean())), len(c)


def main():
    E = {m: {} for m in KGRID}
    for y in YEARS:
        f = load(y)
        for m in KGRID:
            if m == 'loc' and y != 2026:
                continue
            E[m][y] = events(f, m)
        print(f'{y}: {len(f):,} pitches', flush=True)
        del f
    for m in ('strike', 'whiff', 'loc'):
        unit = {'strike': 'pitches', 'whiff': 'swings', 'loc': 'pitches'}[m]
        scale = 1.0 if m == 'loc' else 100.0
        ys = sorted(E[m])
        H = {y: halves(E[m][y]) for y in ys}
        pooled = [pd.concat([H[y][s] for y in ys]) for s in range(SEEDS)]
        print(f'\n================ {m.upper()}  (denominator: {unit}; seasons {ys[0]}-{ys[-1]}, {len(ys)}) ================')
        rr, st = fixed_point(pooled, BANDS[m])
        print('A1. fixed point, pooled: ' + '  '.join(f'{b["median_n"]:.0f}: rel {b["rel"]:.2f} (k {b["k"]:.0f})' for b in rr))
        print(f'    reliability .50 at {st:.0f} {unit}' if st else '    no crossing of .50 on the bands')
        if len(ys) > 1:
            sts = [fixed_point(H[y], BANDS[m][::2] if m != 'whiff' else BANDS[m][::2])[1] for y in ys]
            print('    by season (wider bands): ' + '  '.join(f'{y}: {"%.0f" % s if s else "none"}' for y, s in zip(ys, sts)))
        print(f'A2. sweep of K: half A shrunk, scored on half B (root weighted squared error, {"points" if m == "loc" else "percentage points"})')
        curve = {k: {y: sse(H[y], lambda a, sa, k=k: a * sa / (sa + k)) for y in ys} for k in KGRID[m]}
        print(f'{"K":>8s}' + ''.join(f'{y:>9d}' for y in ys) + f'{"pooled":>9s}')
        pool_c = {}
        for k in KGRID[m]:
            pool_c[k] = float(np.mean([curve[k][y] for y in ys]))
            print(f'{k:>8d}' + ''.join(f'{scale * np.sqrt(curve[k][y]):>9.3f}' for y in ys) + f'{scale * np.sqrt(pool_c[k]):>9.3f}')
        best = {y: min(KGRID[m], key=lambda k: curve[k][y]) for y in ys}
        kb = min(KGRID[m], key=lambda k: pool_c[k])
        edge = kb in (KGRID[m][0], KGRID[m][-1])
        print(f'    argmin by season: ' + '  '.join(f'{y}: {best[y]}' for y in ys) + f'   pooled: {kb}' + ('   <-- GRID EDGE' if edge else '   (interior)'))
        near = [k for k in KGRID[m] if np.sqrt(pool_c[k]) <= np.sqrt(pool_c[kb]) * 1.002]
        print(f'    K within 0.2% of the pooled minimum: {near[0]}-{near[-1]}')
        g = GATE[m]
        print(f'B.  held-out rule test (K from the other seasons; error on the held-out season, half cells, gate scaled to the half: {g // 2})')
        print(f'{"season":>8s}{"K used":>8s}{"evidence":>10s}{"gate rule":>11s}{"raw":>8s}{"group mean":>12s}')
        wins = 0
        for y in ys:
            others = [o for o in ys if o != y] or [y]
            ky = min(KGRID[m], key=lambda k: np.mean([curve[k][o] for o in others]))
            ev = sse(H[y], lambda a, sa: a * sa / (sa + ky))
            gt = sse(H[y], lambda a, sa: a.where(sa >= g / 2, 0.0))
            rw = sse(H[y], lambda a, sa: a)
            gm = sse(H[y], lambda a, sa: a * 0.0)
            wins += ev < gt
            print(f'{y:>8d}{ky:>8d}{scale * np.sqrt(ev):>10.3f}{scale * np.sqrt(gt):>11.3f}{scale * np.sqrt(rw):>8.3f}{scale * np.sqrt(gm):>12.3f}')
        print(f'    evidence rule beats the gate rule in {wins}/{len(ys)} seasons' + ('' if len(ys) > 1 else '  (ONE season: K was chosen on the same season, not held out)'))
        print(f'C.  SD of real differences between cells at K = {kb} (cells at the gate, {g}+ {unit})')
        sds = [spread(E[m][y], kb, g) for y in ys]
        print('    ' + '  '.join(f'{y}: {scale * s:.2f} ({c} cells)' for y, (s, c) in zip(ys, sds)))
        if len(ys) > 1:
            v = [s for s, _c in sds]
            print(f'    mean {scale * np.mean(v):.2f}, CV {np.std(v, ddof=1) / np.mean(v):.0%}')
        full = pooled[0]['n']
        print(f'    weight n / (n + K) at K = {kb}: ' + '  '.join(f'{n}: {n / (n + kb):.2f}' for n in (g // 2, g, 2 * g, 4 * g, 8 * g)))
        print(f'    cells: {int((full >= 10).sum()):,} with 10+ {unit}, {int((full >= g).sum()):,} at the gate')


if __name__ == '__main__':
    main()
