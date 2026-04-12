#!/usr/bin/env python3
"""
Detect outlier pitches in ST 2026 data for Spin Rate, Extension, RelZ, RelX.
Uses per-pitcher per-pitch-type statistics to flag anomalies.
Outputs a structured dict for docx generation.
"""

import gspread
from google.oauth2.service_account import Credentials
import os
import time as time_module
import json
import math
from collections import defaultdict

SPREADSHEET_ID = '1hNILKCGBuyQKV6KPWawgkS1cu72672TBALi8iNBbIFo'
SERVICE_ACCOUNT_FILE = os.path.join(os.path.dirname(__file__), 'service_account.json')

MLB_TEAMS = {
    'ARI', 'ATH', 'ATL', 'BAL', 'BOS', 'CHC', 'CIN', 'CLE', 'COL', 'CWS',
    'DET', 'HOU', 'KCR', 'LAA', 'LAD', 'MIA', 'MIL', 'MIN', 'NYM', 'NYY',
    'PHI', 'PIT', 'SDP', 'SEA', 'SFG', 'STL', 'TBR', 'TEX', 'TOR', 'WSH',
}

# Metrics to check for outliers
OUTLIER_METRICS = {
    'Spin Rate': {'col': 'Spin Rate', 'unit': 'RPM', 'round': 0},
    'Extension': {'col': 'Extension', 'unit': 'ft', 'round': 2},
    'Release Height': {'col': 'RelPosZ', 'unit': 'ft', 'round': 2},
    'Release Side': {'col': 'RelPosX', 'unit': 'ft', 'round': 2},
}

# Context-dependent thresholds per metric
# For small samples we need wider tolerance; for large samples we can be stricter
# Z-score thresholds: "confident" vs "questionable"
CONFIDENT_Z = 3.0      # >= 3 standard deviations = confident outlier
QUESTIONABLE_Z = 2.2    # >= 2.2 but < 3 = questionable

# Minimum pitches needed to compute reliable stats for a pitcher-pitch-type
MIN_PITCHES_FOR_ANALYSIS = 5

# Additional context: absolute deviation thresholds to avoid flagging normal variation
# If the absolute deviation is smaller than these, don't flag even if z-score is high
# (prevents flagging e.g. a 2201 spin when avg is 2200 with very low variance)
MIN_ABSOLUTE_DEV = {
    'Spin Rate': 200,      # at least 200 RPM deviation to be worth flagging
    'Extension': 0.4,      # at least 0.4 ft
    'Release Height': 0.3, # at least 0.3 ft
    'Release Side': 0.3,   # at least 0.3 ft
}

# Spin rate special handling: pitch types with naturally low/variable spin
LOW_SPIN_TYPES = {'FS', 'CH', 'KN'}  # splitters, changeups, knuckleballs have more variance


def read_sheet_with_retry(ws, max_retries=3):
    for attempt in range(max_retries):
        try:
            return ws.get_all_values()
        except gspread.exceptions.APIError as e:
            if '429' in str(e) and attempt < max_retries - 1:
                wait = 30 * (attempt + 1)
                print(f"    Rate limited, waiting {wait}s...")
                time_module.sleep(wait)
            else:
                raise


