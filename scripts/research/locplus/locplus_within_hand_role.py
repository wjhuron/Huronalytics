#!/usr/bin/env python3
"""locplus_within_hand_role.py — read Loc+ verdicts WITHIN pitcher hand and role.

Every pitcher-level Loc+ verdict pooled hands and roles (locplus_target_audit.py).
The Stuff+ gate guards that trap with within-hand and within-role twins; Loc+ had
none. This script adds them, from the audit's cached per-pitcher tables only: no
surface is rebuilt and no pitch is scored.

Grades (rendered unit, mean of integer atoms, signed so higher = better):
  ship   shipped Loc+ (tab_shipped)
  null   the location-free grade (every K x 1e6: count mix, pitch mix, hands)
  loc    ship - null: what the location surface adds to the situation
  hneu   hand-neutral Loc+ of 2026-11-11 (tab_handNeu1111, baseline tab_ctl1111)

Test: grade in season Y against season Y+1 run value of the same pitcher
(x = luck-neutral xRV, rv = actual), five pairs, 300 pitches in each season
(the audit's floor, kept so the numbers line up with it). Every r is the
partial given the pitcher's out-of-sample Stuff+ of season Y.

Frames: pooled (the audit's), within hand, within role (SP/RP/swing from
data/_gate_v2/pitcher_role.json, role of season Y+1 as in the Stuff+ gate),
within hand x role. "Within" demeans every variable inside the group.
Paired pitcher bootstrap for the deltas.

  .venv/bin/python scripts/research/locplus/locplus_within_hand_role.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import locplus_target_audit as A  # noqa: E402

OUT = os.path.join(ROOT, 'data', '_loc_within_hand_role.json')
B = 2000
PAIRS = [2021, 2022, 2023, 2024, 2025]
FRAMES = ('pooled', 'hand', 'role', 'hand_role')


def load(y):
    t = {n: pd.read_pickle(A.table_path(n, y)) for n in ('shipped', A.NULL_NAME, 'handNeu1111', 'ctl1111')}
    t1 = pd.read_pickle(A.table_path('shipped', y + 1))
    v = A.with_stuff(A.view(t['shipped'], t1, 'next'), y)
    d = pd.DataFrame({'ship': v['L_ren'], 'x': v['x'], 'rv': v['rv'], 'stuff': v['stuff']})
    for name, col in ((A.NULL_NAME, 'null'), ('handNeu1111', 'hneu'), ('ctl1111', 'ctl')):
        d[col] = -t[name]['ren_full'].reindex(d.index)
    d['loc'] = d['ship'] - d['null']
    roles = json.load(open(os.path.join(ROOT, 'data', '_gate_v2', 'pitcher_role.json')))['roles']
    rm = roles.get(str(y + 1), {})
    d['hand'] = d.index.get_level_values('throws')
    d['role'] = [rm.get(p, 'NA') for p in d.index.get_level_values('pitcher')]
    d = d.dropna(subset=['ship', 'null', 'hneu', 'ctl', 'x', 'rv', 'stuff'])
    return d[d['role'] != 'NA']


def demean(M, g):
    """M: (boot, n) array already indexed; g: (boot, n) integer group codes."""
    out = M.copy()
    for code in np.unique(g):
        m = (g == code)
        cnt = m.sum(1, keepdims=True)
        mu = np.where(cnt > 0, (M * m).sum(1, keepdims=True) / np.maximum(cnt, 1), 0.0)
        out = out - mu * m
    return out


def partial(L, y, s):
    r = lambda a, b: (a * b).sum(1) / np.sqrt((a * a).sum(1) * (b * b).sum(1))
    c = lambda a: a - a.mean(1, keepdims=True)
    L, y, s = c(L), c(y), c(s)
    rly, rls, rsy = r(L, y), r(L, s), r(s, y)
    return (rly - rls * rsy) / np.sqrt((1 - rls ** 2) * (1 - rsy ** 2))


def one_pair(d, rng):
    n = len(d)
    idx = np.vstack([np.arange(n)[None, :], rng.integers(0, n, size=(B, n))])
    V = {c: d[c].values.astype(float)[idx] for c in ('ship', 'null', 'loc', 'hneu', 'ctl', 'x', 'rv', 'stuff')}
    codes = {
        'pooled': np.zeros((1, n), dtype=int),
        'hand': pd.factorize(d['hand'])[0][None, :],
        'role': pd.factorize(d['role'])[0][None, :],
        'hand_role': pd.factorize(d['hand'] + d['role'])[0][None, :],
    }
    out = {}
    for fr in FRAMES:
        g = codes[fr][0][idx]
        W = {c: demean(V[c], g) for c in V}
        rec = {}
        for tg in ('x', 'rv'):
            pr = {a: partial(W[a], W[tg], W['stuff']) for a in ('ship', 'null', 'loc', 'hneu', 'ctl')}
            for a in ('ship', 'null', 'loc'):
                rec[f'{a}_{tg}'] = (float(pr[a][0]), float(pr[a][1:].std()))
            for nm, dd in (('loc_minus_ship', pr['loc'] - pr['ship']), ('null_minus_ship', pr['null'] - pr['ship']),
                           ('hneu_minus_ctl', pr['hneu'] - pr['ctl'])):
                rec[f'{nm}_{tg}'] = (float(dd[0]), float(dd[1:].std()))
        out[fr] = rec
    return out


def main():
    rng = np.random.default_rng(0)
    per = {}
    for y in PAIRS:
        d = load(y)
        per[y] = one_pair(d, rng)
        print(f'{y}->{y + 1}: n {len(d)}  L {int((d.hand == "L").sum())}  roles {d.role.value_counts().to_dict()}', flush=True)
    keys = list(per[PAIRS[0]]['pooled'])
    res = {}
    for fr in FRAMES:
        res[fr] = {}
        for k in keys:
            m = np.mean([per[y][fr][k][0] for y in PAIRS])
            se = np.sqrt(sum(per[y][fr][k][1] ** 2 for y in PAIRS)) / len(PAIRS)
            wins = sum(per[y][fr][k][0] > 0 for y in PAIRS)
            res[fr][k] = {'mean': round(float(m), 4), 'se': round(float(se), 4), 'pos_pairs': int(wins)}
    for tg, lab in (('x', 'luck-neutral xRV'), ('rv', 'actual RV')):
        print(f'\n=== next season, {lab}; partial r given Stuff+ (mean of 5 pairs, se, pairs > 0) ===')
        print(f'{"frame":>10s} | {"shipped":>16s} {"location-free":>16s} {"location only":>16s} | '
              f'{"loc - ship":>18s} {"null - ship":>18s} {"handNeu - ctl":>18s}')
        for fr in FRAMES:
            c = res[fr]
            f = lambda k: f"{c[k]['mean']:+.3f} ({c[k]['se']:.3f})"
            g = lambda k: f"{c[k]['mean']:+.3f} ({c[k]['se']:.3f}) {c[k]['pos_pairs']}/5"
            print(f'{fr:>10s} | {f("ship_" + tg):>16s} {f("null_" + tg):>16s} {f("loc_" + tg):>16s} | '
                  f'{g("loc_minus_ship_" + tg):>18s} {g("null_minus_ship_" + tg):>18s} {g("hneu_minus_ctl_" + tg):>18s}')
    json.dump({'summary': res, 'per_pair': {str(y): per[y] for y in PAIRS}}, open(OUT, 'w'), indent=1)
    print(f'\nwrote {OUT}')


if __name__ == '__main__':
    main()
