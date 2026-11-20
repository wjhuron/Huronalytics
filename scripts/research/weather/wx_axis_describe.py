"""wx_axis_describe.py -- how do the along-spin and across-spin parts respond to
pressure (altitude) and to temperature, by pitch type?  RESEARCH ONLY.

Within (pitcher, pitch type[, month]) fixed effects, pooled 2021-2026 with season
in the group key. Slopes in INCHES per unit ln; x 0.19 = the Coors pressure effect,
x 0.057 = a 30 F temperature swing. A pure density effect with exponent e reads
slope = e * mean for both drivers.
"""
import os, sys, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wx_exponent_sweep import load, OUT, YEARS, PT
from wx_axis_form import prep
from wx_density_slopes import fe_ols

if __name__ == '__main__':
    by_month = len(sys.argv) > 1 and sys.argv[1] == 'month'
    obs = json.load(open(os.path.join(OUT, 'game_obs.json')))
    keep = ('a', 'c', 'pt', 'pk', 'ivb', 'hb_arm')
    parts = {k: [] for k in keep + ('g', 'lnP', 'lnT')}
    off = 0
    for yr in YEARS:
        d = prep(load(yr, obs), 'obsPH')
        tk = (d['temp'] - 32) * 5 / 9 + 273.15
        lnT = -np.log(tk)
        lnP = np.log(d['rho_obsPH']) - lnT            # pressure and humidity part
        key = d['g'].astype(np.int64)
        if by_month:
            mo = np.array([int(s[5:7]) for s in d['date']])
            key = key * 16 + mo
        g = np.unique(key, return_inverse=True)[1]
        for k in keep:
            parts[k].append(d[k])
        parts['g'].append(g + off); off += g.max() + 1
        parts['lnP'].append(lnP); parts['lnT'].append(lnT)
        del d
    D = {k: np.concatenate(v) for k, v in parts.items()}
    print(('WITH month in the group' if by_month else 'season groups') + '; slopes in inches per unit ln (se)')
    print(f"{'type':5s} {'part':6s} {'mean':>6s} | {'pressure':>14s} {'=> e':>6s} | {'temperature':>14s} {'=> e':>6s}")
    R = {}
    for i, p in enumerate(PT):
        m = D['pt'] == i
        n = np.bincount(D['g'][m]); big = n[D['g'][m]] >= (30 if by_month else 100)
        idx = np.where(m)[0][big]
        gg = np.unique(D['g'][idx], return_inverse=True)[1]
        X = np.column_stack([D['lnP'][idx], D['lnT'][idx]])
        for part, col in (('along', 'a'), ('cross', 'c'), ('ride', 'ivb'), ('run', 'hb_arm')):
            y = D[col][idx]
            b, se = fe_ols(y, X, gg, D['pk'][idx])
            mu = float(y.mean())
            eP = b[0] / mu if abs(mu) > 3 else float('nan'); eT = b[1] / mu if abs(mu) > 3 else float('nan')
            R[f'{p}_{part}'] = dict(mean=mu, bP=float(b[0]), seP=float(se[0]), bT=float(b[1]), seT=float(se[1]))
            print(f'{p:5s} {part:6s} {mu:6.1f} | {b[0]:7.1f} ({se[0]:4.1f}) {eP:6.2f} | {b[1]:7.1f} ({se[1]:4.1f}) {eT:6.2f}')
    json.dump(R, open(os.path.join(OUT, f'axis_describe{"_month" if by_month else ""}.json'), 'w'), indent=1)
