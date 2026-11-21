"""wx_other_metrics.py -- which per-pitch metrics does the weather move?

RESEARCH ONLY. 2021-2025 (the seasons with kinematics), pooled, within
(season, pitcher, pitch type). Each metric is regressed on the two parts of air density,
lnP (measured pressure and humidity) and lnT (temperature, feed / measured blend), SE
clustered by game. Read as:
    at Coors   = slope on lnP x (-0.18), the Coors pressure deficit
    hot day    = slope on lnT x (-0.037), a day 20 F warmer (70 F -> 90 F)
A physical air effect shows on BOTH drivers with one sign per unit of density. An effect
on one driver only is the pitcher or the ball reacting to altitude or heat, not the air
acting on the flight.
"""
import os, sys, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from wx_exponent_sweep import load, OUT, RHO0, PT
from wx_density_slopes import fe_ols

T0K = 295.6
COORS_LNP, HOT_LNT = -0.18, -0.037
METRICS = [('velo', 'release velocity', 'mph'), ('vplate', 'velocity at the plate', 'mph'), ('tflight', 'flight time', 's'),
           ('spin', 'spin rate', 'rpm'), ('ext', 'extension', 'ft'), ('relz', 'release height', 'ft'),
           ('relx_arm', 'release side (arm side +)', 'ft'), ('arm_angle', 'arm angle', 'deg'),
           ('ivb', 'induced vertical break', 'in'), ('hb_arm', 'horizontal break (arm side +)', 'in'),
           ('vaa', 'vertical approach angle', 'deg'), ('haa_arm', 'horizontal approach angle', 'deg'),
           ('pz', 'plate height', 'ft'), ('px_arm', 'plate side (arm side +)', 'ft')]

if __name__ == '__main__':
    obs = json.load(open(os.path.join(OUT, 'game_obs.json')))
    parts, off = {}, 0
    keep = [m[0] for m in METRICS] + ['pk', 'pt', 'lnP', 'lnT', 'g', 'whiff', 'swing', 'bip', 'ev', 'la', 'dist', 'xwoba']
    for yr in (2021, 2022, 2023, 2024, 2025):
        d = load(yr, obs)
        g = np.unique(d['pid'].astype(np.int64) * 16 + d['pt'], return_inverse=True)[1]
        big = np.bincount(g)[g] >= 100
        d = {k: v[big] for k, v in d.items()}
        d['g'] = np.unique(d['pid'].astype(np.int64) * 16 + d['pt'], return_inverse=True)[1] + off
        off = d['g'].max() + 1
        tb = np.where(d['closed'], 72.0, 0.5 * d['temp'] + 0.5 * d['obs_t'])
        d['lnT'] = -np.log(((tb - 32) * 5 / 9 + 273.15) / T0K); d['lnP'] = np.log(d['rho_w50'] / RHO0) - d['lnT']
        for k in keep:
            parts.setdefault(k, []).append(d[k])
        del d
    D = {k: np.concatenate(v) for k, v in parts.items()}
    R = {}

    def fit(y, mask, extra=None):
        m = mask & np.isfinite(y)
        gg = np.unique(D['g'][m], return_inverse=True)[1]
        X = np.column_stack([D['lnP'][m], D['lnT'][m]] + ([e[m] for e in extra] if extra else []))
        b, se = fe_ols(y[m], X, gg, D['pk'][m])
        return b, se, int(m.sum()), float(np.nanmean(y[m])), float(np.nanstd(y[m] - (np.bincount(gg, weights=y[m]) / np.bincount(gg))[gg]))

    print(f"{'metric':34s} {'mean':>8s} {'within-pitcher sd':>18s} | {'at Coors':>10s} {'(z)':>6s} | {'20 F hotter':>12s} {'(z)':>6s}   unit")
    allm = np.ones(len(D['pk']), bool)
    for scope, mask in (('ALL PITCHES', allm), ('FOUR-SEAM ONLY', D['pt'] == 0)):
        print(scope)
        for key, label, unit in METRICS:
            b, se, n, mu, sdw = fit(D[key].astype(float), mask)
            R[f'{scope}|{key}'] = dict(coors=float(b[0] * COORS_LNP), z_p=float(b[0] / se[0]), hot=float(b[1] * HOT_LNT), z_t=float(b[1] / se[1]), mean=mu, sd_within=sdw)
            print(f'  {label:32s} {mu:8.2f} {sdw:18.2f} | {b[0]*COORS_LNP:+10.3f} {b[0]/se[0]:+6.1f} | {b[1]*HOT_LNT:+12.3f} {b[1]/se[1]:+6.1f}   {unit}')
    print('RESULTS OF THE PITCH (all pitches)')
    sw = D['swing'].astype(bool)
    b, se, n, mu, _ = fit(D['whiff'].astype(float), sw)
    print(f"  {'whiff per swing':32s} {mu:8.3f} {'':18s} | {b[0]*COORS_LNP:+10.4f} {b[0]/se[0]:+6.1f} | {b[1]*HOT_LNT:+12.4f} {b[1]/se[1]:+6.1f}   rate")
    R['whiff'] = dict(coors=float(b[0] * COORS_LNP), hot=float(b[1] * HOT_LNT), z_p=float(b[0] / se[0]), z_t=float(b[1] / se[1]))
    bip = D['bip'].astype(bool)
    for key, label, unit in (('ev', 'exit velocity', 'mph'), ('la', 'launch angle', 'deg'), ('xwoba', 'xwOBA on contact', '')):
        b, se, n, mu, _ = fit(D[key].astype(float), bip)
        R[key] = dict(coors=float(b[0] * COORS_LNP), hot=float(b[1] * HOT_LNT), z_p=float(b[0] / se[0]), z_t=float(b[1] / se[1]))
        print(f'  {label:32s} {mu:8.3f} {"":18s} | {b[0]*COORS_LNP:+10.3f} {b[0]/se[0]:+6.1f} | {b[1]*HOT_LNT:+12.3f} {b[1]/se[1]:+6.1f}   {unit}')
    fly = bip & (D['la'] >= 20) & (D['la'] <= 35) & (D['ev'] >= 95)
    ev_c, la_c = D['ev'] - 100.0, D['la'] - 27.0
    b, se, n, mu, _ = fit(D['dist'].astype(float), fly, extra=[np.nan_to_num(ev_c), np.nan_to_num(la_c), np.nan_to_num(la_c) ** 2])
    print(f"  {'fly-ball distance at equal EV, LA':32s} {mu:8.1f} {'':18s} | {b[0]*COORS_LNP:+10.1f} {b[0]/se[0]:+6.1f} | {b[1]*HOT_LNT:+12.1f} {b[1]/se[1]:+6.1f}   ft  (n {n})")
    R['fly_dist'] = dict(coors=float(b[0] * COORS_LNP), hot=float(b[1] * HOT_LNT), z_p=float(b[0] / se[0]), z_t=float(b[1] / se[1]), n=n)
    json.dump(R, open(os.path.join(OUT, 'other_metrics.json'), 'w'), indent=1)
