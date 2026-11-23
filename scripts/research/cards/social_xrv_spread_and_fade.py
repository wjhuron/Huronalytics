#!/usr/bin/env python3
"""social_xrv_spread_and_fade.py — two open points of the social card's xRV/100 tint.

  A  SPREAD. The tint places a cell's shrunk xRV/100 on the SD of real differences between
     cells of its group (pitcher hand, batter hand, pitch type). cards/pitcher.py measures
     that SD on the running season only. Is it the same from season to season, and how many
     groups have a measured SD early in a season (production's real sample size)?
  B  FADE LINE. Under 100 pitches the number fades, a convention. What does a cell of a given
     size tell the reader? Measured: how often the SIGN of a cell's value (better or worse than
     its group) agrees between two random halves, by cell size, against the normal model with
     the measured k (reliability n / (n + k), agreement 1/2 + asin(r) / pi). The model then
     gives the chance that a full cell's sign is right.

Cells and values as in social_xrv_gate.py (luck-neutral run value per pitch, centred within
the group). SD of real differences: sd^2 = mean over cells of 100+ pitches of
deviation^2 x n / (n + K), the card's own estimator, K = 525.

  .venv/bin/python scripts/research/cards/social_xrv_spread_and_fade.py
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pitch_type_metric_importance as M  # noqa: E402
import social_xrv_gate as G  # noqa: E402

K, MIN_N, YEARS, SEEDS = 525.0, 100, (2021, 2022, 2023, 2024, 2025, 2026), 10


def frame(y):
    f = G.sheet2026() if y == 2026 else G.statcast(y)
    if y != 2026:
        d = pd.read_pickle(os.path.join(ROOT, 'data', f'_statcast{y}_cache.pkl'))
        f['date'] = pd.to_datetime(d['game_date']).values
        del d
    lg = f.loc[f['bip'], 'xw'].mean()
    f['val'] = np.where(f['bip'] & f['xw'].notna(), -(f['xw'] - lg) / G.WOBA_SCALE, -f['dre']) * 100.0
    f = f[f['pt'].isin(M.TYPES) & f['val'].notna() & f['stand'].isin(['L', 'R']) & f['throws'].isin(['L', 'R'])].copy()
    return f


def spread(f):
    """Per group: (sd of real differences, cells); plus the same by pitch type and over all."""
    f = f.assign(v=f['val'] - f.groupby(['throws', 'stand', 'pt'])['val'].transform('mean'))
    c = f.groupby(['throws', 'stand', 'pt', 'pitcher'])['v'].agg(['mean', 'size']).reset_index()
    c = c[c['size'] >= MIN_N]
    c['q'] = c['mean'] ** 2 * c['size'] / (c['size'] + K)
    g = c.groupby(['throws', 'stand', 'pt'])['q'].agg(['mean', 'size'])
    return ({k: (np.sqrt(r['mean']), int(r['size'])) for k, r in g.iterrows()},
            {k: (np.sqrt(v['q'].mean()), len(v)) for k, v in c.groupby('pt')},
            (np.sqrt(c['q'].mean()), len(c)))


def main():
    F = {y: frame(y) for y in YEARS}
    S = {y: spread(F[y]) for y in YEARS}
    print('A. SD OF REAL DIFFERENCES between cells, runs per 100 pitches (cells of 100+ pitches)')
    print(f'{"":<14s}' + ''.join(f'{y:>8d}' for y in YEARS) + f'{"mean":>8s}{"CV":>7s}')
    row = [S[y][2][0] for y in YEARS]
    print(f'{"all cells":<14s}' + ''.join(f'{v:>8.2f}' for v in row) + f'{np.mean(row):>8.2f}{np.std(row, ddof=1) / np.mean(row):>7.0%}')
    for pt in M.TYPES:
        row = [S[y][1].get(pt, (np.nan, 0))[0] for y in YEARS]
        print(f'{pt:<14s}' + ''.join(f'{v:>8.2f}' for v in row) + f'{np.nanmean(row):>8.2f}{np.nanstd(row, ddof=1) / np.nanmean(row):>7.0%}')
    big = sorted(S[2025][0], key=lambda k: -S[2025][0][k][1])[:8]
    print('the eight largest groups (pitcher hand, batter hand, type):')
    cvs = []
    for k in big:
        row = [S[y][0].get(k, (np.nan, 0))[0] for y in YEARS]
        cvs.append(np.nanstd(row, ddof=1) / np.nanmean(row))
        print(f'{" ".join(k):<14s}' + ''.join(f'{v:>8.2f}' for v in row) + f'{np.nanmean(row):>8.2f}{cvs[-1]:>7.0%}')
    own = [sum(1 for v in S[y][0].values() if v[1] >= 30) for y in YEARS]
    print(f'groups with their own SD (30+ cells), full season: ' + ' '.join(f'{y}: {n}/{len(S[y][0])}' for y, n in zip(YEARS, own)))
    # what a different SD does to a tint: a 250-pitch cell 2.0 runs per 100 above its group
    from math import erf, sqrt
    pc = lambda sd, n=250, d=2.0: 50 * (1 + erf(d * n / (n + K) / sd / sqrt(2)))
    allv = [S[y][2][0] for y in YEARS]
    print(f'effect on a tint (250 pitches, 2.0 above the group): {pc(min(allv)):.0f}th pct at the lowest season SD, {pc(max(allv)):.0f}th at the highest')
    print('\nEARLY SEASON (production sample size): cells of 100+ pitches and groups with their own SD, season to date')
    for y in (2023, 2024, 2025):
        f = F[y]
        for cut in ('04-20', '05-10', '06-01', '07-01'):
            sub = f[f['date'] <= pd.Timestamp(f'{y}-{cut}')]
            g, _pt, al = spread(sub)
            print(f'   {y} through {cut}: {al[1]:>5d} cells, {sum(1 for v in g.values() if v[1] >= 30):>2d} of {len(g)} groups with their own SD, '
                  f'all-cell SD {al[0]:.2f}' if al[1] else f'   {y} through {cut}: no cell at 100 pitches')

    print('\nB. FADE LINE. Sign agreement of two random halves of a cell, by full cell size, six seasons pooled')
    print(f'{"cell size":<12s}{"cells":>7s}{"median n":>10s}{"halves agree":>14s}{"model":>8s}{"full cell sign right (model)":>30s}')
    allf = pd.concat([F[y].assign(cell=str(y) + '|' + F[y]['pitcher'].astype(str) + '|' + F[y]['stand'] + '|' + F[y]['pt'],
                                  v=F[y]['val'] - F[y].groupby(['throws', 'stand', 'pt'])['val'].transform('mean'))[['cell', 'v']] for y in YEARS])
    n = allf.groupby('cell')['v'].size().rename('n')
    agree = {}
    for seed in range(SEEDS):
        h = np.random.default_rng(seed).integers(0, 2, len(allf))
        t = allf.assign(h=h).groupby(['cell', 'h'])['v'].mean().unstack('h').dropna().join(n)
        t['a'] = np.sign(t[0]) == np.sign(t[1])
        for lo, hi in ((30, 60), (60, 100), (100, 150), (150, 250), (250, 400), (400, 600), (600, 900), (900, 99999)):
            b = t[(t['n'] >= lo) & (t['n'] < hi)]
            agree.setdefault((lo, hi), []).append((b['a'].mean(), len(b), b['n'].median()))
    for (lo, hi), v in agree.items():
        a, c, med = np.mean([x[0] for x in v]), v[0][1], v[0][2]
        rh = (med / 2) / (med / 2 + K)
        full = 0.5 + np.arcsin(np.sqrt(med / (med + K))) / np.pi
        print(f'{f"{lo}-{hi if hi < 9e4 else chr(8734)}":<12s}{c:>7d}{med:>10.0f}{a:>14.1%}{0.5 + np.arcsin(rh) / np.pi:>8.1%}{full:>30.1%}')
    print('\nfull-cell sign right, by the model: ' + '  '.join(f'{m}: {0.5 + np.arcsin(np.sqrt(m / (m + K))) / np.pi:.0%}' for m in (25, 50, 100, 175, 250, 400, 525, 800, 1200)))


if __name__ == '__main__':
    main()
