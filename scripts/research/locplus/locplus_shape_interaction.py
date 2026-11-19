#!/usr/bin/env python3
"""locplus_shape_interaction.py — does the value of a LOCATION depend on the pitch's SHAPE?

Loc+ surfaces know the pitch group, the hands and the count. Inside a group every
pitch at one spot gets one value: a 19-inch-ride four-seamer and a 13-inch one, a
gyro slider and a sweeper. This screen asks how much value that leaves out.

Data: the Stuff+ gate frames (data/_gate_v2/season_{Y}.pkl + sidecar), which hold
location, shape and count on one row. plate_z is in feet, NOT zone-normalized (the
frames keep no batter zone), so this is a screen, not a Loc+ replacement.

Four xgboost models on the luck-neutral target, each fit on ONE season and scored
on an ADJACENT season (10 ordered pairs, 2021-2026), so no pitch scores itself:
  SHP    shape + situation                       E[value | shape, situation]
  LOC    location + situation                    what a surface can know
  ADD    location + shape + situation, with location x shape interactions FORBIDDEN
         (interaction constraints)               shape shifts the level only
  JOINT  the same features, no constraint        the spot's value may depend on shape
The shape-dependent location value is ADD -> JOINT. Squared error, paired per
pitch, by Loc+ group; pairs won.

Pitcher level (each season scored once): location value = model minus SHP, then
minus its mean for the (group, hands, count) cell, as Loc+ does.
  lvA = ADD - SHP,  lvJ = JOINT - SHP,  delta = lvJ - lvA
Units = pitcher x pitch type, 300+ pitches. r(lvA, lvJ), SD of delta against SD of
lvA, odd/even-date reliability of each, and delta's persistence to the next season.
If delta is small or does not repeat, a shape-aware surface changes no grade.

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/locplus_shape_interaction.py
  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/locplus_shape_interaction.py pairs     # stage 2, see stage2()
"""
import gc
import json
import os
import sys

import numpy as np
import pandas as pd
import xgboost as xgb

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
import pipeline.locplus as lp  # noqa: E402

GATE = os.path.join(ROOT, 'data', '_gate_v2')
OUT = os.path.join(ROOT, 'data', '_loc_shape_interaction.json')
YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
LOCF = ['px_b', 'plate_z']
SIT = ['balls', 'strikes', 'grp', 'platoon_same', 'is_lhp']
SHAPE = ['velocity', 'ivb', 'hb_as', 'arm_angle', 'rel_z', 'extension']
PARAMS = dict(max_depth=6, n_estimators=500, learning_rate=0.05, min_child_weight=50, reg_lambda=1.5,
              subsample=0.8, colsample_bytree=0.8, n_jobs=-1, tree_method='hist', random_state=0)
GROUPS = ('FF', 'SI', 'FC', 'SL', 'CU', 'CH')
MIN_UNIT = 300


def load(y):
    d = pd.read_pickle(os.path.join(GATE, f'season_{y}.pkl'))
    sc = pd.read_pickle(os.path.join(GATE, f'sidecar_{y}.pkl'))
    if len(sc) != len(d):
        sys.exit(f'{y}: sidecar rows {len(sc)} != frame rows {len(d)}')
    d = d[['pitcher', 'throws', 'date', 'pitch_type', 'platoon_same', 'target_xrv', 'velocity', 'ivb', 'hb',
           'arm_angle', 'rel_z', 'extension', 'plate_x', 'plate_z', 'vaa_raw', 'haa_meas']].copy()
    d['balls'], d['strikes'] = sc['balls'].values, sc['strikes'].values
    d['is_lhp'] = (d['throws'] == 'L').astype('float32')
    bats_r = ((d['is_lhp'] == 0) == (d['platoon_same'] == 1))        # RHP + same hand, or LHP + opposite hand
    d['px_b'] = (d['plate_x'] * np.where(bats_r, 1.0, -1.0)).astype('float32')   # the same sign = the same side of the batter
    d['hb_as'] = (d['hb'] * np.where(d['is_lhp'] == 1, -1.0, 1.0)).astype('float32')
    gname = d['pitch_type'].map(lp.group_of_code)
    d['gname'] = gname
    d['grp'] = gname.map({g: i for i, g in enumerate(GROUPS)}).astype('float32')
    ok = d['target_xrv'].notna() & d['plate_x'].notna() & d['plate_z'].notna() & d['balls'].notna() & d['grp'].notna()
    d = d[ok].reset_index(drop=True)
    d['season'] = y
    return d


