#!/usr/bin/env python3
"""HitterCards.py — Seasonal hitter cards.

Mirrors the visual grammar of Cards.py (pitcher cards) but reframed for
a hitter audience. Sections, top to bottom:

1. Pitch type color stripe (header band).
2. Identity zone (left): photo, name, "LHH | TEAM | Age", season label,
   headline stats strip
   (PA, AVG, OBP, SLG, BB%, K%, wRC+, SD+, CT+, BB+, Hitter+).
3. LA x Spray scatter (right): MLB wOBAcon zone heatmap, EV-colored dots,
   cyan Avg Placement marker, xwOBAsp annotation.
4. BIP donut + per-pitch-group composition bars (Hard / Breaking / Offspeed).
5. Per-pitch-group performance bars (vs RHP, vs LHP): bar length = usage,
   color = xwOBA performance.
6. Zone heat maps: 4-panel grid (Whiffs / Damage x vs RHP / vs LHP),
   Gaussian KDE density.
7. Contact Profile strip (7 cells): Bat Speed, Avg EV, Max EV,
   Squared-Up%, Blast%, IdealAtkAngle%, Air Pull%.
8. Hitter Performance Table:
   Pitch Group | Count | Usage | Swing% | Chase% | Whiff% | Hard-Hit%
   | Barrel% | xwOBAcon | xwOBAsp | RV/100 | xRV/100, plus Total row.
9. Huronalytics watermark.

Reuses helpers from Cards.py where the math is identical (xRV per pitch,
percentile cell coloring, headshot fetch).
"""

import argparse
import json
import os
import pickle
import sys
from collections import defaultdict
from math import atan2, pi

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch
from matplotlib.colors import LinearSegmentedColormap
import numpy as np

# Reuse helpers from Cards.py. BG/ACCENT/DARK_CELL/DARKER imported but
# immediately overridden below — Cards.py defines them for the dark-theme
# pitcher cards, but the hitter card now defaults to a warm-paper theme.
from Cards import (
    PITCH_COLORS, PITCH_NAMES,
    sf, fmt_fi, fetch_headshot, badge_text_color,
    pct_cell_color as _default_pct_cell_color,
    raw_cell_color as _default_raw_cell_color,
    OUTPUT_DIR, METADATA_PATH, _load_guts,
    is_barrel, compute_iz, _compute_pitch_xrv,
    GUTS_LG_WOBA, GUTS_WOBA_SCALE,
    SWING_DESC, STRIKE_DESC,
)

# ─────────────────────────────────────────────────────────────────────
# WARM PAPER THEME — the canonical hitter-card look.
#
# Magazine-paper aesthetic: cream background, deep-terracotta accent,
# warm near-black text. Distinctive from the cool dark-dashboard genre
# that every other analytics site uses.
# ─────────────────────────────────────────────────────────────────────
BG          = '#f0e8d8'   # warm cream paper background
DARK_CELL   = '#e2d8c4'   # slightly darker cream for cells
DARKER      = '#d8ccb4'   # deepest tan for headers and Total row
ACCENT      = '#9f3026'   # deep terracotta red


# Module-level wrappers — theme wrappers (e.g. warm_paper) can monkey-patch
# these with their own tinting functions to use lower-saturation palettes
# on light themes. Default behavior delegates to Cards.py.
#
# Both wrappers accept an optional `max_alpha` (default None → use Cards.py
# default of 0.55). Set lower (e.g. 0.40) to dampen specific strips like
# Contact Profile / Pitch Group so they don't compete with the heat maps
# and LA × Spray for visual attention.
def pct_cell_color(value_str, league_avg, row_bg_hex,
                    higher_is_better=True, max_alpha=None):
    if max_alpha is None:
        return _default_pct_cell_color(value_str, league_avg, row_bg_hex,
                                         higher_is_better)
    if league_avg is None or not value_str or value_str == '—':
        return None
    try:
        val = float(value_str.replace('%', ''))
    except (ValueError, AttributeError):
        return None
    avg_pct = league_avg * 100
    diff = val - avg_pct
    if not higher_is_better:
        diff = -diff
    intensity = max(-1.0, min(1.0, diff / 8.0))
    rb = int(row_bg_hex[1:3], 16)
    rg = int(row_bg_hex[3:5], 16)
    rbb = int(row_bg_hex[5:7], 16)
    if intensity >= 0:
        target = (0, 180, 0)
    else:
        target = (180, 0, 0); intensity = abs(intensity)
    alpha = intensity * max_alpha
    r = int(rb * (1 - alpha) + target[0] * alpha)
    g = int(rg * (1 - alpha) + target[1] * alpha)
    b = int(rbb * (1 - alpha) + target[2] * alpha)
    return f'#{r:02x}{g:02x}{b:02x}'


def raw_cell_color(value_str, league_avg, scale, higher_is_better,
                    row_bg_hex, max_alpha=None):
    if max_alpha is None:
        return _default_raw_cell_color(value_str, league_avg, scale,
                                         higher_is_better, row_bg_hex)
    if league_avg is None or not value_str or value_str == '—':
        return None
    # Re-use Cards.py's _parse_fi via the default function would be nice but
    # it's a private helper; reimplement value parsing inline.
    try:
        val = float(value_str)
    except (ValueError, AttributeError):
        return None
    diff = val - league_avg
    if not higher_is_better:
        diff = -diff
    intensity = max(-1.0, min(1.0, diff / scale))
    rb = int(row_bg_hex[1:3], 16)
    rg = int(row_bg_hex[3:5], 16)
    rbb = int(row_bg_hex[5:7], 16)
    if intensity >= 0:
        target = (0, 180, 0)
    else:
        target = (180, 0, 0); intensity = abs(intensity)
    alpha = intensity * max_alpha
    r = int(rb * (1 - alpha) + target[0] * alpha)
    g = int(rg * (1 - alpha) + target[1] * alpha)
    b = int(rbb * (1 - alpha) + target[2] * alpha)
    return f'#{r:02x}{g:02x}{b:02x}'


# Avg Placement marker color — deep purple. Cyan washes on cream paper;
# deep purple contrasts strongly without competing with the warm/red
# palette. Theme wrappers override for dark themes (cyan reads better).
MARKER_ACCENT = '#5d3b8e'

# ─────────────────────────────────────────────────────────────────────
# Layout constants
# ─────────────────────────────────────────────────────────────────────
FIG_W = 22
FIG_H = 18
DPI = 100
SAVE_DPI = 150
PLATE_HALF = 17 / 12 / 2  # half-plate width in feet

# Pitch grouping (Hard / Breaking / Offspeed). KN included in Offspeed.
PITCH_GROUPS = {
    'Hard':     ['FF', 'SI'],
    'Breaking': ['FC', 'SL', 'ST', 'CU', 'SV'],
    'Offspeed': ['CH', 'FS', 'KN'],
}
GROUP_ORDER = ['Hard', 'Breaking', 'Offspeed']
GROUP_COLORS = {
    'Hard':     '#3b82f6',  # blue
    'Breaking': '#a78bfa',  # purple
    'Offspeed': '#f59e0b',  # orange
}

# Bat-ball type constants (mirrors Cards.py)
BB_COLORS = {
    'ground_ball': '#06b6d4',
    'line_drive':  '#f97316',
    'fly_ball':    '#a78bfa',
    'popup':       '#fbbf24',
}
BB_LABELS = {
    'ground_ball': 'Ground Ball',
    'line_drive':  'Line Drive',
    'fly_ball':    'Fly Ball',
    'popup':       'Popup',
}
BB_TYPES = ['ground_ball', 'line_drive', 'fly_ball', 'popup']

# Headline stats coloring rule:
#   key  -> (hitter-row metric key, type, higher_is_better, scale)
# 'pct' = stored as decimal (.234), displayed as 23.4%; pct_cell_color picks scale.
# 'raw' = displayed as raw number; scale below sets ±intensity.
HITTER_STAT_LINE_COLOR = {
    'AVG':     ('avg',        'raw', True,  0.05),
    'OBP':     ('obp',        'raw', True,  0.05),
    'SLG':     ('slg',        'raw', True,  0.10),
    'BB%':     ('bbPct',      'pct', True),
    'K%':      ('kPct',       'pct', False),
    'wRC+':    ('wRCplus',    'raw', True,  20),
    'SD+':     ('sdPlus',     'raw', True,  10),
    'CT+':     ('ctPlus',     'raw', True,  10),
    'BB+':     ('bbPlus',     'raw', True,  10),
    'Hitter+': ('hitterPlus', 'raw', True,  10),
}

# Headline stat order — MLB default. ROC overrides this since the + family
# and bat-tracking metrics aren't computed for AAA.
HEADLINE_STATS_MLB = ['PA', 'AVG', 'OBP', 'SLG', 'BB%', 'K%', 'SD+', 'CT+', 'BB+', 'Hitter+']
HEADLINE_STATS_ROC = ['PA', 'AVG', 'OBP', 'SLG', 'BB%', 'K%', 'wRC+']
HEADLINE_STATS = HEADLINE_STATS_MLB  # default; render switches based on team

# ─────────────────────────────────────────────────────────────────────
# Theme variables — warm-paper defaults. Theme wrappers (e.g.
# HitterCards_light_gray.py, HitterCards_vintage.py) can override these
# for alternate looks.
# ─────────────────────────────────────────────────────────────────────
TEXT_PRIMARY       = '#1a1612'      # warm near-black (name, headline values)
TEXT_SECONDARY     = '#3a3530'      # deep warm gray (section titles, headers)
TEXT_MUTED         = '#6a5f55'      # mid warm gray (annotations, axes)
TEXT_FAINT         = '#8a7f75'      # light warm gray (bipnote, fine print)
TEXT_DIMMED        = '#9f9890'      # very light warm gray (legend captions)
SUBTLE_BORDER      = '#c5b89f'      # light tan border (cell edges)
TOTAL_BORDER       = '#6a5f55'      # mid-dark for Total row distinction
ALT_ROW_BG         = '#e8dfcb'      # slightly off DARK_CELL (alt rows)
GRID_COLOR         = '#3a3530'      # dark grid on cream bg
TICK_COLOR         = '#6a5f55'      # spray-chart axis ticks
SPINE_COLOR        = '#8a7f75'      # axis spine
PHOTO_BORDER       = '#6a5f55'      # photo edge
PERCENTILE_NEUTRAL = '#8a7f75'      # fallback when xwOBAsp_pctl is None

# Heat-map colormap — saturated diverging blue → red with NO white middle.
# Skipping the white midpoint means neutral data still shows color (light
# blue / soft red) instead of fading to bg. Heat maps stay bold across
# their entire data region — extremes pop AND neutral zones stay visible.
HEAT_BLUE_DARK    = '#08306b'   # cold extreme
HEAT_BLUE_MID     = '#3a6fa8'   # mid blue
HEAT_BLUE_LIGHT   = '#7eaad6'   # light blue (no white)
HEAT_RED_LIGHT    = '#f0a89c'   # soft red (no white)
HEAT_RED_MID      = '#c43d2e'   # mid red
HEAT_RED_DARK     = '#67000d'   # hot extreme


