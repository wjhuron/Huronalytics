"""Grid-search release/start detection thresholds against hand-labeled clips.

Reads labels from a Numbers file (or CSV), runs pose extraction on each
labeled clip, sweeps thresholds, and reports the config that minimizes
total frame error.

Usage:
    python3 biomech/tune_detector.py --labels /Users/wallyhuron/Downloads/labels.numbers
"""

from __future__ import annotations

import argparse
import csv
import itertools
from pathlib import Path

import numpy as np

import pose_pipeline as pp

REPO = Path(__file__).resolve().parents[1]
CLIPS_DIR = REPO / "biomech" / "clips"


def load_labels(path: Path) -> list[dict]:
    """Load labels from either .numbers or .csv; filter unusable rows."""
    out = []
    if path.suffix == ".numbers":
        from numbers_parser import Document
        doc = Document(str(path))
        for sheet in doc.sheets:
            for table in sheet.tables:
                rows = list(table.rows(values_only=True))
                header = [str(x) for x in rows[0]]
                for r in rows[1:]:
                    row = dict(zip(header, r))
                    if row.get("start_frame") is None or row.get("release_frame") is None:
                        continue
                    out.append({
                        "PitchID": row["PitchID"],
                        "start": int(row["start_frame"]),
                        "release": int(row["release_frame"]),
                    })
    else:
        with path.open() as f:
            for r in csv.DictReader(f):
                if not r.get("start_frame") or not r.get("release_frame"):
                    continue
                out.append({
                    "PitchID": r["PitchID"],
                    "start": int(r["start_frame"]),
                    "release": int(r["release_frame"]),
                })
    return out


def extract(pid: str):
    """Cache-aware extract so we don't re-run MediaPipe every grid step."""
    if pid not in _CACHE:
        path = CLIPS_DIR / f"{pid}.mp4"
        frames, meta = pp.extract_landmarks(path)
        features = pp.compute_features(frames, meta, pp.RHP)
        _CACHE[pid] = (frames, features, meta)
    return _CACHE[pid]


_CACHE: dict = {}


def detect_start_with_threshold(features, release_frame, baseline: float) -> int | None:
    """Same logic as pose_pipeline.detect_delivery_start, but parametrised."""
    if release_frame < 20 or release_frame >= len(features):
        return None
    leg = np.array([f["leg_lift_norm"] for f in features], dtype=float)
    leg_s = pp._nan_smooth(leg, window=5)
    lo = max(0, release_frame - 120)
    seg = leg_s[lo:release_frame]
    if np.all(np.isnan(seg)):
        return None
    leg_peak_frame = lo + int(np.nanargmax(seg))
    if leg_s[leg_peak_frame] < 0.3:
        return None
    for i in range(leg_peak_frame, 0, -1):
        v = leg_s[i]
        if not np.isnan(v) and v < baseline:
            return i + 1
    return None


def evaluate(labels: list[dict], baseline: float) -> dict:
    start_errs = []
    release_errs = []
    details = []
    for row in labels:
        frames, features, _meta = extract(row["PitchID"])
        rel = pp.detect_release_frame(frames, features, pp.RHP)
        if rel is None:
            details.append((row["PitchID"], None, None, None, None))
            continue
        st = detect_start_with_threshold(features, rel, baseline)
        rel_err = rel - row["release"]
        start_err = (st - row["start"]) if st is not None else None
        release_errs.append(rel_err)
        if start_err is not None:
            start_errs.append(start_err)
        details.append((row["PitchID"], row["start"], st, row["release"], rel))
    return {
        "baseline": baseline,
        "start_mae": float(np.mean(np.abs(start_errs))) if start_errs else float("nan"),
        "start_bias": float(np.mean(start_errs)) if start_errs else float("nan"),
        "release_mae": float(np.mean(np.abs(release_errs))) if release_errs else float("nan"),
        "release_bias": float(np.mean(release_errs)) if release_errs else float("nan"),
        "n_start_ok": len(start_errs),
        "n_release_ok": len(release_errs),
        "details": details,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True, help="labels.numbers or labels.csv")
    args = ap.parse_args()

    labels = load_labels(Path(args.labels))
    print(f"{len(labels)} labeled clips")
    for r in labels:
        print(f"  {r['PitchID']}  start={r['start']}  release={r['release']}")

    # Prime the cache with a single pass (expensive)
    print("\nextracting pose on all labeled clips...")
    for r in labels:
        extract(r["PitchID"])
    print()

    # Grid search baseline thresholds
    baselines = [0.020, 0.025, 0.030, 0.035, 0.040, 0.045, 0.050, 0.060]
    print(f"{'baseline':>8}  {'start_mae':>9}  {'start_bias':>10}  "
          f"{'release_mae':>11}  {'release_bias':>12}  {'n':>3}")
    results = []
    for b in baselines:
        res = evaluate(labels, b)
        results.append(res)
        print(f"{b:8.3f}  {res['start_mae']:9.2f}  {res['start_bias']:+10.2f}  "
              f"{res['release_mae']:11.2f}  {res['release_bias']:+12.2f}  "
              f"{res['n_start_ok']:3d}")

    # Best = lowest start_mae (release isn't tunable via this knob)
    best = min(results, key=lambda r: r["start_mae"])
    print(f"\nbest baseline: {best['baseline']:.3f}  "
          f"start_mae={best['start_mae']:.2f}  "
          f"release_mae={best['release_mae']:.2f}")
    print("\nper-clip comparison at best config:")
    print(f"  {'PitchID':<18}  {'truth_start':>11}  {'pred_start':>10}  "
          f"{'d':>4}  {'truth_rel':>9}  {'pred_rel':>8}  {'d':>4}")
    for pid, ts, ps, tr, pr in best["details"]:
        ds = (ps - ts) if (ps is not None and ts is not None) else None
        dr = (pr - tr) if (pr is not None and tr is not None) else None
        fmt = lambda v: "—" if v is None else f"{v:>4d}"
        print(f"  {pid:<18}  {fmt(ts):>11}  {fmt(ps):>10}  {fmt(ds):>4}  "
              f"{fmt(tr):>9}  {fmt(pr):>8}  {fmt(dr):>4}")


if __name__ == "__main__":
    main()
