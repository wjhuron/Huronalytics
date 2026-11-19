#!/usr/bin/env python3
"""xmove_physics_fit.py — per-pitch physics expected movement, tuned on its own objective.

Wally, 2026-11-19: "why do i care about whiffs? the only thing I am looking for here is what
the expected movement should be based on velocity, spin rate, spin axis, release point."
So the objective is not the results test. It is how well the model predicts the MOVEMENT of
pitches from pitchers it never saw (pitcher folds), with inputs measured before the ball
moves. No pitch type and no pitcher grouping enter the model.

Objective (decides everything here): held-out 2D miss, RMSE in inches over all pitches,
  sqrt(mean((IVB - xIVB)^2 + (HB - xHB)^2)).  Lower is better.  It cannot be gamed by the
  directions searched: every input is pre-movement, and a pitcher's own pitches are never in
  the model that scores him.  The movement-inferred axis (OTilt) and spin efficiency are
  calculated FROM the movement and are never inputs.
Diagnostics: R^2 for ride and run over all pitches, mean within-type R^2, median miss.
Comparisons carry a pitcher bootstrap (pitchers resampled, paired).

Modes:
  time                     one fit, to size the job
  sweep  [seasons]         step 1: leaves x min-leaf x iterations, base inputs (dev seasons)
  inputs LEAVES MSL ITERS  step 2: each added or removed input against the base, at the chosen settings
  final  LEAVES MSL ITERS FORM   step 3: the chosen model on every season 2021-2026, five pitcher
                           folds, against the copied settings and neighbours of the chosen ones

  XMOVE_DIR=/scratch PYTHONHASHSEED=0 .venv/bin/python scripts/research/xmove/xmove_physics_fit.py sweep
"""
import json
import os
import pickle
import sys
import time
import zlib

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
_argv = sys.argv[:]
sys.argv = sys.argv[:1]
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import xmove_hitter_basis_candidates as HC  # noqa: E402
sys.argv = _argv

OUTDIR = os.path.join(ROOT, 'data', '_xmove_physics_fit')
PTS = ['FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS']
BASE = ['velo', 'spin', 'ct', 'st', 'aa', 'ext']
FORMS = {
    'base': BASE,
    '+ release point': BASE + ['rz', 'rx_s'],
    '+ spin/velo': BASE + ['spin_v'],
    '+ axis angle': BASE + ['th'],
    '+ velo vs own top': BASE + ['dv'],
    '+ relpt, velo vs own top': BASE + ['rz', 'rx_s', 'dv'],
    '- slot': ['velo', 'spin', 'ct', 'st', 'ext'],
    '- extension': ['velo', 'spin', 'ct', 'st', 'aa'],
    '- slot, + release point': ['velo', 'spin', 'ct', 'st', 'ext', 'rz', 'rx_s'],
    'spin and velo only': ['velo', 'spin', 'ct', 'st'],
}
COPIED = (31, 200, 300, 0.06)        # the settings the plates used, never tuned
LR = 0.1
STAGES = (100, 200, 400, 800)
DEV = (2022, 2024)
NB = 300


def build(df, th, s):
    A = dict(pt=df['Pitch Type'].values, thr=df['Throws'].values, pitcher=df['Pitcher'].astype(str).values,
             ivb=df['xIndVrtBrk'].values.astype('f8'), hb_s=df['xHorzBrk'].values.astype('f8') * s,
             velo=df['Velocity'].values.astype('f8'), spin=df['Spin Rate'].values.astype('f8'),
             aa=df['ArmAngle'].values.astype('f8'), ext=df['Extension'].values.astype('f8'),
             rz=df['RelPosZ'].values.astype('f8'), rx_s=df['RelPosX'].values.astype('f8') * s,
             ct=np.cos(th), st=np.sin(th), th=th)
    A['spin_v'] = A['spin'] / A['velo']
    A['dv'] = A['velo'] - pd.Series(A['velo']).groupby(A['pitcher']).transform(lambda v: v.quantile(0.95)).values
    A['is_l'] = (A['thr'] == 'L').astype('f8')
    A['crc'] = np.array([zlib.crc32(p.encode()) for p in A['pitcher']])
    return A


