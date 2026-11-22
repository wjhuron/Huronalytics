"""wx_flight_models3.py -- ball value: is the pressure effect muted by Coors's fences?

RESEARCH ONLY. zP / zT = the carry model's predicted log carry from pressure and from
temperature (quadratic form, wx_flight_models2.py). Fit, within contact cells:
    value ~ s[band] * zT + p[band] * zP
s is the value of a unit of log carry measured on TEMPERATURE (every park has hot and cold
days, so fences cancel). p is the same thing measured on PRESSURE, which in MLB is mostly
Coors against the rest. Physics says p = s. Three models are then tested:
    DIRECT    shift = s * zT + p * zP      (what MLB data says, park and air together)
    PHYSICS   shift = s * (zT + zP)        (carry is carry; kappa = 1)
    KAPPA k   shift = s * (zT + k * zP)    for k on a grid, to see where Triple-A closes
Triple-A altitude parks are several parks with ordinary fences: if PHYSICS closes the
Triple-A gap and DIRECT does not, the missing pressure effect in MLB is Coors's dimensions.

Usage: .venv/bin/python scripts/research/weather/wx_flight_models3.py
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
BANDS = {'la4': (lambda d: F._la_bands(d['la'], [10, 20, 30, 40, 91]), 4),
         'la4 x ev2 (95)': (F2.VALUE_BANDS['la4 x ev2 (95)'], 8),
         'la4 x ev3 (90, 100)': (F2.VALUE_BANDS['la4 x ev3 (90, 100)'], 12)}

if __name__ == '__main__':
    dfit = np.array(json.load(open(os.path.join(OUT, 'flight_models2.json')))['dist|quadratic']['fit'])
    D = {y: F.load_mlb(y) for y in YEARS}
    A3 = {y: F.load_aaa(y) for y in (2023, 2024, 2025)}
    for d in list(D.values()) + list(A3.values()):
        X = F2.dist_design(d, 'quadratic'); k = X.shape[1] // 2
        d['zP'] = X[:, :k] @ dfit[:k]; d['zT'] = X[:, k:] @ dfit[k:]
    mean = lambda v, i: float(np.nanmean([x[i] for x in v]))
    res = {}
    for name, (fn, nb) in BANDS.items():
        def des(d):
            band = fn(d); X = np.zeros((len(band), 2 * nb))
            for b in range(nb):
                m = band == b
                X[m, b] = d['zT'][m]; X[m, nb + b] = d['zP'][m]
            return X
        S = {}
        for y, d in D.items():
            g = np.unique(d['cell'], return_inverse=True)[1]; m = np.bincount(g)[g] >= 10
            S[y] = F.sums(d['w'][m], des(d)[m], np.unique(d['cell'][m], return_inverse=True)[1])
        full = F.solve(sum(S[y][0] for y in YEARS), sum(S[y][1] for y in YEARS))
        per = np.array([F.solve(*S[y]) for y in YEARS])
        print(f'\n===== bands {name} =====')
        print('  s (temperature): ' + ' '.join(f'{full[b]:+.2f}[{per[:, b].min():+.1f},{per[:, b].max():+.1f}]' for b in range(nb)))
        print('  p (pressure):    ' + ' '.join(f'{full[nb + b]:+.2f}[{per[:, nb + b].min():+.1f},{per[:, nb + b].max():+.1f}]' for b in range(nb)))
        def shift(d, b, kappa):
            band = fn(d); s = np.where(band >= 0, b[np.maximum(band, 0)], 0.0)
            if kappa is None:
                p = np.where(band >= 0, b[nb + np.maximum(band, 0)], 0.0)
                return s * d['zT'] + p * d['zP']
            return s * (d['zT'] + kappa * d['zP'])
        for label, kappa in [('DIRECT', None), ('PHYSICS k=1', 1.0)] + [(f'KAPPA {k:.2f}', k) for k in (0.25, 0.5, 0.75, 1.25)]:
            co, he = [], []
            for y, d in D.items():
                b = F.solve(sum(S[t][0] for t in YEARS if t != y), sum(S[t][1] for t in YEARS if t != y))
                neu = d['w'] - shift(d, b, kappa); am = d['la'] >= 10
                co.append((F.gap(d, d['w'], am), F.gap(d, neu, am))); he.append((F.heat(d, d['w'], am), F.heat(d, neu, am)))
            aa = []
            for y, d in A3.items():
                neu = d['w'] - shift(d, full, kappa); m = (d['hi'] | d['lo']) & (d['la'] >= 10)
                aa.append((F.gap(d, d['w'], m), F.gap(d, neu, m)))
            print(f'  {label:12s} Coors {mean(co, 0):+.4f} -> {mean(co, 1):+.4f} | 20 F hotter {mean(he, 0):+.4f} -> {mean(he, 1):+.4f} | '
                  f'Triple-A altitude {mean(aa, 0):+.4f} -> {mean(aa, 1):+.4f}   by season ' + ' '.join(f'{x[1]:+.3f}' for x in aa))
            res[f'{name}|{label}'] = dict(coors=co, heat=he, aaa=aa)
        res[f'{name}|fit'] = dict(fit=[float(x) for x in full], per_season=per.tolist(), nb=nb)
    tmp = os.path.join(OUT, 'flight_models3.json.tmp')
    json.dump(res, open(tmp, 'w'), indent=1)
    os.replace(tmp, os.path.join(OUT, 'flight_models3.json'))
