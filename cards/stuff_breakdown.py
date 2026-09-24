"""
Stuff+ Breakdown Card
Shows how the Stuff+ model builds one pitcher's grade for one pitch type, over
one outing or any date range, overall and split by batter hand.

Every bar is an exact contribution from the model itself (XGBoost TreeSHAP,
`pred_contribs`): how much one input moved this pitcher's pitches away from
the average 2026 MLB pitch of the same type, in Stuff+ points. The bars in a
panel add up to that panel's grade exactly (checked at run time). The grade
is scored the way CI scores the site and the Sheets column: features from the
pitcher's whole season (the fastball reference is a season mean), the v16
arm-angle chain, the fold model that never saw him (the full model for ROC),
and the live anchor scales from data/stuff_bundle_info.json.

Usage:
    1. Edit the Settings block at the top of main() (or pass the CLI flags)
    2. python3 cards/stuff_breakdown.py
    python3 cards/stuff_breakdown.py --pitcher "Wrobleski, Justin" --pitch-type FF --date 2026-09-22
    python3 cards/stuff_breakdown.py --pitcher "Wrobleski, Justin" --pitch-type FF --start 2026-08-01

Needs a fresh data/all_pitches_rs_cache.pkl (python3 -m pipeline.refresh_pickle,
or --refresh) and a current local bundle (the freshness check names the fix).
"""

import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

import argparse
import difflib
import json
import math
import os
import pickle
import subprocess
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import xgboost as xgb
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from matplotlib.ticker import MaxNLocator

import stuff_plus.train_stuff as T
# style, fonts (registered on import), photo and id helpers: one home, the
# pitcher card
from cards.pitcher import (BG, DARK_CELL, DARKER, ACCENT, TEXT_PRIMARY, TEXT_SECONDARY,
                           TEXT_MUTED, TEXT_FAINT, SUBTLE_BORDER, PITCH_COLORS, PITCH_NAMES,
                           OUTPUT_DIR, STUFF_COLOR_MIN_PITCHES, load_mlb_id_cache,
                           lookup_mlb_id, fetch_headshot, half_up)

REF_CACHE = os.path.join(_ROOT, 'data', '_stuff_breakdown_ref.json')
LOWER_COLOR = '#8594a6'     # slate for bars that lower the grade (raises take ACCENT)

# model input -> (row label, value formatter). Values shown are the overall
# means of what the model actually sees (density-adjusted movement, nVAA,
# hand-mirrored horizontal terms, clipped height).
def _f(fmt):
    return lambda v: fmt.format(v) if v is not None and np.isfinite(v) else 'n/a'


FEATURE_LABELS = {
    'velocity':     ('Velocity', _f('{:.1f} mph')),
    'ivb':          ('Induced vert. break', _f('{:.1f} in (air-density adj.)')),
    'hb':           ('Horizontal break', _f('{:.1f} in (arm side +)')),
    'velo_diff':    ('Velo vs primary fastball', _f('{:+.1f} mph')),
    'ivb_diff':     ('IVB vs primary fastball', _f('{:+.1f} in')),
    'hb_diff':      ('HB vs primary fastball', _f('{:+.1f} in')),
    'spin_rate':    ('Spin rate', _f('{:.0f} rpm')),
    'extension':    ('Extension', _f('{:.1f} ft')),
    'arm_angle':    ('Arm angle', _f('{:.1f}°')),
    'vaa':          ('Vertical approach angle', _f('{:.2f}° (height-adj.)')),
    'vaa_diff':     ('VAA vs primary fastball', _f('{:+.2f}°')),
    'rel_x':        ('Release side', _f('{:.1f} ft (arm side -)')),
    'cross':        ('Break across the spin axis', _f('{:+.1f} in')),
    'cross_abs':    ('Size of break across the axis', _f('{:.1f} in')),
    'height':       ('Pitcher height', _f('{:.0f} in')),
    'platoon_same': ('Batter-hand matchup', None),   # formatted from the same-hand share
}


