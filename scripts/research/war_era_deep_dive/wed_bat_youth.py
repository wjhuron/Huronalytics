"""wed_bat_youth.py - test 2c: an age-dependent prior for the hpWAR hitter projection (the OOPSY idea: the
regression target depends on age). The shipped calibration by age leaves hitters under 24 at +9 wOBA points
(SE 3.2) and 24-26 at +4.9 (SE 2.0). Candidate: mu(E, age) = (c + g * max(0, A0 - age)) / (1 + E / k), so a
young thin-history hitter regresses toward a higher level than an old one. Also a plain youth level term
that does not fade with experience. Honest pool, leave-one-target-season-out.
.venv/bin/python scripts/research/war_era_deep_dive/wed_bat_youth.py"""
import sys, os, itertools
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'projection'))
import bat_experience_test as BX
T_ = BX.TARGETS; N0, C, K, WA = 450, -0.04, 200, 0.75


def main():
    Dr, Aaa, Mlb = BX.build(); Z = {T: BX.arrays(Dr[T], BX.bridge_beta(Aaa, Mlb, T)) for T in T_}
    age = {T: np.array([r['age'] for r in Dr[T]], float) for T in T_}

    def proj(T, g, a0, fade, c=C):
        z = Z[T]; y = np.maximum(0, a0 - age[T])
        mu = (c + (g * y if fade else 0)) / (1 + z['E'] / K)
        mu = np.where(z['has_a'], WA * z['mu_a'] + (1 - WA) * mu, mu)
        p = (z['num'] + N0 * mu) / (z['den'] + N0) + z['aging']
        return p + (0 if fade else g * y)
    base = np.array([BX.wmse(proj(T, 0, 27, True), Z[T]) for T in T_]); base_r = np.array([BX.wmse(proj(T, 0, 27, True), Z[T], Z[T]['w'] >= 200) for T in T_])
    print(f"shipped: MSE x1e4 {base.mean()*1e4:.3f} (regulars {base_r.mean()*1e4:.3f})")
    G = [0.0, 0.001, 0.002, 0.003, 0.004, 0.006, 0.008, 0.012]; A0 = [24, 25, 26, 27, 28, 30]
    for fade, nm in ((True, 'age-dependent PRIOR (fades with MLB experience)'), (False, 'youth LEVEL term (does not fade)')):
        combos = list(itertools.product(G, A0)); L = np.array([[BX.wmse(proj(T, g, a0, fade), Z[T]) for T in T_] for g, a0 in combos])
        Lr = np.array([[BX.wmse(proj(T, g, a0, fade), Z[T], Z[T]['w'] >= 200) for T in T_] for g, a0 in combos])
        best = int(np.argmin(L.mean(axis=1))); ch = [int(np.argmin(L[:, [k for k in range(9) if k != j]].mean(axis=1))) for j in range(9)]
        held = np.array([L[ch[j], j] for j in range(9)]); d = (held - base) / base; dr = (np.array([Lr[ch[j], j] for j in range(9)]) - base_r) / base_r
        print(f"\n {nm}: pooled argmin g {combos[best][0]}, A0 {combos[best][1]} MSE {L[best].mean()*1e4:.3f}")
        print(f"   held-out minus shipped: {100*d.mean():+.2f}% (SE {100*d.std(ddof=1)/3:.2f}), better in {int((d < 0).sum())}/9 | on regulars {100*dr.mean():+.2f}% ({int((dr < 0).sum())}/9); chosen " + " ".join(str(combos[i]) for i in sorted(set(ch), key=ch.count, reverse=True)[:3]))
        print("   g curve at the best A0: " + "  ".join(f"{g}:{L[combos.index((g, combos[best][1]))].mean()*1e4:.3f}" for g in G))
        print("   A0 curve at the best g: " + "  ".join(f"{a}:{L[combos.index((combos[best][0], a))].mean()*1e4:.3f}" for a in A0))
        g, a0 = combos[best]; print("   calibration by age, actual minus projected x1000 (shipped -> candidate):", end=' ')
        for lo, hi in ((19, 24), (24, 26), (26, 28), (28, 30), (30, 45)):
            r0 = r1 = w = 0.0
            for T in T_:
                m = (age[T] >= lo) & (age[T] < hi); ww = Z[T]['w'][m]; r0 += (ww * (Z[T]['y'][m] - proj(T, 0, 27, True)[m])).sum(); r1 += (ww * (Z[T]['y'][m] - proj(T, g, a0, fade)[m])).sum(); w += ww.sum()
            print(f"{lo}-{hi}: {1000*r0/w:+.1f} -> {1000*r1/w:+.1f};", end=' ')
        print()
    # calibration by history size within the young, shipped
    print("\n shipped, hitters under 26 by MLB history PA (actual minus projected x1000, PA share of all):", end=' ')
    tot = sum(Z[T]['w'].sum() for T in T_)
    for lo, hi in ((1, 150), (150, 600), (600, 1500), (1500, 10**6)):
        r0 = w = 0.0
        for T in T_:
            m = (age[T] < 26) & (Z[T]['E'] >= lo) & (Z[T]['E'] < hi); ww = Z[T]['w'][m]; r0 += (ww * (Z[T]['y'][m] - proj(T, 0, 27, True)[m])).sum(); w += ww.sum()
        print(f"{lo}-{hi}: {1000*r0/w:+.1f} ({w/tot:.3f});", end=' ')
    print()


if __name__ == '__main__':
    main()
