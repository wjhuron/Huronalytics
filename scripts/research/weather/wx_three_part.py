"""wx_three_part.py -- three-part description, 2021-2025 (seasons with kinematics).

RESEARCH ONLY. raw = DRAG part (measured per pitch from the trajectory)
                   + ALONG the spin direction + ACROSS it (of what is left).
Within (pitcher, pitch type, season) slopes on pressure and temperature, inches
per unit ln. If the form is right, ALONG reads one exponent for every type and
the response of a part with mean near zero is near zero.
"""
import os, sys, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wx_exponent_sweep import load, OUT, PT
from wx_density_slopes import fe_ols
K = 1.113      # Statcast pfx uses a longer flight than y = 50 ft: measured ratio (wx_build_frame check)

if __name__ == '__main__':
    obs = json.load(open(os.path.join(OUT, 'game_obs.json')))
    P = {k: [] for k in ('a', 'c', 'pt', 'pk', 'g', 'lnP', 'lnT', 'dz', 'dx')}
    off = 0
    for yr in (2021, 2022, 2023, 2024, 2025):
        d = load(yr, obs)
        ok = np.isfinite(d['axis']) & np.isfinite(d['dlift']) & np.isfinite(d['dside_arm'])
        d = {k: v[ok] for k, v in d.items()}
        g = np.unique(d['pid'].astype(np.int64) * 16 + d['pt'], return_inverse=True)[1]
        phi = np.radians(d['axis'])
        ux = np.where(d['rhp'], -np.sin(phi), np.sin(phi)); uz = -np.cos(phi)
        x = d['hb_arm'] - K * d['dside_arm']; z = d['ivb'] - K * d['dlift']
        lnT = -np.log((d['temp'] - 32) * 5 / 9 + 273.15)
        for k, v in (('a', ux * x + uz * z), ('c', -uz * x + ux * z), ('pt', d['pt']), ('pk', d['pk']),
                     ('g', g + off), ('lnP', np.log(d['rho_obsPH']) - lnT), ('lnT', lnT),
                     ('dz', K * d['dlift']), ('dx', K * d['dside_arm'])):
            P[k].append(v)
        off += g.max() + 1
        del d
    D = {k: np.concatenate(v) for k, v in P.items()}
    print(f"{'type':5s} {'part':6s} {'mean':>6s} | {'pressure':>14s} {'=> e':>6s} | {'temperature':>14s} {'=> e':>6s}")
    R = {}
    for i, p in enumerate(PT):
        m = np.where(D['pt'] == i)[0]
        n = np.bincount(D['g'][m]); m = m[n[D['g'][m]] >= 100]
        gg = np.unique(D['g'][m], return_inverse=True)[1]
        X = np.column_stack([D['lnP'][m], D['lnT'][m]])
        for part, col in (('along', 'a'), ('cross', 'c'), ('dragZ', 'dz'), ('dragX', 'dx')):
            y = D[col][m]; b, se = fe_ols(y, X, gg, D['pk'][m]); mu = float(y.mean())
            e = lambda v: v / mu if abs(mu) > 1.5 else float('nan')
            R[f'{p}_{part}'] = dict(mean=mu, bP=float(b[0]), bT=float(b[1]), seP=float(se[0]), seT=float(se[1]))
            print(f'{p:5s} {part:6s} {mu:6.1f} | {b[0]:7.1f} ({se[0]:4.1f}) {e(b[0]):6.2f} | {b[1]:7.1f} ({se[1]:4.1f}) {e(b[1]):6.2f}')
    json.dump(R, open(os.path.join(OUT, 'three_part.json'), 'w'), indent=1)
