"""bat_ev_addon.py: exit velocity as a batting projection channel, T 2018-2026, the same replicate test as pit_ev_addon.py.

Base: bat_experience_test exper+aaa held-out projection. Channels from Savant's exit-velocity leaderboard (data/_proj/ev_batter_{y}.csv,
BBE counts): avg EV, EV95% (ev95percent), barrel % (brl_percent). BBE-weighted history .7^k, delta from league, shrunk at N0 BBE. Residual
OLS leaving T out, PA_T weight. T <= 2021 did not inform the earlier atoms screen, which read T 2022-2026.

Usage: python3 scripts/research/projection/bat_ev_addon.py
Output: console + data/_proj/_bat_ev_addon.json
"""
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bat_experience_test as bx

P = bx.v1.P
N0S = [0, 25, 50, 100, 200, 400]
CH = {'ev': 'avg_hit_speed', 'ev95': 'ev95percent', 'brl': 'brl_percent'}


def main():
    tab, lg = {c: {} for c in CH}, {c: {} for c in CH}
    for y in range(2015, 2027):
        rows = list(csv.DictReader(open(os.path.join(P, f'ev_batter_{y}.csv'), encoding='utf-8-sig')))
        for c, col in CH.items():
            t = {int(r['player_id']): (float(r[col]), int(r['attempts'])) for r in rows if r[col] not in ('', None) and int(r['attempts']) > 0}
            tab[c][y] = t; lg[c][y] = sum(v * n for v, n in t.values()) / sum(n for _, n in t.values())
    D, Aaa, Mlb = bx.build()
    held = {h['T']: h['chosen'] for h in json.load(open(os.path.join(P, '_bat_experience_test.json')))['exper+aaa']['held']}
    R = {}
    for T in bx.TARGETS:
        Z = bx.arrays(D[T], bx.bridge_beta(Aaa, Mlb, T))
        R[T] = dict(p=bx.project(Z, *held[T]), y=Z['y'], w=Z['w'], ids=[int(r['id']) for r in D[T]])

    def channel(T, c, n0):
        out = []
        for i in R[T]['ids']:
            num = den = 0.0
            for k in range(3):
                y = T - 1 - k
                r = tab[c].get(y, {}).get(i)
                if r:
                    num += .7 ** k * r[1] * (r[0] - lg[c][y]); den += .7 ** k * r[1]
            out.append(num / (den + n0) if den + n0 > 0 else 0.0)
        return np.array(out)

    Ts = bx.TARGETS
    old = [i for i, T in enumerate(Ts) if T <= 2021]; new = [i for i, T in enumerate(Ts) if T > 2021]
    res = {}
    for c in CH:
        for n0 in N0S:
            C = {T: channel(T, c, n0) for T in Ts}
            g, cf = [], []
            for T in Ts:
                tr = [S for S in Ts if S != T]
                X = np.column_stack([np.ones(sum(len(C[S]) for S in tr)), np.concatenate([C[S] for S in tr])])
                r = np.concatenate([R[S]['y'] - R[S]['p'] for S in tr]); w = np.concatenate([R[S]['w'] for S in tr])
                sw = np.sqrt(w); b = np.linalg.lstsq(X * sw[:, None], r * sw, rcond=None)[0]
                q = R[T]['p'] + np.column_stack([np.ones(len(C[T])), C[T]]) @ b
                m0 = np.average((R[T]['y'] - R[T]['p']) ** 2, weights=R[T]['w']); m1 = np.average((R[T]['y'] - q) ** 2, weights=R[T]['w'])
                g.append(100 * (1 - m1 / m0)); cf.append(b[1])
            g = np.array(g)
            print(f'{c:5s} N0 {n0:>4}: all {g.mean():+.3f}% ({(g>0).sum()}/9)  T<=2021 {g[old].mean():+.3f}% ({(g[old]>0).sum()}/{len(old)}, se {g[old].std(ddof=1)/2:.3f})  T>2021 {g[new].mean():+.3f}% ({(g[new]>0).sum()}/5)  coef {np.mean(cf):+.5f}  {np.round(g,2).tolist()}')
            res[f'{c}_{n0}'] = g.tolist()
    with open(os.path.join(P, '_bat_ev_addon.json'), 'w') as f:
        json.dump(res, f, indent=1)


if __name__ == '__main__':
    main()
