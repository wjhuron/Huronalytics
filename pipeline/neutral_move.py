"""neutral_move.py -- neutral-environment pitch movement (xIndVrtBrk / xHorzBrk).

IndVertBrk / HorzBrk are what the pitch did in the air of that game. The x columns
are what it would have done in a neutral environment: standard air, no wind, no
roof effect. This module is the single home of that conversion. The scraper, the
sheet backfill and the training-set builders all call it; none of them carries a
copy of the math or of a constant.

Model (per component; run is in the arm-side frame, ride is IndVertBrk):

    neutral = (raw - shift) / (exp(eP * lnP + eT * lnT) * (1 + headwind * head / 100))
    shift   = bP[cell] * lnP + bT[cell] * lnT  (+ crosswind * cross, run only)

    lnP   ln(air density / reference) with the temperature part removed: measured
          station pressure and humidity
    lnT   the temperature part. Open air: the mean of the feed reading and the
          measured game mean. Closed roof: 72 F, except three roofs that follow the
          outside air part of the way (ROOF_K in the coefficient file).
    cell  the pitch's own spin-axis direction (30-degree sectors, arm-side frame) and
          speed, read from the sheet RTilt and Velocity. It reads NO pitch tag, so a
          retag cannot move an x value. Coefficients are interpolated between cell
          centres, so a pitch near a cell edge does not jump.
    head / cross  the feed wind, mph, positive = blowing out / left field to right field.

Pressure and temperature carry separate exponents because the temperature reading is
the noisier input; one pooled exponent under-corrects altitude. Every constant lives in
data/neutral_movement_rs.json, written by scripts/builders/build_neutral_movement.py
from the fit in scripts/research/weather/ (six seasons, leave-one-season-out, checked
unchanged on Triple-A altitude parks). There is no park term and no hand term: both
were measured and left out on purpose (2026-11-20, per Wally) because neither is weather.

Degrade paths, each reported in the returned `mode` so the caller can count them:
    'full'       measured weather, spin axis and velocity present
    'no_cell'    no RTilt or no velocity: exponents and wind only
    'standard'   no measured weather: standard-atmosphere pressure, feed temperature
    'raw'        no elevation: the raw value is returned unchanged. Callers MUST log
                 this one; a silent factor of 1.0 is how whole parks went unadjusted.
"""
import json
import math
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COEF_PATH = os.path.join(ROOT, 'data', 'neutral_movement_rs.json')

ROOF_CLOSED_CONDITIONS = {'dome', 'roof closed'}
ROOF_CLOSED_TEMP_F = 72.0       # convention: conditioned indoor air (see the research note)
ROOF_CLOSED_RH = 50.0           # convention: indoor relative humidity
DEFAULT_TEMP_F = 70.0           # used only when the feed has no temperature

# Feed wind words -> (head, cross) unit parts. Head is positive when the wind blows
# out (against the pitch); cross is positive from left field toward right field.
WIND_DIRS = {'Out To CF': (1.0, 0.0), 'Out To RF': (0.707, 0.707), 'Out To LF': (0.707, -0.707),
             'In From CF': (-1.0, 0.0), 'In From RF': (-0.707, -0.707), 'In From LF': (-0.707, 0.707),
             'L To R': (0.0, 1.0), 'R To L': (0.0, -1.0), 'Calm': (0.0, 0.0), 'None': (0.0, 0.0),
             'Varies': (0.0, 0.0)}

_COEF = None


def load_coefficients(path=COEF_PATH):
    """The fitted constants. Raises if the file is absent: there is no built-in default,
    because a default would silently replace the fitted model."""
    global _COEF
    if _COEF is None or path != COEF_PATH:
        with open(path) as f:
            c = json.load(f)
        for lab in ('run', 'ride'):
            for k in ('bP', 'bT'):
                c[lab][k] = np.asarray(c[lab][k], dtype=float)
        c['speed_centres'] = np.asarray(c['speed_centres'], dtype=float)
        if path != COEF_PATH:
            return c
        _COEF = c
    return _COEF


