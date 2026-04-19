#!/usr/bin/env python3
"""
Predict hypothetical new pitch metrics for a pitcher given his current
arsenal and biomechanics.

Fits a multivariate normal over:
  [arm_angle, extension, FF_velo, FF_IVB, FF_HB, FF_spin, (other_arsenal)?, T_velo, T_IVB, T_HB, T_spin]
per (target pitch type, pitcher hand) across all pitchers who throw both the
anchor fastball and the target pitch. Then conditions on the target pitcher's
known values to produce the posterior distribution of the target pitch.

Two tiers:
  Tier 1: condition only on biomechanics and the anchor fastball (FF, or SI
          if no FF). Always available.
  Tier 2: also condition on the pitcher's other existing pitches. Sharpens the
          prediction but training sample shrinks. Skipped for a given target if
          training sample drops below 30.

Usage:
  python3 scripts/predict_new_pitch.py "Beeter, Clayton" WSH CU
  python3 scripts/predict_new_pitch.py "Beeter, Clayton" WSH CU SI CH
  python3 scripts/predict_new_pitch.py --tier 1 "Beeter, Clayton" WSH CU
  python3 scripts/predict_new_pitch.py --no-plot "Beeter, Clayton" WSH CU

Outputs:
  - printed arsenal summary, predictions, and Mahalanobis comps
  - two-panel plot at scripts/outputs/new_pitch/<pitcher>_<pitches>.png
"""

import argparse
import json
import sys
from pathlib import Path
from collections import defaultdict

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data'
OUTPUT_DIR = Path.home() / 'Downloads'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MIN_COUNT = 25
TIER2_MIN_TRAIN = 30
N_COMPS = 10

# Metrics we fit over in the MVN. Spin stays in the joint distribution so it
# sharpens the velo/IVB/HB conditional, but we do not display predicted spin
# because the cross-pitcher variance on spin-per-grip is high enough that
# "don't trust it" is the right call.
TARGET_METRICS = ['velocity', 'indVertBrk', 'horzBrk', 'spinRate']
PITCH_METRICS = ['velocity', 'indVertBrk', 'horzBrk', 'spinRate']
# Subset actually shown to the user
DISPLAY_METRICS = ['velocity', 'indVertBrk', 'horzBrk']
DISPLAY_INDICES = [TARGET_METRICS.index(m) for m in DISPLAY_METRICS]
# Biomechanics conditioning
BIOMECH = ['armAngle', 'extension']

# Pitch colors matching js/utils.js site palette
PITCH_COLORS = {
    'FF': '#4488FF', 'SI': '#FFD700', 'FC': '#FFA500', 'SL': '#DDDDDD',
    'ST': '#FF1493', 'SV': '#32CD32', 'CU': '#E03030', 'CH': '#CC66EE',
    'FS': '#40E0D0', 'KN': '#AAAAAA', 'SC': '#999999', 'CS': '#666666',
}
PITCH_FULL_NAMES = {
    'FF': 'Four-Seam', 'SI': 'Sinker', 'FC': 'Cutter', 'SL': 'Slider',
    'ST': 'Sweeper', 'SV': 'Slurve', 'CU': 'Curveball', 'CH': 'Changeup',
    'FS': 'Splitter', 'KN': 'Knuckleball', 'SC': 'Screwball', 'CS': 'Slow Curve',
}

# Dark theme palette
BG_COLOR = '#0f172a'
GRID_COLOR = '#334155'
TEXT_COLOR = '#e2e8f0'
AXIS_COLOR = '#475569'


# ────────────────────────────────────────────────────────────────────────
# Data loading
# ────────────────────────────────────────────────────────────────────────

def load_arsenals():
    """Return a dict: (pitcher, team) -> {pitch_type: row, 'throws': hand}."""
    with (DATA_DIR / 'pitch_leaderboard_rs.json').open() as f:
        rows = json.load(f)
    arsenals = defaultdict(dict)
    for r in rows:
        key = (r['pitcher'], r['team'])
        pt = r['pitchType']
        arsenals[key][pt] = r
        # Store throws once per pitcher
        arsenals[key]['_throws'] = r.get('throws')
    return dict(arsenals)


