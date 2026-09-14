"""hwar_positional_sweep.py — the two fiat constants in hwar_positional.py, swept (2026-09-14).
  design 1: MIN_INN, the innings a switcher needs at both positions (50, 100, 150, 200, 300), on 2023-2026 and 2016-2026
  design 2: BENCH_TOP, the regulars excluded per position (15 .. 60), 2021-2026 pooled, tables built once
Reports the slope on fWAR for each setting: an interior plateau means a measurement, a monotone drift means a definition.
Usage: python3 scripts/research/hitter/hwar_positional_sweep.py
Output: console + data/_hwar_positional_sweep.json
"""
import gc, json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'era'))
from pipeline.hwar import HWAR_POS_ADJ
import hwar_positional as HP
import hwar_team_harness as H
import hwar_hitter_rate_validation as HR

out = {'design1': {}, 'design2': {}}
print("DESIGN 1: slope on fWAR by MIN_INN")
for era, label in ((HP.ERA_CAND, '2023-2026'), (HP.ERA_PRE + HP.ERA_CAND, '2016-2026')):
    for mi in (50, 100, 150, 200, 300):
        HP.MIN_INN = float(mi)
        P = HP.pairs_for(era); lv = HP.solve_levels(P); wts = HP.league_innings(era)
        adj = HP.anchor({p: -lv[p] for p in HP.FIELD}, wts, HWAR_POS_ADJ); sl = HP.slope_on_fwar(adj, wts, HP.FIELD)
        out['design1'][f'{label}:{mi}'] = dict(slope=sl, n_pairs=len(P), adj=adj)
        print(f"  {label} MIN_INN {mi:3d}: pairs {len(P):5d}  slope {sl:+.2f}   " + " ".join(f"{p} {adj[p]:+.1f}" for p in HP.FIELD))
HP.MIN_INN = 100.0

print("\nDESIGN 2: slope on fWAR by BENCH_TOP (tables built once)")
tabs = {}
for y in HP.SEASONS_D2:
    if y < 2026:
        games = H.load_games(y); P = H.pa_table(y, games)
    else:
        P, _ = HR.pa_sheet(2026)
    scale = HR.SCALE[y]; L = float(P['xhb'].mean()); P['bat_pa'] = (P['xhb'] - L) / scale
    g = P.groupby('bid').agg(bat=('bat_pa', 'mean'), n=('bat_pa', 'size')); prim = HP.primary_position(y)
    g['pos'] = g.index.map(lambda b: prim.get(str(b))); g = g[g['pos'].notna()].copy()
    g['rk'] = g.groupby('pos')['n'].rank(ascending=False, method='first'); tabs[y] = g
    del P; gc.collect()
wts7 = HP.league_innings(HP.SEASONS_D2)
for top in (15, 20, 25, 30, 35, 40, 45, 60):
    pool = {p: [] for p in HP.ALL9}
    for y, g in tabs.items():
        b = g[g['rk'] > top]
        for p in HP.ALL9:
            s = b[b['pos'] == p]; pool[p] += list(zip(s['bat'].values, s['n'].values))
    lg_pa = {p: sum(n for _, n in pool[p]) for p in HP.ALL9}
    bench = {p: float(np.average([x for x, _ in pool[p]], weights=[n for _, n in pool[p]])) * 600 if pool[p] else 0.0 for p in HP.ALL9}
    adj = HP.anchor({p: -bench[p] for p in HP.ALL9}, lg_pa, HWAR_POS_ADJ); sl = HP.slope_on_fwar(adj, wts7, HP.FIELD)
    out['design2'][top] = dict(slope=sl, adj=adj, n_pa=lg_pa)
    print(f"  BENCH_TOP {top:2d}: slope {sl:+.2f}  bench PA {sum(lg_pa.values()):6d}   " + " ".join(f"{p} {adj[p]:+.1f}" for p in HP.ALL9))
json.dump(out, open(os.path.join(ROOT, 'data', '_hwar_positional_sweep.json'), 'w'), indent=1, default=float)
print("wrote data/_hwar_positional_sweep.json")
