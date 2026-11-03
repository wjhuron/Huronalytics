"""How fast do the social table's columns stabilize at the cell the card renders?

Cell: season x pitcher x pitcher hand x batter hand x pitch type. A percentile tint ranks
inside (pitcher hand, batter hand, pitch type), so values are demeaned in that group.
Design from reference_stabilization_measure_the_rendered_unit: split randomly within the
cell, draw two independent n-unit estimates, corr(A, B) = rho(n) directly, no
Spearman-Brown; atoms come from one surface or model, not one per half. k = n (1 - rho) /
rho, so a gate at n = k means half the colored variance is signal. That .50 point is a
convention. k here is the median across n weighted by cells, over n with 100+ cells.

Units: pitches in the cell for every stat, plus swings for Whiff% and BIP for xwOBAcon.
Replicates: 2021-2025 Statcast caches (Savant tags) and the retagged 2026 cache. Stuff+ and
Loc+ atoms exist for 2026 only. The gate frames' l_loc is NOT a Loc+ atom (std .019 around
0, k about 2,700), so it is not used here.

    python3 scripts/research/cards/social_stabilize.py
Writes data/_social_stabilize.json.
"""
import gc
import json
import os
import pickle

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
GRID = [5, 10, 15, 20, 25, 30, 40, 50, 60, 75, 100, 125, 150, 200]
SEEDS = 10
MIN_CELLS = 100
STRIKE = {'called_strike', 'swinging_strike', 'swinging_strike_blocked', 'foul', 'foul_tip', 'foul_bunt',
          'missed_bunt', 'hit_into_play', 'automatic_strike', 'bunt_foul_tip'}
SWING = {'swinging_strike', 'swinging_strike_blocked', 'foul', 'foul_tip', 'hit_into_play'}
WHIFF = {'swinging_strike', 'swinging_strike_blocked'}


def num(s):
    return pd.to_numeric(s, errors='coerce').to_numpy('float64', na_value=np.nan)


def from_cache(y):
    d = pd.read_pickle(os.path.join(ROOT, 'data', f'_statcast{y}_cache.pkl'))
    desc = d.description.astype('object')
    o = pd.DataFrame({'p': num(d.pitcher).astype(object), 'th': d.p_throws.astype('object').to_numpy(),
                      's': d.stand.astype('object').to_numpy(), 't': d.pitch_type.astype('object').to_numpy()})
    o['strike'] = desc.isin(STRIKE).to_numpy(float)
    swing = desc.isin(SWING).to_numpy()
    o['whiff'] = np.where(swing, desc.isin(WHIFF).to_numpy(float), np.nan)
    bip = ((d['type'].astype('object') == 'X') & d.bb_type.notna() & d.bb_type.astype('object').ne('bunt')).to_numpy()
    o['xwobacon'] = np.where(bip, num(d.estimated_woba_using_speedangle), np.nan)
    del d
    gc.collect()
    return o.dropna(subset=['p', 'th', 's', 't'])