def season(y):
    need = ['xIndVrtBrk', 'xHorzBrk', 'Velocity', 'Spin Rate', 'ArmAngle', 'Extension', 'RelPosZ', 'RelPosX']
    if y == 2026:
        with open(f'{ROOT}/data/all_pitches_rs_cache.pkl', 'rb') as fh:
            rows = pickle.load(fh)
        keep = ['Pitcher', 'Throws', 'Pitch Type', '_source', 'RTilt'] + need
        df = pd.DataFrame([{k: r.get(k) for k in keep} for r in rows])
        del rows
        df = df[df['_source'].fillna('MLB') == 'MLB']
        for c in need:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        import xmove_cavalli_proto as CP
        df['axis'] = df['RTilt'].map(CP.clock_to_deg)
        df = df[df['Pitch Type'].isin(PTS) & df['Throws'].isin(['L', 'R'])].dropna(subset=need + ['axis']).reset_index(drop=True)
        s = np.where(df['Throws'] == 'R', 1.0, -1.0)
        return build(df, np.radians(df['axis'].values.astype('f8') * s), s)
    df = HC.load(y)
    df = df[df['Pitch Type'].isin(PTS) & df['Throws'].isin(['L', 'R'])].dropna(subset=need + ['SpinAxis']).reset_index(drop=True)
    s = np.where(df['Throws'] == 'R', 1.0, -1.0)
    return build(df, np.radians(((df['SpinAxis'].values.astype('f8') - 180.0) % 360.0) * s), s)


def fit_predict(A, feats, leaves, msl, iters, lr, nfold, stages=None, hands='split'):
    """Held-out-pitcher predictions. Returns {stage: (xi, xh)}; stage = number of boosting rounds."""
    from sklearn.ensemble import HistGradientBoostingRegressor as H
    stages = tuple(stages or (iters,))
    n = len(A['ivb'])
    out = {st: (np.full(n, np.nan), np.full(n, np.nan)) for st in stages}
    cols = list(feats) + (['is_l'] if hands == 'flag' else [])
    X = np.column_stack([A[c] for c in cols])
    fold = A['crc'] % nfold
    parts = [A['thr'] == 'L', A['thr'] == 'R'] if hands == 'split' else [np.ones(n, bool)]
    for part in parts:
        for f in range(nfold):
            tr, te = np.where(part & (fold != f))[0], np.where(part & (fold == f))[0]
            for j, tgt in enumerate(('ivb', 'hb_s')):
                m = H(max_iter=max(stages), learning_rate=lr, max_leaf_nodes=leaves, min_samples_leaf=msl, early_stopping=False, random_state=0)
                m.fit(X[tr], A[tgt][tr])
                if len(stages) == 1:
                    out[stages[0]][j][te] = m.predict(X[te])
                else:
                    for i, p in enumerate(m.staged_predict(X[te]), 1):
                        if i in out:
                            out[i][j][te] = p
    return out


def metrics(A, xi, xh):
    oi, oh = A['ivb'] - xi, A['hb_s'] - xh
    sq = oi ** 2 + oh ** 2
    wi, wh = [], []
    key = pd.Series(A['pt']) + A['thr']
    for _, ix in pd.Series(np.arange(len(oi))).groupby(key.values):
        ix = ix.values
        wi.append(1 - (oi[ix] ** 2).sum() / ((A['ivb'][ix] - A['ivb'][ix].mean()) ** 2).sum())
        wh.append(1 - (oh[ix] ** 2).sum() / ((A['hb_s'][ix] - A['hb_s'][ix].mean()) ** 2).sum())
    per = pd.DataFrame({'p': A['pitcher'], 'sq': sq}).groupby('p')['sq'].agg(['sum', 'size'])
    return dict(rmse=float(np.sqrt(sq.mean())), r2i=float(1 - (oi ** 2).sum() / ((A['ivb'] - A['ivb'].mean()) ** 2).sum()),
                r2h=float(1 - (oh ** 2).sum() / ((A['hb_s'] - A['hb_s'].mean()) ** 2).sum()),
                wi=float(np.mean(wi)), wh=float(np.mean(wh)), med=float(np.median(np.sqrt(sq)))), per


