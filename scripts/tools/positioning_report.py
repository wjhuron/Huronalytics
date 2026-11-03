#!/usr/bin/env python3
"""How defenses actually positioned against one batter: where, who, when, why.

Inputs:
    data/_positioning_{id}.json   fielder start spots per plate appearance, by
                                  defensive team (scripts/builders/
                                  batter_positioning_pull.py). 10 ft rounding,
                                  runners group, infield-shaded flag; no game
                                  or count key, so these rows support only
                                  the season / team / runners / shade splits.
    Savant search CSV             the per-pitch alignment LABELS
                                  (if_fielding_alignment: Standard, Infield
                                  shade, Strategic) with the count, outs,
                                  runners, pitcher hand, inning and score of
                                  the same pitch, and the batted balls.

Pages:
    1  Where: 2026 start spots (bubble = plate appearances at that 10 ft
       cell) and the mean spot of each fielder, with arrows for the move
       teams make when they shade and when a runner is on first only.
    2  Who: each defensive team's shade rate and mean 3B / SS angle.
    3  When and why: label shares by situation, the counts at which the
       label changes inside a plate appearance, and the batter's own spray
       in the same situations. 'Why' is inferred from what moves together;
       teams do not publish reasons.

Usage (from the repo root):
    python3 scripts/tools/positioning_report.py --id 695578 \
        --csv ~/Downloads/savant_data.csv --title "James Wood" \
        --out ~/Downloads/james_wood_positioning.pdf
"""
import argparse
import json
import math
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.lines import Line2D

from spray_chart_csv import (BG, TEXT_PRIMARY, TEXT_SECOND, TEXT_MUTED, TEXT_FAINT,
                             LINE, TITLE_FONT, BODY_FONT, draw_field)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POS = {3: '1B', 4: '2B', 5: '3B', 6: 'SS', 7: 'LF', 8: 'CF', 9: 'RF'}
ORDER = ['3B', 'SS', '2B', '1B', 'LF', 'CF', 'RF']
HP_X, HP_Y = 125.42, 198.27      # home plate in HC space (cards/hitter.py)

# Okabe-Ito, one colour per alignment label / situation.
C_STD, C_SHADE, C_STRAT = '#0072B2', '#D55E00', '#009E73'
LABEL_COLORS = {'Standard': C_STD, 'Infield shade': C_SHADE, 'Strategic': C_STRAT}
C_RUN1 = '#CC79A7'
C_OTHER = '#E69F00'


def load_positions(pid):
    with open(os.path.join(REPO, 'data', f'_positioning_{pid}.json')) as f:
        d = pd.DataFrame(json.load(f))
    d['x'] = d.start_pos_x.astype(float)
    d['y'] = d.start_pos_y.astype(float)
    d['pos'] = d.pos_id.astype(int).map(POS)
    d['shaded'] = d.is_shift_infield == '1'
    d['runners'] = d.group_runners_on_cd.map({'0': 'none', '1': '1B only', '27': 'other'})
    return d


def load_csv(path):
    sv = pd.read_csv(os.path.expanduser(path), low_memory=False)
    sv['runners'] = np.select(
        [sv.on_1b.isna() & sv.on_2b.isna() & sv.on_3b.isna(),
         sv.on_1b.notna() & sv.on_2b.isna() & sv.on_3b.isna()], ['none', '1B only'], 'other')
    sv['margin'] = pd.cut(sv.fld_score - sv.bat_score, [-99, -4, -1, 0, 3, 99],
                          labels=['Down 4+', 'Down 1-3', 'Tied', 'Up 1-3', 'Up 4+'])
    sv['inn'] = pd.cut(sv.inning, [0, 3, 6, 30], labels=['1-3', '4-6', '7+'])
    sv['ang'] = np.degrees(np.arctan2(sv.hc_x - HP_X, HP_Y - sv.hc_y))
    return sv


def mean_spot(d):
    return d.groupby('pos')[['x', 'y']].mean()


def header(fig, title, sub):
    fig.text(0.03, 0.965, title, fontsize=22, fontfamily=TITLE_FONT, fontweight='700',
             color=TEXT_PRIMARY, va='top')
    fig.text(0.03, 0.915, sub, fontsize=10.5, fontfamily=BODY_FONT, color=TEXT_MUTED, va='top')