def extract_vec(row, fields):
    """Pull a float vector from a row in field order. Returns None if any are missing."""
    vec = []
    for f in fields:
        v = row.get(f)
        if v is None:
            return None
        vec.append(float(v))
    return np.array(vec)


# ────────────────────────────────────────────────────────────────────────
# MVN conditional distribution
# ────────────────────────────────────────────────────────────────────────

def mvn_conditional(mu, cov, x_a, d_a):
    """Standard MVN conditional: given observed values x_a for the first d_a
    dimensions, return (mu_b_given_a, cov_b_given_a) for the remaining dims.
    """
    mu_a = mu[:d_a]
    mu_b = mu[d_a:]
    cov_aa = cov[:d_a, :d_a]
    cov_ab = cov[:d_a, d_a:]
    cov_ba = cov[d_a:, :d_a]
    cov_bb = cov[d_a:, d_a:]

    # Use solve instead of inv for numerical stability
    # cov_ba @ inv(cov_aa) @ (x_a - mu_a)
    delta = x_a - mu_a
    z = np.linalg.solve(cov_aa, delta)
    mu_b_given_a = mu_b + cov_ba @ z

    # cov_bb - cov_ba @ inv(cov_aa) @ cov_ab
    K = np.linalg.solve(cov_aa, cov_ab)
    cov_b_given_a = cov_bb - cov_ba @ K

    return mu_b_given_a, cov_b_given_a


def mahalanobis_dist_batch(X, x_target, cov_aa):
    """Mahalanobis distance from each row of X to x_target under cov_aa."""
    diffs = X - x_target
    # d^2 = diff^T @ inv(cov_aa) @ diff for each row
    solved = np.linalg.solve(cov_aa, diffs.T).T  # (n, d)
    d2 = np.sum(diffs * solved, axis=1)
    d2 = np.clip(d2, 0, None)  # guard against tiny negatives from float error
    return np.sqrt(d2)


# ────────────────────────────────────────────────────────────────────────
# Training matrix construction
# ────────────────────────────────────────────────────────────────────────

def pick_anchor(arsenal):
    """FF if available with count >= MIN_COUNT, else SI, else None."""
    for pt in ('FF', 'SI'):
        r = arsenal.get(pt)
        if r and (r.get('count') or 0) >= MIN_COUNT:
            return pt
    return None


def build_feature_vector(arsenal, anchor, other_pitches, target_pt):
    """Concatenate [biomech (from anchor row), anchor metrics, other_pitches metrics in order, target metrics]."""
    anchor_row = arsenal.get(anchor)
    if not anchor_row:
        return None
    biomech = extract_vec(anchor_row, BIOMECH)
    if biomech is None:
        return None
    anchor_m = extract_vec(anchor_row, PITCH_METRICS)
    if anchor_m is None:
        return None
    others_m = []
    for op in other_pitches:
        r = arsenal.get(op)
        if not r or (r.get('count') or 0) < MIN_COUNT:
            return None
        m = extract_vec(r, PITCH_METRICS)
        if m is None:
            return None
        others_m.append(m)
    target_row = arsenal.get(target_pt)
    if not target_row or (target_row.get('count') or 0) < MIN_COUNT:
        return None
    target_m = extract_vec(target_row, TARGET_METRICS)
    if target_m is None:
        return None

    parts = [biomech, anchor_m]
    for m in others_m:
        parts.append(m)
    parts.append(target_m)
    return np.concatenate(parts)


def assemble_training_matrix(arsenals, anchor, other_pitches, target_pt, hand, exclude_key=None):
    """Build the (n, d) training matrix for the specified conditioning scheme.

    Returns:
        X: (n, d) matrix of feature vectors
        train_keys: list of (pitcher, team) tuples in row order
    """
    X = []
    keys = []
    for key, arsenal in arsenals.items():
        if key == exclude_key:
            continue
        if arsenal.get('_throws') != hand:
            continue
        vec = build_feature_vector(arsenal, anchor, other_pitches, target_pt)
        if vec is None:
            continue
        X.append(vec)
        keys.append(key)
    if not X:
        return np.empty((0, 0)), []
    return np.vstack(X), keys


def fit_mvn(X):
    """Return (mean, covariance) of X. Uses ddof=1."""
    mu = X.mean(axis=0)
    cov = np.cov(X, rowvar=False, ddof=1)
    # If X has a single row, cov is 0-d; make it 2-d
    cov = np.atleast_2d(cov)
    # Ridge regularizer for numerical stability
    d = cov.shape[0]
    cov = cov + 1e-6 * np.eye(d)
    return mu, cov


