#!/usr/bin/env python3
"""xmove_agnostic_v2.py — a pitch-type-AGNOSTIC expected movement, the forms never tested.

Wally, 2026-11-19: "pitches thrown at specific velocity, specific spin rate, specific release
traits, arm angle ... it should not change dependent on the pitch type." He accepts that a
four-seam and a sinker may then share an expectation.

What the 2026-09 review tested (docs/expected_movement_review.md, Findings 6 and 9): ONE
LINEAR surface per hand on release inputs, 8 to 55 parameters. Mean within-type R^2 was
negative to .09, and about an inch per pitch of the displayed deviation was neighbour
composition. It judged those forms by fit only; the results test (how well the residual
explains whiffs and run value) was never run on an agnostic form.

Never tested, and tested here. Every form reads NO pitch type and pools all pitches of a
hand and season. Every form is scored on pitchers it did NOT train on (two pitcher folds), so
a flexible model cannot memorise a pitcher through his release point:
  L   linear reference: arm angle, extension, velocity, spin, 2 axis harmonics, spin x axis
      (the review's form, on the pitcher folds)
  G1  gradient boosting on the same release inputs (velocity, spin rate, release axis, arm
      angle, extension): one nonlinear surface instead of a fixed basis
  G2  G1 + release point (height and side)
  G3  G2 + the pitch's velocity and spin RELATIVE to the pitcher's own hardest pitches
      (label-free context: an 80 mph pitch from a 96 mph arm is not the same pitch as an
      80 mph pitch from an 88 mph arm)
  M   no league surface at all: direction = the measured release spin axis, size = what that
      spin rate and velocity produce at the top of the league (90th percentile of the break
      along the axis), expected break across the axis = 0. "What the spin promises."
References (they read the tag): S = the SHIPPED hitter basis per type; P = physics per type.

Reported per form:
  fit       mean within-type R^2 for IVB and HB (how well the expectation describes a class it
            was never told about)
  FF/SI     median expected gap between a pitcher's four-seam and sinker, in inches
  SL->ST    how far the expectation moves if every slider is called a sweeper (0 for an
            agnostic form; the shipped form's number is the complaint)
  value     out-of-season r of (IVB residual, HB residual) with whiff rate and run value,
            per type then averaged, and the same with raw movement added; unit bootstrap
            against the shipped form
  DIST      |r| of the residual with raw movement at the unit (a copy of raw movement is useless)

  XMOVE_DIR=/some/scratch PYTHONHASHSEED=0 .venv/bin/python scripts/research/xmove/xmove_agnostic_v2.py
"""
import json
import os
import sys
import zlib

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import xmove_residual_value as RV  # noqa: E402
import xmove_pertype_ladder as LAD  # noqa: E402
import xmove_hitter_basis_candidates as HC  # noqa: E402

SEASONS, PTS = RV.SEASONS, RV.PTS
OUT = os.path.join(ROOT, 'data', '_xmove_agnostic_v2.json')
REL_LIN = ['aa', 'ext', 'velo', 'spin', 'h1s', 'h1c', 'h2s', 'h2c', 'sp1s', 'sp1c', 'sp2s', 'sp2c']
G1 = ['aa', 'ext', 'velo', 'spin', 'ct', 'st']
G2 = G1 + ['rz', 'rx_s']
G3 = G2 + ['dv', 'dspin']
NB = 300


def hgb(quantile=None):
    from sklearn.ensemble import HistGradientBoostingRegressor as H
    kw = dict(max_iter=300, learning_rate=0.06, max_leaf_nodes=31, min_samples_leaf=200, random_state=0)
    return H(loss='quantile', quantile=quantile, **kw) if quantile else H(**kw)


