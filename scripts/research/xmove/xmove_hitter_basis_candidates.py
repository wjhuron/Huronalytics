#!/usr/bin/env python3
"""xmove_hitter_basis_candidates.py — can the shipped expected-movement model be improved
INSIDE its own definition? (2026-11-19 review)

pipeline/xmove.py ships the HITTER basis: what a pitch "should" do given what a hitter can
read before the ball moves (arm angle, extension, velocity), one least-squares fit per pitch
type and hand. The physics basis (spin and axis) explains the movement far better and was
pulled, because its residual explains RESULTS worse (xmove_residual_value.py). So the
deciding objective for this model is not movement R^2: it is how well the RESIDUAL
(IVBOE, HBOE) explains results. This script holds every candidate to that objective.

Candidates, all limited to pre-release information:
  H0  slot only                       aa
  H1  SHIPPED                         aa, ext, velo
  H2  + release point                 aa, ext, velo, rz, rx
  H3  release point, no slot          rz, rx, ext, velo      (the shipped 'roc' fallback form)
  H4  + curvature                     aa, ext, velo, aa^2, velo^2
  H5  + slot x velocity               aa, ext, velo, aa x velo
  H6  all of H2, H4, H5
  G   gradient boosting on aa, ext, velo, rz, rx (the nonlinear ceiling of the definition)
  P   physics (reference only)        + spin, axis harmonics, spin x axis

Same protocol as xmove_residual_value.py: every form is cross-fit by game parity inside
(type, hand, season); units are pitcher x type x hand x season with 50+ pitches and 20+
swings, 2021-2025; outcome ~ (IVB residual, HB residual) is fit on four seasons and scored
on the fifth. Reported per form: within-type movement R^2 (a diagnostic here), the
out-of-season r for whiff rate and for run value, the same with raw IVB/HB added, and how
close the residual is to raw movement. Unit bootstrap for each form against H1.

  XMOVE_DIR=/some/scratch PYTHONHASHSEED=0 .venv/bin/python scripts/research/xmove/xmove_hitter_basis_candidates.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import xmove_residual_value as RV  # noqa: E402
import xmove_pertype_ladder as LAD  # noqa: E402

SEASONS, PTS = RV.SEASONS, RV.PTS
OUT = os.path.join(ROOT, 'data', '_xmove_hitter_basis_candidates.json')
B0 = LAD.B0
FORMS = [('H0 slot', ['aa']), ('H1 SHIPPED', B0), ('H2 +relpt', B0 + ['rz', 'rx_s']), ('H3 relpt no slot', ['rz', 'rx_s', 'ext', 'velo']),
         ('H4 +curv', B0 + ['aa2', 'velo2h']), ('H5 +aa x velo', B0 + ['aav']), ('H6 all', B0 + ['rz', 'rx_s', 'aa2', 'velo2h', 'aav']),
         ('G gbm', None), ('P physics', LAD.B1)]
NB = 500


def load(year):
    """xmove_residual_value.load with a pickle cache: the project environment has no parquet
    engine, and a new dependency is not added for a cache file."""
    import pickle
    path = f'{RV.SCRATCH}/xmove_value_{year}.pkl'
    if os.path.exists(path):
        return pd.read_pickle(path)
    with open(f'{ROOT}/data/_pitches{year}_training.pkl', 'rb') as fh:
        rows = pickle.load(fh)
    df = pd.DataFrame([{c: r.get(c) for c in RV.COLS} for r in rows])
    del rows
    for c in ['Velocity', 'Spin Rate', 'SpinAxis', 'xIndVrtBrk', 'xHorzBrk', 'Extension', 'ArmAngle', 'KinEff', 'KinCd',
              'RelPosZ', 'RelPosX', 'RunExp']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df['season'] = year
    df.to_pickle(path)
    return df


def main():
    d = pd.concat([load(y) for y in SEASONS], ignore_index=True)
    d = d[d['Pitch Type'].isin(PTS) & d['Throws'].isin(['L', 'R'])]
    d = d.dropna(subset=['xIndVrtBrk', 'xHorzBrk', 'Velocity', 'Extension', 'ArmAngle', 'SpinAxis', 'Spin Rate', 'KinEff',
                         'RelPosZ', 'RelPosX']).reset_index(drop=True)
    A = LAD.to_arrays(d)
    A['aa2'] = (A['aa'] / 10.0) ** 2
    A['velo2h'] = (A['velo'] / 10.0) ** 2
    A['aav'] = A['aa'] * A['velo'] / 100.0
    LAD.GBM_RAW = ['aa', 'ext', 'velo', 'rz', 'rx_s']
    res = {n: (LAD.fit_cv(A, f) if f is not None else LAD.fit_cv(A, None, gbm=True)) for n, f in FORMS}
    ok = np.all([np.isfinite(res[n][0]) for n, _ in FORMS], axis=0)
    d = d[ok].reset_index(drop=True)
    s = np.where(d['Throws'] == 'R', 1.0, -1.0)
    d['ivb'], d['hb'] = d['xIndVrtBrk'], d['xHorzBrk'] * s
    r2 = {}
    for n, _ in FORMS:
        xi, xh = res[n][0][ok], res[n][1][ok]
        d[f'oi_{n}'], d[f'oh_{n}'] = d['ivb'] - xi, d['hb'] - xh
        a, b = [], []
        for pt, g in d.groupby('Pitch Type'):
            ci = g['ivb'] - g.groupby(['Throws', 'season'])['ivb'].transform('mean')
            ch = g['hb'] - g.groupby(['Throws', 'season'])['hb'].transform('mean')
            a.append(1 - float((g[f'oi_{n}'] ** 2).sum()) / float((ci ** 2).sum()))
            b.append(1 - float((g[f'oh_{n}'] ** 2).sum()) / float((ch ** 2).sum()))
        r2[n] = (float(np.mean(a)), float(np.mean(b)))
    d['swing'] = d['Description'].isin(RV.SWINGS).astype(float)
    d['whiff'] = d['Description'].isin(RV.WHIFFS).astype(float)
    agg = {'n': ('ivb', 'size'), 'ivb': ('ivb', 'mean'), 'hb': ('hb', 'mean'), 'swings': ('swing', 'sum'), 'whiffs': ('whiff', 'sum'),
           'rv': ('RunExp', 'mean')}
    for n, _ in FORMS:
        agg[f'oi_{n}'], agg[f'oh_{n}'] = (f'oi_{n}', 'mean'), (f'oh_{n}', 'mean')
    u = d.groupby(['Pitcher', 'Pitch Type', 'Throws', 'season']).agg(**agg).reset_index()
    u = u[(u.n >= 50) & (u.swings >= 20)].copy()
    u['whiff_rate'] = u.whiffs / u.swings
    print(f'{len(d):,} pitches, {len(u):,} units (pitcher x type x hand x season, 50+ pitches, 20+ swings)\n')

    def preds(feats, y):
        """Out-of-season prediction for every unit (NaN where a type has too few units)."""
        p = pd.Series(np.nan, index=u.index)
        for pt in PTS:
            b = u[u['Pitch Type'] == pt]
            for yr in SEASONS:
                tr, te = b[b.season != yr], b[b.season == yr]
                if len(tr) < 60 or len(te) < 20:
                    continue
                X = np.column_stack([np.ones(len(tr))] + [tr[f].values for f in feats])
                beta = np.linalg.lstsq(X, tr[y].values, rcond=None)[0]
                p.loc[te.index] = np.column_stack([np.ones(len(te))] + [te[f].values for f in feats]) @ beta
        return p

    def type_mean_r(p, y, idx=None):
        rs = []
        for pt in PTS:
            m = (u['Pitch Type'] == pt).values & np.isfinite(p.values)
            ix = np.where(m)[0] if idx is None else idx[m[idx]]
            if len(ix) > 30:
                rs.append(np.corrcoef(p.values[ix], u[y].values[ix])[0, 1])
        return float(np.mean(rs))

    rng = np.random.default_rng(0)
    boots = [rng.integers(0, len(u), len(u)) for _ in range(NB)]
    out = {}
    hdr = f'{"form":<18s}{"R2 IVB":>8s}{"R2 HB":>8s}{"|r| res,raw":>12s} | '
    for y, lab in (('whiff_rate', 'WHIFF'), ('rv', 'RUN VALUE')):
        hdr += f'{lab + " r":>11s}{"vs H1 (se)":>17s}{"+raw r":>9s}{"vs H1 (se)":>17s} | '
    print(hdr)
    P = {}
    for n, _ in FORMS:
        for y in ('whiff_rate', 'rv'):
            P[(n, y, 'res')] = preds([f'oi_{n}', f'oh_{n}'], y)
            P[(n, y, 'raw')] = preds(['ivb', 'hb', f'oi_{n}', f'oh_{n}'], y)
    for n, _ in FORMS:
        dist = float(np.mean([abs(np.corrcoef(u[f'oi_{n}'], u['ivb'])[0, 1]), abs(np.corrcoef(u[f'oh_{n}'], u['hb'])[0, 1])]))
        line = f'{n:<18s}{r2[n][0]:>8.3f}{r2[n][1]:>8.3f}{dist:>12.2f} | '
        rec = {'r2_ivb': r2[n][0], 'r2_hb': r2[n][1], 'dist': dist}
        for y in ('whiff_rate', 'rv'):
            for kind in ('res', 'raw'):
                r = type_mean_r(P[(n, y, kind)], y)
                dd = [type_mean_r(P[(n, y, kind)], y, ix) - type_mean_r(P[('H1 SHIPPED', y, kind)], y, ix) for ix in boots]
                d0 = r - type_mean_r(P[('H1 SHIPPED', y, kind)], y)
                rec[f'{y}_{kind}'] = (r, d0, float(np.std(dd)))
                line += f'{r:>{11 if kind == "res" else 9}.3f}{f"{d0:+.3f} ({np.std(dd):.3f})":>17s}'
            line += ' | '
        out[n] = rec
        print(line, flush=True)
    print('\nper pitch type, WHIFF r of the residual model: ' + '  '.join(PTS))
    for n, _ in FORMS:
        rs = []
        for pt in PTS:
            m = (u['Pitch Type'] == pt).values & np.isfinite(P[(n, 'whiff_rate', 'res')].values)
            rs.append(np.corrcoef(P[(n, 'whiff_rate', 'res')].values[m], u['whiff_rate'].values[m])[0, 1] if m.sum() > 30 else np.nan)
        print(f'  {n:<18s}' + ' '.join(f'{x:>6.2f}' for x in rs))
    json.dump(out, open(OUT + '.tmp', 'w'), indent=1)
    os.replace(OUT + '.tmp', OUT)
    print(f'\nwrote {OUT}')


if __name__ == '__main__':
    main()
