#!/usr/bin/env python3
"""stuff_sweeper_role.py — does pitcher ROLE explain the sweeper gap, and is
the Stuff+ gate's nxt_r a within-role ranking?

Context: sweeper (ST) Stuff+ carries to the next season at r .11 against
.28-.42 for other types while ST results persist (r .28); noise, spread,
labels, the monotone rule, the one-model design, pitch change and Loc+
location are ruled out. Sweepers are reliever-heavy, and relievers' pitches
play up (one time through the order), so a persistent role effect could sit
in ST results that a physics grade cannot see.

Role proxy (not in the gate frames): starter share = share of a pitcher's
appearances (pitcher, date) with >= SP_PITCHES pitches in the season frame.
Convention, not a measured cutoff: 45 separates openers/bulk arms loosely;
the result is re-read at 35 and 60 to show it does not hinge on it.

Unit analysis (pitcher, type), units >= 150 pitches both seasons, gate
pairs, demeaned within (pair, type):
  role_next_partial   partial r(starter share Y+1, result Y+1 | grade Y)
  grade_next_RP/SP    grade validity within relievers / starters (share
                      < .5 / >= .5 in BOTH seasons)
  t_persist_role      result persistence after removing starter share
                      (Y on Y, Y+1 on Y+1)
Pitcher level (the open "within-role decomposition" of the gate):
  gate SHIPPED s0 pitcher grade Y vs luck-neutral target Y+1 (>= 300 both,
  the gate's MIN_NXT), pooled vs demeaned within role (SP / RP / swing by
  the Y+1 share), pitcher-bootstrap SE.

Output: data/_sweeper_role.json. Run from the repo root.
"""
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
GATE = os.path.join(ROOT, 'data', '_gate_v2')
PRED = os.path.join(ROOT, 'data', '_platoon_split')
OUT = os.path.join(ROOT, 'data', '_sweeper_role.json')
PAIRS = [2021, 2022, 2023, 2024, 2025]
TYPES = ['FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS']
MIN_U = 150
MIN_P = 300
SP_PITCHES = (35, 45, 60)
BOOT_B = 500


def load(y, grade):
    fr = pd.read_pickle(os.path.join(GATE, f'season_{y}.pkl'))
    d = pd.DataFrame({'pitcher': fr['pitcher'].values, 'pitch_type': fr['pitch_type'].values,
                      'date': fr['date'].astype(str).str.slice(0, 10).values,
                      't': -fr['target_xrv'].astype(float).values})
    if grade:
        pr = pd.read_pickle(os.path.join(PRED, f'pred_{y}.pkl'))
        if len(pr) != len(fr) or not (pr['pitcher'].values == fr['pitcher'].values).all():
            raise SystemExit(f'pred_{y}.pkl is not row-aligned with season_{y}; rebuild it')
        d['s'] = pr['stuff'].values
    app = d.groupby(['pitcher', 'date']).size()
    role = pd.DataFrame({f'sp{k}': (app >= k).groupby(level=0).mean() for k in SP_PITCHES})
    role['apps'] = app.groupby(level=0).size()
    return d, role