# ────────────────────────────────────────────────────────────────────────
# Prediction (one tier, one target pitch)
# ────────────────────────────────────────────────────────────────────────

def predict(arsenals, target_key, anchor, other_pitches, target_pt):
    """Fit MVN and condition. Returns dict with keys mu_b, cov_b, n_train, comps, x_a.
    Returns None if training sample is insufficient.
    """
    target_arsenal = arsenals[target_key]
    hand = target_arsenal.get('_throws')
    X, train_keys = assemble_training_matrix(
        arsenals, anchor, other_pitches, target_pt, hand,
        exclude_key=target_key,
    )
    n_train = X.shape[0]
    d_a = len(BIOMECH) + len(PITCH_METRICS) * (1 + len(other_pitches))
    d_b = len(TARGET_METRICS)
    # Need at least d_a + d_b rows for invertible cov, with a safety margin
    min_needed = max(d_a + d_b + 10, TIER2_MIN_TRAIN if other_pitches else 30)
    if n_train < min_needed:
        return {'insufficient': True, 'n_train': n_train, 'min_needed': min_needed,
                'other_pitches': other_pitches, 'anchor': anchor, 'target': target_pt}

    # Build the target pitcher's x_a (conditioning block from arsenal)
    anchor_row = target_arsenal.get(anchor)
    if not anchor_row:
        return None
    biomech = extract_vec(anchor_row, BIOMECH)
    anchor_m = extract_vec(anchor_row, PITCH_METRICS)
    if biomech is None or anchor_m is None:
        return None
    x_a_parts = [biomech, anchor_m]
    for op in other_pitches:
        op_row = target_arsenal.get(op)
        if not op_row or (op_row.get('count') or 0) < MIN_COUNT:
            return None
        m = extract_vec(op_row, PITCH_METRICS)
        if m is None:
            return None
        x_a_parts.append(m)
    x_a = np.concatenate(x_a_parts)

    mu, cov = fit_mvn(X)
    mu_b, cov_b = mvn_conditional(mu, cov, x_a, d_a)

    # Mahalanobis comps in the conditioning space
    X_a_only = X[:, :d_a]
    _, cov_aa_only = mu[:d_a], cov[:d_a, :d_a]
    dists = mahalanobis_dist_batch(X_a_only, x_a, cov_aa_only)
    order = np.argsort(dists)
    comps = []
    for idx in order[:N_COMPS]:
        ck = train_keys[idx]
        carsenal = arsenals[ck]
        tm = extract_vec(carsenal[target_pt], TARGET_METRICS)
        comps.append({
            'pitcher': ck[0],
            'team': ck[1],
            'distance': float(dists[idx]),
            'metrics': tm.tolist() if tm is not None else None,
        })

    return {
        'mu_b': mu_b,
        'cov_b': cov_b,
        'n_train': n_train,
        'comps': comps,
        'x_a': x_a,
        'd_a': d_a,
    }


# ────────────────────────────────────────────────────────────────────────
# Pretty printing
# ────────────────────────────────────────────────────────────────────────

def fmt_pitch(row):
    v = row.get('velocity')
    iv = row.get('indVertBrk')
    hb = row.get('horzBrk')
    n = row.get('count')
    return (f"{v:5.1f} mph  {iv:5.1f}\" IVB  {hb:5.1f}\" HB  (n={n})")


def fmt_prediction(mu_b, cov_b):
    sigmas = np.sqrt(np.diag(cov_b))
    v = mu_b[TARGET_METRICS.index('velocity')]
    iv = mu_b[TARGET_METRICS.index('indVertBrk')]
    hb = mu_b[TARGET_METRICS.index('horzBrk')]
    sv = sigmas[TARGET_METRICS.index('velocity')]
    siv = sigmas[TARGET_METRICS.index('indVertBrk')]
    shb = sigmas[TARGET_METRICS.index('horzBrk')]
    return (f"{v:5.1f} +/- {sv:3.1f} mph   "
            f"{iv:5.1f} +/- {siv:3.1f}\" IVB   "
            f"{hb:5.1f} +/- {shb:3.1f}\" HB")


