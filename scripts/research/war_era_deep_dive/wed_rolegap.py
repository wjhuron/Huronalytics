"""wed_rolegap.py - WAR/ERA deep dive, test 9: the pitcher role gap (WAR_ROLE_GAP .85 runs/9) with 2026.

war_improve_battery2.role_gap: the same pitcher in the same season as starter and as reliever (50+ PA in each
role), reliever minus starter xwOBA against. The shipped .85 used 2021-2025 (281 swingman seasons). 2026 was
skipped there because the sheet rows carry no Savant xwOBA on every PA; data/_statcast2026_full.pkl does.
PYTHONHASHSEED=0 .venv/bin/python scripts/research/war_era_deep_dive/wed_rolegap.py"""
import sys, os, gc, math
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'era'))
import war_improve_battery2 as B2

COLS = ['game_pk', 'pitcher', 'batter', 'events', 'estimated_woba_using_speedangle']
allg = []
for y in (2021, 2022, 2023, 2024, 2025, 2026):
    # 2026: the only Savant-shaped cache is data/_statcast2026_full.pkl, pulled 2026-07-06, so 2026 is a
    # PARTIAL season here (through early July) and is reported apart from the shipped pool.
    df = B2.df_year(y) if y < 2026 else pd.read_pickle(os.path.join(ROOT, 'data', '_statcast2026_full.pkl'))
    if y == 2026:
        print('2026 cache rows', len(df), 'dates', str(df['game_date'].min())[:10], str(df['game_date'].max())[:10])
    if 'game_type' in df.columns:
        df = df[df['game_type'] == 'R']
    df = df[COLS].copy()
    df['estimated_woba_using_speedangle'] = pd.to_numeric(df['estimated_woba_using_speedangle'], errors='coerce').astype('float64')
    g = B2.role_gap(y, df); del df; gc.collect()
    gp = np.array([x[0] for x in g]); w = np.array([x[1] for x in g], float)
    mu = float(np.average(gp, weights=w)); se = math.sqrt(np.average((gp - mu) ** 2, weights=w) / len(gp))
    print(f"{y}: swingmen {len(g)}, RP - SP xwOBA {mu:+.4f} (SE {se:.4f}) => {mu / 1.23 * 38.3:+.2f} runs/9", flush=True)
    allg += [(y, a, b) for a, b in g]
for label, ys in (('2021-2025 (the shipped pool)', range(2021, 2026)), ('2021-2026', range(2021, 2027))):
    s = [x for x in allg if x[0] in ys]; gp = np.array([x[1] for x in s]); w = np.array([x[2] for x in s], float)
    mu = float(np.average(gp, weights=w)); se = math.sqrt(np.average((gp - mu) ** 2, weights=w) / len(gp))
    print(f"{label}: n {len(s)}, RP - SP xwOBA {mu:+.4f} (SE {se:.4f}) => {mu / 1.23 * 38.3:+.2f} runs/9 (SE {se / 1.23 * 38.3:.2f})")
