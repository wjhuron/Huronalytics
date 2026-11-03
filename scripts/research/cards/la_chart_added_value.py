"""What does the LA x spray chart tell a reader that the bubbles do not?

Bubbles: xwOBAcon, EV95, Hard-Hit%, Barrel%, Air Pull%, GB%. Chart reads: where his
hard contact sits on the league damage map, and which way it goes. Two tests on
independent season pairs, 2021-2025, hitter-sides with at least 250 BIP in season Y:

  1. Redundancy: how much of each chart read do the bubbles already explain?
  2. Added value: does adding the chart reads to the bubbles improve a held-out fit of
     same-season wOBAcon and next-season wOBAcon? The next-season pool is gated on Y
     only and weighted by Y+1 BIP (10 BIP floor, so the fit has a target at all).

Barrel% is the EV/LA recompute: these caches carry no launch_speed_angle. wOBA weights
are the 2026 values in every season, which only rescales within a season.

    python3 scripts/research/cards/la_chart_added_value.py
Writes data/_la_chart_added_value.json.
"""
import gc
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
YEARS = [2021, 2022, 2023, 2024, 2025]
MIN_BIP = 250
TARGET_FLOOR = 10
HX, HY = 125.42, 198.27
SPRAY = np.array([-50, -30, -15, 0, 15, 30, 50])
LA_EDGES = np.array([-9999, -10, 0, 5, 10, 15, 20, 25, 30, 35, 40, 50, 9999])
HOT = .55   # the card's damage-view threshold
W = json.load(open(os.path.join(ROOT, 'data', 'metadata_rs.json')))['wobaWeights']
VAL = {'single': W['1B'], 'double': W['2B'], 'triple': W['3B'], 'home_run': W['HR']}
BASE = ['xwobacon', 'ev95', 'hard', 'barrel', 'airpull', 'gb']
CHART = ['zone_all', 'zone_hard', 'hot_share', 'hard_pull', 'hard_oppo', 'hard_low', 'brl_oppo', 'med_spray', 'med_la']


def num(s):
    return pd.to_numeric(s, errors='coerce').to_numpy('float64', na_value=np.nan)


def season(year):
    d = pd.read_pickle(os.path.join(ROOT, 'data', f'_statcast{year}_cache.pkl'))
    d = d[(d['type'] == 'X') & d.bb_type.notna() & d.bb_type.astype('object').ne('bunt')]
    d = d[~d.description.astype('object').str.contains('bunt', na=False)]
    o = pd.DataFrame({'id': num(d.batter), 'stand': d.stand.astype('object').to_numpy(), 'ev': num(d.launch_speed),
                      'la': num(d.launch_angle), 'x': num(d.hc_x), 'y': num(d.hc_y),
                      'xw': num(d.estimated_woba_using_speedangle), 'bb': d.bb_type.astype('object').to_numpy(),
                      'ev_name': d.events.astype('object').to_numpy()})
    del d
    gc.collect()
    o = o.dropna(subset=['id', 'la', 'x', 'y'])
    o = o[HY - o.y > 0]
    ang = np.degrees(np.arctan2(o.x - HX, HY - o.y))
    o['a'] = np.where(o.stand == 'R', -ang, ang)   # pull is positive
    o['w'] = o.ev_name.map(VAL).fillna(0.0)
    o['hd'] = o.ev >= 95
    o['brl'] = (o.la.between(8, 50)) & (o.ev >= 98) & (o.ev * 1.5 - o.la >= 117) & (o.ev + o.la >= 124)
    o['sb'] = np.clip(np.searchsorted(SPRAY, o.a.clip(-49.99, 49.99), side='right') - 1, 0, 5)
    o['lb'] = np.searchsorted(LA_EDGES, o.la, side='right') - 1
    tb = o.groupby(['stand', 'sb', 'lb']).w.mean().rename('zone').reset_index()
    return o.merge(tb, on=['stand', 'sb', 'lb'], how='left')


def features(o):
    rows = {}
    for key, g in o.groupby(['id', 'stand'], sort=False):
        n = len(g)
        h = g[g.hd]
        b = g[g.brl]
        rows[key] = {
            'n': n, 'woba': g.w.mean(), 'xwobacon': g.xw.mean(),
            'ev95': np.nanpercentile(g.ev, 95) if g.ev.notna().any() else np.nan,
            'hard': g.hd.mean(), 'barrel': g.brl.mean(),
            'airpull': ((g.a > 15) & g.bb.isin(['fly_ball', 'line_drive'])).mean(),
            'gb': (g.bb == 'ground_ball').mean(),
            'zone_all': g.zone.mean(), 'zone_hard': h.zone.mean() if len(h) else np.nan,
            'hot_share': (h.zone >= HOT).mean() if len(h) else np.nan,
            'hard_pull': (h.a > 15).mean() if len(h) else np.nan,
            'hard_oppo': (h.a < -15).mean() if len(h) else np.nan,
            'hard_low': (h.la < 10).mean() if len(h) else np.nan,
            'brl_oppo': (b.a < -15).mean() if len(b) else 0.0,
            'med_spray': g.a.median(), 'med_la': g.la.median()}
    return pd.DataFrame.from_dict(rows, orient='index')