def print_report(target_key, arsenals, anchor, other_existing, targets, tier_results):
    name, team = target_key
    arsenal = arsenals[target_key]
    hand = arsenal.get('_throws')
    anchor_row = arsenal.get(anchor)
    arm_angle = anchor_row.get('armAngle')
    ext = anchor_row.get('extension')

    print()
    print(f"{name}, {team} ({hand}HP)")
    print(f"  arm angle {arm_angle:.1f} deg, extension {ext:.1f} ft   "
          f"[anchor: {anchor}]")
    print()
    print(f"  Current arsenal (2026):")
    for pt in sorted(arsenal.keys(), key=lambda k: -(arsenal[k].get('count') or 0)
                     if isinstance(arsenal[k], dict) else 1):
        if pt.startswith('_'):
            continue
        r = arsenal[pt]
        if not isinstance(r, dict) or (r.get('count') or 0) < MIN_COUNT:
            continue
        print(f"    {pt:3s}  {fmt_pitch(r)}")

    for tier_label, results in tier_results.items():
        print()
        desc = (f"anchored on {anchor}" if tier_label == 'Tier 1'
                else f"{anchor} + {', '.join(other_existing)}" if other_existing
                else f"anchored on {anchor}")
        print(f"  {tier_label} predictions ({desc}):")
        for t in targets:
            res = results.get(t)
            if res is None:
                print(f"    {t:3s}  [skipped: target is the anchor pitch]")
                continue
            if res.get('insufficient'):
                combo = ' + '.join([res['anchor']] + res.get('other_pitches', []) + [res['target']])
                print(f"    {t:3s}  [skipped: only {res['n_train']} pitchers throw "
                      f"{combo} (need {res['min_needed']})]")
                continue
            line = f"    {t:3s}  {fmt_prediction(res['mu_b'], res['cov_b'])}   [n_train={res['n_train']}]"
            print(line)

        has_any_comps = any(
            r and not r.get('insufficient') for r in results.values()
        )
        if not has_any_comps:
            continue
        print(f"\n    Top {N_COMPS} Mahalanobis comps per target:")
        for t in targets:
            res = results.get(t)
            if res is None or res.get('insufficient'):
                continue
            print(f"      {t}:")
            for c in res['comps']:
                if c['metrics'] is None:
                    continue
                cv = c['metrics'][TARGET_METRICS.index('velocity')]
                civ = c['metrics'][TARGET_METRICS.index('indVertBrk')]
                chb = c['metrics'][TARGET_METRICS.index('horzBrk')]
                print(f"        d={c['distance']:4.2f}  {c['pitcher']:<28s} ({c['team']})  "
                      f"{cv:5.1f} mph  {civ:5.1f}\" IVB  {chb:5.1f}\" HB")


# ────────────────────────────────────────────────────────────────────────
# Plotting
# ────────────────────────────────────────────────────────────────────────

def plot_cov_ellipse(ax, center, cov2, n_sigma=1, **kwargs):
    """Plot n-sigma ellipse for a 2x2 covariance."""
    vals, vecs = np.linalg.eigh(cov2)  # ascending eigenvalues
    major_vec = vecs[:, 1]
    angle = np.degrees(np.arctan2(major_vec[1], major_vec[0]))
    width = 2 * n_sigma * np.sqrt(max(vals[1], 0))
    height = 2 * n_sigma * np.sqrt(max(vals[0], 0))
    e = Ellipse(xy=center, width=width, height=height, angle=angle, **kwargs)
    ax.add_patch(e)


def _style_plot_axes(ax):
    """Apply the dark Movement-Profile look to an axes."""
    ax.set_facecolor(BG_COLOR)
    ax.set_xlim(-25, 25)
    ax.set_ylim(-25, 25)
    ax.set_aspect('equal')
    ax.axhline(0, color=TEXT_COLOR, ls='--', lw=0.7, alpha=0.45, zorder=1)
    ax.axvline(0, color=TEXT_COLOR, ls='--', lw=0.7, alpha=0.45, zorder=1)
    ax.grid(True, color=GRID_COLOR, lw=0.5, alpha=0.7, zorder=0)
    ax.set_xticks(range(-25, 26, 5))
    ax.set_yticks(range(-25, 26, 5))
    for sp in ax.spines.values():
        sp.set_color(AXIS_COLOR)
    ax.tick_params(colors=TEXT_COLOR, labelsize=9)
    ax.set_xlabel('Horizontal Break (in)', color=TEXT_COLOR, fontsize=10)
    ax.set_ylabel('Induced Vertical Break (in)', color=TEXT_COLOR, fontsize=10)


