"""pit_park_test.py: does park belong in the pitcher runs projection?

On pit_experience_test's wide pool (+exper arm, k 20), add two features in runs per 9:
  park_hist   the history's home-park effect, (PF/100 + 1)/2 - 1 times the league RA9, weighted like the
              history (d^k by BF), PF of the season line's club (the final club for a traded pitcher)
  park_T      the same for the target season's club
The OLS learns both weights leaving the target season out; the batting analogue measured history park
removed and target park added at .375 of the factor (bat_park_test.py). Savant runs factors, data/_proj/
park_factors_hist.json, 2015-2026.

Usage: python3 scripts/research/projection/pit_park_test.py
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pit_experience_test as pe
import pit_rate_backtest as pr
import h2h_pitching as hp

PF = json.load(open(os.path.join(pr.P, 'park_factors_hist.json')))


def clubs(y):
    return {r['id']: r.get('team') for r in json.load(open(os.path.join(pr.P, f'lines_pitching_{y}.json')))}


def main():
    D = pe.build()
    IDS = hp.ids_by_season()
    S = {y: pr.season(y) for y in range(2015, 2027)}
    C = {y: clubs(y) for y in range(2015, 2027)}
    lg = {y: sum(v['ra9'] * 0 + 1 for v in S[y].values()) for y in S}   # placeholder, replaced below
    lgra9 = {}
    for y in S:
        L = json.load(open(os.path.join(pr.P, f'lines_pitching_{y}.json')))
        outs = sum(int(r.get('outs') or 0) for r in L); runs = sum(int(r.get('runs') or 0) for r in L)
        lgra9[y] = 27 * runs / outs
    eff = lambda y, team: 0.0 if PF.get(str(y), {}).get(str(team)) is None else ((PF[str(y)][str(team)] / 100 + 1) / 2 - 1) * lgra9[y]
    PK = {}
    for T in pe.TARGETS:
        rows = []
        for pid in IDS[T]:
            num = den = 0.0
            for k in range(3):
                h = S[T - 1 - k].get(pid)
                if h:
                    num += 0.65 ** k * h['bf'] * eff(T - 1 - k, C[T - 1 - k].get(pid)); den += 0.65 ** k * h['bf']
            rows.append((num / den if den else 0.0, eff(T, C[T].get(pid))))
        PK[T] = np.array(rows)

    def design(T, with_park):
        X = pe.design(D[T], '+exper', 20)
        return np.column_stack([X[:, :-1], PK[T], X[:, -1]]) if with_park else X

    res = {}
    for wp in (False, True):
        mse, betas = [], []
        for T in pe.TARGETS:
            tr = [s for s in pe.TARGETS if s != T]
            p, b = pr.fit_predict(np.vstack([design(s, wp) for s in tr]), np.concatenate([D[s]['y'] for s in tr]),
                                  np.concatenate([D[s]['w'] for s in tr]), design(T, wp))
            mse.append(float(np.average((p - D[T]['y']) ** 2, weights=D[T]['w']))); betas.append(b)
        res[wp] = (mse, betas)
    m0, m1 = res[False][0], res[True][0]
    b = np.mean(res[True][1], axis=0)
    print(f'without park {np.mean(m0):.4f}  with park {np.mean(m1):.4f}  ({100*(1-np.mean(m1)/np.mean(m0)):+.2f}%), wins {sum(a < c for a, c in zip(m1, m0))}/{len(m0)}')
    print(f'mean weights: history park {b[-2]:+.3f}, target park {b[-1]:+.3f}  (runs per 9 of RA9 per run of park effect; experience term {b[-3]:+.3f})')


if __name__ == '__main__':
    main()
