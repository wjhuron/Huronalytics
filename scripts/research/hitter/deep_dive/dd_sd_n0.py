"""dd_sd_n0.py - SD+ n0 under the zone x two-strike mix (and the zone-only control), protocol of
n0_remeasure_2026_08.py: per-hitter subsample split-half at fixed N per half, implied n0 = N (1 - r) / r,
seasons 2024-2026, 3 seeds; plus a parity check of pipeline.sdplus against the research frames."""
import sys, os
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dd_lib as L

NS = (60, 90, 125, 190, 250, 375, 500)
ZI = {z: i for i, z in enumerate(['heart', 'shadow_in', 'shadow_out', 'chase', 'waste'])}


def run(seasons=(2024, 2025, 2026), seeds=3):
    rows = {m: {N: [] for N in NS} for m in ('zone', 'zone x 2K')}
    for Y in seasons:
        d = L.load(Y)['df']; e = d[d.sd_el]
        z = e.zone.astype(str).map(ZI).values; s2 = (e.s.values == 2).astype(int); dv = e.dv.values.astype(float)
        cells = {'zone': z, 'zone x 2K': z * 2 + s2}; ncell = {'zone': 5, 'zone x 2K': 10}
        lgw = {m: np.bincount(c, minlength=ncell[m]) / len(c) for m, c in cells.items()}
        idx = e.groupby('bid', observed=True).indices
        for N in NS:
            hs = [v for v in idx.values() if len(v) >= 2 * N]
            if len(hs) < 30:
                continue
            for seed in range(seeds):
                rng = np.random.default_rng(1000 * seed + N + Y)
                acc = {m: ([], []) for m in cells}
                for v in hs:
                    p = rng.permutation(v)
                    for m, c in cells.items():
                        out = []
                        for part in (p[:N], p[N:2 * N]):
                            n = np.bincount(c[part], minlength=ncell[m]); sm = np.bincount(c[part], weights=dv[part], minlength=ncell[m]); ok = n > 0
                            out.append(float((sm[ok] / n[ok] * lgw[m][ok]).sum() / lgw[m][ok].sum()))
                        acc[m][0].append(out[0]); acc[m][1].append(out[1])
                for m in cells:
                    rows[m][N].append(float(np.corrcoef(acc[m][0], acc[m][1])[0, 1]))
        L.drop(Y)
    for m in rows:
        print(f"{m}:  N/half : mean r : implied n0")
        for N in NS:
            if rows[m][N]:
                r = np.mean(rows[m][N]); print(f"   {N:4d}  {r:.3f}  {N * (1 - r) / r:6.0f}")
    return rows


def parity(Y=2025):
    import dd_build as B, pipeline.sdplus as sd
    from dd_follow import neutral2
    from collections import defaultdict
    P = [p for p in B.load_pub(Y) if p.get('Batter')]; lg, sc = B.A.GUTS[Y]
    by = defaultdict(list)
    for p in P:
        by[(p['Batter'], '')].append(p)
    res, _ = sd.compute_sd_plus(P, by, lg, sc)
    mine = neutral2(L.load(Y)['df'])
    pr = pd.Series({k[0]: v['raw_sd'] for k, v in res.items()}); k = pr.index.intersection(mine.index)
    print(f"parity {Y}: pipeline raw_sd against the research frame on {len(k)} hitters: max |d| {np.max(np.abs(pr[k] - mine[k])):.2e}")


if __name__ == '__main__':
    run()
    parity()
