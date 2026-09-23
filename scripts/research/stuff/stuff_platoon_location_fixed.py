#!/usr/bin/env python3
"""stuff_platoon_location_fixed.py — is the Stuff+ platoon gap a location gap?

Question (Wally, 2026-09-23): Stuff+ grades a pitch higher against a same-hand
batter (SI +18, ST +16, CH/SL +7 points in the 09-05 handedness audit). The
model has no location input, but its LABEL carries location value. If pitchers
locate better against same-hand batters, the single `platoon_same` flag
absorbs that and credits it to "stuff".

Test. For each season 2021-2026 and each pitch type, the same-minus-opposite
gap in the Stuff+ target (luck-neutral xRV: xwOBA on balls in play, RunExp
otherwise, the build_df rule) is estimated four ways, all on one row set
(rows with count AND location):

  raw   difference of means
  P     pitcher fixed effects (the pitcher is held fixed)
  PC    + count fixed effects
  PCL   + (count x location cell) fixed effects: the same pitcher, the same
        count, the same spot RELATIVE TO THE BATTER (x mirrored so + = away,
        z normalised to the zone: 0 = bottom, 1 = top)

PCL is run at three cell sizes (2 in / 0.10, 4 in / 0.20, 6 in / 0.30) to show
the answer does not depend on the grid. Gaps are pitcher-positive and
converted to Stuff+ points with the shipped bundle's per-type anchor SD
(points = 10 * gap / sd_t; KC uses CU's).

Model side (2026 only): every 2026 MLB pitch is scored by the shipped v15
fold bundle at platoon_same = 1 and = 0 (each fold model scores the pitchers
it never saw). The mean difference is the platoon credit Stuff+ actually
gives, in the same units.

Seasons 2021-2025 come straight from the Statcast caches (season Guts as in
the gate); 2026 from the sheets cache via build_df. Pitchers who threw an
EP are dropped, as in the gate.

Output: data/_platoon_locfixed.json. Run from the repo root.
"""
import json
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
import stuff_plus.train_stuff as T                      # noqa: E402

OUT = os.path.join(ROOT, 'data', '_platoon_locfixed.json')
TYPES = ['FF', 'SI', 'FC', 'SL', 'ST', 'SV', 'CU', 'KC', 'CH', 'FS']
GUTS = {2021: (0.314, 1.209), 2022: (0.310, 1.259),
        2023: (0.318, 1.204), 2024: (0.310, 1.242),
        2025: (T.PRIOR_LG_WOBA, T.PRIOR_WOBA_SCALE)}
CELLS = {'2in': (2 / 12, 0.10), '4in': (4 / 12, 0.20), '6in': (6 / 12, 0.30)}
MIN_N = 1500              # rows per (season, type) to report


def _num(s):
    return pd.to_numeric(s, errors='coerce').to_numpy(dtype='float64', na_value=np.nan)


def frame_from_cache(y):
    df = pickle.load(open(os.path.join(ROOT, 'data', f'_statcast{y}_cache.pkl'), 'rb'))
    df = df[df['game_type'] == 'R']
    ep = set(df.loc[df['pitch_type'] == 'EP', 'pitcher'])
    df = df[~df['pitcher'].isin(ep)]
    lg, sc = GUTS[y]
    desc = df['description'].astype(str).values
    xw = _num(df['estimated_woba_using_speedangle'])
    dre = _num(df['delta_run_exp'])            # batter-positive
    bip = desc == 'hit_into_play'
    tgt = np.where(bip & np.isfinite(xw), (xw - lg) / sc, dre)
    tgt = np.where(bip & ~np.isfinite(xw), dre, tgt)
    b, s = _num(df['balls']), _num(df['strikes'])
    out = pd.DataFrame({
        'pitcher': df['pitcher'].astype(str).values,
        'pitch_type': df['pitch_type'].astype(str).values,
        'bats': df['stand'].astype(str).values,
        'throws': df['p_throws'].astype(str).values,
        'target': tgt, 'balls': b, 'strikes': s,
        'px': _num(df['plate_x']), 'pz': _num(df['plate_z']),
        'top': _num(df['sz_top']), 'bot': _num(df['sz_bot']),
    })
    del df
    return out


