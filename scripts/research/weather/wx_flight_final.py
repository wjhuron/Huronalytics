"""wx_flight_final.py -- the ball-value model: band layout, then the pressure share kappa.

RESEARCH ONLY. neutral value = value - s[band] * (zT + kappa * zP), where zP / zT are the
carry model's predicted log carry from pressure and temperature (quadratic form) and s is
the wOBA value of a unit of log carry for that contact band, measured on TEMPERATURE.

Two constants, two searches, two different objectives (one cannot serve both):
  LAYOUT  held-out-season error of the ball value at equal contact after removing s * zT
          only. Temperature varies in every park, so this objective has no park in it.
  KAPPA   Triple-A, the MLB fit unchanged: the altitude gap and the ball-value error at equal
          contact. Triple-A is the only place where pressure varies across parks that were
          not built around it (in MLB, pressure is Coors). Physics says 1.
Writes data/_weather_audit/flight_final.json for scripts/builders/build_neutral_movement.py.

Usage: .venv/bin/python scripts/research/weather/wx_flight_final.py
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wx_flight_models as F  # noqa: E402
import wx_flight_models2 as F2  # noqa: E402

YEARS, OUT = F.YEARS, F.OUT


def grid_band(la_edges, ev_edges):
    def fn(d):
        a = F._la_bands(d['la'], la_edges)
        e = np.digitize(d['ev'], ev_edges)
        return np.where(a < 0, -1, a * (len(ev_edges) + 1) + e)
    return fn, (len(la_edges) - 1) * (len(ev_edges) + 1)


LAYOUTS = {
    'la4':                       ([10, 20, 30, 40, 91], []),
    'la4 x ev2 (95)':            ([10, 20, 30, 40, 91], [95]),
    'la4 x ev3 (90,100)':        ([10, 20, 30, 40, 91], [90, 100]),
    'la4 x ev4 (90,95,100)':     ([10, 20, 30, 40, 91], [90, 95, 100]),
    'la4 x ev5 (90,95,100,105)': ([10, 20, 30, 40, 91], [90, 95, 100, 105]),
    'la6 x ev4 (90,95,100)':     ([10, 15, 20, 25, 30, 40, 91], [90, 95, 100]),
    'la7 x ev4 (90,95,100)':     ([10, 15, 20, 25, 30, 35, 40, 91], [90, 95, 100]),
    'la7 x ev5 (90,95,100,105)': ([10, 15, 20, 25, 30, 35, 40, 91], [90, 95, 100, 105]),
    # grid extension (2026-11-22): the first grid still improved at its finest layout
    'la8 x ev6 (85..105 by 5, 110)':   ([10, 15, 20, 25, 30, 35, 40, 50, 91], [85, 90, 95, 100, 105, 110]),
    'la8 x ev9 (87.5..107.5 by 2.5)':  ([10, 15, 20, 25, 30, 35, 40, 50, 91], [87.5, 90, 92.5, 95, 97.5, 100, 102.5, 105, 107.5]),
    'la15 x ev6 (2.5 deg to 45)':      ([10, 12.5, 15, 17.5, 20, 22.5, 25, 27.5, 30, 32.5, 35, 37.5, 40, 45, 50, 91], [85, 90, 95, 100, 105, 110]),
    'la15 x ev9':                      ([10, 12.5, 15, 17.5, 20, 22.5, 25, 27.5, 30, 32.5, 35, 37.5, 40, 45, 50, 91], [87.5, 90, 92.5, 95, 97.5, 100, 102.5, 105, 107.5]),
    'la20 x ev13 (2 deg, 1.5 mph)':    ([10 + 2 * i for i in range(20)] + [91], [86 + 2 * i for i in range(13)]),
}

if __name__ == '__main__':
    dres = json.load(open(os.path.join(OUT, 'flight_models2.json')))['dist|quadratic']
    dfit = np.array(dres['fit'])
    D = {y: F.load_mlb(y) for y in YEARS}
    A3 = {y: F.load_aaa(y) for y in (2023, 2024, 2025)}
    for d in list(D.values()) + list(A3.values()):
        X = F2.dist_design(d, 'quadratic'); k = X.shape[1] // 2
        d['zP'] = X[:, :k] @ dfit[:k]; d['zT'] = X[:, k:] @ dfit[k:]
        g = np.unique(d['cell'], return_inverse=True)[1]
        d['m'] = np.bincount(g)[g] >= 10
        d['g'] = np.unique(np.where(d['m'], d['cell'], -1), return_inverse=True)[1]

    def des(d, fn, nb):
        band = fn(d); X = np.zeros((len(band), 2 * nb))
        for b in range(nb):
            mm = band == b
            X[mm, b] = d['zT'][mm]; X[mm, nb + b] = d['zP'][mm]
        return X

    print('LAYOUT: held-out error of the ball value at equal contact, temperature part removed')
    fits = {}
    for name, (la_e, ev_e) in LAYOUTS.items():
        fn, nb = grid_band(la_e, ev_e)
        S = {y: F.sums(d['w'][d['m']], des(d, fn, nb)[d['m']], np.unique(d['g'][d['m']], return_inverse=True)[1]) for y, d in D.items()}
        m0 = m1 = 0.0; per_y = []
        for y, d in D.items():
            b = F.solve(sum(S[t][0] for t in YEARS if t != y), sum(S[t][1] for t in YEARS if t != y))
            band = fn(d); s = np.where(band >= 0, b[np.maximum(band, 0)], 0.0)
            mm = d['m']; g = np.unique(d['g'][mm], return_inverse=True)[1]
            e0 = float(np.sum(F.demean(d['w'][mm], g) ** 2)); e1 = float(np.sum(F.demean((d['w'] - s * d['zT'])[mm], g) ** 2))
            m0 += e0; m1 += e1; per_y.append(100 * (e1 / e0 - 1))
        full = F.solve(sum(S[y][0] for y in YEARS), sum(S[y][1] for y in YEARS))
        per = np.array([F.solve(*S[y]) for y in YEARS])
        fits[name] = dict(la=la_e, ev=ev_e, nb=nb, s=[float(x) for x in full[:nb]], s_lo=per[:, :nb].min(0).tolist(), s_hi=per[:, :nb].max(0).tolist(),
                          held_out_pct=100 * (m1 / m0 - 1))
        print(f'  {name:28s} {nb:3d} bands  {100 * (m1 / m0 - 1):+.4f}%   by held-out season ' + ' '.join(f'{x:+.3f}' for x in per_y)
              + f'   better than raw in {sum(x < 0 for x in per_y)}/6')
    pick = min(fits, key=lambda n: fits[n]['held_out_pct'])
    print(f'\nlowest held-out error: {pick}')

    print('\nKAPPA on Triple-A (MLB fit unchanged). gap = altitude parks minus low parks at equal contact; error = ball value at equal contact vs kappa 0')
    out = {}
    for name in dict.fromkeys(['la4 x ev4 (90,95,100)', pick]):
        fn, nb = grid_band(fits[name]['la'], fits[name]['ev']); sfull = np.array(fits[name]['s'])
        rows = []
        for kappa in np.round(np.arange(0.0, 1.5001, 0.1), 2):
            gaps, e = [], []
            for y, d in A3.items():
                band = fn(d); s = np.where(band >= 0, sfull[np.maximum(band, 0)], 0.0)
                neu = d['w'] - s * (d['zT'] + kappa * d['zP']); neu0 = d['w'] - s * d['zT']
                mm = (d['hi'] | d['lo']) & (d['la'] >= 10)
                gaps.append(F.gap(d, neu, mm))
                m2 = d['m']; g = np.unique(d['g'][m2], return_inverse=True)[1]
                e.append(100 * (float(np.sum(F.demean(neu[m2], g) ** 2)) / float(np.sum(F.demean(neu0[m2], g) ** 2)) - 1))
            rows.append((float(kappa), gaps, e))
        print(f'\n  layout {name}')
        for kappa, gaps, e in rows:
            print(f'    kappa {kappa:4.2f}  gap {np.mean(gaps):+.4f} (' + ' '.join(f'{x:+.3f}' for x in gaps) + f')   error {np.mean(e):+.4f}% (' + ' '.join(f'{x:+.3f}' for x in e) + ')')
        out[name] = rows
    tmp = os.path.join(OUT, 'flight_final.json.tmp')
    json.dump(dict(distance=dict(form='quadratic', fit=dres['fit'], la_min=10, u_centre=25.0, u_scale=10.0), layouts=fits, pick=pick, kappa=out), open(tmp, 'w'), indent=1)
    os.replace(tmp, os.path.join(OUT, 'flight_final.json'))