def moist_density(p_hpa, temp_f, rh_pct):
    """Air density (kg/m^3) from station pressure, temperature and relative humidity."""
    t = (np.asarray(temp_f, dtype=float) - 32.0) * 5.0 / 9.0 + 273.15
    p = np.asarray(p_hpa, dtype=float) * 100.0
    es = 610.94 * np.exp(17.625 * (t - 273.15) / (t - 30.11))
    e = np.clip(rh_pct, 0.0, 100.0) / 100.0 * es
    return (p - e) / (287.05 * t) + e / (461.495 * t)


def standard_pressure_hpa(elevation_ft):
    """Standard-atmosphere station pressure. The fallback when no measurement exists;
    it reads about 0.9% low at Coors in season."""
    return 1013.25 * (1.0 - 2.2558e-5 * float(elevation_ft) * 0.3048) ** 5.2556


def parse_wind(wind_str):
    """Feed wind string ('12 mph, Out To CF') -> (head mph, cross mph, recognised)."""
    if not wind_str or ',' not in wind_str:
        return 0.0, 0.0, False
    speed, direction = wind_str.split(',', 1)
    parts = WIND_DIRS.get(direction.strip())
    try:
        mph = float(speed.split()[0])
    except (ValueError, IndexError):
        return 0.0, 0.0, False
    if parts is None:
        return 0.0, 0.0, False
    return mph * parts[0], mph * parts[1], True


def game_air(elevation_ft, feed_temp_f, condition, venue_id=None, measured=None, wind=None, coef=None):
    """Everything the model needs about one game's air.

    measured: dict with 'p_hpa', 'tempF', 'rh' (station pressure, game-mean temperature and
    relative humidity at the park), or None. Returns None when there is no elevation.
    """
    coef = coef or load_coefficients()
    if elevation_ft is None:
        return None
    closed = (condition or '').strip().lower() in ROOF_CLOSED_CONDITIONS
    feed_t = float(feed_temp_f) if feed_temp_f is not None else DEFAULT_TEMP_F
    have = bool(measured) and all(measured.get(k) is not None for k in ('p_hpa', 'tempF', 'rh'))
    if have:
        if closed:
            k = float(coef['roof_k'].get(str(venue_id), 0.0))
            temp = ROOF_CLOSED_TEMP_F + k * (float(measured['tempF']) - ROOF_CLOSED_TEMP_F)
            rho = float(moist_density(measured['p_hpa'], temp, ROOF_CLOSED_RH))
        else:
            w = float(coef['temp_blend_feed'])
            temp = w * feed_t + (1.0 - w) * float(measured['tempF'])
            rho = float(moist_density(measured['p_hpa'], temp, measured['rh']))
        source = 'measured'
    else:
        temp = ROOF_CLOSED_TEMP_F if closed else feed_t
        rho = float(moist_density(standard_pressure_hpa(elevation_ft), temp, 0.0))
        source = 'standard'
    ln_t = -math.log(((temp - 32.0) * 5.0 / 9.0 + 273.15) / float(coef['t0_k']))
    ln_p = math.log(rho / float(coef['rho0'])) - ln_t
    head, cross, wind_ok = (0.0, 0.0, False) if closed else parse_wind(wind)
    return dict(lnP=ln_p, lnT=ln_t, head=head, cross=cross, rho=rho, temp_used=temp,
                closed=closed, source=source, wind_ok=wind_ok)


def tilt_to_axis(val):
    """Sheet RTilt (clock value, 'H:MM' or minutes) -> spin-axis degrees (12:00 = 180)."""
    if val is None or val == '':
        return float('nan')
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        m = float(val) % 720.0
    elif isinstance(val, str) and ':' in val:
        try:
            h, mm = val.strip().split(':')[:2]
            m = (int(h) % 12) * 60.0 + int(mm)
        except (ValueError, IndexError):
            return float('nan')
    else:
        return float('nan')
    return ((m / 60.0 + 6.0) * 30.0) % 360.0


