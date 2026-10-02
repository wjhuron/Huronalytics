"""fld_rate_backtest.py: next-season fielding projection (Savant FRV per defensive out).

rate_y = FRV total / outs on the field (sum of outs_by_pos, catchers included). History
T-1..T-3 weighted d^k by outs, shrunk toward 0 (FRV is position-relative and sums near 0) at
N0 outs, plus a piecewise-linear age term in runs per 1000 outs (peak, yi gain/yr below,
od loss/yr above). Ages from the MLB hitting lines (baseball age, June 30).

Targets T = 2019..2026 (history from 2016), fielders with >= 1500 outs in T and > 0 outs in the
history. Objective: outs_T-weighted MSE of the rate (runs per 1000 outs). LOSO over target
seasons for every swept constant. Baselines: zero (league average) and last season unshrunk.

Usage: python3 scripts/research/projection/fld_rate_backtest.py
Output: console + data/_proj/_fld_rate_backtest.json
"""
import itertools
import json
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
P = os.path.join(ROOT, 'data', '_proj')
TARGETS = list(range(2019, 2027))
MIN_OUTS_T = 1500
GRID = {'d': [0.4, 0.55, 0.7, 0.85, 1.0], 'n0': [500, 1000, 2000, 3000, 4500, 6500],
        'peak': [26, 28, 30, 32, 34, 36], 'yi': [0.0, 0.05, 0.1, 0.15, 0.2], 'od': [0.0, 0.1, 0.2, 0.3, 0.45]}


def season(y):
    F = json.load(open(os.path.join(P, f'frv_{y}.json')))
    ages = {r['id']: r['age'] for r in json.load(open(os.path.join(P, f'lines_hitting_{y}.json'))) if r.get('age') is not None}
    out = {}
    for pid, r in F.items():
        outs = sum(r['outs_by_pos'].values())
        if outs <= 0 or r['total'] is None:
            continue
        out[int(pid)] = (outs, 1000 * r['total'] / outs, ages.get(int(pid)))
    return out


def build():
    S = {y: season(y) for y in range(2016, 2027)}
    D = {}
    for T in TARGETS:
        rows = []
        for pid, (o, r, age) in S[T].items():
            if o < MIN_OUTS_T or age is None:
                continue
            h = [S[T - 1 - k].get(pid, (0, 0.0, None)) for k in range(3)]
            if sum(x[0] for x in h) == 0:
                continue
            rows.append((age, o, r, *[c for x in h for c in x[:2]]))
        D[T] = np.array(rows, float)
    return D


def project(M, d, n0, peak, yi, od):
    num = np.zeros(len(M)); den = np.zeros(len(M))
    for k in range(3):
        o, r = M[:, 3 + 2 * k], M[:, 4 + 2 * k]
        num += d ** k * o * r
        den += d ** k * o
    age = M[:, 0]
    return num / (den + n0) + np.where(age < peak, yi * (peak - age), -od * (age - peak))


def wmse(p, y, w):
    return float((w * (p - y) ** 2).sum() / w.sum())


def main():
    D = build()
    keys = list(GRID)
    combos = list(itertools.product(*[GRID[k] for k in keys]))
    L = np.array([[wmse(project(D[T], *c), D[T][:, 2], D[T][:, 1]) for T in TARGETS] for c in combos])
    print(f'{"T":>5} {"n":>4} {"zero":>8} {"last":>8} {"model":>8}  chosen (d n0 peak yi od)')
    held = []
    for j, T in enumerate(TARGETS):
        o = [k for k in range(len(TARGETS)) if k != j]
        b = int(np.argmin(L[:, o].mean(axis=1)))
        M = D[T]
        z = wmse(np.zeros(len(M)), M[:, 2], M[:, 1])
        last = wmse(np.where(M[:, 3] > 0, M[:, 4], 0.0), M[:, 2], M[:, 1])
        held.append({'T': T, 'zero': z, 'last': last, 'model': float(L[b, j]), 'chosen': dict(zip(keys, combos[b]))})
        print(f'{T:>5} {len(M):>4} {z:8.3f} {last:8.3f} {L[b, j]:8.3f}  {combos[b]}')
    best = int(np.argmin(L.mean(axis=1)))
    print('pooled argmin:', dict(zip(keys, combos[best])))
    curves = {}
    for ki, k in enumerate(keys):
        pts = []
        for v in GRID[k]:
            cc = list(combos[best]); cc[ki] = v
            pts.append((v, float(L[combos.index(tuple(cc))].mean())))
        curves[k] = pts
        print(f'  {k:>4}: ' + '  '.join(f'{v}:{l:.4f}' for v, l in pts))
    # r of projection with target, pooled
    allp = np.concatenate([project(D[T], *combos[best]) for T in TARGETS]); ally = np.concatenate([D[T][:, 2] for T in TARGETS])
    print(f'pooled r(projection, actual) {np.corrcoef(allp, ally)[0, 1]:.3f}; sd projection {allp.std():.2f} vs actual {ally.std():.2f} runs/1000 outs')
    out = {'held': held, 'pooled': dict(zip(keys, combos[best])), 'curves': curves}
    tmp = os.path.join(P, '_fld_rate_backtest.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(out, f, indent=1)
    os.replace(tmp, os.path.join(P, '_fld_rate_backtest.json'))


if __name__ == '__main__':
    main()
