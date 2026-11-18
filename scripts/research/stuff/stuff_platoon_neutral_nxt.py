"""Platoon-neutral Stuff+: does grading a pitch at its type's league platoon mix
predict next season better than grading it at the matchups it was thrown in?

Shipped Stuff+ feeds platoon_same (batter hand == pitcher hand) to the model, so
a pitch thrown only to same-side hitters is credited with that matchup. The
neutral grade scores every pitch twice (platoon_same 0 and 1) and blends the two
with the type's league same-side share in season Y. A pitch type's average is
kept; only a pitcher's departure from typical deployment leaves the grade.

For each pair (Y, Y+1), 2021-2026, the production design (train_stuff.design,
TUNED params, monotone velocity) is fit on the OTHER four seasons, so the model
saw neither the grading season nor the target season (the nxt_r rule).

Unit: pitcher x pitch type x throwing hand, >= MIN_N pitches in both seasons
(frames carry the season tags; 2021-2025 are public Statcast tags).
Targets, Y+1 mean target_xrv of the same unit:
  raw   the target as it is
  padj  the target less the Y+1 league mean for (type, platoon_same), so the
        Y+1 matchup mix is taken out of the outcome
Correlation is taken within (type, hand) and pooled by unit count, so the type
scale and the hand level cannot carry it. Paired pitcher-cluster bootstrap on
the neutral minus shipped difference.

Run from the repo root (frames from stuff_sinker_ride_loso.py are reused):
  PYTHONHASHSEED=0 .venv/bin/python scripts/research/stuff/stuff_platoon_neutral_nxt.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd
import xgboost as xgb

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'stuff'))
import stuff_plus.train_stuff as sv  # noqa: E402
from stuff_sinker_ride_loso import frame, YEARS  # noqa: E402

OUT = os.path.join(ROOT, 'data', '_platoon_neutral_nxt.json')
MIN_N = 50
B = 500


def unit_table(d, col):
    g = d.groupby(['pitcher', 'pitch_type', 'throws'])
    return g[col].agg(['mean', 'size'])


def pooled_r(df, gcol, tcol):
    rs, ws = [], []
    for _, s in df.groupby(['pitch_type', 'throws']):
        if len(s) < 15 or s[gcol].std() == 0:
            continue
        rs.append(np.corrcoef(s[gcol], s[tcol])[0, 1])
        ws.append(len(s))
    return float(np.average(rs, weights=ws)) if rs else float('nan')


def main():
    feats = None
    import pickle
    with open(os.path.join(ROOT, 'stuff_plus', 'stuff_models.pkl'), 'rb') as f:
        feats = pickle.load(f)['features']
    frames = {y: frame(y) for y in YEARS}
    res = {}
    for y in YEARS[:-1]:
        y1 = y + 1
        tr = pd.concat([frames[o] for o in YEARS if o not in (y, y1)], ignore_index=True)
        Xtr = sv.design(tr).reindex(columns=feats, fill_value=0)
        m = xgb.XGBRegressor(**sv._params_for(Xtr))
        m.fit(Xtr, tr['target_xrv'].values)
        del tr, Xtr

        d = frames[y].copy()
        X = sv.design(d).reindex(columns=feats, fill_value=0)
        d['ship'] = -m.predict(X)
        X1 = X.copy(); X1['platoon_same'] = 1
        X0 = X.copy(); X0['platoon_same'] = 0
        p1, p0 = -m.predict(X1), -m.predict(X0)
        w = d.groupby('pitch_type')['platoon_same'].transform('mean').values
        d['neut'] = w * p1 + (1 - w) * p0
        d['gap'] = p1 - p0

        t = frames[y1].copy()
        lg = t.groupby(['pitch_type', 'platoon_same'])['target_xrv'].transform('mean')
        t['padj'] = t['target_xrv'] - lg

        gs = unit_table(d, 'ship').rename(columns={'mean': 'ship', 'size': 'n'})
        gs['neut'] = unit_table(d, 'neut')['mean']
        gs['same'] = unit_table(d, 'platoon_same')['mean']
        tt = unit_table(t, 'target_xrv').rename(columns={'mean': 'raw', 'size': 'n1'})
        tt['padj'] = unit_table(t, 'padj')['mean']
        u = gs.join(tt, how='inner')
        u = u[(u.n >= MIN_N) & (u.n1 >= MIN_N)].reset_index()

        # grades are run-prevention (higher = better); targets are batter runs, so r < 0
        row = {'units': int(len(u)), 'pitchers': int(u.pitcher.nunique())}
        for tc in ('raw', 'padj'):
            a, b_ = pooled_r(u, 'ship', tc), pooled_r(u, 'neut', tc)
            rng = np.random.default_rng(0)
            ids = u.pitcher.unique()
            by = {k: v for k, v in u.groupby('pitcher')}
            ds = []
            for _ in range(B):
                s = pd.concat([by[k] for k in rng.choice(ids, len(ids))], ignore_index=True)
                ds.append(-(pooled_r(s, 'neut', tc) - pooled_r(s, 'ship', tc)))
            row[tc] = {'ship_r': round(-a, 4), 'neut_r': round(-b_, 4),
                       'delta': round(-(b_ - a), 4), 'se': round(float(np.std(ds)), 4)}
        # size of the change, in Stuff+ points on the bundle's per-type scale
        sc = None
        with open(os.path.join(ROOT, 'stuff_plus', 'stuff_models.pkl'), 'rb') as f:
            sc = sv.live_scales(pickle.load(f))[0]
        mv = {}
        for pt, s in u.groupby('pitch_type'):
            if pt not in sc or len(s) < 20:
                continue
            dp = sv.K_SCALE * (s.neut - s.ship) / sc[pt]['sd']
            mv[pt] = {'n': int(len(s)), 'same_share': round(float(s.same.mean()), 2),
                      'mean_pts': round(float(dp.mean()), 2), 'sd_pts': round(float(dp.std()), 2),
                      'max_abs_pts': round(float(dp.abs().max()), 1)}
        row['move'] = mv
        row['gap_pts_by_type'] = {pt: round(float(sv.K_SCALE * s.gap.mean() / sc[pt]['sd']), 2)
                                  for pt, s in d.groupby('pitch_type') if pt in sc}
        res[f'{y}->{y1}'] = row
        print(f'{y}->{y1}', json.dumps({k: row[k] for k in ('units', 'raw', 'padj')}), flush=True)
        with open(OUT, 'w') as f:
            json.dump(res, f, indent=1)


if __name__ == '__main__':
    main()