def agnostic(A, feats, kind):
    """Expected (ivb, hb_s) from one pooled model per hand x season, pitcher-held-out."""
    n = len(A['ivb'])
    xi, xh = np.full(n, np.nan), np.full(n, np.nan)
    grp = pd.factorize(pd.Series(A['thr']) + '_' + pd.Series(A['season']).astype(str))[0]
    for g in range(grp.max() + 1):
        idx = np.where(grp == g)[0]
        for f in (0, 1):
            tr, te = idx[A['pfold'][idx] != f], idx[A['pfold'][idx] == f]
            if kind == 'lin':
                Xt, Xs = LAD.design(A, feats, tr), LAD.design(A, feats, te)
                xi[te] = Xs @ np.linalg.lstsq(Xt, A['ivb'][tr], rcond=None)[0]
                xh[te] = Xs @ np.linalg.lstsq(Xt, A['hb_s'][tr], rcond=None)[0]
            elif kind == 'gbm':
                Xt = np.column_stack([A[c][tr] for c in feats])
                Xs = np.column_stack([A[c][te] for c in feats])
                for tgt, out in (('ivb', xi), ('hb_s', xh)):
                    m = hgb()
                    m.fit(Xt, A[tgt][tr])
                    out[te] = m.predict(Xs)
            else:           # 'magnus': size along the release axis at the league's top, nothing across it
                cols = ['spin', 'velo', 'ext']
                m = hgb(0.9)
                m.fit(np.column_stack([A[c][tr] for c in cols]), A['along'][tr])
                mag = m.predict(np.column_stack([A[c][te] for c in cols]))
                xi[te], xh[te] = mag * A['ct'][te], mag * A['st'][te]
    return xi, xh


