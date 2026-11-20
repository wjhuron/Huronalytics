"""wed_fld_build.py - the hpWAR fielding projection in its PRODUCTION form, re-chosen on honest pools.

Production (project_players.py): frv1000 = (sum_k d^k outs_k rate_k + n0 * c) / (sum_k d^k outs_k + n0) + age term on
the TARGET age (yi per year under the peak, od per year over), one setting for the 1-, 3- and 5-year hpWAR:
d .55, n0 2000, c -1.0, peak 34, yi .05, od .20. d / peak / yi / od were chosen on fielders with 1,500+ outs in the
target season one season out; c and n0 on an honest pool with the other four held at those values.
Here every constant is swept jointly on fielders with 1+ out in the target (target-outs weighted), for h = 1, 3, 5,
leave-one-base-season-out. Candidate design: ONE shape (d, c, peak, yi, od) with a horizon-specific n0.
.venv/bin/python scripts/research/war_era_deep_dive/wed_fld_build.py"""
import sys, os, itertools, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'projection'))
import fld_rate_backtest as FB
S = {y: FB.season(y) for y in range(2016, 2027)}
G = {'d': [0.55, 0.7, 0.85], 'c': [-2.0, -1.5, -1.0, -0.5, 0.0, 0.5], 'peak': [26, 27, 28, 29, 30, 32, 34], 'yi': [0.0, 0.05, 0.1], 'od': [0.05, 0.1, 0.15, 0.2, 0.3]}
N0 = [1000, 2000, 3000, 4500, 6500, 10000, 15000]
SHIP = dict(d=0.55, c=-1.0, peak=34, yi=0.05, od=0.2, n0=2000)
H = (1, 3, 5)


def data(h):
    D = {}
    for B in range(2018, 2027 - h):
        rows = []
        for pid, (o, r, age) in S[B + h].items():
            if o < 1 or age is None:
                continue
            hh = [S[B - k].get(pid, (0, 0.0, None)) for k in range(3)]
            if sum(x[0] for x in hh) == 0:
                continue
            rows.append((age, o, r, *[c for x in hh for c in x[:2]]))
        D[B] = np.array(rows, float)
    return D


def proj(M, d, c, peak, yi, od, n0):
    num = np.zeros(len(M)); den = np.zeros(len(M))
    for k in range(3):
        num += d ** k * M[:, 3 + 2 * k] * M[:, 4 + 2 * k]; den += d ** k * M[:, 3 + 2 * k]
    age = M[:, 0]
    return (num + n0 * c) / (den + n0) + np.where(age < peak, yi * (peak - age), -od * (age - peak))


DAT = {h: data(h) for h in H}
shapes = list(itertools.product(*[G[k] for k in G])); keys = list(G)
# L[h][shape, n0, base]
L = {h: np.array([[[FB.wmse(proj(DAT[h][B], *s, n), DAT[h][B][:, 2], DAT[h][B][:, 1]) for B in DAT[h]] for n in N0] for s in shapes]) for h in H}
ship = {h: np.array([FB.wmse(proj(DAT[h][B], SHIP['d'], SHIP['c'], SHIP['peak'], SHIP['yi'], SHIP['od'], SHIP['n0']), DAT[h][B][:, 2], DAT[h][B][:, 1]) for B in DAT[h]]) for h in H}
zero = {h: np.array([FB.wmse(np.zeros(len(DAT[h][B])), DAT[h][B][:, 2], DAT[h][B][:, 1]) for B in DAT[h]]) for h in H}
res = {}
print("per-horizon free optimum (every constant free):")
for h in H:
    m = L[h].mean(axis=2); i, j = np.unravel_index(np.argmin(m), m.shape)
    print(f"   h {h}: {dict(zip(keys, shapes[i]))} n0 {N0[j]}  MSE {m[i, j]:.3f} | shipped {ship[h].mean():.3f} (+{100*(ship[h].mean()/m[i, j]-1):.1f}%) | zero {zero[h].mean():.3f}")
    res[f'free {h}'] = dict(shape=dict(zip(keys, shapes[i])), n0=N0[j], mse=float(m[i, j]), ship=float(ship[h].mean()), zero=float(zero[h].mean()))
# one shape, horizon-specific n0: minimise the mean over horizons of (loss / free optimum)
free = {h: L[h].mean(axis=2).min() for h in H}
score = sum(L[h].mean(axis=2).min(axis=1) / free[h] for h in H) / 3
bi = int(np.argmin(score)); bs = shapes[bi]; bn = {h: N0[int(np.argmin(L[h].mean(axis=2)[bi]))] for h in H}
print(f"\none shape, n0 by horizon: {dict(zip(keys, bs))}, n0 {bn}")
for h in H:
    v = L[h].mean(axis=2)[bi]; print(f"   h {h}: MSE {v.min():.3f} (+{100*(v.min()/free[h]-1):.2f}% over the free optimum); n0 curve " + "  ".join(f"{n}:{x:.3f}" for n, x in zip(N0, v)))
print("   shape curves (mean over horizons of loss / free optimum, n0 re-chosen):")
for ki, k in enumerate(keys):
    pts = []
    for v in G[k]:
        s = list(bs); s[ki] = v; pts.append(f"{v}:{score[shapes.index(tuple(s))]:.4f}")
    print(f"     {k:>4}: " + "  ".join(pts))
# held out: for each base season, choose the shape and the n0s on every OTHER base season (all horizons), score that season
print("\nheld out by base season (shape and n0 chosen without it), candidate minus shipped:")
for h in H:
    Bs = list(DAT[h]); d = []
    for j, B in enumerate(Bs):
        sc = 0
        for hh in H:
            oth = [k for k, b in enumerate(DAT[hh]) if b != B]
            sc = sc + L[hh][:, :, oth].mean(axis=2).min(axis=1) / L[hh][:, :, oth].mean(axis=2).min()
        i = int(np.argmin(sc)); oth = [k for k, b in enumerate(Bs) if b != B]; n = int(np.argmin(L[h][i][:, oth].mean(axis=1)))
        d.append((L[h][i, n, j] - ship[h][j]) / ship[h][j])
    d = np.array(d); print(f"   h {h}: {100*d.mean():+.2f}% (SE {100*d.std(ddof=1)/np.sqrt(len(d)):.2f}), better in {int((d < 0).sum())}/{len(d)}")
    res[f'heldout {h}'] = dict(d=float(d.mean()), wins=int((d < 0).sum()), n=len(d))
# calibration by age for shipped and candidate at each horizon (actual minus projected, runs per 1000 outs, outs weighted)
print("\ncalibration by target age, actual minus projected (runs per 1000 outs): shipped -> candidate")
for h in H:
    line = []
    for lo, hi in ((19, 25), (25, 28), (28, 31), (31, 34), (34, 45)):
        a = b = w = 0.0
        for B, M in DAT[h].items():
            m = (M[:, 0] >= lo) & (M[:, 0] < hi); ww = M[m, 1]
            a += (ww * (M[m, 2] - proj(M[m], SHIP['d'], SHIP['c'], SHIP['peak'], SHIP['yi'], SHIP['od'], SHIP['n0']))).sum(); b += (ww * (M[m, 2] - proj(M[m], *bs, bn[h]))).sum(); w += ww.sum()
        line.append(f"{lo}-{hi}: {a/w:+.2f} -> {b/w:+.2f}")
    print(f"   h {h}: " + "; ".join(line))
res['candidate'] = dict(shape=dict(zip(keys, bs)), n0=bn)
json.dump(res, open(os.path.join(ROOT, 'data', '_wed', 'res_fld_build.json'), 'w'), indent=1)
