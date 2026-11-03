#!/usr/bin/env python3
"""Advance-report spray charts for one hitter: total, vs RHP, vs LHP.

Reads the hitter's batted balls from the Sheets pitch cache
(`data/all_pitches_rs_cache.pkl`, refresh with
`python3 -m pipeline.refresh_pickle`) and draws three fields on one page.

Placement:
    direction   spray angle from HC_X / HC_Y (where the ball was fielded)
    air balls   Distance along that direction (the projected landing spot)
    grounders   projected along that direction to the MIDDLE OF THE INFIELD
                DIRT, halfway between the base line and the outer dirt arc.
                A grounder's Distance is its first bounce (median 19 ft) and
                its HC point is wherever it was fielded, so neither says
                where it went through the infield. The mid-dirt depth is a
                display convention, not a measured quantity.

Shading (each normalised to its own maximum, so the two are not comparable):
    infield     1-D Gaussian KDE of ground-ball spray angle, painted on the
                dirt band. Labels give the share of grounders per 15 degree
                slice (the `spray_direction` slices in cards/hitter.py).
    outfield    2-D Gaussian KDE of line drive + fly ball landing spots,
                painted outside the dirt. Home runs are drawn but left out:
                no fielder can be positioned for them.
    Both bandwidths are chosen per panel by leave-one-out log-likelihood on
    a grid, at the panel's own sample size. The search prints and the
    footer reports whether the optimum is interior or at a grid edge.

Markers: colour = batted-ball type, size = exit velocity, filled = hit,
hollow = out (errors and fielder's choices count as outs).

Usage (from the repo root):
    python3 scripts/tools/spray_advance_report.py --batter "Wood, James" \
        --out ~/Downloads/james_wood_spray_2026.pdf
"""
import argparse
import gzip
import json
import math
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Ellipse, Polygon
from itertools import permutations

import catch_grid
import hang_time
from catch_prob import PARKS
from spray_chart_csv import (BG, TEXT_PRIMARY, TEXT_SECOND, TEXT_MUTED,
                             TEXT_FAINT, BB_COLORS, BB_LABELS, BB_TYPES,
                             TITLE_FONT, BODY_FONT, MOUND_FT, INFIELD_ARC_FT,
                             BASE_PATH_FT, MARKER_EDGE_W, draw_field)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PICKLE = os.path.join(REPO, 'data', 'all_pitches_rs_cache.pkl')

HP_X, HP_Y = 125.42, 198.27      # home plate in HC space (cards/hitter.py)
HIT_EVENTS = {'Single', 'Double', 'Triple', 'Home Run'}

# Bandwidth search grids. The search must land inside these; an edge
# optimum is reported as such in the footer and on stdout.
GB_BW_GRID = np.arange(1.0, 30.01, 0.5)        # degrees
AIR_BW_GRID = np.arange(10.0, 150.01, 2.5)     # feet

XSPAN, Y0, YSPAN = 680.0, -10.0, 445.0     # plotted field window, feet

SHADE = LinearSegmentedColormap.from_list('shade', ['#e9dfcb', '#5a3a26'])
SLICES = [-45, -30, -15, 0, 15, 30, 45]          # spray_direction edges
FIELDER = '#1a1612'


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def spray_deg(hc_x, hc_y):
    """Degrees, 0 = over second base, positive = right field."""
    dx, dy = hc_x - HP_X, HP_Y - hc_y
    if dy <= 0:
        return None
    return math.degrees(math.atan2(dx, dy))


def base_line_r(th):
    """Distance from home to the 1B-2B (or 2B-3B) line along angle th (rad)."""
    h = BASE_PATH_FT * math.sqrt(2)               # home to second
    return h / (abs(math.sin(th)) + math.cos(th))


def dirt_arc_r(th):
    """Distance from home to the outer dirt arc (radius 95 ft on the mound)."""
    return (MOUND_FT * math.cos(th)
            + math.sqrt(INFIELD_ARC_FT ** 2 - (MOUND_FT * math.sin(th)) ** 2))


def mid_dirt_r(th):
    return 0.5 * (base_line_r(th) + dirt_arc_r(th))


CSV_EVENTS = {'single': 'Single', 'double': 'Double', 'triple': 'Triple',
              'home_run': 'Home Run'}


def csv_rows(path, seasons):
    """A Baseball Savant search CSV as Sheets-shaped pitch dicts."""
    sv = pd.read_csv(os.path.expanduser(path), low_memory=False)
    sv = sv[sv.game_year.isin(seasons)]
    names = sv.player_name.unique()
    if len(names) != 1:
        sys.exit(f'{path}: expected one batter, found {list(names)}')
    for r in sv.itertuples():
        yield {
            'Batter': r.player_name, 'BBType': r.bb_type if isinstance(r.bb_type, str) else None,
            'HC_X': r.hc_x, 'HC_Y': r.hc_y, 'Distance': r.hit_distance_sc,
            'ExitVelo': r.launch_speed, 'LaunchAngle': r.launch_angle,
            'Event': CSV_EVENTS.get(r.events, r.events if isinstance(r.events, str) else ''),
            'Throws': r.p_throws, 'Bats': r.stand, 'Velocity': r.release_speed,
            'Pitch Type': r.pitch_type if isinstance(r.pitch_type, str) else None,
            # Savant's positioning groups: bases empty, runner on 1B only, other.
            'RunnerState': ('empty' if pd.isna(r.on_1b) and pd.isna(r.on_2b) and pd.isna(r.on_3b)
                            else '1b' if pd.isna(r.on_2b) and pd.isna(r.on_3b) else 'other'),
            'PitchID': f'{r.game_pk}_{int(r.at_bat_number):03d}_{int(r.pitch_number):02d}',
            'Game Date': r.game_date,
        }


