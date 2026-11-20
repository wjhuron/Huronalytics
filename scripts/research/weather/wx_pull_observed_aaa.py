"""wx_pull_observed_aaa.py -- measured weather for Triple-A games 2023-2026 (research cache).
Same source and rule as wx_pull_observed.py. Writes data/_weather_audit/game_obs_aaa.json."""
import os, sys, json, time, urllib.parse
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wx_pull_observed import get, OUT, RAW

if __name__ == '__main__':
    st = json.load(open(os.path.join(OUT, 'aaa_weather.json')))
    vpath = os.path.join(OUT, 'venue_coords.json'); coords = json.load(open(vpath))
    vs = sorted({v['venueId'] for v in st.values() if v.get('venueId') and v.get('elevationFt') is not None})
    miss = [v for v in vs if str(v) not in coords]
    if miss:
        j = get('https://statsapi.mlb.com/api/v1/venues?venueIds=' + ','.join(map(str, miss)) + '&hydrate=location')
        for v in j.get('venues', []):
            c = (v.get('location') or {}).get('defaultCoordinates') or {}
            coords[str(v['id'])] = [v.get('name'), c.get('latitude'), c.get('longitude')]
        json.dump(coords, open(vpath, 'w'))
    by = defaultdict(list)
    for pk, v in st.items():
        c = coords.get(str(v.get('venueId')))
        if c and c[1] is not None and v.get('elevationFt') is not None and v.get('t0'):
            by[(v['venueId'], v['yr'], v['elevationFt'])].append(pk)
    opath = os.path.join(OUT, 'game_obs_aaa.json')
    obs = json.load(open(opath)) if os.path.exists(opath) else {}
    for (v, yr, el), pks in sorted(by.items()):
        if all(p in obs for p in pks):
            continue
        f = os.path.join(RAW, f'aaa_{v}_{yr}.json')
        if os.path.exists(f):
            h = json.load(open(f))
        else:
            ts = [datetime.strptime(st[p]['t0'][:19], '%Y-%m-%dT%H:%M:%S') for p in pks]
            q = urllib.parse.urlencode(dict(latitude=coords[str(v)][1], longitude=coords[str(v)][2],
                elevation=round(el * 0.3048, 1), start_date=(min(ts) - timedelta(days=1)).strftime('%Y-%m-%d'),
                end_date=(max(ts) + timedelta(days=1)).strftime('%Y-%m-%d'),
                hourly='temperature_2m,relative_humidity_2m,surface_pressure', temperature_unit='fahrenheit', timezone='UTC'))
            h = get(f'https://archive-api.open-meteo.com/v1/archive?{q}').get('hourly', {})
            json.dump(h, open(f, 'w')); time.sleep(1.0)
        if not h.get('time'):
            continue
        pos = {s: i for i, s in enumerate(h['time'])}
        for p in pks:
            t = datetime.strptime(st[p]['t0'][:19], '%Y-%m-%dT%H:%M:%S')
            ii = [pos.get((t + timedelta(hours=k)).strftime('%Y-%m-%dT%H:00')) for k in range(4)]
            ii = [i for i in ii if i is not None]
            vals = [[h[key][i] for i in ii if h[key][i] is not None]
                    for key in ('temperature_2m', 'relative_humidity_2m', 'surface_pressure')]
            if all(vals):
                obs[p] = dict(t0=st[p]['t0'], venue=v, tempF=round(float(np.mean(vals[0])), 2), temp_first=vals[0][0],
                              temp_last=vals[0][-1], rh=round(float(np.mean(vals[1])), 1), p_hpa=round(float(np.mean(vals[2])), 2))
        json.dump(obs, open(opath, 'w'))
        print(f'  {coords[str(v)][0]} {yr}: {len(pks)}', flush=True)
    print('observed AAA games', len(obs), 'of', len(st))
