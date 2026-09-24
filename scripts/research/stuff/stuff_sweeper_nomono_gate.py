#!/usr/bin/env python3
"""stuff_sweeper_nomono_gate.py — does the monotone velocity rule mis-grade
sweepers?

stuff_sweeper_validity.py (2026-09-23) found ST Stuff+ carries to the next
season at r .12 (others .28-.42) although ST results persist like SL/CU/FC,
and that, given the grade, higher ST velocity / spin / cross predict slightly
WORSE next-season results. Stuff+ forces velocity monotone (faster never
worse, `T.MONO_FEAT`) on every pitch; the ledger lists that rule as CONV,
never toggled on nxt_r. Slower sweepers may carry more sweep.

Variant NOMONO: the SHIPPED config with the monotone constraint removed.
Gate v2 protocol, seed 0: aggregates and results.json exactly as
`stuff_gate_v2.py run` writes them (read the pooled z with `stuff_gate_v2.py
summary --names SHIPPED,NOMONO`), plus per-type next-season unit validity
(rendered unit grade Y vs unit xRV Y+1, units >= 150 both seasons) with a
paired pitcher bootstrap against SHIPPED s0.

Output: data/_sweeper_nomono.json. Run from the repo root.
"""
import gc
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import xgboost as xgb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
import stuff_gate_v2 as G                               # noqa: E402

T = G.T
NAME = 'NOMONO'
SEED = 0
MIN_U = 150
BOOT_B = 1000
OUT = os.path.join(ROOT, 'data', '_sweeper_nomono.json')
TYPES = ['FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS']


def fit_pairs():
    frames = {y: G.load_frame(y) for y in G.SEASONS}
    G.set_arm_side_sign(list(frames.values()))
    for Y, Y1 in G.PAIRS:
        if os.path.exists(G.agg_path(NAME, Y, SEED)):
            print(f'  {Y}->{Y1}: cached', flush=True)
            continue
        t0 = time.time()
        train_years = [y for y in G.SEASONS if y not in (Y, Y1)]
        slopes = G.fit_vaa_slopes([frames[y] for y in train_years])
        P = {y: G.prepare(frames[y], slopes) for y in train_years + [Y, Y1]}
        feats = G.variant_feats({})
        Xtr = pd.concat([G.design(P[y], {}, feats) for y in train_years], ignore_index=True)
        ytr = np.concatenate([P[y]['target_xrv'].values for y in train_years])
        params = T._params_for(Xtr)
        params.pop('monotone_constraints', None)       # the variant
        params['random_state'] = SEED
        m = xgb.XGBRegressor(**params)
        m.fit(Xtr, ytr)
        pred = m.predict(G.design(P[Y], {}, feats))
        agg = G.aggregates(P[Y].assign(stuff=-pred), P[Y1])
        met = G.metrics_from(agg)
        met.update(n_train=int(len(ytr)), feats=feats, partial_target=(Y == G.PARTIAL_Y),
                   note='monotone velocity constraint removed')
        pd.to_pickle(agg, G.agg_path(NAME, Y, SEED))
        res = json.load(open(G.RESULTS)) if os.path.exists(G.RESULTS) else {}
        res.setdefault(NAME, {}).setdefault(str(Y), {})[str(SEED)] = met
        with open(G.RESULTS + '.tmp', 'w') as f:
            json.dump(res, f, indent=1)
        os.replace(G.RESULTS + '.tmp', G.RESULTS)
        print(f'  {NAME} {Y}->{Y1}: nxt raw {met["nxt_r"]:.4f} rend {met["nxt_r_rend"]:.4f} '
              f'[{time.time() - t0:.0f}s]', flush=True)
        del P, Xtr, ytr, m, pred, agg
        gc.collect()


def units(name, Y):
    a = pd.read_pickle(G.agg_path(name, Y, SEED))
    j = a['uy'].join(a['uy1'], lsuffix='_y', rsuffix='_y1', how='inner').reset_index()
    j = j[(j['n_y'] >= MIN_U) & (j['n_y1'] >= MIN_U)]
    return j[['pitcher', 'pitch_type', 's_r', 't']].assign(pair=Y)


def main():
    fit_pairs()
    A = pd.concat([units('SHIPPED', Y) for Y, _ in G.PAIRS])
    B = pd.concat([units(NAME, Y) for Y, _ in G.PAIRS])
    J = A.merge(B, on=['pitcher', 'pitch_type', 'pair'], suffixes=('_a', '_b'))
    rng = np.random.default_rng(9)
    out = {}
    print('\nper-type next-season unit validity (rendered grade Y vs unit xRV Y+1):')
    print('type  units  SHIPPED  NOMONO   delta   se    z   per-pair deltas')
    for t in TYPES:
        g = J[J['pitch_type'] == t].reset_index(drop=True)
        if len(g) < 60:
            continue
        ra = np.corrcoef(g['s_r_a'], g['t_a'])[0, 1]
        rb = np.corrcoef(g['s_r_b'], g['t_b'])[0, 1]
        pits = g['pitcher'].unique()
        idx = {p: np.flatnonzero(g['pitcher'].values == p) for p in pits}
        ds = []
        for _ in range(BOOT_B):
            q = g.iloc[np.concatenate([idx[p] for p in rng.choice(pits, len(pits))])]
            ds.append(np.corrcoef(q['s_r_b'], q['t_b'])[0, 1] - np.corrcoef(q['s_r_a'], q['t_a'])[0, 1])
        se = float(np.std(ds))
        pp = {str(y): float(np.corrcoef(h['s_r_b'], h['t_b'])[0, 1] - np.corrcoef(h['s_r_a'], h['t_a'])[0, 1])
              for y, h in g.groupby('pair')}
        out[t] = {'units': int(len(g)), 'shipped': float(ra), 'nomono': float(rb),
                  'delta': float(rb - ra), 'se': se, 'z': float((rb - ra) / se), 'per_pair': pp}
        print(f'{t:4} {len(g):6}  {ra:7.3f}  {rb:6.3f}  {rb - ra:+.3f}  {se:.3f}  {(rb - ra) / se:+4.1f}  '
              + ' '.join(f'{v:+.3f}' for v in pp.values()))
    json.dump(out, open(OUT + '.tmp', 'w'), indent=1)
    os.replace(OUT + '.tmp', OUT)
    print(f'\nwrote {OUT}\ngate: python3 scripts/research/stuff/stuff_gate_v2.py summary --names SHIPPED,{NAME}')


if __name__ == '__main__':
    main()
