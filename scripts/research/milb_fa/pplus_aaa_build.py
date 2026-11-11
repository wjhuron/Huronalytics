"""AAA Pitcher+ by pitcher-season, 2023-2025 bases, for the FA-ranking backtest (2026-11-11, per
Wally: test "a weighted blend of K-BB%, SwStr%, and Pitcher+").

The formula is pipeline/pitcherplus.py's, unchanged: the six frozen components, weights and
stabilization constants (COMPONENTS), each z-scored against the qualified pool (QUAL_N pitches),
shrunk by n / (n + k), summed, and put on 100 + 10 z of the composite. Differences from production,
all forced by the level:
  * The pool is the AAA season itself (the AAA-ruler framing: 100 = AAA average). The backtest
    ranks pitchers within a pair, so the anchor only moves a constant.
  * No park adjustment. No minor-league park factors exist; ROC scores neutral in production too.
  * Stuff+ is the target-clean AAA grade (rank_stuff_clean.py 's_r': the model never saw season
    Y+1). Loc+ is the location value on that season's MLB surfaces and xRV/100 the currency-
    corrected value, both from scripts/research/era/aaa_battery_build.py (data/_aaa_battery.json).
    xRV there is batter-positive and is negated here.
  * izWhiff% = 1 - in-zone contact% (zcon_pct = in-zone contact / in-zone swings).

Writes data/_milb_fa/_pplus/aaa_pitcherplus.json in the aaa_stuff_pass format
{'AAA': {season: {pid: {v, n}}}}, which rank_backtest.frame() reads through STUFF_SRC.
    python3 scripts/research/milb_fa/pplus_aaa_build.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
from pipeline.pitcherplus import COMPONENTS, QUAL_N, SCALE_K  # noqa: E402

D = os.path.join(ROOT, 'data', '_milb_fa')
OUT = os.path.join(D, '_pplus', 'aaa_pitcherplus.json')
SEASONS = ('2023', '2024', '2025')


def season_frame(bat, stuff):
    rows = []
    for pid, e in bat.items():
        b = e['battery']
        zc = b.get('zcon_pct')
        st = stuff.get(pid, {})
        xr = e.get('xrv', {}).get('v')
        rows.append({'pid': pid, 'n': b.get('pitches') or 0,
                     'stuffScore': st.get('s_r'), 'locPlus': e.get('loc', {}).get('v'),
                     'kPct': b.get('k_pct'), 'izWhiffPct': None if zc is None else 1 - zc,
                     'xRv100': None if xr is None else -xr, 'gbPct': b.get('gb_pct')})
    return pd.DataFrame(rows)


def score(f):
    q = f[f.n >= QUAL_N]
    comp = pd.Series(0.0, index=f.index)
    ok = pd.Series(True, index=f.index)
    for key, w, k in COMPONENTS:
        mu, sd = q[key].mean(), q[key].std()
        if not sd > 0:
            sys.exit(f'{key}: no spread in the qualified pool ({len(q)} pitchers)')
        ok &= f[key].notna()
        comp += w * (f[key] - mu) / sd * f.n / (f.n + k)
    comp[~ok] = np.nan              # a pitcher missing a channel gets no Pitcher+, not a partial one
    cq = comp[f.n >= QUAL_N]
    return 100 + SCALE_K * (comp - cq.mean()) / cq.std(), ok


def main():
    bat = json.load(open(os.path.join(ROOT, 'data', '_aaa_battery.json')))
    stuff = json.load(open(os.path.join(D, '_rank_stuff_clean.json')))
    out = {'AAA': {}}
    for y in SEASONS:
        if y not in bat:
            sys.exit(f'{y} missing from data/_aaa_battery.json; run scripts/research/era/aaa_battery_build.py --seasons {y}')
        f = season_frame(bat[y], stuff.get(y, {}))
        f['pplus'], ok = score(f)
        miss = (~ok).sum()
        print(f'{y}: {len(f)} pitchers, {ok.sum()} scored, {miss} missing a channel '
              f'(Stuff+ {f.stuffScore.isna().sum()}, Loc+ {f.locPlus.isna().sum()}, xRV {f.xRv100.isna().sum()})')
        q = f[(f.n >= QUAL_N) & ok]
        print('  sign check, r with Pitcher+ on the qualified pool:',
              {c: round(q[c].corr(q.pplus), 2) for c, _, _ in COMPONENTS})
        out['AAA'][y] = {r.pid: {'v': float(r.pplus), 'n': int(r.n)} for r in f[ok].itertuples()}
    tmp = OUT + '.tmp'
    json.dump(out, open(tmp, 'w'))
    os.replace(tmp, OUT)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
