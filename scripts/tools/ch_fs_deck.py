"""Changeup + splitter deck: pitchers who throw BOTH in the same outing.

One PDF, two landscape pages per pitcher:
  1. movement plot (both hands pooled) + location plots by batter hand,
     TOTALS table, BY HAND table
  2. usage-by-count grids (both hands, vs RHH, vs LHH), the site's table

Every table row is one pitch type (CH or FS) inside one cell (hand, count
bucket, or both). Usage% is that pitch's share of ALL pitches in the cell,
the same reading as the site's "Usage by count" table. Rates blank ('-')
when their denominator is zero; n is always printed so thin cells read as
thin.

Definitions follow the cards: swings via pipeline.utils.is_swing (bunts
out), Zone% from the cached InZone column (exact Savant geometry), Chase%
= swings on out-of-zone pitches / out-of-zone pitches, Whiff% = swinging
strikes / swings, xwOBAcon = mean xwOBA on balls in play that carry one,
xRV per pitch is the SITE's compute_xrv: a priced BIP by
(xwOBA - lgWOBA)/wOBAScale plus the per-count anchoring offset, an unpriced
BIP by the league anchored mean for its count, everything else by RunExp;
pitcher perspective, positive = good for the pitcher. Stuff+ and Loc+ are the means of the
per-pitch atoms in the cache. Count buckets are the site's
(js/player-page.js) plus a Full Count column: behind includes 2-0 and 3-0;
two-strike overlaps ahead, even and full count, as on Savant.

Run from the repo root:
    python3 scripts/tools/ch_fs_deck.py
    python3 scripts/tools/ch_fs_deck.py --team-split "Gausman, Kevin"   # combined + per club
    python3 scripts/tools/ch_fs_deck.py --only "Griffin, Foster" "Skenes, Paul"   # subset
"""
import os
import sys
import json
import pickle
from math import sin, cos, atan2, pi

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle, Ellipse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from pipeline.utils import is_swing, compute_in_zone  # noqa: E402
from pipeline.sdplus import build_bip_count_offsets, get_count  # noqa: E402
from pipeline.compute import build_bip_count_means  # noqa: E402

CACHE = os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl')
META = os.path.join(ROOT, 'data', 'metadata_rs.json')
OUT = os.path.join(os.path.expanduser('~'), 'Downloads', 'ch_fs_same_outing_2026.pdf')

# ── settings ─────────────────────────────────────────────────────────────
PITCHERS = ['Griffin, Foster', 'Skenes, Paul', 'Gilbert, Logan', 'Gausman, Kevin',
            'Lugo, Seth', 'Lorenzen, Michael', 'Barco, Hunter', 'Kirby, George',
            'Urquidy, José', 'Imai, Tatsuya', 'Knack, Landon']
TYPES = ['CH', 'FS']
COLORS = {'CH': '#009E73', 'FS': '#CC79A7'}          # Okabe-Ito, shared with the cards
NAMES = {'CH': 'Changeup', 'FS': 'Splitter'}
COUNT_BUCKETS = [                                    # js/player-page.js:2947
    ('First Pitch', {'0-0'}),
    ('Pitcher Ahead', {'0-1', '0-2', '1-2'}),
    ('Pitcher Behind', {'1-0', '2-0', '3-0', '2-1', '3-1'}),
    ('Even', {'1-1', '2-2'}),
    ('Two-Strike', {'0-2', '1-2', '2-2', '3-2'}),
    ('Full Count', {'3-2'}),      # Savant: 3-2 is inside "Two strikes" AND its own "Full count" filter
]
HANDS = [('vs RHH', 'R'), ('vs LHH', 'L')]

# palette (cards/pitcher.py)
BG = '#f0e8d8'; DARK_CELL = '#e2d8c4'; DARKER = '#d8ccb4'; ACCENT = '#9f3026'
TEXT_PRIMARY = '#1a1612'; TEXT_SECONDARY = '#3a3530'; TEXT_MUTED = '#6a5f55'
SUBTLE_BORDER = '#c5b89f'; PLOT_PANEL = '#e8dfcb'; GRID_COLOR = '#c5b89f'
PLATE_HALF = 0.7083