def field_ax(fig, box, title, zoom=False):
    ax = fig.add_axes(box)
    ax.set_facecolor(BG)
    draw_field(ax)
    # The shade and runner moves are infield moves of a few feet; on a full
    # field the arrows hide under the fielder labels, so those panels zoom.
    ax.set_xlim(*((-150, 150) if zoom else (-340, 340)))
    ax.set_ylim(*((-10, 190) if zoom else (-10, 430)))
    for t in ax.texts:                 # distance-ring labels outside a zoom
        t.set_clip_on(True)
    ax.set_aspect('equal', adjustable='box')
    ax.axis('off')
    ax.set_title(title, fontsize=13, fontfamily=TITLE_FONT, fontweight='700',
                 color=TEXT_PRIMARY, pad=4)
    return ax


def arrows(ax, a, b, color, only=ORDER):
    for p in only:
        (x0, y0), (x1, y1) = a.loc[p], b.loc[p]
        if math.hypot(x1 - x0, y1 - y0) >= 3:
            ax.annotate('', (x1, y1), (x0, y0), zorder=6,
                        arrowprops=dict(arrowstyle='-|>', color=color, lw=2.2,
                                        mutation_scale=16, shrinkA=0, shrinkB=0))
        ax.scatter([x1], [y1], s=60, color=color, edgecolor=BG, lw=0.8, zorder=7)


def base_spots(ax, m, small=False, only=ORDER):
    for p in only:
        x, y = m.loc[p]
        if small:
            # Hollow ring at the starting spot, label set off below it, so
            # the arrow that leaves the ring stays visible.
            ax.scatter([x], [y], s=110, facecolor='none', edgecolor=TEXT_PRIMARY,
                       lw=1.6, zorder=5)
            ax.text(x, y - 9, p, fontsize=9, fontfamily=BODY_FONT, fontweight='700',
                    color=TEXT_PRIMARY, ha='center', va='top', zorder=6)
            continue
        ax.scatter([x], [y], s=300, color=TEXT_PRIMARY, edgecolor=BG, lw=1.4, zorder=5)
        ax.text(x, y, p, fontsize=7.5, fontfamily=BODY_FONT, fontweight='700',
                color=BG, ha='center', va='center', zorder=6)


def move_table(ax, a, moves):
    """Columns of rows: how far each fielder moves from a, in deg and ft.
    moves = [(b, colour, heading), ...]."""
    ax.axis('off')
    w = 1.0 / len(moves)
    for c, (b, color, head) in enumerate(moves):
        xc = w * (c + 0.5)
        ax.text(xc, 1.0, head, transform=ax.transAxes, ha='center', va='top',
                fontsize=9.5, fontfamily=BODY_FONT, fontweight='700', color=color)
        for i, p in enumerate(ORDER):
            (x0, y0), (x1, y1) = a.loc[p], b.loc[p]
            dang = math.degrees(math.atan2(x1, y1)) - math.degrees(math.atan2(x0, y0))
            ddep = math.hypot(x1, y1) - math.hypot(x0, y0)
            big = abs(ddep) >= 5 or abs(dang) >= 2
            txt = (f'{p}: {abs(dang):.1f} deg {"to RF" if dang > 0 else "to LF"}, '
                   f'{abs(ddep):.0f} ft {"deeper" if ddep >= 0 else "in"}')
            ax.text(xc, 0.84 - 0.12 * i, txt, transform=ax.transAxes, ha='center', va='top',
                    fontsize=8.8, fontfamily=BODY_FONT,
                    color=TEXT_PRIMARY if big else TEXT_FAINT,
                    fontweight='600' if big else 'normal')


