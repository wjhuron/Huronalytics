"""bat_atoms_addon.py: do the Huronalytics hitter atoms add to the batting projection?

Base: bat_experience_test exper+aaa held-out projection of wOBA vs league. Targets T 2022-2026, because the atom
frames (data/_hitter_frames_2026_09.pkl, built by hitterplus_descriptive.py on full 2026) start in 2021.
Channels: each atom, centered on its season's sample-weighted mean, history d^k weighted by its own count, shrunk at
N0_A counts to 0 (league). Residual OLS fit leaving T out, PA_T weighted MSE gain, wins out of 5. N0_A swept per
atom; the sweep's curve is printed, and the reported gain is the mean over the grid AND the best-on-grid value, since
choosing N0 on the same five seasons flatters the best one. Hitters with no frame history get 0 for the channel.

Usage: python3 scripts/research/projection/bat_atoms_addon.py
Output: console + data/_proj/_bat_atoms_addon.json
"""
import json
import os
import pickle
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bat_experience_test as bx

P = bx.v1.P
ROOT = bx.v1.ROOT if hasattr(bx.v1, 'ROOT') else os.path.dirname(os.path.dirname(P))
TARGETS = [2022, 2023, 2024, 2025, 2026]
D_ = 0.7
N0S = [0, 25, 50, 100, 200, 400, 800]
ATOMS = {'bb': 'nbip', 'ev95': 'nbip', 'xwcon': 'nbip', 'sd': 'n_dec', 'chase': 'n_dec', 'swing_pct': 'n_dec',
         'ct_all': 'n_ct_all', 'con': 'n_con', 'zcon': 'n_zcon', 'ocon': 'n_ocon'}
SETS = {'BB+SD+CT': ['bb', 'sd', 'ct_all'], 'ev95+ct': ['ev95', 'ct_all'], 'bb+ev95': ['bb', 'ev95']}


def main():
    F = pickle.load(open(os.path.join(os.path.dirname(P), '_hitter_frames_2026_09.pkl'), 'rb'))
    lg = {}
    for y, rows in F.items():
        lg[y] = {}
        for a, n in ATOMS.items():
            v = [(r[a], r[n]) for r in rows.values() if r.get(a) is not None and r.get(n)]
            lg[y][a] = sum(x * m for x, m in v) / sum(m for _, m in v)
    D, Aaa, Mlb = bx.build()
    held = {h['T']: h['chosen'] for h in json.load(open(os.path.join(P, '_bat_experience_test.json')))['exper+aaa']['held']}
    R = {}
    for T in TARGETS:
        Z = bx.arrays(D[T], bx.bridge_beta(Aaa, Mlb, T))
        R[T] = dict(p=bx.project(Z, *held[T]), y=Z['y'], w=Z['w'], ids=[str(int(r['id'])) for r in D[T]])

    def channel(T, a, n0):
        out = []
        for i in R[T]['ids']:
            num = den = 0.0
            for k in range(3):
                y = T - 1 - k
                r = F.get(y, {}).get(i)
                if r and r.get(a) is not None and r.get(ATOMS[a]):
                    wt = D_ ** k * r[ATOMS[a]]
                    num += wt * (r[a] - lg[y][a]); den += wt
            out.append(num / (den + n0) if den + n0 > 0 else 0.0)
        return np.array(out)

    def loso(chs):
        g, cf = [], []
        for T in TARGETS:
            tr = [S for S in TARGETS if S != T]
            X = np.vstack([np.column_stack([np.ones(len(chs[S][0]))] + chs[S]) for S in tr])
            r = np.concatenate([R[S]['y'] - R[S]['p'] for S in tr]); w = np.concatenate([R[S]['w'] for S in tr])
            sw = np.sqrt(w); b = np.linalg.lstsq(X * sw[:, None], r * sw, rcond=None)[0]
            q = R[T]['p'] + np.column_stack([np.ones(len(chs[T][0]))] + chs[T]) @ b
            m0 = np.average((R[T]['y'] - R[T]['p']) ** 2, weights=R[T]['w']); m1 = np.average((R[T]['y'] - q) ** 2, weights=R[T]['w'])
            g.append(1 - m1 / m0); cf.append(b)
        return np.array(g), np.mean(cf, axis=0)

    res = {}
    print('base MSE by T', {T: round(float(np.average((R[T]['y'] - R[T]['p']) ** 2, weights=R[T]['w'])), 6) for T in TARGETS})
    for a in ATOMS:
        curve = {}
        C = {n0: {T: [channel(T, a, n0)] for T in TARGETS} for n0 in N0S}
        for n0 in N0S:
            g, cf = loso(C[n0]); curve[n0] = (g, cf)
        best = max(N0S, key=lambda n: curve[n][0].mean())
        g = curve[best][0]
        print(f'{a:10s} gain by N0 ' + ' '.join(f'{n}:{100*curve[n][0].mean():+.2f}' for n in N0S) + f' | best N0 {best}: {100*g.mean():+.2f}% se {100*g.std(ddof=1)/np.sqrt(5):.2f} wins {int((g>0).sum())}/5 per T {np.round(100*g,2).tolist()} coef {curve[best][1][1]:.2e}')
        res[a] = {str(n): curve[n][0].tolist() for n in N0S}
    for name, atoms in SETS.items():
        for n0 in (100, 400):
            C = {T: [channel(T, a, n0) for a in atoms] for T in TARGETS}
            g, cf = loso(C)
            print(f'SET {name:10s} N0 {n0}: {100*g.mean():+.2f}% se {100*g.std(ddof=1)/np.sqrt(5):.2f} wins {int((g>0).sum())}/5 per T {np.round(100*g,2).tolist()} coef {np.round(cf[1:],5).tolist()}')
            res[f'{name}_{n0}'] = g.tolist()
    with open(os.path.join(P, '_bat_atoms_addon.json'), 'w') as f:
        json.dump(res, f, indent=1)


if __name__ == '__main__':
    main()
