#!/usr/bin/env python3
"""stuff_sweeper_command.py — are sweeper results command-driven?

Context: sweeper (ST) Stuff+ carries to the next season at r .12 against
.28-.42 for other types, while ST results themselves persist (r .28). Noise,
spread, labels, the monotone rule, the one-model design and pitch change are
ruled out (stuff_sweeper_validity.py, stuff_sweeper_nomono_gate.py,
stuff_sweeper_diagnostics.py). If the persistent part of sweeper results is
LOCATION, a physics grade has a low ceiling there by nature.

Location value per pitch = the gate frames' `l_loc` (locplus.score_pitch on
the season's own surfaces, batter-positive, same currency as the target,
centred within (Loc+ group, bats, throws, count)). Unit L = -mean(l_loc)
(pitcher-positive). Per type, units >= 150 pitches both seasons, pooled over
the gate pairs after demeaning within (pair, type):

  loc_next      r(L_Y, t_Y+1)          location value -> next-season result
  loc_persist   r(L_Y, L_Y+1)          is location value itself stable
  grade_next    r(grade_Y, t_Y+1)      Stuff+ (gate SHIPPED s0) alone
  both_R        multiple R of t_Y+1 on grade_Y and L_Y
  loc_partial   partial r(L_Y, t_Y+1 | grade_Y)
  t_persist     r(t_Y, t_Y+1)          raw result persistence
  tadj_persist  r(tadj_Y, tadj_Y+1)    persistence of the result with the
                location term removed (tadj = target - l_loc)

Caveat: Loc+ surfaces are per Loc+ GROUP, not per pitch type, so a sweeper
is valued on a surface it shares with other breaking balls.

Output: data/_sweeper_command.json. Run from the repo root.
"""
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
GATE = os.path.join(ROOT, 'data', '_gate_v2')
PRED = os.path.join(ROOT, 'data', '_platoon_split')
OUT = os.path.join(ROOT, 'data', '_sweeper_command.json')
PAIRS = [2021, 2022, 2023, 2024, 2025]
TYPES = ['FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS']
MIN_U = 150
BOOT_B = 500


def units(y, grade):
    fr = pd.read_pickle(os.path.join(GATE, f'season_{y}.pkl'))
    d = pd.DataFrame({'pitcher': fr['pitcher'].values, 'pitch_type': fr['pitch_type'].values,
                      't': -fr['target_xrv'].astype(float).values,
                      'loc': -fr['l_loc'].astype(float).values})
    d['tadj'] = d['t'] - d['loc']            # -(target - l_loc)
    if grade:
        pr = pd.read_pickle(os.path.join(PRED, f'pred_{y}.pkl'))
        if len(pr) != len(fr) or not (pr['pitcher'].values == fr['pitcher'].values).all():
            raise SystemExit(f'pred_{y}.pkl is not row-aligned with season_{y}; rebuild it')
        d['s'] = pr['stuff'].values
    cov = float(np.isfinite(d['loc']).mean())
    d = d[np.isfinite(d['loc'])]
    agg = {'t': ('t', 'mean'), 'L': ('loc', 'mean'), 'tadj': ('tadj', 'mean'), 'n': ('t', 'size')}
    if grade:
        agg['s'] = ('s', 'mean')
    return d.groupby(['pitcher', 'pitch_type']).agg(**agg), cov


def r(a, b):
    return float(np.corrcoef(a, b)[0, 1])


def stats(g):
    y, s, L = g['t_1'].values, g['s'].values, g['L'].values
    rs, rl, rsl = r(s, y), r(L, y), r(s, L)
    R2 = (rs ** 2 + rl ** 2 - 2 * rs * rl * rsl) / (1 - rsl ** 2)
    part = (rl - rs * rsl) / np.sqrt((1 - rs ** 2) * (1 - rsl ** 2))
    return {'grade_next': rs, 'loc_next': rl, 'r_grade_loc': rsl,
            'both_R': float(np.sqrt(max(R2, 0))), 'loc_partial': float(part),
            'loc_persist': r(L, g['L_1'].values),
            't_persist': r(g['t'].values, y),
            'tadj_persist': r(g['tadj'].values, g['tadj_1'].values)}


def main():
    rows, covs = [], {}
    cache = {}
    for Y in PAIRS:
        uY, cY = cache.get(Y) or units(Y, True)
        cache[Y] = (uY, cY)
        uY1, cY1 = units(Y + 1, False)
        covs[str(Y)], covs[str(Y + 1)] = cY, cY1
        j = uY.join(uY1, rsuffix='_1', how='inner').reset_index()
        j = j[(j['n'] >= MIN_U) & (j['n_1'] >= MIN_U) & j['pitch_type'].isin(TYPES)].copy()
        j['pair'] = Y
        rows.append(j)
    U = pd.concat(rows, ignore_index=True)
    for c in ['t', 'L', 'tadj', 's', 't_1', 'L_1', 'tadj_1']:
        U[c] = U[c] - U.groupby(['pair', 'pitch_type'])[c].transform('mean')

    rng = np.random.default_rng(21)
    out = {'l_loc_coverage': covs, 'types': {}}
    keys = ['grade_next', 'loc_next', 'both_R', 'loc_partial', 'loc_persist', 't_persist', 'tadj_persist']
    print('l_loc coverage by season: ' + ', '.join(f'{k} {v:.1%}' for k, v in covs.items()))
    print('\ntype units  grade>nxt  loc>nxt  both_R  locPart  locPers  tPers  tadjPers')
    for t in TYPES:
        g = U[U['pitch_type'] == t].reset_index(drop=True)
        st = stats(g)
        pits = g['pitcher'].unique()
        idx = {p: np.flatnonzero(g['pitcher'].values == p) for p in pits}
        bs = [stats(g.iloc[np.concatenate([idx[p] for p in rng.choice(pits, len(pits))])])
              for _ in range(BOOT_B)]
        st_se = {k: float(np.std([b[k] for b in bs])) for k in keys}
        out['types'][t] = {'units': int(len(g)), **st, 'se': st_se}
        print(f'{t:4} {len(g):5}  ' + '  '.join(f'{st[k]:7.3f}' for k in keys))
    print('\nbootstrap SE (ST): ' + ', '.join(f'{k} {out["types"]["ST"]["se"][k]:.3f}' for k in keys))
    json.dump(out, open(OUT + '.tmp', 'w'), indent=1)
    os.replace(OUT + '.tmp', OUT)
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
