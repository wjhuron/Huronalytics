"""pit_rate_backtest.py: next-season pitcher run-prevention projection, v1, against Marcel.

Per pitcher-season (MLB season lines + Savant expected stats), every channel relative to that
season's league (IP- or BF-weighted):
    ra9   runs per 9                      (the result a club lives with)
    fip   (13 HR + 3 (BB + HBP) - 2 K) / IP   (defense-free result; constant cancels in the delta)
    kbb   (K - BB) / BF
    xw    Savant xwOBA against
History B-2..B weighted d^k by BF, each channel shrunk to league at N0 BF. The projection is an
OLS on those shrunk channels plus the target-season starter share (gs/g in T, so the forecast is
role-conditional: "if he starts" / "if he relieves") and a piecewise-linear age term in RUN
direction (yi = runs/9 shed per year below the peak, od = runs/9 added per year above it). OLS weights are fitted on the OTHER target seasons only (LOSO);
d, N0, peak, yi, od are chosen the same way.

Targets T = 2018..2026, pitchers with >= 30 IP in T and > 0 BF in the history.
Objective: IP_T-weighted MSE against ra9_T (primary) and fip_T (defense-free, secondary).
Marcel (pitchers): 3/2/1 on IP, regress 134 IP to league, no age term for runs. Convention as
published by Tango; the floor to beat.

Usage: python3 scripts/research/projection/pit_rate_backtest.py
Output: console + data/_proj/_pit_rate_backtest.json
"""
import csv
import itertools
import json
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
P = os.path.join(ROOT, 'data', '_proj')
TARGETS = list(range(2018, 2027))
MIN_OUTS_T = 90
GRID = {'d': [0.3, 0.4, 0.5, 0.65, 0.8, 1.0], 'n0': [200, 350, 500, 800],
        'peak': [26, 28, 30, 32], 'yi': [0.0, 0.02, 0.04, 0.06, 0.08], 'od': [0.0, 0.01, 0.02, 0.03, 0.04, 0.06]}
CH = ('ra9', 'fip', 'kbb', 'xw')


