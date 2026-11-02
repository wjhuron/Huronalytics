"""pit_ev_addon.py: average exit velocity allowed as a pitcher projection channel, on replicates it was not chosen on.

pit_channels_addon.py screened 15 channels on T 2022-2026 and EV allowed came out best on RA9 (N0 flat 50-400). That is a
selection on five seasons. Savant's exit-velocity leaderboard (data/_proj/ev_pitcher_{y}.csv, min 1 BBE) reaches 2015, so T 2018-2021
are independent replicates. Base: pit_rate_backtest features plus experience term k 20, no Stuff+ because its history
starts in 2021 (the T 2022-2026 rows of this file are therefore a different base from the screen's). EV channel: BBE-weighted
history d^k, delta from the season's BBE-weighted league mean, in mph, shrunk at N0 BBE. OLS jointly refit leaving T out, IP_T
weight, every pitcher with >= 1 out in T. 2020's history counts are left unscaled (60-game season shrinks a little harder);
T 2020 itself stays a replicate, flagged. N0 values tested: 100 and 250 fixed from the screen, others printed for the curve.

Usage: python3 scripts/research/projection/pit_ev_addon.py
Output: console + data/_proj/_pit_ev_addon.json
"""
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pit_experience_test as px
import pit_rate_backtest as pr

TARGETS = list(range(2018, 2027))
N0S = [0, 50, 100, 250, 400, 1000]


def ev_table():
    tab, lg = {}, {}
    for y in range(2015, 2027):
        t = {}
        with open(os.path.join(pr.P, f'ev_pitcher_{y}.csv'), encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                if r['avg_hit_speed'] and int(r['attempts']) > 0:
                    t[int(r['player_id'])] = (float(r['avg_hit_speed']), int(r['attempts']))
        tab[y] = t
        lg[y] = sum(v * n for v, n in t.values()) / sum(n for _, n in t.values())
    return tab, lg


def main():
    tab, lg = ev_table()
    print('league EV', {y: round(v, 2) for y, v in lg.items()})
    S = {y: pr.season(y) for y in range(2015, 2027)}
    D = {}
    for T in TARGETS:
        rows = [(pid, t, [S[T - 1 - k].get(pid) for k in range(3)]) for pid, t in S[T].items() if any(S[T - 1 - k].get(pid) for k in range(3))]
        X, yra, yf, w = pr.features(rows, *px.PAR)
        E = np.array([sum(h['bf'] for h in hist if h) for _, _, hist in rows], float)
        D[T] = dict(rows=rows, F=np.column_stack([X[:, :-1], 1 / (1 + E / 20)]), age=X[:, -1], y=yra, yf=yf, w=w)

    def channel(T, n0, d=px.PAR[0]):
        out = []
        for pid, _, _ in D[T]['rows']:
            num = den = 0.0
            for k in range(3):
                y = T - 1 - k
                r = tab[y].get(int(pid))
                if r:
                    num += d ** k * r[1] * (r[0] - lg[y]); den += d ** k * r[1]
            out.append(num / (den + n0) if den + n0 > 0 else 0.0)
        return np.array(out)

    def loso(ch, key):
        L, B = [], []
        for T in TARGETS:
            tr = [s for s in TARGETS if s != T]
            b = lambda s: np.column_stack([D[s]['F']] + ([ch[s]] if ch else []) + [D[s]['age']])
            p, beta = pr.fit_predict(np.vstack([b(s) for s in tr]), np.concatenate([D[s][key] for s in tr]), np.concatenate([D[s]['w'] for s in tr]), b(T))
            L.append(pr.wmse(p, D[T][key], D[T]['w'])); B.append(beta[-1])
        return np.array(L), float(np.mean(B))

    res = {}
    old = [i for i, T in enumerate(TARGETS) if T <= 2021]; new = [i for i, T in enumerate(TARGETS) if T > 2021]
    for key, lab in (('y', 'RA9'), ('yf', 'FIP')):
        base, _ = loso(None, key)
        print(f'\n== {lab} base MSE ' + ' '.join(f'{T}:{b:.3f}' for T, b in zip(TARGETS, base)))
        for n0 in N0S:
            L, c = loso({T: channel(T, n0) for T in TARGETS}, key)
            g = 100 * (1 - L / base)
            print(f'  N0 {n0:>5}: all {g.mean():+.3f}% ({(g>0).sum()}/9)  T<=2021 {g[old].mean():+.3f}% ({(g[old]>0).sum()}/{len(old)}, se {g[old].std(ddof=1)/np.sqrt(len(old)):.3f})  T>2021 {g[new].mean():+.3f}% ({(g[new]>0).sum()}/{len(new)})  coef per mph {c:+.4f}  {np.round(g,2).tolist()}')
            res[f'{lab}_{n0}'] = dict(gain=g.tolist(), coef=c)
    with open(os.path.join(pr.P, '_pit_ev_addon.json'), 'w') as f:
        json.dump(res, f, indent=1)


if __name__ == '__main__':
    main()