def r(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    return float(np.corrcoef(a[m], b[m])[0, 1]) if m.sum() > 10 else float('nan')


def partial(x, y, z):
    rxy, rxz, ryz = r(x, y), r(x, z), r(y, z)
    return float((rxy - rxz * ryz) / np.sqrt((1 - rxz ** 2) * (1 - ryz ** 2)))


def resid(y, x):
    m = np.isfinite(y) & np.isfinite(x)
    b = np.polyfit(x[m], y[m], 1)
    return y - (b[0] * x + b[1])


def main():
    D = {}
    for y in range(2021, 2027):
        D[y] = load(y, y in PAIRS)
    urows, prow = [], []
    for Y in PAIRS:
        dY, rY = D[Y]
        dY1, rY1 = D[Y + 1]
        uY = dY.groupby(['pitcher', 'pitch_type']).agg(s=('s', 'mean'), t=('t', 'mean'), n=('t', 'size'))
        uY1 = dY1.groupby(['pitcher', 'pitch_type']).agg(t_1=('t', 'mean'), n_1=('t', 'size'))
        j = uY.join(uY1, how='inner').reset_index()
        j = j[(j['n'] >= MIN_U) & (j['n_1'] >= MIN_U) & j['pitch_type'].isin(TYPES)]
        j = j.join(rY.add_suffix('_y'), on='pitcher').join(rY1.add_suffix('_y1'), on='pitcher')
        j['pair'] = Y
        urows.append(j)
        pY = dY.groupby('pitcher').agg(s=('s', 'mean'), n=('t', 'size'))
        pY1 = dY1.groupby('pitcher').agg(t_1=('t', 'mean'), n_1=('t', 'size'))
        p = pY.join(pY1, how='inner')
        p = p[(p['n'] >= MIN_P) & (p['n_1'] >= MIN_P)].join(rY1.add_suffix('_y1'))
        p = p.reset_index().assign(pair=Y)
        prow.append(p)
    U = pd.concat(urows, ignore_index=True)
    Pp = pd.concat(prow, ignore_index=True)
    num = ['s', 't', 't_1'] + [c for c in U.columns if c.startswith('sp')]
    Uc = U.copy()
    for c in num:
        Uc[c] = Uc[c] - Uc.groupby(['pair', 'pitch_type'])[c].transform('mean')

    out = {'units': {}, 'pitcher_level': {}}
    print('unit level (sp share cutoff 45 pitches; 35 / 60 in brackets):')
    print('type units  RPshare  grade>nxt  roleY1|grade        RP: n  r     SP: n  r     tPers  tPers|role')
    for t in TYPES:
        g = Uc[Uc['pitch_type'] == t]
        raw = U[U['pitch_type'] == t]
        rec = {'units': int(len(g)), 'reliever_share': float((raw['sp45_y'] < 0.5).mean()),
               'grade_next': r(g['s'].values, g['t_1'].values)}
        for k in SP_PITCHES:
            rec[f'role_next_partial_{k}'] = partial(g[f'sp{k}_y1'].values, g['t_1'].values, g['s'].values)
            rec[f't_persist_role_{k}'] = r(resid(g['t'].values, g[f'sp{k}_y'].values),
                                           resid(g['t_1'].values, g[f'sp{k}_y1'].values))
        rp = g[(raw['sp45_y'] < 0.5).values & (raw['sp45_y1'] < 0.5).values]
        sp = g[(raw['sp45_y'] >= 0.5).values & (raw['sp45_y1'] >= 0.5).values]
        rec.update(n_RP=int(len(rp)), grade_next_RP=r(rp['s'].values, rp['t_1'].values),
                   n_SP=int(len(sp)), grade_next_SP=r(sp['s'].values, sp['t_1'].values),
                   t_persist=r(g['t'].values, g['t_1'].values))
        out['units'][t] = rec
        print(f"{t:4} {len(g):5}  {rec['reliever_share']:6.2f}  {rec['grade_next']:8.3f}  "
              f"{rec['role_next_partial_45']:+.3f} [{rec['role_next_partial_35']:+.3f} {rec['role_next_partial_60']:+.3f}]  "
              f"{rec['n_RP']:5} {rec['grade_next_RP']:.3f}  {rec['n_SP']:5} {rec['grade_next_SP']:.3f}  "
              f"{rec['t_persist']:.3f}  {rec['t_persist_role_45']:.3f}")

    # pitcher level: pooled vs within role (Y+1 role), gate objective
    Pp['role'] = np.where(Pp['sp45_y1'] >= 0.7, 'SP', np.where(Pp['sp45_y1'] <= 0.3, 'RP', 'SW'))
    for c in ('s', 't_1'):
        Pp[c + '_p'] = Pp[c] - Pp.groupby('pair')[c].transform('mean')
        Pp[c + '_w'] = Pp[c] - Pp.groupby(['pair', 'role'])[c].transform('mean')
    rng = np.random.default_rng(31)
    pits = Pp['pitcher'].unique()
    idx = {q: np.flatnonzero(Pp['pitcher'].values == q) for q in pits}

    def f(df):
        return np.array([r(df['s_p'].values, df['t_1_p'].values), r(df['s_w'].values, df['t_1_w'].values)])
    base = f(Pp)
    bs = np.array([f(Pp.iloc[np.concatenate([idx[q] for q in rng.choice(pits, len(pits))])]) for _ in range(BOOT_B)])
    d_se = float(np.std(bs[:, 1] - bs[:, 0]))
    per_pair = {str(y): list(map(float, f(h))) for y, h in Pp.groupby('pair')}
    lvl = Pp.groupby('role')[['s_p', 't_1_p']].mean()
    out['pitcher_level'] = {'n': int(len(Pp)), 'role_counts': Pp['role'].value_counts().to_dict(),
                            'pooled_r': float(base[0]), 'within_role_r': float(base[1]),
                            'delta': float(base[1] - base[0]), 'delta_se': d_se,
                            'per_pair_pooled_within': per_pair,
                            'role_means_grade_target': lvl.to_dict()}
    print(f"\npitcher level (gate objective, n {len(Pp)}, roles {Pp['role'].value_counts().to_dict()}):")
    print(f"  pooled r {base[0]:.3f}   within role r {base[1]:.3f}   delta {base[1] - base[0]:+.3f} (se {d_se:.3f})")
    print('  per pair (pooled, within): ' + ', '.join(f'{k} {v[0]:.3f}/{v[1]:.3f}' for k, v in per_pair.items()))
    print('  role means (grade, next target), runs/pitch demeaned:\n' + lvl.to_string())
    json.dump(out, open(OUT + '.tmp', 'w'), indent=1, default=float)
    os.replace(OUT + '.tmp', OUT)
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