def load_2026_pitches():
    allp = pickle.load(open(os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl'), 'rb'))
    ep = {(p.get('Pitcher'), p.get('PTeam')) for p in allp
          if p.get('Pitch Type') == 'EP'}
    return [p for p in allp if p.get('_source') == 'MLB'
            and (p.get('Pitcher'), p.get('PTeam')) not in ep]


def frame_2026_and_model(B):
    p26 = load_2026_pitches()
    d = T.build_df(p26)
    d = d[d['target_xrv'].notna()].reset_index(drop=True)
    info = {p.get('PitchID'): p for p in p26}
    del p26

    # ---- model side: platoon credit from the shipped fold bundle ----
    X = T.design(d).reindex(columns=B['features'], fill_value=0)
    pred = {0: np.full(len(d), np.nan), 1: np.full(len(d), np.nan)}
    seen = np.zeros(len(d), bool)
    for m, pits in zip(B['fold_models'], B['fold_pitchers']):
        mask = d['pitcher'].isin(set(pits)).values
        if not mask.any():
            continue
        for v in (0, 1):
            Xv = X.loc[mask].copy()
            Xv['platoon_same'] = v
            pred[v][mask] = m.predict(Xv)
        seen |= mask
    if (~seen).any():                       # pitchers new since the bundle
        for v in (0, 1):
            Xv = X.loc[~seen].copy()
            Xv['platoon_same'] = v
            pred[v][~seen] = B['model'].predict(Xv)
    print(f'  2026 model: {seen.mean():.1%} of rows scored out of fold, '
          f'{(~seen).sum()} by the full model', flush=True)
    # target is batter-positive, so the pitcher-positive credit for SAME is
    # pred(opp) - pred(same)
    d['model_gap'] = pred[0] - pred[1]

    cnt = [info.get(k, {}).get('Count') for k in d['pid']]
    bs = [c.split('-') if isinstance(c, str) and '-' in c else (None, None) for c in cnt]
    out = pd.DataFrame({
        'pitcher': d['pitcher'].astype(str).values,
        'pitch_type': d['pitch_type'].astype(str).values,
        'bats': [info.get(k, {}).get('Bats') for k in d['pid']],
        'throws': d['throws'].astype(str).values,
        'target': d['target_xrv'].astype(float).values,
        'balls': pd.to_numeric([b for b, _ in bs], errors='coerce'),
        'strikes': pd.to_numeric([s for _, s in bs], errors='coerce'),
        'px': pd.to_numeric([info.get(k, {}).get('PlateX') for k in d['pid']], errors='coerce'),
        'pz': pd.to_numeric([info.get(k, {}).get('PlateZ') for k in d['pid']], errors='coerce'),
        'top': pd.to_numeric([info.get(k, {}).get('SzTop') for k in d['pid']], errors='coerce'),
        'bot': pd.to_numeric([info.get(k, {}).get('SzBot') for k in d['pid']], errors='coerce'),
        'model_gap': d['model_gap'].values,
    })
    return out


def prep(f):
    f = f[f['pitch_type'].isin(TYPES) & f['bats'].isin(['L', 'R'])
          & f['throws'].isin(['L', 'R']) & np.isfinite(f['target'])].copy()
    ok = (np.isfinite(f['balls']) & np.isfinite(f['strikes'])
          & f['balls'].between(0, 3) & f['strikes'].between(0, 2)
          & np.isfinite(f['px']) & np.isfinite(f['pz'])
          & np.isfinite(f['top']) & np.isfinite(f['bot'])
          & (f['top'] - f['bot'] > 0.5))
    n0 = len(f)
    f = f[ok].copy()
    f['same'] = (f['bats'] == f['throws']).astype(float)
    f['count'] = (f['balls'] * 3 + f['strikes']).astype(int)
    f['xa'] = np.where(f['bats'] == 'R', f['px'], -f['px'])   # + = away from batter
    f['zn'] = (f['pz'] - f['bot']) / (f['top'] - f['bot'])
    return f, ok.mean() if n0 else float('nan')


def _codes(*arrs):
    k = pd.MultiIndex.from_arrays(arrs) if len(arrs) > 1 else pd.Index(arrs[0])
    return pd.factorize(k)[0]


def fe_coef(y, dvar, fes, cl, iters=200, tol=1e-10):
    """Coefficient on dvar with fixed effects `fes` (list of int code arrays),
    alternating projections; pitcher-clustered SE."""
    ry, rd = y - y.mean(), dvar - dvar.mean()
    for _ in range(iters):
        prev = rd.copy()
        for g in fes:
            n = np.bincount(g)
            ry = ry - (np.bincount(g, ry) / n)[g]
            rd = rd - (np.bincount(g, rd) / n)[g]
        if np.max(np.abs(rd - prev)) < tol:
            break
    sdd = float(np.sum(rd * rd))
    if sdd <= 0:
        return float('nan'), float('nan')
    b = float(np.sum(rd * ry) / sdd)
    e = ry - b * rd
    sg = np.bincount(cl, rd * e)
    return b, float(np.sqrt(np.sum(sg * sg)) / sdd)


def cell_codes(f, wx, wz):
    xa = np.clip(f['xa'].values, -2.5, 2.5)
    zn = np.clip(f['zn'].values, -1.0, 2.0)
    return np.floor(xa / wx).astype(int), np.floor(zn / wz).astype(int)


def season_stats(f, sd_of):
    res = {}
    for t in TYPES:
        g = f[f['pitch_type'] == t]
        if len(g) < MIN_N or g['same'].nunique() < 2:
            continue
        y, dv = g['target'].values, g['same'].values
        pit = _codes(g['pitcher'].values)
        cnt = g['count'].values
        conv = 10.0 / sd_of(t)             # runs/pitch -> Stuff+ points
        r = {'n': int(len(g)), 'same_share': float(dv.mean())}
        # pitcher-positive: opp minus same of a batter-positive target
        r['raw'] = float((y[dv == 0].mean() - y[dv == 1].mean()) * conv)
        b, se = fe_coef(y, dv, [pit], pit)
        r['P'], r['P_se'] = -b * conv, se * conv
        b, se = fe_coef(y, dv, [pit, _codes(cnt)], pit)
        r['PC'], r['PC_se'] = -b * conv, se * conv
        for name, (wx, wz) in CELLS.items():
            cx, cz = cell_codes(g, wx, wz)
            b, se = fe_coef(y, dv, [pit, _codes(cx, cz)], pit)
            r[f'PL_{name}'] = -b * conv
            b, se = fe_coef(y, dv, [pit, _codes(cnt, cx, cz)], pit)
            r[f'PCL_{name}'], r[f'PCL_{name}_se'] = -b * conv, se * conv
        if 'model_gap' in g:
            r['model'] = float(np.nanmean(g['model_gap'].values) * conv)
        res[t] = r
    return res


def main():
    t0 = time.time()
    B = pickle.load(open(os.path.join(ROOT, 'stuff_plus', 'stuff_models.pkl'), 'rb'))
    if B.get('version') != T.BUNDLE_VERSION:
        sys.exit(f'bundle {B.get("version")} != trainer {T.BUNDLE_VERSION}; refresh it first')
    L = B['league']

    def sd_of(t):
        return L.get(t if t != 'KC' else 'CU')['sd']

    out = {'bundle': B['version'], 'trained_through': B.get('trained_through'),
           'cells': {k: list(v) for k, v in CELLS.items()}, 'seasons': {}}
    for y in (2021, 2022, 2023, 2024, 2025, 2026):
        f = frame_2026_and_model(B) if y == 2026 else frame_from_cache(y)
        f, cov = prep(f)
        print(f'  {y}: {len(f)} rows with count + location ({cov:.1%})', flush=True)
        out['seasons'][str(y)] = {'coverage': float(cov), 'types': season_stats(f, sd_of)}
        del f
        print(f'  {y} done [{time.time() - t0:.0f}s]', flush=True)
        tmp = OUT + '.tmp'
        json.dump(out, open(tmp, 'w'), indent=1)
        os.replace(tmp, OUT)

    # summary
    print('\nStuff+ points, pitcher-positive (same-hand minus opposite-hand).')
    print('Mean over 2021-2026 [min, max]; model = shipped v15 credit on 2026.')
    hdr = f'{"type":4} {"model":>6} {"raw":>13} {"P":>13} {"PC":>13} {"PCL 4in":>13} {"2in":>6} {"6in":>6} {"left":>5}'
    print(hdr)
    for t in TYPES:
        rows = [out['seasons'][s]['types'].get(t) for s in out['seasons']]
        rows = [r for r in rows if r]
        if not rows:
            continue

        def ms(k):
            v = np.array([r[k] for r in rows])
            return f'{v.mean():5.1f} [{v.min():4.1f},{v.max():4.1f}]'
        m26 = out['seasons']['2026']['types'].get(t, {}).get('model', float('nan'))
        p = np.mean([r['P'] for r in rows])
        pcl = np.mean([r['PCL_4in'] for r in rows])
        print(f'{t:4} {m26:6.1f} {ms("raw")} {ms("P")} {ms("PC")} {ms("PCL_4in")} '
              f'{np.mean([r["PCL_2in"] for r in rows]):6.1f} '
              f'{np.mean([r["PCL_6in"] for r in rows]):6.1f} '
              f'{(pcl / p if p else float("nan")):5.0%}')
    print(f'\nwrote {OUT} [{time.time() - t0:.0f}s]')


if __name__ == '__main__':
    main()
