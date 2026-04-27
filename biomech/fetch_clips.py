"""Download Baseball Savant pitch clips for a list of PitchIDs.

Given a CSV with a PitchID column (typically the output of pull_pitches.py):
  1. Groups PitchIDs by game_pk.
  2. For each game, hits the MLB statsapi live feed once to build a
     PitchID -> PlayID map (cached locally in biomech/playid_cache.json so
     repeat runs don't re-fetch).
  3. For each PitchID, scrapes the Savant sporty-videos page to find the MP4
     URL and downloads to biomech/clips/<PitchID>.mp4.
  4. Skips any clip that has already been downloaded (resumable).

Usage:
    python3 biomech/fetch_clips.py --input biomech/out/pitches_miles_mikolas_on.csv
    python3 biomech/fetch_clips.py --input <csv> --limit 5        # sanity-check batch
    python3 biomech/fetch_clips.py --input <csv> --cache-only     # build cache, no download
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]
BIOMECH = REPO / "biomech"
CACHE_PATH = BIOMECH / "playid_cache.json"
CLIPS_DIR = BIOMECH / "clips"

LIVE_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
SAVANT_PAGE = "https://baseballsavant.mlb.com/sporty-videos?playId={play_id}"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
HEADERS = {"User-Agent": UA}

# Be polite to MLB's servers.
SLEEP_BETWEEN_GAMES = 1.0   # seconds between live-feed fetches
SLEEP_BETWEEN_CLIPS = 0.3   # seconds between clip downloads


def parse_pitchid(pitch_id: str) -> tuple[int, int, int]:
    """'822750_022_05' -> (822750, 22, 5)"""
    game_pk, ab, pn = pitch_id.split("_")
    return int(game_pk), int(ab), int(pn)


def load_cache() -> dict[str, str]:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text())
    return {}


def save_cache(cache: dict[str, str]) -> None:
    CACHE_PATH.write_text(json.dumps(cache, indent=0, sort_keys=True))


def read_pitchids(csv_path: Path) -> list[str]:
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        return [r["PitchID"] for r in reader if r.get("PitchID")]


def fetch_game_playids(session: requests.Session, game_pk: int) -> dict[str, str]:
    """Fetch live feed and return PitchID -> PlayID for every pitch in that game."""
    url = LIVE_FEED_URL.format(game_pk=game_pk)
    r = session.get(url, headers=HEADERS, timeout=45)
    r.raise_for_status()
    data = r.json()

    out: dict[str, str] = {}
    for play in data.get("liveData", {}).get("plays", {}).get("allPlays", []):
        # atBatIndex is 0-based; PitchID format uses 1-based at-bat numbers
        ab_num = play.get("atBatIndex")
        if ab_num is None:
            continue
        ab_num = ab_num + 1
        for ev in play.get("playEvents", []):
            if not ev.get("isPitch"):
                continue
            pn = ev.get("pitchNumber")
            play_id = ev.get("playId")
            if pn is None or play_id is None:
                continue
            pid = f"{game_pk}_{ab_num:03d}_{pn:02d}"
            out[pid] = play_id
    return out


MP4_RE = re.compile(r'<source[^>]+src="(https?://[^"]+\.mp4)"', re.I)
MP4_FALLBACK_RE = re.compile(r'https?://sporty-clips\.mlb\.com/[^\s"\'<>]+\.mp4', re.I)


def find_mp4_url(session: requests.Session, play_id: str) -> str | None:
    r = session.get(SAVANT_PAGE.format(play_id=play_id), headers=HEADERS, timeout=30)
    r.raise_for_status()
    m = MP4_RE.search(r.text)
    if m:
        return m.group(1)
    m = MP4_FALLBACK_RE.search(r.text)
    return m.group(0) if m else None


def download(session: requests.Session, url: str, dest: Path) -> None:
    with session.get(url, headers=HEADERS, stream=True, timeout=120) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with tmp.open("wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
        tmp.rename(dest)


def ensure_cache(
    pitch_ids: list[str],
    cache: dict[str, str],
    session: requests.Session,
) -> None:
    """Fill cache for any PitchID that doesn't have a PlayID yet."""
    missing_by_game: dict[int, set[str]] = defaultdict(set)
    for pid in pitch_ids:
        if pid not in cache:
            game_pk, _, _ = parse_pitchid(pid)
            missing_by_game[game_pk].add(pid)

    if not missing_by_game:
        return

    print(f"Populating PlayID cache for {len(missing_by_game)} game(s)...")
    for i, (game_pk, pids) in enumerate(sorted(missing_by_game.items())):
        if i > 0:
            time.sleep(SLEEP_BETWEEN_GAMES)
        print(f"  [{i+1}/{len(missing_by_game)}] game {game_pk}: fetching live feed for {len(pids)} pitch(es)...")
        try:
            game_map = fetch_game_playids(session, game_pk)
        except Exception as e:
            print(f"    !! failed: {e}")
            continue
        hits = 0
        for pid in pids:
            if pid in game_map:
                cache[pid] = game_map[pid]
                hits += 1
            else:
                print(f"    ?? {pid} not found in this game's live feed")
        print(f"    matched {hits}/{len(pids)}")
    save_cache(cache)
    print(f"Cache saved: {CACHE_PATH}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="CSV with PitchID column")
    ap.add_argument("--limit", type=int, default=None, help="only fetch first N PitchIDs")
    ap.add_argument("--cache-only", action="store_true", help="populate cache but don't download clips")
    ap.add_argument("--output-dir", default=str(CLIPS_DIR))
    args = ap.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pitch_ids = read_pitchids(Path(args.input))
    if args.limit:
        pitch_ids = pitch_ids[: args.limit]
    print(f"{len(pitch_ids)} PitchIDs from {args.input}")

    cache = load_cache()
    session = requests.Session()
    ensure_cache(pitch_ids, cache, session)

    if args.cache_only:
        return

    downloaded = skipped = failed = 0
    missing_playid = 0
    for i, pid in enumerate(pitch_ids, 1):
        dest = out_dir / f"{pid}.mp4"
        if dest.exists() and dest.stat().st_size > 0:
            skipped += 1
            continue
        play_id = cache.get(pid)
        if not play_id:
            print(f"[{i}/{len(pitch_ids)}] {pid}: NO PLAYID IN CACHE (investigate)")
            missing_playid += 1
            continue
        try:
            mp4_url = find_mp4_url(session, play_id)
            if not mp4_url:
                print(f"[{i}/{len(pitch_ids)}] {pid} (playId={play_id}): NO MP4 URL in Savant page")
                failed += 1
                continue
            download(session, mp4_url, dest)
            size_mb = dest.stat().st_size / (1024 * 1024)
            print(f"[{i}/{len(pitch_ids)}] {pid} -> {dest.name} ({size_mb:.1f} MB)")
            downloaded += 1
        except Exception as e:
            print(f"[{i}/{len(pitch_ids)}] {pid} FAILED: {e}")
            failed += 1
        time.sleep(SLEEP_BETWEEN_CLIPS)

    print(f"\ndone. downloaded={downloaded}  already-had={skipped}  "
          f"failed={failed}  no-playid={missing_playid}")
    if missing_playid or failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
