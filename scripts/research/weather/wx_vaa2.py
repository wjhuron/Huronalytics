"""wx_vaa2.py -- approach angle against pressure and temperature, response by pitch shape.

RESEARCH ONLY. wx_vaa.py's form (VAA follows the weather-driven ride change plus one air
term) did not close the Coors gap on held-out seasons. Here the response to each driver
depends on the pitch's own shape (the group's mean neutral ride, inches):

    VAA = b1 * plate_z + b2 * velo + (aP + bP * ride_g) * lnP + (aT + bT * ride_g) * lnT + group mean

Geometry: bP = eP * 57.3 / (12 * D) = about .13 at a fixed target (eP 1.45, D 53 ft).
Coefficients from five seasons, scored on the sixth at Coors; then the six-season fit is
applied UNCHANGED to Triple-A altitude parks (2023-2025; those frames carry kinematics).
"""
import os, sys, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from wx_exponent_sweep import OUT, RHO0, YEARS, PT, COORS, ROOT
from wx_density_slopes import fe_ols
import wx_vaa as V
from wx_aaa_validate import load_aaa
sys.path.insert(0, ROOT)
from pipeline import neutral_move as NM

NAMES = ['pz', 'velo', 'aP', 'bP', 'aT', 'bT']


def design(d):
    g, ng = d['g'], d['g'].max() + 1
    ride_g = (np.bincount(g, weights=d['ivb'] - d['w_ride'], minlength=ng) / np.bincount(g, minlength=ng))[g]
    d['ride_g'] = ride_g
    return np.column_stack([d['pz'], d['velo'], d['lnP'], ride_g * d['lnP'], d['lnT'], ride_g * d['lnT']])


def neutral(d, b):
    return d['vaa'] - (b[2] + b[3] * d['ride_g']) * d['lnP'] - (b[4] + b[5] * d['ride_g']) * d['lnT']


def gap_hi(d, v, b, hi, lo):
    g, ng = d['g'], d['g'].max() + 1
    r = v - b[0] * d['pz'] - b[1] * d['velo']
    nC = np.bincount(g, weights=hi, minlength=ng); nE = np.bincount(g, weights=lo, minlength=ng)
    ok = (nC >= 25) & (nE >= 25)
    w = np.where(ok, 1 / (1 / np.maximum(nC, 1) + 1 / np.maximum(nE, 1)), 0)
    dd = np.bincount(g, weights=r * hi, minlength=ng) / np.maximum(nC, 1) - np.bincount(g, weights=r * lo, minlength=ng) / np.maximum(nE, 1)
    ptg = np.zeros(ng, int); ptg[g] = d['pt']
    return {PT[i]: float(np.sum(w[ptg == i] * dd[ptg == i]) / w[ptg == i].sum()) for i in range(8) if (ok & (ptg == i)).sum() >= 5}


def prep_aaa(yr, obsA):
    d = load_aaa(yr, obsA)
    ok = np.isfinite(d['vaa']) & np.isfinite(d['pz']) & np.isfinite(d['velo'])
    d = {k: v[ok] for k, v in d.items()}
    g = np.unique(d['pid'].astype(np.int64) * 16 + d['pt'], return_inverse=True)[1]
    big = np.bincount(g)[g] >= 100
    d = {k: v[big] for k, v in d.items()}
    d['g'] = np.unique(d['pid'].astype(np.int64) * 16 + d['pt'], return_inverse=True)[1]
    tb = np.where(d['closed'], 72.0, 0.5 * d['temp'] + 0.5 * d['obs_t'])
    lnT = -np.log(((tb - 32) * 5 / 9 + 273.15) / V.T0K)
    d['lnT'] = lnT; d['lnP'] = np.log(d['rho_w50'] / RHO0) - lnT
    z = np.zeros(len(lnT))
    _, n_ride, _ = NM.neutral_components(d['hb_arm'], d['ivb'], d['rhp'], d['axis'], d['velo'], d['lnP'], lnT, z, z)
    d['w_ride'] = d['ivb'] - n_ride
    return d


if __name__ == '__main__':
    obs = json.load(open(os.path.join(OUT, 'game_obs.json'))); W = json.load(open(os.path.join(OUT, 'wind.json')))
    S = {}
    for yr in YEARS:
        d = V.prep(yr, obs, W); X = design(d)
        S[yr] = V.sums(d, d['vaa'], X)
        b, se = fe_ols(d['vaa'], X, d['g'], d['pk'])
        print(f'{yr}: ' + '  '.join(f'{n} {v:+.3f} ({s:.3f})' for n, v, s in zip(NAMES[2:], b[2:], se[2:])), flush=True)
        del d
    G = {}
    for yr in YEARS:
        tr = [y for y in YEARS if y != yr]
        b = np.linalg.solve(sum(S[y][0] for y in tr), sum(S[y][1] for y in tr))
        d = V.prep(yr, obs, W); design(d)
        at = d['venue'] == COORS
        g0 = gap_hi(d, d['vaa'], b, at, ~at); g1 = gap_hi(d, neutral(d, b), b, at, ~at)
        for p in g0:
            G.setdefault(p, []).append((g0[p], g1[p]))
        del d
    rms = lambda G, i: np.sqrt(np.mean([np.mean([x[i] for x in v]) ** 2 for v in G.values() if len(v) >= 3]))
    print('\nHELD OUT Coors VAA gap, degrees (raw -> neutral): ' + '  '.join(
        f'{p} {np.mean([a for a, _ in v]):+.2f} -> {np.mean([c for _, c in v]):+.2f}' for p, v in G.items() if len(v) >= 4))
    print(f'   RMS over pitch types: raw {rms(G, 0):.3f} -> neutral {rms(G, 1):.3f}')
    bf = np.linalg.solve(sum(S[y][0] for y in YEARS), sum(S[y][1] for y in YEARS))
    print('six-season fit: ' + '  '.join(f'{n} {v:+.4f}' for n, v in zip(NAMES, bf)))
    obsA = json.load(open(os.path.join(OUT, 'game_obs_aaa.json'))); GA = {}
    for yr in (2023, 2024, 2025):
        d = prep_aaa(yr, obsA); design(d)
        hi = d['elev'] >= 3000; lo = d['elev'] < 1500
        g0 = gap_hi(d, d['vaa'], bf, hi, lo); g1 = gap_hi(d, neutral(d, bf), bf, hi, lo)
        for p in g0:
            GA.setdefault(p, []).append((g0[p], g1[p]))
        del d
    print('TRIPLE-A altitude parks, MLB fit applied unchanged (raw -> neutral): ' + '  '.join(
        f'{p} {np.mean([a for a, _ in v]):+.2f} -> {np.mean([c for _, c in v]):+.2f}' for p, v in GA.items() if len(v) >= 3))
    print(f'   RMS over pitch types: raw {rms(GA, 0):.3f} -> neutral {rms(GA, 1):.3f}')
    json.dump(dict(fit=dict(zip(NAMES, map(float, bf))), coors=G, aaa=GA), open(os.path.join(OUT, 'vaa2.json'), 'w'), indent=1)
