"""stuff_movement_oe_calibration.py — does Stuff+ credit movement over expected enough?

Question (2026-11-25, Webb's sinker): the sinker has about 6 in more drop than its
slot, extension and velocity predict, and the shipped design grades it 100. Do the
held-out outcomes of such pitches agree with the grade?

Reads data/_stuff_relx/oof.pkl (stuff_relx_calibration.py fit): six seasons, the
shipped design, pitcher folds pooled over every season, so no model saw any season
of a pitcher it scores. Expected movement is the hitter basis of pipeline/xmove.py
(per pitch type and season: linear in arm angle, extension, velocity), refitted
here on the frame. A pitcher-season's movement over expected is the mean residual
of his pitches of that type.

Values are Stuff+ points of the pitch type (10 per anchor SD, bundle info), around
the type's mean actual value. SEs are a pitcher bootstrap.

Usage: PYTHONHASHSEED=0 python3 scripts/research/stuff/stuff_movement_oe_calibration.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
from stuff_relx_calibration import OUT, _boot            # noqa: E402

MIN_UNIT = 100       # pitches of a type in a pitcher-season to enter (convention)
TYPES = ('SI', 'FF', 'FC', 'CH', 'FS', 'SL', 'ST', 'CU')


def add_oe(d):
    """ivb_oe / hb_oe: pitch residual from the per-(type, season) hitter-basis fit,
    then the pitcher-season-type mean (u_ivb_oe / u_hb_oe)."""
    d = d[d[['ivb', 'hb', 'arm_angle', 'extension', 'velocity']].notna().all(axis=1)].copy()
    d['ivb_oe'] = np.nan
    d['hb_oe'] = np.nan
    for _, idx in d.groupby(['pitch_type', 'season']).groups.items():
        s = d.loc[idx]
        A = np.c_[np.ones(len(s)), s[['arm_angle', 'extension', 'velocity']].values.astype(float)]
        for t in ('ivb', 'hb'):
            b = np.linalg.lstsq(A, s[t].values.astype(float), rcond=None)[0]
            d.loc[idx, t + '_oe'] = s[t].values - A @ b
    g = d.groupby(['pitcher', 'season', 'pitch_type'])
    d['u_ivb_oe'] = g['ivb_oe'].transform('mean')
    d['u_hb_oe'] = g['hb_oe'].transform('mean')
    d['u_velo'] = g['velocity'].transform('mean')
    d['u_n'] = g['ivb_oe'].transform('size')
    return d[d['u_n'] >= MIN_UNIT]


def add_loc(D):
    """l_loc (the gate's location term) joined row for row from the season frames;
    stops when the rows do not line up with the fit's frame."""
    import stuff_gate_v2 as G
    parts = [G.load_frame(y)[['pitcher', 'velocity', 'target_xrv', 'l_loc']] for y in G.SEASONS]
    F = pd.concat(parts, ignore_index=True)
    F = F[np.isfinite(F['target_xrv'].values)].reset_index(drop=True)
    if len(F) != len(D) or not (F['pitcher'].astype(str).values == D['pitcher'].astype(str).values).all() \
            or not np.allclose(F['target_xrv'].values, D['target_xrv'].values):
        sys.exit('frames do not line up with oof.pkl; refit (stuff_relx_calibration.py fit)')
    D['l_loc'] = F['l_loc'].values
    return D


def slope(sub, x, B=1000, seed=0, a_col='act'):
    """Slope per inch of pitcher-mean actual and predicted value on x, pitch-weighted,
    pitcher bootstrap."""
    g = sub.groupby('pitcher').agg(x=(x, 'mean'), a=(a_col, 'mean'), f=('full', 'mean'),
                                   n=('act', 'size'))
    X, a, f, n = g['x'].values, g['a'].values, g['f'].values, g['n'].values.astype(float)

    def fit(i):
        w = n[i]; xm = np.average(X[i], weights=w)
        den = (w * (X[i] - xm) ** 2).sum()
        sa = (w * (X[i] - xm) * a[i]).sum() / den
        sf = (w * (X[i] - xm) * f[i]).sum() / den
        return sa, sf
    base = fit(np.arange(len(n)))
    rng = np.random.default_rng(seed)
    bs = np.array([fit(rng.integers(0, len(n), len(n))) for _ in range(B)])
    return base, bs.std(0), (bs[:, 0] - bs[:, 1]).std()


def main():
    D = pd.read_pickle(os.path.join(OUT, 'oof.pkl'))
    D['pitcher'] = D['pitcher'].astype(str)
    D['pitch_type'] = D['pitch_type'].astype(str)
    D = add_loc(D)
    print('rows with a location term by season:', D.groupby('season')['l_loc'].apply(lambda v: round(float(np.isfinite(v).mean()), 3)).to_dict())
    lg = json.load(open(os.path.join(ROOT, 'data', 'stuff_bundle_info.json')))['league']
    D = add_oe(D[D['pitch_type'].isin(TYPES)])
    cols = ['act', 'full', 'res', 'res_adj']
    print('== 1. slope per inch of movement over expected: outcomes against the model ==')
    print('   (arm side and ride are positive; a sinker with more drop has negative ivb_oe)')
    keep = {}
    for pt in TYPES:
        s = D[D['pitch_type'] == pt].copy()
        pts = 10.0 / lg[pt]['sd']
        mu = -s['target_xrv'].mean()
        s['act'] = (-s['target_xrv'].astype(float) - mu) * pts
        # the model is centred on its OWN type mean, as the per-type anchor does in production
        s['full'] = (-s['pred_FULL'].astype(float) + s['pred_FULL'].astype(float).mean()) * pts
        s['res'] = s['act'] - s['full']
        # location-adjusted outcome: the location term leaves the actual value (rows with one)
        ll = s['l_loc'].astype(float)
        adj = -(s['target_xrv'].astype(float) - ll)
        s['act_adj'] = (adj - adj[np.isfinite(ll)].mean()) * pts
        s['res_adj'] = s['act_adj'] - s['full']
        print(f'  {pt}: model type mean minus actual type mean {(-s["pred_FULL"].astype(float).mean() - mu) * pts:5.1f} points')
        keep[pt] = s
        for x in ('u_ivb_oe', 'u_hb_oe', 'u_velo'):
            (sa, sf), se, sed = slope(s, x)
            sl = s[np.isfinite(s['l_loc'].astype(float))]
            (la, _), lse, lsed = slope(sl, x, a_col='act_adj')
            print(f'  {pt} {x[2:]:<7} n={len(s):>7} p={s["pitcher"].nunique():>4} SD(x) '
                  f'{s.groupby(["pitcher","season"])[x].first().std():4.1f} in | outcomes '
                  f'{sa:5.2f} ({se[0]:.2f}) | model {sf:5.2f} ({se[1]:.2f}) | gap {sa - sf:5.2f} ({sed:.2f}) || location-adjusted outcomes {la:5.2f} ({lse[0]:.2f})')

    def line(tag, sub):
        if sub['pitcher'].nunique() < 15:
            print(f'  {tag:<40} p={sub["pitcher"].nunique()} (too few)')
            return
        m, se, n, k = _boot(sub, cols)
        la = sub[np.isfinite(sub['l_loc'].astype(float))]
        m2, se2, _, _ = _boot(la, ['res_adj']) if la['pitcher'].nunique() >= 15 else ([np.nan], [np.nan], 0, 0)
        print(f'  {tag:<40} n={n:>7} p={k:>4} | actual {m[0]:6.1f} | model {m[1]:6.1f} | '
              f'actual - model {m[2]:5.1f} ({se[2]:.1f}) | location-adjusted {m2[0]:5.1f} ({se2[0]:.1f})')

    s = keep['SI']
    print('\n== 2. sinkers by drop over expected (pitcher-season mean) ==')
    for a, b in ((-99, -4), (-4, -2), (-2, -1), (-1, 0), (0, 1), (1, 2), (2, 99)):
        line(f'ivb_oe {a:+d}..{b:+d} in', s[(s['u_ivb_oe'] >= a) & (s['u_ivb_oe'] < b)])
    print('\n== 3. the Webb group: ivb_oe under -4 in; band checks ==')
    w = s[s['u_ivb_oe'] < -4]
    line('ivb_oe < -4', w)
    line('ivb_oe < -3', s[s['u_ivb_oe'] < -3])
    line('ivb_oe < -5', s[s['u_ivb_oe'] < -5])
    line('ivb_oe < -4, velocity under 93.5', w[w['u_velo'] < 93.5])
    line('ivb_oe < -4, velocity 93.5 or more', w[w['u_velo'] >= 93.5])
    line('ivb_oe < -4, arm angle 15-32', w[w['arm_angle'].between(15, 32)])
    line('ivb_oe < -4, right-handers', w[w['is_lhp'] == 0])
    print('\n== 4. the Webb group by season ==')
    for y in sorted(s['season'].unique()):
        line(f'{y}', w[w['season'] == y])
    print('\n== 5. sinkers by velocity (the other side of his grade) ==')
    for a, b in ((0, 91), (91, 92.5), (92.5, 94), (94, 95.5), (95.5, 97), (97, 200)):
        line(f'velocity {a}..{b}', s[(s['u_velo'] >= a) & (s['u_velo'] < b)])
    print('\n== 6. other types: the tails of ivb_oe (under -3, over +3) ==')
    for pt in TYPES:
        if pt == 'SI':
            continue
        t = keep[pt]
        line(f'{pt} ivb_oe < -3', t[t['u_ivb_oe'] < -3])
        line(f'{pt} ivb_oe > +3', t[t['u_ivb_oe'] > 3])


if __name__ == '__main__':
    main()