def load(batter, csv=None, seasons=None):
    rows = csv_rows(csv, seasons) if csv else pd.read_pickle(PICKLE)
    if csv:
        batter = None
    out, dates, dropped = [], [], 0
    for p in rows:
        if (batter and p.get('Batter') != batter) or not p.get('BBType'):
            continue
        hx, hy = _f(p.get('HC_X')), _f(p.get('HC_Y'))
        ang = spray_deg(hx, hy) if hx is not None and hy is not None else None
        key = p['BBType']
        dist = _f(p.get('Distance'))
        if ang is None or key not in BB_TYPES or (key != 'ground_ball' and dist is None):
            dropped += 1
            continue
        # The raw angle feeds the density and the slice shares. A first
        # baseman fields a line grounder at 45-53 deg, so only the marker is
        # pulled inside the foul line; clamping the raw value stacked 20 of
        # Wood's grounders on one angle and collapsed the KDE bandwidth.
        th = math.radians(max(-44.0, min(44.0, ang)))
        r = mid_dirt_r(th) if key == 'ground_ball' else dist
        out.append({
            'key': key, 'ang': ang, 'x': r * math.sin(th), 'y': r * math.cos(th),
            'ev': _f(p.get('ExitVelo')), 'event': p.get('Event') or '',
            'throws': p.get('Throws'), 'bats': p.get('Bats'),
            'pitch_id': p.get('PitchID'), 'la': _f(p.get('LaunchAngle')),
            'dist': dist, 'velo': _f(p.get('Velocity')),
            'date': str(p.get('Game Date'))[:10], 'ptype': p.get('Pitch Type'),
            'runners': p.get('RunnerState'),
        })
        dates.append(str(p.get('Game Date')))
    return out, dropped, (min(dates), max(dates)) if dates else (None, None)


# ── bandwidth search ────────────────────────────────────────────────────
def loo_1d(a, grid):
    d2 = (a[:, None] - a[None, :]) ** 2
    n = len(a)
    ll = []
    for h in grid:
        k = np.exp(-d2 / (2 * h * h)) / (h * math.sqrt(2 * math.pi))
        np.fill_diagonal(k, 0.0)
        ll.append(np.log(k.sum(1) / (n - 1) + 1e-300).mean())
    return np.array(ll)


def loo_2d(xy, grid):
    d2 = ((xy[:, None, :] - xy[None, :, :]) ** 2).sum(-1)
    n = len(xy)
    ll = []
    for h in grid:
        k = np.exp(-d2 / (2 * h * h)) / (2 * math.pi * h * h)
        np.fill_diagonal(k, 0.0)
        ll.append(np.log(k.sum(1) / (n - 1) + 1e-300).mean())
    return np.array(ll)


def pick(grid, ll):
    i = int(np.argmax(ll))
    where = 'interior' if 0 < i < len(grid) - 1 else 'GRID EDGE'
    return float(grid[i]), where


# ── drawing ─────────────────────────────────────────────────────────────
def shade_infield(ax, angs, h):
    th_grid = np.linspace(-45, 45, 181)
    dens = np.exp(-(th_grid[:, None] - angs[None, :]) ** 2 / (2 * h * h)).sum(1)
    dens /= dens.max()
    for i in range(len(th_grid) - 1):
        a0, a1 = math.radians(th_grid[i]), math.radians(th_grid[i + 1])
        poly = [(base_line_r(a) * math.sin(a), base_line_r(a) * math.cos(a)) for a in (a0, a1)]
        poly += [(dirt_arc_r(a) * math.sin(a), dirt_arc_r(a) * math.cos(a)) for a in (a1, a0)]
        v = 0.5 * (dens[i] + dens[i + 1])
        ax.add_patch(Polygon(poly, closed=True, facecolor=SHADE(v),
                             edgecolor='none', alpha=0.25 + 0.7 * v, zorder=1.5))


def shade_outfield(ax, xy, h):
    gx, gy = np.meshgrid(np.linspace(-330, 330, 221), np.linspace(0, 430, 144))
    d = np.zeros_like(gx)
    for x, y in xy:
        d += np.exp(-((gx - x) ** 2 + (gy - y) ** 2) / (2 * h * h))
    d /= d.max()
    th = np.arctan2(gx, gy)
    r = np.hypot(gx, gy)
    fence = 330 + 70 * np.cos(2 * th)
    arc = MOUND_FT * np.cos(th) + np.sqrt(np.clip(INFIELD_ARC_FT ** 2 - (MOUND_FT * np.sin(th)) ** 2, 0, None))
    mask = (np.abs(th) > math.radians(45)) | (r < arc) | (r > fence)
    d = np.ma.array(d, mask=mask)
    ax.contourf(gx, gy, d, levels=np.linspace(0.08, 1, 10), cmap=SHADE,
                alpha=0.75, zorder=1.4, extend='neither')


def ev_size(ev):
    if ev is None:
        return 30
    return float(np.clip(12 + (ev - 60) * 2.6, 12, 150))


def draw_points(ax, rows):
    for key in BB_TYPES:
        for hit in (False, True):
            pts = [r for r in rows if r['key'] == key and (r['event'] in HIT_EVENTS) == hit]
            if not pts:
                continue
            # Grounders share one thin band, so they draw at 60% size.
            scale = 0.6 if key == 'ground_ball' else 1.0
            ax.scatter([p['x'] for p in pts], [p['y'] for p in pts],
                       s=[scale * ev_size(p['ev']) for p in pts],
                       facecolor=BB_COLORS[key] if hit else 'none',
                       edgecolor=TEXT_SECOND if hit else BB_COLORS[key],
                       linewidths=MARKER_EDGE_W if hit else 1.3,
                       alpha=0.9, zorder=4)


