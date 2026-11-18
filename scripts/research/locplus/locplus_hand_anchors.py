#!/usr/bin/env python3
"""locplus_hand_anchors.py — does the Loc+ anchor need pitcher hand, batter hand?

Shipped Loc+ standardizes per pitch GROUP only, so the mean level of every
(pitcher hand, batter hand) pair stays in the grade. Arms, all on the shipped
surfaces (nothing about the surfaces changes, only the (mu, sigma) a pitch is
standardized against):
  G     group                         (shipped)
  GT    group x pitcher hand
  GBT   group x batter hand x pitcher hand
Anchor pools: unit means with >= 60 pitches, unit = (pitcher, hand, type) for G
and GT, (pitcher, hand, type, batter hand) for GBT (60 is the shipped MIN_POOL_PT,
kept as a convention).

Also prints, per season, whether the surfaces are calibrated by hand: mean
expected run value against mean actual luck-neutral run value by pitcher hand
and by hand pair.

DECIDER, fixed before the run: next season, Stuff+ partialled, rendered unit,
WITHIN pitcher hand and role, mean of the xRV and actual-RV deltas against G.
The pooled frame is reported too: a change there that is absent within hand is
a level effect, not a ranking gain.

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/locplus_hand_anchors.py
"""
import gc
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline.locplus as lp  # noqa: E402
import locplus_fullseason_replicate as FR  # noqa: E402
import locplus_target_audit as A  # noqa: E402
import locplus_within_hand_role as W  # noqa: E402
from pipeline.sdplus import make_rv_xrv  # noqa: E402

CACHE = os.path.join(ROOT, 'data', '_loc_hand_anchors')
OUT = os.path.join(ROOT, 'data', '_loc_hand_anchors.json')
ARMS = {'G': ['grp'], 'GT': ['grp', 'throws'], 'GBT': ['grp', 'bats', 'throws']}
MIN_POOL = lp.MIN_POOL_PT
B = 2000


def season_table(y):
    fn = os.path.join(CACHE, f'{y}.pkl')
    if os.path.exists(fn):
        return pd.read_pickle(fn), json.load(open(fn.replace('.pkl', '_cal.json')))
    pitches = FR.load_season(y)
    base_p = [p for p in pitches if lp.is_eligible_baseline(p)]
    S = lp.build_surfaces(base_p, FR.LG, FR.SCALE)
    rv_x = make_rv_xrv(FR.LG, FR.SCALE)
    rows = []
    for p in pitches:
        if not lp._is_scorable(p):
            continue
        v = lp.score_pitch(p, S)
        if v is None:
            continue
        rows.append((p.get('Pitcher'), p.get('Throws'), p.get('Bats'), p.get('Pitch Type'),
                     lp.group_of(p), v, rv_x(p)))
    del pitches, base_p, S
    gc.collect()
    d = pd.DataFrame(rows, columns=['pitcher', 'throws', 'bats', 'pt', 'grp', 'v', 'x'])
    cal = {
        'by_throws': d.groupby('throws')[['v', 'x']].mean().mul(100).round(3).to_dict('index'),
        'by_pair': {f'{g}|{t}|{b}': [round(float(s.v.mean() * 100), 3), round(float(s.x.mean() * 100), 3), int(len(s))]
                    for (g, t, b), s in d.groupby(['grp', 'throws', 'bats'])},
    }
    out = {}
    for arm, keys in ARMS.items():
        ukeys = ['pitcher', 'throws', 'pt'] + (['bats'] if 'bats' in keys else [])
        u = d.groupby(ukeys + [k for k in keys if k not in ukeys])['v'].agg(['mean', 'size']).reset_index()
        q = u[u['size'] >= MIN_POOL]
        anc = q.groupby(keys)['mean'].agg(mu='mean', sd=lambda s: float(np.sqrt(((s - s.mean()) ** 2).mean())))
        j = d.join(anc, on=keys)
        atom = np.rint(100.0 - lp.LOC_SCALE_K * (j['v'] - j['mu']) / j['sd'])
        atom = atom.where(j['sd'] > 1e-12)
        out[arm] = atom.groupby([d['pitcher'], d['throws']]).mean()
        out['n'] = atom.groupby([d['pitcher'], d['throws']]).size()
    t = pd.DataFrame(out)
    os.makedirs(CACHE, exist_ok=True)
    t.to_pickle(fn)
    json.dump(cal, open(fn.replace('.pkl', '_cal.json'), 'w'), indent=1)
    return t, cal


