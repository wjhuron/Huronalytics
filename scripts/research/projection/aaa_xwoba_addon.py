"""aaa_xwoba_addon.py: does Triple-A Statcast xwOBA add to the box-score bridge (aaa_hitter_bridge.py)?

AAA xwOBA per batter-season = mean estimated_woba_using_speedangle over PA-ending pitches
(data/_aaa_statcastYYYY_cache.pkl; it is populated on strikeouts, walks and HBP too, 1.4 percent
missing), as a delta from the AAA league, shrunk like the box channels. Bridge seasons with the cache:
Y = 2023, 2024, 2025 -> MLB 2024-2026. Paired: both arms (box, box + xw) fit on two seasons and scored
on the third. Three replicates: a screen, not a verdict, and it says so.

Usage: python3 scripts/research/projection/aaa_xwoba_addon.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aaa_hitter_bridge as br

N0 = 1000
YS = [2023, 2024, 2025]


def aaa_xw(y):
    d = pd.read_pickle(os.path.join(br.ROOT, 'data', f'_aaa_statcast{y}_cache.pkl'), )
    e = d[d['events'].notna()].copy()
    e['x'] = pd.to_numeric(e['estimated_woba_using_speedangle'], errors='coerce').to_numpy(dtype='float64', na_value=np.nan)
    e = e[~np.isnan(e['x'])]
    g = e.groupby('batter')['x'].agg(['mean', 'count'])
    lg = float(e['x'].mean())
    return {int(b): (r['mean'] - lg, int(r['count'])) for b, r in g.iterrows()}


def main():
    A, M = br.season_tables()
    XW = {y: aaa_xw(y) for y in YS}
    F = {}
    for y in YS:
        rows = []
        for pid, a in A[y][0].items():
            if a['pa'] < 200 or a['age'] is None:
                continue
            m1 = M[y + 1][0].get(pid)
            if not m1 or m1['pa'] < 100 or pid not in XW[y]:
                continue
            xd, n = XW[y][pid]
            f = br.features(a, M[y][0].get(pid), N0)
            rows.append((f, xd * n / (n + N0), m1['d_woba'], m1['pa']))
        F[y] = rows
    print('pairs with AAA xwOBA:', {y: len(v) for y, v in F.items()})
    for j, y in enumerate(YS):
        tr = [r for t in YS if t != y for r in F[t]]
        te = F[y]
        Xb = np.array([r[0] for r in tr]); Xx = np.column_stack([Xb, [r[1] for r in tr]])
        yt = np.array([r[2] for r in tr]); wt = np.array([r[3] for r in tr], float)
        Tb = np.array([r[0] for r in te]); Tx = np.column_stack([Tb, [r[1] for r in te]])
        yy = np.array([r[2] for r in te]); ww = np.array([r[3] for r in te], float)
        out = []
        for X, T in ((Xb, Tb), (Xx, Tx)):
            b = br.wols(X, yt, wt)
            p = np.column_stack([np.ones(len(T)), T]) @ b
            out.append((float((ww * (p - yy) ** 2).sum() / ww.sum()), np.corrcoef(p, yy)[0, 1], b[-1]))
        print(f'  MLB {y + 1}: box MSE {out[0][0]*1e4:.2f} r {out[0][1]:.3f} | box+xw MSE {out[1][0]*1e4:.2f} r {out[1][1]:.3f}'
              f'  xw weight {out[1][2]:.3f}  -> {"xw helps" if out[1][0] < out[0][0] else "xw hurts"}')


if __name__ == '__main__':
    main()