def main():
    d = pd.concat([HC.load(y) for y in SEASONS], ignore_index=True)
    d = d[d['Pitch Type'].isin(PTS) & d['Throws'].isin(['L', 'R'])]
    d = d.dropna(subset=['xIndVrtBrk', 'xHorzBrk', 'Velocity', 'Extension', 'ArmAngle', 'SpinAxis', 'Spin Rate', 'KinEff',
                         'RelPosZ', 'RelPosX']).reset_index(drop=True)
    A = LAD.to_arrays(d)
    A['pfold'] = np.array([zlib.crc32(str(p).encode()) % 2 for p in A['pitcher']])
    # label-free context: this pitch against the pitcher's own hardest pitches of the season
    key = pd.Series(A['pitcher']).astype(str) + '_' + pd.Series(A['season']).astype(str)
    v95 = pd.Series(A['velo']).groupby(key.values).transform(lambda s: s.quantile(0.95)).values
    top = pd.Series(np.where(A['velo'] >= v95 - 1.0, A['spin'], np.nan)).groupby(key.values).transform('mean').values
    A['dv'], A['dspin'] = A['velo'] - v95, A['spin'] - top
    forms = {'L linear': (REL_LIN, 'lin'), 'G1 gbm release': (G1, 'gbm'), 'G2 + rel point': (G2, 'gbm'),
             'G3 + own-arm context': (G3, 'gbm'), 'M spin promise': (None, 'magnus')}
    fam_mode = len(sys.argv) > 1 and sys.argv[1] == 'fam'
    if fam_mode:
        forms = {}
    res = {n: agnostic(A, f, k) for n, (f, k) in forms.items()}
    print('agnostic forms fitted', flush=True)
    res['S SHIPPED per type'] = LAD.fit_cv(A, LAD.B0)
    res['P physics per type'] = LAD.fit_cv(A, LAD.B1)
    if fam_mode:
        # FAMILY forms (2026-11-19, second pass): the shipped hitter basis (arm angle, extension, velocity),
        # but fit per FAMILY instead of per pitch type.
        #   F1  tag families: FF SI FC | SL ST CU | CH FS. A retag inside a family cannot move the expectation.
        #   F2  PHYSICAL families, no tag read at all:
        #         hard    within `cut` mph of the pitcher's own 95th-percentile velocity
        #         soft, arm-side spin / soft, glove-side spin   by the side of the measured release axis
        #       The axis is used only as a two-way switch, never as a regressor, so the residual keeps
        #       the spin and axis detail that the shipped form keeps. `cut` is swept.
        def with_groups(fam):
            A2 = dict(A)
            A2['gid'] = pd.factorize(pd.Series(fam) + '_' + pd.Series(A['thr']) + '_' + pd.Series(A['season']).astype(str))[0]
            return LAD.fit_cv(A2, LAD.B0)
        tagfam = {'FF': 'H', 'SI': 'H', 'FC': 'H', 'SL': 'B', 'ST': 'B', 'CU': 'B', 'CH': 'O', 'FS': 'O'}
        res['F1 tag families'] = with_groups(np.array([tagfam[t] for t in A['pt']]))
        arm = np.sign(A['st'][A['pt'] == 'CH'].mean())          # which side of the axis is arm-side: a sign convention
        side = np.where(np.sign(A['st']) == arm, 'O', 'B')
        h, edges = np.histogram(A['dv'], bins=np.arange(-25, 3.01, 0.5))
        mid = (edges[:-1] + edges[1:]) / 2
        win = (mid > -12) & (mid < -1)
        print(f'velocity below the pitcher\'s own top: density valley between the fastball mode and the rest at {mid[win][h[win].argmin()]:.1f} mph '
              f'(share of pitches within 4 / 6 / 8 / 10 mph: ' + ' / '.join(f'{(A["dv"] >= -c).mean():.2f}' for c in (4, 6, 8, 10)) + ')', flush=True)
        # SMOOTH physical forms: no velocity cut at all.
        #   F3a  two groups by the side of the release axis; regressors arm angle, extension, velocity and
        #        the velocity below the pitcher's own top (a regressor, not a switch)
        #   F3b  ONE surface per hand; the same regressors plus the axis DIRECTION (cos, sin), no spin rate
        def with_groups_feats(fam, feats):
            A2 = dict(A)
            A2['gid'] = pd.factorize(pd.Series(fam) + '_' + pd.Series(A['thr']) + '_' + pd.Series(A['season']).astype(str))[0]
            return LAD.fit_cv(A2, feats)
        res['F3a axis side + dv'] = with_groups_feats(side, LAD.B0 + ['dv'])
        res['F3b one surface'] = with_groups_feats(np.array(['all'] * len(side)), LAD.B0 + ['dv', 'ct', 'st'])
        # how often a pitch sits in a different group from the pitcher's own majority for that pitch type
        def flip(fam):
            t = pd.DataFrame({'p': A['pitcher'], 'y': A['season'], 'pt': A['pt'], 'f': fam})
            maj = t.groupby(['p', 'y', 'pt'])['f'].transform(lambda x: x.mode().iloc[0])
            return (t['f'] != maj).groupby(t['pt']).mean().round(3).to_dict()
        print('share of pitches outside the pitcher\'s own majority group, by tag:')
        print('   F2 cut 6:', flip(np.where(A['dv'] >= -6, 'H', side)))
        print('   F3a     :', flip(side), flush=True)
        for cut in (6, 10):
            fam = np.where(A['dv'] >= -cut, 'H', side)
            res[f'F2 physical, cut {cut}'] = with_groups(fam)
            if cut == 6:
                tab = pd.crosstab(pd.Series(A['pt'], name='tag'), pd.Series(fam, name='family'), normalize='index').round(2)
                print('physical families at cut 6 (share of each tag):')
                print(tab.to_string(), flush=True)
    names = list(res)
    ok = np.all([np.isfinite(res[n][0]) for n in names], axis=0)
    # retag sensitivity of the per-type forms: score every SL with the ST model of its hand and season
    retag = {}
    for n, feats in (('S SHIPPED per type', LAD.B0), ('P physics per type', LAD.B1)):
        sh = []
        for thr in ('L', 'R'):
            for yr in SEASONS:
                st = np.where((A['pt'] == 'ST') & (A['thr'] == thr) & (A['season'] == yr))[0]
                sl = np.where((A['pt'] == 'SL') & (A['thr'] == thr) & (A['season'] == yr))[0]
                if len(st) < 400 or len(sl) < 400:
                    continue
                Xs, Xst, Xsl = LAD.design(A, feats, sl), LAD.design(A, feats, st), LAD.design(A, feats, sl)
                for tgt in ('ivb', 'hb_s'):
                    b_st = np.linalg.lstsq(Xst, A[tgt][st], rcond=None)[0]
                    b_sl = np.linalg.lstsq(Xsl, A[tgt][sl], rcond=None)[0]
                    sh.append(np.abs(Xs @ b_st - Xs @ b_sl))
        retag[n] = float(np.median(np.concatenate(sh))) if sh else float('nan')
    d = d[ok].reset_index(drop=True)
    s = np.where(d['Throws'] == 'R', 1.0, -1.0)
    d['ivb'], d['hb'] = d['xIndVrtBrk'], d['xHorzBrk'] * s
    r2, gap = {}, {}
    for n in names:
        xi, xh = res[n][0][ok], res[n][1][ok]
        d[f'xi_{n}'], d[f'xh_{n}'] = xi, xh
        d[f'oi_{n}'], d[f'oh_{n}'] = d['ivb'] - xi, d['hb'] - xh
        a, b = [], []
        for pt, g in d.groupby('Pitch Type'):
            ci = g['ivb'] - g.groupby(['Throws', 'season'])['ivb'].transform('mean')
            ch = g['hb'] - g.groupby(['Throws', 'season'])['hb'].transform('mean')
            a.append(1 - float((g[f'oi_{n}'] ** 2).sum()) / float((ci ** 2).sum()))
            b.append(1 - float((g[f'oh_{n}'] ** 2).sum()) / float((ch ** 2).sum()))
        r2[n] = (float(np.mean(a)), float(np.min(a)), float(np.mean(b)), float(np.min(b)))
        u2 = d[d['Pitch Type'].isin(['FF', 'SI'])].groupby(['Pitcher', 'season', 'Pitch Type']).agg(
            xi=(f'xi_{n}', 'mean'), xh=(f'xh_{n}', 'mean'), ai=('ivb', 'mean'), ah=('hb', 'mean'), k=('ivb', 'size'))
        u2 = u2[u2['k'] >= 50].unstack('Pitch Type').dropna()
        gap[n] = (float((u2[('xi', 'FF')] - u2[('xi', 'SI')]).abs().median()), float((u2[('xh', 'FF')] - u2[('xh', 'SI')]).abs().median()),
                  float((u2[('ai', 'FF')] - u2[('ai', 'SI')]).abs().median()), float((u2[('ah', 'FF')] - u2[('ah', 'SI')]).abs().median()), len(u2))
    d['swing'] = d['Description'].isin(RV.SWINGS).astype(float)
    d['whiff'] = d['Description'].isin(RV.WHIFFS).astype(float)
    agg = {'n': ('ivb', 'size'), 'ivb': ('ivb', 'mean'), 'hb': ('hb', 'mean'), 'swings': ('swing', 'sum'), 'whiffs': ('whiff', 'sum'),
           'rv': ('RunExp', 'mean'), 'aa': ('ArmAngle', 'mean'), 'ext': ('Extension', 'mean'), 'velo': ('Velocity', 'mean')}
    for n in names:
        agg[f'oi_{n}'], agg[f'oh_{n}'] = (f'oi_{n}', 'mean'), (f'oh_{n}', 'mean')
    u = d.groupby(['Pitcher', 'Pitch Type', 'Throws', 'season']).agg(**agg).reset_index()
    u = u[(u.n >= 50) & (u.swings >= 20)].copy().reset_index(drop=True)
    u['whiff_rate'] = u.whiffs / u.swings
    print(f'{len(d):,} pitches, {len(u):,} units; actual FF/SI gap {gap[names[0]][2]:.1f}" IVB, {gap[names[0]][3]:.1f}" HB over {gap[names[0]][4]} pitcher-seasons\n')

    def preds(feats, y):
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
        return p.values

    ptv = u['Pitch Type'].values

    def tmr(p, y, ix=None):
        rs = []
        for pt in PTS:
            m = np.where((ptv == pt) & np.isfinite(p))[0] if ix is None else ix[(ptv[ix] == pt) & np.isfinite(p[ix])]
            if len(m) > 30:
                rs.append(np.corrcoef(p[m], u[y].values[m])[0, 1])
        return float(np.mean(rs))

    rng = np.random.default_rng(0)
    boots = [rng.integers(0, len(u), len(u)) for _ in range(NB)]
    P = {(n, y, k): preds(([f'oi_{n}', f'oh_{n}'] if k == 'res' else ['ivb', 'hb', f'oi_{n}', f'oh_{n}']), y)
         for n in names for y in ('whiff_rate', 'rv') for k in ('res', 'raw')}
    REF = 'S SHIPPED per type'
    out = {}
    print(f'{"form":<22s}{"R2 IVB (worst)":>16s}{"R2 HB (worst)":>16s}{"FF/SI exp gap":>15s}{"SL->ST":>8s}{"DIST":>6s} | {"WHIFF r":>8s}{"vs S (se)":>16s}{"+raw":>7s}{"vs S (se)":>16s} | '
          f'{"RV r":>7s}{"vs S (se)":>16s}{"+raw":>7s}{"vs S (se)":>16s}')
    for n in names:
        dist = float(np.mean([abs(np.corrcoef(u[f'oi_{n}'], u['ivb'])[0, 1]), abs(np.corrcoef(u[f'oh_{n}'], u['hb'])[0, 1])]))
        rt = retag.get(n, 0.0)
        line = (f'{n:<22s}{f"{r2[n][0]:.2f} ({r2[n][1]:.2f})":>16s}{f"{r2[n][2]:.2f} ({r2[n][3]:.2f})":>16s}'
                f'{f"{gap[n][0]:.1f} / {gap[n][1]:.1f}":>15s}{rt:>8.1f}{dist:>6.2f} | ')
        rec = {'r2': r2[n], 'gap': gap[n], 'retag': rt, 'dist': dist}
        for y in ('whiff_rate', 'rv'):
            for k in ('res', 'raw'):
                r = tmr(P[(n, y, k)], y)
                d0 = r - tmr(P[(REF, y, k)], y)
                se = float(np.std([tmr(P[(n, y, k)], y, ix) - tmr(P[(REF, y, k)], y, ix) for ix in boots]))
                rec[f'{y}_{k}'] = (r, d0, se)
                line += f'{r:>{8 if (k == "res" and y == "whiff_rate") else 7}.3f}{f"{d0:+.3f} ({se:.3f})":>16s}'
            line += ' | '
        out[n] = rec
        print(line, flush=True)
    # GUARD: the residual-only test can be gamed by a residual that keeps more of the visible traits (velocity
    # above all). With slot, extension, velocity and raw movement all given, what does each residual still add?
    print('\nGUARD: out-of-season r with slot, extension, velocity and raw movement in the model, then with the residual added')
    base = ['aa', 'ext', 'velo', 'ivb', 'hb']
    for y, lab in (('whiff_rate', 'whiff'), ('rv', 'run value')):
        b0 = tmr(preds(base, y), y)
        print(f'  {lab}: base {b0:.3f} | ' + '  '.join(f'{n.split()[0]} {tmr(preds(base + [f"oi_{n}", f"oh_{n}"], y), y) - b0:+.3f}' for n in names))
        print(f'  {lab}: velocity, slot, extension alone {tmr(preds(["aa", "ext", "velo"], y), y):.3f}; raw movement alone {tmr(preds(["ivb", "hb"], y), y):.3f}')
    print('\nper pitch type, WHIFF r of the residual: ' + '  '.join(PTS))
    for n in names:
        rs = []
        for pt in PTS:
            m = (ptv == pt) & np.isfinite(P[(n, 'whiff_rate', 'res')])
            rs.append(np.corrcoef(P[(n, 'whiff_rate', 'res')][m], u['whiff_rate'].values[m])[0, 1] if m.sum() > 30 else np.nan)
        print(f'  {n:<22s}' + ' '.join(f'{x:>6.2f}' for x in rs))
    json.dump(out, open(OUT + '.tmp', 'w'), indent=1)
    os.replace(OUT + '.tmp', OUT)
    print(f'\nwrote {OUT}')


if __name__ == '__main__':
    main()