def paired(per_a, per_b, seed=0):
    """RMSE(a) - RMSE(b) with a pitcher-bootstrap se."""
    j = per_a.join(per_b, lsuffix='_a', rsuffix='_b')
    v = j.values
    rng = np.random.default_rng(seed)
    d = []
    for _ in range(NB):
        b = v[rng.integers(0, len(v), len(v))].sum(0)
        d.append(np.sqrt(b[0] / b[1]) - np.sqrt(b[2] / b[3]))
    t = v.sum(0)
    return float(np.sqrt(t[0] / t[1]) - np.sqrt(t[2] / t[3])), float(np.std(d))


def save(name, obj):
    os.makedirs(OUTDIR, exist_ok=True)
    path = os.path.join(OUTDIR, name)
    with open(path + '.tmp', 'w') as fh:
        json.dump(obj, fh, indent=1)
    os.replace(path + '.tmp', path)


def fmt(m):
    return f'{m["rmse"]:.3f}   R2 {m["r2i"]:.3f} / {m["r2h"]:.3f}   within-type {m["wi"]:.2f} / {m["wh"]:.2f}   median miss {m["med"]:.2f}'


def timing():
    A = season(2022)
    t = time.time()
    r = fit_predict(A, BASE, 31, 200, 300, 0.06, 2)
    m, _ = metrics(A, *r[300])
    print(f'2022: {len(A["ivb"]):,} pitches, copied settings, 2 pitcher folds: {time.time() - t:.0f} s for 8 fits of 300 rounds')
    print('   RMSE ' + fmt(m))


def sweep(seasons):
    """Step 1. Three pitcher folds (train on two thirds of the pitchers); the final check uses five."""
    res = {}
    for y in seasons:
        A = season(y)
        print(f'\n{y}: {len(A["ivb"]):,} pitches. Held-out 2D RMSE (in) by boosting rounds at learning rate {LR}; three pitcher folds', flush=True)
        print(f'{"leaves":>7s}{"min leaf":>9s}' + ''.join(f'{st:>9d}' for st in STAGES))

        def run(leaves, msl):
            if (y, leaves, msl) in res:
                return
            r = fit_predict(A, BASE, leaves, msl, max(STAGES), LR, 3, STAGES)
            res[(y, leaves, msl)] = {st: metrics(A, *r[st])[0]['rmse'] for st in STAGES}
            print(f'{leaves:>7d}{msl:>9d}' + ''.join(f'{res[(y, leaves, msl)][st]:>9.3f}' for st in STAGES), flush=True)
            save(f'sweep_{y}.json', {f'{k[1]}_{k[2]}': v for k, v in res.items() if k[0] == y})

        for leaves in (7, 15, 31, 63, 127):
            run(leaves, 200)
        best_l = min((7, 15, 31, 63, 127), key=lambda lv: min(res[(y, lv, 200)].values()))
        for msl in (20, 60, 600, 2000):
            run(best_l, msl)
        best_m = min((20, 60, 200, 600, 2000), key=lambda ms: min(res[(y, best_l, ms)].values()))
        for leaves in (7, 15, 31, 63, 127):          # the leaves curve again at the chosen min leaf
            run(leaves, best_m)
        k = min((kk for kk in res if kk[0] == y), key=lambda kk: min(res[kk].values()))
        st = min(res[k], key=res[k].get)
        print(f'   best on the grid: leaves {k[1]}, min leaf {k[2]}, rounds {st}: {res[k][st]:.3f}')


