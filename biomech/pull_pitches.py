"""Pull PitchIDs from the Huronalytics sheets matching a filter.

First use: fetch every Mikolas pitch with runners on base, emit a CSV that the
clip fetcher will consume.

Usage:
    python3 biomech/pull_pitches.py --pitcher "Miles Mikolas" --runners on
    python3 biomech/pull_pitches.py --pitcher "Miles Mikolas" --runners any  # includes '0'

Output: biomech/out/pitches_<slug>.csv with PitchID and context columns.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

import gspread

REPO = Path(__file__).resolve().parents[1]

# Six 2026 per-division workbooks (huronalytics), replacing the old AL/NL books.
WORKBOOKS = {
    "ALE": "1YbgAliQzXePiFan-ruwJ50G80l4AjeyTGN8cO3KJ1XI",
    "ALC": "14gglESfgJoT90crQb5hHoEZNUFDZ5chPLbUIV9mlm4E",
    "ALW": "1eSFfKRo5kSImjP0SZ1SMssGrOhrKSZM9GOHiwntIlhs",
    "NLE": "1BypxxlWgQAltETOLqccOYigeo8nXX-FIuVv6rhT4anA",
    "NLC": "1-I8BVEw9bR9rzGVYJao_Ar0bjYZF54pi5pm3YEluB9w",
    "NLW": "1vm257A676FORcSRzXcNj6txgehGhYI7k5mnmsgQCYH0",
}
TEAM_DIVISION = {
    "BAL": "ALE", "BOS": "ALE", "NYY": "ALE", "TBR": "ALE", "TOR": "ALE",
    "CLE": "ALC", "CWS": "ALC", "DET": "ALC", "KCR": "ALC", "MIN": "ALC",
    "ATH": "ALW", "HOU": "ALW", "LAA": "ALW", "SEA": "ALW", "TEX": "ALW",
    "ATL": "NLE", "MIA": "NLE", "NYM": "NLE", "PHI": "NLE", "WSH": "NLE",
    "ROC": "NLE", "AAA": "NLE", "FCL": "NLE",
    "CHC": "NLC", "CIN": "NLC", "MIL": "NLC", "PIT": "NLC", "STL": "NLC",
    "ARI": "NLW", "COL": "NLW", "LAD": "NLW", "SDP": "NLW", "SFG": "NLW",
}

# Pitcher's MLB team -> (league, tab)
TEAM_TO_SHEET = {
    "ATH": ("AL", "ATH"), "BAL": ("AL", "BAL"), "BOS": ("AL", "BOS"),
    "CLE": ("AL", "CLE"), "CWS": ("AL", "CWS"), "DET": ("AL", "DET"),
    "HOU": ("AL", "HOU"), "KCR": ("AL", "KCR"), "LAA": ("AL", "LAA"),
    "MIN": ("AL", "MIN"), "NYY": ("AL", "NYY"), "SEA": ("AL", "SEA"),
    "TBR": ("AL", "TBR"), "TEX": ("AL", "TEX"), "TOR": ("AL", "TOR"),
    "ARI": ("NL", "ARI"), "ATL": ("NL", "ATL"), "CHC": ("NL", "CHC"),
    "CIN": ("NL", "CIN"), "COL": ("NL", "COL"), "LAD": ("NL", "LAD"),
    "MIA": ("NL", "MIA"), "MIL": ("NL", "MIL"), "NYM": ("NL", "NYM"),
    "PHI": ("NL", "PHI"), "PIT": ("NL", "PIT"), "SDP": ("NL", "SDP"),
    "SFG": ("NL", "SFG"), "STL": ("NL", "STL"), "WSH": ("NL", "WSH"),
}

# Known pitcher-to-team map for single-tab lookups. Fall back to scanning all
# tabs if unknown — slower but correct.
KNOWN_PITCHER_TEAMS: dict[str, str] = {
    "Mikolas, Miles": "WSH",
}


def normalize_pitcher_name(name: str) -> str:
    """Accept 'First Last' and convert to sheet format 'Last, First'. Pass
    'Last, First' through unchanged."""
    n = name.strip()
    if "," in n:
        return n
    parts = n.split()
    if len(parts) >= 2:
        first = parts[0]
        last = " ".join(parts[1:])
        return f"{last}, {first}"
    return n

CONTEXT_COLS = ["PitchID", "Game Date", "Pitcher", "Pitch Type", "Count",
                "Runners", "Outs", "Batter", "Bats"]


def auth_gspread() -> gspread.Client:
    # Default gspread service account (~/.config/gspread = huronalytics), the
    # account the six division books are shared with.
    return gspread.service_account()


def col_indices(header: list[str], wanted: list[str]) -> dict[str, int]:
    lookup = {h.strip(): i for i, h in enumerate(header)}
    missing = [w for w in wanted if w not in lookup]
    if missing:
        raise ValueError(f"missing header columns: {missing}")
    return {w: lookup[w] for w in wanted}


def rows_for_tab(gc: gspread.Client, league: str, tab: str) -> list[list[str]]:
    # `league` is kept for the caller's signature; the book is the team's
    # division workbook, resolved from the tab (team code).
    sh = gc.open_by_key(WORKBOOKS[TEAM_DIVISION[tab]])
    ws = sh.worksheet(tab)
    return ws.get_all_values()


def runners_match(value: str, mode: str) -> bool:
    v = (value or "").strip()
    if mode == "any":
        return True
    if mode == "on":
        return v not in ("0", "")
    if mode == "off":
        return v == "0"
    if mode == "scoring":       # runners at 2nd and/or 3rd
        return any(b in v for b in ("2", "3"))
    if mode == "man_on_first":  # at least a man on first (stretch)
        return "1" in v
    raise ValueError(f"unknown runners mode: {mode}")


def pull(pitcher: str, runners_mode: str) -> list[dict]:
    gc = auth_gspread()
    pitcher = normalize_pitcher_name(pitcher)
    print(f"  looking for: {pitcher!r}")

    team = KNOWN_PITCHER_TEAMS.get(pitcher)
    if team is None:
        # scan all tabs; slow but safe
        tabs = [(lg, tab) for tab, (lg, _) in
                ((t, TEAM_TO_SHEET[t]) for t in TEAM_TO_SHEET)]
    else:
        lg, tab = TEAM_TO_SHEET[team]
        tabs = [(lg, tab)]

    out: list[dict] = []
    for league, tab in tabs:
        print(f"  reading [{league}] {tab}...")
        rows = rows_for_tab(gc, league, tab)
        if not rows or len(rows) < 2:
            continue
        header = rows[0]
        try:
            idx = col_indices(header, CONTEXT_COLS)
        except ValueError as e:
            print(f"    skip {tab}: {e}")
            continue
        for r in rows[1:]:
            if len(r) <= max(idx.values()):
                continue
            if r[idx["Pitcher"]].strip() != pitcher:
                continue
            if not runners_match(r[idx["Runners"]], runners_mode):
                continue
            out.append({k: r[idx[k]] for k in CONTEXT_COLS})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pitcher", required=True,
                    help='full name as it appears in your sheet (e.g. "Miles Mikolas")')
    ap.add_argument("--runners", default="on",
                    choices=["any", "on", "off", "scoring", "man_on_first"],
                    help="runner-state filter (default: 'on' — anyone on base)")
    ap.add_argument("--out", default=None,
                    help="output CSV path (default: biomech/out/pitches_<slug>.csv)")
    args = ap.parse_args()

    hits = pull(args.pitcher, args.runners)

    out_dir = REPO / "biomech" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = args.pitcher.lower().replace(" ", "_") + f"_{args.runners}"
    out_path = Path(args.out) if args.out else out_dir / f"pitches_{slug}.csv"

    if hits:
        with out_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CONTEXT_COLS)
            w.writeheader()
            w.writerows(hits)
        print(f"\n{len(hits)} pitches -> {out_path}")
        # tally by pitch type + runners state
        from collections import Counter
        by_type = Counter(h["Pitch Type"] for h in hits)
        by_runners = Counter(h["Runners"] for h in hits)
        print(f"  by pitch type: {dict(by_type)}")
        print(f"  by runners:    {dict(by_runners)}")
    else:
        print("0 matches")
        sys.exit(1)


if __name__ == "__main__":
    main()
