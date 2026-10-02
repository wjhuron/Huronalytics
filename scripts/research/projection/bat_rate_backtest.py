"""bat_rate_backtest.py: next-season batting-rate projection, v1, against Marcel.

Question: what weighted history of wOBA / xwOBA, regressed and age-adjusted, best predicts
a hitter's NEXT-season wOBA? Every rate is a delta from that season's PA-weighted league
mean, so run-environment drift cancels.

    rate_y   = a * xwOBA_y + (1 - a) * wOBA_y                (delta from league y)
    hist     = sum_k d^k PA_{T-1-k} rate_{T-1-k} / sum_k d^k PA_{T-1-k},  k = 0, 1, 2
    proj     = hist * neff / (neff + N0) + age term,  neff = sum_k d^k PA_{T-1-k}
    age term = +y_slope * (peak - age) below peak, -o_slope * (age - peak) above (age in T)

Marcel: a = 0, weights 5/4/3 (d about .8), regress 1200 PA, age +.006 / -.003 per year about
29 applied to the ratio. Implemented as published, as the floor to beat.

Targets T = 2018..2026 (history needs T-3; 2020 enters as a short history season and as a
target), hitters with >= 200 PA in T and > 0 PA in T-1..T-3. Objective: PA_T-weighted MSE of
proj against actual wOBA_T (delta). Secondary: the same against xwOBA_T. Tuning: choose the
grid point on all OTHER target seasons (leave one season out), score it on the held-out one.

Usage: python3 scripts/research/projection/bat_rate_backtest.py
Output: console + data/_proj/_bat_rate_backtest.json
"""
import csv
import itertools
import json
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
P = os.path.join(ROOT, 'data', '_proj')
TARGETS = list(range(2018, 2027))
MIN_PA_T = 200

GRID = {
    'a': [0.0, 0.25, 0.5, 0.75, 1.0],
    'd': [0.4, 0.55, 0.7, 0.85, 1.0],
    'n0': [100, 200, 300, 450, 600, 900, 1200],
    'ys': [0.0, 0.002, 0.004, 0.006, 0.008],
    'os': [0.0, 0.0015, 0.003, 0.0045, 0.006],
    'peak': [26, 27, 28, 29, 30, 31, 32],
}