def page_where(pdf, d, title, season):
    s = d[d.season == season]
    n_pa = len(s) // 7
    fig = plt.figure(figsize=(20, 10), facecolor=BG)
    header(fig, f'{title}  |  Where defenses played him, {season}',
           f'{n_pa} plate appearances.  Savant start positions, rounded to 10 ft.  '
           f'Shaded on {100 * s[s.pos == "SS"].shaded.mean():.0f}% of them.  '
           'Middle and right panels zoom on the infield; outfield moves are in the tables.')
    base = mean_spot(s)
    IF = ['3B', 'SS', '2B', '1B']

    ax = field_ax(fig, [0.01, 0.30, 0.32, 0.56], 'Every start spot')
    cells = s.groupby(['pos', 'x', 'y']).size().reset_index(name='n')
    ax.scatter(cells.x, cells.y, s=cells.n * 4, color=TEXT_MUTED, alpha=0.35,
               edgecolor='none', zorder=4)
    base_spots(ax, base)
    fig.text(0.17, 0.27, 'Bubble size = plate appearances at that 10 ft cell; '
             'labels = mean spot.', ha='center', fontsize=8.5, fontfamily=BODY_FONT,
             color=TEXT_MUTED)

    ax = field_ax(fig, [0.34, 0.30, 0.32, 0.56], 'Not shaded to shaded', zoom=True)
    a, b = mean_spot(s[~s.shaded]), mean_spot(s[s.shaded])
    base_spots(ax, a, small=True, only=IF)
    arrows(ax, a, b, C_SHADE, only=IF)
    move_table(fig.add_axes([0.34, 0.03, 0.32, 0.23]), a,
               [(b, C_SHADE, 'Not shaded to shaded')])

    ax = field_ax(fig, [0.67, 0.30, 0.32, 0.56], 'Bases empty to runners on', zoom=True)
    e = mean_spot(s[s.runners == 'none'])
    r1, ro = mean_spot(s[s.runners == '1B only']), mean_spot(s[s.runners == 'other'])
    base_spots(ax, e, small=True, only=IF)
    arrows(ax, e, r1, C_RUN1, only=IF)
    arrows(ax, e, ro, C_OTHER, only=IF)
    ax.legend(handles=[Line2D([0], [0], color=C_RUN1, lw=2.2, label='Runner on 1B only'),
                       Line2D([0], [0], color=C_OTHER, lw=2.2, label='Other runners')],
              loc='upper left', frameon=False, prop={'family': BODY_FONT, 'size': 9.5})
    move_table(fig.add_axes([0.67, 0.03, 0.32, 0.23]), e,
               [(r1, C_RUN1, 'Runner on 1B only'), (ro, C_OTHER, 'Other runners')])
    pdf.savefig(fig, facecolor=BG)
    return fig


def page_who(pdf, d, title, season):
    s = d[(d.season == season) & d.pos.isin(['3B', 'SS'])].copy()
    s['ang'] = np.degrees(np.arctan2(s.x, s.y))
    g = s.groupby('opp').agg(pa=('x', 'size'), shade=('shaded', 'mean'))
    g['pa'] //= 2
    ang = s.pivot_table(index='opp', columns='pos', values='ang', aggfunc='mean')
    g = g.join(ang).sort_values('shade')
    fig = plt.figure(figsize=(20, 10.5), facecolor=BG)
    header(fig, f'{title}  |  Who shades him, {season}',
           'Each defensive team: share of plate appearances shaded, and the mean 3B and SS '
           'angle (0 = over 2B, negative = left side).  Small samples: read the PA column.')
    y = np.arange(len(g))
    ax1 = fig.add_axes([0.08, 0.07, 0.40, 0.80])
    ax1.barh(y, 100 * g.shade, color=C_SHADE, height=0.7)
    for i, (sh, pa) in enumerate(zip(g.shade, g.pa)):
        ax1.text(100 * sh + 1, i, f'{100 * sh:.0f}%  ({pa} PA)', va='center',
                 fontsize=8.5, fontfamily=BODY_FONT, color=TEXT_SECOND)
    ax1.set_yticks(y, g.index, fontfamily=BODY_FONT, fontsize=9.5, color=TEXT_PRIMARY)
    ax1.set_xlim(0, 115)
    ax1.set_xlabel('Plate appearances shaded (%)', fontfamily=BODY_FONT, color=TEXT_MUTED)
    ax2 = fig.add_axes([0.56, 0.07, 0.40, 0.80], sharey=ax1)
    ax2.scatter(g['3B'], y, color=C_STD, s=40, label='3B', zorder=3)
    ax2.scatter(g['SS'], y, color=C_STRAT, s=40, label='SS', zorder=3)
    ax2.hlines(y, g['3B'], g['SS'], color=LINE, lw=1, zorder=2)
    ax2.set_xlabel('Mean angle (deg)', fontfamily=BODY_FONT, color=TEXT_MUTED)
    ax2.legend(frameon=False, prop={'family': BODY_FONT, 'size': 9}, loc='lower right')
    plt.setp(ax2.get_yticklabels(), visible=False)
    for ax in (ax1, ax2):
        ax.set_facecolor(BG)
        for sp in ('top', 'right'):
            ax.spines[sp].set_visible(False)
        ax.tick_params(colors=TEXT_MUTED)
        ax.grid(axis='x', color=LINE, lw=0.5)
        ax.set_axisbelow(True)
    pdf.savefig(fig, facecolor=BG)
    return fig


