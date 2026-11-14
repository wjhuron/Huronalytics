"""Count-aware location zones for one pitcher's pitch type against one batter hand.

Top row: where he actually threw it, per count state, each pitch coloured by
its own Loc+ atom (the per-pitch grade the leaderboard averages).
Bottom row: the shipped Loc+ value surface for that pitch group, batter hand
and pitcher hand, mixed over the counts inside each state in the proportions
HE threw them, and put on the same grade scale. Same model that graded him.

Count states are the site's (js/player-page.js, Usage by Count). They overlap.

    .venv/bin/python scripts/research/locplus/count_zone_map.py \
        --pitcher "Moll, Sam" --pt CH --bats R

Run `python3 -m pipeline.refresh_pickle` first. The figure goes to ~/Downloads.
"""
import argparse
import math
import os
import pickle
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Ellipse
from matplotlib.colors import TwoSlopeNorm, LinearSegmentedColormap

import pipeline.locplus as lp
from pipeline.utils import get_count, safe_float
import cards.pitcher as cp   # registers fonts, palette

STATES = {   # js/player-page.js, Usage by Count
    'Pitcher Ahead': ['0-1', '0-2', '1-2'],
    'Even': ['1-1', '2-2'],
    'Two-Strike': ['0-2', '1-2', '2-2', '3-2'],
}
# 50% probability ellipse of a bivariate normal: chi2(2) quantile at .5.
# A display convention (half his pitches inside), not a tuned value.
CHI2_50 = -2.0 * math.log(0.5)
TOP_FRAC = 0.10   # optimal-zone outline: best 10% of grid cells (convention)


ACTUAL_C = '#3d5f86'    # slate blue: where he threw it
OPTIMAL_C = cp.ACCENT   # terracotta: where the model says it plays best


def _density(px, pz, X, Z, top, bot):
    """His location density on the display grid. Gaussian kernel at the Loc+
    surfaces' own physical bandwidths (PHYS_X_IN, PHYS_Z_FRAC of zone height),
    so both layers are smoothed alike. Evaluated directly, with no edge clamp."""
    sx = lp.PHYS_X_IN / 12.0
    sz = lp.PHYS_Z_FRAC * (top - bot)
    d = np.zeros_like(X)
    for x0, z0 in zip(px, pz):
        d += np.exp(-0.5 * (((X - x0) / sx) ** 2 + ((Z - z0) / sz) ** 2))
    return d / d.sum()


def _hdr_level(d, mass):
    """Density level whose super-level set holds `mass` of the total."""
    v = np.sort(d.ravel())[::-1]
    return v[np.searchsorted(np.cumsum(v), mass)]


def _alpha_layer(rgb_hex, weight, max_alpha):
    from matplotlib.colors import to_rgb
    img = np.zeros(weight.shape + (4,))
    img[..., :3] = to_rgb(rgb_hex)
    img[..., 3] = np.clip(weight, 0, 1) * max_alpha
    return img