def make_heat_cmap(_bg_hex_unused=None):
    """Build a saturated blue → red diverging colormap with no white
    transition zone. Neutral data renders as light blue / soft red
    instead of fading away."""
    return LinearSegmentedColormap.from_list(
        'heatmap',
        [(0.00, HEAT_BLUE_DARK),
         (0.20, HEAT_BLUE_MID),
         (0.45, HEAT_BLUE_LIGHT),
         (0.55, HEAT_RED_LIGHT),
         (0.80, HEAT_RED_MID),
         (1.00, HEAT_RED_DARK)],
        N=256,
    )


HEAT_CMAP = make_heat_cmap()

# Zone-wOBAcon colormap (LA x Spray underlay) — EXACT match to hitter page
# js/player-page.js sacqZones plugin's wobaColorRGB function:
#   t=0.00  -> rgb(  8, 48,107)
#   t=0.35  -> rgb( 38,148,147)
#   t=0.55  -> rgb(238,228, 47)
#   t=1.00  -> rgb(215, 48, 39)
WOBA_CMAP = LinearSegmentedColormap.from_list(
    'woba',
    [(0.00, (8/255,   48/255, 107/255)),
     (0.35, (38/255, 148/255, 147/255)),
     (0.55, (238/255, 228/255,  47/255)),
     (1.00, (215/255,  48/255,  39/255))],
    N=256,
)


# ─────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────
def load_pitch_data(path='/Users/wallyhuron/Huronalytics/data/all_pitches_rs_cache.pkl'):
    with open(path, 'rb') as f:
        return pickle.load(f)


def load_hitter_leaderboard(path='/Users/wallyhuron/Huronalytics/data/hitter_leaderboard_rs.json'):
    with open(path) as f:
        return json.load(f)


def load_metadata(path=METADATA_PATH):
    with open(path) as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────
# Spray angle / SACQ zones
# ─────────────────────────────────────────────────────────────────────
HP_X, HP_Y = 125.42, 198.27  # home-plate origin in HC space (matches website)


def spray_angle(hc_x, hc_y):
    if hc_x is None or hc_y is None:
        return None
    dx = hc_x - HP_X
    dy = HP_Y - hc_y
    if dy <= 0:
        return None
    return atan2(dx, dy) * 180 / pi


def spray_direction(angle, bats):
    if angle is None or not bats:
        return None
    if bats == 'R':
        if angle < -30: return 'pull'
        if angle < -15: return 'pull_side'
        if angle < 0:   return 'center_pull'
        if angle < 15:  return 'center_oppo'
        if angle < 30:  return 'oppo_side'
        return 'oppo'
    else:
        if angle > 30:  return 'pull'
        if angle > 15:  return 'pull_side'
        if angle > 0:   return 'center_pull'
        if angle > -15: return 'center_oppo'
        if angle > -30: return 'oppo_side'
        return 'oppo'


LA_BINS = [(-9999, 0), (0, 5), (5, 10), (10, 15), (15, 20),
           (20, 25), (25, 30), (30, 35), (35, 40), (40, 50), (50, 9999)]


def la_bin_idx(la):
    for i, (lo, hi) in enumerate(LA_BINS):
        if lo <= la < hi:
            return i
    return None


def build_sacq_lookup(metadata, bats):
    """Returns a lookup function (spray_dir, la_bin) -> wOBAcon, hand-specific
    with pooled fallback. Mirrors the website's sacqLookup."""
    zones = metadata.get('sacqZones', [])
    hand_map, pool_map = {}, {}
    for z in zones:
        key = (z['spray'], z['laBin'])
        if z.get('bats') == bats:
            hand_map[key] = z
        elif z.get('bats') is None:
            pool_map[key] = z
    MIN_BIP = 20

    def lookup(direction, lb):
        if direction is None or lb is None: return None
        z = hand_map.get((direction, lb))
        if z and z.get('count', 0) >= MIN_BIP:
            v = z.get('wobacon')
            if v is None: v = z.get('woba')
            if v is not None: return v
        z = pool_map.get((direction, lb))
        if z and z.get('count', 0) >= MIN_BIP:
            v = z.get('wobacon')
            if v is None: v = z.get('woba')
            if v is not None: return v
        return None

    return lookup, hand_map, pool_map


# ─────────────────────────────────────────────────────────────────────
# Per-pitch stat computation helpers
# ─────────────────────────────────────────────────────────────────────
def compute_group_stats(group_pitches, sacq_lookup, bats):
    """Compute the per-pitch-group row for the bottom table.
    Returns dict with: count, usagePct (caller fills in), swingPct, chasePct,
    whiffPct, hardHitPct, barrelPct, xwOBAcon, xwOBAsp, rv100, xRv100."""
    n = len(group_pitches)
    if n == 0:
        return None
    swings = [p for p in group_pitches if p.get('Description') in SWING_DESC]
    whiffs = [p for p in group_pitches if p.get('Description') == 'Swinging Strike']
    iz = [p for p in group_pitches if compute_iz(p) is True]
    ooz_swings = [p for p in swings if compute_iz(p) is False]
    ooz_total = sum(1 for p in group_pitches if compute_iz(p) is False)

    # Contact-quality rates use BIP (excluding bunts) with valid EV as denom
    bip = [p for p in group_pitches
           if p.get('Description') == 'In Play'
           and p.get('BBType') and not str(p.get('BBType', '')).startswith('bunt')]
    evs = [(sf(p.get('ExitVelo')), p) for p in bip]
    evs_valid = [(v, p) for v, p in evs if v is not None]
    n_ev = len(evs_valid)
    n_hh = sum(1 for v, _ in evs_valid if v >= 95.0)
    n_brl = sum(1 for v, p in evs_valid if is_barrel(v, sf(p.get('LaunchAngle'))))

    # Avg EV / Max EV — population-wide mean / max ExitVelo for the group.
    # Used directly for ROC (where xwOBAcon is null) and as cross-check
    # context for MLB.
    avg_ev = sum(v for v, _p in evs_valid) / n_ev if n_ev else None
    max_ev = max((v for v, _p in evs_valid), default=None)

    # Air Pull% — fraction of BIPs that are in-the-air (LA >= 25°) AND
    # pulled (pull or pull_side spray direction).
    n_airpull = 0
    n_bip_with_ang = 0
    for p in bip:
        la = sf(p.get('LaunchAngle'))
        ang = spray_angle(sf(p.get('HC_X')), sf(p.get('HC_Y')))
        sd = spray_direction(ang, bats)
        if la is None or sd is None:
            continue
        n_bip_with_ang += 1
        if la >= 25 and sd in ('pull', 'pull_side'):
            n_airpull += 1
    air_pull_pct = (n_airpull / n_bip_with_ang) if n_bip_with_ang else None

    # xwOBAcon: average xwOBA on BIP with non-null xwOBA
    bip_xw = [sf(p.get('xwOBA')) for p in bip]
    bip_xw = [v for v in bip_xw if v is not None]
    xwobacon = sum(bip_xw) / len(bip_xw) if bip_xw else None

    # xwOBAsp: average SACQ-zone wOBA across this group's BIPs.
    xw_sp_vals = []
    for p in bip:
        la = sf(p.get('LaunchAngle'))
        ang = spray_angle(sf(p.get('HC_X')), sf(p.get('HC_Y')))
        sd = spray_direction(ang, bats)
        lb = la_bin_idx(la) if la is not None else None
        v = sacq_lookup(sd, lb)
        if v is not None:
            xw_sp_vals.append(v)
    xwobasp = sum(xw_sp_vals) / len(xw_sp_vals) if xw_sp_vals else None

    # Run values: PitchRV/100 (actual outcomes) + xPitchRV/100 (xwOBA model on BIP)
    actual_rvs = [sf(p.get('RunExp')) for p in group_pitches]
    actual_rvs = [v for v in actual_rvs if v is not None]
    rv100 = -round(sum(actual_rvs) / n * 100, 1) if actual_rvs and n else None
    # Note: RunExp is from pitcher perspective in the sheet. Negate for hitter.
    x_rvs = _compute_pitch_xrv(group_pitches)
    # xRV from _compute_pitch_xrv is pitcher-perspective (positive = good for
    # pitcher). Flip sign so hitter card displays hitter-positive values.
    xRv100 = -round(sum(x_rvs) / n * 100, 1) if x_rvs and n else None

    return {
        'count': n,
        'swingPct': len(swings) / n if n else None,
        'chasePct': len(ooz_swings) / ooz_total if ooz_total else None,
        'whiffPct': len(whiffs) / len(swings) if swings else None,
        'hardHitPct': n_hh / n_ev if n_ev else None,
        'barrelPct': n_brl / n_ev if n_ev else None,
        'xwOBAcon': xwobacon,
        'xwOBAsp':  xwobasp,
        'rv100':    rv100,
        'xRv100':   xRv100,
        'avgEV':       avg_ev,
        'maxEV':       max_ev,
        'airPullPct':  air_pull_pct,
        # Carry forward for downstream charts
        '_bip':     bip,
        '_swings':  swings,
        '_whiffs':  whiffs,
    }


# ─────────────────────────────────────────────────────────────────────
# Hand-rolled Gaussian KDE for zone heat maps (no scipy)
# ─────────────────────────────────────────────────────────────────────
def kde_grid(points, weights, x_min, x_max, z_min, z_max,
             n_grid=120, bandwidth=0.15, normalize=True):
    """Return a (n_grid, n_grid) density array.
    points: list of (x, z) tuples. weights: list of floats or None for uniform.
    normalize: if True, scale grid max to 1.0 (per-panel relative density).
    Set normalize=False to keep raw weighted-sum values for ratio math."""
    if not points:
        return None
    bw2 = 2 * bandwidth ** 2
    pts_x = np.array([p[0] for p in points])
    pts_z = np.array([p[1] for p in points])
    pts_w = np.array(weights) if weights is not None else np.ones(len(points))
    xs = np.linspace(x_min, x_max, n_grid)
    zs = np.linspace(z_min, z_max, n_grid)
    grid = np.zeros((n_grid, n_grid))
    for iz, z in enumerate(zs):
        for ix, x in enumerate(xs):
            dx = x - pts_x
            dz = z - pts_z
            grid[iz, ix] = float(np.sum(pts_w * np.exp(-(dx * dx + dz * dz) / bw2)))
    if normalize and grid.max() > 0:
        grid /= grid.max()
    return grid