def stacked(ax, df, col, order, title, n_min=30):
    t = pd.crosstab(df[col], df.if_fielding_alignment, normalize='index').reindex(order)
    n = df[col].value_counts().reindex(order)
    left = np.zeros(len(order))
    for lab in ('Standard', 'Infield shade', 'Strategic'):
        v = 100 * t.get(lab, pd.Series(0, index=order)).fillna(0).to_numpy()
        ax.barh(range(len(order)), v, left=left, color=LABEL_COLORS[lab], height=0.7)
        for i, (l0, w) in enumerate(zip(left, v)):
            if w >= 9:
                ax.text(l0 + w / 2, i, f'{w:.0f}', ha='center', va='center', fontsize=8,
                        fontfamily=BODY_FONT, color='white', fontweight='600')
        left += v
    ax.set_yticks(range(len(order)), [f'{o}  ({int(k)})' if k >= n_min else f'{o}  ({int(k)}, thin)'
                                      for o, k in zip(order, n.fillna(0))],
                  fontfamily=BODY_FONT, fontsize=8.5, color=TEXT_PRIMARY)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xticks([])
    ax.set_title(title, fontsize=10.5, fontfamily=TITLE_FONT, fontweight='700',
                 color=TEXT_PRIMARY, loc='left')
    ax.set_facecolor(BG)
    for sp in ax.spines.values():
        sp.set_visible(False)


def spray_note(df, col, order):
    """Batter's own spray in each group: grounder pull % and air-ball oppo %."""
    b = df[df.bb_type.notna() & df.hc_x.notna()]
    out = []
    for o in order:
        g = b[b[col] == o]
        gb = g[g.bb_type == 'ground_ball'].ang
        air = g[g.bb_type.isin(['line_drive', 'fly_ball'])].ang
        out.append(f'{o}: GB pull {100 * (gb > 15).mean():.0f}% (n {len(gb)}), '
                   f'air oppo {100 * (air < -15).mean():.0f}% (n {len(air)})')
    return out