for _fn in sorted(os.listdir(os.path.join(ROOT, 'assets', 'fonts'))):
    if _fn.lower().endswith(('.ttf', '.otf')):
        fm.fontManager.addfont(os.path.join(ROOT, 'assets', 'fonts', _fn))
plt.rcParams['font.family'] = 'IBM Plex Sans'

_g = json.load(open(META)).get('gutsConstants') or {}
LG_WOBA, WOBA_SCALE = float(_g['lgWOBA']), float(_g['wOBAScale'])


# ── helpers ──────────────────────────────────────────────────────────────
def sf(v):
    if v is None or v == '':
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(f) else f


def avg_tilt(tilts):
    sins, coss = [], []
    for t in tilts:
        if not t or ':' not in str(t):
            continue
        h, m = str(t).split(':')
        h, m = int(h), int(m)
        if h == 12:
            h = 0
        a = (h * 60 + m) / 720 * 2 * pi
        sins.append(sin(a)); coss.append(cos(a))
    if not sins:
        return '-'
    am = (atan2(sum(sins) / len(sins), sum(coss) / len(coss)) * 720 / (2 * pi)) % 720
    h, m = int(am // 60), int(am % 60)
    return f'{12 if h == 0 else h}:{m:02d}'


XRV_OFFSETS = {}
XRV_BIP_MEANS = {}


def build_xrv_anchors(mlb_pitches):
    """The site's count anchors (process_data ~1856), built on every MLB
    pitch in the cache. process_data also drops position-player pitching from
    this baseline; measured effect there is 0.0007 runs, below display."""
    XRV_OFFSETS.update(build_bip_count_offsets(mlb_pitches, LG_WOBA, WOBA_SCALE))
    XRV_BIP_MEANS.update(build_bip_count_means(mlb_pitches, LG_WOBA, WOBA_SCALE, XRV_OFFSETS))


def pitch_xrv(p):
    """Per-pitch xRV, pitcher perspective, the site's compute_xrv branch by branch."""
    if p.get('Description') == 'In Play':
        c = get_count(p)
        xw = sf(p.get('xwOBA'))
        if xw is not None:
            return -((xw - LG_WOBA) / WOBA_SCALE + XRV_OFFSETS.get(c, 0.0))
        if c in XRV_BIP_MEANS:
            return -XRV_BIP_MEANS[c]
    return sf(p.get('RunExp'))


def in_zone(p):
    iz = p.get('InZone')
    if iz not in ('Yes', 'No'):
        iz = compute_in_zone(p)
    return None if iz is None else iz == 'Yes'


def mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def pct(num, den):
    return None if not den else 100.0 * num / den


def fmt(v, spec):
    if v is None:
        return '-'
    dec = {'pct': 1, 'woba': 3, 'int': 0, 'rv': 1, 'rv2': 2}.get(spec, 1)
    if round(v, dec) == 0:
        v = 0.0   # no '-0.0'
    if spec == 'pct':
        return f'{v:.1f}%'
    if spec == 'woba':
        s = f'{v:.3f}'
        return s[1:] if s.startswith('0') else s
    if spec == 'int':
        return f'{v:.0f}'
    if spec == 'rv':
        return f'{v:.1f}'
    if spec == 'rv2':
        return f'{v:.2f}'
    return f'{v:.1f}'


COLS = [  # (header, key, format)
    ('Pitch', 'pitch', None), ('n', 'n', 'int'), ('Usage%', 'usage', 'pct'),
    ('Velo', 'velo', '1'), ('Spin', 'spin', 'int'), ('IVB', 'ivb', '1'), ('HB', 'hb', '1'),
    ('RTilt', 'rtilt', None), ('OTilt', 'otilt', None),
    ('Stuff+', 'stuff', 'int'), ('Loc+', 'loc', 'int'),
    ('Zone%', 'zone', 'pct'), ('Whiff%', 'whiff', 'pct'), ('Chase%', 'chase', 'pct'),
    ('xwOBAcon', 'xwobacon', 'woba'), ('xRV', 'xrv', 'rv'), ('xRV/100', 'xrv100', 'rv'),
]


# ── percentile pools (2026-09-12, per Wally) ─────────────────────────────
# Tinted columns: Stuff+ through xRV/100. Pool = every MLB pitcher-by-type
# unit with >= POOL_MIN pitches, split by PITCHER hand (a LHP changeup is
# graded against LHP changeups), and for the hand tables also by BATTER
# hand (LHP CH vs LHH against every LHP's CH vs LHH). Every row is tinted,
# whatever its n; the floor gates the POOL only. xwOBAcon inverts.
COLOR_KEYS = ['stuff', 'loc', 'zone', 'whiff', 'chase', 'xwobacon', 'xrv', 'xrv100']
INVERT = {'xwobacon'}
POOL_MIN = 25
POOLS = {}   # (throws, pitch_type, bats or None) -> {key: sorted ndarray}


def build_pools(mlb_records):
    df = pd.DataFrame(mlb_records)
    df = df[df['Pitch Type'].isin(TYPES) & df['Throws'].isin(['L', 'R'])]
    acc = {}
    for bats_split in (False, True):
        keys = ['Pitcher', 'Throws', 'Pitch Type'] + (['Bats'] if bats_split else [])
        for gk, g in df.groupby(keys):
            if len(g) < POOL_MIN:
                continue
            thr, pt = gk[1], gk[2]
            bats = gk[3] if bats_split else None
            if bats_split and bats not in ('L', 'R'):
                continue
            m = metrics(g.to_dict('records'), len(g), '')
            d = acc.setdefault((thr, pt, bats), {k: [] for k in COLOR_KEYS})
            for k in COLOR_KEYS:
                if m[k] is not None:
                    d[k].append(m[k])
    for pk, d in acc.items():
        POOLS[pk] = {k: np.sort(np.array(v, dtype=float)) for k, v in d.items()}
    print(f'  pools: {len(POOLS)} (hand x type x bats), '
          f'e.g. R/FS/all n={len(POOLS.get(("R", "FS", None), {}).get("stuff", []))}')


def percentile(v, arr, invert=False):
    if v is None or arr is None or len(arr) == 0:
        return None
    lo = np.searchsorted(arr, v, 'left'); hi = np.searchsorted(arr, v, 'right')
    p = 100.0 * (lo + 0.5 * (hi - lo)) / len(arr)
    return 100.0 - p if invert else p


def pctl_cell_color(pctl, row_bg_hex):
    """cards/pitcher._pctl_cell_color: slate below 50, brick above, from the row bg."""
    if pctl is None:
        return None
    intensity = max(-1.0, min(1.0, (pctl - 50) / 50.0))
    target = (168, 54, 40) if intensity >= 0 else (86, 118, 152)
    alpha = abs(intensity) * 0.72
    rb, rg, rbb = (int(row_bg_hex[i:i + 2], 16) for i in (1, 3, 5))
    return '#%02x%02x%02x' % (int(rb * (1 - alpha) + target[0] * alpha),
                              int(rg * (1 - alpha) + target[1] * alpha),
                              int(rbb * (1 - alpha) + target[2] * alpha))


def metrics(ps, cell_total, label):
    """One table row for the pitches `ps` of one type inside a cell of `cell_total` pitches."""
    n = len(ps)
    swings = [p for p in ps if is_swing(p)]
    whiffs = [p for p in swings if p.get('Description') == 'Swinging Strike']
    iz = [(p, in_zone(p)) for p in ps]
    known = [z for _, z in iz if z is not None]
    ooz = [p for p, z in iz if z is False]
    ooz_sw = [p for p in ooz if is_swing(p)]
    bip_xw = [sf(p.get('xwOBA')) for p in ps if p.get('Description') == 'In Play']
    xrvs = [pitch_xrv(p) for p in ps]
    xrvs = [v for v in xrvs if v is not None]
    xrv = sum(xrvs) if xrvs else None
    return {
        'pitch': label, 'n': n, 'usage': pct(n, cell_total),
        'velo': mean(sf(p.get('Velocity')) for p in ps),
        'spin': mean(sf(p.get('Spin Rate')) for p in ps),
        'ivb': mean(sf(p.get('IndVertBrk')) for p in ps),
        'hb': mean(sf(p.get('HorzBrk')) for p in ps),
        'rtilt': avg_tilt(p.get('RTilt') for p in ps),
        'otilt': avg_tilt(p.get('OTilt') for p in ps),
        'stuff': mean(sf(p.get('Stuff+')) for p in ps),
        'loc': mean(sf(p.get('Loc+')) for p in ps),
        'zone': pct(sum(known), len(known)),
        'whiff': pct(len(whiffs), len(swings)),
        'chase': pct(len(ooz_sw), len(ooz)),
        'xwobacon': mean(bip_xw),
        'xrv': xrv,
        'xrv100': (100.0 * xrv / len(xrvs)) if xrvs else None,
    }


def rows_for(cell_pitches, tag, throws=None, bats=None):
    """throws given -> rows carry _pctl against POOLS[(throws, type, bats)]."""
    tot = len(cell_pitches)
    out = []
    for t in TYPES:
        ps = [p for p in cell_pitches if p.get('Pitch Type') == t]
        m = metrics(ps, tot, f'{t}{tag}')
        if throws is not None:
            pool = POOLS.get((throws, t, bats), {})
            m['_pctl'] = {k: percentile(m[k], pool.get(k), k in INVERT) for k in COLOR_KEYS}
        out.append((t, m))
    return out


# ── drawing ──────────────────────────────────────────────────────────────
HAND_KEYS = ['pitch', 'n', 'usage', 'stuff', 'loc', 'zone', 'whiff', 'chase', 'xwobacon', 'xrv', 'xrv100']


def draw_table(fig, top, title, rows, row_h=0.024, left=0.035, right=0.965, keys=None):
    """rows: list of (type, dict). keys: column subset (default all). Returns the y below the table."""
    # Every table keeps the FULL column grid so the hand tables line up under
    # TOTALS; columns outside `keys` render as blank cells.
    cols = COLS
    fig.text(left, top, title, fontsize=9.5, fontweight='bold', color=TEXT_SECONDARY, va='bottom')
    top -= 0.008
    widths = [0.9 if c[1] == 'pitch' else 0.7 if c[1] == 'n' else 0.9 if c[1] == 'usage' else 0.8 for c in cols]
    tw = sum(widths); xs = [left]
    for w in widths:
        xs.append(xs[-1] + (right - left) * w / tw)
    # header
    fig.patches.append(Rectangle((left, top - row_h), right - left, row_h, transform=fig.transFigure,
                                 facecolor=DARKER, edgecolor='none'))
    for i, (h, key, _) in enumerate(cols):
        if keys is not None and key not in keys:
            continue   # blank header over a blank column
        fig.text((xs[i] + xs[i + 1]) / 2, top - row_h / 2, h, ha='center', va='center',
                 fontsize=7.4, fontweight='bold', color=TEXT_SECONDARY)
    y = top - row_h
    for k, (t, r) in enumerate(rows):
        fig.patches.append(Rectangle((left, y - row_h), right - left, row_h, transform=fig.transFigure,
                                     facecolor=DARK_CELL if k % 2 else BG, edgecolor='none'))
        for i, (_, key, spec) in enumerate(cols):
            cx = (xs[i] + xs[i + 1]) / 2
            if keys is not None and key not in keys:
                continue   # blank cell, keeps the grid aligned with TOTALS
            pc = (r.get('_pctl') or {}).get(key)
            if pc is not None:
                face = pctl_cell_color(pc, DARK_CELL if k % 2 else BG)
                fig.patches.append(Rectangle((xs[i], y - row_h), xs[i + 1] - xs[i], row_h,
                                             transform=fig.transFigure, facecolor=face, edgecolor='none'))
            if key == 'pitch':
                fig.text(cx, y - row_h / 2, r['pitch'], ha='center', va='center', fontsize=7.6,
                         fontweight='bold', color=COLORS[t])
            else:
                v = r[key]
                s = v if isinstance(v, str) else fmt(v, spec)
                fig.text(cx, y - row_h / 2, s, ha='center', va='center', fontsize=7.6,
                         color=TEXT_PRIMARY, fontweight='bold' if key == 'n' else 'normal')
        y -= row_h
    fig.lines.append(plt.Line2D([left, right], [y, y], transform=fig.transFigure, color=SUBTLE_BORDER, lw=0.6))
    return y - 0.03


def header(fig, name, team, throws, ps, outings_both, page):
    fig.patch.set_facecolor(BG)
    fig.text(0.035, 0.955, name, fontsize=17, fontweight='bold', color=TEXT_PRIMARY, family='Bitter')
    n_ch = sum(p.get('Pitch Type') == 'CH' for p in ps)
    n_fs = sum(p.get('Pitch Type') == 'FS' for p in ps)
    sub = f'{team}  ·  {throws}HP  ·  2026 MLB  ·  CH {n_ch}  ·  FS {n_fs}'
    fig.text(0.035, 0.925, sub, fontsize=9, color=TEXT_MUTED)
    fig.text(0.965, 0.925, f'page {page} of 2', ha='right', fontsize=8, color=TEXT_MUTED)
    fig.lines.append(plt.Line2D([0.035, 0.965], [0.912, 0.912], transform=fig.transFigure, color=ACCENT, lw=1.2))


def style_panel(ax):
    ax.set_facecolor(PLOT_PANEL)
    for s in ax.spines.values():
        s.set_color(SUBTLE_BORDER)


def movement_plot(ax, ps):
    style_panel(ax)
    lim = 25
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
    tks = list(range(-lim, lim + 1, 5))
    ax.set_xticks(tks); ax.set_yticks(tks)
    ax.tick_params(labelsize=6.5, colors=TEXT_PRIMARY, length=2)
    for t in tks:
        lw, a = (0.9, 0.9) if t == 0 else (0.5, 0.7)
        ax.axhline(t, color=GRID_COLOR, lw=lw, alpha=a, ls='-' if t == 0 else '--', zorder=1)
        ax.axvline(t, color=GRID_COLOR, lw=lw, alpha=a, ls='-' if t == 0 else '--', zorder=1)
    ax.set_xlabel('HORIZONTAL BREAK (in)', fontsize=7, fontweight='bold', color=TEXT_PRIMARY)
    ax.set_ylabel('INDUCED VERTICAL BREAK (in)', fontsize=7, fontweight='bold', color=TEXT_PRIMARY)
    ax.set_title('MOVEMENT, BOTH HANDS', fontsize=8.5, fontweight='bold', color=TEXT_SECONDARY, loc='left')
    cents = {}
    for t in TYPES:
        xs = [sf(p.get('HorzBrk')) for p in ps if p.get('Pitch Type') == t]
        ys = [sf(p.get('IndVertBrk')) for p in ps if p.get('Pitch Type') == t]
        pts = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
        if not pts:
            continue
        x, y = zip(*pts)
        ax.scatter(x, y, s=9, c=COLORS[t], alpha=0.35, edgecolors='none', zorder=3)
        cx, cy = np.mean(x), np.mean(y)
        cents[t] = (cx, cy)
    # centroid badges; when the two centroids sit within 3 in of each other
    # (Gausman: one look, two grips) push the labels apart vertically so both read
    close = len(cents) == 2 and np.hypot(*(np.subtract(cents['CH'], cents['FS']))) < 3.0
    for i, (t, (cx, cy)) in enumerate(cents.items()):
        ax.scatter([cx], [cy], s=60 if close else 170, c=COLORS[t], edgecolors=BG, linewidths=1.2, zorder=5)
        if close:
            ty = cy + (4.5 if t == 'CH' else -4.5)
            ax.annotate(t, (cx, cy), (cx + 6, ty), fontsize=7, fontweight='bold', color=COLORS[t], zorder=6,
                        arrowprops=dict(arrowstyle='-', color=COLORS[t], lw=0.8), va='center')
        else:
            ax.text(cx, cy, t, ha='center', va='center', fontsize=6.5, fontweight='bold', color='white', zorder=6)


def location_plot(ax, ps, hand_label, hand):
    style_panel(ax)
    hp = [p for p in ps if p.get('Bats') == hand]
    tops = [sf(p.get('SzTop')) for p in hp]; bots = [sf(p.get('SzBot')) for p in hp]
    zt = mean(tops) or 3.4; zb = mean(bots) or 1.6
    ax.set_xlim(-1.583, 1.583); ax.set_ylim(0.833, 3.917)
    ax.add_patch(Rectangle((-PLATE_HALF, zb), PLATE_HALF * 2, zt - zb, fill=False,
                           edgecolor=TEXT_SECONDARY, lw=1.4, zorder=4))
    tw = PLATE_HALF * 2 / 3; th = (zt - zb) / 3
    for i in (1, 2):
        ax.plot([-PLATE_HALF + i * tw] * 2, [zb, zt], color=GRID_COLOR, lw=0.6, zorder=4)
        ax.plot([-PLATE_HALF, PLATE_HALF], [zb + i * th] * 2, color=GRID_COLOR, lw=0.6, zorder=4)
    py = zb - 0.15
    ax.plot([-PLATE_HALF, -PLATE_HALF, 0, PLATE_HALF, PLATE_HALF, -PLATE_HALF],
            [py, py - 0.10, py - 0.20, py - 0.10, py, py], color=TEXT_SECONDARY, lw=1.1, zorder=4)
    ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
    n_by = {}
    for t in TYPES:
        pts = [(sf(p.get('PlateX')), sf(p.get('PlateZ'))) for p in hp if p.get('Pitch Type') == t]
        pts = [(x, y) for x, y in pts if x is not None and y is not None]
        n_by[t] = len(pts)
        if not pts:
            continue
        x, y = np.array(pts).T
        ax.scatter(x, y, s=12, c=COLORS[t], alpha=0.55, edgecolors='none', zorder=3)
        if len(pts) >= 4:
            cov = np.cov(x, y)
            vals, vecs = np.linalg.eigh(cov)
            ang = np.degrees(np.arctan2(vecs[1, 1], vecs[0, 1]))
            w, h = 2 * np.sqrt(max(vals[1], 0)), 2 * np.sqrt(max(vals[0], 0))
            ax.add_patch(Ellipse((x.mean(), y.mean()), w, h, angle=ang, fill=False,
                                 edgecolor=COLORS[t], lw=1.6, zorder=5))
    ax.set_title(f'{hand_label.upper()}   CH {n_by["CH"]}  ·  FS {n_by["FS"]}', fontsize=8.5,
                 fontweight='bold', color=TEXT_SECONDARY, loc='left')
    ax.text(0.02, 0.02, 'catcher view, 1 SD ellipse', transform=ax.transAxes, fontsize=6,
            color=TEXT_MUTED, va='bottom')


def render_pitcher(pdf, name, ps, outings_both, team=None):
    if team is None:
        teams = pd.Series([p.get('PTeam') for p in ps]).value_counts()
        team = teams.index[0] if len(teams) == 1 else f'{len(teams)}TM'   # site label for a traded arm
    throws = ps[0].get('Throws') or '?'
    off = [p for p in ps if p.get('Pitch Type') in TYPES]

    # page 1: plots + totals + by hand
    fig = plt.figure(figsize=(11, 8.5))
    header(fig, name, team, throws, ps, outings_both, 1)
    ax_m = fig.add_axes([0.06, 0.455, 0.30, 0.42])
    movement_plot(ax_m, off)
    ax_r = fig.add_axes([0.40, 0.455, 0.27, 0.42])
    location_plot(ax_r, off, 'vs RHH', 'R')
    ax_l = fig.add_axes([0.695, 0.455, 0.27, 0.42])
    location_plot(ax_l, off, 'vs LHH', 'L')
    y = draw_table(fig, 0.375, 'TOTALS', rows_for(ps, '', throws=throws))
    for lab, hand in HANDS:
        rows = rows_for([p for p in ps if p.get('Bats') == hand], '', throws=throws, bats=hand)
        y = draw_table(fig, y, lab.upper(), rows, keys=HAND_KEYS)
    pdf.savefig(fig, facecolor=BG); plt.close(fig)

    # page 2: usage-by-count grids, the site's table (js/player-page.js), three times
    fig = plt.figure(figsize=(11, 8.5))
    header(fig, name, team, throws, ps, outings_both, 2)
    y = 0.885
    for lab, hand in [('TOTAL', None)] + [(l.upper(), h) for l, h in HANDS]:
        cell = ps if hand is None else [p for p in ps if p.get('Bats') == hand]
        y = usage_grid(fig, y, f'USAGE BY COUNT  ·  {lab}', cell)
    pdf.savefig(fig, facecolor=BG); plt.close(fig)


ALL_COLORS = {'FF': '#0072B2', 'SI': '#E69F00', 'FC': '#D55E00', 'SL': '#D55E00', 'ST': '#56B4E9',
              'CU': '#332288', 'SV': '#882255', 'CH': '#009E73', 'FS': '#CC79A7', 'KN': '#9A9A9A',
              'EP': '#9A9A9A'}
HI = '#b8574a'   # terracotta: used MORE than overall
LO = '#6f8194'   # slate: used LESS than overall
GRID_COLOR_MIN = 25   # site row gate


def _blend(a, b, t):
    a = np.array(matplotlib.colors.to_rgb(a)); b = np.array(matplotlib.colors.to_rgb(b))
    return matplotlib.colors.to_hex(a + (b - a) * t)


def usage_grid(fig, top, title, cell, left=0.035, right=0.965, row_h=0.03):
    """Pitch x count-bucket usage grid. Usage% = the pitch's share of all
    pitches in the cell; bucket cells = share of that bucket's pitches. Tint
    is the site's ratio rule (cell / overall, 1x neutral, 2x and 0x full)."""
    fig.text(left, top, title, fontsize=9.5, fontweight='bold', color=TEXT_SECONDARY, va='bottom')
    top -= 0.008
    counts = pd.Series([p.get('Pitch Type') for p in cell]).value_counts()
    types = sorted(TYPES, key=lambda t: -counts.get(t, 0))  # both rows always, higher usage first
    tot = len(cell)
    bucket_n = {lab: sum(p.get('Count') in cs for p in cell) for lab, cs in COUNT_BUCKETS}
    widths = [1.3, 1.0] + [1.45] * len(COUNT_BUCKETS)
    tw = sum(widths); xs = [left]
    for w in widths:
        xs.append(xs[-1] + (right - left) * w / tw)
    heads = ['Pitch', 'Usage%'] + [f'{lab} (n={bucket_n[lab]})' for lab, _ in COUNT_BUCKETS]
    fig.patches.append(Rectangle((left, top - row_h), right - left, row_h, transform=fig.transFigure,
                                 facecolor=DARKER, edgecolor='none'))
    for i, h in enumerate(heads):
        fig.text((xs[i] + xs[i + 1]) / 2, top - row_h / 2, h, ha='center', va='center',
                 fontsize=7.6, fontweight='bold', color=TEXT_SECONDARY)
    y = top - row_h
    for t in types:
        tp = [p for p in cell if p.get('Pitch Type') == t]
        n = len(tp); base = 100.0 * n / tot if tot else 0.0
        fig.patches.append(Rectangle((left, y - row_h), right - left, row_h, transform=fig.transFigure,
                                     facecolor=BG, edgecolor='none'))
        fig.lines.append(plt.Line2D([left, right], [y - row_h, y - row_h], transform=fig.transFigure,
                                    color=SUBTLE_BORDER, lw=0.4))
        col = ALL_COLORS.get(t, '#9A9A9A')
        fig.text(xs[0] + 0.012, y - row_h / 2, t, ha='center', va='center', fontsize=7.2, fontweight='bold',
                 color='white', bbox=dict(boxstyle='round,pad=0.25', facecolor=col, edgecolor='none'))
        fig.text(xs[0] + 0.027, y - row_h / 2, f'· {n}', ha='left', va='center', fontsize=7.6, color=TEXT_MUTED)
        fig.text((xs[1] + xs[2]) / 2, y - row_h / 2, f'{base:.1f}%', ha='center', va='center',
                 fontsize=8, fontweight='bold', color=TEXT_PRIMARY)
        for j, (lab, cs) in enumerate(COUNT_BUCKETS):
            bn = bucket_n[lab]
            k = sum(p.get('Count') in cs for p in tp)
            pct_ = 100.0 * k / bn if bn else None
            x0, x1 = xs[2 + j], xs[3 + j]
            if pct_ is not None and n >= GRID_COLOR_MIN and base > 0:
                ratio = pct_ / base
                if ratio >= 1:
                    face = _blend(BG, HI, min(1.0, (ratio - 1)) * 0.9)
                else:
                    face = _blend(BG, LO, min(1.0, (1 - ratio)) * 0.9)
                fig.patches.append(Rectangle((x0, y - row_h), x1 - x0, row_h, transform=fig.transFigure,
                                             facecolor=face, edgecolor=BG, lw=0.6))
            fig.text((x0 + x1) / 2, y - row_h / 2, '-' if pct_ is None else f'{pct_:.1f}%',
                     ha='center', va='center', fontsize=8, color=TEXT_PRIMARY)
        y -= row_h
    return y - 0.035


def team_split_deck(name, out):
    """One pitcher, combined then one pass per club in first-appearance order."""
    df = pd.DataFrame(pickle.load(open(CACHE, 'rb')))
    mlb = df[df['_source'] == 'MLB']
    _recs = mlb.to_dict('records')
    build_xrv_anchors(_recs)
    build_pools(_recs)
    ps = mlb[mlb['Pitcher'] == name].sort_values('Game Date').to_dict('records')
    off = [p for p in ps if p.get('Pitch Type') in TYPES]

    def both(rows):
        g = pd.DataFrame(rows).groupby('Game Date')['Pitch Type'].agg(set)
        return int(g.apply(lambda s_: {'CH', 'FS'} <= s_).sum())
    teams = list(dict.fromkeys(p.get('PTeam') for p in ps))
    with PdfPages(out) as pdf:
        render_pitcher(pdf, name, ps, both(off))
        print(f'  {name} combined: {len(ps)} pitches, {both(off)} outings with both')
        for t in teams:
            tp = [p for p in ps if p.get('PTeam') == t]
            to = [p for p in tp if p.get('Pitch Type') in TYPES]
            render_pitcher(pdf, name, tp, both(to), team=t)
            print(f'  {name} {t}: {len(tp)} pitches, {both(to)} outings with both')
    print(f'wrote {out}')


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--team-split':
        name = sys.argv[2]
        out = os.path.join(os.path.expanduser('~'), 'Downloads',
                           f"ch_fs_{name.split(',')[0].lower()}_by_team_2026.pdf")
        team_split_deck(name, out)
        return
    pitchers = PITCHERS
    if len(sys.argv) > 2 and sys.argv[1] == '--only':     # subset, deck order kept
        pitchers = [n for n in PITCHERS if n in sys.argv[2:]]
    df = pd.DataFrame(pickle.load(open(CACHE, 'rb')))
    mlb = df[df['_source'] == 'MLB']
    _recs = mlb.to_dict('records')
    build_xrv_anchors(_recs)
    build_pools(_recs)
    df = mlb[mlb['Pitcher'].isin(PITCHERS)]
    off = df[df['Pitch Type'].isin(TYPES)]
    g = off.groupby(['Pitcher', 'Game Date'])['Pitch Type'].agg(set)
    both = g[g.apply(lambda s: {'CH', 'FS'} <= s)].reset_index().groupby('Pitcher').size().to_dict()
    with PdfPages(OUT) as pdf:
        for name in pitchers:
            ps = df[df['Pitcher'] == name].to_dict('records')
            if not ps:
                print(f'  WARNING: no pitches for {name}')
                continue
            render_pitcher(pdf, name, ps, both.get(name, 0))
            print(f'  {name}: {len(ps)} pitches, {both.get(name, 0)} outings with both')
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
