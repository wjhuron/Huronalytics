"""wed_proj.py - WAR/ERA deep dive, tests 2 and 3: the hpWAR level constants on pools with NO target-season gate.

The shipped hitter setting (a .75, d .70, n0 450, ys .002, os .0045, peak 30) was chosen on hitters with 200+ PA
in the target season, and the pitcher setting (d .65, n0 500, peak 26, yi .09, od .04) on pitchers with 30+ IP in
the target season. Playing time follows performance, so those gates select on the outcome. Here the same
backtests (scripts/research/projection/bat_rate_backtest.py, pit_rate_backtest.py) run with the gate at 1 PA /
1 out, target-PA / target-IP weighted, leave-one-target-season-out. The pitcher arm also swaps the target
season's starter share (a target leak) for the base season's.
.venv/bin/python scripts/research/war_era_deep_dive/wed_proj.py [hit pit]"""
import sys, os, itertools, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'projection'))
import bat_rate_backtest as BR
import pit_rate_backtest as PR
OUT = os.path.join(ROOT, 'data', '_wed'); os.makedirs(OUT, exist_ok=True)
RES = {}


def hit():
    print("\n=== T2 hpWAR hitters: level setting by target gate ===")
    grid = {'a': [0.5, 0.625, 0.75, 0.875, 1.0], 'd': [0.4, 0.55, 0.7, 0.85, 1.0], 'n0': [200, 300, 450, 600, 900, 1200],
            'ys': [0.0, 0.002, 0.004, 0.006], 'os': [0.0, 0.0015, 0.003, 0.0045, 0.006], 'peak': [26, 28, 29, 30, 31]}
    keys = list(grid); combos = list(itertools.product(*[grid[k] for k in keys])); ship = (0.75, 0.7, 450, 0.002, 0.0045, 30)
    si = combos.index(ship)
    for gate in (200, 1):
        BR.MIN_PA_T = gate; data, LG = BR.build(); T_ = BR.TARGETS
        L = np.zeros((len(combos), len(T_)))
        for j, T in enumerate(T_):
            M = data[T]
            for i, c in enumerate(combos):
                L[i, j] = BR.wmse(BR.project(M, *c), M[:, 3], M[:, 2])
        mar = np.array([BR.wmse(BR.marcel(data[T], LG[T][0]), data[T][:, 3], data[T][:, 2]) for T in T_])
        best = int(np.argmin(L.mean(axis=1)))
        held = np.array([L[int(np.argmin(L[:, [k for k in range(len(T_)) if k != j]].mean(axis=1))), j] for j in range(len(T_))])
        chosen = [combos[int(np.argmin(L[:, [k for k in range(len(T_)) if k != j]].mean(axis=1)))] for j in range(len(T_))]
        d = (L[si] - held) / held
        print(f" gate {gate} PA in T: n per season {[len(data[T]) for T in T_]}")
        print(f"   pooled argmin {dict(zip(keys, combos[best]))}  MSE x1e4 {L[best].mean()*1e4:.3f} | shipped {L[si].mean()*1e4:.3f} (+{100*(L[si].mean()/L[best].mean()-1):.2f}%) | Marcel {mar.mean()*1e4:.3f}")
        print(f"   held-out (setting chosen on the other seasons): {held.mean()*1e4:.3f}; shipped minus held-out {100*d.mean():+.2f}% (SE {100*d.std(ddof=1)/np.sqrt(len(d)):.2f}), shipped better in {int((d < 0).sum())}/{len(d)}; shipped beats Marcel {int((L[si] < mar).sum())}/{len(T_)}")
        print("   chosen per held-out season: " + " ".join(str(c) for c in sorted(set(chosen), key=chosen.count, reverse=True)[:4]))
        for ki, k in enumerate(keys):
            pts = []
            for v in grid[k]:
                c = list(combos[best]); c[ki] = v; pts.append(f"{v}:{L[combos.index(tuple(c))].mean()*1e4:.3f}")
            print(f"     {k:>4}: " + "  ".join(pts))
        RES[f'hit gate {gate}'] = dict(best=dict(zip(keys, combos[best])), best_mse=float(L[best].mean()), ship_mse=float(L[si].mean()), marcel=float(mar.mean()), ship_vs_heldout=float(d.mean()))
        if gate == 1:
            # cross-check: the gated optimum scored on the honest pool, and by target-PA band
            print("   by target-PA band on the honest pool (shipped MSE x1e4 / pooled-argmin MSE / Marcel):")
            for lo, hi in ((1, 100), (100, 300), (300, 502), (502, 800)):
                a = b = m = w = 0.0
                for T in T_:
                    M = data[T]; q = (M[:, 2] >= lo) & (M[:, 2] < hi)
                    if q.sum() == 0:
                        continue
                    ww = M[q, 2]
                    a += (ww * (BR.project(M[q], *ship) - M[q, 3]) ** 2).sum(); b += (ww * (BR.project(M[q], *combos[best]) - M[q, 3]) ** 2).sum()
                    m += (ww * (BR.marcel(M[q], LG[T][0]) - M[q, 3]) ** 2).sum(); w += ww.sum()
                print(f"     {lo}-{hi} PA: {a/w*1e4:.3f} / {b/w*1e4:.3f} / {m/w*1e4:.3f}  (share of target PA {w / sum(data[T][:, 2].sum() for T in T_):.3f})")


