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
# A feed temperature this far from the measured game mean is a feed error, not weather,
# and the measured value is used alone. CONVENTION, not a fitted constant: over 13,489
# open-air games 2021-2026 the feed runs 2.6 F above the measured mean with sd 4.0, and
# 4 games sit beyond 20 F. One of them reports 8 F on an August night in Florida
# (measured 79 F), which a 50/50 blend would still carry at half strength.
FEED_TEMP_MAX_GAP_F = 20.0

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
    feed_rejected = False
    if have:
        if closed:
            k = float(coef['roof_k'].get(str(venue_id), 0.0))
            temp = ROOF_CLOSED_TEMP_F + k * (float(measured['tempF']) - ROOF_CLOSED_TEMP_F)
            rho = float(moist_density(measured['p_hpa'], temp, ROOF_CLOSED_RH))
        else:
            w = float(coef['temp_blend_feed'])
            if feed_temp_f is None or abs(feed_t - float(measured['tempF'])) > FEED_TEMP_MAX_GAP_F:
                w = 0.0                      # no feed reading, or a feed error: measured alone
                feed_rejected = feed_temp_f is not None
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
                closed=closed, source=source, wind_ok=wind_ok, feed_temp_rejected=feed_rejected)


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


# ---------------------------------------------------------------------------------------
# The other pitch metrics (model `wm1`, 2026-11-21). Same idea as the movement columns:
# the raw column is what happened in that game's air, the x column is what the pitch
# would have read with no weather effect.
#
#     x = raw - (aP + bP * z) * lnP - (aT + bT * z) * lnT
#
# Release velocity, spin rate, extension and arm angle are what the PITCHER does, and only
# the temperature moves them (a warm arm throws harder): they carry aT alone. A pressure
# term was fitted and REJECTED for them: it closed the Coors gap and then failed at the
# Triple-A altitude parks with the opposite sign (velocity -0.10 mph at Coors, +0.23 mph
# there), so that gap is the park and not the air. The approach angles are FLIGHT: thin
# air drags less and bends less, so they carry all four terms, with z = the pitch's own
# neutral ride (VAA) or neutral arm-side run (HAA). Release height and release side were
# measured too and have no weather effect, so they have no x column.
# Fit and tests: scripts/research/weather/wx_all_metrics.py. Constants:
# data/neutral_movement_rs.json, block `metrics` (scripts/builders/build_neutral_movement.py).
# ---------------------------------------------------------------------------------------
# raw sheet column -> (x sheet column, key in the `metrics` block)
METRIC_COLUMNS = {'Velocity': ('xVelocity', 'velo'), 'Spin Rate': ('xSpinRate', 'spin'),
                  'Extension': ('xExtension', 'ext'), 'ArmAngle': ('xArmAngle', 'arm_angle'),
                  'VAA': ('xVAA', 'vaa'), 'HAA': ('xHAA', 'haa_arm')}
X_METRIC_COLUMNS = [v[0] for v in METRIC_COLUMNS.values()]


def metric_coefficients(coef=None):
    """The `metrics` block. Raises when the constants file predates it: there is no default."""
    c = coef or load_coefficients()
    m = c.get('metrics')
    if not m or any(k not in m for _, k in METRIC_COLUMNS.values()):
        raise RuntimeError(f'{COEF_PATH} has no complete `metrics` block. Run '
                           'scripts/builders/build_neutral_movement.py.')
    return m