def _plot_arsenal_panel(ax, target_arsenal, targets, results, panel_label):
    """Plot current pitches as solid dots, predicted pitches as hatched ellipses."""
    _style_plot_axes(ax)

    # Current arsenal: solid colored dots with pitch-type label
    for pt, row in target_arsenal.items():
        if pt.startswith('_') or not isinstance(row, dict):
            continue
        if (row.get('count') or 0) < MIN_COUNT:
            continue
        ivb = row.get('indVertBrk')
        hb = row.get('horzBrk')
        if ivb is None or hb is None:
            continue
        color = PITCH_COLORS.get(pt, '#999')
        ax.scatter(hb, ivb, s=240, color=color, edgecolor='#000',
                   linewidths=0.6, zorder=5)
        ax.text(hb, ivb, pt, fontsize=8, fontweight='bold', ha='center',
                va='center', color='#000' if pt in ('SL', 'SI', 'FC') else '#ffffff',
                zorder=6)

    # Predictions: hatched ellipses plus small "+T" marker at center
    for t in targets:
        res = results.get(t)
        if res is None or res.get('insufficient'):
            continue
        mu = res['mu_b']
        cov = res['cov_b']
        ivb_hat = mu[TARGET_METRICS.index('indVertBrk')]
        hb_hat = mu[TARGET_METRICS.index('horzBrk')]
        idx_ivb = TARGET_METRICS.index('indVertBrk')
        idx_hb = TARGET_METRICS.index('horzBrk')
        cov2 = np.array([
            [cov[idx_hb, idx_hb], cov[idx_hb, idx_ivb]],
            [cov[idx_ivb, idx_hb], cov[idx_ivb, idx_ivb]],
        ])
        color = PITCH_COLORS.get(t, '#999')
        plot_cov_ellipse(
            ax, (hb_hat, ivb_hat), cov2, n_sigma=1,
            facecolor=color, alpha=0.25, hatch='///', edgecolor=color, lw=1.2,
            zorder=4,
        )
        ax.text(hb_hat, ivb_hat, t, fontsize=8, fontweight='bold', ha='center',
                va='center', color='#000' if t in ('SL', 'SI', 'FC') else '#ffffff',
                zorder=6,
                bbox=dict(boxstyle='round,pad=0.2', fc=color, ec='none', alpha=0.9))

    ax.set_title(panel_label, color=TEXT_COLOR, fontsize=11, fontweight='bold',
                 loc='left', pad=8)


