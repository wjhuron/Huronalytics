#!/usr/bin/env python3
"""stuff_sweeper_validity.py — why does sweeper Stuff+ barely carry to the
next season?

Finding (2026-09-23): per-type next-season validity from the gate v2
SHIPPED aggregates (units >= 150 pitches both seasons) reads r .28-.42 for
every type except ST, r .11 (.07-.15 in all five pairs).

Candidate causes, each measured per pitch type on the SAME units:
  1. noise ceiling   the realized unit xRV's own persistence Y -> Y+1, its
                     split-half reliability (odd/even pitches, Spearman-
                     Brown), and the true-talent SD sqrt(cov(tY, tY1))
  2. narrow spread   SD of the raw unit grade (runs/100)
  3. model misses    disattenuated validity r(s, tY1) / sqrt(rel_t), the
                     grade's own split-half reliability and descriptive
                     r(s, tY)
  4. matchup mix     the same unit on SAME-HAND pitches only and on
                     OPPOSITE-HAND pitches only (grade and target both
                     restricted), and the change in same-hand share Y->Y+1
  5. label / shape   share of Y units whose pitcher throws the same label in
                     Y+1; grade year-over-year r (the same pitcher's grade in
                     Y vs Y+1, both out of sample) as a pitch-stability probe

Grades: gate v2 SHIPPED seed-0 per-pitch predictions from
data/_platoon_split/pred_{Y}.pkl (fit on seasons other than Y and Y+1,
rows aligned with data/_gate_v2/season_{Y}.pkl). Target: target_xrv,
pitcher-positive. Correlations are pooled over pairs after demeaning within
(pair, type). Pitcher-bootstrap SE on the headline r.

Output: data/_sweeper_validity.json. Run from the repo root.
"""
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
GATE = os.path.join(ROOT, 'data', '_gate_v2')
PRED = os.path.join(ROOT, 'data', '_platoon_split')
OUT = os.path.join(ROOT, 'data', '_sweeper_validity.json')
PAIRS = [2021, 2022, 2023, 2024, 2025]
TYPES = ['FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS']
MIN_U = 150
MIN_SIDE = 60
BOOT_B = 500


def season(y):
    fr = pd.read_pickle(os.path.join(GATE, f'season_{y}.pkl'))
    fr = fr[['pitcher', 'pitch_type', 'platoon_same', 'target_xrv']].copy()
    fr['t'] = -fr['target_xrv'].astype(float)          # pitcher-positive
    fr['half'] = fr.groupby(['pitcher', 'pitch_type']).cumcount() % 2
    return fr


def with_grade(fr, y):
    pr = pd.read_pickle(os.path.join(PRED, f'pred_{y}.pkl'))
    if len(pr) != len(fr) or not (pr['pitcher'].values == fr['pitcher'].values).all():
        raise SystemExit(f'pred_{y}.pkl is not row-aligned with season_{y}.pkl; '
                         f'rebuild it with stuff_platoon_split_persistence.py')
    return fr.assign(s=pr['stuff'].values.astype(float) * 100)   # runs/100


def unit_table(fr, grade):
    k = ['pitcher', 'pitch_type']
    agg = {'t': ('t', 'mean'), 'n': ('t', 'size'), 'same': ('platoon_same', 'mean')}
    if grade:
        agg['s'] = ('s', 'mean')
    u = fr.groupby(k).agg(**agg)
    h = fr.groupby(k + ['half'])['t'].mean().unstack('half')
    u['t_h0'], u['t_h1'] = h[0], h[1]
    if grade:
        hs = fr.groupby(k + ['half'])['s'].mean().unstack('half')
        u['s_h0'], u['s_h1'] = hs[0], hs[1]
    for side, v in (('S', 1), ('O', 0)):
        q = fr[fr['platoon_same'] == v]
        a = {'t': ('t', 'mean'), 'n': ('t', 'size')}
        if grade:
            a['s'] = ('s', 'mean')
        qs = q.groupby(k).agg(**a)
        for c in qs.columns:
            u[f'{c}_{side}'] = qs[c]
    return u


