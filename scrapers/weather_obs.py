"""weather_obs.py -- measured weather at the park for one game (Open-Meteo, no key).

The neutral-movement model (pipeline/neutral_move.py) needs station pressure, relative
humidity and the game-mean temperature at the park. The MLB feed carries none of the
first two and only a first-pitch temperature. This module is the single reader of the
measured values; it does no model math.

Two endpoints, tried in this order:
    archive   reanalysis, the source the model was fitted on. It runs several days behind.
    forecast  the same variables from the forecast models' recent hours (`past_days`).
              Used for a game too recent for the archive. The result is marked
              source='forecast' so the backfill can replace it once the archive has
              the day; an x value written from a forecast reading can change once.

The value for a game is the mean of the hours covering the first three hours of play
(the start hour and the next three), the rule the fit used.

Fail closed: any network or shape problem returns None and prints which game, and the
caller falls back to standard-atmosphere pressure and reports it. Nothing is guessed.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ARCHIVE_URL = 'https://archive-api.open-meteo.com/v1/archive'
FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'
HOURLY = 'temperature_2m,relative_humidity_2m,surface_pressure'
GAME_HOURS = 4                    # start hour plus the next three
FORECAST_PAST_DAYS = 14           # the forecast endpoint serves this many past days

# Parks whose feed entry has no coordinates (venue id -> lat, lon).
VENUE_COORDS_OVERRIDE = {
    5340: (19.4040, -99.0855),    # Estadio Alfredo Harp Helu, Mexico City
}


def _get(url, timeout=45):
    req = urllib.request.Request(url, headers={'User-Agent': 'python-weather-client'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _mean_over_game(hourly, start_utc):
    times = hourly.get('time') or []
    pos = {s: i for i, s in enumerate(times)}
    idx = [pos.get((start_utc + timedelta(hours=k)).strftime('%Y-%m-%dT%H:00')) for k in range(GAME_HOURS)]
    idx = [i for i in idx if i is not None]
    cols = []
    for key in ('temperature_2m', 'relative_humidity_2m', 'surface_pressure'):
        vals = [hourly[key][i] for i in idx if hourly.get(key) and hourly[key][i] is not None]
        if not vals:
            return None
        cols.append(sum(vals) / len(vals))
    return dict(tempF=round(cols[0], 2), rh=round(cols[1], 1), p_hpa=round(cols[2], 2), hours=len(idx))


def parse_start(start_iso):
    """Feed gameData.datetime.dateTime ('2026-04-25T22:05:00Z') -> naive UTC datetime, or None."""
    if not start_iso:
        return None
    try:
        return datetime.strptime(start_iso[:19], '%Y-%m-%dT%H:%M:%S')
    except ValueError:
        return None


def fetch_measured(lat, lon, elevation_ft, start_iso, game_pk=None):
    """Measured weather for one game, or None. Returns
    {'p_hpa', 'tempF', 'rh', 'hours', 'source': 'archive' | 'forecast'}."""
    start = parse_start(start_iso)
    if lat is None or lon is None or elevation_ft is None or start is None:
        print(f'  weather_obs: game {game_pk}: no coordinates, elevation or start time; no measured weather')
        return None
    base = dict(latitude=lat, longitude=lon, elevation=round(float(elevation_ft) * 0.3048, 1),
                hourly=HOURLY, temperature_unit='fahrenheit', timezone='UTC')
    day0 = (start - timedelta(days=1)).strftime('%Y-%m-%d'); day1 = (start + timedelta(days=1)).strftime('%Y-%m-%d')
    age_days = (datetime.now(timezone.utc).replace(tzinfo=None) - start).days
    tries = [('archive', ARCHIVE_URL, dict(base, start_date=day0, end_date=day1))]
    if age_days <= FORECAST_PAST_DAYS:
        tries.append(('forecast', FORECAST_URL, dict(base, past_days=FORECAST_PAST_DAYS, forecast_days=1)))
    for source, url, params in tries:
        try:
            data = _get(f'{url}?{urllib.parse.urlencode(params)}')
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print(f'  weather_obs: game {game_pk}: {source} request failed ({e})')
            continue
        got = _mean_over_game(data.get('hourly') or {}, start)
        if got:
            got['source'] = source
            return got
    print(f'  weather_obs: game {game_pk}: no measured weather from the archive or the forecast endpoint')
    return None


def venue_coords(venue):
    """(lat, lon) from a feed venue dict, with the override table as the fallback."""
    co = ((venue or {}).get('location') or {}).get('defaultCoordinates') or {}
    lat, lon = co.get('latitude'), co.get('longitude')
    if lat is None or lon is None:
        return VENUE_COORDS_OVERRIDE.get((venue or {}).get('id'), (None, None))
    return lat, lon