# Fixed row order (per Wally 2026-09-24): speed, movement, spin, approach,
# delivery, then the batter context. Every card reads the same way, so two
# cards compare row by row. Inputs a model lacks (arm_angle on the no-arm
# companion) are skipped.
ROW_ORDER = ['velocity', 'velo_diff', 'ivb', 'ivb_diff', 'hb', 'hb_diff',
             'spin_rate', 'cross', 'cross_abs', 'vaa', 'vaa_diff',
             'extension', 'arm_angle', 'rel_x', 'height', 'platoon_same']


def _pct(v):
    return f'{100 * v:.0f}%'


def r0(x):
    """Stuff+ display: zero decimals, half up (116.5 -> 117), applied to the
    EXACT value, never to a one-decimal display (a true 116.46 must round to
    116). One home: cards.pitcher.half_up."""
    return half_up(x)


# ── data ────────────────────────────────────────────────────────────────
def load_pitches(refresh):
    if refresh:
        print('Refreshing data/all_pitches_rs_cache.pkl from Sheets (about 10 minutes) ...', flush=True)
        subprocess.run([sys.executable, '-m', 'pipeline.refresh_pickle'], cwd=_ROOT, check=True)
    with open(T.PKL, 'rb') as f:
        allp = pickle.load(f)
    last = max(str(p.get('Game Date'))[:10] for p in allp if p.get('Game Date'))
    return allp, last


def pitcher_rows(allp, name, level):
    srcs = ('MLB',) if level == 'MLB' else ('ROC', 'AAA')
    rows = [p for p in allp if p.get('Pitcher') == name and p.get('_source') in srcs]
    if not rows:
        names = sorted({p.get('Pitcher') for p in allp if p.get('_source') in srcs and p.get('Pitcher')})
        near = difflib.get_close_matches(name, names, n=5, cutoff=0.6)
        sys.exit(f'No {level} pitches for {name!r}. Closest names: {near or "none"}')
    return rows


def build_frame(rows, roc_rows, arm_prior):
    """The production feature frame for one pitcher: build_df over his whole
    season at this level (the fastball reference is a season mean), the
    ROC/AAA arm fallback, then the v16 prior-season fill."""
    fb = T._arm_means(roc_rows) if roc_rows else None
    df = T.build_df(rows, arm_fallback=fb)
    return T.fill_arm_prior(df, arm_prior)


# ── model choice, exactly as CI scores the pitch ─────────────────────────
def model_for(B, pitcher, level, has_arm):
    """(booster, feature list, key). MLB: the fold model that held the
    pitcher out (fold 0 for arms newer than the bundle). ROC: the full
    model. No arm angle after the chain: the no-arm companion."""
    if level == 'MLB':
        fold_of = {pp: k for k, ps in enumerate(B['fold_pitchers']) for pp in ps}
        k = fold_of.get(pitcher, 0)
        m = (B['fold_models'] if has_arm else B['fold_models_na'])[k]
        key = f"{'fold' if has_arm else 'na_fold'}{k}"
    else:
        m = B['model'] if has_arm else B['model_na']
        key = 'full' if has_arm else 'na_full'
    booster = m.get_booster()
    return booster, list(booster.feature_names), key


def design_for(df, feats, has_arm, B):
    X = T.design(df) if has_arm else T.design(df, B['noarm_feats'])
    return X.reindex(columns=feats, fill_value=0)


def contribs(booster, X):
    """Per-pitch exact contributions (last column = bias), batter-positive.
    XGBoost returns float32; averaging 216k rows in float32 drifted the bias
    column by 3e-6 (0.006 Stuff+ points), so everything downstream is float64."""
    return booster.predict(xgb.DMatrix(X), pred_contribs=True).astype('float64')