def cv_r2(X, y, w, folds=10, seed=0):
    """Weighted out-of-fold R2 of ridge-free OLS on standardized inputs."""
    idx = np.random.default_rng(seed).permutation(len(y))
    pred = np.zeros(len(y))
    for f in range(folds):
        te = idx[f::folds]
        tr = np.setdiff1d(idx, te)
        mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-9
        A = np.c_[np.ones(len(tr)), (X[tr] - mu) / sd]
        s = np.sqrt(w[tr])
        beta = np.linalg.lstsq(A * s[:, None], y[tr] * s, rcond=None)[0]
        pred[te] = np.c_[np.ones(len(te)), (X[te] - mu) / sd] @ beta
    ybar = np.average(y, weights=w)
    return 1 - np.sum(w * (y - pred) ** 2) / np.sum(w * (y - ybar) ** 2)


def main():
    feats = {y: features(season(y)) for y in YEARS}
    out = {'redundancy': {}, 'same': {}, 'next': {}}
    for y in YEARS:
        f = feats[y][feats[y].n >= MIN_BIP].dropna()
        for c in CHART:
            out['redundancy'].setdefault(c, []).append(cv_r2(f[BASE].to_numpy(), f[c].to_numpy(), np.ones(len(f))))
        y_ = f.woba.to_numpy()
        w = f.n.to_numpy(float)
        out['same'][y] = {'n': len(f), 'base': cv_r2(f[BASE].to_numpy(), y_, w),
                          'plus': cv_r2(f[BASE + CHART].to_numpy(), y_, w)}
    for y0, y1 in zip(YEARS, YEARS[1:]):
        a = feats[y0][feats[y0].n >= MIN_BIP].dropna()
        t = feats[y1][feats[y1].n >= TARGET_FLOOR][['woba', 'n']].rename(columns={'woba': 't', 'n': 'tn'})
        j = a.join(t, how='inner')
        out['next'][f'{y0}-{y1}'] = {'n': len(j), 'base': cv_r2(j[BASE].to_numpy(), j.t.to_numpy(), j.tn.to_numpy(float)),
                                     'plus': cv_r2(j[BASE + CHART].to_numpy(), j.t.to_numpy(), j.tn.to_numpy(float))}
    # All nine reads at once can lose to overfit alone, so each one also runs by itself.
    out['single'] = {}
    for c in CHART:
        same, nxt = [], []
        for y in YEARS:
            f = feats[y][feats[y].n >= MIN_BIP].dropna()
            w = f.n.to_numpy(float)
            same.append(cv_r2(f[BASE + [c]].to_numpy(), f.woba.to_numpy(), w)
                        - cv_r2(f[BASE].to_numpy(), f.woba.to_numpy(), w))
        for y0, y1 in zip(YEARS, YEARS[1:]):
            a = feats[y0][feats[y0].n >= MIN_BIP].dropna()
            t = feats[y1][feats[y1].n >= TARGET_FLOOR][['woba', 'n']].rename(columns={'woba': 't', 'n': 'tn'})
            j = a.join(t, how='inner')
            w = j.tn.to_numpy(float)
            nxt.append(cv_r2(j[BASE + [c]].to_numpy(), j.t.to_numpy(), w)
                       - cv_r2(j[BASE].to_numpy(), j.t.to_numpy(), w))
        out['single'][c] = {'same': same, 'next': nxt}
    tmp = os.path.join(ROOT, 'data', '_la_chart_added_value.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(out, f, indent=1, default=float)
    os.replace(tmp, os.path.join(ROOT, 'data', '_la_chart_added_value.json'))
    print('REDUNDANCY: held-out R2 of each chart read from the six bubbles, mean of 5 seasons')
    for c, v in out['redundancy'].items():
        print(f'  {c:10s} {np.mean(v):.2f}  {[round(x, 2) for x in v]}')
    for name in ('same', 'next'):
        print(f'{name.upper()}: held-out R2 of wOBAcon, bubbles vs bubbles + chart')
        for k, r in out[name].items():
            print(f"  {k}: n {r['n']}  base {r['base']:.3f}  plus {r['plus']:.3f}  diff {r['plus'] - r['base']:+.3f}")
    print('SINGLE: R2 gain from one chart read added to the bubbles (mean, seasons won)')
    for c, r in out['single'].items():
        print(f"  {c:10s} same {np.mean(r['same']):+.4f} ({sum(x > 0 for x in r['same'])}/5)   "
              f"next {np.mean(r['next']):+.4f} ({sum(x > 0 for x in r['next'])}/4)")


if __name__ == '__main__':
    main()