def render_overlay(a, panels, xs_c, zs_c, z_ft, top, bot, throws, n_all, who):
    from scipy.interpolate import RegularGridInterpolator
    half = 17 / 24
    gx = np.linspace(-2.0, 2.0, 321)
    gz = np.linspace(0.0, 4.6, 369)
    X, Z = np.meshgrid(gx, gz)
    zn_rows = z_ft(zs_c)
    fig, axes = plt.subplots(1, 3, figsize=(13, 6.9), facecolor=cp.BG)
    fig.subplots_adjust(left=0.05, right=0.98, top=0.76, bottom=0.12, wspace=0.08)
    for col, (ax, P) in enumerate(zip(axes, panels)):
        ax.set_facecolor(cp.PLOT_PANEL)
        # Optimal layer: the Loc+ surface, shown only above league average
        # (100), opacity rising to full at the state's best cell.
        # Past the grid, Loc+ grades a pitch at the edge cell (_xbin/_zbin
        # clamp), so the layer clamps the query point the same way.
        f = RegularGridInterpolator((zn_rows, xs_c), P['surf'])
        s = f(np.stack([np.clip(Z, zn_rows[0], zn_rows[-1]),
                        np.clip(X, xs_c[0], xs_c[-1])], axis=-1))
        best = np.nanmax(P['surf'])
        w_opt = np.where(np.isnan(s), 0, (s - 100) / (best - 100))
        ax.imshow(_alpha_layer(OPTIMAL_C, w_opt, 0.80), origin='lower',
                  extent=[gx[0], gx[-1], gz[0], gz[-1]], aspect='auto', zorder=1)
        # Actual layer: his density, opacity relative to its own peak.
        d = _density(P['px'], P['pz'], X, Z, top, bot)
        ax.imshow(_alpha_layer(ACTUAL_C, d / d.max(), 0.70), origin='lower',
                  extent=[gx[0], gx[-1], gz[0], gz[-1]], aspect='auto', zorder=2)
        # Outlines: best 10% of model cells; the area holding half his pitches.
        lvl = np.quantile(P['surf'], 1 - TOP_FRAC)
        ax.contour(*np.meshgrid(xs_c, zn_rows), P['surf'], levels=[lvl],
                   colors=[OPTIMAL_C], linewidths=2.4, zorder=4)
        ax.contour(X, Z, d, levels=[_hdr_level(d, 0.5)], colors=[ACTUAL_C],
                   linewidths=2.4, linestyles='--', zorder=4)
        bx, bz, bg = P['best']
        ax.plot(bx, bz, marker='*', color=OPTIMAL_C, ms=18, mec=cp.BG, mew=1.2, zorder=6)
        ax.plot(P['px'].mean(), P['pz'].mean(), marker='X', color=ACTUAL_C, ms=12,
                mec=cp.BG, mew=1.2, zorder=6)
        ax.add_patch(Rectangle((-half, bot), 2 * half, top - bot, fill=False,
                               ec=cp.TEXT_PRIMARY, lw=1.4, zorder=5))
        # Catcher view: flat front edge toward the pitcher, point toward the catcher.
        ax.plot([-half, half, half, 0, -half, -half], [0.5, 0.5, 0.38, 0.25, 0.38, 0.5],
                color=cp.TEXT_MUTED, lw=1, zorder=5)
        ax.set_xlim(-2.0, 2.0); ax.set_ylim(0.0, 4.6); ax.set_aspect('equal')
        ax.tick_params(colors=cp.TEXT_MUTED, labelsize=8)
        for s_ in ax.spines.values():
            s_.set_color(cp.SUBTLE_BORDER)
        if col:
            ax.set_yticklabels([])
        side = -1.85 if a.bats == 'R' else 1.85
        ax.text(side, 4.4, f'{a.bats}HH', ha='left' if side < 0 else 'right', va='top',
                fontsize=9, color=cp.TEXT_MUTED, family='IBM Plex Sans', weight='bold')
        mixs = ', '.join(f'{b}-{s} {w}' for (b, s), w in P['mix'].items())
        ax.set_title(f'{P["name"].upper()}\n', fontsize=13, color=cp.TEXT_PRIMARY,
                     family='Bitter', weight='black', loc='left')
        ax.text(0, 1.03, f'n={P["n"]}  ({mixs})', transform=ax.transAxes,
                fontsize=8.5, color=cp.TEXT_MUTED, family='IBM Plex Sans')
        ax.text(0.97, 0.10, f'his Loc+ {cp.half_up(P["loc"])}', transform=ax.transAxes,
                ha='right', fontsize=12, weight='bold', color=ACTUAL_C, family='Bitter')
        ax.text(0.97, 0.03, f'best spot {cp.half_up(bg)}', transform=ax.transAxes,
                ha='right', fontsize=10, weight='bold', color=OPTIMAL_C, family='IBM Plex Sans')
    fig.text(0.05, 0.93, f'{" ".join(who).upper()}  {a.pt} vs {a.bats}HH: WHERE HE THREW IT, WHERE IT PLAYS',
             fontsize=20, family='Bitter', weight='black', color=cp.TEXT_PRIMARY)
    fig.text(0.05, 0.885, f'2026 MLB  |  {throws}HP  |  {n_all} pitches  |  catcher view, feet',
             fontsize=10, family='IBM Plex Sans', color=cp.TEXT_MUTED)
    # legend
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    h = [Patch(fc=ACTUAL_C, alpha=0.7, label='his locations (density)'),
         Line2D([], [], color=ACTUAL_C, lw=2.4, ls='--', label='half his pitches'),
         Line2D([], [], color=ACTUAL_C, marker='X', ls='', ms=10, mec=cp.BG, label='his average spot'),
         Patch(fc=OPTIMAL_C, alpha=0.8, label='above-average value (Loc+ model)'),
         Line2D([], [], color=OPTIMAL_C, lw=2.4, label='best 10% of cells'),
         Line2D([], [], color=OPTIMAL_C, marker='*', ls='', ms=13, mec=cp.BG, label='best spot')]
    fig.legend(handles=h, loc='lower center', ncol=6, frameon=False, fontsize=8.8,
               bbox_to_anchor=(0.5, 0.035), prop={'family': 'IBM Plex Sans', 'size': 8.8})
    fig.text(0.05, 0.012, 'Optimal layer: shipped Loc+ surfaces, mixed over the counts in each state as he threw them. '
             'His density uses the same smoothing widths. Count states overlap, as on the site.',
             fontsize=8, family='IBM Plex Sans', color=cp.TEXT_FAINT)
    out = os.path.join(os.path.expanduser('~'), 'Downloads',
                       f'{who[-1].lower()}_{a.pt.lower()}_vs_{a.bats.lower()}hh_count_overlay.png')
    fig.savefig(out + '.tmp.png', dpi=150, facecolor=cp.BG)
    os.replace(out + '.tmp.png', out)
    print(f'  wrote {out}')


