#!/usr/bin/env python3
"""xmove_agnostic_plate.py — one pitcher, three definitions of expected movement, side by side.

Wally, 2026-11-19: the expectation should not change when a pitch is relabelled. The numbers
cannot choose between the relabel-proof forms (xmove_agnostic_v2.py: given slot, extension,
velocity and raw movement, no residual adds information about results), so this draws them.

All three panels use the shipped inputs (arm angle, extension, velocity), fit on the 2026 MLB
pitches. Only the GROUP changes:
  1  SHIPPED            one fit per pitch type and hand
  2  TAG FAMILIES       one fit per family and hand: FF SI FC | SL ST SV CU KC | CH FS
  3  PHYSICAL FAMILIES  no tag read: hard = within CUT mph of the pitcher's own 95th-percentile
                        velocity; the soft pitches split by the side of the measured release tilt
Disc = actual mean, dashed ring = expectation, dashed line = the difference.
Panel 1 also shows the complaint: the dotted ring is where the shipped expectation goes if the
pitcher's slider is called a sweeper (or his sweeper a slider).

  .venv/bin/python scripts/research/xmove/xmove_agnostic_plate.py --pitcher 'Cavalli, Cade'
Output: ~/Downloads/xmove_agnostic_plate_<name>.png
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
import xmove_cavalli_proto as CP  # noqa: E402  (reads --pitcher from argv)

PITCHER = CP.PITCHER
CUT = 5.0            # mph below the pitcher's own top velocity; the natural break in the data is 4.8
TAGFAM = {'FF': 'H', 'SI': 'H', 'FC': 'H', 'SL': 'B', 'ST': 'B', 'SV': 'B', 'CU': 'B', 'KC': 'B', 'CH': 'O', 'FS': 'O'}
OUT = os.path.expanduser(f'~/Downloads/xmove_agnostic_plate_{PITCHER.split(",")[0].lower().replace(" ", "")}.png')
MIN_SHOW = 15


def fit_groups(df, col):
    coefs = {}
    for key, g in df.groupby([col, 'Throws']):
        if len(g) < CP.MIN_N:
            continue
        A = CP.X(g, CP.OLD)
        coefs[key] = (np.linalg.lstsq(A, g['ivb'].values, rcond=None)[0], np.linalg.lstsq(A, g['hb_s'].values, rcond=None)[0])
    return coefs


def score_groups(df, col, coefs):
    xi, xh = np.full(len(df), np.nan), np.full(len(df), np.nan)
    for key, idx in df.groupby([col, 'Throws']).indices.items():
        if key in coefs:
            A = CP.X(df.iloc[idx], CP.OLD)
            xi[idx], xh[idx] = A @ coefs[key][0], A @ coefs[key][1]
    return xi, xh


def main():
    df = CP.load_2026().reset_index(drop=True)
    df = df[df['Pitch Type'].isin(TAGFAM)].reset_index(drop=True)
    v95 = df.groupby('Pitcher')['Velocity'].transform(lambda s: s.quantile(0.95))
    df['dv'] = df['Velocity'] - v95
    st = np.sin(df['th'].values)
    arm = np.sign(st[(df['Pitch Type'] == 'CH').values].mean())
    df['fam_tag'] = df['Pitch Type'].map(TAGFAM)
    df['fam_phys'] = np.where(df['dv'] >= -CUT, 'H', np.where(np.sign(st) == arm, 'O', 'B'))
    forms = {}
    for name, col in (('ship', 'Pitch Type'), ('tag', 'fam_tag'), ('phys', 'fam_phys')):
        co = fit_groups(df, col)
        forms[name] = (col, co)
        df[f'xi_{name}'], df[f'xh_{name}'] = score_groups(df, col, co)
    p = df[df['Pitcher'] == PITCHER].copy()
    if p.empty:
        sys.exit(f'no 2026 MLB pitches for {PITCHER}')
    s = p['s'].iloc[0]
    # the complaint: SL scored as ST (or ST as SL) under the shipped per-type fit
    co = forms['ship'][1]
    thr = p['Throws'].iloc[0]
    relabel = {}
    for a, b in (('SL', 'ST'), ('ST', 'SL'), ('FF', 'SI'), ('SI', 'FF'), ('FC', 'SL')):
        g = p[p['Pitch Type'] == a]
        if len(g) >= MIN_SHOW and (b, thr) in co:
            A = CP.X(g, CP.OLD)
            relabel[a] = (b, float((A @ co[(b, thr)][0]).mean()), float((A @ co[(b, thr)][1]).mean()) * s)
    counts = p['Pitch Type'].value_counts()
    types = [t for t in CP.PITCH_ORDER if counts.get(t, 0) >= MIN_SHOW]
    print(f'{PITCHER} 2026: ' + ', '.join(f'{t} {counts[t]}' for t in types) + f'; top velocity (95th pct) {v95[p.index].iloc[0]:.1f}')
    print(f'{"type":>5s}{"n":>6s}{"actual IVB/HB":>16s}' + ''.join(f'{n + " exp":>16s}{"diff":>14s}' for n in ('shipped', 'tag fam', 'physical')) + '   physical family share (H / B / O)')
    panels = {n: [] for n in forms}
    for t in types:
        g = p[p['Pitch Type'] == t]
        aI, aH = g['ivb'].mean(), g['xHorzBrk'].mean()
        line = f'{t:>5s}{len(g):>6d}{f"{aI:.1f} / {aH:.1f}":>16s}'
        for n in forms:
            eI, eH = g[f'xi_{n}'].mean(), (g[f'xh_{n}'] * s).mean()
            panels[n].append({'pt': t, 'aX': aH, 'aY': aI, 'eX': eH, 'eY': eI})
            line += f'{f"{eI:.1f} / {eH:.1f}":>16s}{f"{aI - eI:+.1f} / {aH - eH:+.1f}":>14s}'
        sh = g['fam_phys'].value_counts(normalize=True)
        line += '   ' + ' / '.join(f'{sh.get(k, 0):.0%}' for k in ('H', 'B', 'O'))
        print(line)
    for a, (b, eI, eH) in relabel.items():
        base = next(r for r in panels['ship'] if r['pt'] == a)
        print(f'  relabel {a} -> {b} under the shipped model: expectation {base["eY"]:.1f} / {base["eX"]:.1f} -> {eI:.1f} / {eH:.1f} '
              f'(moves {np.hypot(eI - base["eY"], eH - base["eX"]):.1f} in); tag families move {0.0 if TAGFAM[a] == TAGFAM[b] else float("nan"):.1f}; physical 0.0')

    fig, axes = plt.subplots(1, 3, figsize=(19.5, 7.2), facecolor=CP.BG)
    titles = {'ship': 'SHIPPED: one fit per pitch type', 'tag': 'TAG FAMILIES: fastball / breaking / offspeed',
              'phys': f'PHYSICAL FAMILIES: no tag (hard = within {CUT:g} mph of his top)'}
    for ax, n in zip(axes, forms):
        CP.draw_panel(ax, titles[n], panels[n])
        if n == 'ship':
            for a, (b, eI, eH) in relabel.items():
                if a not in ('SL', 'ST'):
                    continue
                base = next(r for r in panels['ship'] if r['pt'] == a)
                c = CP.PITCH_COLORS[a]
                ax.annotate('', xy=(eH, eI), xytext=(base['eX'], base['eY']), arrowprops=dict(arrowstyle='->', color=c, lw=1.6, linestyle=':'), zorder=4)
                ax.scatter([eH], [eI], s=140, facecolors='none', edgecolors=c, linewidths=1.4, linestyle=':', zorder=4)
                ax.annotate(f'if called {b}', (eH, eI), xytext=(6, -12), textcoords='offset points', fontsize=7.5, color=c)
    fig.suptitle(f'{PITCHER.split(", ")[1]} {PITCHER.split(", ")[0]}, 2026: three definitions of expected movement (disc = actual, dashed ring = expected)',
                 fontsize=13, color=CP.TEXT_SECONDARY, fontweight='bold', y=0.98)
    fig.text(0.5, 0.012, 'Same inputs in every panel: arm angle, extension, velocity. Only the group that shares one fit changes. '
             'Dotted ring in panel 1 = the shipped expectation after a relabel.', ha='center', fontsize=9, color=CP.TEXT_MUTED)
    fig.tight_layout(rect=(0, 0.06, 1, 0.95))
    fig.savefig(OUT, dpi=150, facecolor=CP.BG)
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