def slice_labels(ax, angs):
    n = len(angs)
    for lo, hi in zip(SLICES[:-1], SLICES[1:]):
        lo_ok = angs >= lo if lo > -45 else np.ones_like(angs, bool)
        hi_ok = angs < hi if hi < 45 else np.ones_like(angs, bool)
        k = int((lo_ok & hi_ok).sum())
        th = math.radians(0.5 * (lo + hi))
        r = dirt_arc_r(th) + 28
        ax.text(r * math.sin(th), r * math.cos(th), f'{100 * k / n:.0f}%',
                fontsize=9, fontfamily=BODY_FONT, fontweight='700',
                color=TEXT_PRIMARY, ha='center', va='center', zorder=6,
                bbox=dict(boxstyle='round,pad=0.18', facecolor=BG,
                          edgecolor='none', alpha=0.85))
    for a in SLICES[1:-1]:
        t = math.radians(a)
        r0, r1 = base_line_r(t), dirt_arc_r(t)
        ax.plot([r0 * math.sin(t), r1 * math.sin(t)], [r0 * math.cos(t), r1 * math.cos(t)],
                color=TEXT_FAINT, lw=0.5, ls=(0, (1, 2)), zorder=2)


# ── fielder spots ───────────────────────────────────────────────────────
# Infield: infield_spots (exact constrained 1-D 4-medians on grounder angle,
# two fielders per side of second base, nearest-infielder cost). Every panel
# draws the TOTAL panel's infield: on Wood 2024-2026, leaving one season out,
# the vs-hand infield and the Total one are within 0.05 deg pooled (flat),
# and per-pitch-group infields lost (research/fielding/if_pitchgroup_gate.py).
#
# Outfield, two modes:
#   normal  where a normal outfielder plays: the play-weighted season-average
#           start positions of all 2026 range plays, all hitters. A rule of
#           CF over second and corners halfway to the lines (+-22.5) scored
#           4.5 expected outs worse on Wood's tracked balls; real corner
#           outfielders play nearer the lines.
#   fitted  the normal alignment moved by TWO numbers, a rotation phi
#           (deg, + = toward right field) and a depth change delta (ft, all
#           three), at the most expected outs on this panel's balls, each
#           ball smoothed into a Gaussian cloud (bandwidth by leave-one-out
#           likelihood). A free placement of each fielder overfit (centre
#           fielder behind short at 170 ft). Gate
#           (scripts/research/fielding/of_shift_gate.py), Wood 2024-2026,
#           fit on two seasons and score the third: beats the unshifted
#           normal outfield in 3/3 held-out seasons vs RHP, 2/3 Total and
#           2/3 vs LHP (both lost 2026); on one season (2026 halves) it
#           failed. It never beat real per-pitch positioning on tracked
#           balls.
# Expected outs: on the hitter's LD + FB that land past the dirt (home runs
# and pop-ups out), the best official Statcast catch probability over the
# three fielders (`catch_grid`, the 95k-play surface), from the distance each
# fielder needs, the opportunity time, the back flag (landing within 30 deg
# of straight behind him) and the wall flag. Opportunity time is Savant's own
# where the ball is a tracked range play, else the `hang_time` kNN (hitter
# held out) plus pitch flight 37.6 / velo. Savant logs mostly outs, so most
# untracked balls are hits. Wall flag: official where tracked; otherwise the
# catch_prob park rule (20+ ft short of the park's shortest wall = no wall),
# and a closer ball scores the mean of the wall and no-wall probabilities, a
# convention.
N_BOOT = 200
FEED_ABBREV_TO_PARK = {'AZ': 'ARI'}
BASE_ANG = {'LF': -28.5, 'CF': -1.1, 'RF': 26.4}       # measured, deg
BASE_DEPTH = {'LF': 295.0, 'CF': 319.0, 'RF': 289.0}   # measured, ft
PHI_GRID = np.arange(-16.5, 18.01, 1.5)                # LF / RF stay fair
DELTA_GRID = np.arange(-80, 61, 5)
M_JITTER = 200      # draws per ball for the smoothed fit (integration, not a knob)
FIT_SEEDS = 5       # smoothed fit repeated on fixed seeds to detect a flat objective