def _cell_coefs(axis_deg, velo, rhp, comp_coef, speed_centres, sector_deg):
    """Interpolated (bP, bT) per pitch. Angle is periodic; speed is clamped at the end centres."""
    n_sec = int(round(360.0 / sector_deg)); n_sp = len(speed_centres)
    phi = np.radians(axis_deg)
    ux = np.where(rhp, -np.sin(phi), np.sin(phi)); uz = -np.cos(phi)       # (run arm-side, ride)
    ang = (np.degrees(np.arctan2(uz, ux)) + 360.0) % 360.0
    a = (ang - sector_deg / 2.0) / sector_deg
    a0 = np.floor(a).astype(int); wa = a - a0
    s0 = np.clip(np.searchsorted(speed_centres, velo) - 1, 0, n_sp - 2)
    ws = np.clip((velo - speed_centres[s0]) / (speed_centres[s0 + 1] - speed_centres[s0]), 0.0, 1.0)
    out = []
    for key in ('bP', 'bT'):
        b = comp_coef[key]; tot = 0.0
        for da, w1 in ((0, 1.0 - wa), (1, wa)):
            for ds, w2 in ((0, 1.0 - ws), (1, ws)):
                tot = tot + w1 * w2 * b[((a0 + da) % n_sec) * n_sp + (s0 + ds)]
        out.append(tot)
    return out[0], out[1]


def neutral_components(run, ride, rhp, axis_deg, velo, ln_p, ln_t, head, cross, coef=None):
    """Vectorised core. run is arm-side positive. Inputs broadcast. Returns
    (neutral run, neutral ride, has_cell). A pitch with no axis or velocity gets the
    exponents and the wind terms only."""
    coef = coef or load_coefficients()
    run, ride, rhp, axis_deg, velo, ln_p, ln_t, head, cross = np.broadcast_arrays(
        *[np.asarray(v) for v in (run, ride, rhp, axis_deg, velo, ln_p, ln_t, head, cross)])
    rhp = rhp.astype(bool)
    axis_deg = axis_deg.astype(float); velo = velo.astype(float)
    has_cell = np.isfinite(axis_deg) & np.isfinite(velo)
    ax = np.where(has_cell, axis_deg, 0.0); ve = np.where(has_cell, velo, float(coef['speed_centres'][0]))
    out = []
    for lab, raw in (('run', run), ('ride', ride)):
        c = coef[lab]
        b_p, b_t = _cell_coefs(ax, ve, rhp, c, coef['speed_centres'], float(coef['sector_deg']))
        shift = np.where(has_cell, b_p * ln_p + b_t * ln_t, 0.0)
        if lab == 'run':
            shift = shift + c['crosswind_in_per_mph'] * cross * np.where(rhp, -1.0, 1.0)
        factor = np.exp(c['eP'] * ln_p + c['eT'] * ln_t) * (1.0 + c['headwind_pct_per_mph'] * head / 100.0)
        out.append((raw.astype(float) - shift) / factor)
    return out[0], out[1], has_cell


def neutral_movement(ivb, hb, throws, rtilt, velo, air, coef=None):
    """One pitch, sheet conventions in and out (HorzBrk positive = a right-hander's arm side).

    Returns (x_ivb, x_hb, mode). Values are NOT rounded: the caller rounds with the
    sheet precision map. A missing raw value comes back as None.
    """
    if air is None or throws not in ('L', 'R'):
        return ivb, hb, 'raw'
    rhp = throws == 'R'
    run = float('nan') if hb is None else (float(hb) if rhp else -float(hb))
    ride = float('nan') if ivb is None else float(ivb)
    axis = tilt_to_axis(rtilt)
    v = float('nan') if velo is None else float(velo)
    n_run, n_ride, has_cell = neutral_components(run, ride, rhp, axis, v, air['lnP'], air['lnT'],
                                                 air['head'], air['cross'], coef)
    x_hb = None if hb is None else float(n_run if rhp else -n_run)
    x_ivb = None if ivb is None else float(n_ride)
    mode = 'standard' if air.get('source') != 'measured' else ('full' if bool(has_cell) else 'no_cell')
    return x_ivb, x_hb, mode
