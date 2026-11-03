#!/usr/bin/env python3
"""Spray chart from a hand-entered research.mlb.com batted-ball CSV.

Each ball in play is placed at its LANDING spot from two scalar fields on
the research.mlb.com per-pitch page:

    Hit Landing Bearing   degrees, 0 = over second base, positive = right field
    Hit Distance          feet, the projected landing point (first bounce on
                          a ground ball, so grounders cluster near the plate)

Points are coloured by `Hit Type` on the hitter card's batted-ball palette
and drawn at one size. Rows with no bearing or no distance (swings without
contact, summary rows) are skipped and counted.

The fence drawn is a 330 / 400 / 330 ft reference arc, not any park.

Usage (from the repo root):
    python3 scripts/tools/spray_chart_csv.py "~/Downloads/file.csv" \
        --title "Chris Hacopian" --bats R --out ~/Downloads/hacopian_spray.png
"""
import argparse
import csv
import math
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon

# Warm-paper theme and batted-ball palette. The HOME of these values is
# cards/hitter.py (BB_COLORS, BG, TEXT_*). They are copied here because
# cards.hitter imports cards.pitcher at module load, which pulls the card
# settings block and its network paths into a one-off render. Change them
# there first, then here.
BG           = '#f0e8d8'
FIELD        = '#e9dfcb'
INFIELD      = '#e2d8c4'
TEXT_PRIMARY = '#1a1612'
TEXT_SECOND  = '#3a3530'
TEXT_MUTED   = '#6a5f55'
TEXT_FAINT   = '#8a7f75'
LINE         = '#c5b89f'

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
    'popup':       'Pop Up',
}
BB_TYPES = ['ground_ball', 'line_drive', 'fly_ball', 'popup']

HIT_TYPE_KEY = {
    'ground ball': 'ground_ball', 'groundball': 'ground_ball',
    'line drive':  'line_drive',  'linedrive':  'line_drive',
    'fly ball':    'fly_ball',    'flyball':    'fly_ball',
    'pop up':      'popup',       'popup':      'popup',
}

TITLE_FONT = 'Bitter'
BODY_FONT = 'IBM Plex Sans'

FENCE_LINE_FT = 330.0
FENCE_CF_FT = 400.0
BASE_PATH_FT = 90.0
MOUND_FT = 60.5
INFIELD_ARC_FT = 95.0
MARKER_PT2 = 70            # scatter `s`, one size for every point
MARKER_EDGE_W = 0.7


def _num(s):
    """Float from a CSV cell; None on blank or non-numeric."""
    s = (s or '').strip()
    if s == '':
        return None
    try:
        return float(s)
    except ValueError:
        return None


def read_rows(path):
    """Return (plotted, skipped) where plotted is a list of dicts with
    x, y, key, ev, la, dist and skipped counts rows without a landing spot."""
    plotted, skipped = [], 0
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            bearing = _num(row.get('Hit Landing Bearing'))
            dist = _num(row.get('Hit Distance'))
            key = HIT_TYPE_KEY.get((row.get('Hit Type') or '').strip().lower())
            if bearing is None or dist is None or key is None:
                skipped += 1
                continue
            rad = math.radians(bearing)
            plotted.append({
                'x': dist * math.sin(rad),
                'y': dist * math.cos(rad),
                'key': key,
                'ev': _num(row.get('Exit Velocity')),
                'la': _num(row.get('Launch Angle')),
                'dist': dist,
                'event': (row.get('Event') or '').strip(),
            })
    return plotted, skipped


def fence_xy(n=181):
    """Reference fence: 330 ft down each line, 400 ft to centre, smooth."""
    xs, ys = [], []
    for i in range(n):
        th = math.radians(-45 + 90 * i / (n - 1))
        r = FENCE_LINE_FT + (FENCE_CF_FT - FENCE_LINE_FT) * math.cos(2 * th)
        xs.append(r * math.sin(th))
        ys.append(r * math.cos(th))
    return xs, ys


