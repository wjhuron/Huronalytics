"""aaa_hitter_bridge.py: translate a Triple-A season into a next-season MLB wOBA projection.

Bridge sample: hitters with >= 200 PA at Triple-A in Y and >= 100 PA in MLB in Y+1, Y = 2015-2025
(no 2020 minor-league season). Box-score lines (MLB Stats API, sportId 11 and 1). Every rate is a
delta from its own league-season (AAA rates against the AAA league, MLB against MLB; fixed 2026
Guts weights for wOBA). Inputs, AAA side: wOBA, K%, BB%, ISO deltas, each shrunk at N0 PA; age in
Y+1. MLB side: any MLB wOBA delta in Y (shrunk, PA-weighted), so a September call-up's MLB sample
counts. Target: MLB wOBA delta in Y+1, PA-weighted MSE.

Arms (OLS refit leave-one-season-out, N0 swept with the same LOSO):
  naive     a single translation factor on the AAA wOBA delta plus an intercept (the level gap)
  box       AAA wOBA, K%, BB%, ISO + age + MLB-in-Y
Reports held-out MSE per season, wins of box over naive, r, and the pooled coefficients.

Usage: python3 scripts/research/projection/aaa_hitter_bridge.py
Output: console + data/_proj/_aaa_hitter_bridge.json
"""
import json
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
P = os.path.join(ROOT, 'data', '_proj')
W = {'BB': 0.698, 'HBP': 0.729, '1B': 0.89, '2B': 1.261, '3B': 1.596, 'HR': 2.049}
YEARS = [y for y in range(2015, 2026) if y != 2020]
N0_GRID = [100, 200, 400, 700, 1000, 1500, 2500]


def rates(path):
    out = {}
    for r in json.load(open(path)):
        if r.get('pos') == 'P':
            continue
        g = lambda k: int(r.get(k) or 0)
        ab, bb, ibb, hbp, sf, so = g('atBats'), g('baseOnBalls'), g('intentionalWalks'), g('hitByPitch'), g('sacFlies'), g('strikeOuts')
        h, d2, d3, hr = g('hits'), g('doubles'), g('triples'), g('homeRuns')
        pa = g('plateAppearances'); den = ab + bb - ibb + sf + hbp
        if pa <= 0 or den <= 0 or ab <= 0:
            continue
        woba = (W['BB'] * (bb - ibb) + W['HBP'] * hbp + W['1B'] * (h - d2 - d3 - hr) + W['2B'] * d2 + W['3B'] * d3 + W['HR'] * hr) / den
        out[r['id']] = {'pa': pa, 'woba': woba, 'k': so / pa, 'bb': bb / pa, 'iso': (d2 + 2 * d3 + 3 * hr) / ab,
                        'age': r.get('age'), 'name': r.get('name'), 'team': r.get('team'), 'pos': r.get('pos')}
    lg = {c: sum(v[c] * v['pa'] for v in out.values()) / sum(v['pa'] for v in out.values()) for c in ('woba', 'k', 'bb', 'iso')}
    for v in out.values():
        for c in lg:
            v['d_' + c] = v[c] - lg[c]
    return out, lg


def season_tables():
    A = {y: rates(os.path.join(P, f'aaa_lines_hitting_{y}.json')) for y in range(2015, 2027) if y != 2020}
    M = {y: rates(os.path.join(P, f'lines_hitting_{y}.json')) for y in range(2015, 2027)}
    return A, M


def features(a, m_y, n0):
    sh = a['pa'] / (a['pa'] + n0)
    mlb = (m_y['d_woba'] * m_y['pa'] / (m_y['pa'] + 450)) if m_y else 0.0     # the MLB batting N0 (bat_rate_backtest)
    return [a['d_woba'] * sh, a['d_k'] * sh, a['d_bb'] * sh, a['d_iso'] * sh, a['age'] + 1, mlb, 1.0 if m_y else 0.0]


def wols(X, y, w):
    A = np.column_stack([np.ones(len(X)), X]); sw = np.sqrt(w)
    b, *_ = np.linalg.lstsq(A * sw[:, None], y * sw, rcond=None)
    return b


def main():
    A, M = season_tables()
    pairs = {}
    for y in YEARS:
        rows = []
        for pid, a in A[y][0].items():
            if a['pa'] < 200 or a['age'] is None:
                continue
            m1 = M[y + 1][0].get(pid)
            if not m1 or m1['pa'] < 100:
                continue
            rows.append((a, M[y][0].get(pid), m1))
        pairs[y] = rows
    print('bridge pairs per season:', {y: len(v) for y, v in pairs.items()})
    res = {}
    for arm in ('naive', 'box'):
        L = np.zeros((len(N0_GRID), len(YEARS))); R = np.zeros_like(L)
        for i, n0 in enumerate(N0_GRID):
            F = {}
            for y in YEARS:
                X = np.array([features(a, m, n0) for a, m, _ in pairs[y]])
                if arm == 'naive':
                    X = X[:, :1]
                F[y] = (X, np.array([m1['d_woba'] for _, _, m1 in pairs[y]]), np.array([m1['pa'] for _, _, m1 in pairs[y]], float))
            for j, y in enumerate(YEARS):
                tr = [F[t] for t in YEARS if t != y]
                b = wols(np.vstack([t[0] for t in tr]), np.concatenate([t[1] for t in tr]), np.concatenate([t[2] for t in tr]))
                p = np.column_stack([np.ones(len(F[y][0])), F[y][0]]) @ b
                L[i, j] = float((F[y][2] * (p - F[y][1]) ** 2).sum() / F[y][2].sum())
                R[i, j] = np.corrcoef(p, F[y][1])[0, 1]
        held = []
        for j, y in enumerate(YEARS):
            o = [k for k in range(len(YEARS)) if k != j]
            b = int(np.argmin(L[:, o].mean(axis=1)))
            held.append((y + 1, N0_GRID[b], float(L[b, j]), float(R[b, j])))
        best = int(np.argmin(L.mean(axis=1)))
        F_all = [np.array([features(a, m, N0_GRID[best]) for a, m, _ in pairs[y]]) for y in YEARS]
        X_all = np.vstack(F_all)[:, :1] if arm == 'naive' else np.vstack(F_all)
        beta = wols(X_all, np.concatenate([[m1['d_woba'] for _, _, m1 in pairs[y]] for y in YEARS]),
                    np.concatenate([[m1['pa'] for _, _, m1 in pairs[y]] for y in YEARS]).astype(float))
        res[arm] = {'held': held, 'n0': N0_GRID[best], 'beta': beta.tolist(),
                    'curve': {str(n): float(L[i].mean()) for i, n in enumerate(N0_GRID)}}
        print(f'\n== {arm}: N0 curve ' + '  '.join(f'{n}:{L[i].mean()*1e4:.3f}' for i, n in enumerate(N0_GRID)))
        print('   held-out (T, N0, MSE x1e4, r): ' + ' '.join(f'{T}:{l*1e4:.2f}/{r:.2f}' for T, _, l, r in held))
        print('   pooled beta (int, ' + ('aaa_woba' if arm == 'naive' else 'aaa_woba, k, bb, iso, age, mlb_y, has_mlb_y') + '):', np.round(beta, 4).tolist())
    wins = sum(b[2] < n[2] for b, n in zip(res['box']['held'], res['naive']['held']))
    print(f'\nbox beats naive in {wins}/{len(YEARS)} held-out seasons')
    tmp = os.path.join(P, '_aaa_hitter_bridge.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(res, f, indent=1)
    os.replace(tmp, os.path.join(P, '_aaa_hitter_bridge.json'))


if __name__ == '__main__':
    main()