def infield_spots(angs, weights=None):
    """Exact constrained 1-D 4-medians on grounder angle.

    Objective: the (weighted) mean absolute angle from each grounder to the
    NEAREST of the four infielders, the cost the gates score. Constraint:
    3B and SS stand left of second base (angle < 0), 2B and 1B right of it
    (>= 0), the 2023 shift rule; the rule limits where fielders stand, not
    which balls they take, so a SS may own grounders just right of the bag.

    Sorted grounders split into four contiguous runs; each fielder stands
    at his run's weighted median, clamped to his side (the absolute-loss
    optimum under the side constraint); a dynamic program picks the splits.
    Until 2026-10-27 this split the grounders at second base and fitted each
    side alone, which scored 0.44 deg worse than the career infield it had
    produced under Wheeler's weights once the SS was allowed the middle.
    """
    a = np.asarray(angs, float)
    w = np.ones_like(a) if weights is None else np.asarray(weights, float)
    if len(a) < 4:
        sys.exit('Fewer than 4 grounders; no infield can be fitted.')
    o = np.argsort(a)
    a, w = a[o], w[o]
    n = len(a)
    W = np.concatenate([[0.0], np.cumsum(w)])
    A = np.concatenate([[0.0], np.cumsum(w * a)])
    eps = 1e-6

    def run_cost(i, j, left):
        """Cost and centre of runs [i, j) for an array of starts i, one end j."""
        i = np.asarray(i)
        half = W[i] + 0.5 * (W[j] - W[i])
        k = np.clip(np.searchsorted(W, half) - 1, i, j - 1)
        c = a[k]
        c = np.minimum(c, -eps) if left else np.maximum(c, 0.0)
        p = np.clip(np.searchsorted(a, c, side='right'), i, j)
        cost = (c * (W[p] - W[i]) - (A[p] - A[i])) + ((A[j] - A[p]) - c * (W[j] - W[p]))
        return cost, c

    INF = np.inf
    f = np.full((5, n + 1), INF)
    arg = np.zeros((5, n + 1), int)
    f[0, 0] = 0.0
    for layer in range(1, 5):
        left = layer <= 2
        for j in range(layer, n + 1 - (4 - layer)):
            i = np.arange(layer - 1, j)
            cost, _c = run_cost(i, j, left)
            tot = f[layer - 1, i] + cost
            b = int(np.argmin(tot))
            f[layer, j], arg[layer, j] = tot[b], i[b]
    cuts, j = [n], n
    for layer in range(4, 0, -1):
        j = arg[layer, j]
        cuts.append(j)
    cuts = cuts[::-1]
    centres = [float(run_cost(np.array([cuts[m]]), cuts[m + 1], m < 2)[1][0]) for m in range(4)]
    return dict(zip(('3B', 'SS', '2B', '1B'), centres))


def load_tracked(seasons):
    """pitch_id -> Savant range play (opportunity_time, wall)."""
    out = {}
    for season in seasons:
        path = os.path.join(REPO, 'data', f'_range_plays_{season}.json')
        if not os.path.exists(path):
            sys.exit(f'{path} is missing. Build it with: python3 '
                     'scripts/builders/range_plays_pull.py --csv <savant.csv> '
                     f'--season {season}')
        with open(path) as f:
            out.update({r['pitch_id']: r for r in json.load(f)})
    return out


def home_park(game_pk, cache={}):
    if game_pk not in cache:
        with gzip.open(os.path.join(REPO, 'data', '_feed_cache', f'{game_pk}.json.gz'), 'rt') as f:
            ab = json.load(f)['gameData']['teams']['home']['abbreviation']
        cache[game_pk] = FEED_ABBREV_TO_PARK.get(ab, ab)
    return cache[game_pk]


def of_balls(rows, tracked, hmodel):
    """Arrays for the outfield fit: x, y, opportunity time, wall weight."""
    xs, ys, ts, ws, src = [], [], [], [], []
    for r in rows:
        if r['key'] not in ('line_drive', 'fly_ball') or r['event'] == 'Home Run':
            continue
        th = math.atan2(r['x'], r['y'])
        if math.hypot(r['x'], r['y']) <= dirt_arc_r(th):
            continue
        t = tracked.get(r['pitch_id'])
        if t is not None:
            opp, wall, how = float(t['opportunity_time']), float(t['wall']), 'tracked'
        else:
            if None in (r['la'], r['ev'], r['dist'], r['velo']):
                sys.exit(f'{r["pitch_id"]}: no LA/EV/Distance/Velocity for the hang model.')
            hang = float(hmodel.predict([[r['la'], r['ev'], r['dist']]])[0])
            opp, how = hang + 37.6 / r['velo'], 'model'
            park = home_park(r['pitch_id'].split('_')[0])
            if park not in PARKS:
                sys.exit(f'No wall distances for park {park!r} in catch_prob.PARKS.')
            wall = 0.0 if min(PARKS[park]) - r['dist'] >= 20 else 0.5
        xs.append(r['x']); ys.append(r['y']); ts.append(opp); ws.append(wall); src.append(how)
    return (np.array(xs), np.array(ys), np.array(ts), np.array(ws)), src


def out_prob_matrix(cand, balls, grid):
    """P[c, i]: out probability of ball i for a fielder starting at cand c."""
    bx, by, bt, bw = balls
    dx = bx[None, :] - cand[:, :1]
    dy = by[None, :] - cand[:, 1:]
    dist = np.hypot(dx, dy)
    # Angle between the run to the ball and the line from the fielder to
    # home plate; going back = within 30 deg of straight behind (|angle| >= 150).
    hx, hy = -cand[:, :1], -cand[:, 1:]
    cosang = (dx * hx + dy * hy) / np.maximum(dist * np.hypot(hx, hy), 1e-9)
    back = (cosang <= math.cos(math.radians(150))).astype(int)
    t = np.broadcast_to(bt, dist.shape)
    p0 = catch_grid.lookup(grid, t, dist, back, np.zeros_like(back))
    p1 = catch_grid.lookup(grid, t, dist, back, np.ones_like(back))
    return (1 - bw)[None, :] * p0 + bw[None, :] * p1


def positions(phi, delta):
    """LF, CF, RF (x, y) for the normal alignment rotated by phi and moved
    delta ft deeper; None when a fielder would stand within 10 ft of the
    reference fence."""
    out = []
    for k in ('LF', 'CF', 'RF'):
        th = math.radians(BASE_ANG[k] + phi)
        r = BASE_DEPTH[k] + delta
        if r > 330 + 70 * math.cos(2 * th) - 10:
            return None
        out.append((r * math.sin(th), r * math.cos(th)))
    return np.array(out)


def shift_table(balls, grid):
    """Per-ball out probability for every (phi, delta): array [phi, delta,
    ball], NaN rows where the alignment is invalid."""
    tab = np.full((len(PHI_GRID), len(DELTA_GRID), len(balls[0])), np.nan)
    for i, phi in enumerate(PHI_GRID):
        for j, d in enumerate(DELTA_GRID):
            pos = positions(phi, d)
            if pos is not None:
                tab[i, j] = out_prob_matrix(pos, balls, grid).max(0)
    return tab


