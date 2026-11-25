"""stuff_relx_calibration.py — is the Stuff+ release-side penalty real?

Question (2026-11-25, Pasqualotto's four-seam): the shipped design reads a
four-seam released near the centre of the rubber (rel_x about -0.4 ft), from a
three-quarter arm angle and with average ride, about 8 points under the same
pitch released at the MLB median (-1.6 ft). Does the held-out outcome agree?

Method. Six gate frames (2021-2026), the shipped design and parameters, and
pitcher-grouped folds POOLED over all six seasons, so the model that scores a
pitcher never saw any season of his (no identity carry). Two arms:
  FULL    the shipped design
  NORELX  the shipped design without rel_x
The test group's mean (actual - NORELX prediction) is the release-side effect
the outcomes show; (FULL - NORELX) is the effect the model assigns. Standard
errors are a pitcher bootstrap.

Usage (repo root, alone on this machine):
  PYTHONHASHSEED=0 python3 scripts/research/stuff/stuff_relx_calibration.py fit
  PYTHONHASHSEED=0 python3 scripts/research/stuff/stuff_relx_calibration.py read
"""
import gc
import os
import sys
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stuff_gate_v2 as G                               # noqa: E402

OUT = os.path.join(ROOT, 'data', '_stuff_relx')
K_FOLDS = 5          # convention: the fold count is not a tuned constant
SEED = 0
ARMS = {'FULL': {}, 'NORELX': {'drop': ['rel_x']}}
KEEP = ['pitcher', 'season', 'pitch_type', 'throws', 'target_xrv', 'rel_z']
BOOT_B = 2000


def fit():
    os.makedirs(OUT, exist_ok=True)
    frames = {y: G.load_frame(y) for y in G.SEASONS}
    G.set_arm_side_sign(list(frames.values()))
    slopes = G.fit_vaa_slopes(list(frames.values()))
    feats_all = G.variant_feats({})
    parts = []
    for y in G.SEASONS:
        p = G.prepare(frames.pop(y), slopes)
        X = G.design(p, {}, feats_all)
        meta = p[KEEP].reset_index(drop=True)
        parts.append(pd.concat([meta, X.reset_index(drop=True)], axis=1))
        del p, X
        gc.collect()
    D = pd.concat(parts, ignore_index=True)
    del parts
    gc.collect()
    D = D[np.isfinite(D['target_xrv'].values)].reset_index(drop=True)
    print(f'rows with a target: {len(D)}; pitchers {D["pitcher"].nunique()}', flush=True)
    rng = np.random.default_rng(1000 + SEED)
    pits = np.array(sorted(D['pitcher'].astype(str).unique()))
    fold_of = dict(zip(pits, rng.permutation(len(pits)) % K_FOLDS))
    fold = D['pitcher'].astype(str).map(fold_of).values
    y = D['target_xrv'].values
    out = D[KEEP + feats_all + G.DESIGN_TAIL].copy()
    out['fold'] = fold
    for name, spec in ARMS.items():
        feats = G.variant_feats(spec)
        X = D[feats + G.DESIGN_TAIL]
        pred = np.full(len(D), np.nan, dtype='float32')
        t0 = time.time()
        for k in range(K_FOLDS):
            te = fold == k
            pred[te] = G.fit_predict(X[~te], y[~te], X[te], spec, SEED)
            print(f'  {name} fold {k}: train {int((~te).sum())}, scored {int(te.sum())} '
                  f'[{time.time() - t0:.0f}s]', flush=True)
        out['pred_' + name] = pred
    tmp = os.path.join(OUT, 'oof.pkl.tmp')
    out.to_pickle(tmp)
    os.replace(tmp, os.path.join(OUT, 'oof.pkl'))
    print('wrote', os.path.join(OUT, 'oof.pkl'))


def _boot(df, cols, B=BOOT_B, seed=0):
    """Pitch-weighted means of `cols` with a pitcher-bootstrap SE."""
    g = df.groupby('pitcher')[cols].sum()
    n = df.groupby('pitcher').size().reindex(g.index).values.astype(float)
    S = g.values
    mean = S.sum(0) / n.sum()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(n), size=(B, len(n)))
    bs = S[idx].sum(1) / n[idx].sum(1)[:, None]
    return mean, bs.std(0), int(n.sum()), len(n)