def render_rate_kde_to_axes(ax, num_points, num_weights,
                             den_points, den_weights,
                             x_min, x_max, z_min, z_max,
                             sz_top, sz_bot, label, sample_label,
                             scale_max=1.0, scale_min=0.0,
                             mask_threshold=0.05, min_n=5):
    """Render a SMOOTHED RATE field via two KDEs.
    rate(x, z) = K_num(x, z) / K_den(x, z)

    For DAMAGE: num=BIPs weighted by xwOBA, den=BIPs unweighted, scale_max=1.0
                → mean xwOBA per location (absolute scale anchored at MLB avg
                via WOBA_CMAP — weak hitters render mostly cool, strong hitters red)
    For WHIFFS: num=whiffs (weight=1), den=swings (weight=1), scale_max=0.6
                → whiff rate per location (cool below MLB ~25%, red above ~36%)

    Alpha is gated by the denominator KDE so regions with too few events fade
    out — the panel only "speaks" where there's enough signal.
    """
    # Transparent panel — lets the figure background (with subtle radial
    # gradient) show through. Avoids visible rectangle frames where the
    # panel's flat color doesn't perfectly match the gradient.
    ax.set_facecolor('none')
    if num_points and den_points and len(num_points) >= min_n:
        # Compute both KDEs raw (unnormalized so the ratio is meaningful)
        num_grid = kde_grid(num_points, num_weights,
                             x_min, x_max, z_min, z_max, normalize=False)
        den_grid = kde_grid(den_points, den_weights,
                             x_min, x_max, z_min, z_max, normalize=False)
        # Ratio = smoothed local rate (mean weight per event in that area)
        # Guard division-by-zero — set rate to 0 where denominator is essentially nil
        eps = 1e-9
        rate = np.where(den_grid > eps, num_grid / den_grid, 0.0)
        # Map rate → colormap input [0, 1] using absolute scale_max
        # WOBA_CMAP is anchored: 0=blue, 0.35=teal, 0.55=yellow, 1.0=red.
        # For DAMAGE (scale_max=1.0): rate=.37 (MLB) → 0.37 input → teal/yellow boundary
        # For WHIFFS (scale_max=0.6): rate=.252 (MLB) → 0.42 → teal-yellow boundary
        # Use HEAT_CMAP (navy → light blue → white → red) — matches the
        # website's swing-heat-map color scheme. With absolute scaling, weak
        # hitters' bins stay in the cool blue range (no white/red).
        # Normalize: (rate - scale_min) / (scale_max - scale_min). For most
        # metrics scale_min=0; for ROC's Avg-EV damage panel, scale_min=50
        # so the cmap input maps EV ∈ [50, 110] → [0, 1].
        scale_range = max(scale_max - scale_min, 1e-9)
        normalized_rate = np.clip((rate - scale_min) / scale_range, 0.0, 1.0)
        rgba = HEAT_CMAP(normalized_rate)
        # Alpha mask — fade regions where denominator is below threshold (low data)
        den_peak = den_grid.max() if den_grid.max() > 0 else 1.0
        den_rel = den_grid / den_peak  # [0, 1]
        # Linear ramp above threshold, smoothed with gamma
        alpha = np.clip((den_rel - mask_threshold) / (1.0 - mask_threshold), 0, 1)
        # Gamma 0.15 = very aggressive ramp — colors hit full saturation
        # quickly so almost the entire data region shows bold color
        # instead of feathering out toward bg.
        alpha = np.power(alpha, 0.15)
        rgba[..., 3] = alpha
        # Smooth bilinear interpolation with tight bandwidth (0.18) and high
        # resolution (120×120 grid). This produces the TruMedia "cloud of
        # detail" look — many small hot/cold atoms with feathered edges
        # rather than one big wavy blob.
        ax.imshow(rgba, origin='lower', extent=[x_min, x_max, z_min, z_max],
                  aspect='auto', interpolation='bilinear')
    else:
        ax.text(0.5, 0.5, 'n = ' + str(len(num_points or [])) + ' (insufficient)',
                transform=ax.transAxes, color=TEXT_DIMMED, ha='center',
                fontstyle='italic', fontfamily='Avenir Next')
    # Strike-zone overlay — alpha 0.85 (was 0.95) softens the outline
    # slightly so it doesn't read as harsh against the saturated heat blobs.
    ax.add_patch(Rectangle((-PLATE_HALF, sz_bot), PLATE_HALF * 2, sz_top - sz_bot,
                            fill=False, edgecolor=GRID_COLOR, linewidth=1.8,
                            alpha=0.85, zorder=10))
    ax.set_xlim(x_min, x_max); ax.set_ylim(z_min, z_max)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values(): s.set_visible(False)
    # Title — bigger, brighter for visibility against saturated panels
    ax.set_title(label, color=TEXT_PRIMARY, fontsize=13, fontweight='700',
                 fontfamily='Avenir Next', pad=8)
    # Sample-size annotation — backdrop alpha 0.65 (was 0.85) is more
    # subtle, less visible-pill feel.
    ax.text(0.02, 0.97, sample_label, transform=ax.transAxes,
            color=TEXT_MUTED, fontsize=11, fontweight='600',
            fontfamily='Avenir Next', va='top', ha='left',
            bbox=dict(facecolor=BG, edgecolor='none', alpha=0.65,
                       boxstyle='round,pad=0.25'),
            zorder=11)


# ─────────────────────────────────────────────────────────────────────
# Format helpers
# ─────────────────────────────────────────────────────────────────────
def fmt_3dec(v):
    if v is None: return '—'
    s = f"{v:.3f}"
    if s.startswith('0.'): s = s[1:]
    if s.startswith('-0.'): s = '-' + s[2:]
    return s


def fmt_pct(v, decimals=1):
    if v is None: return '—'
    return f"{v * 100:.{decimals}f}%"


def fmt_int(v):
    if v is None: return '—'
    return str(int(round(v)))


def fmt_signed_decimal(v, decimals=1):
    if v is None: return '—'
    return f"{v:.{decimals}f}"


