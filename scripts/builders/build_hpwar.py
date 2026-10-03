"""build_hpwar.py: write data/hpwar_projections.json, the static input behind the site's hpWAR columns.

hpWAR is the PROJECTED sibling of hdWAR (the site label of the descriptive hWAR): wins above
replacement projected 1, 3 and 5 seasons past BASE, as a RATE.
  hitters    per 600 PA, neutral park (projections_hitters.csv WAR600_*)
  pitchers   per 180 IP if his BASE start share is .5 or more (SP180), else per 60 IP (RP60)
             (projections_pitchers.csv WAR180_SP_* / WAR60_RP_*)
Rochester and other Triple-A rows get nothing (per Wally 2026-10-02): the Triple-A bridges are weak.

Method, backtests and limits: scripts/research/projection/project_players.py and the methods doc
(Google Doc "Huronalytics hWAR audit and projection model: methods (2026-10-02)"). In short: three
seasons of history regressed to league, xwOBA/wOBA 75/25 for batting, Stuff+ in the pitcher level,
measured aging, a coherent 3/5-year chain; projections of ACTUAL results, conditional on the player
still playing. Ages past the data's support (hitters 38+, pitchers 39+) are flagged per horizon.

The projection does not move during a season unless rebuilt, so the file is static and committed;
process_data merges it by mlbId every run (pipeline/process_data.py, apply_hpwar).
Rebuild once a season is complete:
    python3 scripts/research/projection/pull_season_lines.py
    python3 scripts/research/projection/pull_savant_history.py
    python3 scripts/research/projection/pull_frv_history.py
    python3 scripts/research/projection/pull_park_history.py
    python3 scripts/builders/build_hpwar.py          # runs project_players.py, then writes the JSON

Usage: python3 scripts/builders/build_hpwar.py
"""
import csv
import json
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJ = os.path.join(ROOT, 'scripts', 'research', 'projection')
sys.path.insert(0, PROJ)
import project_players  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'hpwar_projections.json')
HORIZONS = {1: 'hpWAR', 3: 'hpWAR3', 5: 'hpWAR5'}
SP_SHARE = 0.5     # role cut for the pitcher unit; a convention (a starter is a pitcher who mostly starts)


def num(v):
    return None if v in (None, '') else float(v)


def main():
    project_players.main()
    base = project_players.BASE
    P = project_players.P
    hitters, pitchers = {}, {}
    for r in csv.DictReader(open(os.path.join(P, 'projections_hitters.csv'))):
        rec = {key: num(r.get(f'WAR600_{base + h}')) for h, key in HORIZONS.items()}
        if all(v is None for v in rec.values()):
            continue
        rec['unit'] = 'PA600'
        rec['thin'] = r.get('thin_age_support') or ''
        hitters[r['mlbId']] = rec
    for r in csv.DictReader(open(os.path.join(P, 'projections_pitchers.csv'))):
        share = num(r.get('gs_share_2026'))
        if share is None:
            continue                     # no BASE season: no leaderboard row to carry it
        sp = share >= SP_SHARE
        rec = {key: num(r.get(f'WAR180_SP_{base + h}' if sp else f'WAR60_RP_{base + h}')) for h, key in HORIZONS.items()}
        rec['unit'] = 'SP180' if sp else 'RP60'
        rec['thin'] = r.get('thin_age_support') or ''
        pitchers[r['mlbId']] = rec
    if len(hitters) < 300 or len(pitchers) < 300:
        raise RuntimeError(f'hpWAR build: {len(hitters)} hitters / {len(pitchers)} pitchers; the projection inputs are '
                           f'incomplete. Re-run the pulls listed in this file docstring.')
    out = {'base': base, 'targets': {key: base + h for h, key in HORIZONS.items()}, 'built': date.today().isoformat(),
           'spShare': SP_SHARE, 'hitters': hitters, 'pitchers': pitchers}
    tmp = OUT + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(out, f, separators=(',', ':'), sort_keys=True)
    os.replace(tmp, OUT)
    print(f'wrote {os.path.relpath(OUT, ROOT)}: {len(hitters)} hitters, {len(pitchers)} pitchers '
          f'({sum(1 for v in pitchers.values() if v["unit"] == "SP180")} SP180)')


if __name__ == '__main__':
    main()