def load(path):
    D = pickle.load(open(path, 'rb'))
    dates = [p.get('Game Date') for p in D if p.get('_source') == 'MLB' and p.get('Game Date')]
    print(f'  pickle MLB date range {min(dates)} .. {max(dates)}, {len(D):,} rows')
    return D


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pitcher', required=True)
    ap.add_argument('--pt', required=True)
    ap.add_argument('--bats', required=True, choices=['L', 'R'])
    ap.add_argument('--layout', choices=['overlay', 'rows'], default='overlay',
                    help='overlay: one panel per state, both heat maps; rows: actual over optimal')
    ap.add_argument('--expect', type=float, default=None,
                    help='shipped per-type Loc+ to validate the replication against')
    a = ap.parse_args()

    D = load(os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl'))
    meta = json.load(open(os.path.join(ROOT, 'data', 'metadata_rs.json')))
    g = meta['gutsConstants']
    lg_woba, woba_scale = g['lgWOBA'], g['wOBAScale']

    # Same inputs as process_data: MLB pitches, position-player pitching out.
    ep = {(p.get('Pitcher'), p.get('PTeam')) for p in D if p.get('Pitch Type') == 'EP'}
    allp = [p for p in D if p.get('_source') == 'MLB'
            and (p.get('Pitcher'), p.get('PTeam')) not in ep]
    del D
    S = lp.build_surfaces([p for p in allp if lp.is_eligible_baseline(p)],
                          lg_woba, woba_scale)

    groups = defaultdict(list)
    for p in allp:
        if p.get('Pitch Type') != 'EP':
            groups[(p.get('Pitcher'), p.get('PTeam'), p.get('Pitch Type'),
                    p.get('Throws'))].append(p)
    # Combined 2TM/3TM rows, as process_data synthesizes them: the anchor pool
    # keeps a traded pitcher's combined row and drops his stint rows.
    teams = defaultdict(set)
    for (pi, t, _pt, th) in groups:
        teams[(pi, th)].add(t)
    for (pi, th), ts in teams.items():
        if len(ts) >= 2:
            lab = f'{len(ts)}TM'
            for (pi2, t, pt, th2), ps in list(groups.items()):
                if pi2 == pi and th2 == th and t in ts:
                    groups[(pi, lab, pt, th)].extend(ps)
    raw = lp._aggregate(groups, S)
    _, anchors = lp._normalize_by_group(
        raw, group_fn=lambda k: lp.group_of_code(k[2]), n_prior=lp.N_PRIOR_PT,
        min_pool=lp.MIN_POOL_PT, pool_filter=lambda k: k[1] not in lp.AAA_TEAMS,
        return_anchors=True)

    mine = [p for p in allp if p.get('Pitcher') == a.pitcher
            and p.get('Pitch Type') == a.pt and lp._is_scorable(p)]
    if not mine:
        raise SystemExit(f'no scorable {a.pt} for {a.pitcher}')
    grp = lp.group_of(mine[0])
    mu, sig = anchors[grp]
    grade = lambda v: 100.0 - lp.LOC_SCALE_K * (v - mu) / sig

    # Validation against the shipped per-type Loc+ (all batters).
    atoms = [int(round(grade(lp.score_pitch(p, S)))) for p in mine]
    rep = lp.int_mean_tenths_half_up(sum(atoms), len(atoms))
    print(f'  replicated {a.pt} Loc+ {rep} on {len(atoms)} pitches'
          + (f' (shipped {a.expect})' if a.expect is not None else ''))
    if a.expect is not None and abs(rep - a.expect) > 0.05:
        raise SystemExit('replication does not match the shipped value; stop')

    sub = [p for p in mine if p.get('Bats') == a.bats]
    throws = sub[0]['Throws']
    by_c = defaultdict(list)
    for p in sub:
        by_c[get_count(p)].append(int(round(grade(lp.score_pitch(p, S)))))
    print('  per count: ' + '  '.join(
        f'{b}-{s} n={len(v)} {sum(v) / len(v):.0f}' for (b, s), v in sorted(by_c.items())))
    key = (grp, a.bats, throws)
    top = np.mean([safe_float(p['SzTop']) for p in sub])
    bot = np.mean([safe_float(p['SzBot']) for p in sub])
    z_ft = lambda zn: bot + zn * (top - bot)

    def cell_grade(c, i, j):
        psw = S['SW'][key][c][i][j]; pwh = S['WH'][key][c][i][j]
        pfl = S['FL'][key][i][j]; pbip = max(0.0, 1.0 - pwh - pfl)
        vbip = S['XW'][key][i][j] + S['XWOFF'].get(c, 0.0) + S['BIPOFF'].get(c, 0.0)
        pcs = S['PCS'][a.bats][c][i][j]; RV = S['RV']
        sw = pwh * RV['whiff'][c] + pfl * RV['foul'][c] + pbip * vbip
        tk = pcs * RV['cs'][c] + (1 - pcs) * RV['ball'][c]
        return grade(psw * sw + (1 - psw) * tk)

    xs_c = lp.X_MIN + (np.arange(lp.NX) + 0.5) * lp.BIN_X
    zs_c = lp.Z_MIN + (np.arange(lp.NZ) + 0.5) * lp.BIN_Z

    panels = []
    for name, cl in STATES.items():
        cs = [tuple(int(x) for x in s.split('-')) for s in cl]
        pts = [p for p in sub if get_count(p) in cs]
        mix = {c: sum(1 for p in pts if get_count(p) == c) for c in cs}
        n = sum(mix.values())
        surf = np.zeros((lp.NZ, lp.NX))
        for c, w in mix.items():
            if w:
                for i in range(lp.NX):
                    for j in range(lp.NZ):
                        surf[j, i] += w / n * cell_grade(c, i, j)
        px = np.array([safe_float(p['PlateX']) for p in pts])
        pz = np.array([z_ft(lp._znorm(p)) for p in pts])
        pg = np.array([grade(lp.score_pitch(p, S)) for p in pts])
        at = [int(round(x)) for x in pg]
        j0, i0 = np.unravel_index(np.argmax(surf), surf.shape)
        print(f'  {name} surface quantiles 5/25/50/75/95: '
              f'{np.percentile(surf, [5, 25, 50, 75, 95]).round(0)}')
        panels.append(dict(name=name, n=n, mix=mix, surf=surf, px=px, pz=pz, pg=pg,
                           loc=lp.int_mean_tenths_half_up(sum(at), len(at)),
                           best=(xs_c[i0], z_ft(zs_c[j0]), surf[j0, i0]),
                           edge=(i0 in (0, lp.NX - 1) or j0 in (0, lp.NZ - 1))))
        print(f'  {name:14s} n={n:3d} mix={ {f"{b}-{s}": w for (b, s), w in mix.items()} } '
              f'Loc+ {panels[-1]["loc"]}  best cell x={xs_c[i0]:+.2f} z={z_ft(zs_c[j0]):.2f} '
              f'grade {surf[j0, i0]:.0f}{"  EDGE CELL" if panels[-1]["edge"] else ""}')

    who = a.pitcher.split(', ')[::-1]
    if a.layout == 'overlay':
        render_overlay(a, panels, xs_c, zs_c, z_ft, top, bot, throws, len(sub), who)
        return

    # ── render: two rows ────────────────────────────────────────────────
    cmap =LinearSegmentedColormap.from_list('loc', ['#3d5f86', '#9fb3c8', cp.BG, '#d9a08c', '#9f3026'])
    # Per-pitch grades span about -135..205 on this sample, so the scale is
    # 100 +/- 120. A display range, not a fitted value.
    norm = TwoSlopeNorm(vcenter=100, vmin=-20, vmax=220)
    fig, axes = plt.subplots(2, 3, figsize=(13, 10.4), facecolor=cp.BG)
    fig.subplots_adjust(left=0.05, right=0.92, top=0.86, bottom=0.07, wspace=0.08, hspace=0.22)
    half = 17 / 24
    ext = [lp.X_MIN, lp.X_MAX, z_ft(lp.Z_MIN), z_ft(lp.Z_MAX)]
    for col, P in enumerate(panels):
        for row, ax in enumerate(axes[:, col]):
            ax.set_facecolor(cp.PLOT_PANEL)
            if row == 1:
                ax.imshow(P['surf'], origin='lower', extent=ext, cmap=cmap, norm=norm,
                          aspect='auto', interpolation='bilinear')
                X, Z = np.meshgrid(xs_c, z_ft(zs_c))
                # Optimal zone = the best TOP_FRAC of grid cells for this state.
                # A display convention; the surface itself is the measurement.
                lvl = np.quantile(P['surf'], 1 - TOP_FRAC)
                ax.contour(X, Z, P['surf'], levels=[lvl], colors=[cp.TEXT_PRIMARY],
                           linewidths=[2.0])
                bx, bz, _bg = P['best']
                ax.plot(bx, bz, marker='*', color=cp.TEXT_PRIMARY, ms=16,
                        mec=cp.BG, mew=1, zorder=6)
            else:
                o = np.argsort(np.abs(P['pg'] - 100))
                ax.scatter(P['px'][o], P['pz'][o], c=P['pg'][o], cmap=cmap, norm=norm,
                           s=58, edgecolor=cp.TEXT_PRIMARY, linewidth=0.5, zorder=3)
            # his 50% ellipse and centre on both rows
            if len(P['px']) >= 3:
                cov = np.cov(P['px'], P['pz']); w, v = np.linalg.eigh(cov)
                ang = math.degrees(math.atan2(v[1, 1], v[0, 1]))
                ax.add_patch(Ellipse((P['px'].mean(), P['pz'].mean()),
                                     2 * math.sqrt(CHI2_50 * w[1]), 2 * math.sqrt(CHI2_50 * w[0]),
                                     angle=ang, fill=False, ec=cp.TEXT_PRIMARY, lw=1.6,
                                     ls='-' if row == 0 else ':', zorder=4))
                ax.plot(P['px'].mean(), P['pz'].mean(), marker='x', color=cp.TEXT_PRIMARY,
                        ms=9, mew=2, zorder=5)
            ax.add_patch(Rectangle((-half, bot), 2 * half, top - bot, fill=False,
                                   ec=cp.TEXT_PRIMARY, lw=1.4, zorder=2))
            # Catcher view: the flat front edge faces the pitcher (top of the
            # panel) and the point faces the catcher (bottom).
            ax.plot([-half, half, half, 0, -half, -half], [0.5, 0.5, 0.38, 0.25, 0.38, 0.5],
                    color=cp.TEXT_MUTED, lw=1)
            ax.set_xlim(-2.0, 2.0); ax.set_ylim(0.0, 4.6); ax.set_aspect('equal')
            ax.tick_params(colors=cp.TEXT_MUTED, labelsize=8)
            for s_ in ax.spines.values():
                s_.set_color(cp.SUBTLE_BORDER)
            if col:
                ax.set_yticklabels([])
            side = -1.85 if a.bats == 'R' else 1.85
            ax.text(side, 4.4, f'{a.bats}HH', ha='left' if side < 0 else 'right',
                    va='top', fontsize=9, color=cp.TEXT_MUTED, family='IBM Plex Sans', weight='bold')
        mixs = ', '.join(f'{b}-{s} {w}' for (b, s), w in P['mix'].items())
        axes[0, col].set_title(f'{P["name"].upper()}\n', fontsize=13, color=cp.TEXT_PRIMARY,
                               family='Bitter', weight='black', loc='left')
        axes[0, col].text(0, 1.035, f'n={P["n"]}  ({mixs})', transform=axes[0, col].transAxes,
                          fontsize=8.5, color=cp.TEXT_MUTED, family='IBM Plex Sans')
        axes[0, col].text(0.97, 0.03, f'Loc+ {cp.half_up(P["loc"])}', transform=axes[0, col].transAxes,
                          ha='right', fontsize=12, weight='bold', color=cp.TEXT_PRIMARY, family='Bitter')
        bx, bz, bg = P['best']
        axes[1, col].text(0.97, 0.03, f'best cell {cp.half_up(bg)}', transform=axes[1, col].transAxes,
                          ha='right', fontsize=10, weight='bold', color=cp.TEXT_PRIMARY, family='IBM Plex Sans')
    axes[0, 0].set_ylabel('ACTUAL: each pitch = its Loc+ grade', fontsize=9.5,
                          color=cp.TEXT_SECONDARY, family='IBM Plex Sans', weight='bold')
    axes[1, 0].set_ylabel('OPTIMAL: league value surface, his count mix', fontsize=9.5,
                          color=cp.TEXT_SECONDARY, family='IBM Plex Sans', weight='bold')
    cax = fig.add_axes([0.935, 0.2, 0.014, 0.55])
    cb = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), cax=cax)
    cb.set_label('Loc+ grade (100 = league avg)', color=cp.TEXT_SECONDARY, fontsize=9)
    cb.ax.tick_params(colors=cp.TEXT_MUTED, labelsize=8)
    fig.text(0.05, 0.955, f'{" ".join(who).upper()}  {a.pt} vs {a.bats}HH, BY COUNT',
             fontsize=22, family='Bitter', weight='black', color=cp.TEXT_PRIMARY)
    fig.text(0.05, 0.918, f'2026 MLB  |  {throws}HP  |  {len(sub)} pitches  |  catcher view, feet  |  '
             f'solid ellipse = half his pitches, x = his average spot',
             fontsize=10, family='IBM Plex Sans', color=cp.TEXT_MUTED)
    fig.text(0.05, 0.025, 'Bottom row: shipped Loc+ surfaces, mixed over the counts in each state as he threw them. '
             'Outline = best 10% of cells, star = best cell. Count states overlap, as on the site.',
             fontsize=8.5, family='IBM Plex Sans', color=cp.TEXT_FAINT)
    out = os.path.join(os.path.expanduser('~'), 'Downloads',
                       f'{who[-1].lower()}_{a.pt.lower()}_vs_{a.bats.lower()}hh_count_zones.png')
    fig.savefig(out + '.tmp.png', dpi=150, facecolor=cp.BG)
    os.replace(out + '.tmp.png', out)
    print(f'  wrote {out}')


if __name__ == '__main__':
    main()
