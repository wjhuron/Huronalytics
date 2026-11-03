"""fa_class_followup.py: stress tests of the hitter free-agent projection gap (fa_class_calibration.py).

 A  event study: FA class Y, residual at T = Y-1 (walk year), Y, Y+1. Tells a temporary drop from a level miss.
 B  Steamer and ZiPS on the same matched set, each centered on that set's PA-weighted actual mean: same gap?
 C  held-out correction: projection + b x FA, b fit on the other target seasons. MSE on FA rows and all rows.
 D  placebo: random non-FA flags drawn within T x age-bin x experience-bin cells to mirror the FA mix.
 E  target split: the same gap on actual wOBA and on actual xwOBA.

Usage: python3 scripts/research/projection/fa_class_followup.py
Output: console + data/_proj/_fa_class_followup.json
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bat_experience_test as bx
import fa_class_calibration as fc
import h2h_batting as h2


def frame(FA):
    D, Aaa, Mlb = bx.build()
    held = {h['T']: h['chosen'] for h in json.load(open(os.path.join(bx.v1.P, '_bat_experience_test.json')))['exper+aaa']['held']}
    X = {y: bx.v1.load_xstats(y) for y in range(2015, 2027)}
    LG = {y: bx.v1.league(X[y]) for y in X}
    A = dict(T=[], id=[], p=[], y=[], yx=[], w=[], age=[], E=[])
    for T in bx.TARGETS:
        Z = bx.arrays(D[T], bx.bridge_beta(Aaa, Mlb, T))
        p = bx.project(Z, *held[T])
        for i, r in enumerate(D[T]):
            A['T'].append(T); A['id'].append(int(r['id'])); A['p'].append(p[i]); A['y'].append(Z['y'][i])
            A['yx'].append(X[T][r['id']][2] - LG[T][1]); A['w'].append(Z['w'][i]); A['age'].append(r['age']); A['E'].append(r['E'])
    A = {k: np.array(v) for k, v in A.items()}
    return A


def flag(A, FA, off):
    return np.array([(int(t) - off, int(i)) in FA for t, i in zip(A['T'], A['id'])])


def main():
    FA = fc.fa_rows()
    A = frame(FA)
    res = {}
    print('A. event study, hitters, residual actual minus projected wOBA, FA class minus rest')
    res['A'] = {}
    for lab, off in (('T = Y-1 (walk year)', -1), ('T = Y   (year after reaching FA)', 0), ('T = Y+1', 1)):
        f = flag(A, FA, off)
        m = (A['T'] - off >= 2021) & (A['T'] - off <= 2026)
        res['A'][lab] = fc.report(lab, A['y'] - A['p'], f, A['age'], A['E'], A['w'], A['T'], 'wOBA', sub=m)

    f0 = flag(A, FA, 0)
    m0 = (A['T'] >= 2021)
    print('\nE. target split at T = Y')
    fc.report('actual wOBA', A['y'] - A['p'], f0, A['age'], A['E'], A['w'], A['T'], 'wOBA', sub=m0)
    fc.report('actual xwOBA', A['yx'] - A['p'], f0, A['age'], A['E'], A['w'], A['T'], 'xwOBA', sub=m0)

    print('\nB. other systems, same matched set, centered on the set')
    res['B'] = {}
    for system, yrs in h2.SYSTEMS.items():
        rows = {n: [] for n in ('T', 'ours', 'theirs', 'y', 'w', 'fa', 'age', 'E')}
        for T in yrs:
            if T < 2021:
                continue
            fg = h2.fg(system, T)
            ix = np.where(A['T'] == T)[0]
            keep = [i for i in ix if int(A['id'][i]) in fg]
            y = A['y'][keep]; w = A['w'][keep]; lgm = None
            ours = A['p'][keep]; th = np.array([fg[int(A['id'][i])] for i in keep], float)
            ours = ours - np.average(ours, weights=w) + np.average(y, weights=w)
            th = th - np.average(th, weights=w) + np.average(y, weights=w)
            for n, v in (('T', A['T'][keep]), ('ours', ours), ('theirs', th), ('y', y), ('w', w), ('fa', f0[keep]), ('age', A['age'][keep]), ('E', A['E'][keep])):
                rows[n].append(v)
        R = {k: np.concatenate(v) for k, v in rows.items()}
        print(f' {system}: n {len(R["y"])}, FA {int(R["fa"].sum())}')
        res['B'][system] = dict(
            ours=fc.report('  ours', R['y'] - R['ours'], R['fa'], R['age'], R['E'], R['w'], R['T'], 'wOBA'),
            theirs=fc.report(f'  {system}', R['y'] - R['theirs'], R['fa'], R['age'], R['E'], R['w'], R['T'], 'wOBA'),
        )

    print('\nC. held-out correction: p + b x FA, b fit on the other seasons')
    Ts = list(range(2021, 2027)); gains_fa, gains_all, bs = [], [], []
    for T in Ts:
        tr = (A['T'] >= 2021) & (A['T'] != T); te = A['T'] == T
        r = A['y'] - A['p']
        b = np.average(r[tr & f0], weights=A['w'][tr & f0]) - np.average(r[tr & ~f0], weights=A['w'][tr & ~f0])
        q = A['p'] + b * f0
        mse = lambda pp, m: np.average((A['y'][m] - pp[m]) ** 2, weights=A['w'][m])
        gains_fa.append(1 - mse(q, te & f0) / mse(A['p'], te & f0)); gains_all.append(1 - mse(q, te) / mse(A['p'], te)); bs.append(b)
    print('  b by held-out season', np.round(bs, 4).tolist())
    print(f'  FA rows: mean MSE gain {100*np.mean(gains_fa):+.2f}%  wins {sum(g > 0 for g in gains_fa)}/6  {np.round(100*np.array(gains_fa),2).tolist()}')
    print(f'  all rows: mean MSE gain {100*np.mean(gains_all):+.3f}%  wins {sum(g > 0 for g in gains_all)}/6')
    res['C'] = dict(b=bs, gain_fa=gains_fa, gain_all=gains_all)

    print('\nD. placebo: random non-FA flags matched on T x age-bin x experience-bin')
    m = A['T'] >= 2021
    T_, age, E, w = A['T'][m], A['age'][m], A['E'][m], A['w'][m]; r = (A['y'] - A['p'])[m]; f = f0[m]
    ab = np.digitize(age, [25, 28, 31, 34]); eb = np.digitize(E, np.percentile(E, [25, 50, 75]))
    cell = T_ * 100 + ab * 10 + eb
    rng = np.random.default_rng(1); pl = []
    obs = np.average(r[f], weights=w[f]) - np.average(r[~f], weights=w[~f])
    for _ in range(1000):
        g = np.zeros(len(f), bool)
        for c in np.unique(cell):
            ci = np.where(cell == c)[0]; n = int(f[ci].sum()); pool = ci[~f[ci]]
            if n and len(pool):
                g[rng.choice(pool, min(n, len(pool)), replace=False)] = True
        keep = ~f
        pl.append(np.average(r[g], weights=w[g]) - np.average(r[keep & ~g], weights=w[keep & ~g]))
    pl = np.array(pl)
    print(f'  observed {obs:+.4f}; placebo mean {pl.mean():+.4f} sd {pl.std():.4f}; share of placebos <= observed {float((pl <= obs).mean()):.4f}')
    res['D'] = dict(obs=float(obs), mean=float(pl.mean()), sd=float(pl.std()), p=float((pl <= obs).mean()))
    tmp = os.path.join(bx.v1.P, '_fa_class_followup.json.tmp')
    with open(tmp, 'w') as fh:
        json.dump(res, fh, indent=1, default=float)
    os.replace(tmp, os.path.join(bx.v1.P, '_fa_class_followup.json'))


if __name__ == '__main__':
    main()