def safe_float(val):
    if val is None or val == '':
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def compute_iqr_bounds(values, multiplier=1.5):
    """Compute IQR-based outlier bounds."""
    s = sorted(values)
    n = len(s)
    q1 = s[n // 4]
    q3 = s[(3 * n) // 4]
    iqr = q3 - q1
    return q1 - multiplier * iqr, q3 + multiplier * iqr


def detect_outliers(all_pitches):
    """
    For each pitcher-team-pitch_type group, detect outliers in each metric.
    Returns dict: {metric_name: {'confident': [...], 'questionable': [...]}}
    """
    # Group pitches by (pitcher, team, pitch_type)
    groups = defaultdict(list)
    for p in all_pitches:
        pitcher = p.get('Pitcher')
        team = p.get('Team') or p.get('PTeam')
        pt = p.get('Pitch Type')
        if not pitcher or not pt:
            continue
        groups[(pitcher, team, pt)].append(p)

    results = {metric: {'confident': [], 'questionable': []} for metric in OUTLIER_METRICS}

    total_groups = len(groups)
    processed = 0

    for (pitcher, team, pt), pitches in groups.items():
        processed += 1
        if processed % 500 == 0:
            print(f"  Processing group {processed}/{total_groups}...")

        for metric_name, metric_info in OUTLIER_METRICS.items():
            col = metric_info['col']
            rnd = metric_info['round']
            unit = metric_info['unit']

            # Extract valid values for this metric
            values = []
            pitch_data = []  # parallel array with pitch info
            for i, p in enumerate(pitches):
                v = safe_float(p.get(col))
                if v is not None and v != 0:  # 0 often means missing/error for these metrics
                    values.append(v)
                    pitch_data.append((i, v, p))

            if len(values) < MIN_PITCHES_FOR_ANALYSIS:
                continue

            # Compute stats
            mean_val = sum(values) / len(values)
            variance = sum((v - mean_val) ** 2 for v in values) / len(values)
            std_val = math.sqrt(variance) if variance > 0 else 0

            if std_val == 0:
                continue  # all same value, no outliers possible

            # Also compute IQR bounds for cross-validation
            iqr_low, iqr_high = compute_iqr_bounds(values, multiplier=2.0)

            # Compute median for reporting
            sorted_vals = sorted(values)
            median_val = sorted_vals[len(sorted_vals) // 2]

            min_abs_dev = MIN_ABSOLUTE_DEV[metric_name]

            # For low-spin pitch types, raise the min absolute deviation for spin
            if metric_name == 'Spin Rate' and pt in LOW_SPIN_TYPES:
                min_abs_dev = 300  # more tolerance for naturally variable spin types

            for idx, val, pitch in pitch_data:
                z_score = abs(val - mean_val) / std_val
                abs_dev = abs(val - mean_val)

                # Skip if absolute deviation is too small (normal variation)
                if abs_dev < min_abs_dev:
                    continue

                # Must also be outside IQR bounds (cross-validate)
                outside_iqr = val < iqr_low or val > iqr_high

                if z_score >= CONFIDENT_Z and outside_iqr:
                    category = 'confident'
                elif z_score >= QUESTIONABLE_Z and outside_iqr:
                    category = 'questionable'
                else:
                    continue

                # Build outlier record
                game_date = pitch.get('Game Date', 'Unknown')
                velocity = safe_float(pitch.get('Velocity'))
                desc = pitch.get('Description', '')

                record = {
                    'pitcher': pitcher,
                    'team': team or '?',
                    'pitch_type': pt,
                    'metric': metric_name,
                    'value': round(val, rnd),
                    'mean': round(mean_val, rnd),
                    'median': round(median_val, rnd),
                    'std': round(std_val, rnd if rnd > 0 else 1),
                    'z_score': round(z_score, 2),
                    'abs_dev': round(abs_dev, rnd if rnd > 0 else 1),
                    'n_pitches': len(values),
                    'game_date': game_date,
                    'velocity': round(velocity, 1) if velocity else None,
                    'description': desc,
                    'unit': unit,
                }
                results[metric_name][category].append(record)

    # Sort each list by z-score descending (most extreme first)
    for metric_name in results:
        for cat in ('confident', 'questionable'):
            results[metric_name][cat].sort(key=lambda r: r['z_score'], reverse=True)

    return results


def print_summary(results):
    print("\n" + "=" * 80)
    print("OUTLIER DETECTION SUMMARY")
    print("=" * 80)
    for metric_name, cats in results.items():
        n_conf = len(cats['confident'])
        n_quest = len(cats['questionable'])
        print(f"\n{metric_name}:")
        print(f"  Confident outliers:    {n_conf}")
        print(f"  Questionable outliers: {n_quest}")

        if n_conf > 0:
            print(f"  Top 5 confident:")
            for r in cats['confident'][:5]:
                print(f"    {r['pitcher']} ({r['team']}) {r['pitch_type']}: "
                      f"{r['value']} {r['unit']} (avg {r['mean']}, z={r['z_score']}, "
                      f"n={r['n_pitches']}, {r['game_date']})")


def main():
    print("Connecting to Google Sheets...")
    scopes = ['https://www.googleapis.com/auth/spreadsheets.readonly']
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)
    print(f"Spreadsheet: {sh.title}")

    # Read all pitches
    all_pitches = []
    for i, ws in enumerate(sh.worksheets()):
        if ws.title not in MLB_TEAMS:
            print(f"  Skipping {ws.title}")
            continue
        print(f"  Reading {ws.title}...")
        if i > 0:
            time_module.sleep(1.5)
        rows = read_sheet_with_retry(ws)
        if not rows:
            continue
        header = rows[0]
        col_idx = {name: j for j, name in enumerate(header) if name}

        for row in rows[1:]:
            pitcher = row[col_idx['Pitcher']] if 'Pitcher' in col_idx and col_idx['Pitcher'] < len(row) else None
            if not pitcher:
                continue
            pitch = {}
            for col_name, idx in col_idx.items():
                val = row[idx] if idx < len(row) else None
                if val == '':
                    val = None
                pitch[col_name] = val
            # Store team from sheet title
            pitch['Team'] = ws.title
            all_pitches.append(pitch)

    print(f"\nTotal pitches read: {len(all_pitches)}")

    # Detect outliers
    print("\nDetecting outliers...")
    results = detect_outliers(all_pitches)

    print_summary(results)

    # Save results as JSON for docx generation
    output_path = os.path.join(os.path.dirname(__file__), 'outlier_results.json')
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {output_path}")

    return results


if __name__ == '__main__':
    main()