def r(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    return float(np.corrcoef(a[m], b[m])[0, 1]) if m.sum() > 10 else float('nan')


def sb(x):
    return 2 * x / (1 + x) if np.isfinite(x) else float('nan')


def main():
    F = {y: season(y) for y in range(2021, 2027)}
    rows = []
    for Y in PAIRS:
        uY = unit_table(with_grade(F[Y], Y), True)
        uY1 = unit_table(F[Y + 1], False)
        gY1 = (unit_table(with_grade(F[Y + 1], Y + 1), True)['s']
               if Y + 1 in PAIRS else None)
        j = uY.join(uY1, rsuffix='_1', how='left').reset_index()
        j['kept_label'] = j['n_1'].notna() & (j['n_1'] >= MIN_U)
        if gY1 is not None:
            j = j.merge(gY1.rename('s_next').reset_index(), on=['pitcher', 'pitch_type'], how='left')
        else:
            j['s_next'] = np.nan
        j['pair'] = Y
        rows.append(j)
    U = pd.concat(rows, ignore_index=True)
    U = U[U['pitch_type'].isin(TYPES) & (U['n'] >= MIN_U)]
    # label continuity uses every Y unit; everything else needs both seasons
    cont = U.groupby('pitch_type')['kept_label'].mean()
    B = U[U['kept_label']].copy()
    for c in ['s', 't', 't_1', 's_h0', 's_h1', 't_h0', 't_h1', 's_S', 't_S', 's_O', 't_O',
              't_S_1', 't_O_1', 's_next']:
        if c in B:
            B[c] = B[c] - B.groupby(['pair', 'pitch_type'])[c].transform('mean')

    rng = np.random.default_rng(5)
    out = {}
    for t in TYPES:
        g = B[B['pitch_type'] == t]
        if len(g) < 60:
            continue
        rel_t = sb(r(g['t_h0'].values, g['t_h1'].values))
        rel_s = sb(r(g['s_h0'].values, g['s_h1'].values))
        nxt = r(g['s'].values, g['t_1'].values)
        pits = g['pitcher'].unique()
        idx = {p: np.flatnonzero(g['pitcher'].values == p) for p in pits}
        bs = []
        for _ in range(BOOT_B):
            q = g.iloc[np.concatenate([idx[p] for p in rng.choice(pits, len(pits))])]
            bs.append(r(q['s'].values, q['t_1'].values))
        cov = float(np.cov(g['t'].values, g['t_1'].values)[0, 1])
        sS = g[(g['n_S'] >= MIN_SIDE) & (g['n_S_1'] >= MIN_SIDE)]
        sO = g[(g['n_O'] >= MIN_SIDE) & (g['n_O_1'] >= MIN_SIDE)]
        out[t] = {
            'units': int(len(g)),
            'nxt_r': nxt, 'nxt_r_se': float(np.nanstd(bs)),
            'nxt_r_pair': {str(y): r(h['s'].values, h['t_1'].values) for y, h in g.groupby('pair')},
            'target_persist_r': r(g['t'].values, g['t_1'].values),
            'target_rel_sb': rel_t,
            'true_sd_runs100': float(np.sqrt(max(cov, 0.0)) * 100),
            'target_sd_runs100': float(g['t_1'].std() * 100),
            'grade_sd_runs100': float(g['s'].std()),
            'grade_rel_sb': rel_s,
            'desc_r': r(g['s'].values, g['t'].values),
            'nxt_r_disatt': nxt / np.sqrt(rel_t) if rel_t and rel_t > 0 else float('nan'),
            'grade_yoy_r': r(g['s'].values, g['s_next'].values),
            'same_share': float(g['same'].mean()),
            'same_share_change_sd': float((g['same_1'] - g['same']).std()),
            'nxt_r_same_only': r(sS['s_S'].values, sS['t_S_1'].values), 'n_same_only': int(len(sS)),
            'nxt_r_opp_only': r(sO['s_O'].values, sO['t_O_1'].values), 'n_opp_only': int(len(sO)),
            'label_continuity': float(cont.get(t, np.nan)),
        }
    json.dump(out, open(OUT + '.tmp', 'w'), indent=1)
    os.replace(OUT + '.tmp', OUT)
    cols = [('units', '{:5d}'), ('nxt_r', '{:5.2f}'), ('target_persist_r', '{:5.2f}'),
            ('target_rel_sb', '{:5.2f}'), ('nxt_r_disatt', '{:5.2f}'), ('true_sd_runs100', '{:5.2f}'),
            ('grade_sd_runs100', '{:5.2f}'), ('grade_rel_sb', '{:5.2f}'), ('desc_r', '{:5.2f}'),
            ('grade_yoy_r', '{:5.2f}'), ('nxt_r_same_only', '{:5.2f}'), ('nxt_r_opp_only', '{:5.2f}'),
            ('label_continuity', '{:5.2f}')]
    heads = ['n', 'nxt', 'tPers', 'tRel', 'disatt', 'trueSD', 'gSD', 'gRel', 'desc', 'gYoY', 'sameO', 'oppO', 'label']
    print('type ' + ' '.join(f'{h:>6}' for h in heads))
    for t, v in out.items():
        print(f'{t:4} ' + ' '.join(f'{fmt.format(v[c]):>6}' for c, fmt in cols))
    print(f'\nST per pair: {out.get("ST", {}).get("nxt_r_pair")}')
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
