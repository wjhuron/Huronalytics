"""Pose-extraction pipeline for pitcher biomechanics / tipping analysis.

Input:  path to a single pitch video.
Output (into ./out/<video_stem>_*):
  - keypoints.json    per-frame 33 BlazePose landmarks (normalized 0..1 + z + visibility)
  - features.csv      per-frame biomech features (glove height, leg lift, etc.)
  - overlay.mp4       input video with skeleton + feature readout drawn on each frame
  - metrics.png       time-series plot of features, release frame marked

Usage:
    python3 biomech/pose_pipeline.py path/to/video.mp4
"""

from __future__ import annotations

import csv
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_py
from mediapipe.tasks.python import vision as mp_vision

MODEL_PATH = Path(__file__).parent / "pose_landmarker_heavy.task"

# 33 BlazePose connections (pairs of landmark indices) for skeleton drawing
POSE_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8),
    (9, 10),
    (11, 12), (11, 13), (13, 15), (15, 17), (15, 19), (15, 21), (17, 19),
    (12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (27, 29), (27, 31), (29, 31),
    (24, 26), (26, 28), (28, 30), (28, 32), (30, 32),
]

# BlazePose landmark indices we care about
NOSE = 0
L_SHOULDER, R_SHOULDER = 11, 12
L_ELBOW, R_ELBOW = 13, 14
L_WRIST, R_WRIST = 15, 16
L_HIP, R_HIP = 23, 24
L_KNEE, R_KNEE = 25, 26
L_ANKLE, R_ANKLE = 27, 28


@dataclass
class Handedness:
    """Throws with `throwing` arm, glove on `glove` arm. Indices are into landmark list."""
    throwing_shoulder: int
    throwing_elbow: int
    throwing_wrist: int
    glove_shoulder: int
    glove_elbow: int
    glove_wrist: int
    lead_hip: int     # hip on glove side (lead leg when delivering)
    lead_knee: int
    lead_ankle: int
    trail_hip: int
    trail_knee: int
    trail_ankle: int


RHP = Handedness(
    throwing_shoulder=R_SHOULDER, throwing_elbow=R_ELBOW, throwing_wrist=R_WRIST,
    glove_shoulder=L_SHOULDER, glove_elbow=L_ELBOW, glove_wrist=L_WRIST,
    lead_hip=L_HIP, lead_knee=L_KNEE, lead_ankle=L_ANKLE,
    trail_hip=R_HIP, trail_knee=R_KNEE, trail_ankle=R_ANKLE,
)
LHP = Handedness(
    throwing_shoulder=L_SHOULDER, throwing_elbow=L_ELBOW, throwing_wrist=L_WRIST,
    glove_shoulder=R_SHOULDER, glove_elbow=R_ELBOW, glove_wrist=R_WRIST,
    lead_hip=R_HIP, lead_knee=R_KNEE, lead_ankle=R_ANKLE,
    trail_hip=L_HIP, trail_knee=L_KNEE, trail_ankle=L_ANKLE,
)


# Default crop box for CF broadcast pitcher-only detection.
# (x_min, y_min, x_max, y_max) in normalized [0,1] coords.
# Excludes batter (right side), crops above the catcher, includes full pitcher body.
DEFAULT_CF_CROP = (0.25, 0.40, 0.60, 1.00)