def page_when(pdf, sv, title, season, bats):
    s = sv[(sv.game_year == season) & sv.if_fielding_alignment.notna()].copy()
    s['count'] = s.balls.astype(int).astype(str) + '-' + s.strikes.astype(int).astype(str)
    s['outs'] = s.outs_when_up.astype(int).astype(str)
    s['hand'] = s.p_throws.map({'R': 'vs RHP', 'L': 'vs LHP'})
    fig = plt.figure(figsize=(20, 11.5), facecolor=BG)
    header(fig, f'{title}  |  When the infield alignment changes, {season}',
           f'{len(s):,} pitches with a Savant infield label.  Bars: share of pitches '
           'in each label (n pitches).  Right: his own spray in the same split, career.')
    fig.legend(handles=[Line2D([0], [0], marker='s', color='none', markerfacecolor=c,
                               markersize=11, label=l) for l, c in LABEL_COLORS.items()],
               loc='upper right', bbox_to_anchor=(0.97, 0.965), ncol=3, frameon=False,
               prop={'family': BODY_FONT, 'size': 10})
    specs = [('runners', ['none', '1B only', 'other'], 'Runners'),
             ('outs', ['0', '1', '2'], 'Outs'),
             ('hand', ['vs RHP', 'vs LHP'], 'Pitcher hand'),
             ('inn', ['1-3', '4-6', '7+'], 'Inning'),
             ('margin', ['Down 4+', 'Down 1-3', 'Tied', 'Up 1-3', 'Up 4+'],
              'Fielding team score'),
             ('count', ['0-0', '1-0', '2-0', '3-0', '0-1', '1-1', '2-1', '3-1',
                        '0-2', '1-2', '2-2', '3-2'], 'Count')]
    boxes = [[0.08, 0.66, 0.24, 0.18], [0.40, 0.66, 0.24, 0.18], [0.72, 0.70, 0.24, 0.14],
             [0.08, 0.40, 0.24, 0.18], [0.40, 0.36, 0.24, 0.22], [0.72, 0.17, 0.24, 0.45]]
    for (col, order, ttl), box in zip(specs, boxes):
        stacked(fig.add_axes(box), s, col, order, ttl)

    # Mid-PA changes: the count on the pitch where the label first differs
    # from the previous pitch of the same plate appearance.
    ch = []
    for _k, g in s.sort_values('pitch_number').groupby(['game_pk', 'at_bat_number']):
        lab, cnt = g.if_fielding_alignment.tolist(), g['count'].tolist()
        ch += [cnt[i] for i in range(1, len(lab)) if lab[i] != lab[i - 1]]
    n_pa = s.groupby(['game_pk', 'at_bat_number']).ngroups
    n_chg = s.groupby(['game_pk', 'at_bat_number']).if_fielding_alignment.nunique().gt(1).sum()
    ax = fig.add_axes([0.08, 0.07, 0.24, 0.22])
    vc = pd.Series(ch).value_counts().reindex(specs[-1][1][1:]).fillna(0)
    ax.bar(range(len(vc)), vc, color=TEXT_MUTED)
    ax.set_xticks(range(len(vc)), vc.index, fontfamily=BODY_FONT, fontsize=8.5)
    ax.set_title(f'Mid-PA changes: {n_chg} of {n_pa} PA ({100 * n_chg / n_pa:.0f}%), '
                 'by count of the new pitch', fontsize=10.5, fontfamily=TITLE_FONT,
                 fontweight='700', color=TEXT_PRIMARY, loc='left')
    ax.set_facecolor(BG)
    for sp in ('top', 'right'):
        ax.spines[sp].set_visible(False)
    ax.tick_params(colors=TEXT_MUTED)

    # Why: the batter's own spray (career, so splits are not too thin).
    two = sv.assign(two=np.where(sv.strikes == 2, '2 strikes', '0-1 strikes'),
                    hand=sv.p_throws.map({'R': 'vs RHP', 'L': 'vs LHP'}))
    lines = (['His spray, career (does the alignment follow him?)']
             + spray_note(two, 'runners', ['none', '1B only', 'other'])
             + spray_note(two, 'hand', ['vs RHP', 'vs LHP'])
             + spray_note(two, 'two', ['0-1 strikes', '2 strikes']))
    ax = fig.add_axes([0.40, 0.03, 0.26, 0.28])
    ax.axis('off')
    for i, t in enumerate(lines):
        ax.text(0, 1 - 0.085 * i, t, transform=ax.transAxes, va='top', fontsize=8.6,
                fontfamily=BODY_FONT, color=TEXT_PRIMARY if i == 0 else TEXT_SECOND,
                fontweight='700' if i == 0 else 'normal')
    pull = 'right' if bats == 'L' else 'left'
    fig.text(0.72, 0.10, f'Pull = {pull} side for a {bats}HH.  Labels are Savant\'s:\n'
             'Standard, Infield shade (a fielder outside his usual slice),\n'
             'Strategic (Savant\'s label for other non-standard alignments).',
             fontsize=8.5, fontfamily=BODY_FONT, color=TEXT_MUTED, va='top', linespacing=1.5)
    pdf.savefig(fig, facecolor=BG)
    return fig


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--id', type=int, required=True)
    ap.add_argument('--csv', required=True)
    ap.add_argument('--title', required=True)
    ap.add_argument('--season', type=int, default=2026)
    ap.add_argument('--out', required=True, help='output .pdf; one .png per page beside it')
    args = ap.parse_args()

    d = load_positions(args.id)
    sv = load_csv(args.csv)
    bats = sv.stand.mode().iat[0]
    out = os.path.expanduser(args.out)
    tmp = out + '.tmp.pdf'
    stem = os.path.splitext(out)[0]
    with PdfPages(tmp) as pdf:
        figs = [page_where(pdf, d, args.title, args.season),
                page_who(pdf, d, args.title, args.season),
                page_when(pdf, sv, args.title, args.season, bats)]
    os.replace(tmp, out)
    for i, f in enumerate(figs, 1):
        f.savefig(f'{stem}_p{i}.png', dpi=130, facecolor=BG)
        plt.close(f)
    print(f'-> {out} and {len(figs)} page PNGs')


if __name__ == '__main__':
    main()