def smooth(balls, h, rng):
    """Each ball as M_JITTER Gaussian draws (sd h ft) around its landing
    spot, with the ball's own timing and wall weight."""
    bx, by, bt, bw = balls
    n = len(bx)
    jx = np.repeat(bx, M_JITTER) + rng.normal(0, h, n * M_JITTER)
    jy = np.repeat(by, M_JITTER) + rng.normal(0, h, n * M_JITTER)
    return (jx, jy, np.repeat(bt, M_JITTER), np.repeat(bw, M_JITTER))


def smoothed_tab(balls, grid, seed=0, h=None):
    """Per-ball out probability [phi, delta, ball] on smoothed balls, and
    the bandwidth used (leave-one-out likelihood unless h is given)."""
    if h is None:
        h, _w = pick(AIR_BW_GRID, loo_2d(np.column_stack(balls[:2]), AIR_BW_GRID))
    n = len(balls[0])
    t = shift_table(smooth(balls, h, np.random.default_rng(seed)), grid)
    return t.reshape(len(PHI_GRID), len(DELTA_GRID), n, M_JITTER).mean(3), h


def best_shift(v):
    i, j = np.unravel_index(np.nanargmax(v), v.shape)
    edge = []
    if i in (0, len(PHI_GRID) - 1):
        edge.append('phi at foul-line bound')
    if (j in (0, len(DELTA_GRID) - 1) or np.isnan(v[i, max(j - 1, 0)])
            or np.isnan(v[i, min(j + 1, v.shape[1] - 1)])):
        edge.append('delta at grid/fence edge')
    return float(PHI_GRID[i]), float(DELTA_GRID[j]), ', '.join(edge) or 'interior'


def team_of_spots(batter_id, seasons):
    """Teams' mean outfield start spots against this batter (Savant batter
    positioning, scripts/builders/batter_positioning_pull.py), all pitchers."""
    path = os.path.join(REPO, 'data', f'_positioning_{batter_id}.json')
    if not os.path.exists(path):
        sys.exit(f'{path} is missing. Build it with: python3 scripts/builders/'
                 f'batter_positioning_pull.py --id {batter_id} --bats <L|R> --seasons ...')
    with open(path) as f:
        rows = [r for r in json.load(f) if r['season'] in seasons]
    out = []
    for pid in (7, 8, 9):
        pts = np.array([[float(r['start_pos_x']), float(r['start_pos_y'])]
                        for r in rows if int(r['pos_id']) == pid])
        if not len(pts):
            sys.exit(f'No positioning rows for fielder {pid} in {seasons}.')
        out.append(pts.mean(0))
    return np.array(out)


def fit_spots(rows, rng, tracked, hmodel, grid, of_mode, total_gb, fallback_of=None):
    inf = infield_spots(total_gb)
    balls, src = of_balls(rows, tracked, hmodel)
    raw = shift_table(balls, grid)
    i0, j0 = int(np.argmin(np.abs(PHI_GRID))), int(np.argmin(np.abs(DELTA_GRID)))
    normal_xouts = float(raw.sum(2)[i0, j0])
    # The fit reads SMOOTHED balls (variant B of the gate, which beat the raw
    # fit across the held-out seasons): bandwidth by leave-one-out likelihood
    # on these balls, and the per-ball out probability averaged over draws.
    h, hw = pick(AIR_BW_GRID, loo_2d(np.column_stack(balls[:2]), AIR_BW_GRID))
    n = len(balls[0])
    # Fixed seeds, own generators: the fit must not depend on how much of
    # the shared generator the bootstrap used before it.
    fits, tab = [], None
    for seed in range(FIT_SEEDS):
        t, _h = smoothed_tab(balls, grid, seed, h)
        tab = t if tab is None else tab
        fits.append(best_shift(t.sum(2)))
    phi, delta, where = fits[0]
    fit_xouts = float(raw.sum(2)[list(PHI_GRID).index(phi), list(DELTA_GRID).index(delta)])
    # Flat: the chosen shift moves more than one grid step between seeds, or
    # does not beat the normal outfield on the real balls. Then no shift is
    # supported and the panel draws the normal outfield.
    spread_phi = max(f[0] for f in fits) - min(f[0] for f in fits)
    spread_delta = max(f[1] for f in fits) - min(f[1] for f in fits)
    flat = (spread_phi > PHI_GRID[1] - PHI_GRID[0] or spread_delta > DELTA_GRID[1] - DELTA_GRID[0]
            or fit_xouts <= normal_xouts)

    boot = {k: [] for k in inf}
    draw_fit = of_mode == 'fitted' and not flat
    if draw_fit:
        boot.update({k: [] for k in ('LF', 'CF', 'RF')})
    for _ in range(N_BOOT):
        bi = infield_spots(total_gb[rng.integers(0, len(total_gb), len(total_gb))])
        for k, a in bi.items():
            boot[k].append(_if_xy(a))
        if draw_fit:
            bp, bd, _w = best_shift(tab[:, :, rng.integers(0, n, n)].sum(2))
            for k, xy in zip(('LF', 'CF', 'RF'), positions(bp, bd)):
                boot[k].append(xy)
    spots = {k: _if_xy(a) for k, a in inf.items()}
    # A flat panel falls back to the teams' real spots against this batter
    # when given (Wally 2026-10-28): fixed and never fitted to his balls, they
    # beat the league-normal outfield in 3/3 seasons for Wood's Total.
    use_teams = of_mode == 'fitted' and flat and fallback_of is not None
    of_pos = (positions(phi, delta) if draw_fit
              else np.asarray(fallback_of) if use_teams else positions(0.0, 0.0))
    teams_xouts = (float(out_prob_matrix(np.asarray(fallback_of), balls, grid).max(0).sum())
                   if fallback_of is not None else None)
    spots.update(zip(('LF', 'CF', 'RF'), of_pos))
    of = {'mode': of_mode, 'n': n, 'tracked': src.count('tracked'),
          'model': src.count('model'), 'wall_mixed': int((balls[3] == 0.5).sum()),
          'normal_xouts': normal_xouts, 'fit_xouts': fit_xouts,
          'phi': phi, 'delta': delta, 'where': where, 'bw': h, 'bw_where': hw,
          'flat': flat, 'seed_fits': [(f[0], f[1]) for f in fits],
          'teams_fallback': use_teams, 'teams_xouts': teams_xouts}
    return spots, {k: np.array(b) for k, b in boot.items()}, inf, of