def main():
    tabs, cals = {}, {}
    for y in range(2021, 2027):
        tabs[y], cals[y] = season_table(y)
        c = cals[y]['by_throws']
        print(f'{y}: expected vs actual runs/100 by hand  L {c["L"]["v"]:+.3f} / {c["L"]["x"]:+.3f}   '
              f'R {c["R"]["v"]:+.3f} / {c["R"]["x"]:+.3f}', flush=True)
    # level by hand under each arm
    print('\nmean rendered Loc+ by pitcher hand (>= 300 pitches), L minus R:')
    for y in range(2021, 2027):
        t = tabs[y][tabs[y]['n'] >= 300]
        g = t.groupby(level='throws')[list(ARMS)].mean()
        print(f'  {y}: ' + '  '.join(f'{a} {g.loc["L", a] - g.loc["R", a]:+.2f}' for a in ARMS))
    rng = np.random.default_rng(0)
    roles = json.load(open(os.path.join(ROOT, 'data', '_gate_v2', 'pitcher_role.json')))['roles']
    per = {}
    for y in W.PAIRS:
        ship = pd.read_pickle(A.table_path('shipped', y))
        v = A.with_stuff(A.view(ship, pd.read_pickle(A.table_path('shipped', y + 1)), 'next'), y)
        d = pd.DataFrame({'x': v['x'], 'rv': v['rv'], 'stuff': v['stuff'], 'audit': v['L_ren']})
        for a in ARMS:
            d[a] = -tabs[y][a].reindex(d.index)
        rm = roles.get(str(y + 1), {})
        d['hand'] = d.index.get_level_values('throws')
        d['role'] = [rm.get(p, 'NA') for p in d.index.get_level_values('pitcher')]
        d = d.dropna(subset=list(ARMS) + ['x', 'rv', 'stuff'])
        d = d[d['role'] != 'NA']
        chk = float(np.corrcoef(d['G'], d['audit'])[0, 1])
        n = len(d)
        idx = np.vstack([np.arange(n)[None, :], rng.integers(0, n, size=(B, n))])
        V = {c: d[c].values.astype(float)[idx] for c in list(ARMS) + ['x', 'rv', 'stuff']}
        codes = {'pooled': np.zeros(n, dtype=int), 'hand': pd.factorize(d['hand'])[0],
                 'hand_role': pd.factorize(d['hand'] + d['role'])[0]}
        rec = {}
        for fr, cd in codes.items():
            g = cd[idx]
            Wd = {c: W.demean(V[c], g) for c in V}
            for tg in ('x', 'rv'):
                pr = {a: W.partial(Wd[a], Wd[tg], Wd['stuff']) for a in ARMS}
                rec[f'{fr}:G:{tg}'] = (float(pr['G'][0]), float(pr['G'][1:].std()))
                for a in ('GT', 'GBT'):
                    dd = pr[a] - pr['G']
                    rec[f'{fr}:{a}-G:{tg}'] = (float(dd[0]), float(dd[1:].std()))
            for a in ('GT', 'GBT'):
                dd = sum(W.partial(Wd[a], Wd[tg], Wd['stuff']) - W.partial(Wd['G'], Wd[tg], Wd['stuff'])
                         for tg in ('x', 'rv')) / 2
                rec[f'{fr}:{a}-G:avg'] = (float(dd[0]), float(dd[1:].std()))
        per[y] = rec
        print(f'{y}->{y + 1}: n {n}, r(G arm, audit shipped) {chk:.4f}', flush=True)
    res = {}
    for k in per[W.PAIRS[0]]:
        m = float(np.mean([per[y][k][0] for y in W.PAIRS]))
        se = float(np.sqrt(sum(per[y][k][1] ** 2 for y in W.PAIRS)) / len(W.PAIRS))
        res[k] = {'mean': round(m, 4), 'se': round(se, 4), 'pos': int(sum(per[y][k][0] > 0 for y in W.PAIRS))}
    print('\nnext season, partial r given Stuff+ (mean of 5 pairs; se; pairs > 0)')
    for k, v in res.items():
        print(f'  {k:<22s} {v["mean"]:+.4f} ({v["se"]:.4f}) {v["pos"]}/5')
    json.dump({'summary': res, 'calibration': {str(y): cals[y] for y in cals}}, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
