"""wx_flight_models.py -- the air and a batted ball: carry distance and result value.

RESEARCH ONLY. Two models for a ball in play, both with the pitch-side form:

  DISTANCE  neutral distance = distance / exp(eP[band] * lnP + eT[band] * lnT)
  VALUE     neutral wOBA value = value - (aP[band] * lnP + aT[band] * lnT)

lnP / lnT are the pressure-and-humidity and temperature parts of ln(air density / reference),
from pipeline/neutral_move.game_air. `band` is a coarse cell of launch angle (and exit
velocity); the band layout is the thing swept here. The fit is within FINE contact cells
(2 mph x 2 deg, by season), so a ball is compared only with balls hit the same way: what is
left is the air. Value is the fixed-weight wOBA value of the event (1B .88, 2B 1.25, 3B 1.59,
HR 2.05, anything else 0).

Tests, each with coefficients the test data never saw:
  COORS  held-out season: Coors minus elsewhere at equal contact, raw -> neutral
  HEAT   held-out season: what a day 20 F hotter does at equal contact, raw -> neutral
  AAA    the full MLB fit applied UNCHANGED to Triple-A: parks at 3,000 ft or more against
         parks under 1,500 ft, raw -> neutral
The band layout is chosen on the held-out error of the DISTANCE model (a continuous target);
the value model is too noisy per ball to choose a layout by error, so it is read on the three
gap tests.

Usage: .venv/bin/python scripts/research/weather/wx_flight_models.py
"""
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
from pipeline import neutral_move as NM  # noqa: E402
from wx_aaa_validate import moist  # noqa: E402

OUT = os.path.join(ROOT, 'data', '_weather_audit')
YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
COORS, HOT = 19, -0.037
RHO0, T0K = 1.195, 295.6
WOBA_W = {'single': 0.88, 'double': 1.25, 'triple': 1.59, 'home_run': 2.05,
          'Single': 0.88, 'Double': 1.25, 'Triple': 1.59, 'Home Run': 2.05}


def f64(s):
    return pd.to_numeric(s, errors='coerce').to_numpy(dtype='float64', na_value=np.nan)


def finish(d):
    ok = np.isfinite(d['ev']) & np.isfinite(d['la']) & np.isfinite(d['lnP']) & np.isfinite(d['lnT'])
    d = {k: v[ok] for k, v in d.items()}
    d['cell'] = np.floor(d['ev'] / 2).astype(np.int64) * 200 + np.floor((d['la'] + 90) / 2).astype(np.int64)
    return d