def neutral_metric_arrays(raw, rhp, x_ivb, x_hb, ln_p, ln_t, coef=None):
    """Vectorized. `raw` maps a raw sheet column (a key of METRIC_COLUMNS) to a float array;
    rhp is a bool array; x_ivb / x_hb are the NEUTRAL movement columns in sheet convention
    (HorzBrk positive = a right-hander's arm side); ln_p / ln_t come from game_air.
    Returns {x column: array}. NaN in gives NaN out; nothing is rounded.

    HAA: the model is fitted on the arm-side angle, which is the sheet HAA times -1 for a
    right-hander and +1 for a left-hander, so the correction takes that sign back out."""
    m = metric_coefficients(coef)
    rhp = np.asarray(rhp, dtype=bool)
    ln_p, ln_t = np.asarray(ln_p, dtype=float), np.asarray(ln_t, dtype=float)
    out = {}
    for col, (xcol, key) in METRIC_COLUMNS.items():
        if col not in raw:
            continue
        v = np.asarray(raw[col], dtype=float)
        k = m[key]
        if key == 'vaa':
            z, sign = np.asarray(x_ivb, dtype=float), 1.0
        elif key == 'haa_arm':
            z, sign = np.where(rhp, 1.0, -1.0) * np.asarray(x_hb, dtype=float), np.where(rhp, -1.0, 1.0)
        else:
            z, sign = 0.0, 1.0
        shift = (k.get('aP', 0.0) + k.get('bP', 0.0) * z) * ln_p + (k['aT'] + k.get('bT', 0.0) * z) * ln_t
        out[xcol] = v - sign * shift
    return out


def neutral_metrics(raw, throws, x_ivb, x_hb, air, coef=None):
    """One pitch. `raw` maps raw sheet columns to values (None = missing). Returns
    ({x column: value or None}, mode). Not rounded: the caller rounds with the sheet
    precision map.

    mode 'raw'      no air for the game, or no hand: every x value equals the raw value
         'no_shape' an approach angle is present and its neutral movement is not: that x
                    value is None (a correction without the shape term would be a different
                    model, not a smaller one)
         'full'     every present metric was corrected
    """
    cols = [c for c in METRIC_COLUMNS if c in raw]
    if air is None or throws not in ('L', 'R'):
        return {METRIC_COLUMNS[c][0]: (None if raw[c] is None else float(raw[c])) for c in cols}, 'raw'
    f = lambda v: float('nan') if v is None else float(v)
    arr = neutral_metric_arrays({c: f(raw[c]) for c in cols}, throws == 'R', f(x_ivb), f(x_hb),
                                air['lnP'], air['lnT'], coef)
    out, mode = {}, 'full'
    for c in cols:
        xcol = METRIC_COLUMNS[c][0]
        v = float(arr[xcol])
        if raw[c] is None:
            out[xcol] = None
        elif math.isnan(v):
            out[xcol], mode = None, 'no_shape'
        else:
            out[xcol] = v
    return out, mode


def neutral_metric_table(raw, throws, x_ivb, x_hb, ln_p, ln_t, coef=None):
    """A table of pitches (the scraper's frame, a sheet tab, a corpus chunk).

    raw      {raw sheet column: float array, NaN = missing}
    throws   array of 'L' / 'R' / anything else
    x_ivb, x_hb   the neutral movement columns, float arrays
    ln_p, ln_t    per pitch, from game_air; NaN = the game has no air (no elevation)

    Returns ({x column: float array}, {mode: pitch count}). A pitch with no air or no hand
    keeps x equal to raw (mode 'raw'). An approach angle whose neutral movement is missing
    comes back NaN (mode 'no_shape'). Nothing is rounded.
    """
    throws = np.asarray(throws, dtype=object)
    ln_p, ln_t = np.asarray(ln_p, dtype=float), np.asarray(ln_t, dtype=float)
    ok = np.isfinite(ln_p) & np.isfinite(ln_t) & np.isin(throws, ('L', 'R'))
    zero = np.zeros(len(throws))
    arr = neutral_metric_arrays(raw, throws == 'R', x_ivb, x_hb, np.where(ok, ln_p, zero),
                                np.where(ok, ln_t, zero), coef)
    out, no_shape, tracked = {}, np.zeros(len(throws), dtype=bool), np.zeros(len(throws), dtype=bool)
    for col, (xcol, key) in METRIC_COLUMNS.items():
        if col not in raw:
            continue
        v = np.asarray(raw[col], dtype=float)
        out[xcol] = np.where(ok, arr[xcol], v)
        tracked |= np.isfinite(v)
        no_shape |= ok & np.isfinite(v) & ~np.isfinite(arr[xcol])
    modes = {'raw': int((tracked & ~ok).sum()), 'no_shape': int(no_shape.sum()),
             'full': int((tracked & ok & ~no_shape).sum())}
    return out, modes


