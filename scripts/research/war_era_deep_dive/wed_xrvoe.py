"""wed_xrvoe.py - WAR/ERA deep dive, test 16: the xRVOE shrinkage constant (XRVOE_N0 275) on the current models.

XRVOE_N0 was measured 2026-07-14 (split-half, 250-300 pitches), before the Savant plate-plane change, Stuff+ v18
and the Loc+ kernel change. The stored comparison (data/_xrvoe_location_compare.json) reads a split-half r of
.23 at the pitcher level, which does not fit a 275-pitch half-reliability point. This measures it directly on
the released models: per-pitch residuals from the real score-only path (xrvoe_location_compare.capture), two
disjoint random samples of n pitches per unit, r across units, N0 = n (1 - r) / r, 5 seeds.
PYTHONHASHSEED=0 .venv/bin/python scripts/research/war_era_deep_dive/wed_xrvoe.py"""
import sys, os, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'locplus'))
import xrvoe_location_compare as XC


def main():
    T, box = XC.capture(); df, pitches, lg, scale = box['df'], box['pitches'], box['lg'], box['scale']
    import pipeline.locplus as SHIP
    base = [p for p in pitches if SHIP.is_eligible_baseline(p)]
    d, _ = XC.residuals(T, df, XC.exprv_for(SHIP, base, lg, scale), SHIP.group_of_code)
    d = d[['pid', 'pitcher', 'team', 'pitch_type', 'resid']].copy()
    d['game'] = d['pid'].map(lambda k: str(k).split('_')[0])
    d.to_pickle(os.path.join(ROOT, 'data', '_wed', 'xrvoe_resid_2026.pkl'))
    print(f"pitches {len(d)}, per-pitch residual SD {d.resid.std():.4f} runs", flush=True)
    res = {}
    for tag, keys, grid in (('pitcher', ['pitcher', 'team'], (150, 300, 500, 800, 1200)), ('pitch type', ['pitcher', 'team', 'pitch_type'], (75, 150, 300, 500, 800))):
        g = d.groupby(keys)['resid']; idx = {k: v.values for k, v in g}
        print(f"\n {tag}: units with n pitches in each of two disjoint random samples")
        for n in grid:
            rs = []
            for seed in range(5):
                rng = np.random.default_rng(seed); a, b = [], []
                for k, v in idx.items():
                    if len(v) >= 2 * n:
                        p = rng.permutation(len(v)); a.append(v[p[:n]].mean()); b.append(v[p[n:2 * n]].mean())
                if len(a) >= 30:
                    rs.append(np.corrcoef(a, b)[0, 1])
            if rs:
                r = float(np.mean(rs)); k0 = n * (1 - r) / r if r > 0 else float('inf')
                print(f"   n {n:5d}: r {r:.3f} (seeds {np.round(rs, 3)}), units {len(a)} -> N0 {k0:.0f}", flush=True)
                res[f'{tag} {n}'] = dict(r=r, n0=k0, units=len(a))
        # by-game halves at the unit's own size, the stored diagnostic
        d['fold'] = d['game'].map(lambda x: int(x) % 2 if x.isdigit() else 0)
        h = d.groupby(keys + ['fold'])['resid'].agg(['mean', 'size']).unstack('fold'); h = h[(h[('size', 0)] >= 150) & (h[('size', 1)] >= 150)]
        r = float(np.corrcoef(h[('mean', 0)], h[('mean', 1)])[0, 1]); nh = float(np.sqrt(h[('size', 0)] * h[('size', 1)]).mean())
        print(f"   odd / even games, 150+ pitches each: r {r:.3f}, units {len(h)}, mean half size {nh:.0f} -> N0 about {nh * (1 - r) / r:.0f}")
        # variance decomposition: true SD of the unit residual per 100 pitches
        u = d.groupby(keys)['resid'].agg(['mean', 'size', 'var']); u = u[u['size'] >= 300]
        noise = (u['var'] / u['size']).mean(); tv = u['mean'].var() - noise
        print(f"   units with 300+ pitches: observed SD {100 * u['mean'].std():.3f} runs/100, noise SD {100 * np.sqrt(noise):.3f}, implied true SD {100 * np.sqrt(max(tv, 0)):.3f}; N0 = per-pitch var / true var = {d.resid.var() / tv if tv > 0 else float('inf'):.0f}")
    json.dump(res, open(os.path.join(ROOT, 'data', '_wed', 'res_xrvoe.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