def reference_means(B, booster, feats, key, has_arm, pitch_type, allp, last_date):
    """Mean contribution per input over every 2026 MLB pitch of this type,
    under the SAME model, cached per (bundle, model, type, data date) in
    data/_stuff_breakdown_ref.json (scratch)."""
    ck = f"{B['version']}|{B['trained_through']}|{key}|{pitch_type}|{last_date}"
    cache = {}
    if os.path.exists(REF_CACHE):
        with open(REF_CACHE) as f:
            cache = json.load(f)
    if ck in cache and cache[ck]['features'] == feats:
        return np.array(cache[ck]['mean']), cache[ck]['n']
    print(f'  building the league {pitch_type} reference for {key} (cached after this run) ...', flush=True)
    ep = {(p.get('Pitcher'), p.get('PTeam')) for p in allp if p.get('Pitch Type') == 'EP'}
    mlb = [p for p in allp if p.get('_source') == 'MLB'
           and (p.get('Pitcher'), p.get('PTeam')) not in ep and p.get('Pitch Type') == pitch_type]
    # the fastball reference needs each pitcher's fastballs too
    need = {p.get('Pitcher') for p in mlb}
    fbs = [p for p in allp if p.get('_source') == 'MLB' and p.get('Pitcher') in need
           and p.get('Pitch Type') in T.FB_TYPES and p.get('Pitch Type') != pitch_type
           and (p.get('Pitcher'), p.get('PTeam')) not in ep]
    df = T.fill_arm_prior(T.build_df(mlb + fbs), B['arm_prior'])
    df = df[df['pitch_type'] == pitch_type]
    c = contribs(booster, design_for(df, feats, has_arm, B))
    mean = c.mean(axis=0)
    cache[ck] = {'features': feats, 'mean': [float(v) for v in mean], 'n': int(len(df))}
    tmp = REF_CACHE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(cache, f)
    os.replace(tmp, REF_CACHE)
    return mean, int(len(df))


# ── the breakdown ────────────────────────────────────────────────────────
def breakdown(C, ref_mean, feats, mu, sd):
    """Panel numbers from per-pitch contributions C (n x feats+1). Points are
    pitcher-positive: -10 * contribution / sd."""
    pts = -10.0 * C / sd
    grades = 100.0 + 10.0 * (-C.sum(axis=1) - mu) / sd
    anchor = 100.0 + 10.0 * (-ref_mean.sum() - mu) / sd
    delta = pts[:, :-1].mean(axis=0) - (-10.0 * ref_mean[:-1] / sd)
    total = anchor + delta.sum()
    if abs(total - grades.mean()) > 1e-6:
        raise RuntimeError(f'contributions do not add up: {total:.6f} vs {grades.mean():.6f}')
    site = float(np.mean([int(round(g)) for g in grades]))   # the whole-number pitch grades the site averages
    return {'n': int(len(grades)), 'anchor': float(anchor), 'delta': dict(zip(feats, delta)),
            'total': float(total), 'site': site}


# ── rendering ────────────────────────────────────────────────────────────
def _signed(v):
    return '(0.0)' if abs(v) < 0.05 else f'({v:+.1f})'


