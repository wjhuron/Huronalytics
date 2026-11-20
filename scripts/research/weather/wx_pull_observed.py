"""wx_pull_observed.py -- measured weather per game, 2021-2026 (research cache).

RESEARCH ONLY. For every game in the audit frames:
  1. game start (UTC) and venue from the MLB schedule API (one call per season)
  2. venue coordinates from the venues endpoint
  3. hourly temperature, relative humidity and surface pressure from the
     Open-Meteo archive at the venue's coordinates and the feed's elevation
     (one call per venue-season), averaged over the first three hours of play
Writes data/_weather_audit/game_obs.json: {gamePk: {t0, venue, tempF, rh, p_hpa}}.
Nothing here feeds production.
"""
import os, sys, json, time, urllib.request, urllib.parse
from datetime import datetime, timedelta
from collections import defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT = os.path.join(ROOT, 'data', '_weather_audit')
RAW = os.path.join(OUT, 'openmeteo'); os.makedirs(RAW, exist_ok=True)
UA = {'User-Agent': 'python-research-client'}


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
                return json.load(r)
        except Exception as e:                      # noqa: BLE001 -- retried, then raised
            if i == tries - 1:
                raise
            time.sleep(5 * (i + 1))


def main():
    need = {}
    for yr in (2021, 2022, 2023, 2024, 2025, 2026):
        z = np.load(os.path.join(OUT, f'frame_{yr}.npz'))
        pk, venue, elev = z['pk'], z['venue'], z['elev']
        _, idx = np.unique(pk, return_index=True)
        for i in idx:
            need[int(pk[i])] = (yr, int(venue[i]), float(elev[i]))
    sched_path = os.path.join(OUT, 'schedule_times.json')
    times = json.load(open(sched_path)) if os.path.exists(sched_path) else {}
    for yr in (2021, 2022, 2023, 2024, 2025, 2026):
        if any(v[0] == yr and str(k) not in times for k, v in need.items()):
            for sport in (1, 11):
                j = get(f'https://statsapi.mlb.com/api/v1/schedule?sportId={sport}&season={yr}'
                        f'&gameType=R&fields=dates,games,gamePk,gameDate,venue,id')
                for d in j.get('dates', []):
                    for g in d.get('games', []):
                        times[str(g['gamePk'])] = [g['gameDate'], g.get('venue', {}).get('id')]
            json.dump(times, open(sched_path, 'w'))
    print('games needed', len(need), 'with start time', sum(str(k) in times for k in need))
    venues = sorted({v[1] for v in need.values() if v[1] > 0})
    vpath = os.path.join(OUT, 'venue_coords.json')
    coords = json.load(open(vpath)) if os.path.exists(vpath) else {}
    miss = [v for v in venues if str(v) not in coords]
    if miss:
        j = get('https://statsapi.mlb.com/api/v1/venues?venueIds=' + ','.join(map(str, miss)) + '&hydrate=location')
        for v in j.get('venues', []):
            c = (v.get('location') or {}).get('defaultCoordinates') or {}
            coords[str(v['id'])] = [v.get('name'), c.get('latitude'), c.get('longitude')]
        json.dump(coords, open(vpath, 'w'))
    by_vy = defaultdict(list)
    for pk, (yr, v, el) in need.items():
        if str(pk) in times and str(v) in coords and coords[str(v)][1] is not None and el == el:
            by_vy[(v, yr, el)].append(pk)
    print('venue-seasons', len(by_vy))
    obs_path = os.path.join(OUT, 'game_obs.json')
    obs = json.load(open(obs_path)) if os.path.exists(obs_path) else {}
    for (v, yr, el), pks in sorted(by_vy.items()):
        if all(str(p) in obs for p in pks):
            continue
        f = os.path.join(RAW, f'{v}_{yr}.json')
        if os.path.exists(f):
            h = json.load(open(f))
        else:
            ts = [datetime.strptime(times[str(p)][0][:19], '%Y-%m-%dT%H:%M:%S') for p in pks]
            q = urllib.parse.urlencode(dict(
                latitude=coords[str(v)][1], longitude=coords[str(v)][2], elevation=round(el * 0.3048, 1),
                start_date=(min(ts) - timedelta(days=1)).strftime('%Y-%m-%d'),
                end_date=(max(ts) + timedelta(days=1)).strftime('%Y-%m-%d'),
                hourly='temperature_2m,relative_humidity_2m,surface_pressure',
                temperature_unit='fahrenheit', timezone='UTC'))
            h = get(f'https://archive-api.open-meteo.com/v1/archive?{q}').get('hourly', {})
            json.dump(h, open(f, 'w'))
            time.sleep(1.0)
        if not h.get('time'):
            print('  no data', v, yr); continue
        pos = {s: i for i, s in enumerate(h['time'])}
        for p in pks:
            t = datetime.strptime(times[str(p)][0][:19], '%Y-%m-%dT%H:%M:%S')
            ii = [pos.get((t + timedelta(hours=k)).strftime('%Y-%m-%dT%H:00')) for k in (0, 1, 2, 3)]
            ii = [i for i in ii if i is not None]
            vals = [[h[key][i] for i in ii if h[key][i] is not None]
                    for key in ('temperature_2m', 'relative_humidity_2m', 'surface_pressure')]
            if not all(vals):
                continue
            obs[str(p)] = dict(t0=times[str(p)][0], venue=v, tempF=round(float(np.mean(vals[0])), 2),
                               temp_first=vals[0][0], temp_last=vals[0][-1],
                               rh=round(float(np.mean(vals[1])), 1), p_hpa=round(float(np.mean(vals[2])), 2))
        json.dump(obs, open(obs_path, 'w'))
        print(f'  {coords[str(v)][0]} {yr}: {len(pks)} games', flush=True)
    print('observed games', len(obs), 'of', len(need))


if __name__ == '__main__':
    main()
