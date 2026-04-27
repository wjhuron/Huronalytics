"""Render clips with a big frame-number overlay for hand-labeling.

Takes a list of PitchIDs, copies each clip with a clean corner overlay showing
the current frame number. No skeleton, no markers — just the footage so the
labeler's eye isn't biased.

Also writes a CSV template with rows pre-populated for the labeler to fill in.

Usage:
    python3 biomech/render_labeling.py
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import cv2

REPO = Path(__file__).resolve().parents[1]
CLIPS_DIR = REPO / "biomech" / "clips"
OUT_DIR = Path.home() / "Downloads" / "labeling"
CSV_PATH = OUT_DIR / "labels.csv"

PITCH_IDS = [
    "823398_017_01",  # CU vs Gonzales
    "822758_044_02",  # FC vs Hernandez
    "822753_017_02",  # SI vs Burleson (bases loaded)
    "824701_041_01",  # FC vs Swanson
    "823398_017_02",  # SI vs Gonzales
    "822753_015_02",  # CH vs Wetherholt
    "822750_032_01",  # ST vs Adames
    "822758_020_02",  # CH vs Ohtani
    "822753_024_03",  # ST vs Urias
    "822758_035_03",  # FF vs Tucker
]


def render(pid: str) -> Path:
    src = CLIPS_DIR / f"{pid}.mp4"
    dst = OUT_DIR / f"{pid}.mp4"
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = cv2.VideoWriter(str(dst), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))

    fi = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        text = f"frame {fi:4d}"
        # Shadow + foreground text in top-left, big & readable
        cv2.putText(frame, text, (14, 52), cv2.FONT_HERSHEY_SIMPLEX,
                    1.4, (0, 0, 0), 6, cv2.LINE_AA)
        cv2.putText(frame, text, (14, 52), cv2.FONT_HERSHEY_SIMPLEX,
                    1.4, (0, 255, 255), 2, cv2.LINE_AA)
        writer.write(frame)
        fi += 1

    cap.release()
    writer.release()
    return dst


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for pid in PITCH_IDS:
        path = render(pid)
        print(f"  {path.name}")

    with CSV_PATH.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["PitchID", "start_frame", "release_frame", "notes"])
        for pid in PITCH_IDS:
            w.writerow([pid, "", "", ""])
    print(f"\ntemplate: {CSV_PATH}")


if __name__ == "__main__":
    main()
