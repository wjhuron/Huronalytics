"""bat_career_test.py: does career length add to the hitter projection, and does it explain the FA gap?

Base: bat_experience_test exper+aaa held-out projection, T 2018-2026. Candidate channels, all known before T:
    log career PA    MLB box lines 2000..T-1
    MLB seasons      seasons with >= 1 PA, 2000..T-1 (service-time proxy; a career that began before 2000 is short-counted)
    age x career     (age - 30)+ x log career PA, late decline steeper for long careers?
Residual OLS, fit leaving T out (bx convention); PA_T weighted MSE gain, per season wins, bootstrap SE of mean gain by season.
Then: the FA gap (fa_class_calibration) on the corrected projection.

Usage: python3 scripts/research/projection/bat_career_test.py
Output: console + data/_proj/_bat_career_test.json
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aaa_hitter_bridge as hb
import bat_experience_test as bx
import fa_class_calibration as fc

P = bx.v1.P


def careers():
    pa = {}
    for y in range(2000, 2027):
        rows = json.load(open(os.path.join(P, f'lines_hitting_{y}.json')))
        it = rows.values() if isinstance(rows, dict) else rows
        if isinstance(rows, dict):
            it = [dict(v, mlbId=k) for k, v in rows.items()]
        by = {}
        for r in it:
            pid = r.get('mlbId') or r.get('id') or r.get('playerId') or r.get('person_id')
            n = r.get('plateAppearances')
            if pid is None or n is None:
                raise RuntimeError(f'unexpected line shape {y}: {list(r)[:12]}')
            by[int(pid)] = by.get(int(pid), 0) + int(n)
        pa[y] = by
    return pa


def main():
    FA = fc.fa_rows()
    D, Aaa, Mlb = bx.build()
    held = {h['T']: h['chosen'] for h in json.load(open(os.path.join(P, '_bat_experience_test.json')))['exper+aaa']['held']}
    C = careers()
    R = {}
    for T in bx.TARGETS:
        Z = bx.arrays(D[T], bx.bridge_beta(Aaa, Mlb, T))
        p = bx.project(Z, *held[T])
        ids = [int(r['id']) for r in D[T]]; age = np.array([r['age'] for r in D[T]], float)
        cpa = np.array([sum(C[y].get(i, 0) for y in range(2000, T)) for i in ids], float)
        sea = np.array([sum(1 for y in range(2000, T) if C[y].get(i, 0) > 0) for i in ids], float)
        R[T] = dict(p=p, y=Z['y'], w=Z['w'], age=age, cpa=cpa, sea=sea, E=Z['E'], ids=ids,
                    fa=np.array([(T, i) in FA for i in ids]))
    feats = {
        'logPA': lambda r: [np.log1p(r['cpa'])],
        'seasons': lambda r: [r['sea']],
        'logPA+ageX': lambda r: [np.log1p(r['cpa']), np.maximum(r['age'] - 30, 0) * np.log1p(r['cpa'])],
        'seasons+ageX': lambda r: [r['sea'], np.maximum(r['age'] - 30, 0) * r['sea']],
        'ageX only': lambda r: [np.maximum(r['age'] - 30, 0) * np.log1p(r['cpa'])],
        'age30+ only (control)': lambda r: [np.maximum(r['age'] - 30, 0)],
    }
    out = {}
    for name, fn in feats.items():
        Xs = {T: np.column_stack([np.ones(len(R[T]['y']))] + fn(R[T])) for T in R}
        gains, cf, q = [], [], {}
        for T in R:
            tr = [S for S in R if S != T]
            X = np.vstack([Xs[S] for S in tr]); r = np.concatenate([R[S]['y'] - R[S]['p'] for S in tr]); w = np.concatenate([R[S]['w'] for S in tr])
            sw = np.sqrt(w); b = np.linalg.lstsq(X * sw[:, None], r * sw, rcond=None)[0]
            q[T] = R[T]['p'] + Xs[T] @ b; cf.append(b)
            m0 = np.average((R[T]['y'] - R[T]['p']) ** 2, weights=R[T]['w']); m1 = np.average((R[T]['y'] - q[T]) ** 2, weights=R[T]['w'])
            gains.append(1 - m1 / m0)
        g = np.array(gains)
        # FA gap after the correction, T 2021-2026
        rs = np.concatenate([R[T]['y'] - q[T] for T in R if T >= 2021]); fa = np.concatenate([R[T]['fa'] for T in R if T >= 2021]); w = np.concatenate([R[T]['w'] for T in R if T >= 2021])
        gap = np.average(rs[fa], weights=w[fa]) - np.average(rs[~fa], weights=w[~fa])
        print(f'{name:24s} gain {100*g.mean():+.3f}% (se {100*g.std(ddof=1)/np.sqrt(len(g)):.3f})  wins {int((g>0).sum())}/{len(g)}  coef {np.round(np.mean(cf,axis=0),5).tolist()}  FA gap after {gap:+.4f}')
        out[name] = dict(gain=g.tolist(), coef=np.mean(cf, axis=0).tolist(), fa_gap=float(gap))
    # how the residual looks by age x career quartile, T 2021-2026
    A = {k: np.concatenate([R[T][k] for T in R if T >= 2021]) for k in ('p', 'y', 'w', 'age', 'cpa', 'fa')}
    r = A['y'] - A['p']
    print('\nresidual by age and career PA (PA_T weighted, T 2021-2026); n in brackets')
    for lo, hi in ((0, 27.5), (27.5, 30.5), (30.5, 33.5), (33.5, 99)):
        cells = []
        for pl, ph in ((0, 1000), (1000, 2500), (2500, 4500), (4500, 10 ** 6)):
            m = (A['age'] >= lo) & (A['age'] < hi) & (A['cpa'] >= pl) & (A['cpa'] < ph)
            cells.append(f'{np.average(r[m], weights=A["w"][m]):+.4f} [{int(m.sum())}]' if m.sum() > 20 else '   --    ')
        print(f'  age {lo:>4}-{hi:<4}: ' + '  '.join(cells))
    print('FA minus rest inside the veteran cell (age 30.5+, career PA 2500+):', end=' ')
    m = (A['age'] >= 30.5) & (A['cpa'] >= 2500)
    print(f'{np.average(r[m & A["fa"]], weights=A["w"][m & A["fa"]]) - np.average(r[m & ~A["fa"]], weights=A["w"][m & ~A["fa"]]):+.4f}  n FA {int((m & A["fa"]).sum())} rest {int((m & ~A["fa"]).sum())}')
    with open(os.path.join(P, '_bat_career_test.json'), 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
