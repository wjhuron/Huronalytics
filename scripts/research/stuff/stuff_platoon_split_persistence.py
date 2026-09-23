#!/usr/bin/env python3
"""stuff_platoon_split_persistence.py — is a pitcher's Stuff+ platoon split
a pitcher-specific grade, or only the pitch-type average?

Question (Wally, 2026-09-23). The card shows Stuff+ vs LHH and vs RHH. The
same-hand gap is real on average (stuff_platoon_location_fixed.py), but most
of any one pitcher's gap is the average for his pitch type. Does the part of
the split that is HIS predict his real split next season?

Protocol (the Stuff+ gate v2 replicate design). For each pair (Y, Y+1),
Y = 2021..2025, the SHIPPED config is fit on every season except Y and Y+1,
then every Y pitch is scored at platoon_same = 1 and = 0. Unit u = (pitcher,
throws, pitch_type).

  G(u)   predicted split in season Y: mean over u's Y pitches of
         pred(opp) - pred(same)   (pitcher-positive credit for same-hand)
  A(u)   realized split: mean target vs opp - mean target vs same
         (pitcher-positive), in Y+1 (outcome) and in Y (benchmark)

Both are demeaned within (pair, pitch_type, throws), so only the part beyond
the pitch-type-and-hand average is left. Weighted (w = 1 / (1/n_same +
1/n_opp) in Y+1, the inverse noise variance of A) slope and r of
A_dm(Y+1) on G_dm(Y). A calibrated pitcher-specific grade has slope 1. The
benchmark A_dm(Y) -> A_dm(Y+1) says how much real split persists at all.

Targets: 'raw' = target_xrv (the Stuff+ label, the gate's objective);
'adj' = target_xrv - l_loc (the pitcher's location deviation removed, the
gate's secondary). Points use season-Y anchor SDs (10 * gap / sd_t).

Pitcher-bootstrap SE (pitchers resampled across all pairs jointly). The
(2025, 2026) pair targets a partial season and is reported with and without.

Per-pair predictions cache to data/_platoon_split/pred_{Y}.pkl; delete to
refit. Output: data/_platoon_split/results.json. Run from the repo root.
`--identity 5` is the strict version (own pitcher removed from every
training season); it writes the same files with an `_identity5` suffix.
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
OUT_DIR = os.path.join(ROOT, 'data', '_platoon_split')
MIN_SIDE = 40             # pitches per side for a realized split
MIN_UNIT_Y = G.ANCHOR_MIN  # 50: unit pitches in Y for a predicted split
BOOT_B = 2000
SEED = 0
TYPES = ['FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS']


IDENTITY = 0             # --identity K: pitcher-grouped folds (see fit_pair)
SUFFIX = ''


def pred_path(Y):
    return os.path.join(OUT_DIR, f'pred{SUFFIX}_{Y}.pkl')


def _fit(Xtr, ytr):
    params = T._params_for(Xtr)
    params['monotone_constraints'] = tuple(
        -1 if c == T.MONO_FEAT else 0 for c in Xtr.columns)
    params['random_state'] = SEED
    m = xgb.XGBRegressor(**params)
    m.fit(Xtr, ytr)
    return m


def fit_pair(Y, Y1, frames):
    """IDENTITY > 0: the Y pitchers are split into K folds, and each fold's
    pitchers leave EVERY training season before the fit that scores them
    (gate v2 'identity'), so a pitcher's own outcomes in other seasons
    cannot teach the model his split."""
    train_years = [y for y in G.SEASONS if y not in (Y, Y1)]
    t0 = time.time()
    slopes = G.fit_vaa_slopes([frames[y] for y in train_years])
    P = {y: G.prepare(frames[y], slopes) for y in train_years + [Y]}
    feats = G.variant_feats({})
    Xtr = pd.concat([G.design(P[y], {}, feats) for y in train_years],
                    ignore_index=True)
    ytr = np.concatenate([P[y]['target_xrv'].values for y in train_years])
    ptr = np.concatenate([P[y]['pitcher'].values for y in train_years])
    dY = P[Y]
    XY = G.design(dY, {}, feats)
    if IDENTITY:
        pits = np.array(sorted(dY['pitcher'].unique()))
        rng = np.random.default_rng(1000 + SEED)
        fold_of = dict(zip(pits, rng.permutation(len(pits)) % IDENTITY))
        fy = dY['pitcher'].map(fold_of).values
        ftr = np.array([fold_of.get(p, -1) for p in ptr])
        folds = [(ftr != k, fy == k) for k in range(IDENTITY)]
    else:
        folds = [(np.ones(len(ytr), bool), np.ones(len(dY), bool))]
    pa = np.full(len(dY), np.nan)
    p0 = np.full(len(dY), np.nan)
    p1 = np.full(len(dY), np.nan)
    for keep, sc in folds:
        m = _fit(Xtr[keep], ytr[keep])
        Xs = XY[sc].copy()
        pa[sc] = m.predict(Xs)
        Xs['platoon_same'] = 0
        p0[sc] = m.predict(Xs)
        Xs['platoon_same'] = 1
        p1[sc] = m.predict(Xs)
        print(f'    fold: train {int(keep.sum())} rows, {int(sc.sum())} scored '
              f'[{time.time() - t0:.0f}s]', flush=True)
        del m
        gc.collect()
    del Xtr, ytr
    gc.collect()
    out = pd.DataFrame({
        'pitcher': dY['pitcher'].values, 'throws': dY['throws'].values,
        'pitch_type': dY['pitch_type'].values,
        'platoon_same': dY['platoon_same'].values,
        'stuff': -pa, 'gap': (p0 - p1).astype('float64'),
    })
    del P, XY
    gc.collect()
    print(f'  pair {Y}->{Y1}: fit on {train_years}, {len(out)} Y pitches '
          f'scored [{time.time() - t0:.0f}s]', flush=True)
    return out


def realized(d, tcol):
    """Per unit: pitcher-positive realized split and side counts."""
    x = d[['pitcher', 'throws', 'pitch_type', 'platoon_same', tcol]].dropna()
    g = x.groupby(['pitcher', 'throws', 'pitch_type', 'platoon_same'])[tcol].agg(['mean', 'size'])
    g = g.unstack('platoon_same')
    A = g[('mean', 0)] - g[('mean', 1)]
    return pd.DataFrame({'A': A, 'n_same': g[('size', 1)], 'n_opp': g[('size', 0)]})


def wstats(x, y, w):
    """Weighted slope of y on x and weighted r (inputs already demeaned)."""
    sxx = np.sum(w * x * x)
    syy = np.sum(w * y * y)
    sxy = np.sum(w * x * y)
    return sxy / sxx, sxy / np.sqrt(sxx * syy)


def demean(df, cols, by):
    out = df.copy()
    for c in cols:
        wm = (out[c] * out['w']).groupby([out[k] for k in by]).transform('sum') \
            / out['w'].groupby([out[k] for k in by]).transform('sum')
        out[c] = out[c] - wm
    return out


def boot(df, fn, B=BOOT_B, seed=7):
    pits = df['pitcher'].unique()
    idx = {p: np.flatnonzero(df['pitcher'].values == p) for p in pits}
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(B):
        take = np.concatenate([idx[p] for p in rng.choice(pits, len(pits))])
        vals.append(fn(df.iloc[take]))
    return np.nanstd(np.array(vals), axis=0)


def main():
    global IDENTITY, SUFFIX
    if '--identity' in sys.argv:
        IDENTITY = int(sys.argv[sys.argv.index('--identity') + 1])
        SUFFIX = f'_identity{IDENTITY}'
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    frames = {y: G.load_frame(y) for y in G.SEASONS}
    G.set_arm_side_sign(list(frames.values()))
    for y, d in frames.items():
        d['target_adj'] = d['target_xrv'] - d['l_loc']
        print(f'  {y}: l_loc on {d["l_loc"].notna().mean():.1%} of rows', flush=True)

    units = []
    for Y, Y1 in G.PAIRS:
        if os.path.exists(pred_path(Y)):
            pr = pd.read_pickle(pred_path(Y))
            print(f'  pair {Y}->{Y1}: cached predictions', flush=True)
        else:
            pr = fit_pair(Y, Y1, frames)
            pr.to_pickle(pred_path(Y))
        anc = G.anchors_for(pr)                 # (mu, sd, nqual) per type, season Y
        sd = {k: v[1] for k, v in anc.items()}
        gp = pr.groupby(['pitcher', 'throws', 'pitch_type'])['gap'].agg(G_='mean', n_y='size')
        for tname, tcol in (('raw', 'target_xrv'), ('adj', 'target_adj')):
            a1 = realized(frames[Y1], tcol).add_suffix('_1')
            a0 = realized(frames[Y], tcol).add_suffix('_0')
            u = gp.join(a1, how='inner').join(a0, how='left').reset_index()
            u = u[(u['n_y'] >= MIN_UNIT_Y) & (u['n_same_1'] >= MIN_SIDE)
                  & (u['n_opp_1'] >= MIN_SIDE) & u['pitch_type'].isin(TYPES)]
            conv = 10.0 / u['pitch_type'].map(sd).astype(float)
            u = u.assign(G=u['G_'] * conv, A1=u['A_1'] * conv, A0=u['A_0'] * conv,
                         w=1.0 / (1.0 / u['n_same_1'] + 1.0 / u['n_opp_1']),
                         pair=Y, target=tname)
            units.append(u[['pitcher', 'throws', 'pitch_type', 'pair', 'target',
                            'G', 'A1', 'A0', 'n_same_0', 'n_opp_0',
                            'n_same_1', 'n_opp_1', 'w']])
        del pr
        gc.collect()
    U = pd.concat(units, ignore_index=True)
    U.to_pickle(os.path.join(OUT_DIR, f'units{SUFFIX}.pkl'))

    res = {'identity': IDENTITY, 'min_side': MIN_SIDE, 'min_unit_y': MIN_UNIT_Y, 'seed': SEED, 'results': {}}
    lines = []
    for tname in ('raw', 'adj'):
        for base_name, by in (('type_hand', ['pair', 'pitch_type', 'throws']),
                              ('type', ['pair', 'pitch_type'])):
            for scope, pairs in (('all', [2021, 2022, 2023, 2024, 2025]),
                                 ('full_seasons', [2021, 2022, 2023, 2024])):
                u = U[(U['target'] == tname) & U['pair'].isin(pairs)]
                ub = u[(u['n_same_0'] >= MIN_SIDE) & (u['n_opp_0'] >= MIN_SIDE)]
                u = demean(u, ['G', 'A1'], by)
                ub = demean(ub, ['G', 'A1', 'A0'], by)

                def f_pred(df):
                    return np.array(wstats(df['G'].values, df['A1'].values, df['w'].values))

                def f_bench(df):
                    return np.array(wstats(df['A0'].values, df['A1'].values, df['w'].values))

                sp, rp = f_pred(u)
                se_sp, se_rp = boot(u, f_pred)
                sb, rb = f_bench(ub)
                se_sb, se_rb = boot(ub, f_bench)
                sdG = float(np.sqrt(np.average(u['G'] ** 2, weights=u['w'])))
                sdA = float(np.sqrt(np.average(u['A1'] ** 2, weights=u['w'])))
                per_pair = {}
                for y in pairs:
                    q = u[u['pair'] == y]
                    per_pair[str(y)] = dict(zip(('slope', 'r'), map(float, f_pred(q))))
                per_type = {}
                for t in TYPES:
                    q = u[u['pitch_type'] == t]
                    if len(q) >= 30:
                        s_, r_ = f_pred(q)
                        se_s, se_r = boot(q, f_pred, B=500)
                        per_type[t] = {'n': int(len(q)), 'slope': float(s_),
                                       'slope_se': float(se_s), 'r': float(r_),
                                       'r_se': float(se_r),
                                       'sd_G': float(np.sqrt(np.average(q['G'] ** 2, weights=q['w'])))}
                key = f'{tname}|{base_name}|{scope}'
                res['results'][key] = {
                    'n_units': int(len(u)), 'n_pitchers': int(u['pitcher'].nunique()),
                    'pred_slope': float(sp), 'pred_slope_se': float(se_sp),
                    'pred_r': float(rp), 'pred_r_se': float(se_rp),
                    'bench_n': int(len(ub)),
                    'bench_slope': float(sb), 'bench_slope_se': float(se_sb),
                    'bench_r': float(rb), 'bench_r_se': float(se_rb),
                    'sd_G_pts': sdG, 'sd_A1_pts': sdA,
                    'per_pair': per_pair, 'per_type': per_type,
                }
                lines.append(f'{key:<28} n {len(u):5d} | model split -> next: slope '
                             f'{sp:5.2f} ({se_sp:.2f}) r {rp:.3f} ({se_rp:.3f}) | '
                             f'real split -> next: slope {sb:5.2f} ({se_sb:.2f}) '
                             f'r {rb:.3f} ({se_rb:.3f}) | sd model {sdG:.1f} pts, '
                             f'sd real {sdA:.1f}')
                print(lines[-1], flush=True)
                dst = os.path.join(OUT_DIR, f'results{SUFFIX}.json')
                json.dump(res, open(dst + '.tmp', 'w'), indent=1)
                os.replace(dst + '.tmp', dst)
    print(f'\ndone [{time.time() - t0:.0f}s]')


if __name__ == '__main__':
    main()
