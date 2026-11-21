"""wx_all_metrics.py -- one weather model per pitch metric, with the same tests movement got.

RESEARCH ONLY. For each metric m (release velocity, spin rate, extension, release height,
release side, arm angle, vertical and horizontal approach angle):

    neutral m = m - (aP + bP * z) * lnP - (aT + bT * z) * lnT

lnP = pressure-and-humidity part of ln(air density / reference), lnT = temperature part
(feed / measured blend), both from pipeline/neutral_move.py inputs. z is the pitch's neutral
ride (VAA) or neutral run (HAA), and absent for the other metrics (bP = bT = 0).

Fit: within (pitcher, pitch type, MONTH), so the calendar cannot pose as the weather (arms
get stronger from April to July; 2026-11-21: the heat effect on release height vanished
with the month in the group). The approach angles also hold plate location and release
velocity fixed.

Tests, each with coefficients the test data never saw:
  COORS    held-out season: metric at Coors minus the same pitcher elsewhere, raw -> neutral
  HEAT     held-out season: what a day 20 F hotter does inside a month, raw -> neutral
  AAA      the six-season MLB fit applied UNCHANGED to Triple-A: parks at 3,000 ft or more
           against parks under 1,500 ft, raw -> neutral
A term that closes Coors but NOT Triple-A is a Coors park or tracking effect, not weather.
"""
import os, sys, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from wx_exponent_sweep import OUT, RHO0, YEARS, COORS, ROOT
from wx_wind_hand_month import wind_arrays
from wx_aaa_validate import load_aaa
import wx_vaa as V
sys.path.insert(0, ROOT)
from pipeline import neutral_move as NM

# metric key, label, unit, shape covariate (or None), location control (or None)
METRICS = [('velo', 'release velocity', 'mph', None, None), ('spin', 'spin rate', 'rpm', None, None),
           ('ext', 'extension', 'ft', None, None), ('relz', 'release height', 'ft', None, None),
           ('relx_arm', 'release side', 'ft', None, None), ('arm_angle', 'arm angle', 'deg', None, None),
           ('vaa', 'vertical approach angle', 'deg', 'n_ride', 'pz'),
           ('haa_arm', 'horizontal approach angle', 'deg', 'n_run', 'px_arm')]
# Metrics whose PRESSURE term is dropped (pass `temp` on the command line). The first run
# (2026-11-21, all terms) closed Coors for every metric, but for these six the correction did
# not transfer to Triple-A altitude parks: release velocity reads -0.10 mph at Coors and
# +0.23 mph at Triple-A altitude, extension -0.024 ft against +0.041. An altitude effect that
# changes sign between parks is the park (or its tracking), not the air.
TEMP_ONLY = {'velo', 'spin', 'ext', 'relz', 'relx_arm', 'arm_angle'}
MODE = sys.argv[1] if len(sys.argv) > 1 else 'all'
HOT = -0.037


def month_groups(d):
    mo = np.array([int(s[5:7]) for s in d['date']])
    key = (d['pid'].astype(np.int64) * 16 + d['pt']) * 16 + mo
    g = np.unique(key, return_inverse=True)[1]
    return g, np.bincount(g)[g] >= 30


def add_shape(d):
    g, ng = d['g'], d['g'].max() + 1
    cnt = np.bincount(g, minlength=ng)
    d['n_ride'] = (np.bincount(g, weights=d['ivb'] - d['w_ride'], minlength=ng) / cnt)[g]
    d['n_run'] = (np.bincount(g, weights=d['hb_arm'] - d['w_run'], minlength=ng) / cnt)[g]


def design(d, key, zkey, loc):
    cols, names = [], []
    if loc:
        cols += [d[loc], d['velo']]; names += ['loc', 'velo']
    if MODE == 'temp' and key in TEMP_ONLY:
        cols += [d['lnT']]; names += ['aT']
    else:
        cols += [d['lnP'], d['lnT']]; names += ['aP', 'aT']
    if zkey:
        cols += [d[zkey] * d['lnP'], d[zkey] * d['lnT']]; names += ['bP', 'bT']
    return np.column_stack(cols), names