def fit_predict(tr, te, feats, constraints=None):
    p = dict(PARAMS)
    if constraints:
        p['interaction_constraints'] = [list(grp) for grp in constraints]     # feature NAMES: the fit takes a DataFrame
    m = xgb.XGBRegressor(**p)
    m.fit(tr[feats].astype('float32'), tr['target_xrv'].values)
    out = m.predict(te[feats].astype('float32'))
    del m
    return out


def score(tr, te):
    allf = LOCF + SHAPE + SIT
    return {'SHP': fit_predict(tr, te, SHAPE + SIT), 'LOC': fit_predict(tr, te, LOCF + SIT),
            'ADD': fit_predict(tr, te, allf, [LOCF + SIT, SHAPE + SIT]), 'JOINT': fit_predict(tr, te, allf)}


def rel(d, col, keys):
    half = (pd.to_datetime(d['date']).dt.dayofyear % 2).values
    a = d[half == 0].groupby(keys)[col].agg(['mean', 'size'])
    b = d[half == 1].groupby(keys)[col].agg(['mean', 'size'])
    j = a.join(b, lsuffix='_a', rsuffix='_b', how='inner')
    j = j[(j['size_a'] >= MIN_UNIT / 2) & (j['size_b'] >= MIN_UNIT / 2)]
    return float(np.corrcoef(j['mean_a'], j['mean_b'])[0, 1]), len(j)


