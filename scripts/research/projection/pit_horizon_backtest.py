"""pit_horizon_backtest.py: pitcher runs projection at 1, 3 and 5 seasons out.

pit_rate_backtest's model (shrunk ra9 / fip / kbb / xw history, target-season starter share, OLS
fitted LOSO) with base season B, history B-2..B, target T = B + h. Savant from 2015, so
h=1 B 2017-2025 (9), h=3 B 2017-2023 (7), h=5 B 2017-2021 (5). The age term is integrated from
the history's weighted age to the target age: -yi per year below the peak, +od per year above
(run direction). Stuff+ history starts in 2021, so it is not in this test; pit_stuff_addon.py
measured it at h = 1 only.

Usage: python3 scripts/research/projection/pit_horizon_backtest.py
Output: console + data/_proj/_pit_horizon_backtest.json
"""
import itertools
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pit_rate_backtest as pr

HORIZONS = {1: range(2017, 2026), 3: range(2017, 2024), 5: range(2017, 2022)}
GRID = {'d': [0.2, 0.3, 0.4, 0.5, 0.65], 'n0': [150, 300, 500], 'peak': [22, 24, 26, 28, 30, 32, 34],
        'yi': [0.0, 0.03, 0.06, 0.09, 0.12, 0.16, 0.2], 'od': [0.04, 0.06, 0.08, 0.1, 0.14, 0.18, 0.24]}


def rows_for(S, B, h):
    T = B + h
    out = []
    for pid, t in S[T].items():
        if t['ip'] * 3 < pr.MIN_OUTS_T:
            continue
        hist = [S[B - k].get(pid) for k in range(3)]
        if any(hist):
            out.append((pid, t, hist))
    return out


def feats(rows, h, d, n0, peak, yi, od):
    X, y, w = [], [], []
    for _, t, hist in rows:
        f = []
        for c in pr.CH:
            num = den = 0.0
            for k, hh in enumerate(hist):
                if not hh or hh[c] is None:
                    continue
                e = hh['xw_n'] if c == 'xw' else hh['bf']
                num += d ** k * e * hh[c]; den += d ** k * e
            f.append(num / (den + n0))
        f.append(t['gs'])
        wsum = sum(d ** k * hh['bf'] for k, hh in enumerate(hist) if hh)
        a0 = sum(d ** k * hh['bf'] * (t['age'] - h - k) for k, hh in enumerate(hist) if hh) / wsum
        a1 = t['age']
        lo = min(a1, peak) - min(a0, peak); hi = max(a1, peak) - max(a0, peak)
        f.append(-yi * lo + od * hi)
        X.append(f); y.append(t['ra9']); w.append(t['ip'])
    return np.array(X), np.array(y), np.array(w)


def main():
    S = {y: pr.season(y) for y in range(2015, 2027)}
    keys = list(GRID)
    combos = list(itertools.product(*[GRID[k] for k in keys]))
    out = {}
    for h, bases in HORIZONS.items():
        bases = list(bases)
        R = {B: rows_for(S, B, h) for B in bases}
        F = {c: {B: feats(R[B], h, *c) for B in bases} for c in combos}
        L = np.zeros((len(combos), len(bases)))
        for i, c in enumerate(combos):
            for j, B in enumerate(bases):
                tr = [F[c][b] for b in bases if b != B]
                p, _ = pr.fit_predict(np.vstack([f[0] for f in tr]), np.concatenate([f[1] for f in tr]),
                                      np.concatenate([f[2] for f in tr]), F[c][B][0])
                L[i, j] = pr.wmse(p, F[c][B][1], F[c][B][2])
        held = []
        for j, B in enumerate(bases):
            o = [k for k in range(len(bases)) if k != j]
            b = int(np.argmin(L[:, o].mean(axis=1)))
            mar = pr.wmse(pr.marcel(R[B]), F[combos[b]][B][1], F[combos[b]][B][2])
            held.append({'B': B, 'model': float(L[b, j]), 'marcel': mar, 'chosen': dict(zip(keys, combos[b]))})
        best = int(np.argmin(L.mean(axis=1)))
        wins = sum(x['model'] < x['marcel'] for x in held)
        print(f'\n== h = {h}  n = {[len(R[B]) for B in bases]}  beats Marcel {wins}/{len(bases)}')
        print('  held-out gain vs Marcel: ' + ' '.join(f'{x["B"]+h}:{100*(1-x["model"]/x["marcel"]):+.1f}%' for x in held))
        print('  pooled:', dict(zip(keys, combos[best])))
        curves = {}
        for ki, k in enumerate(keys):
            pts = []
            for v in GRID[k]:
                cc = list(combos[best]); cc[ki] = v
                pts.append((v, float(L[combos.index(tuple(cc))].mean())))
            curves[k] = pts
            print(f'    {k:>4}: ' + '  '.join(f'{v}:{l:.4f}' for v, l in pts))
        out[h] = {'held': held, 'pooled': dict(zip(keys, combos[best])), 'curves': curves}
    tmp = os.path.join(pr.P, '_pit_horizon_backtest.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(out, f, indent=1)
    os.replace(tmp, os.path.join(pr.P, '_pit_horizon_backtest.json'))


if __name__ == '__main__':
    main()