def fe_sums(y, X, g):
    ng = g.max() + 1
    cnt = np.bincount(g, minlength=ng)
    dm = lambda v: v - (np.bincount(g, weights=v, minlength=ng) / cnt)[g]
    Xd = np.column_stack([dm(X[:, j]) for j in range(X.shape[1])]); yd = dm(y)
    return Xd.T @ Xd, Xd.T @ yd


def neutral(d, key, zkey, coef):
    z = d[zkey] if zkey else 0.0
    return d[key] - (coef.get('aP', 0.0) + coef.get('bP', 0.0) * z) * d['lnP'] - (coef['aT'] + coef.get('bT', 0.0) * z) * d['lnT']


def high_gap(d, v, hi, lo, loc, coef):
    """High-altitude minus low, same (pitcher, pitch type), location and velocity held fixed where modelled."""
    r = v - (coef['loc'] * d[loc] + coef['velo'] * d['velo'] if loc else 0.0)
    g, ng = d['g'], d['g'].max() + 1
    nH = np.bincount(g, weights=hi, minlength=ng); nL = np.bincount(g, weights=lo, minlength=ng)
    ok = (nH >= 25) & (nL >= 25)
    w = np.where(ok, 1 / (1 / np.maximum(nH, 1) + 1 / np.maximum(nL, 1)), 0)
    dd = np.bincount(g, weights=r * hi, minlength=ng) / np.maximum(nH, 1) - np.bincount(g, weights=r * lo, minlength=ng) / np.maximum(nL, 1)
    return float(np.sum(w * dd) / w.sum()), float(np.sqrt(np.sum(w * dd * dd) / w.sum()))


def heat(d, v, gm, okm, loc, coef):
    """Effect of a day 20 F hotter inside (pitcher, pitch type, month)."""
    r = (v - (coef['loc'] * d[loc] + coef['velo'] * d['velo'] if loc else 0.0))[okm]
    g = np.unique(gm[okm], return_inverse=True)[1]
    A, b = fe_sums(r, np.column_stack([d['lnP'][okm], d['lnT'][okm]]), g)
    return float(np.linalg.solve(A, b)[1] * HOT)


def prep_aaa(yr, obsA):
    d = load_aaa(yr, obsA)
    ok = np.isfinite(d['vaa']) & np.isfinite(d['pz']) & np.isfinite(d['velo']) & np.isfinite(d['haa_arm']) & np.isfinite(d['px_arm'])
    d = {k: v[ok] for k, v in d.items()}
    g = np.unique(d['pid'].astype(np.int64) * 16 + d['pt'], return_inverse=True)[1]
    big = np.bincount(g)[g] >= 100
    d = {k: v[big] for k, v in d.items()}
    d['g'] = np.unique(d['pid'].astype(np.int64) * 16 + d['pt'], return_inverse=True)[1]
    tb = np.where(d['closed'], 72.0, 0.5 * d['temp'] + 0.5 * d['obs_t'])
    d['lnT'] = -np.log(((tb - 32) * 5 / 9 + 273.15) / V.T0K); d['lnP'] = np.log(d['rho_w50'] / RHO0) - d['lnT']
    z = np.zeros(len(tb))
    n_run, n_ride, _ = NM.neutral_components(d['hb_arm'], d['ivb'], d['rhp'], d['axis'], d['velo'], d['lnP'], d['lnT'], z, z)
    d['w_ride'] = d['ivb'] - n_ride; d['w_run'] = d['hb_arm'] - n_run
    return d


