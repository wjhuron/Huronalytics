"""Render a single clip with labeled markers so a human can sanity-check detections.

Marks:
  - SET        (green)  — settle_start: where we think the pitcher's pre-delivery plateau begins
  - LEG PEAK   (yellow) — top of the leg kick
  - RELEASE    (red)    — detected ball release frame

Also overlays pose skeleton and a phase label on each frame.

Usage:
    python3 biomech/annotate_clip.py <clip.mp4> [RHP|LHP] [out_path.mp4]
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

import pose_pipeline as pp


def phase_label(i: int, start_frame: int, release: int) -> str:
    if i < start_frame:
        return "(pre-delivery / not analyzed)"
    if i < release:
        return "DELIVERY"
    return "FOLLOW-THROUGH"


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: annotate_clip.py <clip.mp4> [RHP|LHP] [out.mp4]")
        sys.exit(2)
    clip = Path(sys.argv[1]).expanduser().resolve()
    hand_s = sys.argv[2] if len(sys.argv) > 2 else "RHP"
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path.home() / "Downloads" / f"{clip.stem}_annotated.mp4"
    hand = pp.RHP if hand_s == "RHP" else pp.LHP

    print(f"extracting pose from {clip.name}...")
    frames, meta = pp.extract_landmarks(clip)
    features = pp.compute_features(frames, meta, hand)
    release = pp.detect_release_frame(frames, features, hand)

    if release is None:
        print("no release detected — aborting")
        sys.exit(1)

    start = pp.detect_delivery_start(frames, features, hand, release)
    if start is None:
        print("could not resolve start of delivery — using release - 60 as rough default")
        start = max(0, release - 60)

    print(f"  release_frame    = {release}   t={features[release]['t']:.2f}s")
    print(f"  start_frame      = {start}    t={features[start]['t']:.2f}s")
    print(f"  delivery_length  = {release - start} frames "
          f"({(release - start) / meta['fps']:.2f}s)")

    cap = cv2.VideoCapture(str(clip))
    fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))

    fi = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        lms = frames[fi] if fi < len(frames) else None
        feat = features[fi] if fi < len(features) else None

        if lms is not None:
            pp._draw_skeleton(frame, lms, w, h)

        # HUD
        def put(text: str, x: int, y: int, color, big: bool = False) -> None:
            scale = 0.9 if big else 0.55
            thick_bg = 4 if big else 3
            thick_fg = 2 if big else 1
            cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale,
                        (0, 0, 0), thick_bg, cv2.LINE_AA)
            cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale,
                        color, thick_fg, cv2.LINE_AA)

        put(f"frame {fi}   t={fi/fps:5.2f}s", 10, 22, (255, 255, 255))
        put(phase_label(fi, start, release), 10, 44, (200, 200, 200))

        if feat is not None:
            put(f"leg_lift_norm = {feat['leg_lift_norm']:+.2f}", 10, 66, (180, 220, 255))

        # Event banners
        if fi == start:
            put("START (first leg motion)", 10, h - 40, (0, 255, 0), big=True)
        elif fi == release:
            put("RELEASE", 10, h - 40, (0, 0, 255), big=True)

        # Persistent corner notes
        put(f"START    = {start}", w - 220, 22, (0, 255, 0))
        put(f"RELEASE  = {release}", w - 220, 44, (0, 0, 255))

        writer.write(frame)
        fi += 1

    cap.release()
    writer.release()
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
