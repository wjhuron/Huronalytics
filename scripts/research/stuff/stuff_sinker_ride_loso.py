"""Does Stuff+ rate fast, high-ride sinkers correctly? Leave-one-season-out.

The shipped bundle trains on 2021-2025 in every fold, so it cannot score those
seasons honestly. For each season Y in 2021-2026 this fits the production
design (train_stuff.design, TUNED params, monotone velocity) on the other five
seasons, predicts Y, and compares the model's expected run value with the
pitch's own target (target_xrv, the model's training target) on MLB sinkers.

Groups (sinkers only, held-out season):
  fast_hi  velocity >= 96, IVB >= 12
  fast_lo  velocity >= 96, IVB < 8
  region   velocity >= 96, IVB >= 12, |HB| >= 12

Bias in Stuff+ points = K_SCALE * mean(target - prediction) / SI scale sd.
Positive means the pitches did WORSE than the model expected (model overrates).
SE is a pitcher-cluster bootstrap. Run from the repo root:
  .venv/bin/python scripts/research/stuff/stuff_sinker_ride_loso.py
"""
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd
import xgboost as xgb

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'cards'))
import stuff_plus.train_stuff as sv  # noqa: E402

OUT = os.path.join(ROOT, 'data', '_sinker_ride_loso.json')
FRAMES = os.path.join(ROOT, 'data', '_sinker_ride_frames')
YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
GUTS = dict(sv.HIST_GUTS)
GUTS[2025] = (sv.PRIOR_LG_WOBA, sv.PRIOR_WOBA_SCALE)
KEEP = ['pitcher', 'pitch_type', 'velocity', 'ivb', 'hb', 'target_xrv']


def frame(y):
    os.makedirs(FRAMES, exist_ok=True)
    p = os.path.join(FRAMES, f'{y}.pkl')
    if os.path.exists(p):
        return pd.read_pickle(p)
    lg0, sc0 = sv.LG_WOBA, sv.WOBA_SCALE
    if y == 2026:
        import pitcher as cp
        from pipeline.utils import AAA_TEAMS
        rows = [r for r in pickle.load(open(os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl'), 'rb'))
                if r.get('PTeam') not in AAA_TEAMS]
        d = sv.build_df([cp._normalize_scratch_pitch(r) for r in rows])
    else:
        sv.LG_WOBA, sv.WOBA_SCALE = GUTS[y]
        d = sv.build_df(pickle.load(open(sv.HIST_PKL.format(year=y), 'rb')))
        sv.LG_WOBA, sv.WOBA_SCALE = lg0, sc0
    d = d[d['target_xrv'].notna() & d['arm_angle'].notna()].reset_index(drop=True)
    d['season'] = y
    d.to_pickle(p)
    print(f'  {y}: {len(d)} pitches', flush=True)
    return d


def boot(v, g, B=500, seed=0):
    rng = np.random.default_rng(seed)
    ids = pd.unique(g)
    by = {k: v[g == k] for k in ids}
    out = []
    for _ in range(B):
        pick = rng.choice(ids, len(ids))
        s = np.concatenate([by[k] for k in pick])
        out.append(s.mean())
    return float(np.std(out))


def main():
    frames = {y: frame(y) for y in YEARS}
    feats = None
    sd = None
    with open(os.path.join(ROOT, 'stuff_plus', 'stuff_models.pkl'), 'rb') as f:
        b = pickle.load(f)
    feats = b['features']
    sd = sv.live_scales(b)[0]['SI']['sd']
    res = {}
    for y in YEARS:
        tr = pd.concat([frames[o] for o in YEARS if o != y], ignore_index=True)
        Xtr = sv.design(tr).reindex(columns=feats, fill_value=0)
        m = xgb.XGBRegressor(**sv._params_for(Xtr))
        m.fit(Xtr, tr['target_xrv'].values)
        te = frames[y]
        te = te[te['pitch_type'] == 'SI'].reset_index(drop=True)
        Xte = sv.design(te).reindex(columns=feats, fill_value=0)
        te['pred'] = m.predict(Xte)
        te['res'] = te['target_xrv'] - te['pred']
        mu_si = te['pred'].mean()
        grp = {
            'fast_hi': (te.velocity >= 96) & (te.ivb >= 12),
            'fast_lo': (te.velocity >= 96) & (te.ivb < 8),
            'region': (te.velocity >= 96) & (te.ivb >= 12) & (te.hb.abs() >= 12),
            'all_si': te.velocity > 0,
        }
        row = {}
        for k, msk in grp.items():
            s = te[msk]
            if len(s) < 200:
                row[k] = {'n': int(len(s))}
                continue
            row[k] = {
                'n': int(len(s)), 'pitchers': int(s.pitcher.nunique()),
                'stuff': round(float(100 + sv.K_SCALE * (mu_si - s.pred.mean()) / sd), 1),
                'bias_pts': round(float(sv.K_SCALE * s.res.mean() / sd), 2),
                'se_pts': round(sv.K_SCALE * boot(s.res.values, s.pitcher.values) / sd, 2),
            }
        d = te[grp['fast_hi']]
        e = te[grp['fast_lo']]
        if len(d) >= 200 and len(e) >= 200:
            row['hi_minus_lo_bias'] = round(row['fast_hi']['bias_pts'] - row['fast_lo']['bias_pts'], 2)
            row['hi_minus_lo_se'] = round(float(np.hypot(row['fast_hi']['se_pts'], row['fast_lo']['se_pts'])), 2)
        res[y] = row
        print(y, json.dumps(row), flush=True)
        with open(OUT, 'w') as f:
            json.dump(res, f, indent=1)


if __name__ == '__main__':
    main()
