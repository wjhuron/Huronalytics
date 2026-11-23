#!/usr/bin/env python3
"""social_xrv_gate.py — a measured minimum for the xRV/100 tint on the season social card.

The card tints the xRV/100 of one cell (pitcher x batter hand x pitch type) by its percentile
among the same cells. The card's other gates sit at the denominator where split-half
reliability is .50 (the level is the repo's convention; the denominator is measured). For
xRV/100 a single k does not exist: k = n_half x (1 - r) / r rises with the size of the cells
it is measured on, because large cells (a starter's main pitch) differ less from each other
than small ones. So the gate is the FIXED POINT: the cell size n* at which cells of about that
size have a reliability of .50, i.e. where k measured on a size band equals the band's size.

Per season: every cell is split into two random halves (SEEDS seeds); within a band of FULL
cell size the weighted r of the two half values gives k, and the reliability of a full cell of
the band's median size is n / (n + k). Values are luck-neutral run value per pitch (a ball in
play by xwOBA, every other pitch by delta_run_exp), centred within pitcher hand x batter hand
x pitch type, the pool the tint ranks in. Seasons 2021-2025 from the Statcast caches and 2026
from the pitch pickle are six replicates; the pooled row stacks the seasons.

  .venv/bin/python scripts/research/cards/social_xrv_gate.py
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pitch_type_metric_importance as M  # noqa: E402

BANDS = [(100, 150), (150, 200), (200, 300), (300, 400), (400, 500), (500, 650), (650, 850), (850, 1200), (1200, 99999)]
SEEDS = 10
WOBA_SCALE = 1.24


def statcast(y):
    d = pd.read_pickle(os.path.join(ROOT, 'data', f'_statcast{y}_cache.pkl'))
    f = pd.DataFrame({'pitcher': d['pitcher'].astype('int64').values.astype(str), 'throws': d['p_throws'].astype(object).values,
                      'pt': d['pitch_type'].astype(object).map(lambda v: M.MERGE.get(v, v)).values,
                      'stand': d['stand'].astype(object).values, 'bip': (d['description'].astype(object) == 'hit_into_play').values,
                      'dre': M.num(d['delta_run_exp']), 'xw': M.num(d['estimated_woba_using_speedangle'])})
    return f


def sheet2026():
    with open(os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl'), 'rb') as fh:
        rows = pickle.load(fh)
    f = pd.DataFrame([{'pitcher': r.get('Pitcher'), 'throws': r.get('Throws'), 'pt': M.MERGE.get(r.get('Pitch Type'), r.get('Pitch Type')),
                       'stand': r.get('Bats'), 'bip': r.get('Description') == 'In Play', 'dre': r.get('RunExp'), 'xw': r.get('xwOBA')}
                      for r in rows if r.get('_source', 'MLB') == 'MLB'])
    f['dre'], f['xw'] = pd.to_numeric(f['dre'], errors='coerce'), pd.to_numeric(f['xw'], errors='coerce')
    return f


def prep(f, y):
    lg = f.loc[f['bip'], 'xw'].mean()
    f['val'] = np.where(f['bip'] & f['xw'].notna(), -(f['xw'] - lg) / WOBA_SCALE, -f['dre']) * 100.0
    f = f[f['pt'].isin(M.TYPES) & f['val'].notna() & f['stand'].isin(['L', 'R']) & f['throws'].isin(['L', 'R'])].copy()
    f['val'] -= f.groupby(['throws', 'stand', 'pt'])['val'].transform('mean')
    f['cell'] = str(y) + '|' + f['pitcher'] + '|' + f['stand'] + '|' + f['pt']
    return f[['cell', 'val']]


def halves(f):
    """Per seed: one row per cell with the two half means and sizes."""
    out = []
    n = f.groupby('cell')['val'].size().rename('n')
    for seed in range(SEEDS):
        h = np.random.default_rng(seed).integers(0, 2, len(f))
        t = f.assign(h=h).groupby(['cell', 'h'])['val'].agg(['mean', 'size']).unstack('h').dropna()
        t.columns = ['m0', 'm1', 's0', 's1']
        out.append(t.join(n))
    return out


def band_stats(hs, lo, hi):
    rs, ks, nh, cells, med = [], [], [], 0, np.nan
    for t in hs:
        t = t[(t['n'] >= lo) & (t['n'] < hi) & (t['s0'] >= 10) & (t['s1'] >= 10)]
        if len(t) < 40:
            return None
        w = 2.0 / (1.0 / t['s0'] + 1.0 / t['s1'])
        r = M.wr(t['m0'].values, t['m1'].values, w.values)
        n_half = len(t) / (1.0 / w).sum()
        rs.append(r)
        nh.append(n_half)
        ks.append(n_half * (1 - r) / r if r > 0 else np.inf)
        cells, med = len(t), float(t['n'].median())
    r = float(np.mean(rs))
    k = float(np.mean(nh)) * (1 - r) / r if r > 0 else np.inf
    return {'cells': cells, 'median_n': med, 'r_half': r, 'k': k, 'rel_full': med / (med + k)}


def main():
    per = {}
    for y in (2021, 2022, 2023, 2024, 2025, 2026):
        f = prep(sheet2026() if y == 2026 else statcast(y), y)
        per[y] = halves(f)
        full = per[y][0]['n']
        print(f'{y}: {len(f):,} pitches, {int((full >= 100).sum()):,} cells with 100+ pitches, '
              f'{int((full >= 400).sum())} with 400+, {int((full >= 600).sum())} with 600+', flush=True)
    pooled = [pd.concat([per[y][s] for y in per]) for s in range(SEEDS)]
    print('\nPOOLED, six seasons. k = pitches for a reliability of .50, measured on cells of that band; rel = reliability of the band\'s median cell')
    print(f'{"band (full cell)":<18s}{"cells":>7s}{"median n":>10s}{"r of halves":>13s}{"k":>8s}{"rel":>7s}')
    rows = []
    for lo, hi in BANDS:
        b = band_stats(pooled, lo, hi)
        if b:
            rows.append(b)
            print(f'{f"{lo}-{hi if hi < 9e4 else chr(8734)}":<18s}{b["cells"]:>7d}{b["median_n"]:>10.0f}{b["r_half"]:>13.3f}{b["k"]:>8.0f}{b["rel_full"]:>7.2f}')
    # the fixed point: interpolate rel(median n) = .50
    xs, ys = [b['median_n'] for b in rows], [b['rel_full'] for b in rows]
    star = next((xs[i] + (0.5 - ys[i]) * (xs[i + 1] - xs[i]) / (ys[i + 1] - ys[i]) for i in range(len(xs) - 1) if ys[i] < 0.5 <= ys[i + 1]), None)
    print(f'\nfixed point (reliability of the full cell = .50), pooled: {star:.0f} pitches' if star else '\nno crossing of .50 on the bands')
    print('\nBY SEASON: the same fixed point on wider bands (fewer cells per season)')
    wide = [(100, 200), (200, 350), (350, 500), (500, 700), (700, 1000), (1000, 99999)]
    stars = []
    for y in per:
        rr = [b for b in (band_stats(per[y], lo, hi) for lo, hi in wide) if b]
        xs, ys = [b['median_n'] for b in rr], [b['rel_full'] for b in rr]
        st = next((xs[i] + (0.5 - ys[i]) * (xs[i + 1] - xs[i]) / (ys[i + 1] - ys[i]) for i in range(len(xs) - 1) if ys[i] < 0.5 <= ys[i + 1]), None)
        stars.append(st)
        print(f'   {y}: ' + '  '.join(f'{b["median_n"]:.0f}: {b["rel_full"]:.2f}' for b in rr) + f'   -> {"%.0f" % st if st else "no crossing"}')
    ok = [s for s in stars if s]
    if ok:
        print(f'   seasons with a crossing {len(ok)}/6: median {np.median(ok):.0f}, range {min(ok):.0f}-{max(ok):.0f}')
    full = pooled[0]['n']
    print(f'\nshare of the 100+ pitch cells at or above a gate: ' + '  '.join(f'{g}: {(full >= g).sum() / (full >= 100).sum():.0%}' for g in (100, 200, 300, 400, 500, 600, 800)))


if __name__ == '__main__':
    main()