def season(y):
    xs = {}
    with open(os.path.join(P, f'xstats_pitcher_{y}.csv'), encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['est_woba'] not in ('', None):
                xs[int(r['player_id'])] = (int(r['pa']), float(r['est_woba']))
    out = {}
    for r in json.load(open(os.path.join(P, f'lines_pitching_{y}.json'))):
        outs, bf = int(r.get('outs') or 0), int(r.get('battersFaced') or 0)
        if outs <= 0 or bf <= 0 or r.get('age') is None:
            continue
        if r.get('pos') not in ('P', 'TWP'):
            continue      # a position player pitching (2026-10-03: they sat in every pool and projected -.8)
        ip = outs / 3
        k, bb, hbp, hr = (int(r.get(c) or 0) for c in ('strikeOuts', 'baseOnBalls', 'hitByPitch', 'homeRuns'))
        g, gs = int(r.get('gamesPlayed') or 0), int(r.get('gamesStarted') or 0)
        x = xs.get(r['id'])
        out[r['id']] = {'ip': ip, 'bf': bf, 'age': r['age'], 'gs': gs / g if g else 0.0,
                        'ra9': 9 * int(r.get('runs') or 0) / ip,
                        'fip': (13 * hr + 3 * (bb + hbp) - 2 * k) / ip,
                        'kbb': (k - bb) / bf, 'xw': x[1] if x else None, 'xw_n': x[0] if x else 0}
    lg = {}
    for c, wk in (('ra9', 'ip'), ('fip', 'ip'), ('kbb', 'bf'), ('xw', 'xw_n')):
        v = [(s[c], s[wk]) for s in out.values() if s[c] is not None and s[wk] > 0]
        lg[c] = sum(a * b for a, b in v) / sum(b for _, b in v)
    for s in out.values():
        for c in CH:
            if s[c] is not None:
                s[c] -= lg[c]
    return out


def build():
    S = {y: season(y) for y in range(2015, 2027)}
    D = {}
    for T in TARGETS:
        rows = []
        for pid, t in S[T].items():
            if t['ip'] * 3 < MIN_OUTS_T:
                continue
            hist = [S[T - 1 - k].get(pid) for k in range(3)]
            if not any(hist):
                continue
            rows.append((pid, t, hist))
        D[T] = rows
    return D


def features(rows, d, n0, peak, yi, od):
    X, y_ra, y_fip, w = [], [], [], []
    for _, t, hist in rows:
        f = []
        for c in CH:
            num = den = 0.0
            for k, h in enumerate(hist):
                if not h or h[c] is None:
                    continue
                e = h['xw_n'] if c == 'xw' else h['bf']
                num += d ** k * e * h[c]
                den += d ** k * e
            f.append(num / (den + n0))
        age = t['age']
        f.append(t['gs'])
        # run direction: a young arm sheds yi runs/9 per year to the peak, an old one adds od
        f.append(-yi * (peak - age) if age < peak else od * (age - peak))
        X.append(f); y_ra.append(t['ra9']); y_fip.append(t['fip']); w.append(t['ip'])
    return np.array(X), np.array(y_ra), np.array(y_fip), np.array(w)


def marcel(rows):
    p = []
    for _, t, hist in rows:
        num = den = 0.0
        for k, h in enumerate(hist):
            if h:
                num += (3 - k) * h['ip'] * h['ra9']
                den += (3 - k) * h['ip']
        p.append(num / (den + 134 * 3))   # 134 IP at the weight of the most recent season
    return np.array(p)


def fit_predict(Xtr, ytr, wtr, Xte):
    """weighted OLS with intercept; the age column enters with a fixed coefficient of 1 (its
    size is the swept yi/od), so it is moved to the offset before the fit."""
    off_tr, off_te = Xtr[:, -1], Xte[:, -1]
    A = np.column_stack([np.ones(len(Xtr)), Xtr[:, :-1]])
    sw = np.sqrt(wtr)
    beta, *_ = np.linalg.lstsq(A * sw[:, None], (ytr - off_tr) * sw, rcond=None)
    return np.column_stack([np.ones(len(Xte)), Xte[:, :-1]]) @ beta + off_te, beta


def wmse(p, y, w):
    return float((w * (p - y) ** 2).sum() / w.sum())


def main():
    D = build()
    keys = list(GRID)
    combos = list(itertools.product(*[GRID[k] for k in keys]))
    F = {}
    for c in combos:
        F[c] = {T: features(D[T], *c) for T in TARGETS}
    res = {}
    for tgt in ('ra9', 'fip'):
        yi = 1 if tgt == 'ra9' else 2
        L = np.zeros((len(combos), len(TARGETS)))
        for i, c in enumerate(combos):
            for j, T in enumerate(TARGETS):
                tr = [F[c][S] for S in TARGETS if S != T]
                Xtr = np.vstack([f[0] for f in tr]); ytr = np.concatenate([f[yi] for f in tr]); wtr = np.concatenate([f[3] for f in tr])
                p, _ = fit_predict(Xtr, ytr, wtr, F[c][T][0])
                L[i, j] = wmse(p, F[c][T][yi], F[c][T][3])
        print(f'\n== target {tgt}')
        print(f'{"T":>5} {"n":>4} {"marcel":>8} {"model":>8} {"gain%":>6}  chosen (d n0 peak yi od)')
        wins = 0; held = []
        for j, T in enumerate(TARGETS):
            o = [k for k in range(len(TARGETS)) if k != j]
            b = int(np.argmin(L[:, o].mean(axis=1)))
            X, yra, yfip, w = F[combos[b]][T]
            m = wmse(marcel(D[T]), yra if tgt == 'ra9' else yfip, w)
            wins += L[b, j] < m
            held.append({'T': T, 'marcel': m, 'model': float(L[b, j]), 'chosen': dict(zip(keys, combos[b]))})
            print(f'{T:>5} {len(X):>4} {m:8.3f} {L[b, j]:8.3f} {100*(1-L[b, j]/m):6.1f}  {combos[b]}')
        print(f'model beats Marcel in {wins}/{len(TARGETS)}')
        best = int(np.argmin(L.mean(axis=1)))
        allX = np.vstack([F[combos[best]][T][0] for T in TARGETS])
        ally = np.concatenate([F[combos[best]][T][yi] for T in TARGETS]); allw = np.concatenate([F[combos[best]][T][3] for T in TARGETS])
        _, beta = fit_predict(allX, ally, allw, allX[:1])
        print('pooled argmin:', dict(zip(keys, combos[best])), ' OLS (int, ' + ', '.join(CH) + ', gs):', np.round(beta, 3).tolist())
        for ki, k in enumerate(keys):
            pts = []
            for v in GRID[k]:
                cc = list(combos[best]); cc[ki] = v
                pts.append(f'{v}:{L[combos.index(tuple(cc))].mean():.4f}')
            print(f'  {k:>4}: ' + '  '.join(pts))
        res[tgt] = {'held': held, 'pooled': dict(zip(keys, combos[best])), 'beta': beta.tolist()}
    tmp = os.path.join(P, '_pit_rate_backtest.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(res, f, indent=1)
    os.replace(tmp, os.path.join(P, '_pit_rate_backtest.json'))


if __name__ == '__main__':
    main()