def _if_xy(ang):
    th = math.radians(ang)
    r = mid_dirt_r(th)
    return np.array([r * math.sin(th), r * math.cos(th)])


def draw_spots(ax, spots, boot):
    # 68% covariance ellipse of the resampled spots (chi-square, 2 dof).
    for k, pts in boot.items():
        cov = np.cov(pts.T)
        vals, vecs = np.linalg.eigh(cov)
        vals = np.clip(vals, 0, None)
        ang = math.degrees(math.atan2(vecs[1, 1], vecs[0, 1]))
        sc = math.sqrt(2.279)
        ax.add_patch(Ellipse(pts.mean(0), 2 * sc * math.sqrt(vals[1]),
                             2 * sc * math.sqrt(vals[0]), angle=ang,
                             facecolor='none', edgecolor=FIELDER, alpha=0.7,
                             lw=1.0, ls=(0, (3, 2)), zorder=6))
    for k, (x, y) in spots.items():
        ax.scatter([x], [y], s=330, color=FIELDER, edgecolor=BG, linewidths=1.5,
                   zorder=7)
        ax.text(x, y, k, fontsize=7.5, fontfamily=BODY_FONT, fontweight='700',
                color=BG, ha='center', va='center', zorder=8)


def summary(ax, rows, bats, spots, inf, of):
    ax.axis('off')
    n = len(rows)
    mix = '   '.join(f'{BB_LABELS[k]} {100 * sum(r["key"] == k for r in rows) / n:.0f}%'
                     for k in BB_TYPES)
    pull_sign = 1 if bats == 'L' else -1

    def ppo(rs):
        if not rs:
            return '-'
        a = np.array([r['ang'] for r in rs]) * pull_sign
        return (f'Pull {100 * (a > 15).mean():.0f}%  Center {100 * (np.abs(a) <= 15).mean():.0f}%  '
                f'Oppo {100 * (a < -15).mean():.0f}%')
    gb = [r for r in rows if r['key'] == 'ground_ball']
    air = [r for r in rows if r['key'] in ('line_drive', 'fly_ball')]
    lines = [mix, f'Grounders: {ppo(gb)}', f'LD + FB: {ppo(air)}']
    # Spot positions: infield as spray angle (+ = right field), outfield as
    # angle and distance from home.
    # + 0 turns the SS's -0.000001 (left of the bag by rule) into a plain 0.
    lines.append('Infield: ' + '   '.join(f'{k} {round(inf[k]) + 0:.0f} deg'
                                         for k in ('3B', 'SS', '2B', '1B')))
    lines.append('Outfield: ' + '   '.join(
        f'{k} {math.degrees(math.atan2(*spots[k])):.0f} deg, {math.hypot(*spots[k]):.0f} ft'
        for k in ('LF', 'CF', 'RF')))
    side = 'left' if of['phi'] < 0 else 'right'
    shift = (f'rotated {abs(of["phi"]):g} deg toward {side} field, '
             f'{abs(of["delta"]):g} ft {"deeper" if of["delta"] >= 0 else "shallower"}')
    if of['mode'] == 'fitted' and of['flat'] and of['teams_fallback']:
        lines.append(f"No shift held up, so teams' spots vs this hitter: {of['teams_xouts']:.1f} "
                     f"expected outs on {of['n']} (normal {of['normal_xouts']:.1f})")
    elif of['mode'] == 'fitted' and of['flat']:
        lines.append(f'No shift supported (flat: fit moves with random draws or does not beat '
                     f'normal).  Normal: {of["normal_xouts"]:.1f} expected outs on {of["n"]}')
    elif of['mode'] == 'normal':
        lines.append(f'Expected outs on {of["n"]} LD + FB: normal {of["normal_xouts"]:.1f}  '
                     f'(fitted shift, {shift}: {of["fit_xouts"]:.1f})')
    else:
        lines.append(f'Fitted: {shift}.  Expected outs on {of["n"]} LD + FB: '
                     f'{of["fit_xouts"]:.1f} vs normal {of["normal_xouts"]:.1f}')
    for i, s in enumerate(lines):
        ax.text(0.5, 0.97 - 0.165 * i, s, transform=ax.transAxes, fontsize=8.6,
                fontfamily=BODY_FONT, color=TEXT_SECOND, ha='center', va='top')


