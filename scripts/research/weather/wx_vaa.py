"""wx_vaa.py -- approach angle and the weather.

RESEARCH ONLY. The neutral-movement model (pipeline/neutral_move.py) corrects IVB and HB.
VAA and HAA are still what the pitch did in that game's air: a four-seam crosses the plate
0.22 degrees steeper at Coors. Stuff+ reads `vaa` and `vaa_diff`.

The weather-driven part of a pitch's movement is w = raw - neutral (inches, from the model).
Within (pitcher, pitch type), with plate location held fixed:

    VAA = b * plate_z + c_v * w_ride + group mean        HAA = b * plate_x + c_h * w_run + group mean

Geometry gives the expected c. At a FIXED TARGET, extra drop dz over the flight distance D
steepens the plate angle by dz / D (the pitcher raises his launch angle by dz / D and the
break adds 2 dz / D): c = 57.3 / (12 * D) = about .09 degrees per inch at D = 53 ft. At a
fixed LAUNCH angle it is twice that. So c also says which of the two the pitchers do.

c is fitted on five seasons and scored on the sixth: the held-out Coors gap in VAA (at fixed
plate height), before and after  neutral VAA = VAA - c * w.
"""
import os, sys, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from wx_exponent_sweep import load, OUT, RHO0, YEARS, PT, COORS, ROOT
from wx_density_slopes import fe_ols
from wx_wind_hand_month import wind_arrays
sys.path.insert(0, ROOT)
from pipeline import neutral_move as NM

T0K = 295.6


def prep(yr, obs, W):
    d = load(yr, obs)
    ok = np.isfinite(d['vaa']) & np.isfinite(d['pz']) & np.isfinite(d['haa_arm']) & np.isfinite(d['px_arm']) & np.isfinite(d['velo'])
    d = {k: v[ok] for k, v in d.items()}
    g = np.unique(d['pid'].astype(np.int64) * 16 + d['pt'], return_inverse=True)[1]
    big = np.bincount(g)[g] >= 100
    d = {k: v[big] for k, v in d.items()}
    d['g'] = np.unique(d['pid'].astype(np.int64) * 16 + d['pt'], return_inverse=True)[1]
    tb = np.where(d['closed'], 72.0, 0.5 * d['temp'] + 0.5 * d['obs_t'])
    lnT = -np.log(((tb - 32) * 5 / 9 + 273.15) / T0K)
    lnP = np.log(d['rho_w50'] / RHO0) - lnT
    head, cross = wind_arrays(d['pk'], W)
    head = np.where(d['closed'] | ~np.isfinite(head), 0.0, head); cross = np.where(d['closed'] | ~np.isfinite(cross), 0.0, cross)
    n_run, n_ride, _ = NM.neutral_components(d['hb_arm'], d['ivb'], d['rhp'], d['axis'], d['velo'], lnP, lnT, head, cross)
    d['w_ride'] = d['ivb'] - n_ride; d['w_run'] = d['hb_arm'] - n_run
    d['lnP'] = lnP; d['lnT'] = lnT
    return d


def design(d, loc, w):
    """Columns: plate location, release velocity, the weather-driven movement change, and the
    air itself (pressure part, temperature part). The last two carry what thin air does to the
    angle of EVERY pitch: less drag, a faster ball, less time to drop."""
    return np.column_stack([d[loc], d['velo'], d[w], d['lnP'], d['lnT']])


def sums(d, y, X):
    g, ng = d['g'], d['g'].max() + 1
    cnt = np.bincount(g, minlength=ng)
    dm = lambda v: v - (np.bincount(g, weights=v, minlength=ng) / cnt)[g]
    Xd = np.column_stack([dm(X[:, j]) for j in range(X.shape[1])]); yd = dm(y)
    return Xd.T @ Xd, Xd.T @ yd


def gap(d, v, x_loc, b_loc, b_velo):
    """Coors minus elsewhere, same group, at fixed plate location and release velocity."""
    g, ng = d['g'], d['g'].max() + 1
    r = v - b_loc * x_loc - b_velo * d['velo']
    at = d['venue'] == COORS
    nC = np.bincount(g, weights=at, minlength=ng); nE = np.bincount(g, weights=~at, minlength=ng)
    ok = (nC >= 25) & (nE >= 25)
    w = np.where(ok, 1 / (1 / np.maximum(nC, 1) + 1 / np.maximum(nE, 1)), 0)
    dd = np.bincount(g, weights=r * at, minlength=ng) / np.maximum(nC, 1) - np.bincount(g, weights=r * ~at, minlength=ng) / np.maximum(nE, 1)
    ptg = np.zeros(ng, int); ptg[g] = d['pt']
    return {PT[i]: float(np.sum(w[ptg == i] * dd[ptg == i]) / w[ptg == i].sum()) for i in range(8) if (ok & (ptg == i)).sum() >= 5}