def main():
    D = {y: load(y) for y in YEARS}
    pairs = [(a, b) for a in YEARS for b in YEARS if abs(a - b) == 1]
    fit_rows, units, kept = [], {}, {}
    for a, b in pairs:
        te = D[b]
        P = score(D[a], te)
        t = te['target_xrv'].values
        se = {k: (v - t) ** 2 for k, v in P.items()}
        var = float(((t - t.mean()) ** 2).mean())
        rec = {'pair': f'{a}->{b}', 'n': len(te), 'r2': {k: 1 - float(v.mean()) / var for k, v in se.items()}}
        dj = se['JOINT'] - se['ADD']
        rec['joint_minus_add'] = (float(dj.mean()), float(dj.std() / np.sqrt(len(dj))))
        rec['by_group'] = {}
        for g in GROUPS:
            m = (te['gname'] == g).values
            rec['by_group'][g] = (float(dj[m].mean()), float(dj[m].std() / np.sqrt(m.sum())), int(m.sum()),
                                  float((se['ADD'][m] - se['LOC'][m]).mean()))
        fit_rows.append(rec)
        print(f'{a}->{b}: R2 ' + ' '.join(f'{k} {v:.5f}' for k, v in rec['r2'].items())
              + f' | JOINT-ADD sq err {dj.mean() * 1e4:+.3f}e-4 (se {dj.std() / np.sqrt(len(dj)) * 1e4:.3f})', flush=True)
        if b not in kept and (a == b - 1 or b == YEARS[0]):
            cell = ['gname', 'platoon_same', 'is_lhp', 'balls', 'strikes']
            u = te[['pitcher', 'pitch_type', 'date', 'gname', 'season'] + cell[1:]].copy()
            u['lvA'] = P['ADD'] - P['SHP']
            u['lvJ'] = P['JOINT'] - P['SHP']
            for c in ('lvA', 'lvJ'):
                u[c] = u[c] - u.groupby(cell)[c].transform('mean')
            u['delta'] = u['lvJ'] - u['lvA']
            kept[b] = u
        del P, se
        gc.collect()
    out = {'pairs': fit_rows}
    print('\n== pitch level, JOINT minus ADD squared error (negative = the spot value depends on shape), 10 pairs')
    for g in ('ALL',) + GROUPS:
        if g == 'ALL':
            v = [r['joint_minus_add'][0] for r in fit_rows]
        else:
            v = [r['by_group'][g][0] for r in fit_rows]
        v = np.array(v)
        z = v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))
        out[f'fit_{g}'] = {'mean': float(v.mean()), 'wins': int((v < 0).sum()), 'z': float(z)}
        print(f'  {g:>4s}  {v.mean() * 1e4:+.3f}e-4   JOINT wins {int((v < 0).sum())}/{len(v)}   z across pairs {z:+.1f}')
    r2 = {k: float(np.mean([r['r2'][k] for r in fit_rows])) for k in ('SHP', 'LOC', 'ADD', 'JOINT')}
    out['r2'] = r2
    print('  mean held-out R2: ' + '  '.join(f'{k} {v:.5f}' for k, v in r2.items()))

    print('\n== pitcher x pitch type units (300+ pitches), location value in runs per 100')
    U = pd.concat(kept.values(), ignore_index=True)
    keys = ['season', 'pitcher', 'pitch_type']
    g = U.groupby(keys).agg(lvA=('lvA', 'mean'), lvJ=('lvJ', 'mean'), delta=('delta', 'mean'), n=('lvA', 'size'),
                            gname=('gname', 'first'))
    g = g[g['n'] >= MIN_UNIT]
    res = {}
    for grp in ('ALL',) + GROUPS:
        s = g if grp == 'ALL' else g[g['gname'] == grp]
        Us = U if grp == 'ALL' else U[U['gname'] == grp]
        rA, nA = rel(Us, 'lvA', keys)
        rJ, _ = rel(Us, 'lvJ', keys)
        rD, _ = rel(Us, 'delta', keys)
        nx = s['delta'].reset_index()
        nx2 = nx.assign(season=nx['season'] - 1)
        pj = nx.merge(nx2, on=keys, suffixes=('', '_next'))
        pers = float(np.corrcoef(pj['delta'], pj['delta_next'])[0, 1]) if len(pj) > 30 else float('nan')
        res[grp] = {'units': len(s), 'r_A_J': float(np.corrcoef(s['lvA'], s['lvJ'])[0, 1]), 'sd_A': float(s['lvA'].std() * 100),
                    'sd_J': float(s['lvJ'].std() * 100), 'sd_delta': float(s['delta'].std() * 100), 'half_A': rA, 'half_J': rJ,
                    'half_delta': rD, 'half_units': nA, 'delta_next_season_r': pers, 'pairs_next': len(pj)}
        r = res[grp]
        print(f'  {grp:>4s} units {r["units"]:>5d}  r(lvA, lvJ) {r["r_A_J"]:.3f}  SD lvA {r["sd_A"]:.3f} lvJ {r["sd_J"]:.3f} delta {r["sd_delta"]:.3f}'
              f'  | odd/even r: lvA {rA:.3f} lvJ {rJ:.3f} delta {rD:.3f}  | delta next-season r {pers:.3f} (n {len(pj)})')
    out['units'] = res
    tmp = OUT + '.tmp'
    json.dump(out, open(tmp, 'w'), indent=1)
    os.replace(tmp, OUT)
    print(f'\nwrote {OUT}')


