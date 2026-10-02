"""sprint_backtest.py: next-season sprint speed projection (the baserunning input).

Savant serves Baserunning Run Value for the current season only, so baserunning itself cannot be
backtested. Sprint speed has history from 2015, and the shipped hWAR fill already maps it to
baserunning runs (pipeline.hwar.baserunning_fill: BRV per advance = a + b x sprint, r ~.70 live).
So the projection forecasts sprint speed, and the conversion stays the live hWAR relation.

    proj_T = lg_T + [sum_k d^k n_k (s_k - lg_k)] / (sum_k d^k n_k + N0) - decline x (age_T - age_base)
             + extra decline per year above `knee`

n = competitive runs (Savant's own sample size). Ages from Savant's file (season age).
Targets T = 2018..2026, runners with >= 10 competitive runs in T and >= 1 in the history.
Objective: runs_T-weighted MSE in ft/s. LOSO over target seasons for every swept constant.
Baselines: last season unshrunk, and last season with no aging.

Usage: python3 scripts/research/projection/sprint_backtest.py
Output: console + data/_proj/_sprint_backtest.json
"""
import csv
import itertools
import json
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
P = os.path.join(ROOT, 'data', '_proj')
TARGETS = list(range(2018, 2027))
MIN_RUNS_T = 10
GRID = {'d': [0.05, 0.1, 0.2, 0.3, 0.5], 'n0': [0, 1, 2, 4, 8],
        'dec': [0.15, 0.2, 0.25, 0.3, 0.4], 'knee': [24, 26, 28, 30, 32], 'extra': [-0.05, -0.025, 0.0, 0.025, 0.05]}


def season(y):
    out = {}
    with open(os.path.join(P, f'sprint_{y}.csv'), encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            try:
                out[int(r['player_id'])] = (float(r['sprint_speed']), int(r['competitive_runs'] or 0), int(r['age']))
            except (ValueError, KeyError):
                continue
    pool = [v for v in out.values() if v[1] > 0]
    lg = sum(s * n for s, n, _ in pool) / sum(n for _, n, _ in pool)
    return out, lg


def build():
    S = {y: season(y) for y in range(2015, 2027)}
    D = {}
    for T in TARGETS:
        cur, lg_t = S[T]
        rows = []
        for pid, (s, n, age) in cur.items():
            if n < MIN_RUNS_T:
                continue
            h = []
            for k in range(3):
                v = S[T - 1 - k][0].get(pid)
                h.append((v[0] - S[T - 1 - k][1], v[1]) if v and v[1] > 0 else (0.0, 0))
            if sum(x[1] for x in h) == 0:
                continue
            last = S[T - 1][0].get(pid)
            rows.append((age, n, s - lg_t, *[c for x in h for c in x], (last[0] - S[T - 1][1]) if last and last[1] > 0 else np.nan))
        D[T] = np.array(rows, float)
    return D


def project(M, d, n0, dec, knee, extra):
    num = np.zeros(len(M)); den = np.zeros(len(M))
    for k in range(3):
        dev, n = M[:, 3 + 2 * k], M[:, 4 + 2 * k]
        num += d ** k * n * dev
        den += d ** k * n
    age = M[:, 0]
    # the history is about one year younger than T on average; aging is the change to T
    return num / (den + n0) - dec - extra * np.clip(age - knee, 0, None)


def wmse(p, y, w):
    ok = ~np.isnan(p)
    return float((w[ok] * (p[ok] - y[ok]) ** 2).sum() / w[ok].sum())


def main():
    D = build()
    keys = list(GRID)
    combos = list(itertools.product(*[GRID[k] for k in keys]))
    L = np.array([[wmse(project(D[T], *c), D[T][:, 2], D[T][:, 1]) for T in TARGETS] for c in combos])
    print(f'{"T":>5} {"n":>4} {"last":>7} {"model":>7}  chosen (d n0 dec knee extra)')
    held = []
    for j, T in enumerate(TARGETS):
        o = [k for k in range(len(TARGETS)) if k != j]
        b = int(np.argmin(L[:, o].mean(axis=1)))
        M = D[T]
        last = wmse(M[:, -1], M[:, 2], M[:, 1])
        held.append({'T': T, 'last': last, 'model': float(L[b, j]), 'chosen': dict(zip(keys, combos[b]))})
        print(f'{T:>5} {len(M):>4} {last:7.4f} {L[b, j]:7.4f}  {combos[b]}')
    best = int(np.argmin(L.mean(axis=1)))
    print('pooled argmin:', dict(zip(keys, combos[best])))
    curves = {}
    for ki, k in enumerate(keys):
        pts = []
        for v in GRID[k]:
            cc = list(combos[best]); cc[ki] = v
            pts.append((v, float(L[combos.index(tuple(cc))].mean())))
        curves[k] = pts
        print(f'  {k:>5}: ' + '  '.join(f'{v}:{l:.4f}' for v, l in pts))
    out = {'held': held, 'pooled': dict(zip(keys, combos[best])), 'curves': curves}
    tmp = os.path.join(P, '_sprint_backtest.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(out, f, indent=1)
    os.replace(tmp, os.path.join(P, '_sprint_backtest.json'))


if __name__ == '__main__':
    main()