def sweep2(seasons):
    """Step 1, extended toward small models: the first grid put its best values on the small edge."""
    stages = (25, 50, 100, 200, 400, 800, 1600)
    out = {}
    for y in seasons:
        A = season(y)
        print(f'\n{y}: held-out 2D RMSE (in), min leaf 200, learning rate {LR}, three pitcher folds; * = the row minimum', flush=True)
        print(f'{"leaves":>7s}' + ''.join(f'{st:>9d}' for st in stages))
        for leaves in (3, 4, 5, 7, 10, 15, 22):
            r = fit_predict(A, BASE, leaves, 200, max(stages), LR, 3, stages)
            v = {st: metrics(A, *r[st])[0]['rmse'] for st in stages}
            out[f'{y}|{leaves}'] = v
            print(f'{leaves:>7d}' + ''.join(f'{v[st]:>8.3f}{"*" if v[st] == min(v.values()) else " "}' for st in stages), flush=True)
            save('sweep2.json', out)


def inputs(leaves, msl, iters, seasons=DEV):
    out = {}
    for y in seasons:
        A = season(y)
        print(f'\n{y}: {len(A["ivb"]):,} pitches; leaves {leaves}, min leaf {msl}, rounds {iters}, learning rate {LR}; three pitcher folds', flush=True)
        print(f'{"form":<28s}{"RMSE":>7s}{"vs base (se)":>17s}   diagnostics')
        base = None
        runs = [(n, f, 'split') for n, f in FORMS.items()] + [('base, one model both hands', BASE, 'pool'), ('base, one model + hand flag', BASE, 'flag')]
        for name, feats, hands in runs:
            r = fit_predict(A, feats, leaves, msl, iters, LR, 3, hands=hands)
            m, per = metrics(A, *r[iters])
            if base is None:
                base = per
            d, se = paired(per, base)
            out[f'{y}|{name}'] = dict(m, d=d, se=se)
            print(f'{name:<28s}{m["rmse"]:>7.3f}{f"{d:+.3f} ({se:.3f})":>17s}   R2 {m["r2i"]:.3f} / {m["r2h"]:.3f}  within-type {m["wi"]:.2f} / {m["wh"]:.2f}', flush=True)
            save('inputs.json', out)


def final(leaves, msl, iters, form, hands='split'):
    feats = FORMS[form]
    out = {}
    print(f'chosen: {form}, leaves {leaves}, min leaf {msl}, rounds {iters}, learning rate {LR}, hands {hands}; five pitcher folds')
    print(f'{"season":>7s}{"pitches":>10s}{"CHOSEN RMSE":>13s}{"COPIED base":>13s}{"chosen - copied (se)":>23s}{"leaves/2":>18s}{"leaves x2":>18s}   diagnostics of the chosen model')
    for y in (2021, 2022, 2023, 2024, 2025, 2026):
        A = season(y)
        m, per = metrics(A, *fit_predict(A, feats, leaves, msl, iters, LR, 5, hands=hands)[iters])
        mc, perc = metrics(A, *fit_predict(A, BASE, COPIED[0], COPIED[1], COPIED[2], COPIED[3], 5)[COPIED[2]])
        d, se = paired(per, perc)
        nb = []
        for lv in (max(3, leaves // 2), leaves * 2):
            _, pn = metrics(A, *fit_predict(A, feats, lv, msl, iters, LR, 5, hands=hands)[iters])
            nb.append(paired(pn, per))
        out[str(y)] = dict(chosen=m, copied=mc, d=d, se=se, half=nb[0], double=nb[1])
        print(f'{y:>7d}{len(A["ivb"]):>10,d}{m["rmse"]:>13.3f}{mc["rmse"]:>13.3f}{f"{d:+.3f} ({se:.3f})":>23s}'
              + ''.join(f'{f"{a:+.3f} ({b:.3f})":>18s}' for a, b in nb)
              + f'   R2 {m["r2i"]:.3f} / {m["r2h"]:.3f}  within-type {m["wi"]:.2f} / {m["wh"]:.2f}  median {m["med"]:.2f}', flush=True)
        save('final.json', out)
        del A


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'time'
    if mode == 'time':
        timing()
    elif mode == 'sweep':
        sweep([int(a) for a in sys.argv[2:]] or DEV)
    elif mode == 'sweep2':
        sweep2([int(a) for a in sys.argv[2:]] or DEV)
    elif mode == 'inputs':
        inputs(int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
    elif mode == 'final':
        final(int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5], *(sys.argv[6:7]))