def load_xstats(y):
    out = {}
    with open(os.path.join(P, f'xstats_batter_{y}.csv'), encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            pa = int(r['pa'])
            if pa <= 0 or r['woba'] in ('', None) or r['est_woba'] in ('', None):
                continue
            out[int(r['player_id'])] = (pa, float(r['woba']), float(r['est_woba']))
    return out


def load_ages(y):
    rows = json.load(open(os.path.join(P, f'lines_hitting_{y}.json')))
    return {r['id']: (r['age'], r['pos']) for r in rows if r['age'] is not None}


def league(xs):
    pa = np.array([v[0] for v in xs.values()], float)
    w = np.array([v[1] for v in xs.values()])
    x = np.array([v[2] for v in xs.values()])
    return (pa * w).sum() / pa.sum(), (pa * x).sum() / pa.sum()


def build():
    X = {y: load_xstats(y) for y in range(2015, 2027)}
    LG = {y: league(X[y]) for y in X}
    A = {y: load_ages(y) for y in range(2015, 2027)}
    data = {}
    for T in TARGETS:
        rows = []
        for pid, (pa_t, w_t, x_t) in X[T].items():
            if pa_t < MIN_PA_T:
                continue
            ag = A[T].get(pid)
            if ag is None or ag[1] == 'P':
                continue
            hist = []
            for k in range(3):
                v = X[T - 1 - k].get(pid)
                if v:
                    lw, lx = LG[T - 1 - k]
                    hist.append((v[0], v[1] - lw, v[2] - lx))
                else:
                    hist.append((0, 0.0, 0.0))
            if sum(h[0] for h in hist) == 0:
                continue
            rows.append((pid, ag[0], pa_t, w_t - LG[T][0], x_t - LG[T][1], *[c for h in hist for c in h]))
        data[T] = np.array(rows, float)
    return data, LG


def project(M, a, d, n0, ys, os_, peak):
    age = M[:, 1]
    num = np.zeros(len(M))
    den = np.zeros(len(M))
    for k in range(3):
        pa, w, x = M[:, 5 + 3 * k], M[:, 6 + 3 * k], M[:, 7 + 3 * k]
        wt = d ** k * pa
        num += wt * (a * x + (1 - a) * w)
        den += wt
    hist = num / den
    proj = hist * den / (den + n0)
    proj += np.where(age < peak, ys * (peak - age), -os_ * (age - peak))
    return proj


def marcel(M, lg_t):
    """Marcel the Monkey (Tango): 5/4/3 on PA, 1200 PA of league average, age on the ratio."""
    num = np.zeros(len(M))
    den = np.zeros(len(M))
    for k, w in enumerate((5, 4, 3)):
        pa, dw = M[:, 5 + 3 * k], M[:, 6 + 3 * k]
        num += w * pa * dw
        den += w * pa
    reg = num / (den + 1200)              # delta from league, regressed
    age = M[:, 1]
    adj = np.where(age < 29, 0.006 * (29 - age), -0.003 * (age - 29))
    return (lg_t + reg) * (1 + adj) - lg_t


def wmse(p, y, w):
    return float((w * (p - y) ** 2).sum() / w.sum())


def main():
    data, LG = build()
    keys = list(GRID)
    combos = list(itertools.product(*[GRID[k] for k in keys]))
    # loss[combo][season] against actual wOBA and against xwOBA
    loss_w = np.zeros((len(combos), len(TARGETS)))
    loss_x = np.zeros((len(combos), len(TARGETS)))
    for j, T in enumerate(TARGETS):
        M = data[T]
        for i, c in enumerate(combos):
            p = project(M, *c)
            loss_w[i, j] = wmse(p, M[:, 3], M[:, 2])
            loss_x[i, j] = wmse(p, M[:, 4], M[:, 2])
    out = {'targets': TARGETS, 'n': {T: len(data[T]) for T in TARGETS}, 'loso': [], 'grid': GRID}
    print(f'{"T":>5} {"n":>4} {"marcel":>8} {"model":>8} {"gain%":>6}  chosen (a d n0 ys os peak)')
    wins = 0
    for j, T in enumerate(TARGETS):
        others = [k for k in range(len(TARGETS)) if k != j]
        best = int(np.argmin(loss_w[:, others].mean(axis=1)))
        M = data[T]
        m = wmse(marcel(M, LG[T][0]), M[:, 3], M[:, 2])
        g = loss_w[best, j]
        wins += g < m
        out['loso'].append({'T': T, 'marcel': m, 'model': g, 'chosen': dict(zip(keys, combos[best]))})
        print(f'{T:>5} {len(M):>4} {m*1e4:8.3f} {g*1e4:8.3f} {100*(1-g/m):6.1f}  {combos[best]}')
    allbest = int(np.argmin(loss_w.mean(axis=1)))
    print(f'model beats Marcel in {wins}/{len(TARGETS)} held-out seasons (MSE x1e4 above)')
    print('pooled argmin:', dict(zip(keys, combos[allbest])))
    # one-at-a-time curves through the pooled argmin, to show each is bracketed
    curves = {}
    for ki, k in enumerate(keys):
        pts = []
        for v in GRID[k]:
            c = list(combos[allbest]); c[ki] = v
            i = combos.index(tuple(c))
            pts.append((v, float(loss_w[i].mean() * 1e4), int((loss_w[i] <= loss_w[allbest]).sum())))
        curves[k] = pts
        print(f'  {k:>4}: ' + '  '.join(f'{v}:{l:.3f}' for v, l, _ in pts))
    out['pooled'] = dict(zip(keys, combos[allbest]))
    out['curves'] = curves
    tmp = os.path.join(P, '_bat_rate_backtest.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(out, f, indent=1)
    os.replace(tmp, os.path.join(P, '_bat_rate_backtest.json'))


if __name__ == '__main__':
    main()
