#!/usr/bin/env python3
"""xmove_perpitch_physics_plate.py — per-pitch physics expectation with no names and no groups.

Wally, 2026-11-19: "why can't each pitch just be individual and you base the expected movement
off of the physics of the pitch? and then once I choose pitch types for them, the average
expected movement of those pitches is now the expected movement of that pitch type?"

That form, drawn. One model per hand on the 2026 MLB pitches, gradient boosting on what the
pitch IS at release: velocity, spin rate, release spin axis (cos, sin), arm angle, extension.
No pitch type and no pitcher grouping enter. Every pitch is scored by a model that never saw
its pitcher (two pitcher folds), so the model cannot learn one arm's movement by heart. The
expectation of "his sweeper" is the mean over whatever pitches carry that name: a rename or a
regroup cannot move any pitch's expectation.

Panel 1 is the shipped model for comparison. The console prints the league SD of the arrow
under both, so the size of an arrow has a ruler, and the largest arrows in the league.

  .venv/bin/python scripts/research/xmove/xmove_perpitch_physics_plate.py 'Cavalli, Cade' 'Fried, Max'
Output: ~/Downloads/xmove_perpitch_physics_<name>.png
"""
import os
import sys
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_argv = sys.argv[:]
sys.argv = sys.argv[:1]                      # xmove_cavalli_proto reads --pitcher at import
sys.path.insert(0, HERE)
import xmove_cavalli_proto as CP  # noqa: E402
sys.argv = _argv

FEATS = ['Velocity', 'Spin Rate', 'ct', 'st', 'ArmAngle', 'Extension']
TYPES = ('FF', 'SI', 'FC', 'SL', 'ST', 'SV', 'CU', 'KC', 'CH', 'FS')
MIN_SHOW = 30
MIN_UNIT = 150


def physics(df):
    """Tuned on held-out movement fit (xmove_physics_fit.py, 2026-11-19): one model for both hands on
    hand-signed inputs, 10 leaves, 200 rounds at learning rate 0.1, min leaf 200. Pitch-only inputs
    (Wally: no velocity against the pitcher's own top). Five pitcher folds: no pitch is scored by a
    model that saw its pitcher."""
    from sklearn.ensemble import HistGradientBoostingRegressor as H
    xi, xh = np.full(len(df), np.nan), np.full(len(df), np.nan)
    fold = np.array([zlib.crc32(str(p).encode()) % 5 for p in df['Pitcher']])
    X = df[FEATS].values.astype('f8')
    for f in range(5):
        tr, te = fold != f, fold == f
        for tgt, out in (('ivb', xi), ('hb_s', xh)):
            m = H(max_iter=200, learning_rate=0.1, max_leaf_nodes=10, min_samples_leaf=200, early_stopping=False, random_state=0)
            m.fit(X[tr], df[tgt].values[tr])
            out[te] = m.predict(X[te])
    return xi, xh