def draw_field(ax):
    fx, fy = fence_xy()
    # Fair territory, plate to fence.
    ax.add_patch(Polygon([(0, 0)] + list(zip(fx, fy)), closed=True,
                         facecolor=FIELD, edgecolor='none', zorder=0))
    ax.plot(fx, fy, color=LINE, lw=1.2, zorder=1)
    # Foul lines, a little past the fence.
    for sgn in (-1, 1):
        ax.plot([0, sgn * 310], [0, 310], color=LINE, lw=1.2, zorder=1)
    # Infield dirt arc, centred on the mound.
    arc_x, arc_y = [], []
    for i in range(121):
        th = math.radians(-70 + 140 * i / 120)
        arc_x.append(INFIELD_ARC_FT * math.sin(th))
        arc_y.append(MOUND_FT + INFIELD_ARC_FT * math.cos(th))
    ax.plot(arc_x, arc_y, color=LINE, lw=0.9, zorder=1)
    # Base paths.
    h = BASE_PATH_FT / math.sqrt(2)
    diamond = [(0, 0), (h, h), (0, 2 * h), (-h, h)]
    ax.add_patch(Polygon(diamond, closed=True, facecolor=INFIELD,
                         edgecolor=LINE, lw=0.9, zorder=1))
    for bx, by in diamond[1:]:
        ax.add_patch(Polygon([(bx - 4, by - 4), (bx + 4, by - 4),
                              (bx + 4, by + 4), (bx - 4, by + 4)],
                             closed=True, facecolor=BG, edgecolor=TEXT_FAINT,
                             lw=0.6, zorder=2))
    ax.add_patch(plt.Circle((0, MOUND_FT), 9, facecolor=INFIELD,
                            edgecolor=LINE, lw=0.6, zorder=2))
    # Distance rings, faint, labelled down the left line.
    for r in (100, 200, 300):
        rx, ry = [], []
        for i in range(91):
            th = math.radians(-45 + 90 * i / 90)
            rx.append(r * math.sin(th))
            ry.append(r * math.cos(th))
        ax.plot(rx, ry, color=LINE, lw=0.6, ls=(0, (2, 3)), zorder=1)
        lx, ly = r * math.sin(math.radians(-45)), r * math.cos(math.radians(-45))
        ax.text(lx - 6, ly + 6, f'{r} ft', fontsize=7.5, color=TEXT_FAINT,
                fontfamily=BODY_FONT, ha='right', va='bottom', zorder=3)


def draw_points(ax, rows):
    for key in BB_TYPES:               # fixed draw order = fixed legend order
        pts = [r for r in rows if r['key'] == key]
        if not pts:
            continue
        ax.scatter([p['x'] for p in pts], [p['y'] for p in pts],
                   s=MARKER_PT2, color=BB_COLORS[key], edgecolor=TEXT_SECOND,
                   linewidths=MARKER_EDGE_W, alpha=0.95, zorder=4)


def legend_handles(rows):
    handles = []
    for key in BB_TYPES:
        n = sum(1 for r in rows if r['key'] == key)
        handles.append(Line2D([0], [0], marker='o', color='none',
                              markerfacecolor=BB_COLORS[key],
                              markeredgecolor=TEXT_SECOND,
                              markeredgewidth=MARKER_EDGE_W, markersize=8.5,
                              label=f'{BB_LABELS[key]}  ({n})'))
    return handles


def mix_table(ax, rows):
    """Small text table under the plot: type, n, share, avg EV, avg distance."""
    total = len(rows)
    ax.axis('off')
    cols = ['', 'n', 'share', 'avg EV', 'avg dist']
    xs = [0.02, 0.36, 0.50, 0.66, 0.84]
    y = 0.92
    for x, c in zip(xs, cols):
        ax.text(x, y, c, transform=ax.transAxes, fontsize=8.5,
                color=TEXT_FAINT, fontfamily=BODY_FONT,
                ha='left' if x == xs[0] else 'right', va='top')
    for key in BB_TYPES:
        pts = [r for r in rows if r['key'] == key]
        y -= 0.19
        n = len(pts)
        evs = [p['ev'] for p in pts if p['ev'] is not None]
        ds = [p['dist'] for p in pts]
        vals = [
            BB_LABELS[key],
            f'{n}',
            f'{100 * n / total:.1f}%' if total else '',
            f'{sum(evs) / len(evs):.1f}' if evs else '',
            f'{sum(ds) / len(ds):.0f} ft' if ds else '',
        ]
        for x, v in zip(xs, vals):
            ax.text(x, y, v, transform=ax.transAxes, fontsize=9,
                    color=TEXT_PRIMARY, fontfamily=BODY_FONT,
                    ha='left' if x == xs[0] else 'right', va='top')