# ─────────────────────────────────────────────────────────────────────
# Card render
# ─────────────────────────────────────────────────────────────────────
def render_hitter_card(hitter_name, team_abbrev=None, year_label='2026 Season',
                       output_dir=OUTPUT_DIR):
    print(f"Generating hitter card: {hitter_name} ({team_abbrev or 'auto'}) — {year_label}")

    # Load data
    print("  Loading pitch cache + leaderboard + metadata...")
    all_pitches = load_pitch_data()
    hitter_lb = load_hitter_leaderboard()
    metadata = load_metadata()

    # Find hitter row
    hitter_rows = [r for r in hitter_lb if r.get('hitter') == hitter_name]
    if team_abbrev:
        hitter_rows = [r for r in hitter_rows if r.get('team') == team_abbrev]
    if not hitter_rows:
        print(f"  ERROR: {hitter_name} not found in leaderboard")
        return False
    if len(hitter_rows) > 1:
        # Prefer single-team row over multi-team aggregate
        single = [r for r in hitter_rows if not (str(r.get('team', '')).endswith('TM'))]
        hitter_rows = single or hitter_rows
    h_row = hitter_rows[0]
    team = h_row.get('team') or team_abbrev or '???'
    bats = h_row.get('stands') or 'R'

    # Filter pitches to this hitter (and team if specified)
    hitter_pitches = [p for p in all_pitches
                      if p.get('Batter') == hitter_name
                      and (not team_abbrev or p.get('BTeam') == team_abbrev)]
    if not hitter_pitches:
        print(f"  ERROR: no pitches found for {hitter_name}")
        return False
    print(f"  {len(hitter_pitches)} pitches faced")

    # Compute SzTop/SzBot (already constant per hitter in current data)
    sz_tops = [v for v in (sf(p.get('SzTop')) for p in hitter_pitches) if v is not None]
    sz_bots = [v for v in (sf(p.get('SzBot')) for p in hitter_pitches) if v is not None]
    sz_top = float(np.mean(sz_tops)) if sz_tops else 3.5
    sz_bot = float(np.mean(sz_bots)) if sz_bots else 1.5

    # Headshot
    mlb_id = h_row.get('mlbId')
    headshot = fetch_headshot(mlb_id) if mlb_id else None
    if headshot is None:
        from PIL import Image
        headshot = Image.new('RGB', (180, 180), (50, 50, 50))

    # Display name (FIRST LAST)
    parts = hitter_name.split(', ')
    display_name = (parts[1] + ' ' + parts[0]).upper() if len(parts) == 2 else hitter_name.upper()

    # Age — fetch from MLB API
    age = h_row.get('age')
    if not age and mlb_id:
        try:
            from Cards import fetch_player_metadata
            meta = fetch_player_metadata(mlb_id)
            age = meta.get('age', '—')
        except Exception:
            age = '—'
    if not age:
        age = '—'

    # ─── Set up the figure ─────────────────────────────────────────
    fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=DPI)
    fig.patch.set_facecolor(BG)

    # Subtle radial-gradient background for depth — slightly lighter at center,
    # darker at edges. Painted at the very back so all other axes draw on top.
    # BG rgb derived from the BG hex constant so theme overrides flow through.
    ax_bg = fig.add_axes([0, 0, 1, 1], zorder=-100)
    ax_bg.axis('off')
    n_bg = 200
    _xs, _ys = np.meshgrid(np.linspace(-1, 1, n_bg), np.linspace(-1, 1, n_bg))
    _d = np.sqrt(_xs ** 2 + _ys ** 2) / np.sqrt(2)
    _lift = (1.0 - _d) * 0.045
    _bg_hex = BG.lstrip('#')
    bg_rgb = (int(_bg_hex[0:2], 16) / 255,
              int(_bg_hex[2:4], 16) / 255,
              int(_bg_hex[4:6], 16) / 255)
    bg_grad = np.zeros((n_bg, n_bg, 3))
    for ci in range(3):
        bg_grad[..., ci] = np.clip(bg_rgb[ci] + _lift, 0, 1)
    ax_bg.imshow(bg_grad, extent=[0, 1, 0, 1], aspect='auto',
                  origin='lower', interpolation='bilinear')

    ax_main = fig.add_axes([0, 0, 1, 1])
    ax_main.set_xlim(0, FIG_W); ax_main.set_ylim(0, FIG_H)
    ax_main.axis('off')
    # Don't fill ax_main background — let the radial gradient show through

    # Layout anchors (the rainbow header stripe was cut — kept the position
    # variables since the photo + identity zone positions reference them).
    stripe_left = 0.01 * FIG_W
    stripe_right = 0.99 * FIG_W
    stripe_y = FIG_H - 0.20      # was 0.30; pulled up since no stripe

    # ─── Identity zone (top-left) ───────────────────────────────────
    photo_left = stripe_left
    photo_top = stripe_y - 0.05      # nudged up; gap below photo widened
                                      # via stat_y_header offset below
    photo_w = 2.0
    photo_h = photo_w * headshot.size[1] / headshot.size[0]
    photo_bottom = photo_top - photo_h
    ax_main.imshow(np.array(headshot),
                    extent=[photo_left, photo_left + photo_w, photo_bottom, photo_top],
                    aspect='auto', zorder=2, interpolation='antialiased')
    # Photo edge — alpha 0.80, linewidth 1.5: actually frames the photo
    # without screaming. Reads as intentional, not decorative.
    ax_main.add_patch(Rectangle((photo_left, photo_bottom), photo_w, photo_h,
                                 fill=False, edgecolor=PHOTO_BORDER, linewidth=1.5,
                                 alpha=0.80, zorder=3))

    # Inverted typography hierarchy: name down, context up, season label
    # demoted from cyan display font to a quiet off-white sans subline.
    text_x = photo_left + photo_w + 0.4
    ax_main.text(text_x, photo_top - 0.15, display_name,
                  fontsize=36, fontfamily='DIN Condensed', color=TEXT_PRIMARY,
                  va='top', fontweight='bold')
    hand_code = 'LHH' if bats == 'L' else ('SHH' if bats == 'S' else 'RHH')
    ax_main.text(text_x, photo_top - 1.05,
                  f"{hand_code}  |  {team}  |  Age: {age}",
                  fontsize=16, fontfamily='Avenir Next', color=TEXT_PRIMARY, va='top',
                  fontweight='600')
    # Year label + "Through {date}" inline data freshness stamp.
    # Pulled from metadata.generatedAt — shareable cards need the date so
    # readers know which snapshot of the season they're looking at.
    _gen_at = metadata.get('generatedAt', '')
    _date_suffix = ''
    if _gen_at:
        try:
            from datetime import datetime
            _dt = datetime.strptime(_gen_at[:10], '%Y-%m-%d')
            _date_suffix = f"  ·  Through {_dt.strftime('%B %-d').lstrip('0')}"
        except Exception:
            _date_suffix = ''
    ax_main.text(text_x, photo_top - 1.80, year_label + _date_suffix,
                  fontsize=17, fontfamily='Avenir Next', color=TEXT_SECONDARY,
                  va='top', fontweight='600')

    # ─── Headline stats strip ────────────────────────────────────────
    # ROC players have a reduced stat set (no + family, no bat-tracking)
    is_roc = (h_row.get('team') == 'ROC')
    headline_stats = HEADLINE_STATS_ROC if is_roc else HEADLINE_STATS_MLB
    stat_values = []
    for k in headline_stats:
        if k == 'PA':
            stat_values.append(str(h_row.get('pa', '—')))
        elif k == 'AVG':  stat_values.append(fmt_3dec(h_row.get('avg')))
        elif k == 'OBP':  stat_values.append(fmt_3dec(h_row.get('obp')))
        elif k == 'SLG':  stat_values.append(fmt_3dec(h_row.get('slg')))
        elif k == 'BB%':  stat_values.append(fmt_pct(h_row.get('bbPct')))
        elif k == 'K%':   stat_values.append(fmt_pct(h_row.get('kPct')))
        elif k == 'wRC+': stat_values.append(fmt_int(h_row.get('wRCplus')))
        elif k == 'SD+':  stat_values.append(fmt_int(h_row.get('sdPlus')))
        elif k == 'CT+':  stat_values.append(fmt_int(h_row.get('ctPlus')))
        elif k == 'BB+':  stat_values.append(fmt_int(h_row.get('bbPlus')))
        elif k == 'Hitter+': stat_values.append(fmt_int(h_row.get('hitterPlus')))
        else: stat_values.append('—')

    # Proportional column widths — every cell sized to its content + padding.
    # All cells (slash line + rate stats + + stats) render at the same scale.
    HL_PAD_CHARS = 4
    HL_MIN_CHARS = 5
    hl_char_widths = []
    for i, k in enumerate(headline_stats):
        widest = max(len(k), len(stat_values[i]))
        hl_char_widths.append(max(HL_MIN_CHARS, widest + HL_PAD_CHARS))
    hl_total_chars = sum(hl_char_widths)
    # Total horizontal budget: identity column edge → just before LA × Spray
    hl_total_w = (9.5 / FIG_W * FIG_W) - photo_left - 0.4   # in inches
    hl_widths = [hl_total_w * c / hl_total_chars for c in hl_char_widths]

    cell_h = 0.55
    stat_y_header = photo_bottom - 0.70   # was 0.55 — extra breathing room
                                            # between the photo and headline
    stat_y_value = stat_y_header - cell_h
    hitter_la = metadata.get('hitterLeagueAverages', {})
    cur_x = photo_left
    for i, k in enumerate(headline_stats):
        cw = hl_widths[i]
        val_str = stat_values[i]
        # Header cell
        ax_main.add_patch(Rectangle((cur_x, stat_y_header), cw, cell_h,
                                     facecolor=DARKER, edgecolor=SUBTLE_BORDER,
                                     linewidth=0.8))
        ax_main.text(cur_x + cw / 2, stat_y_header + cell_h / 2, k,
                      fontsize=12, ha='center', va='center', color=TEXT_SECONDARY,
                      fontweight='bold', fontfamily='Avenir Next')
        # Value cell — percentile-colored bg
        cell_bg = DARK_CELL
        sl_cfg = HITTER_STAT_LINE_COLOR.get(k)
        if sl_cfg and hitter_la and val_str and val_str != '—':
            la_val = hitter_la.get(sl_cfg[0])
            if la_val is not None:
                if sl_cfg[1] == 'pct':
                    tinted = pct_cell_color(val_str, la_val, DARK_CELL, sl_cfg[2])
                else:
                    scale = sl_cfg[3] if len(sl_cfg) > 3 else 1.0
                    tinted = raw_cell_color(val_str, la_val, scale, sl_cfg[2], DARK_CELL)
                if tinted:
                    cell_bg = tinted
        ax_main.add_patch(Rectangle((cur_x, stat_y_value), cw, cell_h,
                                     facecolor=cell_bg, edgecolor=SUBTLE_BORDER,
                                     linewidth=0.8))
        # All values render at the same size — no slash-line emphasis
        ax_main.text(cur_x + cw / 2, stat_y_value + cell_h / 2, val_str,
                      fontsize=15, ha='center', va='center',
                      color=TEXT_PRIMARY, fontweight='bold',
                      fontfamily='Avenir Next')
        cur_x += cw

    # Subtle group dividers — thin vertical hairlines between stat groups
    # so the headline strip reads as PA | slash-line | rate-stats | +stats
    # without changing cell sizes. Anchors the eye without re-sizing.
    # For MLB: divide PA | slash | rate | + family. For ROC: just PA | slash | rate | wRC+.
    GROUP_BOUNDARIES = ({'AVG', 'BB%', 'wRC+'} if is_roc
                        else {'AVG', 'BB%', 'SD+'})
    div_x = photo_left
    for i, k in enumerate(headline_stats):
        if i > 0 and k in GROUP_BOUNDARIES:
            ax_main.plot([div_x, div_x],
                          [stat_y_value, stat_y_header + cell_h],
                          color=PHOTO_BORDER, linewidth=1.2, alpha=0.60,
                          zorder=6)
        div_x += hl_widths[i]

    # ─── LA × Spray scatter (top-right) ────────────────────────────
    # Mirrors the hitter page panel: title centered above, annotations in
    # top-left, big tall chart, legend below.
    sacq_lookup, hand_zones, pool_zones = build_sacq_lookup(metadata, bats)
    spray_axes_left = 9.5 / FIG_W      # left edge (clear of headline stats)
    spray_axes_right = 0.985
    spray_axes_bottom = 0.295          # more vertical room below chart so
                                        # the legend block can breathe
    spray_axes_top = 0.910             # leave room for title + 2 annotations
    ax_spray = fig.add_axes([spray_axes_left, spray_axes_bottom,
                              spray_axes_right - spray_axes_left,
                              spray_axes_top - spray_axes_bottom])
    ax_spray.set_facecolor(BG)
    ax_spray.set_xlim(-50, 50); ax_spray.set_ylim(-20, 60)

    # Heatmap zones
    if bats == 'L':
        bounds = {'pull': (30, 50), 'pull_side': (15, 30), 'center_pull': (0, 15),
                  'center_oppo': (-15, 0), 'oppo_side': (-30, -15), 'oppo': (-50, -30)}
    else:
        bounds = {'pull': (-50, -30), 'pull_side': (-30, -15), 'center_pull': (-15, 0),
                  'center_oppo': (0, 15), 'oppo_side': (15, 30), 'oppo': (30, 50)}
    LA_RANGES = LA_BINS
    # Choose value: hand-specific if qualified, else pooled
    for (sd, lb), z_hand in hand_zones.items():
        z_pool = pool_zones.get((sd, lb))
        z = z_hand if z_hand.get('count', 0) >= 20 else z_pool
        if not z: continue
        v = z.get('wobacon') if z.get('wobacon') is not None else z.get('woba')
        if v is None: continue
        if sd not in bounds: continue
        bx = bounds[sd]
        if lb >= len(LA_RANGES): continue
        ly = LA_RANGES[lb]
        lo = max(-20, ly[0]); hi = min(60, ly[1])
        col = WOBA_CMAP(min(1.0, v / 1.0))
        # Bumped from 0.25 → 0.45 so SACQ zones pop instead of washing out.
        alpha = 0.15 if z.get('count', 0) < 20 else 0.45
        ax_spray.add_patch(Rectangle((min(bx), lo), abs(bx[1] - bx[0]), hi - lo,
                                       facecolor=col, alpha=alpha,
                                       edgecolor=GRID_COLOR, linewidth=0.3))
    for (sd, lb), z in pool_zones.items():
        if (sd, lb) in hand_zones: continue
        v = z.get('wobacon') if z.get('wobacon') is not None else z.get('woba')
        if v is None: continue
        if sd not in bounds: continue
        bx = bounds[sd]
        if lb >= len(LA_RANGES): continue
        ly = LA_RANGES[lb]
        lo = max(-20, ly[0]); hi = min(60, ly[1])
        col = WOBA_CMAP(min(1.0, v / 1.0))
        # Bumped from 0.25 → 0.45 so SACQ zones pop instead of washing out.
        alpha = 0.15 if z.get('count', 0) < 20 else 0.45
        ax_spray.add_patch(Rectangle((min(bx), lo), abs(bx[1] - bx[0]), hi - lo,
                                       facecolor=col, alpha=alpha,
                                       edgecolor=GRID_COLOR, linewidth=0.3))

    # BIP scatter
    bip_pts = []
    for p in hitter_pitches:
        if p.get('Description') != 'In Play': continue
        bbt = str(p.get('BBType', '')).strip()
        if not bbt or bbt.startswith('bunt'): continue
        la = sf(p.get('LaunchAngle'))
        ang = spray_angle(sf(p.get('HC_X')), sf(p.get('HC_Y')))
        ev = sf(p.get('ExitVelo'))
        if la is None or ang is None: continue
        bip_pts.append((ang, max(-20, min(60, la)), ev, la))

    def ev_color(ev):
        # Alpha 0.95 (was 0.85) — dots fully opaque so they don't get
        # washed by the saturated SACQ zone colors underneath.
        if ev is None: return (0.6, 0.6, 0.6, 0.75)
        t = max(0, min(1, (ev - 70) / 45))
        if t < 0.5:
            s = t / 0.5
            return ((0 + s * 140) / 255, (100 + s * 40) / 255, (255 - s * 115) / 255, 0.95)
        s = (t - 0.5) / 0.5
        return ((140 + s * 115) / 255, (140 - s * 120) / 255, (140 - s * 120) / 255, 0.95)

    def ev_size(ev):
        # Match hitter page (js/player-page.js evRadius): 7-12 pixel radii.
        # Convert to matplotlib `s` (area in points²) at SAVE_DPI=150:
        #   s = π × (r_px × 72/150)² = π × r² × 0.2304
        # Slightly scaled up so dots read at our wider chart proportions.
        if ev is None: return 80
        if ev < 80:  return 80   # r ~10 px equivalent
        if ev < 90:  return 105
        if ev < 95:  return 135
        if ev < 100: return 165
        if ev < 105: return 200
        return 240               # r ~17 px equivalent

    # Thin dark edge on every BIP dot for contrast against the saturated
    # SACQ zone backgrounds — gray dots in particular were blending with
    # the muted tan/teal zones without an edge.
    for x, y, ev, _real in bip_pts:
        ax_spray.scatter([x], [y], s=ev_size(ev), c=[ev_color(ev)],
                          edgecolors='#1a1612', linewidths=0.7, zorder=3)

    # Median placement (cyan marker) using REAL la (not clamped) — matches
    # the hitter page (median, not mean, so single extreme BIPs don't pull
    # the marker away from where the hitter typically places the ball)
    if bip_pts:
        sorted_sprays = sorted(p[0] for p in bip_pts)
        sorted_las = sorted(p[3] for p in bip_pts)
        n_pts = len(bip_pts)
        mid = n_pts // 2
        if n_pts % 2 == 0:
            med_spray = (sorted_sprays[mid - 1] + sorted_sprays[mid]) / 2
            med_la_real = (sorted_las[mid - 1] + sorted_las[mid]) / 2
        else:
            med_spray = sorted_sprays[mid]
            med_la_real = sorted_las[mid]
        med_la_plot = max(-20, min(60, med_la_real))
        # Always cyan, regardless of theme — this is a system annotation.
        # Outer white halo + cyan inner dot, black edge for contrast on
        # any background (cream paper or dark navy alike).
        ax_spray.scatter([med_spray], [med_la_plot], s=420,
                          c='white', zorder=10, alpha=0.95,
                          edgecolors='black', linewidths=0.5)
        ax_spray.scatter([med_spray], [med_la_plot], s=240,
                          c=MARKER_ACCENT, edgecolors='black',
                          linewidths=2, zorder=11)
    else:
        med_spray = med_la_real = None

    # xwOBAsp (hitter overall, hand-specific zones with pooled fallback)
    xwobasp_sum = 0; xwobasp_n = 0; total_bip = 0
    for ang, _yc, _ev, la_r in bip_pts:
        total_bip += 1
        sd = spray_direction(ang, bats)
        lb = la_bin_idx(la_r) if la_r is not None else None
        v = sacq_lookup(sd, lb)
        if v is not None:
            xwobasp_sum += v
            xwobasp_n += 1
    xwobasp = xwobasp_sum / xwobasp_n if xwobasp_n else None

    # Annotations placed TOP-LEFT of chart panel (matches hitter page).
    # Each line is one consolidated fig.text() so spacing is correct regardless
    # of font metrics. Color emphasis applied via second-pass overlay.
    annot_x = spray_axes_left + 0.005   # left edge, just inside panel
    # Use leaderboard's xwOBAsp value + percentile for consistency with website
    xwobasp_display = h_row.get('xwOBAsp', xwobasp)
    pctl = h_row.get('xwOBAsp_pctl')

    # Percentile→color (mirrors js/utils.js Utils.percentileColorDark):
    #   0   = rgb(  0,100,255) bright blue
    #   50  = rgb(140,140,140) neutral gray
    #   100 = rgb(255, 20, 20) bright red
    def _pctl_color_dark(p):
        if p is None: return PERCENTILE_NEUTRAL
        if p <= 50:
            tt = p / 50.0
            r = int(round(0   + tt * 140))
            g = int(round(100 + tt * 40))
            b = int(round(255 - tt * 115))
        else:
            tt = (p - 50) / 50.0
            r = int(round(140 + tt * 115))
            g = int(round(140 - tt * 120))
            b = int(round(140 - tt * 120))
        return f'#{r:02x}{g:02x}{b:02x}'

    pctl_color = _pctl_color_dark(pctl)

    if xwobasp_display is not None:
        # Note format: "(95th percentile, 58 qualifying BIP)"
        # If qualifying < total, show "X of Y qualifying BIP"
        bip_str = (f"{xwobasp_n} of {total_bip} qualifying BIP"
                   if total_bip > xwobasp_n else f"{xwobasp_n} qualifying BIP")
        if pctl is not None:
            pctl_int = int(round(pctl))
            # Pick suffix (1st, 2nd, 3rd, 4th-9th, 10th-19th)
            if 11 <= (pctl_int % 100) <= 13:
                suffix = 'th'
            else:
                suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(pctl_int % 10, 'th')
            bipnote = f"({pctl_int}{suffix} percentile, {bip_str})"
        else:
            bipnote = f"({bip_str})"
        l1_y = 0.955
        # Approach: render label first (gray), measure its width via the
        # renderer, place value right after, measure that, place bipnote.
        renderer = fig.canvas.get_renderer()
        inv = fig.transFigure.inverted()

        def _place_text(x, y, txt, fontsize, color, fontweight):
            t = fig.text(x, y, txt, color=color, fontsize=fontsize,
                          fontweight=fontweight, fontfamily='Avenir Next',
                          va='center', ha='left')
            bbox = t.get_window_extent(renderer=renderer)
            bbox_fig = bbox.transformed(inv)
            return bbox_fig.x1  # right edge in figure fraction coords

        right = _place_text(annot_x, l1_y, 'xwOBAsp: ', 18, TEXT_MUTED, '600')
        # Value uses percentile-derived color (matches hitter page)
        right = _place_text(right, l1_y, fmt_3dec(xwobasp_display), 18, pctl_color, '800')
        right += 0.005  # tiny gap before bipnote
        _place_text(right, l1_y, bipnote, 11, TEXT_FAINT, '600')

    if med_spray is not None and med_la_real is not None:
        sd = ('Pull' if med_spray > 0 else 'Oppo') if bats == 'L' else \
             ('Pull' if med_spray < 0 else 'Oppo')
        l2_y = 0.930
        renderer = fig.canvas.get_renderer()
        inv = fig.transFigure.inverted()

        def _place_text2(x, y, txt, fontsize, color, fontweight):
            t = fig.text(x, y, txt, color=color, fontsize=fontsize,
                          fontweight=fontweight, fontfamily='Avenir Next',
                          va='center', ha='left')
            bbox = t.get_window_extent(renderer=renderer)
            bbox_fig = bbox.transformed(inv)
            return bbox_fig.x1

        right = _place_text2(annot_x, l2_y, 'Avg Placement: ', 14, TEXT_MUTED, '600')
        # Both spray-direction value and LA value share xwOBAsp percentile color
        # (matches hitter page — links Avg Placement visually to xwOBAsp)
        right = _place_text2(right, l2_y, f"{abs(med_spray):.1f}° {sd}",
                              14, pctl_color, '800')
        right += 0.006
        right = _place_text2(right, l2_y, '|', 13, TEXT_FAINT, '600')
        right += 0.006
        _place_text2(right, l2_y, f"{med_la_real:+.1f}° LA",
                       14, pctl_color, '800')

    # Spray axes styling
    ax_spray.set_xticks([-50, -30, -15, 0, 15, 30, 50])
    ax_spray.set_yticks(range(-20, 61, 10))
    ax_spray.tick_params(colors=TICK_COLOR, labelsize=8)
    for s in ax_spray.spines.values(): s.set_color(SPINE_COLOR)
    ax_spray.grid(True, color=GRID_COLOR, alpha=0.10, linewidth=0.4)
    leftL = ('Oppo' if bats == 'L' else 'Pull')
    rightL = ('Pull' if bats == 'L' else 'Oppo')
    # Title-case throughout — matches the card's typographic voice.
    # Bullet separators avoid the ←→ font-fallback warnings.
    ax_spray.set_xlabel(f'{leftL}   •   Spray Angle   •   {rightL}',
                         color=TEXT_MUTED, fontsize=10, fontfamily='Avenir Next')
    ax_spray.set_ylabel('Launch Angle', color=TEXT_MUTED, fontsize=10,
                         fontfamily='Avenir Next')
    # Section title (centered ABOVE the annotation block, matches hitter page)
    # Editorial-style title: letterspaced uppercase, off-white, with thin
    # underline rule. Same treatment used for all section titles below.
    title_x = (spray_axes_left + spray_axes_right) / 2
    fig.text(title_x, 0.985, 'L A U N C H   A N G L E   ×   S P R A Y',
              color=TEXT_SECONDARY, fontsize=12, fontweight='700',
              fontfamily='Avenir Next', va='center', ha='center')
    # Thin underline rule
    rule_w = 0.18
    ax_rule = fig.add_axes([title_x - rule_w / 2, 0.978, rule_w, 0.0008])
    ax_rule.axis('off')
    ax_rule.add_patch(Rectangle((0, 0), 1, 1, facecolor=TEXT_SECONDARY,
                                  edgecolor='none', alpha=0.30,
                                  transform=ax_rule.transAxes))

    # ─── Heat map + per-group bar geometry (computed up front so both
    #     sections can reference shared boundaries) ─────────────────
    # Heat maps fill the middle band; top lifted to give panels more height.
    # Panels rendered ~square so the 4×4 ft data range stays proportional.
    # Bottom raised to 0.20 to make room for the heat-map color-scale legend
    # (single compact row) in the band between heat maps and Contact Profile.
    zhm_y_bottom = 0.20
    zhm_y_top = 0.70
    panel_h = (zhm_y_top - zhm_y_bottom) / 2 - 0.025
    panel_h_in = panel_h * FIG_H
    panel_w_in = panel_h_in
    panel_w = panel_w_in / FIG_W
    zhm_x_left = 0.012
    zhm_x_right = zhm_x_left + 2 * panel_w + 0.014

    # ─── LA × Spray legend (matches hitter page exactly) ───────────
    # Two rows beneath the LA × Spray chart:
    #   Row 1: 70 mph (blue) · 95 mph (gray) · 115 mph (red) · Size = EV
    #   Row 2: MLB wOBAcon: .000 [gradient bar] 1.000+
    from matplotlib.patches import Circle
    legend_center_x = (spray_axes_left + spray_axes_right) / 2
    # Larger gaps below xlabel and between rows so the legend doesn't
    # feel crammed together with the chart's axis label.
    legend_y_dots = spray_axes_bottom - 0.045    # clear of xlabel
    legend_y_grad = spray_axes_bottom - 0.090    # generous gap from dots

    EV_LEGEND = [
        ('70 mph',  '#0064ff'),
        ('95 mph',  '#8c8c8c'),
        ('115 mph', '#ff1414'),
    ]
    LEGEND_FONTSIZE = 13
    DOT_RADIUS = 0.0065
    ITEM_GAP = 0.026

    renderer_l = fig.canvas.get_renderer()
    inv_l = fig.transFigure.inverted()

    def _measure_text(txt, fontsize, fontweight='600'):
        t = fig.text(0, 0, txt, color='#000', fontsize=fontsize,
                      fontweight=fontweight, fontfamily='Avenir Next',
                      va='center', ha='left')
        w = t.get_window_extent(renderer=renderer_l).transformed(inv_l).width
        t.remove()
        return w

    def _draw_text(x, y, txt, fontsize, color, fontweight='600'):
        t = fig.text(x, y, txt, color=color, fontsize=fontsize,
                      fontweight=fontweight, fontfamily='Avenir Next',
                      va='center', ha='left')
        return t.get_window_extent(renderer=renderer_l).transformed(inv_l).x1

    def _draw_dot(x, y, color, radius=DOT_RADIUS):
        c = Circle((x, y), radius,
                    facecolor=color, edgecolor='none',
                    transform=fig.transFigure, figure=fig)
        fig.add_artist(c)

    # Row 1 — pre-measure entire row to center it
    row1_w = 0.0
    for label, _ in EV_LEGEND:
        row1_w += 2 * DOT_RADIUS + 0.006 + _measure_text(label, LEGEND_FONTSIZE) + ITEM_GAP
    row1_w += 2 * DOT_RADIUS + 0.006 + _measure_text('Size = EV', LEGEND_FONTSIZE)
    cur_x = legend_center_x - row1_w / 2

    for label, hexcolor in EV_LEGEND:
        _draw_dot(cur_x + DOT_RADIUS, legend_y_dots, hexcolor)
        cur_x += 2 * DOT_RADIUS + 0.006
        cur_x = _draw_text(cur_x, legend_y_dots, label, LEGEND_FONTSIZE, PERCENTILE_NEUTRAL)
        cur_x += ITEM_GAP
    _draw_dot(cur_x + DOT_RADIUS * 0.85, legend_y_dots, TEXT_DIMMED,
              radius=DOT_RADIUS * 0.85)
    cur_x += 2 * DOT_RADIUS + 0.006
    _draw_text(cur_x, legend_y_dots, 'Size = EV', LEGEND_FONTSIZE, TEXT_DIMMED)

    # Row 2 — MLB wOBAcon gradient (label + .000 + bar + 1.000+)
    grad_label = 'MLB wOBAcon: '
    grad_low = '.000'
    grad_high = '1.000+'
    grad_bar_w = 0.22
    grad_bar_h = 0.014
    lbl_w = _measure_text(grad_label, LEGEND_FONTSIZE)
    low_w = _measure_text(grad_low, LEGEND_FONTSIZE)
    high_w = _measure_text(grad_high, LEGEND_FONTSIZE)
    total_w = lbl_w + 0.005 + low_w + 0.006 + grad_bar_w + 0.006 + high_w
    cur = legend_center_x - total_w / 2
    cur = _draw_text(cur, legend_y_grad, grad_label, LEGEND_FONTSIZE, TEXT_DIMMED)
    cur += 0.005
    cur = _draw_text(cur, legend_y_grad, grad_low, LEGEND_FONTSIZE, TEXT_DIMMED)
    cur += 0.006
    bar_left_x = cur
    ax_grad = fig.add_axes([bar_left_x, legend_y_grad - grad_bar_h / 2,
                              grad_bar_w, grad_bar_h])
    ax_grad.set_facecolor(BG)
    grad_arr = np.linspace(0, 1, 256).reshape(1, -1)
    ax_grad.imshow(grad_arr, aspect='auto', cmap=WOBA_CMAP,
                    extent=[0, 1, 0, 1], origin='lower')
    ax_grad.set_xticks([]); ax_grad.set_yticks([])
    for s in ax_grad.spines.values(): s.set_visible(False)
    cur = bar_left_x + grad_bar_w + 0.006
    _draw_text(cur, legend_y_grad, grad_high, LEGEND_FONTSIZE, TEXT_DIMMED)

    # No section title for heat maps — the four panel titles
    # ("WHIFFS vs RHP — 33.9%", etc.) already label the section.

    # ─── Zone heat maps: 2 rows × 2 cols (geometry already computed) ─
    ZONE_X_MIN, ZONE_X_MAX = -2.0, 2.0
    ZONE_Z_MIN, ZONE_Z_MAX = 0.5, 4.5

    SWING_ALL = set(SWING_DESC)
    for hi, hand in enumerate(['R', 'L']):  # row index
        # Build the two underlying point sets per handedness, used for both
        # the panel subtitles AND the rate-KDE numerator/denominator.
        swing_pts = []          # all swing locations (denominator for WHIFFS)
        whiff_pts = []          # swinging-strike locations (numerator for WHIFFS)
        bip_pts_loc = []        # BIP locations (denominator for DAMAGE)
        bip_xw_weights = []     # BIP xwOBA values (MLB DAMAGE weights)
        bip_ev_weights = []     # BIP ExitVelo values (ROC DAMAGE weights)
        for p in hitter_pitches:
            if p.get('Throws') != hand: continue
            px = sf(p.get('PlateX')); pz = sf(p.get('PlateZ'))
            if px is None or pz is None: continue
            desc = p.get('Description', '')
            if desc in SWING_ALL:
                swing_pts.append((px, pz))
                if desc == 'Swinging Strike':
                    whiff_pts.append((px, pz))
            if desc == 'In Play':
                if is_roc:
                    # ROC: weight by ExitVelo (xwOBA isn't tagged for AAA)
                    ev = sf(p.get('ExitVelo'))
                    if ev is not None:
                        bip_pts_loc.append((px, pz))
                        bip_ev_weights.append(ev)
                else:
                    xw = sf(p.get('xwOBA'))
                    if xw is not None:
                        bip_pts_loc.append((px, pz))
                        bip_xw_weights.append(xw)

        # Aggregate metrics for the panel subtitle
        n_swings_hand = len(swing_pts)
        n_whiffs_hand = len(whiff_pts)
        whiff_pct_hand = (n_whiffs_hand / n_swings_hand) if n_swings_hand else None
        xwobacon_hand = (sum(bip_xw_weights) / len(bip_xw_weights)) if bip_xw_weights else None
        avg_ev_hand = (sum(bip_ev_weights) / len(bip_ev_weights)) if bip_ev_weights else None

        for ci, mode in enumerate(['whiffs', 'damage']):  # col index
            ax = fig.add_axes([zhm_x_left + ci * (panel_w + 0.01),
                                zhm_y_top - (hi + 1) * panel_h - hi * 0.02,
                                panel_w, panel_h])
            hand_label = 'RHP' if hand == 'R' else 'LHP'
            if mode == 'whiffs':
                # WHIFFS rate KDE — numerator = whiffs, denominator = swings.
                # Color anchored to MLB whiff% via scale_max=0.6.
                if whiff_pct_hand is not None:
                    label = (f"WHIFFS vs {hand_label} · "
                             f"{whiff_pct_hand * 100:.1f}%")
                    sample = f"{n_whiffs_hand} of {n_swings_hand} swings"
                else:
                    label = f"WHIFFS vs {hand_label}"
                    sample = f"n = {n_whiffs_hand}"
                render_rate_kde_to_axes(ax,
                    whiff_pts, None,           # num: whiffs (uniform weight)
                    swing_pts, None,           # den: all swings (uniform weight)
                    ZONE_X_MIN, ZONE_X_MAX, ZONE_Z_MIN, ZONE_Z_MAX,
                    sz_top, sz_bot, label, sample,
                    scale_max=0.6, mask_threshold=0.02, min_n=5)
            else:
                # DAMAGE rate KDE — for MLB: xwOBA-weighted BIPs gives mean
                # xwOBAcon per location. For ROC: ExitVelo-weighted gives mean
                # Avg EV per location (xwOBA isn't tagged for AAA).
                if is_roc:
                    if avg_ev_hand is not None:
                        label = (f"DAMAGE vs {hand_label} · "
                                 f"Avg EV {avg_ev_hand:.1f} mph")
                        sample = f"{len(bip_pts_loc)} BIP"
                    else:
                        label = f"DAMAGE vs {hand_label}"
                        sample = f"n = {len(bip_pts_loc)}"
                    # ExitVelo: clamp range [50, 110] mph. MLB avg EV ~88 mph
                    # falls at (88-50)/60 = 0.63 along the cmap → warm.
                    render_rate_kde_to_axes(ax,
                        bip_pts_loc, bip_ev_weights,
                        bip_pts_loc, None,
                        ZONE_X_MIN, ZONE_X_MAX, ZONE_Z_MIN, ZONE_Z_MAX,
                        sz_top, sz_bot, label, sample,
                        scale_max=110.0, scale_min=50.0,
                        mask_threshold=0.05, min_n=5)
                else:
                    if xwobacon_hand is not None:
                        label = (f"DAMAGE vs {hand_label} · "
                                 f"xwOBAcon {fmt_3dec(xwobacon_hand)}")
                        sample = f"{len(bip_pts_loc)} BIP"
                    else:
                        label = f"DAMAGE vs {hand_label}"
                        sample = f"n = {len(bip_pts_loc)}"
                    render_rate_kde_to_axes(ax,
                        bip_pts_loc, bip_xw_weights,
                        bip_pts_loc, None,
                        ZONE_X_MIN, ZONE_X_MAX, ZONE_Z_MIN, ZONE_Z_MAX,
                        sz_top, sz_bot, label, sample,
                        scale_max=1.0, mask_threshold=0.05, min_n=5)

    # ─── Heat-map color-scale legend ──────────────────────────────
    # Compact side-by-side scales sharing HEAT_CMAP but different scale_max:
    # red on WHIFFS = 60%+ whiff rate, red on DAMAGE = 1.000+ xwOBAcon.
    # Each scale takes ~half the heat-maps width so they sit on a single line.
    HM_BAR_H = 0.010
    HM_FONT  = 9

    renderer_hm = fig.canvas.get_renderer()
    inv_hm = fig.transFigure.inverted()

    def _hm_measure(txt, fontsize=HM_FONT, fontweight='600'):
        t = fig.text(0, 0, txt, color='#000', fontsize=fontsize,
                      fontweight=fontweight, fontfamily='Avenir Next',
                      va='center', ha='left')
        w = t.get_window_extent(renderer=renderer_hm).transformed(inv_hm).width
        t.remove()
        return w

    def _hm_text(x, y, txt, color, fontsize=HM_FONT, fontweight='600'):
        t = fig.text(x, y, txt, color=color, fontsize=fontsize,
                      fontweight=fontweight, fontfamily='Avenir Next',
                      va='center', ha='left')
        return t.get_window_extent(renderer=renderer_hm).transformed(inv_hm).x1

    def _hm_legend_row(x_left, x_right, y_center, label, low_str, high_str,
                       mlb_pos=None):
        """Inline legend: 'LABEL low [bar] high' within [x_left, x_right].
        mlb_pos: optional [0, 1] position on the bar to draw a white tick +
        small 'MLB' label, anchoring the absolute scale."""
        x = x_left
        x = _hm_text(x, y_center, label, TEXT_MUTED, fontweight='800')
        x += 0.005
        x = _hm_text(x, y_center, low_str, TEXT_SECONDARY)
        x += 0.003
        high_w = _hm_measure(high_str)
        bar_right = x_right - high_w - 0.004
        bar_w = bar_right - x
        if bar_w > 0.02:
            ax_g = fig.add_axes([x, y_center - HM_BAR_H / 2,
                                  bar_w, HM_BAR_H])
            ax_g.set_facecolor(BG)
            grad_arr = np.linspace(0, 1, 256).reshape(1, -1)
            ax_g.imshow(grad_arr, aspect='auto', cmap=HEAT_CMAP,
                         extent=[0, 1, 0, 1], origin='lower')
            ax_g.set_xticks([]); ax_g.set_yticks([])
            for s in ax_g.spines.values(): s.set_visible(False)
            # MLB anchor: thin white tick across the bar + tiny 'MLB' label below
            if mlb_pos is not None:
                ax_g.axvline(mlb_pos, color=GRID_COLOR, linewidth=1.1,
                              alpha=0.95, zorder=5)
                tick_fig_x = x + bar_w * mlb_pos
                fig.text(tick_fig_x, y_center - HM_BAR_H / 2 - 0.006, 'MLB',
                          color=TEXT_SECONDARY, fontsize=8, fontweight='700',
                          fontfamily='Avenir Next', va='top', ha='center')
        _hm_text(bar_right + 0.003, y_center, high_str, TEXT_SECONDARY)

    # Side-by-side: WHIFFS (left) + DAMAGE (right), with MLB-avg tick on each.
    # MLB whiff rate ≈ 25.2% → 0.252/0.6 = 0.420 of bar
    # MLB xwOBAcon  ≈ .370   → 0.370/1.0 = 0.370 of bar
    hm_mid = (zhm_x_left + zhm_x_right) / 2
    legend_y = 0.215
    _hm_legend_row(zhm_x_left + 0.005, hm_mid - 0.008, legend_y,
                    'WHIFF RATE', '0%', '60%+', mlb_pos=0.420)
    # ROC: DAMAGE legend shows EV (50-110 mph) with MLB tick at 88 mph
    # → (88-50)/60 = 0.633 along the bar. MLB: xwOBAcon (.000-1.000+) with
    # MLB tick at .370 → 0.370.
    if is_roc:
        _hm_legend_row(hm_mid + 0.008, zhm_x_right - 0.005, legend_y,
                        'Avg EV', '50', '110+ mph', mlb_pos=0.633)
    else:
        _hm_legend_row(hm_mid + 0.008, zhm_x_right - 0.005, legend_y,
                        'xwOBAcon', '.000', '1.000+', mlb_pos=0.370)

    # ─── Contact Profile strip (7 cells, proportional widths) ──────
    # Skipped entirely for ROC — bat-tracking metrics aren't recorded for
    # AAA, and the three available (Avg EV / Max EV / Air Pull%) move into
    # the Pitch Group table instead.
    if not is_roc:
        cp_y_top = 0.155
        cp_y_bot = 0.120
        cp_x_left = 0.01
        cp_x_right = 0.99
        cp_height = cp_y_top - cp_y_bot
        cp_cells = [
            ('Bat Speed',        h_row.get('batSpeed'),      'mph', None),
            ('Avg EV',           h_row.get('avgEVAll'),      'mph', None),
            ('Max EV',           h_row.get('maxEV'),         'mph', None),
            ('Squared-Up%',      h_row.get('squaredUpPct'),  'pct', None),
            ('Blast%',           h_row.get('blastPct'),      'pct', None),
            ('IdealAtkAngle%',   h_row.get('idealAAPct'),    'pct', None),
            ('Air Pull%',        h_row.get('airPullPct'),    'pct', None),
        ]
        def _format_cp_val(val, kind):
            if val is None: return '—'
            if kind == 'pct': return f'{val * 100:.1f}%'
            return f'{val:.1f} {kind}' if kind else f'{val:.1f}'
        cp_val_strs = [_format_cp_val(v, kd) for (_l, v, kd, _) in cp_cells]
        CP_PAD_CHARS = 4
        CP_MIN_CHARS = 9
        cp_char_widths = []
        for i, (lbl, _v, _kd, _) in enumerate(cp_cells):
            widest = max(len(lbl), len(cp_val_strs[i]))
            cp_char_widths.append(max(CP_MIN_CHARS, widest + CP_PAD_CHARS))
        cp_total = sum(cp_char_widths)
        cp_widths_frac = [(cp_x_right - cp_x_left) * c / cp_total
                          for c in cp_char_widths]
        cp_x_offsets = []
        _cx = cp_x_left
        for w in cp_widths_frac:
            cp_x_offsets.append(_cx)
            _cx += w

        for i, (lbl, val, kind, _) in enumerate(cp_cells):
            cx = cp_x_offsets[i]
            cw = cp_widths_frac[i]
            val_str = cp_val_strs[i]
            ax_main.add_patch(Rectangle((cx * FIG_W, (cp_y_bot + cp_height / 2) * FIG_H),
                                          cw * FIG_W, cp_height / 2 * FIG_H,
                                          facecolor=DARKER, edgecolor=SUBTLE_BORDER,
                                          linewidth=0.6))
            ax_main.text((cx + cw / 2) * FIG_W,
                           (cp_y_bot + cp_height * 0.75) * FIG_H, lbl,
                           fontsize=11, ha='center', va='center', color=ACCENT,
                           fontweight='bold', fontfamily='Avenir Next')
            pctl_key_map = {
                'Bat Speed': 'batSpeed_pctl', 'Avg EV': 'avgEVAll_pctl',
                'Max EV': 'maxEV_pctl', 'Squared-Up%': 'squaredUpPct_pctl',
                'Blast%': 'blastPct_pctl', 'IdealAtkAngle%': 'idealAAPct_pctl',
                'Air Pull%': 'airPullPct_pctl',
            }
            pctl = h_row.get(pctl_key_map.get(lbl, ''))
            cell_bg = DARK_CELL
            if pctl is not None:
                if pctl <= 50:
                    t = pctl / 50.0
                    r_t = int(0 + t * 140); g_t = int(100 + t * 40); b_t = int(255 - t * 115)
                else:
                    t = (pctl - 50) / 50.0
                    r_t = int(140 + t * 115); g_t = int(140 - t * 120); b_t = int(140 - t * 120)
                cp_alpha = 0.55
                rb = int(DARK_CELL[1:3], 16)
                rg = int(DARK_CELL[3:5], 16)
                rbb = int(DARK_CELL[5:7], 16)
                r = int(rb * (1 - cp_alpha) + r_t * cp_alpha)
                g = int(rg * (1 - cp_alpha) + g_t * cp_alpha)
                b = int(rbb * (1 - cp_alpha) + b_t * cp_alpha)
                cell_bg = f'#{r:02x}{g:02x}{b:02x}'
            ax_main.add_patch(Rectangle((cx * FIG_W, cp_y_bot * FIG_H),
                                          cw * FIG_W, cp_height / 2 * FIG_H,
                                          facecolor=cell_bg, edgecolor=SUBTLE_BORDER,
                                          linewidth=0.6))
            ax_main.text((cx + cw / 2) * FIG_W,
                           (cp_y_bot + cp_height * 0.25) * FIG_H, val_str,
                           fontsize=14, ha='center', va='center', color=TEXT_PRIMARY,
                           fontweight='bold', fontfamily='Avenir Next')
        # Section title — same letterspaced editorial style as LA × Spray title
        fig.text(0.5, cp_y_top + 0.008, 'C O N T A C T   P R O F I L E',
                  fontsize=12, ha='center', va='bottom', color=TEXT_SECONDARY,
                  fontweight='700', fontfamily='Avenir Next')
        rule_w_cp = 0.13
        ax_rule_cp = fig.add_axes([0.5 - rule_w_cp / 2, cp_y_top + 0.005,
                                    rule_w_cp, 0.0008])
        ax_rule_cp.axis('off')
        ax_rule_cp.add_patch(Rectangle((0, 0), 1, 1, facecolor=TEXT_SECONDARY,
                                         edgecolor='none', alpha=0.30,
                                         transform=ax_rule_cp.transAxes))

    # ─── Bottom table: per-pitch-group performance ──────────────────
    # Compute per-group stats
    group_rows = []
    n_total_seen = len(hitter_pitches)
    for g in GROUP_ORDER:
        gp = [p for p in hitter_pitches if p.get('Pitch Type') in PITCH_GROUPS[g]]
        stats = compute_group_stats(gp, sacq_lookup, bats)
        if stats:
            stats['group'] = g
            stats['usagePct'] = stats['count'] / n_total_seen if n_total_seen else None
            group_rows.append(stats)
    # Total row
    total_stats = compute_group_stats(hitter_pitches, sacq_lookup, bats) or {}
    total_stats['group'] = 'Total'
    total_stats['usagePct'] = 1.0

    # Build table data — different columns for ROC (no xwOBA-based metrics
    # but adds Avg EV / Max EV / Air Pull% in their place since the Contact
    # Profile strip is dropped for ROC).
    def _fmt_ev(v):
        return f'{v:.1f}' if v is not None else '—'

    if is_roc:
        BOTTOM_HEADERS = ['Pitch Group', 'Count', 'Usage', 'Swing%', 'Chase%',
                          'Whiff%', 'Hard-Hit%', 'Barrel%', 'xwOBAsp',
                          'Avg EV', 'Max EV', 'Air Pull%']
        rows = []
        for r in group_rows + [total_stats]:
            rows.append([
                r['group'],
                str(r.get('count', 0)),
                fmt_pct(r.get('usagePct')),
                fmt_pct(r.get('swingPct')),
                fmt_pct(r.get('chasePct')),
                fmt_pct(r.get('whiffPct')),
                fmt_pct(r.get('hardHitPct')),
                fmt_pct(r.get('barrelPct')),
                fmt_3dec(r.get('xwOBAsp')),
                _fmt_ev(r.get('avgEV')),
                _fmt_ev(r.get('maxEV')),
                fmt_pct(r.get('airPullPct')),
            ])
    else:
        BOTTOM_HEADERS = ['Pitch Group', 'Count', 'Usage', 'Swing%', 'Chase%',
                          'Whiff%', 'Hard-Hit%', 'Barrel%', 'xwOBAcon',
                          'xwOBAsp', 'RV/100', 'xRV/100']
        rows = []
        for r in group_rows + [total_stats]:
            rows.append([
                r['group'],
                str(r.get('count', 0)),
                fmt_pct(r.get('usagePct')),
                fmt_pct(r.get('swingPct')),
                fmt_pct(r.get('chasePct')),
                fmt_pct(r.get('whiffPct')),
                fmt_pct(r.get('hardHitPct')),
                fmt_pct(r.get('barrelPct')),
                fmt_3dec(r.get('xwOBAcon')),
                fmt_3dec(r.get('xwOBAsp')),
                fmt_signed_decimal(r.get('rv100')),
                fmt_signed_decimal(r.get('xRv100')),
            ])

    # PITCH GROUP BREAKDOWN section title removed — the table's own header
    # row already labels the section (Pitch Group | Count | Usage | ...).
    # Render bottom table
    table_y_top = 0.112
    table_y_bot = 0.010
    ax_table = fig.add_axes([0.01, table_y_bot, 0.98, table_y_top - table_y_bot])
    ax_table.axis('off'); ax_table.set_facecolor(BG)

    # Proportional column widths — smart padding: each column fits its widest
    # entry plus a generous padding floor so headers + values breathe.
    PAD_CHARS = 4
    MIN_CHARS = 6
    col_char_w = []
    for ci in range(len(BOTTOM_HEADERS)):
        max_len = len(BOTTOM_HEADERS[ci])
        for r in rows:
            if len(r[ci]) > max_len: max_len = len(r[ci])
        col_char_w.append(max(MIN_CHARS, max_len + PAD_CHARS))
    total_chars = sum(col_char_w)
    col_widths = [c / total_chars for c in col_char_w]

    table = ax_table.table(cellText=rows, colLabels=BOTTOM_HEADERS,
                            loc='upper center', cellLoc='center',
                            colWidths=col_widths)
    table.auto_set_font_size(False); table.set_fontsize(13); table.scale(1, 2.4)

    # Style cells — header off-white (no cyan), body lighter weight, Total row
    # gets architectural distinction (heavier weight + brighter color + thicker
    # border on top edge of Total row to anchor it as the summary)
    for (rr, cc), cell in table.get_celld().items():
        cell.set_edgecolor(SUBTLE_BORDER); cell.set_linewidth(0.5)
        if rr == 0:
            # Header row: off-white, heavy weight, slightly bigger
            cell.set_facecolor(DARKER)
            cell.set_text_props(color=TEXT_PRIMARY, fontweight='800', fontsize=13)
        elif rr == len(rows):
            # Total row: heavier weight + brighter, edge thickened all-around
            # to read as a distinct summary band
            cell.set_facecolor(DARKER)
            cell.set_edgecolor(TOTAL_BORDER); cell.set_linewidth(1.4)
            cell.set_text_props(fontweight='800', color=TEXT_PRIMARY, fontsize=13)
        else:
            # Body rows: lighter weight to differentiate from header/total
            cell.set_facecolor(DARK_CELL if rr % 2 == 1 else ALT_ROW_BG)
            cell.set_text_props(color=TEXT_PRIMARY, fontweight='600', fontsize=13)
        if cc == 0 and rr > 0:
            row_idx = rr - 1
            grp = group_rows[row_idx]['group'] if row_idx < len(group_rows) else None
            if grp and grp in GROUP_COLORS:
                # Dampened badge — blend GROUP_COLORS with DARKER at 0.70 so
                # the category labels harmonize with the dampened rate cells
                # in the rest of the table instead of being the loudest thing
                # in the lower half of the card.
                gc = GROUP_COLORS[grp]
                gr = int(gc[1:3], 16); gg = int(gc[3:5], 16); gb = int(gc[5:7], 16)
                dr = int(DARKER[1:3], 16); dg = int(DARKER[3:5], 16); db_ = int(DARKER[5:7], 16)
                a = 0.70
                blend_r = int(dr * (1 - a) + gr * a)
                blend_g = int(dg * (1 - a) + gg * a)
                blend_b = int(db_ * (1 - a) + gb * a)
                blended = f'#{blend_r:02x}{blend_g:02x}{blend_b:02x}'
                cell.set_facecolor(blended)
                cell.set_text_props(color=badge_text_color(blended),
                                    fontweight='800', fontsize=13)

    # Color rate-stat cells based on hitter direction
    hl_a = metadata.get('hitterLeagueAverages', {})

    def col_idx(name):
        return BOTTOM_HEADERS.index(name) if name in BOTTOM_HEADERS else None

    # higher_is_better convention for hitter:
    HITTER_DIR_COLS = {
        'Swing%':    ('swingPct',   'pct', False),  # lower = better (selectivity)
        'Chase%':    ('chasePct',   'pct', False),
        'Whiff%':    ('whiffPct',   'pct', False),
        'Hard-Hit%': ('hardHitPct', 'pct', True),
        'Barrel%':   ('barrelPct',  'pct', True),
    }
    for hdr, (k, kind, hib) in HITTER_DIR_COLS.items():
        ci = col_idx(hdr)
        if ci is None: continue
        la = hl_a.get(k)
        if la is None: continue
        for rr in range(1, len(rows) + 1):
            val_str = rows[rr - 1][ci]
            row_bg = DARKER if rr == len(rows) else (DARK_CELL if rr % 2 == 1 else ALT_ROW_BG)
            # Dampened: max_alpha=0.40 (default 0.55) so bottom table reads
            # as supporting context, not competing with hero visuals above.
            tinted = pct_cell_color(val_str, la, row_bg, hib, max_alpha=0.40)
            if tinted: table.get_celld()[(rr, ci)].set_facecolor(tinted)

    # xwOBAcon, xwOBAsp: higher_is_better=True, raw scale ~0.05
    for hdr, (k, scale) in [('xwOBAcon', ('xwOBAcon', 0.05)), ('xwOBAsp', ('xwOBAsp', 0.05))]:
        ci = col_idx(hdr)
        if ci is None: continue
        la = hl_a.get(k)
        if la is None: continue
        for rr in range(1, len(rows) + 1):
            val_str = rows[rr - 1][ci]
            row_bg = DARKER if rr == len(rows) else (DARK_CELL if rr % 2 == 1 else ALT_ROW_BG)
            tinted = raw_cell_color(val_str, la, scale, True, row_bg, max_alpha=0.40)
            if tinted: table.get_celld()[(rr, ci)].set_facecolor(tinted)

    # RV/100 and xRV/100: centered at 0, higher=better for hitter
    for hdr in ('RV/100', 'xRV/100'):
        ci = col_idx(hdr)
        if ci is None: continue
        for rr in range(1, len(rows) + 1):
            val_str = rows[rr - 1][ci]
            row_bg = DARKER if rr == len(rows) else (DARK_CELL if rr % 2 == 1 else ALT_ROW_BG)
            tinted = raw_cell_color(val_str, 0.0, 2.0, True, row_bg, max_alpha=0.40)
            if tinted: table.get_celld()[(rr, ci)].set_facecolor(tinted)

    # ROC-only columns: Avg EV / Max EV (mph, MLB avg ~88/110, higher=better)
    # and Air Pull% (pct, MLB avg ~13%, higher=better).
    if is_roc:
        for hdr, (k, scale) in [('Avg EV', ('avgEVAll', 4.0)),
                                  ('Max EV', ('maxEV', 4.0))]:
            ci = col_idx(hdr)
            if ci is None: continue
            la = hl_a.get(k)
            if la is None: continue
            for rr in range(1, len(rows) + 1):
                val_str = rows[rr - 1][ci]
                row_bg = DARKER if rr == len(rows) else (DARK_CELL if rr % 2 == 1 else ALT_ROW_BG)
                tinted = raw_cell_color(val_str, la, scale, True, row_bg, max_alpha=0.40)
                if tinted: table.get_celld()[(rr, ci)].set_facecolor(tinted)
        # Air Pull% (percentage column, higher=better)
        ci = col_idx('Air Pull%')
        if ci is not None:
            la = hl_a.get('airPullPct')
            if la is not None:
                for rr in range(1, len(rows) + 1):
                    val_str = rows[rr - 1][ci]
                    row_bg = DARKER if rr == len(rows) else (DARK_CELL if rr % 2 == 1 else ALT_ROW_BG)
                    tinted = pct_cell_color(val_str, la, row_bg, True, max_alpha=0.40)
                    if tinted: table.get_celld()[(rr, ci)].set_facecolor(tinted)

    # ─── Watermark ─────────────────────────────────────────────────
    # Watermark — top-right corner. Sits in the empty space above the
    # right edge of the LA × Spray chart, well clear of any table cells.
    fig.text(0.99, 0.992, 'Huronalytics', color=TEXT_DIMMED, fontsize=10,
              fontfamily='Avenir Next', ha='right', va='top',
              fontweight='600')

    # Save
    safe_name = display_name.replace(' ', '_').replace('.', '').replace(',', '')
    out_path = os.path.join(output_dir,
                              f'HitterCard_{safe_name}_{year_label.replace(" ", "_")}.png')
    plt.savefig(out_path, dpi=SAVE_DPI, facecolor=BG, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved: {out_path}")
    return True


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────
def main():
    # ── Settings (edit these directly or override via command line) ──
    team           = None                    # Team filter (e.g., "NYY"), or None for all teams
    filter_hitters = ""       # Semicolon-separated "Last, First" names, or "" for all
    year_label     = "2026 Season"        # Display label on the card
    output_dir     = OUTPUT_DIR

    # ── CLI overrides (optional — values above are used if no args passed) ──
    parser = argparse.ArgumentParser(description='Generate hitter stat cards')
    parser.add_argument('--team', default=None,
                         help='Team abbreviation — only render hitters on this team')
    parser.add_argument('--hitters', default=None,
                         help='Semicolon-separated "Last, First" names; empty string = all qualified hitters')
    parser.add_argument('--year-label', default=None,
                         help=f'Display label on the card (default: "{year_label}")')
    parser.add_argument('--output-dir', default=None,
                         help=f'Output directory (default: {OUTPUT_DIR})')
    args = parser.parse_args()

    if args.team is not None: team = args.team
    if args.hitters is not None: filter_hitters = args.hitters
    if args.year_label is not None: year_label = args.year_label
    if args.output_dir is not None: output_dir = args.output_dir

    # Parse filter_hitters string into a list (empty string → render all)
    if filter_hitters:
        hitter_names = [h.strip() for h in filter_hitters.split(';') if h.strip()]
    else:
        hitter_names = None
    # ──────────────────────────────────────────────────────────

    if hitter_names:
        team_label = team if team else 'auto-resolve team'
        print(f"═══ Generating hitter cards for {', '.join(hitter_names)} "
              f"({team_label}) — {year_label} ═══\n")
        for name in hitter_names:
            render_hitter_card(name, team_abbrev=team,
                                year_label=year_label, output_dir=output_dir)
    else:
        # No specific names: render every (qualified) hitter, optionally filtered by team
        leaderboard = load_hitter_leaderboard()
        targets = [r for r in leaderboard if r.get('bipQual')]
        if team:
            targets = [r for r in targets if r.get('team') == team]
        team_label = team if team else 'all teams'
        print(f"═══ Generating hitter cards for {len(targets)} hitters "
              f"({team_label}) — {year_label} ═══\n")
        for r in targets:
            render_hitter_card(r.get('hitter'), team_abbrev=r.get('team'),
                                year_label=year_label, output_dir=output_dir)


if __name__ == '__main__':
    main()
