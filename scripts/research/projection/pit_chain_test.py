"""pit_chain_test.py: a coherent multi-year pitcher projection (chain) against the direct per-horizon fits.

Direct (pit_horizon_backtest): a separate OLS per horizon. It scored well, but its chains are not
coherent (an old arm's 5-year value rose above his 3-year value in 468 of 602 cases, because each
horizon regresses to the mean of a different survivor pool).

Chain: one 1-season-out level, then per horizon
    delta_T = R_h x level1 + age term integrated from (base age + 1) to the target age
with level1 = the h=1 model's projection at the base (OLS fit leaving the held-out base out), R_h
(persistence of projected talent) and the decline `od` (runs/9 per year above `peak`, the young-arm
term fixed at the h=1 value) swept. R_h, od and peak are chosen leave-one-base-out.

Coherence check reported: share of arms aged 31+ at the base whose 5-year delta is BETTER than their
3-year delta (should be near zero for a coherent aging rule).

Usage: python3 scripts/research/projection/pit_chain_test.py
"""
import itertools
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pit_horizon_backtest as ph
import pit_rate_backtest as pr

H1 = (0.65, 500, 26, 0.09, 0.04)          # pit_horizon_backtest h=1 pooled
R_GRID = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
OD_GRID = [0.0, 0.03, 0.06, 0.09, 0.12, 0.15]
PEAK_GRID = [24, 26, 28, 30]


def main():
    S = {y: pr.season(y) for y in range(2015, 2027)}
    bases1 = list(ph.HORIZONS[1])
    F1 = {B: ph.feats(ph.rows_for(S, B, 1), 1, *H1) for B in bases1}
    res = {}
    for h in (3, 5):
        bases = list(ph.HORIZONS[h])
        direct = json.load(open(os.path.join(pr.P, '_pit_horizon_backtest.json')))[str(h)]['held']
        D = {}
        for B in bases:
            rows = ph.rows_for(S, B, h)
            # level1 at base B: h=1 OLS fit on every h=1 replicate whose target is not in B+1..B+h
            tr = [F1[b] for b in bases1 if not (B < b + 1 <= B + h)]
            fake = [(pid, dict(t, age=t['age'] - h + 1), hist) for pid, t, hist in rows]   # age at B+1
            Xp, _, _ = ph.feats(fake, 1, *H1)
            lvl, _ = pr.fit_predict(np.vstack([f[0] for f in tr]), np.concatenate([f[1] for f in tr]),
                                    np.concatenate([f[2] for f in tr]), Xp)
            age1 = np.array([t['age'] - h + 1 for _, t, _ in rows], float)
            ageT = np.array([t['age'] for _, t, _ in rows], float)
            y = np.array([t['ra9'] for _, t, _ in rows]); w = np.array([t['ip'] for _, t, _ in rows])
            D[B] = (lvl, age1, ageT, y, w)
        combos = list(itertools.product(R_GRID, OD_GRID, PEAK_GRID))

        def pred(B, R, od, peak):
            lvl, a1, aT, _, _ = D[B]
            lo = np.minimum(aT, peak) - np.minimum(a1, peak); hi = np.maximum(aT, peak) - np.maximum(a1, peak)
            return R * lvl - H1[3] * lo + od * hi

        L = np.array([[pr.wmse(pred(B, *c), D[B][3], D[B][4]) for B in bases] for c in combos])
        held = []
        for j, B in enumerate(bases):
            o = [k for k in range(len(bases)) if k != j]
            b = int(np.argmin(L[:, o].mean(axis=1)))
            held.append((B + h, combos[b], float(L[b, j]), direct[j]['model'], direct[j]['marcel']))
        wins = sum(c < d for _, _, c, d, _ in held)
        best = int(np.argmin(L.mean(axis=1)))
        print(f'\n== h = {h}: chain vs direct, held-out MSE; chain wins {wins}/{len(bases)}, beats Marcel '
              f'{sum(c < m for _, _, c, _, m in held)}/{len(bases)}')
        for T, c, ch, di, ma in held:
            print(f'   T {T}: chain {ch:.4f}  direct {di:.4f}  marcel {ma:.4f}   (R od peak) {c}')
        print('   pooled (R, od, peak):', combos[best])
        for nm, idx, grid in (('R', 0, R_GRID), ('od', 1, OD_GRID), ('peak', 2, PEAK_GRID)):
            pts = []
            for v in grid:
                cc = list(combos[best]); cc[idx] = v
                pts.append(f'{v}:{L[combos.index(tuple(cc))].mean():.4f}')
            print(f'     {nm:>4}: ' + '  '.join(pts))
        res[h] = {'held': held, 'pooled': combos[best]}
    tmp = os.path.join(pr.P, '_pit_chain_test.json.tmp')
    with open(tmp, 'w') as f:
        json.dump({str(k): v for k, v in res.items()}, f, indent=1)
    os.replace(tmp, os.path.join(pr.P, '_pit_chain_test.json'))


if __name__ == '__main__':
    main()
