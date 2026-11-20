"""wed_fld.py - WAR/ERA deep dive, test 13: the hpWAR fielding projection constants (d .55, n0 2000, peak 34,
yi .05, od .20) with no target gate and at 3 and 5 seasons out.

fld_rate_backtest.py chose them one season out, on fielders with 1,500+ outs in the target season; the same
constants are reused for the 3- and 5-year hpWAR. Here: history B-2..B, target T = B + h, the age term on the
target age (as shipped), gate 1,500 or 1 out in T, target-outs weighted, leave-one-base-season-out.
.venv/bin/python scripts/research/war_era_deep_dive/wed_fld.py"""
import sys, os, itertools, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'projection'))
import fld_rate_backtest as FB
GRID = {'d': [0.4, 0.55, 0.7, 0.85, 1.0], 'n0': [500, 1000, 2000, 3000, 4500, 6500, 10000], 'peak': [26, 28, 30, 32, 34, 36],
        'yi': [0.0, 0.05, 0.1, 0.15, 0.2], 'od': [0.0, 0.1, 0.2, 0.3, 0.45, 0.6]}
SHIP = (0.55, 2000, 34, 0.05, 0.2)
S = {y: FB.season(y) for y in range(2016, 2027)}
keys = list(GRID); combos = list(itertools.product(*[GRID[k] for k in keys])); si = combos.index(SHIP); res = {}
for gate in (1500, 1):
    for h in (1, 3, 5):
        D = {}
        for B in range(2018, 2027 - h):
            rows = []
            for pid, (o, r, age) in S[B + h].items():
                if o < gate or age is None:
                    continue
                hh = [S[B - k].get(pid, (0, 0.0, None)) for k in range(3)]
                if sum(x[0] for x in hh) == 0:
                    continue
                rows.append((age, o, r, *[c for x in hh for c in x[:2]]))
            D[B] = np.array(rows, float)
        Bs = list(D); L = np.array([[FB.wmse(FB.project(D[B], *c), D[B][:, 2], D[B][:, 1]) for B in Bs] for c in combos])
        zero = np.array([FB.wmse(np.zeros(len(D[B])), D[B][:, 2], D[B][:, 1]) for B in Bs])
        best = int(np.argmin(L.mean(axis=1))); ch = [int(np.argmin(L[:, [k for k in range(len(Bs)) if k != j]].mean(axis=1))) for j in range(len(Bs))]
        held = np.array([L[ch[j], j] for j in range(len(Bs))]); d = (L[si] - held) / held
        print(f"\n gate {gate} outs in T, h = {h}: n {[len(D[B]) for B in Bs]}")
        print(f"   zero {zero.mean():.3f} | shipped {L[si].mean():.3f} | pooled argmin {dict(zip(keys, combos[best]))} {L[best].mean():.3f} (shipped +{100*(L[si].mean()/L[best].mean()-1):.2f}%)")
        print(f"   shipped minus held-out refit: {100*d.mean():+.2f}% (SE {100*d.std(ddof=1)/np.sqrt(len(d)):.2f}), shipped better in {int((d < 0).sum())}/{len(d)}; shipped beats zero in {int((L[si] < zero).sum())}/{len(Bs)}")
        for ki, k in enumerate(keys):
            pts = []
            for v in GRID[k]:
                c = list(combos[best]); c[ki] = v; pts.append(f"{v}:{L[combos.index(tuple(c))].mean():.3f}")
            print(f"     {k:>4}: " + "  ".join(pts))
        res[f'{gate} {h}'] = dict(best=dict(zip(keys, combos[best])), ship=float(L[si].mean()), best_mse=float(L[best].mean()), zero=float(zero.mean()), d=float(d.mean()))
json.dump(res, open(os.path.join(ROOT, 'data', '_wed', 'res_fld.json'), 'w'), indent=1)