if __name__ == '__main__':
    obs = json.load(open(os.path.join(OUT, 'game_obs.json'))); W = json.load(open(os.path.join(OUT, 'wind.json')))
    S = {m[0]: {} for m in METRICS}; NAMES = {}
    for yr in YEARS:
        d = V.prep(yr, obs, W); add_shape(d)
        if yr == 2026:
            d['haa_arm'] = -d['haa_arm']      # sheet HAA is signed opposite to the kinematic one
        gm, okm = month_groups(d)
        for key, _, _, zkey, loc in METRICS:
            m = okm & np.isfinite(d[key])
            X, names = design(d, key, zkey, loc); NAMES[key] = names
            S[key][yr] = fe_sums(d[key][m], X[m], np.unique(gm[m], return_inverse=True)[1])
        print(f'{yr}: sums done', flush=True)
        del d
    FULL = {k: dict(zip(NAMES[k], map(float, np.linalg.solve(sum(S[k][y][0] for y in YEARS), sum(S[k][y][1] for y in YEARS))))) for k in S}
    per = {k: {n: [float(np.linalg.solve(*S[k][y])[i]) for y in YEARS] for i, n in enumerate(NAMES[k])} for k in S}
    print('\nSIX-SEASON FIT (per unit ln; season range in brackets)')
    for key, label, unit, zkey, loc in METRICS:
        print(f'  {label:26s} ' + '  '.join(f'{n} {FULL[key][n]:+.4f} [{min(per[key][n]):+.3f}, {max(per[key][n]):+.3f}]' for n in NAMES[key] if n not in ('loc', 'velo')))
    R = {k: dict(coors=[], heat=[]) for k in S}
    for yr in YEARS:
        tr = [y for y in YEARS if y != yr]
        d = V.prep(yr, obs, W); add_shape(d)
        if yr == 2026:
            d['haa_arm'] = -d['haa_arm']      # sheet HAA is signed opposite to the kinematic one
        gm, okm = month_groups(d)
        at = d['venue'] == COORS
        for key, _, _, zkey, loc in METRICS:
            c = dict(zip(NAMES[key], np.linalg.solve(sum(S[key][y][0] for y in tr), sum(S[key][y][1] for y in tr))))
            fin = np.isfinite(d[key])
            dd = {k: v[fin] for k, v in d.items()}; dd['g'] = np.unique(dd['g'], return_inverse=True)[1]
            nv = neutral(dd, key, zkey, c)
            R[key]['coors'].append((high_gap(dd, dd[key], at[fin], ~at[fin], loc, c)[0], high_gap(dd, nv, at[fin], ~at[fin], loc, c)[0]))
            R[key]['heat'].append((heat(dd, dd[key], gm[fin], okm[fin], loc, c), heat(dd, nv, gm[fin], okm[fin], loc, c)))
        del d
    obsA = json.load(open(os.path.join(OUT, 'game_obs_aaa.json')))
    for k in R:
        R[k]['aaa'] = []
    for yr in (2023, 2024, 2025):
        d = prep_aaa(yr, obsA); add_shape(d)
        hi = d['elev'] >= 3000; lo = d['elev'] < 1500
        for key, _, _, zkey, loc in METRICS:
            c = FULL[key]
            fin = np.isfinite(d[key])
            if fin.sum() < 50000:
                continue
            dd = {k: v[fin] for k, v in d.items()}; dd['g'] = np.unique(dd['g'], return_inverse=True)[1]
            R[key]['aaa'].append((high_gap(dd, dd[key], hi[fin], lo[fin], loc, c)[0], high_gap(dd, neutral(dd, key, zkey, c), hi[fin], lo[fin], loc, c)[0]))
        del d
    print('\nTESTS (raw -> neutral; coefficients never saw the test data)')
    print(f"  {'metric':26s} {'unit':4s} | {'Coors gap, 6 held-out seasons':>32s} | {'20 F hotter, in-month':>24s} | {'Triple-A altitude gap':>24s}")
    mean = lambda v, i: float(np.mean([x[i] for x in v])) if v else float('nan')
    for key, label, unit, zkey, loc in METRICS:
        r = R[key]
        print(f"  {label:26s} {unit:4s} | {mean(r['coors'], 0):+12.3f} -> {mean(r['coors'], 1):+8.3f}      | {mean(r['heat'], 0):+9.3f} -> {mean(r['heat'], 1):+8.3f} | {mean(r['aaa'], 0):+9.3f} -> {mean(r['aaa'], 1):+8.3f}")
    json.dump(dict(fit=FULL, per_season=per, tests=R, mode=MODE), open(os.path.join(OUT, f'all_metrics_{MODE}.json'), 'w'), indent=1)
