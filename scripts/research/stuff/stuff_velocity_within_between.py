"""stuff_velocity_within_between.py — is the Stuff+ velocity slope right BETWEEN pitchers?

Found 2026-11-25 (Webb's sinker). Reads data/_stuff_relx/oof.pkl (stuff_relx_calibration.py
fit: six seasons, shipped design, pitcher folds pooled over every season). Per pitch type,
the slope of actual value and of the model's value on velocity, three ways: over all
pitches, within a pitcher-season, and between pitcher-seasons. Stuff+ points per mph,
pitcher bootstrap. The model is calibrated over all pitches; that slope blends a steep
within-pitcher slope with a shallow between-pitcher one, so between pitchers the model
credits velocity more than the outcomes do.

Usage: PYTHONHASHSEED=0 python3 scripts/research/stuff/stuff_velocity_within_between.py
"""
import json, os, sys
import numpy as np, pandas as pd
D = pd.read_pickle('data/_stuff_relx/oof.pkl')
D['pitcher'] = D['pitcher'].astype(str); D['pitch_type'] = D['pitch_type'].astype(str)
lg = json.load(open('data/stuff_bundle_info.json'))['league']
rng = np.random.default_rng(0)
def slopes(s, x):
    """pitch-level total, within pitcher-season, and between pitcher-season slopes of act and model on x,
    pitcher bootstrap from per-pitcher sufficient statistics"""
    s = s[np.isfinite(s[x])].copy()
    g = s.groupby(['pitcher', 'season'])
    for c in (x, 'act', 'full'):
        s['m_' + c] = g[c].transform('mean')
    s['xw'] = s[x] - s['m_' + x]
    xb = s['m_' + x] - s[x].mean(); xt = s[x] - s[x].mean()
    st = pd.DataFrame({'pitcher': s['pitcher'],
        'tt': xt * xt, 'ta': xt * s['act'], 'tf': xt * s['full'],
        'ww': s['xw'] ** 2, 'wa': s['xw'] * s['act'], 'wf': s['xw'] * s['full'],
        'bb': xb * xb, 'ba': xb * s['act'], 'bf': xb * s['full']}).groupby('pitcher').sum().values
    def est(T):
        t = T.sum(0); return np.array([t[1]/t[0], t[2]/t[0], t[4]/t[3], t[5]/t[3], t[7]/t[6], t[8]/t[6]])
    b = est(st); idx = rng.integers(0, len(st), (500, len(st)))
    bs = np.array([est(st[i]) for i in idx])
    se = bs.std(0); gap = bs[:, 0::2] - bs[:, 1::2]
    return b, se, gap.std(0)
for pt in ('FF', 'SI', 'SL', 'ST', 'CH', 'CU', 'FC', 'FS'):
    s = D[D['pitch_type'] == pt].copy(); pts = 10.0 / lg[pt]['sd']
    s['act'] = -s['target_xrv'].astype(float) * pts; s['full'] = -s['pred_FULL'].astype(float) * pts
    b, se, gs = slopes(s, 'velocity')
    # calibration slope: pitcher-season mean actual on mean model (units of 100+ pitches)
    u = s.groupby(['pitcher', 'season']).agg(a=('act', 'mean'), f=('full', 'mean'), n=('act', 'size')); u = u[u['n'] >= 100]
    w = u['n'].values; fm = np.average(u['f'], weights=w)
    cal = (w * (u['f'] - fm) * u['a']).sum() / (w * (u['f'] - fm) ** 2).sum()
    print(f"{pt} per mph | pitch-level: outcomes {b[0]:5.2f} model {b[1]:5.2f} gap {b[0]-b[1]:5.2f} ({gs[0]:.2f}) | "
          f"within pitcher: outcomes {b[2]:5.2f} ({se[2]:.2f}) model {b[3]:5.2f} gap {b[2]-b[3]:5.2f} ({gs[1]:.2f}) | "
          f"between pitchers: outcomes {b[4]:5.2f} ({se[4]:.2f}) model {b[5]:5.2f} gap {b[4]-b[5]:5.2f} ({gs[2]:.2f}) | "
          f"calibration slope (unit actual on unit model) {cal:.2f}")