if __name__ == '__main__':
    obs = json.load(open(os.path.join(OUT, 'game_obs.json'))); W = json.load(open(os.path.join(OUT, 'wind.json')))
    S = {}; R = {}
    names = ['loc', 'velo', 'c', 'aP', 'aT']
    for yr in YEARS:
        d = prep(yr, obs, W)
        Xv, Xh = design(d, 'pz', 'w_ride'), design(d, 'px_arm', 'w_run')
        S[yr] = dict(v=sums(d, d['vaa'], Xv), h=sums(d, d['haa_arm'], Xh))
        bv, sev = fe_ols(d['vaa'], Xv, d['g'], d['pk']); bh, seh = fe_ols(d['haa_arm'], Xh, d['g'], d['pk'])
        R[yr] = dict(v=dict(zip(names, map(float, bv))), v_se=dict(zip(names, map(float, sev))), h=dict(zip(names, map(float, bh))))
        D = 60.5 - np.nanmean(d['ext']) - 17 / 12
        print(f'{yr}: VAA  c {bv[2]:.4f} ({sev[2]:.4f})  aP {bv[3]:+.3f} ({sev[3]:.3f})  aT {bv[4]:+.3f} ({sev[4]:.3f})  velo {bv[1]:+.4f} | '
              f'HAA  c {bh[2]:.4f} ({seh[2]:.4f})  aP {bh[3]:+.3f}  aT {bh[4]:+.3f} | geometry c at a fixed target {57.3/(12*D):.4f}', flush=True)
        del d
    print('\nHELD OUT: coefficients from the other five seasons; Coors gap at fixed plate location and velocity, degrees')
    GV = {}; GH = {}
    for yr in YEARS:
        tr = [y for y in YEARS if y != yr]
        bv = np.linalg.solve(sum(S[y]['v'][0] for y in tr), sum(S[y]['v'][1] for y in tr))
        bh = np.linalg.solve(sum(S[y]['h'][0] for y in tr), sum(S[y]['h'][1] for y in tr))
        d = prep(yr, obs, W)
        nv = d['vaa'] - bv[2] * d['w_ride'] - bv[3] * d['lnP'] - bv[4] * d['lnT']
        nh = d['haa_arm'] - bh[2] * d['w_run'] - bh[3] * d['lnP'] - bh[4] * d['lnT']
        g0 = gap(d, d['vaa'], d['pz'], bv[0], bv[1]); g1 = gap(d, nv, d['pz'], bv[0], bv[1])
        h0 = gap(d, d['haa_arm'], d['px_arm'], bh[0], bh[1]); h1 = gap(d, nh, d['px_arm'], bh[0], bh[1])
        for p in g0:
            GV.setdefault(p, []).append((g0[p], g1[p]))
        for p in h0:
            GH.setdefault(p, []).append((h0[p], h1[p]))
        del d
    for name, G in (('VAA', GV), ('HAA (arm side)', GH)):
        print(f' {name}: ' + '  '.join(f'{p} {np.mean([a for a, _ in v]):+.2f} -> {np.mean([b for _, b in v]):+.2f}' for p, v in G.items() if len(v) >= 4))
        print(f'   RMS over pitch types: raw {np.sqrt(np.mean([np.mean([a for a, _ in v]) ** 2 for v in G.values() if len(v) >= 4])):.3f}'
              f' -> neutral {np.sqrt(np.mean([np.mean([b for _, b in v]) ** 2 for v in G.values() if len(v) >= 4])):.3f}')
    fv = np.linalg.solve(sum(S[y]['v'][0] for y in YEARS), sum(S[y]['v'][1] for y in YEARS))
    fh = np.linalg.solve(sum(S[y]['h'][0] for y in YEARS), sum(S[y]['h'][1] for y in YEARS))
    print('\nfull sample VAA: ' + '  '.join(f'{n} {v:+.4f}' for n, v in zip(names, fv)))
    print('full sample HAA: ' + '  '.join(f'{n} {v:+.4f}' for n, v in zip(names, fh)))
    json.dump(dict(by_year=R, vaa=dict(zip(names, map(float, fv))), haa=dict(zip(names, map(float, fh))),
                   coors_vaa=GV, coors_haa=GH), open(os.path.join(OUT, 'vaa.json'), 'w'), indent=1)