def extract_landmarks(
    video_path: Path,
    crop_box: tuple[float, float, float, float] | None = DEFAULT_CF_CROP,
) -> tuple[list[list[dict] | None], dict]:
    """Run MediaPipe PoseLandmarker over every frame.

    crop_box: (x_min, y_min, x_max, y_max) in normalized [0,1] coords. If set,
    each frame is cropped to this region before pose detection — this forces
    MediaPipe to track only the pitcher in CF broadcast views, avoiding
    lock-on to batters/catchers/runners. Landmarks are mapped back to full-
    frame coordinates before returning. Pass None to run on the full frame.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"could not open {video_path}")

    meta = {
        "fps": cap.get(cv2.CAP_PROP_FPS),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "n_frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "crop_box": crop_box,
    }

    options = mp_vision.PoseLandmarkerOptions(
        base_options=mp_py.BaseOptions(model_asset_path=str(MODEL_PATH)),
        running_mode=mp_vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    # Pre-compute pixel bounds for the crop
    if crop_box is not None:
        x0_n, y0_n, x1_n, y1_n = crop_box
        x0_px = int(round(x0_n * meta["width"]))
        y0_px = int(round(y0_n * meta["height"]))
        x1_px = int(round(x1_n * meta["width"]))
        y1_px = int(round(y1_n * meta["height"]))
        cw = x1_n - x0_n
        ch = y1_n - y0_n
    else:
        x0_px = y0_px = 0
        x1_px = meta["width"]
        y1_px = meta["height"]
        x0_n = y0_n = 0.0
        cw = ch = 1.0

    frames: list[list[dict] | None] = []
    with mp_vision.PoseLandmarker.create_from_options(options) as landmarker:
        fi = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            region = frame[y0_px:y1_px, x0_px:x1_px]
            rgb = cv2.cvtColor(region, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            ts_ms = int(fi * 1000 / meta["fps"]) if meta["fps"] else fi
            res = landmarker.detect_for_video(mp_image, ts_ms)
            if not res.pose_landmarks:
                frames.append(None)
            else:
                lms = res.pose_landmarks[0]
                # Map cropped-frame normalized coords back to full-frame coords
                frames.append([
                    {"x": x0_n + lm.x * cw,
                     "y": y0_n + lm.y * ch,
                     "z": lm.z,
                     "v": getattr(lm, "visibility", 1.0)}
                    for lm in lms
                ])
            fi += 1
    cap.release()
    return frames, meta


def _np(lms: list[dict], idx: int) -> np.ndarray:
    """Landmark as (x, y) in normalized image coords."""
    lm = lms[idx]
    return np.array([lm["x"], lm["y"]])


def _visible(lms: list[dict], idx: int, thresh: float = 0.3) -> bool:
    return lms[idx]["v"] >= thresh


def compute_features(
    frames: list[list[dict] | None],
    meta: dict,
    hand: Handedness,
) -> list[dict]:
    """One feature row per frame. NaN where the pose was not detected."""
    out: list[dict] = []
    h = meta["height"]
    w = meta["width"]

    for fi, lms in enumerate(frames):
        row = {"frame": fi, "t": fi / meta["fps"] if meta["fps"] else fi}
        if lms is None:
            for k in ("glove_y", "glove_height_norm", "throwing_wrist_y",
                     "throwing_wrist_x", "lead_ankle_y", "leg_lift_norm",
                     "hip_shoulder_sep_deg", "arm_slot_deg", "stride_norm",
                     "spine_tilt_deg"):
                row[k] = float("nan")
            out.append(row)
            continue

        # points
        l_sh, r_sh = _np(lms, L_SHOULDER), _np(lms, R_SHOULDER)
        l_hip, r_hip = _np(lms, L_HIP), _np(lms, R_HIP)
        sh_mid = (l_sh + r_sh) / 2
        hip_mid = (l_hip + r_hip) / 2
        torso_len = np.linalg.norm(sh_mid - hip_mid)  # normalized-image-space
        torso_len = max(torso_len, 1e-6)

        glove_wrist = _np(lms, hand.glove_wrist)
        throwing_wrist = _np(lms, hand.throwing_wrist)
        lead_ankle = _np(lms, hand.lead_ankle)
        trail_ankle = _np(lms, hand.trail_ankle)
        throwing_shoulder = _np(lms, hand.throwing_shoulder)
        throwing_elbow = _np(lms, hand.throwing_elbow)

        # glove height: how far above hip, normalized by torso (1.0 = at shoulder line)
        # y is inverted in image coords (0=top), so subtract glove_y from hip_y
        row["glove_y"] = float(glove_wrist[1])
        row["glove_height_norm"] = float((hip_mid[1] - glove_wrist[1]) / torso_len)

        row["throwing_wrist_x"] = float(throwing_wrist[0])
        row["throwing_wrist_y"] = float(throwing_wrist[1])

        # leg lift: lead ankle height above trail ankle, in torso-lengths
        row["lead_ankle_y"] = float(lead_ankle[1])
        row["leg_lift_norm"] = float((trail_ankle[1] - lead_ankle[1]) / torso_len)

        # hip-shoulder separation: signed angle between shoulder-line and hip-line
        sh_vec = r_sh - l_sh
        hip_vec = r_hip - l_hip
        sh_ang = math.degrees(math.atan2(sh_vec[1], sh_vec[0]))
        hip_ang = math.degrees(math.atan2(hip_vec[1], hip_vec[0]))
        diff = (sh_ang - hip_ang + 180) % 360 - 180
        row["hip_shoulder_sep_deg"] = float(diff)

        # arm slot: angle of throwing forearm vs horizontal (shoulder->elbow->wrist)
        # we report the shoulder-to-wrist vector angle (simpler, more robust)
        arm_vec = throwing_wrist - throwing_shoulder
        # negate y because image y grows downward; we want 0° horizontal, +90° overhead
        slot_deg = math.degrees(math.atan2(-arm_vec[1], arm_vec[0]))
        row["arm_slot_deg"] = float(slot_deg)

        # stride: horizontal distance between ankles, in torso-lengths
        row["stride_norm"] = float(abs(lead_ankle[0] - trail_ankle[0]) / torso_len)

        # spine tilt from vertical: positive = leaning toward throwing side
        spine_vec = sh_mid - hip_mid
        spine_deg = math.degrees(math.atan2(spine_vec[0], -spine_vec[1]))
        row["spine_tilt_deg"] = float(spine_deg)

        out.append(row)

    return out


def _find_leg_lift_peak(features: list[dict], threshold: float = 0.2) -> int | None:
    """First leg-lift peak above `threshold`. This is the real pitch — later
    peaks in long clips correspond to pre-pitch motion of other subjects or
    post-pitch follow-through."""
    from scipy.signal import find_peaks
    leg = np.array([f["leg_lift_norm"] for f in features], dtype=float)
    leg_s = _nan_smooth(leg, window=5)
    leg_clean = np.where(np.isfinite(leg_s), leg_s, 0.0)
    peaks, _ = find_peaks(leg_clean, height=threshold, distance=30)
    return int(peaks[0]) if len(peaks) else None


def detect_release_frame(
    frames: list[list[dict] | None],
    features: list[dict],
    hand: Handedness,
    leg_lift_threshold: float = 0.2,
    release_window_start: int = 10,
    release_window_end: int = 55,
) -> int | None:
    """Release = max wrist-speed in a physiologically-constrained window after
    the FIRST leg-lift peak.

    Rationale: in a pitching delivery, leg-lift peaks first, then the arm
    accelerates through release ~300-800ms later. We find the first real
    leg-lift peak (the actual pitch — later peaks in Savant clips are always
    replays), then look for release in [peak+10, peak+80] frames after.

    This fixes two failure modes:
    - Savant clips with replays: prior algorithm picked wrong replay's peak.
    - Long clips with multiple leg-lifts: prior algorithm picked hand-
      separation peak instead of release.
    """
    n = len(features)
    if n < 20:
        return None

    leg_peak_frame = _find_leg_lift_peak(features, threshold=leg_lift_threshold)
    if leg_peak_frame is None:
        return None

    # Wrist speed
    xs = np.array([f["throwing_wrist_x"] for f in features])
    ys = np.array([f["throwing_wrist_y"] for f in features])
    mask = np.isfinite(xs) & np.isfinite(ys)
    if mask.sum() < 10:
        return None
    dx = np.gradient(np.where(mask, xs, np.nan))
    dy = np.gradient(np.where(mask, ys, np.nan))
    speed = _nan_smooth(np.sqrt(dx * dx + dy * dy), window=5)
    speed_clean = np.where(np.isfinite(speed), speed, 0.0)

    # Search window: [leg_peak + release_window_start, leg_peak + release_window_end]
    lo = min(n - 1, leg_peak_frame + release_window_start)
    hi = min(n, leg_peak_frame + release_window_end + 1)
    if hi - lo < 2:
        return None
    return lo + int(np.argmax(speed_clean[lo:hi]))


def detect_delivery_start(
    frames: list[list[dict] | None],
    features: list[dict],
    hand: Handedness,
    release_frame: int,
) -> int | None:
    """First frame of delivery motion (earliest visible leg flinch before release).

    Anchors on leg-lift peak (robust signal), then walks BACKWARD through
    leg_lift_norm. The set-hold has leg_lift ≈ 0; any subtle flinch of either
    leg registers as a small positive/negative value (since leg_lift_norm is
    relative ankle-height difference). Start = the frame just before this
    signal crosses back below the baseline noise floor.

    This also handles both stretch and windup naturally — the algorithm walks
    back however far the leg_lift signal remains elevated, regardless of
    total delivery length.
    """
    n = len(features)
    if release_frame < 20 or release_frame >= n:
        return None

    # Use the SAME leg-lift peak that release detection used — keeps both
    # detectors referring to the same delivery phase.
    leg_peak_frame = _find_leg_lift_peak(features, threshold=0.2)
    if leg_peak_frame is None or leg_peak_frame >= release_frame:
        return None

    leg = np.array([f["leg_lift_norm"] for f in features], dtype=float)
    leg_s = _nan_smooth(leg, window=5)

    # Per-clip baseline: median of smoothed leg_lift over the first 60 frames
    # before the peak. This absorbs small systematic offsets (e.g., Mikolas's
    # stance isn't perfectly symmetrical when set) so we're comparing to the
    # ACTUAL set-position value, not zero.
    pre = leg_s[max(0, leg_peak_frame - 60):leg_peak_frame]
    pre = pre[np.isfinite(pre)]
    if len(pre) < 5:
        baseline = 0.0
    else:
        baseline = float(np.median(pre))
    # Motion detected when leg_lift exceeds baseline by DELTA
    DELTA = 0.045  # tuned against 6 labeled clips
    threshold = baseline + DELTA

    for i in range(leg_peak_frame, 0, -1):
        v = leg_s[i]
        if not np.isnan(v) and v < threshold:
            return i + 1
    return None


def _nan_smooth(x: np.ndarray, window: int = 5) -> np.ndarray:
    """Moving average that ignores NaN; returns NaN only where the window is empty."""
    n = len(x)
    half = window // 2
    out = np.full(n, np.nan, dtype=float)
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        chunk = x[lo:hi]
        m = np.isfinite(chunk)
        if m.any():
            out[i] = float(np.mean(chunk[m]))
    return out


def render_overlay(
    video_path: Path,
    out_path: Path,
    frames: list[list[dict] | None],
    features: list[dict],
    release_frame: int | None,
) -> None:
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_path), fourcc, fps, (w, h))

    fi = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        lms = frames[fi] if fi < len(frames) else None
        feat = features[fi] if fi < len(features) else None

        if lms is not None:
            _draw_skeleton(frame, lms, w, h)

        # text HUD
        lines = [f"frame {fi}   t={fi/fps:5.2f}s"]
        if feat is not None and not math.isnan(feat.get("glove_height_norm", float("nan"))):
            lines.append(f"glove height (torso-norm): {feat['glove_height_norm']:+.2f}")
            lines.append(f"leg lift (torso-norm):     {feat['leg_lift_norm']:+.2f}")
            lines.append(f"arm slot (deg):            {feat['arm_slot_deg']:+.1f}")
            lines.append(f"hip-shoulder sep (deg):    {feat['hip_shoulder_sep_deg']:+.1f}")
            lines.append(f"spine tilt (deg):          {feat['spine_tilt_deg']:+.1f}")
        for i, line in enumerate(lines):
            cv2.putText(frame, line, (10, 22 + 20 * i),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(frame, line, (10, 22 + 20 * i),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

        if release_frame is not None and fi == release_frame:
            cv2.putText(frame, "RELEASE", (w // 2 - 80, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3, cv2.LINE_AA)

        writer.write(frame)
        fi += 1

    cap.release()
    writer.release()


def _draw_skeleton(frame: np.ndarray, lms: list[dict], w: int, h: int) -> None:
    """Draw 33-keypoint skeleton on the frame in-place."""
    pts = [(int(lm["x"] * w), int(lm["y"] * h)) for lm in lms]
    vis = [lm["v"] for lm in lms]
    for a, b in POSE_CONNECTIONS:
        if vis[a] < 0.3 or vis[b] < 0.3:
            continue
        cv2.line(frame, pts[a], pts[b], (0, 255, 0), 2, cv2.LINE_AA)
    for i, (x, y) in enumerate(pts):
        if vis[i] < 0.3:
            continue
        cv2.circle(frame, (x, y), 3, (0, 0, 255), -1, cv2.LINE_AA)


def plot_metrics(features: list[dict], release_frame: int | None, out_path: Path) -> None:
    t = np.array([f["t"] for f in features])
    fig, axes = plt.subplots(5, 1, figsize=(10, 11), sharex=True)

    plots = [
        ("glove_height_norm",    "Glove height (torso-norm)",   "C0"),
        ("leg_lift_norm",        "Leg lift (torso-norm)",       "C1"),
        ("arm_slot_deg",         "Arm slot (deg, 0=horiz)",     "C2"),
        ("hip_shoulder_sep_deg", "Hip-shoulder sep (deg)",      "C3"),
        ("spine_tilt_deg",       "Spine tilt from vertical (deg)", "C4"),
    ]
    for ax, (key, label, color) in zip(axes, plots):
        y = np.array([f[key] for f in features], dtype=float)
        ax.plot(t, y, color=color, lw=1.5)
        ax.set_ylabel(label, fontsize=9)
        ax.grid(alpha=0.3)
        if release_frame is not None:
            ax.axvline(t[release_frame], color="red", lw=1, ls="--", alpha=0.7)

    axes[-1].set_xlabel("time (s)")
    if release_frame is not None:
        axes[0].set_title(f"Release @ frame {release_frame} (t={t[release_frame]:.2f}s)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def write_keypoints_json(frames, meta, out_path: Path) -> None:
    out_path.write_text(json.dumps({"meta": meta, "frames": frames}))


def write_features_csv(features: list[dict], out_path: Path) -> None:
    if not features:
        return
    keys = list(features[0].keys())
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(features)


def main(video_path: str, handedness: str = "RHP") -> None:
    video_path = Path(video_path).expanduser().resolve()
    out_dir = Path(__file__).parent / "out"
    out_dir.mkdir(exist_ok=True)
    stem = video_path.stem[:24]  # clip the long encoded names

    hand = RHP if handedness.upper() == "RHP" else LHP

    print(f"[1/4] extracting pose from {video_path.name}...")
    frames, meta = extract_landmarks(video_path)
    print(f"      {meta['n_frames']} frames, {meta['fps']:.1f} fps, "
          f"detected in {sum(1 for f in frames if f is not None)} / {len(frames)}")

    print("[2/4] computing features...")
    features = compute_features(frames, meta, hand)
    release = detect_release_frame(frames, features, hand)
    if release is not None:
        print(f"      release frame: {release} (t={features[release]['t']:.2f}s)")
    else:
        print("      release frame: not found")

    print("[3/4] writing keypoints + features...")
    write_keypoints_json(frames, meta, out_dir / f"{stem}_keypoints.json")
    write_features_csv(features, out_dir / f"{stem}_features.csv")

    print("[4/4] rendering overlay video + metrics plot...")
    render_overlay(video_path, out_dir / f"{stem}_overlay.mp4",
                   frames, features, release)
    plot_metrics(features, release, out_dir / f"{stem}_metrics.png")

    print("done.")
    print("outputs in:", out_dir)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 pose_pipeline.py <video.mp4> [RHP|LHP]")
        sys.exit(2)
    hand = sys.argv[2] if len(sys.argv) > 2 else "RHP"
    main(sys.argv[1], hand)
