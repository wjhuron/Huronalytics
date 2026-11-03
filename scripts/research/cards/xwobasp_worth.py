"""Is xwOBAsp worth keeping beside the shipped contact stats?

xwOBAsp scores each ball by the league wOBAcon of its launch angle x spray zone, so it
reads placement and ignores exit velocity. Season pairs 2021-2025, hitter-sides with at
least 250 BIP in Y, next-season targets gated on Y only and weighted by Y+1 BIP. The zone
value here is rebuilt per season per side (zone_all in la_chart_added_value.py); the 2026
block reads the shipped leaderboard to validate that against the real column.

    python3 scripts/research/cards/xwobasp_worth.py
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from la_chart_added_value import BASE, MIN_BIP, ROOT, TARGET_FLOOR, YEARS, cv_r2, features, season

COLS = {'xwOBAsp': 'zone_all', 'xwOBAcon': 'xwobacon', 'EV95': 'ev95', 'Hard-Hit%': 'hard',
        'Barrel%': 'barrel', 'Air Pull%': 'airpull', 'wOBAcon': 'woba'}


def wr(a, b, w):
    C = np.cov(a, b, aweights=w)
    return C[0, 1] / np.sqrt(C[0, 0] * C[1, 1])


def main():
    feats = {y: features(season(y)) for y in YEARS}
    res = {k: {'yoy': [], 'next': []} for k in COLS}
    gain_base, gain_xw = [], []
    for y0, y1 in zip(YEARS, YEARS[1:]):
        a = feats[y0][feats[y0].n >= MIN_BIP].dropna()
        t = feats[y1][feats[y1].n >= TARGET_FLOOR].rename(columns=lambda c: c + '_t')
        j = a.join(t, how='inner')
        w = j.n_t.to_numpy(float)
        for k, c in COLS.items():
            res[k]['yoy'].append(wr(j[c], j[c + '_t'], w))
            res[k]['next'].append(wr(j[c], j.woba_t, w))
        y = j.woba_t.to_numpy()
        gain_base.append(cv_r2(j[BASE + ['zone_all']].to_numpy(), y, w) - cv_r2(j[BASE].to_numpy(), y, w))
        gain_xw.append(cv_r2(j[['xwobacon', 'zone_all']].to_numpy(), y, w) - cv_r2(j[['xwobacon']].to_numpy(), y, w))
    print('stat         year-to-year r (4 pairs)         next-season wOBAcon r (4 pairs)')
    for k, r in res.items():
        print(f"{k:11s}  {np.mean(r['yoy']):.3f} {[round(x, 3) for x in r['yoy']]}  "
              f"{np.mean(r['next']):.3f} {[round(x, 3) for x in r['next']]}")
    print('R2 gain, next-season wOBAcon: on xwOBAcon', [round(x, 4) for x in gain_xw],
          ' on six bubbles', [round(x, 4) for x in gain_base])
    same = {k: [] for k in COLS}
    for y in YEARS:
        f = feats[y][feats[y].n >= MIN_BIP].dropna()
        for k, c in COLS.items():
            same[k].append(float(np.corrcoef(f.zone_all, f[c])[0, 1]))
    print('same-season r with xwOBAsp:', {k: round(float(np.mean(v)), 3) for k, v in same.items()})
    rows = [x for x in json.load(open(os.path.join(ROOT, 'data', 'hitter_leaderboard_rs.json')))
            if x.get('team') not in ('ROC', 'AAA') and not str(x.get('team')).endswith('TM')
            and (x.get('pa') or 0) >= 300 and x.get('xwOBAsp') is not None]
    keys = ['xwOBAcon', 'ev95', 'hardHitPct', 'barrelPct', 'airPullPct', 'wOBA', 'wRCplus', 'bbPlus']
    print('2026 shipped, PA >= 300, n', len(rows), 'r with xwOBAsp:')
    for k in keys:
        p = [(r['xwOBAsp'], r[k]) for r in rows if r.get(k) is not None]
        if len(p) > 30:
            print(f'  {k:11s} {np.corrcoef(np.array(p).T)[0, 1]:+.3f}')
    for n in ('Wood, James', 'Judge, Aaron', 'Arraez, Luis'):
        print(' ', [(r['hitter'], r['team'], r['xwOBAsp'], r.get('xwOBAsp_pctl'), r['xwOBAcon'], r.get('xwOBAcon_pctl'), r.get('ev95'))
                    for r in rows if r['hitter'] == n])


if __name__ == '__main__':
    main()