def panel(fig, box, rows, label, bats, notes, points, rng, ctx):
    ax = fig.add_axes(box)
    ax.set_facecolor(BG)
    draw_field(ax)
    gb = np.array([r['ang'] for r in rows if r['key'] == 'ground_ball'])
    air = np.array([[r['x'], r['y']] for r in rows
                    if r['key'] in ('line_drive', 'fly_ball') and r['event'] != 'Home Run'])
    h_gb, w_gb = pick(GB_BW_GRID, loo_1d(gb, GB_BW_GRID))
    h_air, w_air = pick(AIR_BW_GRID, loo_2d(air, AIR_BW_GRID))
    notes.append((label, len(gb), h_gb, w_gb, len(air), h_air, w_air))
    shade_infield(ax, gb, h_gb)
    shade_outfield(ax, air, h_air)
    if points:
        draw_points(ax, rows)
    slice_labels(ax, gb)
    spots, boot, inf, of = fit_spots(rows, rng, *ctx)
    draw_spots(ax, spots, boot)
    notes[-1] += (spots, inf, of)
    for sgn, word in ((1, 'PULL'), (-1, 'OPPO')):
        s = sgn if bats == 'L' else -sgn
        th = math.radians(s * 41)
        ax.text(352 * math.sin(th), 352 * math.cos(th), word, fontsize=8.5,
                color=TEXT_FAINT, fontfamily=BODY_FONT, fontweight='600',
                ha='center', va='center', zorder=3)
    ax.set_xlim(-XSPAN / 2, XSPAN / 2)
    ax.set_ylim(Y0, Y0 + YSPAN)
    ax.set_aspect('equal', adjustable='box')
    ax.axis('off')
    ax.set_title(f'{label}  ({len(rows)} BIP)', fontsize=14, fontfamily=TITLE_FONT,
                 fontweight='700', color=TEXT_PRIMARY, pad=4)
    fh = fig.get_figheight()
    sax = fig.add_axes([box[0], box[1] - 1.75 / fh, box[2], 1.7 / fh])
    summary(sax, rows, bats, spots, inf, of)