def read():
    D = pd.read_pickle(os.path.join(OUT, 'oof.pkl'))
    D['pitcher'] = D['pitcher'].astype(str)
    # anchor SD of the four-seam unit: 10 Stuff+ points per SD (bundle info, CI)
    import json
    sd = json.load(open(os.path.join(ROOT, 'data', 'stuff_bundle_info.json')))['league']['FF']['sd']
    pts = 10.0 / sd                      # Stuff+ points per run per pitch
    # pitcher-positive values, in four-seam Stuff+ points around the FF mean
    ff = D[D['pitch_type'].astype(str) == 'FF'].copy()
    for c in ('target_xrv', 'pred_FULL', 'pred_NORELX'):
        ff[c] = -ff[c].astype(float)
    mu = ff['target_xrv'].mean()
    ff['act'] = (ff['target_xrv'] - mu) * pts
    ff['full'] = (ff['pred_FULL'] - mu) * pts
    ff['norx'] = (ff['pred_NORELX'] - mu) * pts
    ff['res_full'] = ff['act'] - ff['full']
    ff['res_norx'] = ff['act'] - ff['norx']
    ff['assigned'] = ff['full'] - ff['norx']
    cols = ['act', 'full', 'norx', 'res_full', 'res_norx', 'assigned']
    print(f'four-seams: {len(ff)} pitches, {ff["pitcher"].nunique()} pitchers; '
          f'1 run/100 = {pts / 100:.1f} points')

    def line(tag, sub):
        if len(sub) < 500:
            print(f'{tag:<34} n={len(sub)} (too few)')
            return
        m, se, n, k = _boot(sub, cols)
        print(f'{tag:<34} n={n:>7} p={k:>4} | actual {m[0]:6.1f} | FULL {m[1]:6.1f} '
              f'NORELX {m[2]:6.1f} | actual-FULL {m[3]:5.1f} ({se[3]:.1f}) | '
              f'actual-NORELX {m[4]:5.1f} ({se[4]:.1f}) | assigned {m[5]:5.1f}')

    edges = [-9, -2.6, -2.2, -1.8, -1.4, -1.0, -0.6, 9]
    lab = lambda a, b: f'rel_x {a:+.1f}..{b:+.1f}'
    print('\n== A. every four-seam, by release side (arm side is negative) ==')
    for a, b in zip(edges[:-1], edges[1:]):
        line(lab(a, b), ff[(ff['rel_x'] >= a) & (ff['rel_x'] < b)])

    def like(d, arm=(36, 50), ivb=(14.0, 17.5)):
        return d[d['arm_angle'].between(*arm) & d['ivb'].between(*ivb)]
    print('\n== B. arm angle 36-50, IVB 14-17.5 (his type), by release side ==')
    L = like(ff)
    for a, b in zip(edges[:-1], edges[1:]):
        line(lab(a, b), L[(L['rel_x'] >= a) & (L['rel_x'] < b)])
    print('\n== C. the test group: his type and rel_x > -1.0; band checks ==')
    line('base (36-50, 14-17.5, > -1.0)', L[L['rel_x'] > -1.0])
    line('rel_x > -0.8', L[L['rel_x'] > -0.8])
    line('rel_x > -1.2', L[L['rel_x'] > -1.2])
    line('arm 38-48, IVB 14.5-17', like(ff, (38, 48), (14.5, 17.0)).query('rel_x > -1.0'))
    line('arm 33-53, IVB 13-18.5', like(ff, (33, 53), (13.0, 18.5)).query('rel_x > -1.0'))
    line('velocity 94-97.5 added', L[(L['rel_x'] > -1.0) & L['velocity'].between(94, 97.5)])
    line('right-handers only', L[(L['rel_x'] > -1.0) & (L['is_lhp'] == 0)])
    print('\n== D. the test group by season (independent replicates) ==')
    for y in sorted(ff['season'].unique()):
        line(f'{y}', L[(L['rel_x'] > -1.0) & (L['season'] == y)])
    print('\n== E. control: his type at the usual release side (-2.0..-1.2) ==')
    line('control', L[L['rel_x'].between(-2.0, -1.2)])
    for y in sorted(ff['season'].unique()):
        line(f'control {y}', L[L['rel_x'].between(-2.0, -1.2) & (L['season'] == y)])


if __name__ == '__main__':
    {'fit': fit, 'read': read}[sys.argv[1]]()
