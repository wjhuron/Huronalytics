"""wed_bat_aging.py - WAR/ERA deep dive, test 2b: the hpWAR hitter AGING and LEVEL constants in the production form.

bat_experience_test.py scores every hitter with 1+ PA in the target season (an honest pool), but it holds
a, d, ys, os and peak at the values chosen earlier on the 200-PA-gated pool (.75, .7, .002, .0045, 30). This
sweeps them in that same production form (experience prior c -.04, k 200, AAA bridge weight .75, n0 450),
leave-one-target-season-out, and prints the calibration by age.
.venv/bin/python scripts/research/war_era_deep_dive/wed_bat_aging.py"""
import sys, os, itertools, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'projection'))
import bat_experience_test as BX
T_ = BX.TARGETS
SHIP = dict(a=.75, d=.7, ys=.002, os_=.0045, peak=30); N0, C, K, WA = 450, -0.04, 200, 0.75


def main():
    Dr, Aaa, Mlb = BX.build(); beta = {T: BX.bridge_beta(Aaa, Mlb, T) for T in T_}

    def losses(a, d, ys, os_, peak, n0=N0, c=C, k=K, reg=False, keep=False):
        BX.A, BX.D, BX.YS, BX.OS, BX.PEAK = a, d, ys, os_, peak
        out = []; zs = {}
        for T in T_:
            Z = BX.arrays(Dr[T], beta[T]); p = BX.project(Z, n0, c, k, WA)
            out.append(BX.wmse(p, Z, (Z['w'] >= 200) if reg else None)); zs[T] = (Z, p)
        return (np.array(out), zs) if keep else np.array(out)
    base = losses(**SHIP); base_r = losses(**SHIP, reg=True)
    print(f"shipped (a .75, d .7, ys .002, os .0045, peak 30): MSE x1e4 all {base.mean()*1e4:.3f}, regulars 200+ PA {base_r.mean()*1e4:.3f}")
    grid = {'ys': [0.0, 0.001, 0.002, 0.003, 0.004, 0.006], 'os': [0.0, 0.0015, 0.003, 0.0045, 0.006, 0.0075], 'peak': [23, 24, 25, 26, 27, 28, 29, 30, 31, 32]}
    keys = list(grid); combos = list(itertools.product(*[grid[k] for k in keys]))
    L = np.array([losses(SHIP['a'], SHIP['d'], *c) for c in combos]); Lr = np.array([losses(SHIP['a'], SHIP['d'], *c, reg=True) for c in combos])
    for nm, M in (('all hitters', L), ('regulars 200+ PA in T (the gated view)', Lr)):
        best = int(np.argmin(M.mean(axis=1))); ch = [int(np.argmin(M[:, [k for k in range(len(T_)) if k != j]].mean(axis=1))) for j in range(len(T_))]
        b0 = base if M is L else base_r
        held = np.array([M[ch[j], j] for j in range(len(T_))]); d = (held - b0) / b0
        print(f"\n aging sweep, {nm}: pooled argmin {dict(zip(keys, combos[best]))} MSE {M[best].mean()*1e4:.3f}")
        print(f"   held-out (chosen on the other eight seasons) minus shipped: {100*d.mean():+.2f}% (SE {100*d.std(ddof=1)/3:.2f}), better in {int((d < 0).sum())}/9; chosen: " + " ".join(str(combos[i]) for i in sorted(set(ch), key=ch.count, reverse=True)[:4]))
        for ki, k in enumerate(keys):
            pts = []
            for v in grid[k]:
                c = list(combos[best]); c[ki] = v; pts.append(f"{v}:{M[combos.index(tuple(c))].mean()*1e4:.3f}")
            print(f"     {k:>4}: " + "  ".join(pts))
    best = combos[int(np.argmin(L.mean(axis=1)))]
    # does the gated-view optimum cost the regulars? and the reverse
    bi = combos.index(best); print(f"\n the all-hitter optimum {best} scored on regulars: {Lr[bi].mean()*1e4:.3f} against shipped {base_r.mean()*1e4:.3f} ({100*(Lr[bi].mean()/base_r.mean()-1):+.2f}%), better in {int((Lr[bi] < base_r).sum())}/9")
    # level constants at the new aging
    print(" level constants re-swept at that aging (one at a time):")
    for nm, vals in (('a', [0.5, 0.625, 0.75, 0.875, 1.0]), ('d', [0.4, 0.55, 0.7, 0.85, 1.0])):
        pts = []
        for v in vals:
            kw = dict(a=SHIP['a'], d=SHIP['d']); kw[nm] = v; pts.append(f"{v}:{losses(kw['a'], kw['d'], *best).mean()*1e4:.3f}")
        print(f"     {nm}: " + "  ".join(pts))
    print("     n0: " + "  ".join(f"{v}:{losses(SHIP['a'], SHIP['d'], *best, n0=v).mean()*1e4:.3f}" for v in (200, 300, 450, 600, 900)))
    print("     c:  " + "  ".join(f"{v}:{losses(SHIP['a'], SHIP['d'], *best, c=v).mean()*1e4:.3f}" for v in (0.0, -0.02, -0.03, -0.04, -0.05, -0.06)))
    print("     k:  " + "  ".join(f"{v}:{losses(SHIP['a'], SHIP['d'], *best, k=v).mean()*1e4:.3f}" for v in (50, 100, 200, 400, 800)))
    # calibration by age: PA-weighted mean of actual minus projected, wOBA points x1000
    print("\n calibration by target age (actual minus projected, wOBA x1000, PA-weighted; PA share): shipped | optimum")
    _, z0 = losses(**SHIP, keep=True); _, z1 = losses(SHIP['a'], SHIP['d'], *best, keep=True)
    ages = {T: np.array([r['age'] for r in Dr[T]], float) for T in T_}
    for lo, hi in ((19, 24), (24, 26), (26, 28), (28, 30), (30, 32), (32, 34), (34, 45)):
        r0 = r1 = w = 0.0; per0, per1 = [], []
        for T in T_:
            (Z, p0), (_, p1) = z0[T], z1[T]; m = (ages[T] >= lo) & (ages[T] < hi)
            if not m.any():
                continue
            ww = Z['w'][m]; r0 += (ww * (Z['y'][m] - p0[m])).sum(); r1 += (ww * (Z['y'][m] - p1[m])).sum(); w += ww.sum()
            per0.append((ww * (Z['y'][m] - p0[m])).sum() / ww.sum()); per1.append((ww * (Z['y'][m] - p1[m])).sum() / ww.sum())
        tot = sum(z0[T][0]['w'].sum() for T in T_)
        print(f"   age {lo}-{hi}: {1000*r0/w:+6.2f} (SE {1000*np.std(per0, ddof=1)/np.sqrt(len(per0)):.2f}) | {1000*r1/w:+6.2f} (SE {1000*np.std(per1, ddof=1)/np.sqrt(len(per1)):.2f})   share {w/tot:.3f}")
    json.dump(dict(shipped=float(base.mean()), best=list(best), best_mse=float(L.min(axis=0).mean()) if False else float(L[bi].mean())), open(os.path.join(ROOT, 'data', '_wed', 'res_bat_aging.json'), 'w'))


if __name__ == '__main__':
    main()
