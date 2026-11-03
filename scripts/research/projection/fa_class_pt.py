"""fa_class_pt.py: is projected playing time biased on free agents? Held-out full arm of pt_backtest, zeros counted.

T 2021-2026 (FA tracker years), OLS refit leaving T out, pt_backtest conventions. Reads actual minus projected PT for the FA
class vs the rest, raw and within age bins, per season. Also the share of FAs at zero. This is what a total hpWAR multiplies.

Usage: python3 scripts/research/projection/fa_class_pt.py
Output: console + data/_proj/_fa_class_pt.json
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fa_class_calibration as fc
import pt_backtest as pt


def run(side, FA):
    S = {y: (pt.pitch_season if side == 'pit' else pt.hit_season)(y) for y in range(pt.TARGETS[0] - 3, 2027)}
    A = {y: pt.aaa_pt(y, 'outs' if side == 'pit' else 'plateAppearances') for y in S}
    R = {T: pt.rows(side, S, A, T - 1) for T in pt.TARGETS}
    cols = pt.ARMS[side]['full']
    X = {T: pt.design(R[T], cols) for T in R}; Y = {T: np.array([y for _, _, y in R[T]]) for T in R}
    out = []
    for T in range(2021, 2027):
        tr = [s for s in R if s != T]
        b = np.linalg.lstsq(np.vstack([X[s] for s in tr]), np.concatenate([Y[s] for s in tr]), rcond=None)[0]
        p = np.clip(X[T] @ b, 0, max(Y[s].max() for s in tr))
        for (pid, f, y), q in zip(R[T], p):
            out.append((T, (T, int(pid)) in FA, f['age'], y, q))
    a = np.array(out, float)
    T, fa, age, y, q = a[:, 0], a[:, 1] > 0, a[:, 2], a[:, 3], a[:, 4]
    r = y - q
    unit = 'IP' if side == 'pit' else 'PA'
    print(f'\n== {side}: rows {len(a)}, FA {int(fa.sum())}; mean age FA {age[fa].mean():.1f} rest {age[~fa].mean():.1f}')
    print(f'  mean actual {unit}: FA {y[fa].mean():.1f} rest {y[~fa].mean():.1f}; mean projected: FA {q[fa].mean():.1f} rest {q[~fa].mean():.1f}; zero share FA {(y[fa]==0).mean():.3f} rest {(y[~fa]==0).mean():.3f}')
    print(f'  actual minus projected, FA {r[fa].mean():+.1f} (se {r[fa].std(ddof=1)/np.sqrt(fa.sum()):.1f})  rest {r[~fa].mean():+.1f}  per T ' + ' '.join(f'{r[fa&(T==t)].mean():+.1f}' for t in range(2021, 2027)))
    res = {'fa': float(r[fa].mean()), 'rest': float(r[~fa].mean()), 'per_T': [float(r[fa & (T == t)].mean()) for t in range(2021, 2027)]}
    for lo, hi in ((0, 30.5), (30.5, 33.5), (33.5, 99)):
        m = (age >= lo) & (age < hi)
        d = r[m & fa].mean() - r[m & ~fa].mean()
        print(f'  age {lo}-{hi}: FA {r[m&fa].mean():+.1f} (n {int((m&fa).sum())}, se {r[m&fa].std(ddof=1)/np.sqrt((m&fa).sum()):.1f}) rest {r[m&~fa].mean():+.1f} (n {int((m&~fa).sum())}) diff {d:+.1f}')
        res[f'{lo}-{hi}'] = {'fa': float(r[m & fa].mean()), 'rest': float(r[m & ~fa].mean())}
    return res


def main():
    FA = fc.fa_rows()
    res = {side: run(side, FA) for side in ('hit', 'pit')}
    with open(os.path.join(pt.P, '_fa_class_pt.json'), 'w') as f:
        json.dump(res, f, indent=1)


if __name__ == '__main__':
    main()
