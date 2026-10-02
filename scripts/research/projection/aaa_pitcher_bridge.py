"""aaa_pitcher_bridge.py: translate a Triple-A pitching season into next-season MLB runs per 9.

Bridge: pitchers with >= 40 IP at Triple-A in Y and >= 30 IP in MLB in Y+1, Y = 2015-2025 (no 2020).
Box lines only (MLB Stats API sportId 11 and 1), every rate a delta from its own league-season:
ra9, fip-core (13 HR + 3 (BB + HBP) - 2 K) / IP, K-BB per BF, each shrunk at N0 BF; age in Y+1; the
target-season starter share (role-conditional, like the MLB model); any MLB ra9/kbb in Y shrunk at
the MLB pitcher N0 (500 BF, pit_rate_backtest).
Arms, OLS refit leave-one-season-out: naive (AAA ra9 alone) and box (all of the above).
Target: MLB ra9 delta in Y+1, IP-weighted MSE.

Usage: python3 scripts/research/projection/aaa_pitcher_bridge.py
Output: console + data/_proj/_aaa_pitcher_bridge.json
"""
import json
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
P = os.path.join(ROOT, 'data', '_proj')
YEARS = [y for y in range(2015, 2026) if y != 2020]
N0_GRID = [100, 200, 400, 700, 1000, 1500]


def table(path):
    out = {}
    for r in json.load(open(path)):
        g = lambda k: int(r.get(k) or 0)
        outs, bf = g('outs'), g('battersFaced')
        if outs <= 0 or bf <= 0:
            continue
        ip = outs / 3
        gp = g('gamesPlayed')
        out[r['id']] = {'ip': ip, 'bf': bf, 'age': r.get('age'), 'name': r.get('name'), 'team': r.get('team'),
                        'gs': g('gamesStarted') / gp if gp else 0.0,
                        'ra9': 9 * g('runs') / ip, 'fip': (13 * g('homeRuns') + 3 * (g('baseOnBalls') + g('hitByPitch')) - 2 * g('strikeOuts')) / ip,
                        'kbb': (g('strikeOuts') - g('baseOnBalls')) / bf}
    lg = {c: sum(v[c] * v['ip'] for v in out.values()) / sum(v['ip'] for v in out.values()) for c in ('ra9', 'fip')}
    lg['kbb'] = sum(v['kbb'] * v['bf'] for v in out.values()) / sum(v['bf'] for v in out.values())
    for v in out.values():
        for c in lg:
            v['d_' + c] = v[c] - lg[c]
    return out


def tables():
    A = {y: table(os.path.join(P, f'aaa_lines_pitching_{y}.json')) for y in range(2015, 2027) if y != 2020}
    M = {y: table(os.path.join(P, f'lines_pitching_{y}.json')) for y in range(2015, 2027)}
    return A, M


def features(a, m_y, gs_t, age_t, n0):
    sh = a['bf'] / (a['bf'] + n0)
    msh = m_y['bf'] / (m_y['bf'] + 500) if m_y else 0.0
    return [a['d_ra9'] * sh, a['d_fip'] * sh, a['d_kbb'] * sh, age_t, gs_t,
            (m_y['d_ra9'] if m_y else 0.0) * msh, (m_y['d_kbb'] if m_y else 0.0) * msh]


def wols(X, y, w):
    A = np.column_stack([np.ones(len(X)), X]); sw = np.sqrt(w)
    b, *_ = np.linalg.lstsq(A * sw[:, None], y * sw, rcond=None)
    return b


def main():
    A, M = tables()
    pairs = {y: [(a, M[y].get(pid), M[y + 1][pid]) for pid, a in A[y].items()
                 if a['ip'] >= 40 and a['age'] is not None and pid in M[y + 1] and M[y + 1][pid]['ip'] >= 30] for y in YEARS}
    print('bridge pairs per season:', {y: len(v) for y, v in pairs.items()})
    res = {}
    for arm in ('naive', 'box'):
        L = np.zeros((len(N0_GRID), len(YEARS))); R = np.zeros_like(L)
        for i, n0 in enumerate(N0_GRID):
            F = {}
            for y in YEARS:
                X = np.array([features(a, m, m1['gs'], a['age'] + 1, n0) for a, m, m1 in pairs[y]])
                if arm == 'naive':
                    X = X[:, :1]
                F[y] = (X, np.array([m1['d_ra9'] for *_, m1 in pairs[y]]), np.array([m1['ip'] for *_, m1 in pairs[y]]))
            for j, y in enumerate(YEARS):
                tr = [F[t] for t in YEARS if t != y]
                b = wols(np.vstack([t[0] for t in tr]), np.concatenate([t[1] for t in tr]), np.concatenate([t[2] for t in tr]))
                p = np.column_stack([np.ones(len(F[y][0])), F[y][0]]) @ b
                L[i, j] = float((F[y][2] * (p - F[y][1]) ** 2).sum() / F[y][2].sum())
                R[i, j] = np.corrcoef(p, F[y][1])[0, 1]
        best = int(np.argmin(L.mean(axis=1)))
        held = [(y + 1, float(L[best, j]), float(R[best, j])) for j, y in enumerate(YEARS)]
        Xall = np.vstack([np.array([features(a, m, m1['gs'], a['age'] + 1, N0_GRID[best]) for a, m, m1 in pairs[y]]) for y in YEARS])
        if arm == 'naive':
            Xall = Xall[:, :1]
        beta = wols(Xall, np.concatenate([[m1['d_ra9'] for *_, m1 in pairs[y]] for y in YEARS]),
                    np.concatenate([[m1['ip'] for *_, m1 in pairs[y]] for y in YEARS]))
        res[arm] = {'held': held, 'n0': N0_GRID[best], 'beta': beta.tolist(), 'curve': {str(n): float(L[i].mean()) for i, n in enumerate(N0_GRID)}}
        print(f'\n== {arm}: N0 curve ' + '  '.join(f'{n}:{L[i].mean():.3f}' for i, n in enumerate(N0_GRID)))
        print('   held-out (T: MSE / r): ' + ' '.join(f'{T}:{l:.2f}/{r:.2f}' for T, l, r in held))
        print('   pooled beta:', np.round(beta, 4).tolist())
    wins = sum(b[1] < n[1] for b, n in zip(res['box']['held'], res['naive']['held']))
    print(f'\nbox beats naive in {wins}/{len(YEARS)}')
    tmp = os.path.join(P, '_aaa_pitcher_bridge.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(res, f, indent=1)
    os.replace(tmp, os.path.join(P, '_aaa_pitcher_bridge.json'))


if __name__ == '__main__':
    main()