def pit():
    print("\n=== T3 hpWAR pitchers: level setting by target gate and by the starter-share source ===")
    grid = {'d': [0.3, 0.4, 0.5, 0.65, 0.8, 1.0], 'n0': [150, 300, 500, 800, 1200], 'peak': [22, 24, 26, 28, 30],
            'yi': [0.0, 0.03, 0.06, 0.09, 0.12], 'od': [0.0, 0.02, 0.04, 0.06, 0.10]}
    keys = list(grid); combos = list(itertools.product(*[grid[k] for k in keys])); ship = (0.65, 500, 26, 0.09, 0.04); si = combos.index(ship)
    T_ = PR.TARGETS
    for gate, gs_src in ((90, 'target'), (1, 'target'), (1, 'base')):
        PR.MIN_OUTS_T = gate; D = PR.build()
        if gs_src == 'base':
            for T in T_:
                rows = []
                for pid, t, hist in D[T]:
                    h = next((x for x in hist if x), None); t2 = dict(t); t2['gs'] = h['gs'] if h else 0.0; rows.append((pid, t2, hist))
                D[T] = rows
        for tgt, yi_ in (('ra9', 1), ('fip', 2)):
            L = np.zeros((len(combos), len(T_)))
            for i, c in enumerate(combos):
                F = {T: PR.features(D[T], *c) for T in T_}
                for j, T in enumerate(T_):
                    tr = [F[S] for S in T_ if S != T]
                    p, _ = PR.fit_predict(np.vstack([f[0] for f in tr]), np.concatenate([f[yi_] for f in tr]), np.concatenate([f[3] for f in tr]), F[T][0])
                    L[i, j] = PR.wmse(p, F[T][yi_], F[T][3])
            F0 = {T: PR.features(D[T], *ship) for T in T_}
            mar = np.array([PR.wmse(PR.marcel(D[T]), F0[T][yi_], F0[T][3]) for T in T_])
            best = int(np.argmin(L.mean(axis=1)))
            ch = [int(np.argmin(L[:, [k for k in range(len(T_)) if k != j]].mean(axis=1))) for j in range(len(T_))]
            held = np.array([L[ch[j], j] for j in range(len(T_))]); d = (L[si] - held) / held
            print(f" gate {gate} outs, starter share from the {gs_src} season, target {tgt}: n {[len(D[T]) for T in T_]}")
            print(f"   pooled argmin {dict(zip(keys, combos[best]))} MSE {L[best].mean():.4f} | shipped {L[si].mean():.4f} (+{100*(L[si].mean()/L[best].mean()-1):.2f}%) | Marcel {mar.mean():.4f} | shipped beats Marcel {int((L[si] < mar).sum())}/{len(T_)}")
            print(f"   held-out {held.mean():.4f}; shipped minus held-out {100*d.mean():+.2f}% (SE {100*d.std(ddof=1)/np.sqrt(len(d)):.2f}), shipped better in {int((d < 0).sum())}/{len(d)}")
            for ki, k in enumerate(keys):
                pts = []
                for v in grid[k]:
                    c = list(combos[best]); c[ki] = v; pts.append(f"{v}:{L[combos.index(tuple(c))].mean():.4f}")
                print(f"     {k:>4}: " + "  ".join(pts))
            RES[f'pit gate {gate} gs {gs_src} {tgt}'] = dict(best=dict(zip(keys, combos[best])), best_mse=float(L[best].mean()), ship_mse=float(L[si].mean()), marcel=float(mar.mean()), ship_vs_heldout=float(d.mean()))


if __name__ == '__main__':
    for t in (sys.argv[1:] or ['hit', 'pit']):
        globals()[t]()
        json.dump(RES, open(os.path.join(OUT, 'res_proj.json'), 'w'), indent=1, default=float)
