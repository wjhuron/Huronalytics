#!/usr/bin/env python3
"""xmove_shape_types.py — expected movement from what a pitch IS, not what it is CALLED.

Wally, 2026-11-19: a sweeper and a curveball must not share an expectation, but calling
Cavalli's sweepers slurves must not move anything, because no pitch changed.

Nothing at release separates a sweeper from a curveball (review Finding 9), so the model must
read something that comes from the movement. Today that is the tag NAME. Here the name is
never read:
  1. The tag only says which pitches belong together: a GROUP = one pitcher's pitches under one
     tag (30+ pitches).
  2. Each group is described by its own means: velocity below the pitcher's own 95th-percentile
     velocity, induced vertical break, arm-side horizontal break.
  3. SHAPE TYPES are learned from all groups in the league with no names: a Gaussian mixture
     with K components on those three numbers. A group belongs to every type with a share.
  4. One fit per shape type and hand on the shipped inputs (arm angle, extension, velocity),
     each pitch weighted by its group's share of that type. A pitch's expectation is the
     share-weighted mix of the type fits.
A rename leaves groups, means, shares and expectations exactly as they were. Moving pitches
between groups changes the groups, so it can move the expectation: that is measured too.

K is the one knob. Too few types and a sweeper shares a ghost with a curveball; too many and
the types follow single pitchers, so expected = actual and the arrow says nothing. Swept, with:
  sep       how often a group's top type holds one tag family apart (purity against the tags)
  agree     r of the group expectation with the shipped per-type expectation
  arrow     league SD of the group arrow, against the shipped SD
  rank      Spearman r of the within-tag rank of the arrow with the shipped rank
  BIC       the mixture's own fit criterion

  .venv/bin/python scripts/research/xmove/xmove_shape_types.py            # sweep K, tables
  .venv/bin/python scripts/research/xmove/xmove_shape_types.py plate 9 'Cavalli, Cade'
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_argv = sys.argv[:]
sys.argv = sys.argv[:1]                      # xmove_cavalli_proto reads --pitcher at import
sys.path.insert(0, HERE)
import xmove_cavalli_proto as CP  # noqa: E402
sys.argv = _argv

FEATS = ['aa_', 'ext_', 'velo_']
MIN_GROUP = 30
TYPES = ('FF', 'SI', 'FC', 'SL', 'ST', 'SV', 'CU', 'KC', 'CH', 'FS')
SEED = 0


def load():
    df = CP.load_2026().reset_index(drop=True)
    df = df[df['Pitch Type'].isin(TYPES)].reset_index(drop=True)
    df['dv'] = df['Velocity'] - df.groupby('Pitcher')['Velocity'].transform(lambda s: s.quantile(0.95))
    df['aa_'], df['ext_'], df['velo_'] = df['ArmAngle'], df['Extension'], df['Velocity']
    return df


def groups_of(df, col='Pitch Type'):
    g = df.groupby(['Pitcher', 'Throws', col]).agg(n=('ivb', 'size'), dv=('dv', 'mean'), ivb=('ivb', 'mean'), hb=('hb_s', 'mean')).reset_index()
    return g[g['n'] >= MIN_GROUP].reset_index(drop=True)


def fit_mixture(G, K):
    from sklearn.mixture import GaussianMixture
    X = G[['dv', 'ivb', 'hb']].values
    mu, sd = X.mean(0), X.std(0)
    gm = GaussianMixture(n_components=K, covariance_type='full', n_init=5, random_state=SEED).fit((X - mu) / sd)
    return gm, mu, sd


def shares(gm, mu, sd, G):
    return gm.predict_proba((G[['dv', 'ivb', 'hb']].values - mu) / sd)


def expectations(df, G, R, col='Pitch Type'):
    """Per-pitch (xIVB, xHB hand-signed) from the share-weighted type fits. R: group x K shares."""
    key = pd.MultiIndex.from_frame(G[['Pitcher', 'Throws', col]])
    pos = pd.Series(np.arange(len(G)), index=key)
    gi = pos.reindex(pd.MultiIndex.from_frame(df[['Pitcher', 'Throws', col]])).values
    ok = np.isfinite(gi)
    gi_ok = gi[ok].astype(int)
    X = np.column_stack([np.ones(ok.sum())] + [df[f].values[ok].astype('f8') for f in FEATS])
    thr = df['Throws'].values[ok]
    xi, xh = np.zeros(ok.sum()), np.zeros(ok.sum())
    for k in range(R.shape[1]):
        w = R[gi_ok, k]
        for hand in ('L', 'R'):
            m = thr == hand
            if w[m].sum() < 150:              # the same floor as the shipped model, in weighted pitches
                continue
            sw = np.sqrt(w[m])
            A = X[m] * sw[:, None]
            bi = np.linalg.lstsq(A, df['ivb'].values[ok][m] * sw, rcond=None)[0]
            bh = np.linalg.lstsq(A, df['hb_s'].values[ok][m] * sw, rcond=None)[0]
            xi[m] += w[m] * (X[m] @ bi)
            xh[m] += w[m] * (X[m] @ bh)
    oi, oh = np.full(len(df), np.nan), np.full(len(df), np.nan)
    oi[ok], oh[ok] = xi, xh
    return oi, oh


def shipped(df):
    return CP.score(df, CP.OLD, CP.fit_per_group(df, CP.OLD))


def unit_table(df, xi, xh, col='Pitch Type'):
    d = df.assign(xi=xi, xh=xh).dropna(subset=['xi', 'xh'])
    u = d.groupby(['Pitcher', 'Throws', col]).agg(n=('ivb', 'size'), ivb=('ivb', 'mean'), hb=('hb_s', 'mean'), xi=('xi', 'mean'), xh=('xh', 'mean'))
    u['oi'], u['oh'] = u['ivb'] - u['xi'], u['hb'] - u['xh']
    return u


def sweep():
    df = load()
    G = groups_of(df)
    si, sh = shipped(df)
    US = unit_table(df, si, sh)
    US = US[US['n'] >= 150]
    fam = {'FF': 'FF', 'SI': 'SI', 'FC': 'FC', 'SL': 'SL', 'ST': 'ST', 'SV': 'ST', 'CU': 'CU', 'KC': 'CU', 'CH': 'CH', 'FS': 'FS'}
    print(f'{len(df):,} pitches, {len(G):,} groups (pitcher x tag, {MIN_GROUP}+ pitches); shipped arrow SD {US.oi.std():.2f} ride / {US.oh.std():.2f} run\n')
    print(f'{"K":>3s}{"BIC":>9s}{"purity":>8s}{"ST v CU apart":>15s}{"agree ride/run":>16s}{"arrow SD ride/run":>19s}{"rank r ride/run":>17s}{"top share":>11s}')
    for K in (4, 6, 8, 9, 10, 12, 15, 20, 30):
        gm, mu, sd = fit_mixture(G, K)
        R = shares(gm, mu, sd, G)
        xi, xh = expectations(df, G, R)
        U = unit_table(df, xi, xh)
        U = U[U['n'] >= 150].join(US[['xi', 'xh', 'oi', 'oh']], rsuffix='_s', how='inner').reset_index()
        top = R.argmax(1)
        tagf = G['Pitch Type'].map(fam).values
        pur = np.mean([pd.Series(tagf[top == k]).value_counts(normalize=True).iloc[0] * (top == k).sum() for k in range(K) if (top == k).any()]) * K / len(G) \
            if False else sum(pd.Series(tagf[top == k]).value_counts().iloc[0] for k in range(K) if (top == k).any()) / len(G)
        # sweepers and curveballs: share of ST groups whose top type is NOT the most common top type of CU groups
        cu_top = pd.Series(top[tagf == 'CU']).mode().iloc[0]
        apart = float((top[tagf == 'ST'] != cu_top).mean())
        rk = []
        for a, b in (('oi', 'oi_s'), ('oh', 'oh_s')):
            rr = [U[U['Pitch Type'] == t][[a, b]].corr(method='spearman').iloc[0, 1] for t in ('FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS')
                  if (U['Pitch Type'] == t).sum() >= 30]
            rk.append(float(np.mean(rr)))
        print(f'{K:>3d}{gm.bic((G[["dv", "ivb", "hb"]].values - mu) / sd):>9.0f}{pur:>8.2f}{apart:>15.2f}'
              f'{f"{np.corrcoef(U.xi, U.xi_s)[0, 1]:.3f} / {np.corrcoef(U.xh, U.xh_s)[0, 1]:.3f}":>16s}{f"{U.oi.std():.2f} / {U.oh.std():.2f}":>19s}'
              f'{f"{rk[0]:.2f} / {rk[1]:.2f}":>17s}{R.max(1).mean():>11.2f}', flush=True)


def plate(K, pitcher):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    df = load()
    G = groups_of(df)
    gm, mu, sd = fit_mixture(G, K)
    R = shares(gm, mu, sd, G)
    df['xi_shape'], df['xh_shape'] = expectations(df, G, R)
    df['xi_ship'], df['xh_ship'] = shipped(df)
    p = df[df['Pitcher'] == pitcher]
    if p.empty:
        sys.exit(f'no 2026 MLB pitches for {pitcher}')
    s = p['s'].iloc[0]
    counts = p['Pitch Type'].value_counts()
    types = [t for t in CP.PITCH_ORDER if counts.get(t, 0) >= MIN_GROUP]
    # what each shape type is: its centre and the tags that fall in it
    cen = gm.means_ * sd + mu
    top = R.argmax(1)
    names = {}
    for k in range(K):
        vc = G['Pitch Type'][top == k].value_counts(normalize=True)
        names[k] = ' '.join(f'{t} {v:.0%}' for t, v in vc.head(3).items()) if len(vc) else '(empty)'
    print(f'shape types at K = {K} (centre: mph below own top, ride, arm-side run; the tags that land there):')
    for k in np.argsort(-cen[:, 1]):
        print(f'   type {k:>2d}: {cen[k, 0]:+5.1f} mph, {cen[k, 1]:+5.1f} ride, {cen[k, 2]:+5.1f} run   {(top == k).sum():>4d} groups   {names[k]}')
    gp = G[G['Pitcher'] == pitcher].reset_index()
    print(f'\n{pitcher} 2026')
    print(f'{"tag":>4s}{"n":>6s}{"actual":>14s}{"SHIPPED exp":>14s}{"arrow":>13s}{"SHAPE exp":>14s}{"arrow":>13s}   shares of shape types')
    panels = {'ship': [], 'shape': []}
    for t in types:
        g = p[p['Pitch Type'] == t]
        aI, aH = g['ivb'].mean(), g['xHorzBrk'].mean()
        line = f'{t:>4s}{len(g):>6d}{f"{aI:.1f} / {aH:.1f}":>14s}'
        for n in ('ship', 'shape'):
            eI, eH = g[f'xi_{n}'].mean(), (g[f'xh_{n}'] * s).mean()
            panels[n].append({'pt': t, 'aX': aH, 'aY': aI, 'eX': eH, 'eY': eI})
            line += f'{f"{eI:.1f} / {eH:.1f}":>14s}{f"{aI - eI:+.1f} / {aH - eH:+.1f}":>13s}'
        row = gp[gp['Pitch Type'] == t]
        if len(row):
            r = R[row['index'].iloc[0]]
            line += '   ' + ', '.join(f'type {k} {r[k]:.0%}' for k in np.argsort(-r)[:3] if r[k] >= 0.05)
        print(line)
    # renames and regroupings
    ren = df.copy()
    ren.loc[(ren['Pitcher'] == pitcher) & (ren['Pitch Type'] == 'ST'), 'Pitch Type'] = 'SV'
    G2 = groups_of(ren)
    x2i, x2h = expectations(ren, G2, shares(gm, mu, sd, G2))
    m = ((df['Pitcher'] == pitcher) & (df['Pitch Type'] == 'ST')).values
    if m.any():
        print(f'\nrename every sweeper to slurve: shape expectation moves {np.nanmax(np.abs(x2i[m] - df["xi_shape"].values[m])):.3f} in ride, '
              f'{np.nanmax(np.abs(x2h[m] - df["xh_shape"].values[m])):.3f} in run (largest single pitch; the type fits are not refit)')
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 7.2), facecolor=CP.BG)
    CP.draw_panel(axes[0], 'SHIPPED: one fit per pitch NAME', panels['ship'])
    CP.draw_panel(axes[1], f'SHAPE TYPES: the name is never read ({K} types)', panels['shape'])
    fig.suptitle(f'{pitcher.split(", ")[1]} {pitcher.split(", ")[0]}, 2026 (disc = actual, dashed ring = expected)', fontsize=13,
                 color=CP.TEXT_SECONDARY, fontweight='bold', y=0.98)
    fig.tight_layout(rect=(0, 0.02, 1, 0.95))
    out = os.path.expanduser(f'~/Downloads/xmove_shape_types_{pitcher.split(",")[0].lower().replace(" ", "")}.png')
    fig.savefig(out, dpi=150, facecolor=CP.BG)
    print(f'wrote {out}')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'plate':
        plate(int(sys.argv[2]), sys.argv[3])
    else:
        sweep()
