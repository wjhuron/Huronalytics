#!/usr/bin/env python3
"""locplus_cs_count_fit.py — does the called-strike count transform fit held-out
takes, and does it still fit in the ABS challenge season (2026)?

CS_COUNT_TRANSFORM adds one logit intercept per (batter hand, count) to the
called-strike surface. It shipped on reliability alone. This is the direct test:
surfaces on even dates score the TAKES of odd dates (and the reverse); log loss
of the called-strike probability, transform on against off, per season and by
strikes. A human umpire widens the zone at 3-0 and narrows it at 0-2; the 2026
challenge system may have changed that, so 2026 is read apart from 2021-2025.

Also prints the mean observed minus predicted called-strike rate by count with
the transform OFF: the size of the count effect the transform has to explain.

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/locplus_cs_count_fit.py
"""
import gc
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline.locplus as lp  # noqa: E402
import locplus_fullseason_replicate as FR  # noqa: E402

OUT = os.path.join(ROOT, 'data', '_loc_cs_count_fit.json')
EPS = 1e-6


def ll(p, y):
    p = min(max(p, EPS), 1 - EPS)
    return -(math.log(p) if y else math.log(1 - p))


def main():
    acc = defaultdict(lambda: np.zeros(3))            # [(yr, slice)] n, sum d, sum d^2 ; d = ll_on - ll_off
    gap = defaultdict(lambda: np.zeros(3))            # [(yr, count)] n, obs, pred_off
    for yr in range(2021, 2027):
        base_p = [p for p in FR.load_season(yr) if lp.is_eligible_baseline(p)]
        dates = sorted({p['Game Date'] for p in base_p if p['Game Date']})
        par = {d: i % 2 for i, d in enumerate(dates)}
        for fold in (0, 1):
            train = [p for p in base_p if par.get(p['Game Date']) != fold]
            S = {}
            for flag in (True, False):
                lp.CS_COUNT_TRANSFORM = flag
                S[flag] = lp.build_surfaces(train, FR.LG, FR.SCALE)['PCS']
            lp.CS_COUNT_TRANSFORM = True
            del train
            for p in base_p:
                if par.get(p['Game Date']) != fold:
                    continue
                d = p.get('Description')
                if d not in ('Called Strike', 'Ball'):
                    continue
                c = lp.get_count(p)
                px = lp.safe_float(p.get('PlateX'))
                zn = lp._znorm(p)
                if c is None or px is None or zn is None:
                    continue
                i, j = lp._xbin(px), lp._zbin(zn)
                y = d == 'Called Strike'
                pon, poff = S[True][p['Bats']][c][i][j], S[False][p['Bats']][c][i][j]
                dd = ll(pon, y) - ll(poff, y)
                rec = np.array([1.0, dd, dd * dd])
                for sl in ('all', f's{c[1]}', f'b{c[0]}'):
                    acc[(yr, sl)] += rec
                gap[(yr, c)] += np.array([1.0, float(y), poff])
            del S
            gc.collect()
        t = acc[(yr, 'all')]
        print(f'{yr}: {int(t[0])} takes scored', flush=True)
        del base_p
        gc.collect()
    out = {}
    slices = ['all', 's0', 's1', 's2', 'b0', 'b1', 'b2', 'b3']
    print('\nlog loss per take x 1e4, transform ON minus OFF (negative = the transform fits better), with z')
    print(f'{"season":>8s}' + ''.join(f'{s:>18s}' for s in slices))
    for yr in list(range(2021, 2027)) + ['2021-25']:
        row = f'{str(yr):>8s}'
        for sl in slices:
            t = (sum(acc[(y, sl)] for y in range(2021, 2026)) if yr == '2021-25' else acc[(yr, sl)])
            n = t[0]
            e = t[1] / n
            se = math.sqrt(max(t[2] / n - e * e, 0.0) / n)
            out[f'{yr}:{sl}'] = {'n': int(n), 'd': e, 'se': se}
            row += f'{e * 1e4:>+9.2f} ({(e / se if se else 0):>+5.1f})'
        print(row)
    print('\ncalled-strike rate on takes, observed minus predicted with the transform OFF, percentage points')
    counts = sorted({k[1] for k in gap})
    print(f'{"season":>8s}' + ''.join(f'{str(c[0]) + "-" + str(c[1]):>7s}' for c in counts))
    for yr in range(2021, 2027):
        row = f'{yr:>8d}'
        for c in counts:
            t = gap[(yr, c)]
            g = 100 * (t[1] - t[2]) / t[0] if t[0] else float('nan')
            out[f'gap:{yr}:{c[0]}-{c[1]}'] = g
            row += f'{g:>+7.2f}'
        print(row)
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