def render(meta, panels, order, labels, out_path):
    n_rows = len(order)
    row_h = 0.70
    panel_top_in = 4.75
    panel_bot_in = panel_top_in + n_rows * row_h
    fig_h = panel_bot_in + 3.0
    fig = plt.figure(figsize=(16, fig_h), dpi=100)
    fig.patch.set_facecolor(BG)
    H = fig_h

    def y(inches_from_top):
        return 1 - inches_from_top / H

    # header
    ax_photo = fig.add_axes([0.03, y(2.95), 0.10, 2.55 / H])
    ax_photo.axis('off')
    if meta.get('photo') is not None:
        ax_photo.imshow(meta['photo'])
    fig.text(0.15, y(0.95), meta['display_name'], fontsize=30, fontfamily='Bitter',
             fontweight='black', color=TEXT_PRIMARY, va='bottom')
    fig.text(0.15, y(1.45), meta['window_text'], fontsize=17, fontfamily='IBM Plex Sans',
             color=ACCENT, va='bottom')
    fig.text(0.15, y(1.95), meta['sub_text'], fontsize=15, fontfamily='IBM Plex Sans',
             color=TEXT_MUTED, va='bottom')
    tiles = [('VELO', meta['velo']), ('IVB', meta['ivb']), ('HB', meta['hb']),
             ('OVERALL', meta['overall']), ('VS LHH', meta['vs_l']), ('VS RHH', meta['vs_r'])]
    tw, th, gap = 0.072, 0.95 / H, 0.008
    x0 = 0.965 - 3 * tw - 2 * gap
    for i, (lab, val) in enumerate(tiles):
        r, c = divmod(i, 3)
        tx = x0 + c * (tw + gap)
        ty = y(0.55 + (r + 1) * (0.95 + 0.12))
        fig.patches.append(FancyBboxPatch((tx, ty), tw, th, boxstyle='round,pad=0,rounding_size=0.006',
                                          transform=fig.transFigure, facecolor=DARK_CELL if r == 0 else DARKER,
                                          edgecolor=SUBTLE_BORDER, linewidth=1))
        fig.text(tx + tw / 2, ty + th * 0.74, lab, fontsize=12, fontfamily='IBM Plex Sans Condensed',
                 fontweight='bold', color=TEXT_SECONDARY, ha='center', va='center')
        fig.text(tx + tw / 2, ty + th * 0.33, val, fontsize=23, fontfamily='IBM Plex Sans',
                 fontweight='bold', color=TEXT_PRIMARY if r == 0 else ACCENT, ha='center', va='center')

    # section title
    pt = meta['pitch_type']
    fig.text(0.03, y(3.5), f"{PITCH_NAMES.get(pt, pt)} Stuff+", fontsize=25, fontfamily='Bitter',
             fontweight='black', color=PITCH_COLORS.get(pt, TEXT_PRIMARY), va='bottom')
    fig.text(0.03, y(3.92), f"{meta['n_pitches']} pitches  |  how each input moved the grade from the "
             f"average 2026 MLB {PITCH_NAMES.get(pt, pt).lower()}", fontsize=14,
             fontfamily='IBM Plex Sans', color=TEXT_MUTED, va='bottom')

    # panels: shared x range
    lo, hi = 100.0, 100.0
    for p in panels:
        if not p['data']:
            continue
        cum = p['data']['anchor']
        lo, hi = min(lo, cum), max(hi, cum)
        for v in [p['data']['delta'][f] for f in order]:
            cum += v
            lo, hi = min(lo, cum), max(hi, cum)
    span = max(hi - lo, 20.0)
    lo = np.floor((lo - 0.12 * span) / 10) * 10
    hi = np.ceil((hi + 0.12 * span) / 10) * 10

    top = y(panel_top_in)
    bottom = y(panel_bot_in)
    lab_w = 0.235
    pgap = 0.04
    pw = (0.965 - 0.03 - lab_w - 2 * pgap) / 3
    # row labels
    names = [labels[f] for f in order]
    for i, (nm, sub) in enumerate(names):
        yc = top - (i + 0.5) * row_h / H
        fig.text(0.03 + lab_w - 0.008, yc + 0.06 / H, nm, fontsize=15, fontfamily='IBM Plex Sans',
                 fontweight='bold', color=TEXT_PRIMARY, ha='right', va='bottom')
        fig.text(0.03 + lab_w - 0.008, yc - 0.03 / H, sub, fontsize=12, fontfamily='IBM Plex Sans',
                 color=TEXT_MUTED, ha='right', va='top')

    for k, p in enumerate(panels):
        px = 0.03 + lab_w + k * (pw + pgap)
        ax = fig.add_axes([px, bottom, pw, top - bottom])
        ax.set_facecolor(BG)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.set_xlim(lo, hi)
        ax.set_ylim(n_rows, 0)
        ax.set_yticks([])
        ax.tick_params(axis='x', colors=TEXT_MUTED, labelsize=13)
        for tick in ax.get_xticklabels():
            tick.set_fontfamily('IBM Plex Sans')
        ax.grid(axis='x', color=SUBTLE_BORDER, linewidth=0.6, linestyle=':')
        ax.set_axisbelow(True)
        ax.xaxis.set_major_locator(MaxNLocator(nbins=6, steps=[1, 2, 5, 10], integer=True))
        n = p['data']['n'] if p['data'] else 0
        flag = '  (small sample)' if 0 < n < STUFF_COLOR_MIN_PITCHES else ''
        ax.set_title(p['title'], fontsize=16, fontfamily='IBM Plex Sans',
                     fontweight='bold', color=TEXT_SECONDARY, pad=30)
        ax.text(0.5, 1.012, f"n = {n}{', small sample' if flag else ''}", transform=ax.transAxes,
                ha='center', va='bottom', fontsize=12.5, fontfamily='IBM Plex Sans',
                color=ACCENT if flag else TEXT_MUTED)
        if not p['data']:
            ax.text((lo + hi) / 2, n_rows / 2, 'no pitches', ha='center', va='center',
                    fontsize=16, color=TEXT_FAINT, fontfamily='IBM Plex Sans')
            ax.set_xticks([])
            continue
        d = p['data']
        # the chain starts at the average MLB pitch of the type (the solid
        # line), not at the scale's 100: the two differ by a few tenths
        ax.axvline(d['anchor'], color=TEXT_SECONDARY, linewidth=1.3)
        cum = d['anchor']
        steps = [d['delta'][f] for f in order]
        for i, v in enumerate(steps):
            left, right = (cum, cum + v) if v >= 0 else (cum + v, cum)
            ax.barh(i + 0.5, right - left, left=left, height=0.72,
                    color=ACCENT if v >= 0 else LOWER_COLOR, edgecolor='none', zorder=3)
            if i + 1 < len(steps):
                ax.plot([cum + v, cum + v], [i + 0.86, i + 1.14], color=TEXT_FAINT, linewidth=0.9, zorder=2)
            xt = right + 0.012 * (hi - lo) if v >= 0 else left - 0.012 * (hi - lo)
            ax.text(xt, i + 0.5, _signed(v), va='center', ha='left' if v >= 0 else 'right',
                    fontsize=13.5, fontfamily='IBM Plex Sans', fontweight='bold',
                    color=ACCENT if v >= 0 else '#5a6878', zorder=6,
                    bbox=dict(facecolor=BG, edgecolor='none', pad=0.6))
            cum += v
        ax.axvline(d['total'], color=ACCENT, linewidth=1.5, linestyle='--', zorder=4)
        fig.text(px + pw / 2, y(panel_bot_in + 0.48), f"{r0(d['site'])} Stuff+", ha='center',
                 va='top', fontsize=18, fontfamily='IBM Plex Sans', fontweight='bold', color=ACCENT)
        if r0(d['total']) != r0(d['site']):
            fig.text(px + pw / 2, y(panel_bot_in + 0.85), f"bars sum to {d['total']:.1f}",
                     ha='center', va='top', fontsize=12, fontfamily='IBM Plex Sans', color=TEXT_MUTED)

    # legend + footer
    fy = y(panel_bot_in + 1.35)
    for i, (lab, col) in enumerate((('Raises the grade', ACCENT), ('Lowers the grade', LOWER_COLOR))):
        fx = 0.16 + i * 0.16
        fig.patches.append(FancyBboxPatch((fx, fy), 0.014, 0.2 / H, boxstyle='square,pad=0',
                                          transform=fig.transFigure, facecolor=col, edgecolor='none'))
        fig.text(fx + 0.019, fy + 0.1 / H, lab, fontsize=13, fontfamily='IBM Plex Sans',
                 color=TEXT_SECONDARY, va='center')
    avg_lab = f"Average MLB {PITCH_NAMES.get(pt, pt).lower()}"
    for fx, ls, col, lab in ((0.48, '-', TEXT_SECONDARY, avg_lab), (0.70, '--', ACCENT, 'Grade')):
        # vertical key marks, drawn like the vertical lines they label
        fig.add_artist(plt.Line2D([fx + 0.006] * 2, [fy - 0.05 / H, fy + 0.25 / H], transform=fig.transFigure,
                                  color=col, linewidth=2, linestyle=ls))
        fig.text(fx + 0.016, fy + 0.1 / H, lab, fontsize=13, fontfamily='IBM Plex Sans',
                 color=TEXT_SECONDARY, va='center')
    notes = [
        f"Each bar shows how much one input moved these pitches away from the average 2026 MLB "
        f"{PITCH_NAMES.get(pt, pt).lower()} (solid line), in Stuff+ points. The values come directly from the "
        f"model.",
        'Related inputs share credit (for example, velocity and the velocity gap to the fastball), so read those '
        'bars together. vs LHH / vs RHH use only the pitches thrown to that batter hand.',
        'The bars add up to each panel\'s grade before rounding; grades match the site. ' + meta['model_text'],
    ]
    for i, t in enumerate(notes):
        fig.text(0.03, fy - (0.42 + 0.34 * i) / H, t, fontsize=12.5, fontfamily='IBM Plex Sans',
                 fontweight=500, color=TEXT_SECONDARY, va='top')
    fig.text(0.965, fy - 1.10 / H, 'huronalytics.vercel.app', fontsize=13, fontfamily='IBM Plex Sans',
             fontweight='bold', color=TEXT_SECONDARY, ha='right', va='top')
    fig.savefig(out_path, dpi=150, facecolor=BG)
    plt.close(fig)


