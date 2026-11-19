#!/usr/bin/env python3
"""xmove_agnostic_examples.py — examples for the tag-family expected movement (2026-11-19).

Three pictures of the points made to Wally about a relabel-proof expectation:
  1  WHAT THE ARROW SAYS. Every pitcher's sinker (150+ pitches, 2026) as one dot: its actual
     movement minus its expectation, under the shipped per-type fit and under the tag-family
     fit. Shipped: the cloud sits on zero, so an arrow means "different from other sinkers".
     Family: the whole cloud sits down and to the arm side, so an arrow first means "sinker".
  2  THE SECOND NUMBER. Rank of each pitch inside its own pitch type, shipped against family.
     If they agree, a percentile within type beside the plate gives back what the arrow lost.
  3  THE SAME THREE SINKERS under both forms: a plain one and the two extremes.

  .venv/bin/python scripts/research/xmove/xmove_agnostic_examples.py
Output: ~/Downloads/xmove_family_examples_1_sinkers.png, _2_ranks.png, and a console table
"""
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import xmove_cavalli_proto as CP  # noqa: E402
import xmove_agnostic_plate as PL  # noqa: E402

DL = os.path.expanduser('~/Downloads')
MIN_UNIT = 150
TYPES = ('FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS')


def main():
    df = CP.load_2026().reset_index(drop=True)
    df = df[df['Pitch Type'].isin(PL.TAGFAM)].reset_index(drop=True)
    df['fam_tag'] = df['Pitch Type'].map(PL.TAGFAM)
    for name, col in (('ship', 'Pitch Type'), ('tag', 'fam_tag')):
        co = PL.fit_groups(df, col)
        xi, xh = PL.score_groups(df, col, co)
        df[f'oi_{name}'], df[f'oh_{name}'] = df['ivb'] - xi, df['hb_s'] - xh
    u = df.groupby(['Pitcher', 'Throws', 'Pitch Type']).agg(n=('ivb', 'size'), ivb=('ivb', 'mean'), hb=('hb_s', 'mean'),
                                                             oi_ship=('oi_ship', 'mean'), oh_ship=('oh_ship', 'mean'),
                                                             oi_tag=('oi_tag', 'mean'), oh_tag=('oh_tag', 'mean')).reset_index()
    u = u[u['n'] >= MIN_UNIT].dropna().reset_index(drop=True)
    for c in ('oi_ship', 'oh_ship', 'oi_tag', 'oh_tag'):
        u['p_' + c] = u.groupby('Pitch Type')[c].rank(pct=True) * 100

    # ── 1. the sinker cloud ──
    s = u[u['Pitch Type'] == 'SI'].copy()
    s['size_ship'] = np.hypot(s['oi_ship'], s['oh_ship'])
    plain = s.loc[s['size_ship'].idxmin()]
    sink = s.loc[s['oi_ship'].idxmin()]            # most sink against other sinkers
    run = s.loc[s['oh_ship'].idxmax()]             # most run against other sinkers
    ride = s.loc[s['oi_ship'].idxmax()]            # least sink
    picks = [('plain', plain), ('most sink', sink), ('most run', run), ('least sink', ride)]
    c = CP.PITCH_COLORS['SI']
    fig, axes = plt.subplots(1, 2, figsize=(14, 7), facecolor=CP.BG)
    for ax, form, title in ((axes[0], 'ship', 'SHIPPED: actual minus what a SINKER from that slot does'),
                            (axes[1], 'tag', 'TAG FAMILIES: actual minus what a HARD PITCH from that slot does')):
        ax.set_facecolor(CP.PLOT_PANEL)
        ax.scatter(s[f'oh_{form}'], s[f'oi_{form}'], s=26, color=c, alpha=0.45, linewidths=0)
        ax.axhline(0, color=CP.TEXT_FAINT, lw=0.8)
        ax.axvline(0, color=CP.TEXT_FAINT, lw=0.8)
        mx, my = s[f'oh_{form}'].mean(), s[f'oi_{form}'].mean()
        ax.scatter([mx], [my], marker='+', s=260, color=CP.TEXT_SECONDARY, linewidths=2, zorder=6)
        ax.annotate(f'league average sinker\n{my:+.1f} in ride, {mx:+.1f} in run', (mx, my), xytext=(-150, 36), textcoords='offset points',
                    arrowprops=dict(arrowstyle='-', color=CP.TEXT_FAINT, lw=0.8),
                    fontsize=9, color=CP.TEXT_SECONDARY)
        for lab, r in picks:
            ax.scatter([r[f'oh_{form}']], [r[f'oi_{form}']], s=90, color=c, edgecolors=CP.TEXT_SECONDARY, linewidths=1.3, zorder=7)
            ax.annotate(f'{r["Pitcher"].split(",")[0]} ({lab})', (r[f'oh_{form}'], r[f'oi_{form}']), xytext=(7, -4), textcoords='offset points',
                        fontsize=8.5, color=CP.TEXT_SECONDARY)
        ax.set_xlim(-10, 12)
        ax.set_ylim(-13, 11.5)
        ax.grid(True, alpha=0.5, color=CP.GRID_COLOR)
        ax.set_xlabel('Run beyond expected (in, arm side +)', fontsize=10, color=CP.TEXT_MUTED, fontweight='bold')
        ax.set_ylabel('Ride beyond expected (in)', fontsize=10, color=CP.TEXT_MUTED, fontweight='bold')
        ax.set_title(title, fontsize=11, color=CP.TEXT_SECONDARY, fontweight='bold', pad=8)
        ax.tick_params(labelsize=8, colors=CP.TEXT_MUTED)
    fig.suptitle(f'Every sinker of 2026 with {MIN_UNIT}+ pitches ({len(s)} pitchers): one dot = that pitcher\'s arrow on the plate',
                 fontsize=13, color=CP.TEXT_SECONDARY, fontweight='bold', y=0.98)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fn1 = os.path.join(DL, 'xmove_family_examples_1_sinkers.png')
    fig.savefig(fn1, dpi=150, facecolor=CP.BG)
    plt.close(fig)

    # ── 2. rank inside the pitch type, shipped against family ──
    fig, axes = plt.subplots(2, 4, figsize=(17, 8.6), facecolor=CP.BG)
    print(f'rank inside the pitch type, shipped against tag families ({MIN_UNIT}+ pitches): Spearman r for ride and for run')
    for ax, pt in zip(axes.ravel(), TYPES):
        g = u[u['Pitch Type'] == pt]
        ri = g[['p_oi_ship', 'p_oi_tag']].corr(method='spearman').iloc[0, 1]
        rh = g[['p_oh_ship', 'p_oh_tag']].corr(method='spearman').iloc[0, 1]
        mi = (g['p_oi_ship'] - g['p_oi_tag']).abs()
        mh = (g['p_oh_ship'] - g['p_oh_tag']).abs()
        print(f'  {pt}: n {len(g):4d}  ride r {ri:.3f} (median move {mi.median():.0f} pct points, 90th pct {mi.quantile(.9):.0f})   '
              f'run r {rh:.3f} (median {mh.median():.0f}, 90th pct {mh.quantile(.9):.0f})')
        ax.set_facecolor(CP.PLOT_PANEL)
        ax.plot([0, 100], [0, 100], color=CP.TEXT_FAINT, lw=0.8)
        ax.scatter(g['p_oi_ship'], g['p_oi_tag'], s=14, color=CP.PITCH_COLORS[pt], alpha=0.7, linewidths=0, label=f'ride  r {ri:.2f}')
        ax.scatter(g['p_oh_ship'], g['p_oh_tag'], s=14, facecolors='none', edgecolors=CP.PITCH_COLORS[pt], alpha=0.7, linewidths=0.8,
                   label=f'run  r {rh:.2f}')
        ax.set_title(f'{CP.PITCH_NAMES.get(pt, pt)} ({len(g)} pitchers)', fontsize=10.5, color=CP.TEXT_SECONDARY, fontweight='bold')
        ax.legend(fontsize=8.5, loc='upper left', frameon=False)
        ax.set_xlabel('percentile within type, SHIPPED', fontsize=8.5, color=CP.TEXT_MUTED)
        ax.set_ylabel('percentile within type, TAG FAMILIES', fontsize=8.5, color=CP.TEXT_MUTED)
        ax.tick_params(labelsize=7.5, colors=CP.TEXT_MUTED)
        ax.grid(True, alpha=0.5, color=CP.GRID_COLOR)
    fig.suptitle('Does a rank inside the pitch type survive the change? Each dot is one pitcher\'s pitch (filled = ride, open = run)',
                 fontsize=13, color=CP.TEXT_SECONDARY, fontweight='bold', y=0.985)
    fig.tight_layout(rect=(0, 0, 1, 0.955))
    fn2 = os.path.join(DL, 'xmove_family_examples_2_ranks.png')
    fig.savefig(fn2, dpi=150, facecolor=CP.BG)
    plt.close(fig)

    # ── 3. the same sinkers, both forms ──
    print('\nthe same sinkers under both forms (ride / run in inches; pct = rank among sinkers)')
    print(f'{"pitcher":<22s}{"n":>5s}{"actual":>14s}{"SHIPPED arrow":>16s}{"pct":>10s}{"FAMILY arrow":>16s}{"pct":>10s}')
    for lab, r in picks:
        print(f'{r["Pitcher"] + " (" + lab + ")":<34s}'[:34].ljust(34) + f'{int(r["n"]):>5d}{f"{r.ivb:.1f} / {r.hb:.1f}":>14s}'
              f'{f"{r.oi_ship:+.1f} / {r.oh_ship:+.1f}":>16s}{f"{r.p_oi_ship:.0f} / {r.p_oh_ship:.0f}":>10s}'
              f'{f"{r.oi_tag:+.1f} / {r.oh_tag:+.1f}":>16s}{f"{r.p_oi_tag:.0f} / {r.p_oh_tag:.0f}":>10s}')
    print(f'sinker arrows, league: shipped mean {s.oi_ship.mean():+.1f} / {s.oh_ship.mean():+.1f} (sd {s.oi_ship.std():.1f} / {s.oh_ship.std():.1f}); '
          f'family mean {s.oi_tag.mean():+.1f} / {s.oh_tag.mean():+.1f} (sd {s.oi_tag.std():.1f} / {s.oh_tag.std():.1f})')
    print(f'share of sinkers whose family arrow points down AND arm side: {((s.oi_tag < 0) & (s.oh_tag > 0)).mean():.0%}; shipped: {((s.oi_ship < 0) & (s.oh_ship > 0)).mean():.0%}')
    print(f'wrote {fn1}\nwrote {fn2}')


if __name__ == '__main__':
    main()
