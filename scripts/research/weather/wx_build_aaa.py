"""wx_build_aaa.py -- Triple-A audit frames, 2023-2026 (independent altitude replicate).

RESEARCH ONLY. Triple-A has four parks above 3,700 ft (Albuquerque, Salt Lake,
Reno, El Paso) plus Las Vegas at 3,010, so it tests whether the Coors result is
an ALTITUDE result or a Coors result. Weather and venue per game come from the
schedule API (hydrate=weather); elevation from VENUE_ELEVATION_FT_OVERRIDE, the
table production uses. Writes data/_weather_audit/frame_aaa_{yr}.npz and
aaa_weather.json.
"""
import os, sys, json, urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrapers.pitcher2026 import VENUE_ELEVATION_FT_OVERRIDE
import wx_build_frame as B

OUT = B.OUT
if __name__ == '__main__':
    wp = os.path.join(OUT, 'aaa_weather.json')
    store = json.load(open(wp)) if os.path.exists(wp) else {}
    for yr in (2023, 2024, 2025, 2026):
        if any(v.get('yr') == yr for v in store.values()):
            continue
        url = (f'https://statsapi.mlb.com/api/v1/schedule?sportId=11&season={yr}&gameType=R'
               f'&hydrate=weather&fields=dates,games,gamePk,gameDate,weather,condition,temp,venue,id')
        with urllib.request.urlopen(url, timeout=120) as r:
            j = json.load(r)
        for d in j.get('dates', []):
            for g in d.get('games', []):
                w = g.get('weather') or {}
                vid = (g.get('venue') or {}).get('id')
                try:
                    t = float(w.get('temp'))
                except (TypeError, ValueError):
                    t = None
                store[str(g['gamePk'])] = dict(yr=yr, venueId=vid, condition=w.get('condition'), tempF=t,
                                               elevationFt=VENUE_ELEVATION_FT_OVERRIDE.get(vid),
                                               t0=g.get('gameDate'))
        json.dump(store, open(wp, 'w'))
    print('AAA games with weather', len(store),
          'null temp', sum(v['tempF'] is None for v in store.values()),
          'null elev', sum(v['elevationFt'] is None for v in store.values()))
    for yr in (2023, 2024, 2025, 2026):
        fr = B.build_statcast(yr, os.path.join(ROOT, 'data', f'_aaa_statcast{yr}_cache.pkl'), store)
        np.savez_compressed(os.path.join(OUT, f'frame_aaa_{yr}.npz'), **fr)
        hi = fr['elev'] >= 3000
        print(f"AAA {yr}: {len(fr['pk'])} pitches, rho missing {np.isnan(fr['rho']).mean():.3%}, "
              f"pitches at 3000 ft or more {hi.sum()}", flush=True)
        del fr