# ── main ─────────────────────────────────────────────────────────────────
def main():
    # ── Settings (per-run scratch; every CLI flag below overrides one) ──
    pitcher    = 'Wrobleski, Justin'   # "Last, First" as in the sheets
    pitch_type = 'FF'
    start_date = None                  # 'YYYY-MM-DD'; None = season start
    end_date   = None                  # 'YYYY-MM-DD'; None = the last game in the cache
    level      = 'MLB'                 # 'MLB' or 'ROC'
    output_dir = OUTPUT_DIR
    top_n      = None                  # None = every input; an int keeps the largest |overall| bars
    photo      = True
    refresh    = False                 # True re-reads Sheets into the pickle first (~10 min)

    ap = argparse.ArgumentParser(description='Stuff+ breakdown card for one pitch type')
    ap.add_argument('--pitcher')
    ap.add_argument('--pitch-type')
    ap.add_argument('--date', help='one outing: sets --start and --end')
    ap.add_argument('--start')
    ap.add_argument('--end')
    ap.add_argument('--level', choices=['MLB', 'ROC'])
    ap.add_argument('--output-dir')
    ap.add_argument('--top-n', type=int)
    ap.add_argument('--no-photo', action='store_true')
    ap.add_argument('--refresh', action='store_true')
    a = ap.parse_args()
    pitcher = a.pitcher or pitcher
    pitch_type = (a.pitch_type or pitch_type).upper()
    if a.date:
        start_date = end_date = a.date
    start_date = a.start or start_date
    end_date = a.end or end_date
    level = a.level or level
    output_dir = a.output_dir or output_dir
    top_n = a.top_n if a.top_n is not None else top_n
    photo = photo and not a.no_photo
    refresh = refresh or a.refresh

    with open(os.path.join(_ROOT, 'stuff_plus', 'stuff_models.pkl'), 'rb') as f:
        B = pickle.load(f)
    if B.get('version') != T.BUNDLE_VERSION or 'arm_prior' not in B:
        sys.exit(f"stuff_models.pkl is {B.get('version')!r}, the code expects {T.BUNDLE_VERSION!r}. "
                 f"Refresh it:\n  {T.BUNDLE_REFRESH_CMD}")
    T.check_bundle_fresh(B)
    league, na_league = T.live_scales(B)

    allp, last = load_pitches(refresh)
    if end_date and end_date > last:
        sys.exit(f'data/all_pitches_rs_cache.pkl ends {last}, before {end_date}. Refresh it:\n'
                 f'  python3 -m pipeline.refresh_pickle   (or run this with --refresh)')
    rows = pitcher_rows(allp, pitcher, level)
    roc_rows = ([p for p in allp if p.get('Pitcher') == pitcher and p.get('_source') in ('ROC', 'AAA')]
                if level == 'MLB' else None)
    df = build_frame(rows, roc_rows, B['arm_prior'])
    df['date'] = df['date'].astype(str).str.slice(0, 10)
    bats = {p.get('PitchID'): p.get('Bats') for p in rows}
    df['bats'] = df['pid'].map(bats)
    lo_d = start_date or '0000-00-00'
    hi_d = end_date or last
    w = df[(df['pitch_type'] == pitch_type) & (df['date'] >= lo_d) & (df['date'] <= hi_d)].reset_index(drop=True)
    if not len(w):
        types = df[(df['date'] >= lo_d) & (df['date'] <= hi_d)]['pitch_type'].value_counts().to_dict()
        sys.exit(f'No {pitch_type} for {pitcher} in {lo_d}..{hi_d}. Pitch types there: {types or "none"}')

    has_arm = bool(df.loc[df['pitcher'] == pitcher, 'arm_angle'].notna().any())
    booster, feats, key = model_for(B, pitcher, level, has_arm)
    scale = (league if has_arm else na_league).get(pitch_type)
    if not scale or not scale.get('sd'):
        sys.exit(f'No anchor scale for {pitch_type} in the bundle')
    mu, sd = scale['mu'], scale['sd']
    ref_mean, ref_n = reference_means(B, booster, feats, key, has_arm, pitch_type, allp, last)

    C = contribs(booster, design_for(w, feats, has_arm, B))
    panels = []
    for title, mask in (('Overall', np.ones(len(w), bool)),
                        ('vs LHH', (w['bats'] == 'L').values), ('vs RHH', (w['bats'] == 'R').values)):
        panels.append({'title': title, 'data': breakdown(C[mask], ref_mean, feats, mu, sd) if mask.any() else None})

    overall = panels[0]['data']
    order = [f for f in ROW_ORDER if f in feats] + [f for f in feats if f not in ROW_ORDER]
    if top_n:
        keep = set(sorted(order, key=lambda f: -abs(overall['delta'][f]))[:top_n])
        order = [f for f in order if f in keep]
        # fold the rest into one row so the panels still add up
        rest = [f for f in feats if f not in order]
        if rest:
            for p in panels:
                if p['data']:
                    p['data']['delta']['__other__'] = sum(p['data']['delta'][f] for f in rest)
            order.append('__other__')

    # row labels with the overall means of what the model sees
    labels = {}
    for f in feats:
        nm, fmt = FEATURE_LABELS.get(f, (f, _f('{:.2f}')))
        if f == 'platoon_same':
            labels[f] = (nm, f"same-hand share {_pct(w['platoon_same'].mean())}")
        elif f == 'velo_diff' and w[f].isna().all():
            labels[f] = (nm, 'blank on FF/SI (model routing only)')
        else:
            labels[f] = (nm, fmt(float(w[f].mean())) if f in w else 'n/a')
    labels['__other__'] = ('Other inputs', f'{len(feats) - (len(order) - 1)} smaller bars combined')

    # header facts from the sheet rows of the window
    wid = set(w['pid'])
    wr = [p for p in rows if p.get('PitchID') in wid]
    def _mean(col):
        v = [T.sf(p.get(col)) for p in wr]
        v = [x for x in v if x is not None]
        return float(np.mean(v)) if v else float('nan')
    team = max(wr, key=lambda p: str(p.get('Game Date'))).get('PTeam')
    hand = wr[0].get('Throws')
    if lo_d == hi_d:
        opp = {p.get('BTeam') for p in wr} - {team}
        window_text = datetime.strptime(lo_d, '%Y-%m-%d').strftime('%B %-d, %Y') + \
            (f"  vs {', '.join(sorted(o for o in opp if o))}" if opp else '')
    else:
        first, lastd = min(w['date']), max(w['date'])
        window_text = (f"{datetime.strptime(first, '%Y-%m-%d').strftime('%b %-d')} to "
                       f"{datetime.strptime(lastd, '%Y-%m-%d').strftime('%b %-d, %Y')}"
                       f"  ({w['date'].nunique()} games)")
    last_first = pitcher.split(', ')
    display = f'{last_first[1]} {last_first[0]}' if len(last_first) == 2 else pitcher
    img = None
    if photo:
        mid = lookup_mlb_id(pitcher, team, load_mlb_id_cache())   # the id cache is read, never saved here
        img = fetch_headshot(mid) if mid else None
    def _tile(p):
        return f"{r0(p['data']['site'])}" if p['data'] else '-'
    meta = {
        'display_name': display, 'window_text': window_text,
        'sub_text': f"{'LHP' if hand == 'L' else 'RHP'}  |  {team}  |  {'MLB' if level == 'MLB' else 'AAA'}",
        'pitch_type': pitch_type, 'n_pitches': len(w), 'photo': img, 'anchor': overall['anchor'],
        'velo': f"{_mean('Velocity'):.1f}", 'ivb': f"{_mean('IndVertBrk'):.1f}",
        'hb': f"{_mean('HorzBrk'):.1f}",
        'overall': _tile(panels[0]), 'vs_l': _tile(panels[1]), 'vs_r': _tile(panels[2]),
        'model_text': (f"Stuff+ {B['version']}, trained through {B['trained_through']}; "
                       f"{'' if has_arm else 'graded without arm angle (none recorded yet); '}"
                       f"data through {last}."),
    }
    os.makedirs(output_dir, exist_ok=True)
    fn = (f"{last_first[0]}_{last_first[1] if len(last_first) == 2 else ''}_{pitch_type}_stuff_breakdown_"
          f"{min(w['date'])}_{max(w['date'])}.png").replace(' ', '')
    out = os.path.join(output_dir, fn)
    render(meta, panels, order, labels, out)

    # the same numbers as text
    print(f"\n{display} {pitch_type}  {window_text}  ({len(w)} pitches)")
    print(f"  Stuff+ (site value, half up): overall {meta['overall']}, vs LHH {meta['vs_l']}, "
          f"vs RHH {meta['vs_r']}   exact: " + ', '.join(
              f"{p['data']['site']:.3f}" if p['data'] else '-' for p in panels))
    hdr = f"  {'input':<32}" + ''.join(f"{p['title']:>12}" for p in panels)
    print(hdr)
    print(f"  {'start: average MLB ' + pitch_type:<32}" +
          ''.join(f"{(p['data']['anchor'] if p['data'] else float('nan')):>12.1f}" for p in panels)
          + f"   ({ref_n:,} pitches)")
    for f in order:
        nm = labels[f][0] if f in labels else f
        print(f"  {nm:<32}" + ''.join(f"{(p['data']['delta'][f] if p['data'] else float('nan')):>+12.1f}"
                                     for p in panels))
    print(f"  {'= grade (unrounded)':<32}" +
          ''.join(f"{(p['data']['total'] if p['data'] else float('nan')):>12.1f}" for p in panels))
    print(f'\nwrote {out}')


if __name__ == '__main__':
    main()
