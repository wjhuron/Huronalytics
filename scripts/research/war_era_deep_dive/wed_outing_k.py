"""wed_outing_k.py - WAR/ERA deep dive, test 18: the Pitching+ outing shrinkage for CSW (398) and xRV (1581).

Those two k values are reliability crossings (per season 293-768 and 954-5180). The repo's own lesson is that a
composite's shrinkage is decided by the composite's curve, not by a component's reliability crossing; that sweep
was run for the stuff and loc k only. Same harness as pitcherplus_outing_location.lock, on the released (far-miss)
outing tables: frozen shipped weights, and weights refit out of fold by season.
PYTHONHASHSEED=0 .venv/bin/python scripts/research/war_era_deep_dive/wed_outing_k.py"""
import sys, os, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'stuff')); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'misc'))
import pitcherplus_outing_refit as R
R.TABLES = os.path.join(ROOT, 'data', '_pplus_outing_tables_far.pkl')
four = ['stuffAtom', 'locRaw', 'cswPct', 'xrv100']
t = R.load_tables()[0]; params = R.pool_params(t, four); cols = list(range(4)); out = {}
print('shipped k', R.SHIPPED_K, 'weights', R.SHIPPED_W)
for comp, grid in (('cswPct', (50, 100, 200, 300, 398, 600, 900, 1500, 3000, 8000)), ('xrv100', (200, 400, 800, 1200, 1581, 2500, 4000, 8000, 20000)), ('stuffAtom', (5, 10, 20, 42, 80, 150, 300))):
    rows = []
    for k in grid:
        km = dict(R.SHIPPED_K); km[comp] = float(k)
        X, y, g, _ = R.build_split_panel(t, km, params, four)
        fr, ff = R.fixed_r(X, y, g, cols, [R.SHIPPED_W[f] for f in four]); orr, of = R.oof_r(X, y, g, cols)
        ff = list(ff.values()) if isinstance(ff, dict) else list(ff)
        rows.append((k, fr, orr, ff))
    base = next(r for r in rows if abs(r[0] - R.SHIPPED_K[comp]) < 1)
    print(f"\n{comp}: outing composite r by k (others at shipped); shipped {R.SHIPPED_K[comp]}")
    print(f"{'k':>7s}{'frozen w':>10s}{'refit w':>9s}  frozen minus shipped (SE over seasons; better in)")
    for k, fr, orr, ff in rows:
        d = np.array(ff) - np.array(base[3])
        print(f"{k:>7d}{fr:>10.4f}{orr:>9.4f}  {d.mean():+.4f} (SE {d.std(ddof=1)/np.sqrt(len(d)):.4f}; {int((d > 0).sum())}/{len(d)})")
    out[comp] = [dict(k=k, frozen=fr, oof=orr) for k, fr, orr, _ in rows]
json.dump(out, open(os.path.join(ROOT, 'data', '_wed', 'res_outing_k.json'), 'w'), indent=1, default=float)
