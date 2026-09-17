#!/usr/bin/env python3
"""locplus_bandwidth_surface_compare.py — LOOK at what a bandwidth change does
to the league Loc+ surface. (2026-09-17)

Builds the 2026 league surfaces twice (shipped bandwidth, candidate
bandwidth), evaluates lp.score_pitch at every cell centre for a few
(group, batter hand, pitcher hand, count) panels, and draws shipped /
candidate / difference on one shared colour scale per panel. Panels include
the thinnest pair (CH, LHP vs LHH), where smoothing does the most work.

ExpRV is hitter-positive runs per pitch: blue = good for the pitcher.

Usage:
  python3 scripts/research/locplus/locplus_bandwidth_surface_compare.py 9 0.55
Writes data/_loc_target_audit/prep/surface_compare_<bx>_<bz>.png
"""
import os
import pickle
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline.locplus as lp                           # noqa: E402
import locplus_fullseason_replicate as FR               # noqa: E402

# (group, bats, throws, count, title)
PANELS = [('FF', 'R', 'R', '0-0', 'FF  RHP vs RHH  0-0'),
          ('SL', 'R', 'R', '1-2', 'SL  RHP vs RHH  1-2'),
          ('CH', 'L', 'R', '0-0', 'CH  RHP vs LHH  0-0'),
          ('CH', 'L', 'L', '0-0', 'CH  LHP vs LHH  0-0 (thinnest pair)')]
SZ_BOT, SZ_TOP = 1.5, 3.5          # synthetic zone: only znorm matters to the surface
TYPE_OF = {'FF': 'FF', 'SL': 'SL', 'CH': 'CH'}


def grid(S, grp, bats, throws, count):
    out = np.full((lp.NZ, lp.NX), np.nan)
    for i in range(lp.NX):
        x = lp.X_MIN + (i + 0.5) * (lp.X_MAX - lp.X_MIN) / lp.NX
        for j in range(lp.NZ):
            zn = lp.Z_MIN + (j + 0.5) * lp.BIN_Z
            p = {'Pitch Type': TYPE_OF[grp], 'Bats': bats, 'Throws': throws, 'Count': count,
                 'PlateX': x, 'PlateZ': SZ_BOT + zn * (SZ_TOP - SZ_BOT),
                 'SzTop': SZ_TOP, 'SzBot': SZ_BOT}
            v = lp.score_pitch(p, S)
            if v is not None:
                out[j, i] = v
    return out


def main():
    bx, bz = float(sys.argv[1]), float(sys.argv[2])
    D = pickle.load(open(os.path.join(ROOT, FR.SEASONS[2026]), 'rb'))
    base = [p for p in D if p.get('_source') == 'MLB' and lp.is_eligible_baseline(p)]
    del D
    S0 = lp.build_surfaces(base, FR.LG, FR.SCALE)
    FR.apply({'PHYS_X_IN': bx, 'PHYS_Z_FRAC': bz})
    try:
        S1 = lp.build_surfaces(base, FR.LG, FR.SCALE)
    finally:
        FR.restore()
    ship = f'{FR.SHIPPED["PHYS_X_IN"]:g} in / {FR.SHIPPED["PHYS_Z_FRAC"]:g}'
    fig, axes = plt.subplots(3, len(PANELS), figsize=(4.0 * len(PANELS), 12.2))
    ext = [lp.X_MIN, lp.X_MAX, lp.Z_MIN, lp.Z_MAX]
    for c, (grp, bats, throws, count, title) in enumerate(PANELS):
        g0, g1 = grid(S0, grp, bats, throws, count), grid(S1, grp, bats, throws, count)
        lim = float(np.nanmax(np.abs(np.concatenate([g0.ravel(), g1.ravel()]))))
        dlim = float(np.nanmax(np.abs(g1 - g0)))
        for r, (g, lab, vm) in enumerate(((g0, f'shipped {ship}', lim),
                                          (g1, f'candidate {bx:g} in / {bz:g}', lim),
                                          (g1 - g0, 'candidate minus shipped', dlim))):
            ax = axes[r, c]
            im = ax.imshow(g, origin='lower', extent=ext, aspect='auto', cmap='RdBu_r',
                           vmin=-vm, vmax=vm, interpolation='nearest')
            ax.add_patch(Rectangle((-0.83, 0), 1.66, 1.0, fill=False, ec='k', lw=1.4))
            ax.set_title(f'{title}\n{lab}', fontsize=9)
            ax.set_xlabel('PlateX (ft, catcher view)', fontsize=8)
            ax.set_ylabel('height (zone fraction)', fontsize=8)
            fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
        print(f'{title:<38s} shipped range {np.nanmin(g0):+.3f}..{np.nanmax(g0):+.3f}  '
              f'candidate {np.nanmin(g1):+.3f}..{np.nanmax(g1):+.3f}  '
              f'max |diff| {dlim:.3f}  r {np.corrcoef(g0.ravel(), g1.ravel())[0, 1]:.3f}')
    fig.suptitle('League Loc+ ExpRV surface, 2026 (runs per pitch, hitter-positive: blue is good for the pitcher)',
                 fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out = os.path.join(ROOT, 'data', '_loc_target_audit', 'prep', f'surface_compare_{bx:g}_{bz:g}.png')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=110)
    print('wrote', out)


if __name__ == '__main__':
    main()