def plot_predictions(target_key, arsenal, targets, tier_results, out_path):
    """Two-panel plot plus shared metrics table, styled to match the site's
    Movement Profile card (dark theme, -25..25 axes, dashed crosshair, legend
    pills, pitch-type color coding).
    """
    fig = plt.figure(figsize=(14, 11), facecolor=BG_COLOR)
    gs = fig.add_gridspec(
        nrows=2, ncols=2, height_ratios=[3, 1.2],
        hspace=0.25, wspace=0.15,
        left=0.06, right=0.97, top=0.92, bottom=0.05,
    )
    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1])
    ax_table = fig.add_subplot(gs[1, :])

    panel_descs = {
        'Tier 1': 'Tier 1: anchor-only (FF or SI)',
        'Tier 2': 'Tier 2: full-arsenal conditioning',
    }
    _plot_arsenal_panel(ax1, arsenal, targets, tier_results.get('Tier 1', {}),
                        panel_descs['Tier 1'])
    _plot_arsenal_panel(ax2, arsenal, targets, tier_results.get('Tier 2', {}),
                        panel_descs['Tier 2'])

    if not any(r and not r.get('insufficient')
               for r in tier_results.get('Tier 2', {}).values()):
        ax2.text(0, 24, '(no predictions: insufficient training sample)',
                 fontsize=9, color='#94a3b8', ha='center', va='top')

    # Build table rows: current arsenal first (sorted by count desc), then
    # predictions ordered by tier then input order of target pitches.
    table_rows = []
    current_sorted = sorted(
        ((pt, r) for pt, r in arsenal.items()
         if not pt.startswith('_') and isinstance(r, dict)
         and (r.get('count') or 0) >= MIN_COUNT),
        key=lambda kv: -(kv[1].get('count') or 0),
    )
    for pt, r in current_sorted:
        table_rows.append({
            'pitch': pt, 'kind': 'current',
            'mph': r.get('velocity'),
            'ivb': r.get('indVertBrk'),
            'hb': r.get('horzBrk'),
        })
    # Prefer T2 (sharper estimate) when available; fall back to T1 if T2 is
    # unavailable for that target. The two-panel plot above already shows the
    # T1 vs T2 split visually, so the table only needs the best estimate per pitch.
    t1_results = tier_results.get('Tier 1', {})
    t2_results = tier_results.get('Tier 2', {})
    for t in targets:
        t2 = t2_results.get(t)
        t1 = t1_results.get(t)
        if t2 and not t2.get('insufficient'):
            res = t2
            tier_suffix = ' (T2)'
        elif t1 and not t1.get('insufficient'):
            res = t1
            tier_suffix = ' (T1)'
        else:
            continue
        mu = res['mu_b']
        table_rows.append({
            'pitch': t, 'kind': 'predicted',
            'tier_suffix': tier_suffix,
            'mph': mu[TARGET_METRICS.index('velocity')],
            'ivb': mu[TARGET_METRICS.index('indVertBrk')],
            'hb': mu[TARGET_METRICS.index('horzBrk')],
        })

    _draw_arsenal_table(ax_table, table_rows)

    name, team = target_key
    hand = arsenal.get('_throws')
    anchor_row = next((r for pt, r in arsenal.items()
                       if not pt.startswith('_') and isinstance(r, dict)
                       and (r.get('count') or 0) >= MIN_COUNT
                       and pt in ('FF', 'SI')), None)
    arm_angle = anchor_row.get('armAngle') if anchor_row else None

    title = f"{name}, {team}   {hand}HP"
    subtitle = "* = predicted new pitch   |   hatched region = 1-sigma uncertainty"
    if arm_angle is not None:
        subtitle = f"Arm Angle = {arm_angle:.1f}°   |   " + subtitle
    fig.text(0.06, 0.965, 'MOVEMENT PROFILE', color='#67e8f9', fontsize=13,
             fontweight='bold', ha='left', va='center')
    fig.text(0.06, 0.94, title, color=TEXT_COLOR, fontsize=14,
             fontweight='bold', ha='left', va='center')
    fig.text(0.97, 0.965, subtitle, color='#94a3b8', fontsize=9,
             ha='right', va='center')

    fig.savefig(out_path, dpi=140, facecolor=BG_COLOR)
    plt.close(fig)


def _draw_arsenal_table(ax, rows):
    """Render the metrics table (PITCH | MPH | IVB | HB) with colored pill
    badges for pitch labels and tier suffixes on predicted rows."""
    ax.set_facecolor(BG_COLOR)
    ax.axis('off')
    if not rows:
        return

    headers = ['PITCH', 'MPH', 'IVB', 'HB']
    col_x = [0.12, 0.38, 0.60, 0.82]

    y_header = 0.95
    for x, h in zip(col_x, headers):
        ax.text(x, y_header, h, color='#67e8f9', fontsize=11, fontweight='bold',
                ha='center', va='center', transform=ax.transAxes)
    ax.plot([0.05, 0.95], [0.86, 0.86], color=GRID_COLOR, lw=0.7,
            transform=ax.transAxes, clip_on=False)

    n_rows = len(rows)
    row_height = 0.82 / max(n_rows, 1)
    for i, r in enumerate(rows):
        y = 0.82 - (i + 0.5) * row_height
        pt = r['pitch']
        label = pt + (r.get('tier_suffix') or '') + ('*' if r['kind'] == 'predicted' else '')
        color = PITCH_COLORS.get(pt, '#999')
        text_color = '#000000' if pt in ('SL', 'SI', 'FC') else '#ffffff'
        ax.text(col_x[0], y, label, color=text_color, fontsize=10, fontweight='bold',
                ha='center', va='center', transform=ax.transAxes,
                bbox=dict(boxstyle='round,pad=0.35', fc=color, ec=color, lw=0))
        for x, key in zip(col_x[1:], ['mph', 'ivb', 'hb']):
            val = r[key]
            if val is None:
                txt = '—'
            elif key == 'mph':
                txt = f"{val:.1f}"
            else:
                txt = f"{val:.1f}\""
            ax.text(x, y, txt, color=TEXT_COLOR, fontsize=10,
                    ha='center', va='center', transform=ax.transAxes)


