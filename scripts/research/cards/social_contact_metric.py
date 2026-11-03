"""Which contact stat best fits the social table: xwOBAcon, Hard-Hit%, or Barrel%?

Pitcher side. Cell: season x pitcher x pitcher hand x batter hand x pitch type, values
within (hand, hand, type), 2021-2025. k in balls in play, from social_stabilize.curve.
Year to year and next-season targets: cells with 100+ pitches in Y, gated on Y only, Y+1
weighted by pitches. The same two targets at the whole-pitcher level, 500+ pitches in Y.
Barrel% is the EV/LA recompute: these caches carry no launch_speed_angle.

    python3 scripts/research/cards/social_contact_metric.py
"""
import gc
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from social_stabilize import ROOT, curve, fit_k, num

YEARS = [2021, 2022, 2023, 2024, 2025]
STATS = ['xwobacon', 'hard', 'barrel']
LAB = {'xwobacon': 'xwOBAcon', 'hard': 'Hard-Hit%', 'barrel': 'Barrel%'}
W = {'single': .89, 'double': 1.261, 'triple': 1.596, 'home_run': 2.049}   # 2026 wOBA weights


def load(y):
    d = pd.read_pickle(os.path.join(ROOT, 'data', f'_statcast{y}_cache.pkl'))
    o = pd.DataFrame({'p': num(d.pitcher).astype(object), 'th': d.p_throws.astype('object').to_numpy(),
                      's': d.stand.astype('object').to_numpy(), 't': d.pitch_type.astype('object').to_numpy()})
    bip = ((d['type'].astype('object') == 'X') & d.bb_type.notna() & d.bb_type.astype('object').ne('bunt')).to_numpy()
    ev, la = num(d.launch_speed), num(d.launch_angle)
    o['xwobacon'] = np.where(bip, num(d.estimated_woba_using_speedangle), np.nan)
    ok = bip & np.isfinite(ev)
    o['hard'] = np.where(ok, (ev >= 95).astype(float), np.nan)
    brl = (la >= 8) & (la <= 50) & (ev >= 98) & (ev * 1.5 - la >= 117) & (ev + la >= 124)
    o['barrel'] = np.where(ok & np.isfinite(la), brl.astype(float), np.nan)
    o['wcon'] = np.where(bip, d.events.astype('object').map(W).fillna(0.0).to_numpy(), np.nan)
    o['rv'] = -num(d.delta_run_exp)
    del d
    gc.collect()
    return o.dropna(subset=['p', 'th', 's', 't'])


def wr(a, b, w):
    ok = np.isfinite(a) & np.isfinite(b) & (w > 0)
    C = np.cov(a[ok], b[ok], aweights=w[ok])
    return float(C[0, 1] / np.sqrt(C[0, 0] * C[1, 1]))


def agg(o, keys):
    f = o.groupby(keys).agg(n=('rv', 'size'), xwobacon=('xwobacon', 'mean'), hard=('hard', 'mean'),
                            barrel=('barrel', 'mean'), wcon=('wcon', 'mean'), rv=('rv', 'mean'))
    return f.reset_index()


def main():
    rng = np.random.default_rng(0)
    fr = {y: load(y) for y in YEARS}
    ks = {k: [] for k in STATS}
    for y, o in fr.items():
        for k in STATS:
            ks[k].append(fit_k(curve(o, k, True, rng)))
    print('k in balls in play by season, then median')
    for k in STATS:
        print(f'  {LAB[k]:10s} {[round(x) if x else None for x in ks[k]]}  {np.median([x for x in ks[k] if x]):.0f}')
    keys = ['p', 'th', 's', 't']
    res = {k: {m: [] for m in ('yoy', 'wcon', 'rv', 'same', 'p_yoy', 'p_wcon', 'p_rv')} for k in STATS}
    for y0, y1 in zip(YEARS, YEARS[1:]):
        a = agg(fr[y0], keys)
        a = a[a.n >= 100]
        j = a.merge(agg(fr[y1], keys), on=keys, suffixes=('', '1'))
        cols = STATS + [c + '1' for c in STATS] + ['wcon', 'wcon1', 'rv1']
        z = j[cols] - j.groupby(['th', 's', 't'])[cols].transform('mean')
        w = j.n1.to_numpy(float)
        P0 = agg(fr[y0], ['p'])
        P0 = P0[P0.n >= 500]
        P = P0.merge(agg(fr[y1], ['p']), on='p', suffixes=('', '1'))
        wp = P.n1.to_numpy(float)
        for k in STATS:
            res[k]['yoy'].append(wr(z[k].to_numpy(), z[k + '1'].to_numpy(), w))
            res[k]['wcon'].append(wr(z[k].to_numpy(), z.wcon1.to_numpy(), w))
            res[k]['rv'].append(wr(z[k].to_numpy(), z.rv1.to_numpy(), w))
            res[k]['same'].append(wr(z[k].to_numpy(), z.wcon.to_numpy(), j.n.to_numpy(float)))
            res[k]['p_yoy'].append(wr(P[k].to_numpy(), P[k + '1'].to_numpy(), wp))
            res[k]['p_wcon'].append(wr(P[k].to_numpy(), P.wcon1.to_numpy(), wp))
            res[k]['p_rv'].append(wr(P[k].to_numpy(), P.rv1.to_numpy(), wp))
    print('Mean r across 4 season pairs. rv is pitcher-positive, so a good contact stat reads negative there.')
    for m in ('same', 'yoy', 'wcon', 'rv', 'p_yoy', 'p_wcon', 'p_rv'):
        print(f'  {m:7s} ' + '  '.join(f'{LAB[k]} {np.mean(res[k][m]):+.3f} {[round(x, 3) for x in res[k][m]]}' for k in STATS))


if __name__ == '__main__':
    main()
