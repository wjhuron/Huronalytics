"""build_hpwar.py: write data/hpwar_projections.json, the static input behind the site's hpWAR columns.

hpWAR is the PROJECTED sibling of hdWAR (the site label of the descriptive hWAR): wins above
replacement projected 1, 3 and 5 seasons past BASE, as a RATE.
  hitters    per 600 PA, neutral park (projections_hitters.csv WAR600_*)
  pitchers   per 180 IP if his BASE start share is .5 or more (SP180), else per 60 IP (RP60)
             (projections_pitchers.csv WAR180_SP_* / WAR60_RP_*)
Rochester and other Triple-A rows get nothing (per Wally 2026-10-02): the Triple-A bridges are weak.

hpWARtot (2026-10-07) is the one-season TOTAL: hpWAR times projected playing time (hpWAR_pt, IP or PA
in 2027, from scripts/research/projection/pt_backtest.py; zero playing time counts, so injury and
demotion risk are inside it), over the unit's IP or PA. Next season only (per Wally).

Method, backtests and limits: scripts/research/projection/project_players.py and the methods doc
(Google Doc "Huronalytics hWAR audit and projection model: methods (2026-10-02)"). In short: three
seasons of history regressed to league (four for batting), xwOBA/wOBA 75/25 for batting, Stuff+ in the pitcher level,
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
import pt_backtest  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'hpwar_projections.json')
HORIZONS = {1: 'hpWAR', 3: 'hpWAR3', 5: 'hpWAR5'}
UNIT_PT = {'PA600': 600.0, 'SP180': 180.0, 'RP60': 60.0}
SP_SHARE = 0.5     # role cut for the pitcher unit; a convention (a starter is a pitcher who mostly starts)


def num(v):
    return None if v in (None, '') else float(v)


def add_total(rec, pt):
    """hpWAR_pt (projected 2027 IP or PA) and hpWARtot = hpWAR x pt / unit. A player outside the
    playing-time pool keeps the rate and gets no total, never a zero."""
    if pt is None or rec['hpWAR'] is None:
        rec['pt'] = rec['tot'] = None
        return
    rec['pt'] = round(pt, 1)
    rec['tot'] = round(rec['hpWAR'] * pt / UNIT_PT[rec['unit']], 2)


def main():
    project_players.main()
    base = project_players.BASE
    P = project_players.P
    hitters, pitchers = {}, {}
    pt = {'hitters': pt_backtest.project('hit', base), 'pitchers': pt_backtest.project('pit', base)}
    for r in csv.DictReader(open(os.path.join(P, 'projections_hitters.csv'))):
        rec = {key: num(r.get(f'WAR600_{base + h}')) for h, key in HORIZONS.items()}
        if all(v is None for v in rec.values()):
            continue
        rec['unit'] = 'PA600'
        rec['thin'] = r.get('thin_age_support') or ''
        add_total(rec, pt['hitters'].get(int(r['mlbId'])))
        hitters[r['mlbId']] = rec
    for r in csv.DictReader(open(os.path.join(P, 'projections_pitchers.csv'))):
        share = num(r.get('gs_share_2026'))
        if share is None:
            continue                     # no BASE season: no leaderboard row to carry it
        sp = share >= SP_SHARE
        rec = {key: num(r.get(f'WAR180_SP_{base + h}' if sp else f'WAR60_RP_{base + h}')) for h, key in HORIZONS.items()}
        rec['unit'] = 'SP180' if sp else 'RP60'
        rec['thin'] = r.get('thin_age_support') or ''
        add_total(rec, pt['pitchers'].get(int(r['mlbId'])))
        pitchers[r['mlbId']] = rec
    n_tot = {s: sum(v['tot'] is not None for v in d.values()) for s, d in (('hitters', hitters), ('pitchers', pitchers))}
    if n_tot['hitters'] < 0.9 * len(hitters) or n_tot['pitchers'] < 0.9 * len(pitchers):
        raise RuntimeError(f'hpWAR build: totals for only {n_tot} of {len(hitters)} hitters / {len(pitchers)} pitchers; '
                           f'the playing-time pool does not cover the projection pool. Check pt_backtest.py inputs.')
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
