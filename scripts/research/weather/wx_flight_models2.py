"""wx_flight_models2.py -- smooth carry model, and a ball-value model built ON the carry.

RESEARCH ONLY. wx_flight_models.py showed two things:
  1. the carry exponents rise steadily with launch angle, so bands are a staircase over a slope;
  2. the direct value model under-corrects at Triple-A altitude (.078 -> .030) and its
     pressure coefficient is far smaller, against temperature, than the carry model's. Pressure
     variation is mostly Coors, and Coors has deep fences built for its air: the PARK hides part
     of the air effect on results.

So here:
  DISTANCE  exponent as a smooth function of launch angle (u = (LA - 25) / 10, LA 10 or more):
            linear and quadratic in u, against the la4 / la8 bands, on held-out error.
  VALUE     structural: z = the carry model's predicted log carry for the ball
            (eP(LA) * lnP + eT(LA) * lnT). neutral value = value - s[band] * z, with ONE
            sensitivity s per contact band (value per unit of log carry), fitted WITHIN
            (contact cell, park): inside one park the fences are fixed, so s is the air.
            The same s then prices pressure and temperature. What is left at Coors after this
            is the park's dimensions, which is a park factor and not weather.

Tests as before (held-out seasons for Coors and heat; the full MLB fit unchanged on Triple-A).
The distance model inside the value test is the full-sample fit (a second-stage input; its own
held-out test is above).

Usage: .venv/bin/python scripts/research/weather/wx_flight_models2.py
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wx_flight_models as F  # noqa: E402

YEARS, OUT = F.YEARS, F.OUT


def u_of(d):
    return (d['la'] - 25.0) / 10.0


def dist_design(d, form):
    air = (d['la'] >= 10).astype(float); u = u_of(d)
    cols = {'const': [air], 'linear': [air, air * u], 'quadratic': [air, air * u, air * u * u],
            'linear + EV': [air, air * u, air * (d['ev'] - 90) / 10], 'quadratic + EV': [air, air * u, air * u * u, air * (d['ev'] - 90) / 10]}[form]
    return np.column_stack([c * d['lnP'] for c in cols] + [c * d['lnT'] for c in cols])


def cell_mask(d, y):
    g = np.unique(d['cell'], return_inverse=True)[1]
    return np.isfinite(y) & (np.bincount(g)[g] >= 10)


VALUE_BANDS = {
    'one (LA 10+)':        lambda d: np.where(d['la'] >= 10, 0, -1),
    'la4':                 lambda d: F._la_bands(d['la'], [10, 20, 30, 40, 91]),
    'la4 x ev2 (95)':      lambda d: np.where(F._la_bands(d['la'], [10, 20, 30, 40, 91]) < 0, -1, F._la_bands(d['la'], [10, 20, 30, 40, 91]) * 2 + (d['ev'] >= 95)),
    'la4 x ev3 (90, 100)': lambda d: np.where(F._la_bands(d['la'], [10, 20, 30, 40, 91]) < 0, -1,
                                              F._la_bands(d['la'], [10, 20, 30, 40, 91]) * 3 + (d['ev'] >= 90).astype(int) + (d['ev'] >= 100).astype(int)),
}
VNB = {'one (LA 10+)': 1, 'la4': 4, 'la4 x ev2 (95)': 8, 'la4 x ev3 (90, 100)': 12}


if __name__ == '__main__':
    D = {y: F.load_mlb(y) for y in YEARS}
    A3 = {y: F.load_aaa(y) for y in (2023, 2024, 2025)}
    mean = lambda v, i: float(np.nanmean([x[i] for x in v]))
    res = {}
    print('================ DISTANCE: smooth exponent in launch angle ================')
    best = None
    for form in ('const', 'linear', 'quadratic', 'linear + EV', 'quadratic + EV'):
        S, M = {}, {}
        for y, d in D.items():
            yy = np.log(np.where(d['dist'] > 30, d['dist'], np.nan)); m = cell_mask(d, yy)
            g = np.unique(d['cell'][m], return_inverse=True)[1]
            S[y] = F.sums(yy[m], dist_design(d, form)[m], g); M[y] = (m, yy)
        full = F.solve(sum(S[y][0] for y in YEARS), sum(S[y][1] for y in YEARS))
        per = np.array([F.solve(*S[y]) for y in YEARS])
        m0 = m1 = 0.0; co, he = [], []
        for y, d in D.items():
            b = F.solve(sum(S[t][0] for t in YEARS if t != y), sum(S[t][1] for t in YEARS if t != y))
            m, yy = M[y]; shift = dist_design(d, form) @ b
            g = np.unique(d['cell'][m], return_inverse=True)[1]
            m0 += float(np.sum(F.demean(yy[m], g) ** 2)); m1 += float(np.sum(F.demean((yy - shift)[m], g) ** 2))
            neu = d['dist'] / np.exp(shift); am = m & (d['la'] >= 10)
            co.append((F.gap(d, d['dist'], am), F.gap(d, neu, am))); he.append((F.heat(d, d['dist'], am), F.heat(d, neu, am)))
        aa = []
        for y, d in A3.items():
            neu = d['dist'] / np.exp(dist_design(d, form) @ full); m = np.isfinite(d['dist']) & (d['dist'] > 30) & (d['hi'] | d['lo']) & (d['la'] >= 10)
            aa.append((F.gap(d, d['dist'], m), F.gap(d, neu, m)))
        k = len(full) // 2
        print(f'\n{form:15s} held-out error {100 * (m1 / m0 - 1):+.3f}% | Coors {mean(co, 0):+.2f} -> {mean(co, 1):+.2f} ft | 20 F hotter {mean(he, 0):+.2f} -> {mean(he, 1):+.2f} ft | '
              f'Triple-A altitude {mean(aa, 0):+.2f} -> {mean(aa, 1):+.2f} ft')
        print('   eP terms: ' + ' '.join(f'{full[i]:+.4f}[{per[:, i].min():+.3f},{per[:, i].max():+.3f}]' for i in range(k)))
        print('   eT terms: ' + ' '.join(f'{full[k + i]:+.4f}[{per[:, k + i].min():+.3f},{per[:, k + i].max():+.3f}]' for i in range(k)))
        res[f'dist|{form}'] = dict(fit=[float(x) for x in full], per_season=per.tolist(), held_out_pct=100 * (m1 / m0 - 1), coors=co, heat=he, aaa=aa)
    DIST_FORM = 'quadratic'
    dfit = np.array(res[f'dist|{DIST_FORM}']['fit'])
    for d in list(D.values()) + list(A3.values()):
        d['z'] = dist_design(d, DIST_FORM) @ dfit                      # predicted log carry from the air
        d['cv'] = d['cell'] * 10000 + (d['ven'] % 10000)               # contact cell within park

    print(f'\n================ VALUE on the carry (distance form: {DIST_FORM}) ================')
    for fe in ('cell x park', 'cell'):
        for name, fn in VALUE_BANDS.items():
            nb = VNB[name]
            def zdes(d):
                band = fn(d); X = np.zeros((len(band), nb))
                for b in range(nb):
                    X[band == b, b] = d['z'][band == b]
                return X
            S = {}
            for y, d in D.items():
                key = d['cv'] if fe == 'cell x park' else d['cell']
                g = np.unique(key, return_inverse=True)[1]; m = np.bincount(g)[g] >= 5
                S[y] = F.sums(d['w'][m], zdes(d)[m], np.unique(key[m], return_inverse=True)[1])
            full = F.solve(sum(S[y][0] for y in YEARS), sum(S[y][1] for y in YEARS))
            per = np.array([F.solve(*S[y]) for y in YEARS])
            co, he = [], []
            for y, d in D.items():
                b = F.solve(sum(S[t][0] for t in YEARS if t != y), sum(S[t][1] for t in YEARS if t != y))
                neu = d['w'] - zdes(d) @ b; am = d['la'] >= 10
                co.append((F.gap(d, d['w'], am), F.gap(d, neu, am))); he.append((F.heat(d, d['w'], am), F.heat(d, neu, am)))
            aa = []
            for y, d in A3.items():
                neu = d['w'] - zdes(d) @ full; m = (d['hi'] | d['lo']) & (d['la'] >= 10)
                aa.append((F.gap(d, d['w'], m), F.gap(d, neu, m)))
            print(f'\nFE {fe:11s} bands {name:20s} Coors {mean(co, 0):+.4f} -> {mean(co, 1):+.4f} | 20 F hotter {mean(he, 0):+.4f} -> {mean(he, 1):+.4f} | '
                  f'Triple-A altitude {mean(aa, 0):+.4f} -> {mean(aa, 1):+.4f}')
            print('   s by band (value per unit log carry): ' + ' '.join(f'{full[b]:+.2f}[{per[:, b].min():+.1f},{per[:, b].max():+.1f}]' for b in range(nb)))
            res[f'value|{fe}|{name}'] = dict(fit=[float(x) for x in full], per_season=per.tolist(), coors=co, heat=he, aaa=aa)
    tmp = os.path.join(OUT, 'flight_models2.json.tmp')
    json.dump(res, open(tmp, 'w'), indent=1)
    os.replace(tmp, os.path.join(OUT, 'flight_models2.json'))