def load_mlb(yr):
    if yr == 2026:
        P = [p for p in pickle.load(open(os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl'), 'rb'))
             if p.get('_source') == 'MLB' and p.get('BBType')]
        store = json.load(open(os.path.join(ROOT, 'data', 'game_weather_rs.json')))
        pk = np.array([int((p.get('PitchID') or '0_').split('_')[0] or 0) for p in P])
        num = lambda k: np.array([float(p[k]) if p.get(k) not in (None, '') else np.nan for p in P])
        ev, la, dist, xw = num('ExitVelo'), num('LaunchAngle'), num('Distance'), num('xwOBA')
        w = np.array([WOBA_W.get(p.get('Event'), 0.0) for p in P])
    else:
        df = pickle.load(open(os.path.join(ROOT, 'data', f'_statcast{yr}_cache.pkl'), 'rb'))
        df = df[df['bb_type'].notna().to_numpy()]
        store = json.load(open(os.path.join(ROOT, 'data', 'game_weather_2025.json')))
        pk = f64(df['game_pk']).astype(np.int64)
        ev, la, dist, xw = f64(df['launch_speed']), f64(df['launch_angle']), f64(df['hit_distance_sc']), f64(df['estimated_woba_using_speedangle'])
        w = np.array([WOBA_W.get(e, 0.0) for e in df['events'].astype(object)])
        del df
    air, ven = {}, {}
    for k in np.unique(pk):
        i = store.get(str(int(k))) or {}
        air[int(k)] = NM.game_air(i.get('elevationFt'), i.get('tempF'), i.get('condition'), i.get('venueId'), i.get('obs'), i.get('wind'))
        ven[int(k)] = i.get('venueId') or -1
    return finish(dict(pk=pk, ev=ev, la=la, dist=dist, xw=xw, w=w,
                       lnP=np.array([air[k]['lnP'] if air[k] else np.nan for k in pk]),
                       lnT=np.array([air[k]['lnT'] if air[k] else np.nan for k in pk]),
                       hi=np.array([ven[k] == COORS for k in pk]), lo=np.array([ven[k] != COORS for k in pk]),
                       ven=np.array([ven[k] for k in pk], dtype=np.int64)))


def load_aaa(yr):
    """Triple-A balls in play, with the game air rebuilt from the frame's per-game fields."""
    z = np.load(os.path.join(OUT, f'frame_aaa_{yr}.npz'))
    obs = json.load(open(os.path.join(OUT, 'game_obs_aaa.json')))
    g = {}
    for pk, el, t, cl, vn in zip(z['pk'], z['elev'], z['temp'], z['closed'], z['venue']):
        g.setdefault(int(pk), (float(el), float(t), bool(cl), int(vn)))
    df = pickle.load(open(os.path.join(ROOT, 'data', f'_aaa_statcast{yr}_cache.pkl'), 'rb'))
    df = df[df['bb_type'].notna().to_numpy()]
    pk = f64(df['game_pk']).astype(np.int64)
    lnP, lnT, el = {}, {}, {}
    for k in np.unique(pk):
        o, gi = obs.get(str(int(k))), g.get(int(k))
        if not o or not gi or not np.isfinite(gi[0]):
            continue
        tb = 72.0 if gi[2] else 0.5 * gi[1] + 0.5 * o['tempF']
        if not np.isfinite(tb):
            continue
        rho = float(moist(np.array([o['p_hpa']]), np.array([tb]), np.array([50.0 if gi[2] else o['rh']]))[0])
        lnT[int(k)] = -np.log(((tb - 32) * 5 / 9 + 273.15) / T0K); lnP[int(k)] = np.log(rho / RHO0) - lnT[int(k)]; el[int(k)] = gi[0]
    elev = np.array([el.get(int(k), np.nan) for k in pk])
    return finish(dict(pk=pk, ev=f64(df['launch_speed']), la=f64(df['launch_angle']), dist=f64(df['hit_distance_sc']),
                       xw=f64(df['estimated_woba_using_speedangle']), w=np.array([WOBA_W.get(e, 0.0) for e in df['events'].astype(object)]),
                       lnP=np.array([lnP.get(int(k), np.nan) for k in pk]), lnT=np.array([lnT.get(int(k), np.nan) for k in pk]),
                       hi=elev >= 3000, lo=elev < 1500,
                       ven=np.array([g[int(k)][3] if int(k) in g else -1 for k in pk], dtype=np.int64)))


# ── band layouts: integer id per ball, -1 = no adjustment ────────────────────────────
def _la_bands(la, edges):
    b = np.digitize(la, edges) - 1
    return np.where((la < edges[0]) | (la >= edges[-1]), -1, b)


LAYOUTS = {
    'one  LA 10+':            lambda d: np.where(d['la'] >= 10, 0, -1),
    'la4  10/20/30/40/90':    lambda d: _la_bands(d['la'], [10, 20, 30, 40, 91]),
    'la8  5-deg, 10..50, 90': lambda d: _la_bands(d['la'], [10, 15, 20, 25, 30, 35, 40, 50, 91]),
    'la4 x ev2 (95)':         lambda d: np.where(_la_bands(d['la'], [10, 20, 30, 40, 91]) < 0, -1,
                                                 _la_bands(d['la'], [10, 20, 30, 40, 91]) * 2 + (d['ev'] >= 95)),
    'la5 from 0 (control)':   lambda d: _la_bands(d['la'], [0, 10, 20, 30, 40, 91]),
}


def nb_of(name):
    return {'one  LA 10+': 1, 'la4  10/20/30/40/90': 4, 'la8  5-deg, 10..50, 90': 8, 'la4 x ev2 (95)': 8, 'la5 from 0 (control)': 5}[name]


def design(d, band, nb):
    X = np.zeros((len(band), 2 * nb))
    for b in range(nb):
        m = band == b
        X[m, b] = d['lnP'][m]; X[m, nb + b] = d['lnT'][m]
    return X


def demean(v, g):
    return v - (np.bincount(g, weights=v) / np.bincount(g))[g]


def sums(y, X, g):
    Xd = np.column_stack([demean(X[:, j], g) for j in range(X.shape[1])]); yd = demean(y, g)
    return Xd.T @ Xd, Xd.T @ yd


def solve(A, b):
    return np.linalg.lstsq(A, b, rcond=None)[0]


def gap(d, v, m):
    """High minus low at equal contact (fine cell), 5 or more balls on each side."""
    g = np.unique(d['cell'][m], return_inverse=True)[1]; ng = g.max() + 1
    hi, lo, x = d['hi'][m].astype(float), d['lo'][m].astype(float), v[m]
    nH, nL = np.bincount(g, weights=hi, minlength=ng), np.bincount(g, weights=lo, minlength=ng)
    ok = (nH >= 5) & (nL >= 5)
    if not ok.any():
        return float('nan')
    wt = np.where(ok, 1 / (1 / np.maximum(nH, 1) + 1 / np.maximum(nL, 1)), 0)
    dd = np.bincount(g, weights=x * hi, minlength=ng) / np.maximum(nH, 1) - np.bincount(g, weights=x * lo, minlength=ng) / np.maximum(nL, 1)
    return float(np.sum(wt * dd) / wt.sum())


def heat(d, v, m):
    g = np.unique(d['cell'][m], return_inverse=True)[1]
    keep = np.bincount(g)[g] >= 10
    idx = np.where(m)[0][keep]; g = np.unique(d['cell'][idx], return_inverse=True)[1]
    A, b = sums(v[idx], np.column_stack([d['lnP'][idx], d['lnT'][idx]]), g)
    return float(solve(A, b)[1] * HOT)


if __name__ == '__main__':
    D = {y: load_mlb(y) for y in YEARS}
    A3 = {y: load_aaa(y) for y in (2023, 2024, 2025)}
    print('balls in play: ' + ', '.join(f'{y} {len(d["ev"])}' for y, d in D.items()) + ' | AAA ' + ', '.join(f'{y} {len(d["ev"])} ({int(d["hi"].sum())} high)' for y, d in A3.items()))
    res = {}
    for target in ('dist', 'value'):
        print(f'\n================ {"DISTANCE (ft)" if target == "dist" else "VALUE (wOBA points on contact)"} ================')
        ysel = (lambda d: np.log(np.where(d['dist'] > 30, d['dist'], np.nan))) if target == 'dist' else (lambda d: d['w'])
        raw_of = (lambda d: d['dist']) if target == 'dist' else (lambda d: d['w'])
        for name, fn in LAYOUTS.items():
            nb = nb_of(name)
            S, M = {}, {}
            for y, d in D.items():
                band = fn(d); yy = ysel(d)
                m = np.isfinite(yy) & (np.bincount(np.unique(d['cell'], return_inverse=True)[1])[np.unique(d['cell'], return_inverse=True)[1]] >= 10)
                g = np.unique(d['cell'][m], return_inverse=True)[1]
                S[y] = sums(yy[m], design(d, band, nb)[m], g); M[y] = (m, band, yy)
            full = solve(sum(S[y][0] for y in YEARS), sum(S[y][1] for y in YEARS))
            per = np.array([solve(*S[y]) for y in YEARS])
            mse0 = mse1 = 0.0; n = 0; co, he = [], []
            for y, d in D.items():
                b = solve(sum(S[t][0] for t in YEARS if t != y), sum(S[t][1] for t in YEARS if t != y))
                m, band, yy = M[y]
                shift = design(d, band, nb) @ b
                g = np.unique(d['cell'][m], return_inverse=True)[1]
                mse0 += float(np.sum(demean(yy[m], g) ** 2)); mse1 += float(np.sum(demean((yy - shift)[m], g) ** 2)); n += int(m.sum())
                neu = d['dist'] / np.exp(shift) if target == 'dist' else d['w'] - shift
                raw = raw_of(d); air_m = m & (d['la'] >= 10)
                co.append((gap(d, raw, air_m), gap(d, neu, air_m))); he.append((heat(d, raw, air_m), heat(d, neu, air_m)))
            aa = []
            for y, d in A3.items():
                band = fn(d); shift = design(d, band, nb) @ full
                yy = ysel(d); m = np.isfinite(yy) & (d['hi'] | d['lo']) & (d['la'] >= 10)
                neu = d['dist'] / np.exp(shift) if target == 'dist' else d['w'] - shift
                aa.append((gap(d, raw_of(d), m), gap(d, neu, m)))
            mean = lambda v, i: float(np.nanmean([x[i] for x in v]))
            wins = sum(1 for c in co if abs(c[1]) < abs(c[0]))
            print(f'\n{name}   held-out error {100 * (mse1 / mse0 - 1):+.3f}% vs raw')
            print(f'   Coors {mean(co, 0):+.4f} -> {mean(co, 1):+.4f} ({wins}/{len(co)} seasons closer to 0) | 20 F hotter {mean(he, 0):+.4f} -> {mean(he, 1):+.4f} | '
                  f'Triple-A altitude {mean(aa, 0):+.4f} -> {mean(aa, 1):+.4f}')
            lab = 'eP' if target == 'dist' else 'aP'
            print('   ' + lab + ' by band: ' + ' '.join(f'{full[b]:+.3f}[{per[:, b].min():+.2f},{per[:, b].max():+.2f}]' for b in range(nb)))
            print('   ' + lab.replace('P', 'T') + ' by band: ' + ' '.join(f'{full[nb + b]:+.3f}[{per[:, nb + b].min():+.2f},{per[:, nb + b].max():+.2f}]' for b in range(nb)))
            res[f'{target}|{name}'] = dict(fit=[float(x) for x in full], per_season=per.tolist(), held_out_pct=100 * (mse1 / mse0 - 1),
                                           coors=co, heat=he, aaa=aa, nb=nb)
    tmp = os.path.join(OUT, 'flight_models.json.tmp')
    json.dump(res, open(tmp, 'w'), indent=1)
    os.replace(tmp, os.path.join(OUT, 'flight_models.json'))