# ---------------------------------------------------------------------------------------
# The read boundary. Since 2026-11-21 (per Wally: adjusted replaces raw) every reader of a
# pitch row sees the NEUTRAL value under the plain column name, and the value as tracked
# under `<column>_raw`. One swap, at the read (pipeline/fetch.py), so no consumer chooses.
# A consumer whose constants were fitted on tracked values reads raw_metric() instead and
# says why at the call.
# ---------------------------------------------------------------------------------------
RAW_SUFFIX = '_raw'


def swap_in_neutral_metrics(pitch):
    """In place, for a row from a tab that HAS the x metric columns: `Velocity` becomes the
    xVelocity cell and the tracked value moves to `Velocity_raw` (the same for all six).
    A blank x cell stays blank: there is no fall-back to the tracked value, the rule the
    movement columns have had since 2026-08-05. Returns the number of blank x cells whose
    tracked value is present, so the caller can report them."""
    stale = 0
    for col, (xcol, _) in METRIC_COLUMNS.items():
        raw, x = pitch.get(col), pitch.get(xcol)
        pitch[col + RAW_SUFFIX] = raw
        pitch[col] = x
        if x is None and raw is not None:
            stale += 1
    # The hitter columns (model hm1), when the row has them. Distance, BatSpeed and SwingLength
    # follow the same rule; AirwOBA has no tracked twin and stays under its own name.
    for col, xcol in HITTER_METRIC_COLUMNS.items():
        if xcol not in pitch:
            continue
        raw, x = pitch.get(col), pitch.get(xcol)
        pitch[col + RAW_SUFFIX] = raw
        pitch[col] = x
        if x is None and raw is not None:
            stale += 1
    return stale


def raw_metric(pitch, col):
    """The metric as tracked in that game's air. Falls through to the plain column for a row
    that never went through the swap (the 2021-2025 training pickles hold tracked values)."""
    k = col + RAW_SUFFIX
    return pitch[k] if k in pitch else pitch.get(col)


# ---------------------------------------------------------------------------------------
# The hitter side (model `hm1`, 2026-11-22). Three things the weather does to a swing and a
# batted ball, and nothing else:
#   CARRY   a ball hit at launch angle 10 or more flies farther in thin or warm air:
#               neutral distance = distance / exp(zP + zT)
#           zP = eP(u) * lnP, zT = eT(u) * lnT, u = (LA - 25) / 10, eP / eT quadratic in u.
#   VALUE   the wOBA that the air added to that ball: AirwOBA = s[band] * (zT + kappa * zP),
#           s = the value of a unit of log carry for the ball's (launch angle, exit velocity)
#           band, measured on temperature (every park has hot and cold days, so its fences
#           cancel). kappa is the share of the PRESSURE carry that reaches results; it is
#           measured on Triple-A altitude parks, because in MLB pressure is Coors and Coors's
#           field was built around its air. What is left at Coors after this is the field's
#           size, a park effect, not weather (per Wally 2026-11-22: air only).
#   SWING   a hitter swings faster on a warm day: bat speed and swing length, temperature only.
# Exit velocity, launch angle, whiffs and strikeouts also change at altitude, through the
# PITCH (it moves less). That is the matchup, not the air, and it is not adjusted.
# Fit and tests: scripts/research/weather/wx_flight_*.py and wx_swing_models.py.
# ---------------------------------------------------------------------------------------
# raw sheet column -> x sheet column (the same swap rule as METRIC_COLUMNS)
HITTER_METRIC_COLUMNS = {'Distance': 'xDistance', 'BatSpeed': 'xBatSpeed', 'SwingLength': 'xSwingLength'}
AIR_VALUE_COLUMN = 'AirwOBA'          # wOBA the air added to a ball in play; no raw twin
X_HITTER_COLUMNS = list(HITTER_METRIC_COLUMNS.values()) + [AIR_VALUE_COLUMN]