def from_2026():
    with open(os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl'), 'rb') as f:
        P = [p for p in pickle.load(f) if p.get('_source') == 'MLB' and p.get('Pitch Type')]
    sf = lambda v: pd.to_numeric(pd.Series(v), errors='coerce').to_numpy('float64')
    d = [p.get('Description') for p in P]
    o = pd.DataFrame({'p': [p.get('Pitcher') for p in P], 'th': [p.get('Throws') for p in P],
                      's': [p.get('Bats') for p in P], 't': [p.get('Pitch Type') for p in P]})
    o['strike'] = [float(x in ('Called Strike', 'Swinging Strike', 'Foul', 'Foul Bunt', 'In Play')) for x in d]
    o['whiff'] = [float(x == 'Swinging Strike') if x in ('Swinging Strike', 'Foul', 'In Play') else np.nan for x in d]
    o['xwobacon'] = [(lambda v: v if (x == 'In Play' and not str(b or '').startswith('bunt')) else np.nan)(w)
                     for x, b, w in zip(d, [p.get('BBType') for p in P], sf([p.get('xwOBA') for p in P]))]
    o['stuff'] = sf([p.get('Stuff+') for p in P])
    o['loc'] = sf([p.get('Loc+') for p in P])
    return o.dropna(subset=['p', 'th', 's', 't'])


def curve(o, col, native, rng):
    """{n: rho}. native=True samples n VALID values; False samples n pitches in the cell."""
    cells, groups = [], []
    for (pp, th, s, t), g in o.groupby(['p', 'th', 's', 't'], sort=False):
        v = g[col].to_numpy('float64')
        if native:
            v = v[~np.isnan(v)]
        if len(v) >= 2 * GRID[0]:
            cells.append(v)
            groups.append((th, s, t))
    groups = np.array(pd.factorize(pd.Series(groups))[0])
    sizes = np.array([len(v) for v in cells])
    out = {}
    for n in GRID:
        idx = np.where(sizes >= 2 * n)[0]
        if len(idx) < MIN_CELLS:
            continue
        rs = []
        for _ in range(SEEDS):
            A, B = np.full(len(idx), np.nan), np.full(len(idx), np.nan)
            for i, c in enumerate(idx):
                v = cells[c][rng.permutation(sizes[c])[:2 * n]]
                a, b = v[:n], v[n:]
                if np.isfinite(a).any() and np.isfinite(b).any():
                    A[i], B[i] = np.nanmean(a), np.nanmean(b)
            frame = pd.DataFrame({'g': groups[idx], 'a': A, 'b': B}).dropna()
            frame['a'] -= frame.groupby('g').a.transform('mean')
            frame['b'] -= frame.groupby('g').b.transform('mean')
            rs.append(np.corrcoef(frame.a, frame.b)[0, 1])
        out[n] = {'r': float(np.mean(rs)), 'cells': len(idx)}
    return out


def fit_k(c):
    ks, ws = [], []
    for n, d in c.items():
        if d['r'] > 0:
            ks.append(n * (1 - d['r']) / d['r'])
            ws.append(d['cells'])
    if not ks:
        return None
    order = np.argsort(ks)
    ks, ws = np.array(ks)[order], np.array(ws)[order]
    return float(ks[np.searchsorted(np.cumsum(ws), ws.sum() / 2)])


def main():
    rng = np.random.default_rng(0)
    res = {}
    jobs = [(y, from_cache, [('strike', False), ('whiff', False), ('whiff', True), ('xwobacon', False), ('xwobacon', True)])
            for y in range(2021, 2026)]
    for y, load, stats in jobs:
        o = load(y)
        for col, native in stats:
            res.setdefault(f'{col}{"_native" if native else ""}', {})[str(y)] = curve(o, col, native, rng)
        del o
        gc.collect()
        print('done', y, flush=True)
    o = from_2026()
    for col, native in [('strike', False), ('whiff', False), ('whiff', True), ('xwobacon', False), ('xwobacon', True),
                        ('stuff', False), ('loc', False)]:
        res.setdefault(f'{col}{"_native" if native else ""}', {})['2026'] = curve(o, col, native, rng)
    # Coverage on the 2026 rendered cells. Checked against shipped values at the pitcher x
    # type unit: Loc+ reads 51 pitches against STABILIZE_N_PT 49-62.
    sz = o.groupby(['p', 'th', 's', 't']).size().to_numpy()
    cover = {k: round(float((sz >= k).mean()), 3) for k in (15, 25, 50, 75, 100, 150, 200, 300, 500)}
    tmp = os.path.join(ROOT, 'data', '_social_stabilize.json.tmp')
    with open(tmp, 'w') as f:
        json.dump({'curves': res, 'cover': cover}, f)
    os.replace(tmp, os.path.join(ROOT, 'data', '_social_stabilize.json'))
    print('\nstat              k by season                                          median k')
    for stat, by in res.items():
        ks = {y: fit_k(c) for y, c in by.items()}
        vals = [v for v in ks.values() if v is not None]
        print(f'{stat:16s} ' + ' '.join(f'{y[2:]}:{v:5.0f}' if v else f'{y[2:]}:  n/a' for y, v in ks.items())
              + f'   {np.median(vals):.0f}')
    print('\nrho(n), mean across seasons (cells in the first season)')
    for stat, by in res.items():
        cs = {}
        for c in by.values():
            for n, d in c.items():
                cs.setdefault(n, []).append(d['r'])
        print(f'{stat:16s} ' + ' '.join(f'{n}:{np.mean(v):.2f}' for n, v in sorted(cs.items())))
    print('\n2026 share of rendered cells with at least n pitches:', cover)


if __name__ == '__main__':
    main()
