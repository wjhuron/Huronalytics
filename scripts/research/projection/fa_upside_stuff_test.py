"""fa_upside_stuff_test.py: does Stuff+ history improve the 90th-percentile outcome fit for pitchers, on seasons where Stuff+ history exists? Also reads the cost of the .4/.3/.3 composite by season. Research only (2026-11-05).
Stuff+ history starts 2021, so T 2022 on. Same channel form as fa_upside_blend. Fit and scored only on T with real history. Five years has one replicate and is not tested.
Usage: PYTHONHASHSEED=0 python3 scripts/research/projection/fa_upside_stuff_test.py
Output: console + data/_proj/_fa_upside_stuff.json
"""
import json, os, pickle, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fa_upside_blend as U
B = U.B
rows = pickle.load(open(U.CACHE, 'rb'))
stuff = json.load(open(os.path.join(B.ROOT, 'data', '_era_internal_stuff.json')))
N0 = 250


def ch(r):
    n = d = 0.0
    for k in range(3):
        v = stuff.get(str(r['T'] - 1 - k), {}).get(str(r['pid']))
        if v and v.get('stuff_full') is not None:
            n += .7 ** k * v['n_full'] * v['stuff_full']; d += .7 ** k * v['n_full']
    return n / (d + N0) * 100


out = {}
for g in ('SP', 'RP'):
    w = U.FIXED[g]
    for h in (1, 3):
        use = [r for r in rows if r['group'] == g and r['T'] >= 2022 and r[f'y{h}'] is not None and B.blend_rate(r, w) is not None]; Ts = sorted({r['T'] for r in use})
        a, b, cov_a, cov_b, tops = [], [], [], [], []
        for T in Ts:
            te = [r for r in use if r['T'] == T]; tr = [r for r in use if r['T'] != T]; ytr = np.array([r[f'y{h}'] for r in tr]); y = np.array([r[f'y{h}'] for r in te])
            X0, Xt0 = U.dz(tr, g, h, 'M2'), U.dz(te, g, h, 'M2')
            X1, Xt1 = np.column_stack([X0, [ch(r) for r in tr]]), np.column_stack([Xt0, [ch(r) for r in te]])
            p0, p1 = Xt0 @ U.qfit(X0, ytr), Xt1 @ U.qfit(X1, ytr)
            a.append(U.pin(p1, y)); b.append(U.pin(p0, y)); cov_a.append(np.mean(y <= p1)); tops.append((U.top_overlap(p1, y), U.top_overlap(p0, y)))
        all_ = U.dz(use, g, h, 'M2'); X = np.column_stack([all_, [ch(r) for r in use]]); c = U.qfit(X, np.array([r[f'y{h}'] for r in use]))
        print(f'{g} {h}: T {Ts} n {len(use)}: pinball with Stuff+ {np.mean(a):.4f} v {np.mean(b):.4f}, wins {sum(x < y for x, y in zip(a, b))}/{len(Ts)}, coverage {np.mean(cov_a):.3f}; top decile {np.mean([t[0] for t in tops]):.3f} v {np.mean([t[1] for t in tops]):.3f}; slope per Stuff+ unit {c[-1]:.4f}')
        out[f'{g}_{h}'] = dict(qcoef=c.tolist(), wins=sum(x < y for x, y in zip(a, b)), n=len(Ts), pin=float(np.mean(a)), pin0=float(np.mean(b)))
json.dump(out, open(os.path.join(B.P, '_fa_upside_stuff.json'), 'w'), indent=1, default=float)
J = json.load(open(os.path.join(B.P, '_fa_upside_blend.json')))
print('\ncomposite .4/.3/.3 v expected alone: mean gap, seasons won (ties count as not won)')
for g in ('H', 'SP', 'RP'):
    for h in (1, 3, 5):
        p = J[f'{g}_{h}']['per_T']; A, C = p[str((.4, .3, .3))], p[str((1.0, 0.0, 0.0))]
        ln = []
        for k in ('r', 'top', 'top5'):
            d = [A[k][T] - C[k][T] for T in A[k]]; ln.append(f'{k} {np.mean(d):+.3f} {sum(x > 0 for x in d)}/{len(d)}')
        print(f'  {g} {h}: ' + ' | '.join(ln))