def hitter_coefficients(coef=None):
    c = coef or load_coefficients()
    if 'flight' not in c or 'swing' not in c:
        raise RuntimeError(f'{COEF_PATH} has no hitter blocks. Run scripts/builders/build_neutral_movement.py.')
    return c['flight'], c['swing']


def carry_log(la, ln_p, ln_t, coef=None):
    """(zP, zT): the log carry the air added, from pressure and from temperature. Zero below
    the minimum launch angle; NaN where the launch angle or the air is missing."""
    fl, _ = hitter_coefficients(coef)
    la = np.asarray(la, dtype=float)
    u = (la - fl['u_centre']) / fl['u_scale']
    air = np.where(la >= fl['la_min'], 1.0, 0.0)
    poly = lambda k: k[0] + k[1] * u + k[2] * u * u
    return air * poly(fl['eP']) * np.asarray(ln_p, dtype=float), air * poly(fl['eT']) * np.asarray(ln_t, dtype=float)


def neutral_hitter_table(raw, ev, la, bip, ln_p, ln_t, coef=None):
    """A table of pitches. raw = {'Distance' | 'BatSpeed' | 'SwingLength': float array};
    ev / la = exit velocity and launch angle; bip = bool array, the row is a ball in play.
    ln_p / ln_t per pitch (NaN = the game has no air: x equals raw and AirwOBA is blank).
    Returns ({x column: float array}, {mode: count}). Nothing is rounded.
      xDistance     NaN where the distance or the launch angle is missing
      AirwOBA       balls in play only; 0 for a ball outside the value bands (a grounder);
                    NaN when the ball has no exit velocity or launch angle
    """
    fl, sw = hitter_coefficients(coef)
    ln_p, ln_t = np.asarray(ln_p, dtype=float), np.asarray(ln_t, dtype=float)
    ok = np.isfinite(ln_p) & np.isfinite(ln_t)
    lp, lt = np.where(ok, ln_p, 0.0), np.where(ok, ln_t, 0.0)
    ev, la, bip = np.asarray(ev, dtype=float), np.asarray(la, dtype=float), np.asarray(bip, dtype=bool)
    z_p, z_t = carry_log(la, lp, lt, coef)
    out = {}
    if 'Distance' in raw:
        dist = np.asarray(raw['Distance'], dtype=float)
        out['xDistance'] = np.where(ok, dist / np.exp(z_p + z_t), dist)
    v = fl['value']
    la_e, ev_e = np.asarray(v['la_edges'], dtype=float), np.asarray(v['ev_edges'], dtype=float)
    a = np.digitize(la, la_e) - 1
    inb = np.isfinite(la) & np.isfinite(ev) & (la >= la_e[0]) & (la < la_e[-1])
    band = np.where(inb, np.clip(a, 0, len(la_e) - 2) * (len(ev_e) + 1) + np.digitize(np.nan_to_num(ev), ev_e), 0)
    s = np.where(inb, np.asarray(v['s'], dtype=float)[band], 0.0)
    air_v = s * (np.nan_to_num(z_t) + v['kappa'] * np.nan_to_num(z_p))
    out[AIR_VALUE_COLUMN] = np.where(bip & ok & np.isfinite(la) & np.isfinite(ev), air_v, np.nan)
    for col, key in (('BatSpeed', 'bat_speed'), ('SwingLength', 'swing_length')):
        if col in raw:
            x = np.asarray(raw[col], dtype=float)
            out[HITTER_METRIC_COLUMNS[col]] = np.where(ok, x - sw[key]['aT'] * lt, x)
    tracked = bip | np.isfinite(np.asarray(raw.get('BatSpeed', np.full(len(ok), np.nan)), dtype=float))
    return out, {'raw': int((tracked & ~ok).sum()), 'full': int((tracked & ok).sum())}