def stage2():
    """One model for both seasons of a pair, fit on the OTHER four seasons (the Stuff+ gate's
    rule), so a unit's value in Y and in Y+1 come from the same surface and from no pitch of
    either season. Units = pitcher x pitch type, 300+ pitches in both seasons.
      persistence   r(value Y, value Y+1) for lvA, lvJ and delta
      validity      r(value Y, RESULT Y+1), where the result is the unit mean of the target minus
                    SHP (what shape and situation do not explain), cell-demeaned like the values
    Paired unit bootstrap for lvJ minus lvA. This decides whether the shape term is a pitcher
    trait that a grade can use, which the pitch-level fit alone cannot show."""
    D = {y: load(y) for y in YEARS}
    cell = ['gname', 'platoon_same', 'is_lhp', 'balls', 'strikes']
    keys = ['pitcher', 'pitch_type']
    rng = np.random.default_rng(0)
    out, pooled = {}, []
    for Y in YEARS[:-1]:
        tr = pd.concat([D[y] for y in YEARS if y not in (Y, Y + 1)], ignore_index=True)
        tabs = {}
        for y in (Y, Y + 1):
            te = D[y]
            P = score(tr, te)
            u = te[keys + cell].copy()
            u['lvA'], u['lvJ'] = P['ADD'] - P['SHP'], P['JOINT'] - P['SHP']
            u['res'] = te['target_xrv'].values - P['SHP']
            for c in ('lvA', 'lvJ', 'res'):
                u[c] = u[c] - u.groupby(cell)[c].transform('mean')
            u['delta'] = u['lvJ'] - u['lvA']
            g = u.groupby(keys).agg(lvA=('lvA', 'mean'), lvJ=('lvJ', 'mean'), delta=('delta', 'mean'), res=('res', 'mean'),
                                    n=('lvA', 'size'), gname=('gname', 'first'))
            tabs[y] = g[g['n'] >= MIN_UNIT]
            del P
        del tr
        gc.collect()
        j = tabs[Y].join(tabs[Y + 1], lsuffix='_y', rsuffix='_n', how='inner')
        j['pair'] = Y
        pooled.append(j)
        c = lambda a, b: float(np.corrcoef(j[a], j[b])[0, 1])
        out[str(Y)] = {'units': len(j), 'pers_A': c('lvA_y', 'lvA_n'), 'pers_J': c('lvJ_y', 'lvJ_n'), 'pers_delta': c('delta_y', 'delta_n'),
                       'val_A': c('lvA_y', 'res_n'), 'val_J': c('lvJ_y', 'res_n'), 'val_delta': c('delta_y', 'res_n')}
        r = out[str(Y)]
        print(f'{Y}->{Y + 1}: units {r["units"]}  persistence lvA {r["pers_A"]:.3f} lvJ {r["pers_J"]:.3f} delta {r["pers_delta"]:.3f}'
              f'  | next-season result r: lvA {r["val_A"]:.3f} lvJ {r["val_J"]:.3f} delta {r["val_delta"]:.3f}', flush=True)
    J = pd.concat(pooled)
    print('\n== pooled over five pairs; r is positive when a HIGHER (worse for the pitcher) value is followed by worse results')
    res = {}
    for grp in ('ALL',) + GROUPS:
        s = J if grp == 'ALL' else J[J['gname_y'] == grp]
        if len(s) < 60:
            continue
        ix = rng.integers(0, len(s), size=(2000, len(s)))
        v = {k: s[k].values for k in ('lvA_y', 'lvJ_y', 'lvA_n', 'lvJ_n', 'delta_y', 'delta_n', 'res_n')}
        cr = lambda a, b, i=None: float(np.corrcoef(v[a] if i is None else v[a][i], v[b] if i is None else v[b][i])[0, 1])
        dval = [cr('lvJ_y', 'res_n', i) - cr('lvA_y', 'res_n', i) for i in ix]
        dper = [cr('lvJ_y', 'lvJ_n', i) - cr('lvA_y', 'lvA_n', i) for i in ix]
        res[grp] = {'units': len(s), 'pers_A': cr('lvA_y', 'lvA_n'), 'pers_J': cr('lvJ_y', 'lvJ_n'), 'pers_delta': cr('delta_y', 'delta_n'),
                    'val_A': cr('lvA_y', 'res_n'), 'val_J': cr('lvJ_y', 'res_n'), 'val_delta': cr('delta_y', 'res_n'),
                    'val_J_minus_A': cr('lvJ_y', 'res_n') - cr('lvA_y', 'res_n'), 'val_se': float(np.std(dval)),
                    'pers_J_minus_A': cr('lvJ_y', 'lvJ_n') - cr('lvA_y', 'lvA_n'), 'pers_se': float(np.std(dper)),
                    'pairs_J_wins_val': int(sum(out[str(Y)]['val_J'] > out[str(Y)]['val_A'] for Y in YEARS[:-1])) if grp == 'ALL' else None}
        r = res[grp]
        print(f'  {grp:>4s} units {r["units"]:>5d}  persistence lvA {r["pers_A"]:.3f} lvJ {r["pers_J"]:.3f} (J-A {r["pers_J_minus_A"]:+.3f}, se {r["pers_se"]:.3f}) '
              f'delta {r["pers_delta"]:.3f}  | result r: lvA {r["val_A"]:.3f} lvJ {r["val_J"]:.3f} (J-A {r["val_J_minus_A"]:+.3f}, se {r["val_se"]:.3f}) delta {r["val_delta"]:.3f}')
    fn = OUT.replace('.json', '_stage2.json')
    json.dump({'pairs': out, 'pooled': res}, open(fn + '.tmp', 'w'), indent=1)
    os.replace(fn + '.tmp', fn)
    print(f'\nwrote {fn}')