def render(rows, skipped, title, bats, out_path):
    # Axes boxes are placed by hand so the equal-aspect field fills its box
    # (x span 660 ft, y span 440 ft) instead of floating inside a gridspec.
    fig = plt.figure(figsize=(8.6, 8.5), facecolor=BG)
    ax = fig.add_axes([0.05, 0.255, 0.90, 0.635])
    ax.set_facecolor(BG)
    draw_field(ax)
    draw_points(ax, rows)

    # Pull / oppo cue from the batting side.
    if bats in ('R', 'L'):
        pull_x = -1 if bats == 'R' else 1
        for sgn, word in ((pull_x, 'PULL'), (-pull_x, 'OPPO')):
            th = math.radians(sgn * 38)
            ax.text(345 * math.sin(th), 345 * math.cos(th), word, fontsize=9,
                    color=TEXT_FAINT, fontfamily=BODY_FONT, fontweight='600',
                    ha='center', va='center', zorder=3)

    ax.set_xlim(-330, 330)
    ax.set_ylim(-15, 425)
    ax.set_aspect('equal', adjustable='datalim')
    ax.axis('off')
    ax.legend(handles=legend_handles(rows), loc='lower right',
              bbox_to_anchor=(1.0, 0.0), frameon=False, fontsize=9,
              labelcolor=TEXT_SECOND, handletextpad=0.4,
              prop={'family': BODY_FONT, 'size': 9})

    n = len(rows)
    fig.text(0.05, 0.968, title, fontsize=22, fontfamily=TITLE_FONT,
             fontweight='700', color=TEXT_PRIMARY, ha='left', va='top')
    sub = f'{n} balls in play, landing spot from Hit Landing Bearing and Hit Distance'
    if bats in ('R', 'L'):
        sub = f'Bats {bats}.  ' + sub
    fig.text(0.05, 0.922, sub, fontsize=10.5, fontfamily=BODY_FONT,
             color=TEXT_MUTED, ha='left', va='top')

    tax = fig.add_axes([0.05, 0.065, 0.90, 0.175])
    tax.set_facecolor(BG)
    mix_table(tax, rows)

    foot = ('Fence is a 330 / 400 / 330 ft reference, not a park.  '
            'A ground ball\'s distance is its first bounce.\n'
            'Source: research.mlb.com, hand entered.')
    if skipped:
        foot += f'  {skipped} rows without a landing spot were skipped.'
    fig.text(0.05, 0.014, foot, fontsize=7.5, fontfamily=BODY_FONT,
             color=TEXT_FAINT, ha='left', va='bottom', linespacing=1.5)

    fig.savefig(out_path, dpi=200, facecolor=BG)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('csv', help='research.mlb.com batted-ball CSV')
    ap.add_argument('--title', default='Batted balls')
    ap.add_argument('--bats', choices=['R', 'L'], default=None,
                    help='batting side, adds PULL / OPPO cues')
    ap.add_argument('--out', default=None,
                    help='output PNG (default: next to the CSV)')
    args = ap.parse_args()

    csv_path = os.path.expanduser(args.csv)
    if not os.path.isfile(csv_path):
        sys.exit(f'CSV not found: {csv_path}')
    out = os.path.expanduser(args.out) if args.out else \
        os.path.splitext(csv_path)[0] + '_spray.png'

    rows, skipped = read_rows(csv_path)
    if not rows:
        sys.exit('No rows with Hit Landing Bearing, Hit Distance and Hit Type.')
    render(rows, skipped, args.title, args.bats, out)
    by_type = {k: sum(1 for r in rows if r['key'] == k) for k in BB_TYPES}
    print(f'{len(rows)} balls in play plotted, {skipped} rows skipped '
          f'({by_type}) -> {out}')


if __name__ == '__main__':
    main()
