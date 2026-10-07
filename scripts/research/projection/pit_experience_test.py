"""pit_experience_test.py: the pitcher projection on EVERY pitcher, with experience and Triple-A terms.

Same question as bat_experience_test.py for runs per 9 (pit_rate_backtest features: shrunk ra9 /
fip / kbb / xw history, target start share, age term at the pit_rate_backtest pooled settings). The v1
fit and score used pitchers with >= 30 IP in T. Here: every pitcher with >= 1 out in T (2018-2026) and
>= 1 MLB BF in T-3..T-1, IP_T-weighted MSE, OLS refit leave one target season out. Arms:
  v1pool    OLS fitted on the >= 30 IP pool only (as shipped), scored on everyone
  wide      the same features, OLS fitted on everyone
  +exper    wide plus x_E = 1 / (1 + E / k), E = raw history BF (k swept; OLS learns the size)
  +aaa      +exper plus the latest Triple-A season in T-1/T-2: d_fip and d_kbb shrunk at 400 BF and a
            has-AAA flag (AAA box lines; zeros when absent)
Calibration (IP-weighted mean of actual minus projected, runs per 9) by history BF bin, and per-bin MSE.

Usage: python3 scripts/research/projection/pit_experience_test.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aaa_pitcher_bridge as apb
import pit_rate_backtest as pr

TARGETS = list(range(2018, 2027))
PAR = (0.65, 500, 28, 0.04, 0.01)
BINS = [(1, 100), (100, 300), (300, 700), (700, 1500), (1500, 10 ** 6)]
K_GRID = [5, 10, 20, 35, 50, 100, 200]


def build():
    S = {y: pr.season(y) for y in range(2015, 2027)}
    A, _ = apb.tables()
    D = {}
    for T in TARGETS:
        rows, extra = [], []
        for pid, t in S[T].items():
            hist = [S[T - 1 - k].get(pid) for k in range(3)]
            if not any(hist):
                continue
            E = sum(h['bf'] for h in hist if h)
            aa = next((A[y][pid] for y in (T - 1, T - 2) if y in A and pid in A[y]), None)
            rows.append((pid, t, hist))
            sh = aa['bf'] / (aa['bf'] + 400) if aa else 0.0
            extra.append((E, aa['d_fip'] * sh if aa else 0.0, aa['d_kbb'] * sh if aa else 0.0, 1.0 if aa else 0.0))
        X, yra, _, w = pr.features(rows, *PAR)
        D[T] = {'X': X, 'y': yra, 'w': w, 'E': np.array([e[0] for e in extra], float),
                'A': np.array([e[1:] for e in extra], float)}
    return D


def design(z, arm, k):
    X = z['X']
    cols = [X[:, :-1]]
    if arm in ('+exper', '+aaa'):
        cols.append((1 / (1 + z['E'] / k))[:, None])
    if arm == '+aaa':
        cols.append(z['A'])
    return np.column_stack(cols + [X[:, -1]])          # age offset stays last (fit_predict convention)


def run(D, arm, k):
    preds = {}
    for T in TARGETS:
        tr = [S for S in TARGETS if S != T]
        if arm == 'v1pool':
            masks = {S: D[S]['w'] >= 30 for S in tr}
        else:
            masks = {S: np.ones(len(D[S]['y']), bool) for S in tr}
        Xtr = np.vstack([design(D[S], arm, k)[masks[S]] for S in tr])
        ytr = np.concatenate([D[S]['y'][masks[S]] for S in tr]); wtr = np.concatenate([D[S]['w'][masks[S]] for S in tr])
        preds[T], _ = pr.fit_predict(Xtr, ytr, wtr, design(D[T], arm, k))
    return preds


def score(D, preds, m_fn=None):
    out = []
    for T in TARGETS:
        z = D[T]; m = np.ones(len(z['y']), bool) if m_fn is None else m_fn(z)
        out.append(float((z['w'][m] * (preds[T][m] - z['y'][m]) ** 2).sum() / z['w'][m].sum()) if m.any() else np.nan)
    return out


def main():
    D = build()
    print('pool per season:', {T: len(D[T]['y']) for T in TARGETS})
    res = {}
    for arm in ('v1pool', 'wide'):
        res[arm] = run(D, arm, None)
    for arm in ('+exper', '+aaa'):
        curve = {}
        for k in K_GRID:
            curve[k] = (run(D, arm, k),)
            curve[k] += (np.mean(score(D, curve[k][0])),)
        kb = min(curve, key=lambda kk: curve[kk][1])
        print(f'{arm}: k curve ' + '  '.join(f'{kk}:{curve[kk][1]:.4f}' for kk in K_GRID) + f'  -> k {kb}')
        res[arm] = curve[kb][0]
    base = score(D, res['v1pool'])
    for arm in res:
        s = score(D, res[arm])
        print(f'\n== {arm}: mean MSE {np.mean(s):.4f}  beats v1pool {sum(a < b for a, b in zip(s, base))}/{len(TARGETS)}')
        for lo, hi in BINS:
            f = lambda z: (z['E'] >= lo) & (z['E'] < hi)
            bias = np.mean([float((D[T]['w'][f(D[T])] * (D[T]['y'][f(D[T])] - res[arm][T][f(D[T])])).sum() / D[T]['w'][f(D[T])].sum()) for T in TARGETS])
            print(f'   history BF {lo}-{hi if hi < 10**6 else "+"}: bias {bias:+.2f} runs/9   MSE {np.nanmean(score(D, res[arm], f)):.3f}')


if __name__ == '__main__':
    main()