def legend(fig, points):
    if not points:
        h = [Line2D([0], [0], marker='s', color='none', markerfacecolor=SHADE(v),
                    markeredgecolor='none', markersize=11, label=lab)
             for v, lab in ((0.15, 'Few batted balls'), (0.55, ''), (1.0, 'Most batted balls'))]
        h += [Line2D([0], [0], marker='o', color='none', markerfacecolor=FIELDER,
                     markersize=11, label='Suggested fielder spot'),
              Ellipse((0, 0), 1, 1, facecolor='none', edgecolor=FIELDER, alpha=0.7,
                      ls=(0, (3, 2)), label='Where the spot lands on 68% of resamples')]
        fig.legend(handles=h, loc='upper center',
                   bbox_to_anchor=(0.5, 1 - 1.05 / fig.get_figheight()), ncol=len(h),
                   frameon=False, prop={'family': BODY_FONT, 'size': 9},
                   labelcolor=TEXT_SECOND, handletextpad=0.3, columnspacing=1.0)
        return
    h = [Line2D([0], [0], marker='o', color='none', markerfacecolor=BB_COLORS[k],
                markeredgecolor=TEXT_SECOND, markeredgewidth=MARKER_EDGE_W,
                markersize=8, label=BB_LABELS[k]) for k in BB_TYPES]
    h += [Line2D([0], [0], marker='o', color='none', markerfacecolor=TEXT_MUTED,
                 markeredgecolor=TEXT_SECOND, markersize=8, label='Hit (filled)'),
          Line2D([0], [0], marker='o', color='none', markerfacecolor='none',
                 markeredgecolor=TEXT_MUTED, markeredgewidth=1.3, markersize=8,
                 label='Out (hollow)')]
    for ev in (75, 90, 105):
        h.append(Line2D([0], [0], marker='o', color='none', markerfacecolor='none',
                        markeredgecolor=TEXT_MUTED, markersize=math.sqrt(ev_size(ev)),
                        label=f'{ev} mph'))
    fig.legend(handles=h, loc='upper center', bbox_to_anchor=(0.5, 1 - 1.05 / fig.get_figheight()), ncol=len(h),
               frameon=False, prop={'family': BODY_FONT, 'size': 9},
               labelcolor=TEXT_SECOND, handletextpad=0.3, columnspacing=1.2)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--batter', help='Sheets name, "Last, First"')
    src.add_argument('--csv', help='Baseball Savant search CSV for one batter')
    ap.add_argument('--title', default=None)
    ap.add_argument('--out', required=True, help='output .pdf or .png')
    ap.add_argument('--seasons', type=int, nargs='+', default=[2026])
    ap.add_argument('--note', default=None,
                    help='the gate verdict to print under the title (fitted mode); '
                         'without it the chart says the fit is not validated')
    ap.add_argument('--of', choices=('normal', 'fitted'), default='normal',
                    help='outfield spots: measured normal, or the 2-number shift '
                         'fitted in sample (failed the season-half gate)')
    ap.add_argument('--no-points', action='store_true',
                    help='draw the shading and fielder spots only')
    args = ap.parse_args()

    rows, dropped, (d0, d1) = load(args.batter, args.csv, args.seasons)
    if not rows:
        sys.exit(f'No batted balls for {args.batter or args.csv!r}. '
                 'Refresh the pickle with: python3 -m pipeline.refresh_pickle')
    sides = {r['bats'] for r in rows}
    if len(sides) != 1 or sides.pop() not in ('L', 'R'):
        sys.exit(f'Expected one batting side, got {sorted({r["bats"] for r in rows})}. '
                 'A switch hitter needs a per-side split first.')
    bats = rows[0]['bats']
    unknown_hand = [r for r in rows if r['throws'] not in ('R', 'L')]
    if unknown_hand:
        sys.exit(f'{len(unknown_hand)} batted balls have no pitcher hand (Throws).')

    name = args.batter or pd.read_csv(os.path.expanduser(args.csv), nrows=1).player_name.iat[0]
    title = args.title or ' '.join(reversed(name.split(', ')))
    yrs = (str(args.seasons[0]) if len(args.seasons) == 1
           else f'{min(args.seasons)}-{max(args.seasons)}')
    # Each field box is sized to the field's own aspect, so no panel space
    # is left blank under the plate.
    fig_w, w, gap, left = 20.0, 0.315, 0.0125, 0.0125
    field_h_in = w * fig_w * YSPAN / XSPAN
    fig_h = field_h_in + 4.6
    fig = plt.figure(figsize=(fig_w, fig_h), facecolor=BG)
    bottom = 2.75 / fig_h
    top_pad = 1.85 / fig_h
    fig.text(0.02, 1 - 0.25 / fig_h, f'{title}  |  Spray chart, {yrs}', fontsize=24,
             fontfamily=TITLE_FONT, fontweight='700', color=TEXT_PRIMARY, va='top')
    of_note = ('Outfield: normal positions (league-average starts), no shift.'
               if args.of == 'normal' else
               f'Outfield: best 2-number shift of the normal positions, fitted on {yrs}.  '
               + (args.note or 'NOT validated out of sample.'))
    source = 'Baseball Savant data' if args.csv else 'Sheets pitch data'
    fig.text(0.02, 1 - 0.72 / fig_h, f'Bats {bats}.  {d0} to {d1}, {source}.  '
             f'Infield: Total-panel spots on every panel.  {of_note}',
             fontsize=11, fontfamily=BODY_FONT, color=TEXT_MUTED, va='top')
    legend(fig, not args.no_points)
    notes = []
    rng = np.random.default_rng(0)
    tracked = load_tracked(args.seasons)
    ids = {tracked[r['pitch_id']]['batter_id'] for r in rows if r['pitch_id'] in tracked}
    if len(ids) != 1:
        sys.exit(f'Cannot resolve one MLB id for {title!r} from the range plays: {ids}')
    hang_id = ids.pop()
    hmodel, hsweep, hk, hwhere = hang_time.fit(args.seasons, exclude=hang_id)
    grid, _n_filled = catch_grid.fill(catch_grid.build())
    total_gb = np.array([r['ang'] for r in rows if r['key'] == 'ground_ball'])
    batter_id = hang_id
    fallback = team_of_spots(batter_id, args.seasons) if args.of == 'fitted' else None
    ctx = (tracked, hmodel, grid, args.of, total_gb, fallback)
    for i, (label, sub) in enumerate((
            ('Total', rows),
            ('vs RHP', [r for r in rows if r['throws'] == 'R']),
            ('vs LHP', [r for r in rows if r['throws'] == 'L']))):
        panel(fig, [left + i * (w + gap), bottom, w, 1 - bottom - top_pad],
              sub, label, bats, notes, not args.no_points, rng, ctx)

    bw = '   '.join(f'{lab}: GB {hg:g} deg ({wg}), air {ha:g} ft ({wa})'
                   for lab, _, hg, wg, _, ha, wa, *_ in notes)
    foot = ('Infield shading: grounder direction density on the dirt; % = share of grounders '
            'in each 15 deg slice.  Outfield shading: LD + FB landing density, home runs '
            'excluded.  Each shading is scaled to its own maximum.\n'
            f'Bandwidths by leave-one-out likelihood per panel: {bw}.  '
            'Fence is a 330 / 400 / 330 ft reference, not a park.\n'
            'Fielder spots: infield = smallest mean angle to a grounder, two per side of 2B, '
            'drawn at mid-dirt depth.  Normal outfield = play-weighted 2026 average start '
            'positions.  Expected outs on LD + FB past the dirt (home runs, pop-ups out) '
            'from the official Statcast catch-probability surface; '
            f'hang time from Savant where tracked, else a kNN model (k={hk}, {hwhere}).\n'
            'Angles: 0 = over 2B, negative = left field.  Ellipse: where the spot lands on '
            '68% of 200 bootstrap resamples.')
    if dropped:
        foot += f'  {dropped} batted balls without a location were skipped.'
    fig.text(0.02, 0.012, foot, fontsize=8, fontfamily=BODY_FONT, color=TEXT_FAINT,
             va='bottom', linespacing=1.6)

    out = os.path.expanduser(args.out)
    tmp = out + '.tmp' + os.path.splitext(out)[1]
    fig.savefig(tmp, dpi=200, facecolor=BG)
    plt.close(fig)
    os.replace(tmp, out)

    print(f'{len(rows)} batted balls ({d0} to {d1}), {dropped} skipped -> {out}')
    print(f'hang-time kNN: k={hk} ({hwhere}); CV MAE by k: '
          + '  '.join(f'{k}:{e:.4f}' for k, e in hsweep))
    for lab, ngb, hg, wg, nair, ha, wa, spots, inf, of in notes:
        print(f'  {lab:7s} GB n={ngb:3d} bw={hg:5.1f} deg [{wg}]   '
              f'LD+FB n={nair:3d} bw={ha:6.1f} ft [{wa}]')
        print(f'          OF on {of["n"]} balls ({of["tracked"]} tracked, {of["model"]} '
              f'model hang, {of["wall_mixed"]} wall-ambiguous): normal {of["normal_xouts"]:.2f}, '
              f'fitted {of["fit_xouts"]:.2f} at phi {of["phi"]:g} delta {of["delta"]:g} '
              f'[{of["where"]}]  seeds {of["seed_fits"]}  flat={of["flat"]}')
        print('          ' + '  '.join(f'{k} {inf[k]:+.1f}' for k in ('3B', 'SS', '2B', '1B'))
              + '  |  ' + '  '.join(
                  f'{k} ({spots[k][0]:.0f}, {spots[k][1]:.0f})' for k in ('LF', 'CF', 'RF')))


if __name__ == '__main__':
    main()