# ────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────

def main():
    # ── Settings (edit these directly or override via command line) ──
    pitcher  = "Beeter, Clayton"   # Pitcher name, "Last, First" format
    team     = "WSH"                 # Team abbreviation
    pitches  = ["SI", "CU", "CH"]          # Target pitch types to predict (e.g., ["CU","SI","CH"])

    tier      = "both"               # "1", "2", or "both"
    no_plot   = False                # True to skip plot generation
    plot_only = False                # True to write plot but skip printed text

    # ── CLI overrides (optional — values above are used if no args passed) ──
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    parser.add_argument('pitcher', nargs='?', default=None,
                        help='Pitcher name, "Last, First" format')
    parser.add_argument('team', nargs='?', default=None,
                        help='Team abbreviation, e.g. WSH')
    parser.add_argument('pitches', nargs='*',
                        help='Target pitch types to predict (e.g., CU SI CH)')
    parser.add_argument('--tier', choices=['1', '2', 'both'], default=None,
                        help='Which tier(s) to run')
    parser.add_argument('--no-plot', action='store_true', default=None,
                        help='Skip plot generation')
    parser.add_argument('--plot-only', action='store_true', default=None,
                        help='Write plot but skip printed text')
    args = parser.parse_args()

    if args.pitcher is not None: pitcher = args.pitcher
    if args.team is not None: team = args.team
    if args.pitches: pitches = args.pitches
    if args.tier is not None: tier = args.tier
    if args.no_plot: no_plot = True
    if args.plot_only: plot_only = True

    arsenals = load_arsenals()
    target_key = (pitcher, team)
    if target_key not in arsenals:
        print(f"Error: pitcher {pitcher} on team {team} not found.", file=sys.stderr)
        # Suggest close matches
        close = [k for k in arsenals if pitcher.lower() in k[0].lower() and k[1] == team]
        if close:
            print("  Closest name matches on this team:", file=sys.stderr)
            for k in close[:5]:
                print(f"    '{k[0]}'", file=sys.stderr)
        sys.exit(1)

    target_arsenal = arsenals[target_key]
    anchor = pick_anchor(target_arsenal)
    if not anchor:
        print(f"Error: {pitcher} has no FF or SI with >={MIN_COUNT} pitches; "
              "cannot anchor prediction.", file=sys.stderr)
        sys.exit(1)

    # Determine other existing pitches (for Tier 2)
    existing = [
        pt for pt, r in target_arsenal.items()
        if (not pt.startswith('_'))
        and isinstance(r, dict)
        and (r.get('count') or 0) >= MIN_COUNT
    ]
    other_existing_full = [pt for pt in existing if pt != anchor]

    tier_results = {}
    for t_iter in (['1', '2'] if tier == 'both' else [tier]):
        tier_label = f"Tier {t_iter}"
        others = [] if t_iter == '1' else [p for p in other_existing_full if p not in pitches]
        results = {}
        for t in pitches:
            if t == anchor:
                print(f"Note: {t} is the anchor pitch; skipping prediction for it.",
                      file=sys.stderr)
                results[t] = None
                continue
            res = predict(arsenals, target_key, anchor, others, t)
            results[t] = res
        tier_results[tier_label] = results

    if not plot_only:
        print_report(target_key, arsenals, anchor, other_existing_full,
                     pitches, tier_results)

    if not no_plot:
        name_slug = pitcher.replace(', ', '_').replace(' ', '_').replace("'", '')
        pitches_slug = '_'.join(pitches)
        out_path = OUTPUT_DIR / f"{name_slug}_{team}_{pitches_slug}.png"
        plot_predictions(target_key, target_arsenal, pitches, tier_results, out_path)
        if not plot_only:
            print(f"\n  plot: {out_path}")


if __name__ == '__main__':
    main()