def which():
    """Which shape variable carries the location x shape gain? Five forward pairs (fit on Y,
    score Y+1). Between ADD and JOINT, one model per candidate lets ONLY that variable interact
    with location. Two more candidates are not shape columns: the measured approach angles
    (vaa_raw, haa_meas), which a location and a shape produce together. Reported per Loc+ group:
    the share of the ADD -> JOINT squared-error gain that the candidate alone recovers."""
    D = {y: load(y) for y in YEARS}
    allf = LOCF + SHAPE + SIT
    cands = {f: (allf, [LOCF + SIT + [f], SHAPE + SIT]) for f in SHAPE}
    for f in ('vaa_raw', 'haa_meas'):
        cands[f] = (allf + [f], [LOCF + SIT + [f], SHAPE + SIT])
    cands['vaa+haa'] = (allf + ['vaa_raw', 'haa_meas'], [LOCF + SIT + ['vaa_raw', 'haa_meas'], SHAPE + SIT])
    acc = {}
    for Y in YEARS[:-1]:
        tr, te = D[Y], D[Y + 1]
        t = te['target_xrv'].values
        add = (fit_predict(tr, te, allf, [LOCF + SIT, SHAPE + SIT]) - t) ** 2
        joint = (fit_predict(tr, te, allf) - t) ** 2
        se = {k: (fit_predict(tr, te, fs, cs) - t) ** 2 for k, (fs, cs) in cands.items()}
        for g in ('ALL',) + GROUPS:
            m = np.ones(len(te), bool) if g == 'ALL' else (te['gname'] == g).values
            a = acc.setdefault(g, {'full': [], **{k: [] for k in cands}})
            a['full'].append(float((add[m] - joint[m]).mean()))
            for k in cands:
                a[k].append(float((add[m] - se[k][m]).mean()))
        print(f'{Y}->{Y + 1} done', flush=True)
        del add, joint, se
        gc.collect()
    print('\nsquared-error gain over ADD, e-4 (mean of five pairs; pairs with a gain). JOINT = every shape column free')
    print(f'{"":>5s}{"JOINT":>14s}' + ''.join(f'{k:>14s}' for k in cands))
    out = {}
    for g, a in acc.items():
        row = f'{g:>5s}{np.mean(a["full"]) * 1e4:>10.3f} {sum(x > 0 for x in a["full"])}/5'
        for k in cands:
            row += f'{np.mean(a[k]) * 1e4:>10.3f} {sum(x > 0 for x in a[k])}/5'
        print(row)
        out[g] = {k: (float(np.mean(v)), int(sum(x > 0 for x in v))) for k, v in a.items()}
    fn = OUT.replace('.json', '_which.json')
    json.dump(out, open(fn + '.tmp', 'w'), indent=1)
    os.replace(fn + '.tmp', fn)
    print(f'wrote {fn}')


if __name__ == '__main__':
    {'pairs': stage2, 'which': which}.get(sys.argv[1] if len(sys.argv) > 1 else '', main)()