def main(pitchers):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    df = CP.load_2026().reset_index(drop=True)
    df = df[df['Pitch Type'].isin(TYPES)].reset_index(drop=True)
    df['ct'], df['st'] = np.cos(df['th']), np.sin(df['th'])
    df['xi_ship'], df['xh_ship'] = CP.score(df, CP.OLD, CP.fit_per_group(df, CP.OLD))
    df['xi_phys'], df['xh_phys'] = physics(df)
    for n in ('ship', 'phys'):
        df[f'oi_{n}'], df[f'oh_{n}'] = df['ivb'] - df[f'xi_{n}'], df['hb_s'] - df[f'xh_{n}']
    u = df.groupby(['Pitcher', 'Throws', 'Pitch Type']).agg(n=('ivb', 'size'), **{f'{a}_{n}': (f'{a}_{n}', 'mean') for a in ('oi', 'oh') for n in ('ship', 'phys')}).reset_index()
    u = u[u['n'] >= MIN_UNIT].dropna()
    print(f'{len(df):,} pitches of 2026. Per-pitch fit, R2 over all pitches: ride {1 - (df.oi_phys ** 2).sum() / ((df.ivb - df.ivb.mean()) ** 2).sum():.3f}, '
          f'run {1 - (df.oh_phys ** 2).sum() / ((df.hb_s - df.hb_s.mean()) ** 2).sum():.3f}; median miss per pitch {np.hypot(df.oi_phys, df.oh_phys).median():.1f} in')
    print(f'\nleague SD of the arrow by pitch type ({MIN_UNIT}+ pitches): ride / run, and r of the arrow with the shipped arrow')
    for t in ('FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS'):
        g = u[u['Pitch Type'] == t]
        print(f'   {t}: n {len(g):>3d}   shipped {g.oi_ship.std():.1f} / {g.oh_ship.std():.1f}   physics {g.oi_phys.std():.1f} / {g.oh_phys.std():.1f}   '
              f'r {np.corrcoef(g.oi_ship, g.oi_phys)[0, 1]:.2f} / {np.corrcoef(g.oh_ship, g.oh_phys)[0, 1]:.2f}')
    print('\nlargest arrows under physics (what the spin does not explain):')
    for t, col, lab, asc in (('SI', 'oi_phys', 'sinker, most drop beyond its spin', True), ('FF', 'oi_phys', 'four-seam, most ride beyond its spin', False),
                             ('ST', 'oh_phys', 'sweeper, most sweep beyond its spin', True), ('CH', 'oi_phys', 'changeup, most drop beyond its spin', True)):
        g = u[u['Pitch Type'] == t].sort_values(col, ascending=asc).head(5)
        print(f'   {lab}: ' + ', '.join(f'{r.Pitcher.split(",")[0]} {getattr(r, col):+.1f}' for r in g.itertuples()))
    for pitcher in pitchers:
        p = df[df['Pitcher'] == pitcher]
        if p.empty:
            print(f'no 2026 MLB pitches for {pitcher}')
            continue
        s = p['s'].iloc[0]
        counts = p['Pitch Type'].value_counts()
        types = [t for t in CP.PITCH_ORDER if counts.get(t, 0) >= MIN_SHOW]
        print(f'\n{pitcher} 2026 (ride / run, inches; pct = rank of the physics arrow among that pitch type, ride / run)')
        print(f'{"tag":>4s}{"n":>6s}{"actual":>14s}{"SHIPPED exp":>14s}{"arrow":>13s}{"PHYSICS exp":>14s}{"arrow":>13s}{"pct":>10s}')
        panels = {'ship': [], 'phys': []}
        for t in types:
            g = p[p['Pitch Type'] == t]
            aI, aH = g['ivb'].mean(), g['xHorzBrk'].mean()
            line = f'{t:>4s}{len(g):>6d}{f"{aI:.1f} / {aH:.1f}":>14s}'
            for n in ('ship', 'phys'):
                eI, eH = g[f'xi_{n}'].mean(), (g[f'xh_{n}'] * s).mean()
                panels[n].append({'pt': t, 'aX': aH, 'aY': aI, 'eX': eH, 'eY': eI})
                line += f'{f"{eI:.1f} / {eH:.1f}":>14s}{f"{aI - eI:+.1f} / {aH - eH:+.1f}":>13s}'
            pool = u[u['Pitch Type'] == t]
            if len(pool) >= 20:
                line += f'{f"{(pool.oi_phys < g.oi_phys.mean()).mean() * 100:.0f} / {(pool.oh_phys < g.oh_phys.mean()).mean() * 100:.0f}":>10s}'
            print(line)
        fig, axes = plt.subplots(1, 2, figsize=(13.5, 7.2), facecolor=CP.BG)
        CP.draw_panel(axes[0], 'SHIPPED: slot, extension, velocity, one fit per pitch NAME', panels['ship'])
        CP.draw_panel(axes[1], 'PER-PITCH PHYSICS, tuned: no name read', panels['phys'])
        fig.suptitle(f'{pitcher.split(", ")[1]} {pitcher.split(", ")[0]}, 2026 (disc = actual, dashed ring = expected)', fontsize=13,
                     color=CP.TEXT_SECONDARY, fontweight='bold', y=0.98)
        fig.text(0.5, 0.012, 'Right panel: each pitch has its own expectation; the ring is the mean over the pitches that carry the name. '
                 'The arrow is the movement the spin does not explain.', ha='center', fontsize=9, color=CP.TEXT_MUTED)
        fig.tight_layout(rect=(0, 0.07, 1, 0.95))
        out = os.path.expanduser(f'~/Downloads/xmove_physics_tuned_{pitcher.split(",")[0].lower().replace(" ", "")}.png')
        fig.savefig(out, dpi=150, facecolor=CP.BG)
        plt.close(fig)
        print(f'wrote {out}')


if __name__ == '__main__':
    main(sys.argv[1:] or ['Cavalli, Cade', 'Fried, Max'])
