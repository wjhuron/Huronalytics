"""Batch pose extraction + feature aggregation across many pitch clips.

Takes a directory of clips (from fetch_clips.py, filenames like
<PitchID>.mp4), runs MediaPipe Pose on each, aligns features on release,
validates clip quality, and emits one row per valid clip to a CSV.

Drops clips where:
  - pose detection fails on too many frames
  - the camera cut in late (no stable pre-delivery plateau at start)
  - release frame is not detectable or falls too close to the start

Usage:
    python3 biomech/batch_pose.py \
        --clips-dir biomech/clips \
        --context biomech/out/pitches_miles_mikolas_on.csv \
        --handedness RHP \
        --output biomech/out/mikolas_pose_features.csv
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import cv2
import numpy as np

import pose_pipeline as pp  # sibling module

REPO = Path(__file__).resolve().parents[1]

# How many frames (@ ~60 fps) = how many seconds
PRE_DELIVERY_SETTLE_FRAMES = 18   # ~300ms; clip must be settled for at least this long at start
LEG_LIFT_SETTLE_THRESHOLD = 0.15  # torso-norm; leg_lift above this during settle window = clip cut in late
MIN_DETECTED_FRAME_FRAC = 0.8     # require pose detected on ≥80% of frames
MIN_RELEASE_FRAME = 30            # release must be at least this far into the clip (else set wasn't captured)

# Sample the trajectory at these offsets before release (frames @ 60 fps)
SAMPLE_OFFSETS_FRAMES = [0, 6, 12, 18, 30]    # 0ms, 100ms, 200ms, 300ms, 500ms before release


def load_context(context_csv: Path | None) -> dict[str, dict]:
    if context_csv is None:
        return {}
    out = {}
    with context_csv.open() as f:
        for row in csv.DictReader(f):
            pid = row.get("PitchID")
            if pid:
                out[pid] = row
    return out


def find_delivery_window(
    features: list[dict],
    release_frame: int,
    max_delivery_frames: int = 120,  # ~2s at 60fps — upper bound on a full delivery
) -> tuple[int | None, int | None]:
    """Walk backward from release to find (leg_peak_frame, set_frame).

    Savant clips for pitches with runners on base often contain several seconds
    of prior-play footage before the CF broadcast cut to the pitcher. We find
    the ACTUAL delivery window by searching backward from release_frame — the
    leg_lift peak is the top of the leg kick, and the set position is the
    stable plateau immediately before leg_lift starts rising.

    Returns (None, None) if we can't resolve a valid window.
    """
    leg_lift = np.array([f["leg_lift_norm"] for f in features], dtype=float)
    leg_smooth = pp._nan_smooth(leg_lift, window=9)

    # search window: up to max_delivery_frames before release
    ws = max(0, release_frame - max_delivery_frames)
    segment = leg_smooth[ws:release_frame]
    if len(segment) == 0 or np.all(np.isnan(segment)):
        return None, None

    leg_peak_rel = int(np.nanargmax(segment))
    leg_peak_frame = ws + leg_peak_rel
    if not np.isfinite(leg_smooth[leg_peak_frame]):
        return None, None
    # Require a meaningful leg lift (guards against noise peaks)
    if leg_smooth[leg_peak_frame] < 0.4:
        return None, None

    return leg_peak_frame, max(0, leg_peak_frame - PRE_DELIVERY_SETTLE_FRAMES)


def validate_clip(
    frames: list[list[dict] | None],
    features: list[dict],
    release_frame: int | None,
) -> tuple[bool, str, dict]:
    """Return (is_valid, reason_if_not, extras). extras includes leg_peak_frame."""
    n = len(features)
    extras: dict = {}

    if release_frame is None:
        return False, "no_release_detected", extras
    if release_frame < MIN_RELEASE_FRAME:
        return False, f"release_too_early (frame {release_frame})", extras

    # Find delivery window (leg_peak and set position) by walking back from release
    leg_peak_frame, settle_start = find_delivery_window(features, release_frame)
    if leg_peak_frame is None:
        return False, "no_leg_lift_peak_before_release", extras
    extras["leg_peak_frame"] = leg_peak_frame

    # Require pose detection on the delivery window (set → release)
    window_frames = frames[settle_start:release_frame + 1]
    detected_in_window = sum(1 for f in window_frames if f is not None) / max(1, len(window_frames))
    if detected_in_window < MIN_DETECTED_FRAME_FRAC:
        return False, f"pose_detected_in_delivery={detected_in_window:.2f}", extras

    # Plateau check: immediately before leg-lift peak, leg_lift should be ≈ 0
    settle = np.array(
        [f["leg_lift_norm"] for f in features[settle_start:leg_peak_frame]],
        dtype=float,
    )
    settle = settle[~np.isnan(settle)]
    if len(settle) < PRE_DELIVERY_SETTLE_FRAMES // 2:
        return False, "no_pose_in_pre_delivery_window", extras
    if np.max(np.abs(settle)) > LEG_LIFT_SETTLE_THRESHOLD:
        return False, f"no_stable_plateau (|leg_lift| max={np.max(np.abs(settle)):.2f})", extras

    return True, "", extras


def sample_feature_at_offset(
    features: list[dict],
    release_frame: int,
    offset_frames: int,
    key: str,
) -> float:
    idx = release_frame - offset_frames
    if idx < 0 or idx >= len(features):
        return float("nan")
    v = features[idx].get(key, float("nan"))
    return float(v) if v is not None else float("nan")


def process_one(
    clip_path: Path,
    hand: pp.Handedness,
) -> tuple[dict | None, str]:
    """Run the pipeline on one clip. Returns (row_dict, drop_reason).
    row_dict is None if clip was invalid."""
    try:
        frames, meta = pp.extract_landmarks(clip_path)
    except Exception as e:
        return None, f"extract_failed: {e}"

    features = pp.compute_features(frames, meta, hand)
    release = pp.detect_release_frame(frames, features, hand)

    valid, reason, extras = validate_clip(frames, features, release)
    if not valid:
        return None, reason

    assert release is not None
    leg_peak = extras["leg_peak_frame"]
    row: dict = {
        "PitchID": clip_path.stem,
        "n_frames": meta["n_frames"],
        "fps": round(meta["fps"], 2),
        "release_frame": release,
        "release_t_s": round(features[release]["t"], 3),
        "leg_peak_frame": leg_peak,
        "leg_peak_value": round(float(features[leg_peak]["leg_lift_norm"]), 3),
        "tempo_leg_to_release_frames": release - leg_peak,
        "tempo_leg_to_release_s": round((release - leg_peak) / meta["fps"], 3),
    }

    # Sample features at offsets pre-release
    for key in ("glove_height_norm", "leg_lift_norm", "arm_slot_deg",
                "hip_shoulder_sep_deg", "spine_tilt_deg",
                "throwing_wrist_x", "throwing_wrist_y"):
        for off in SAMPLE_OFFSETS_FRAMES:
            label = f"{key}_t-{off}f"
            row[label] = round(
                sample_feature_at_offset(features, release, off, key), 4
            )

    return row, ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips-dir", required=True)
    ap.add_argument("--context", default=None,
                    help="CSV to pass through (e.g. pull_pitches.py output) "
                         "— rows matched on PitchID. Columns merged into output.")
    ap.add_argument("--handedness", default="RHP", choices=["RHP", "LHP"])
    ap.add_argument("--output", required=True,
                    help="output CSV (one row per valid clip)")
    ap.add_argument("--drops-output", default=None,
                    help="optional CSV listing dropped clips + reasons")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    clips_dir = Path(args.clips_dir)
    clips = sorted(clips_dir.glob("*.mp4"))
    if args.limit:
        clips = clips[: args.limit]
    print(f"{len(clips)} clips in {clips_dir}")

    context = load_context(Path(args.context)) if args.context else {}
    if context:
        print(f"  {len(context)} context rows loaded from {args.context}")

    hand = pp.RHP if args.handedness == "RHP" else pp.LHP

    rows = []
    drops = []
    reason_counts: dict[str, int] = {}
    for i, clip in enumerate(clips, 1):
        row, reason = process_one(clip, hand)
        if row is None:
            drops.append({"PitchID": clip.stem, "reason": reason})
            reason_counts[reason.split(" ")[0] if " " in reason else reason] = \
                reason_counts.get(reason.split(" ")[0] if " " in reason else reason, 0) + 1
            print(f"[{i}/{len(clips)}] DROP {clip.name}: {reason}")
            continue
        # merge context
        if row["PitchID"] in context:
            ctx = context[row["PitchID"]]
            for k in ("Pitch Type", "Game Date", "Count", "Runners", "Outs", "Batter", "Bats"):
                if k in ctx:
                    row[k] = ctx[k]
        rows.append(row)
        print(f"[{i}/{len(clips)}] {clip.name} -> release frame {row['release_frame']}")

    # write output CSV
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        keys = list(rows[0].keys())
        # make sure all rows have same keys (use union to be safe)
        all_keys = list(dict.fromkeys(k for r in rows for k in r.keys()))
        with out_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=all_keys)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in all_keys})
        print(f"\nwrote {len(rows)} rows -> {out_path}")

    if args.drops_output and drops:
        drops_path = Path(args.drops_output)
        drops_path.parent.mkdir(parents=True, exist_ok=True)
        with drops_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["PitchID", "reason"])
            w.writeheader()
            w.writerows(drops)
        print(f"wrote {len(drops)} drops -> {drops_path}")

    print(f"\nsummary: {len(rows)} valid  /  {len(drops)} dropped  /  {len(clips)} total")
    if reason_counts:
        print("drop reasons:")
        for r, c in sorted(reason_counts.items(), key=lambda x: -x[1]):
            print(f"  {c:3d}  {r}")


if __name__ == "__main__":
    main()
