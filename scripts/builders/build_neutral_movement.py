"""build_neutral_movement.py -- write data/neutral_movement_rs.json.

The constants of the neutral-environment movement model (pipeline/neutral_move.py).
Nothing here is fitted: the fit lives in scripts/research/weather/ and this script only
packages its result, so the shipped file can be traced to one research run.

Source: data/_weather_audit/final_fit_smooth.json (written by
scripts/research/weather/wx_smooth_check.py: six MLB seasons 2021-2026, the full-sample
fit at the exponents the leave-one-season-out search picked in every fold).

Provenance of each constant (the sweep that decided it):
    eP, eT                wx_final_fit.py   grid .05 / .10, interior optimum, same pick +- one step in 6/6 folds
    bP, bT (36 cells)     wx_final_fit.py   least squares at those exponents; cell = 30-degree spin-axis
                                            sector x 3 speed bands. Sector width 15 / 30 / 45 is FLAT
                                            (wx_cell_shift.py); the band cuts 84 / 90 mph are a CONVENTION
    crosswind, headwind   wx_joint.py       6/6 and 5/6 held-out seasons
    temp_blend_feed       wx_cell_shift.py  grid 0 / .25 / .5 / .75 / 1, interior optimum at .5, 6/6 seasons
    roof_k                wx_roof_ingame.py grid step .1, interior optimum, held-out 4/5, 6/6, 6/6;
                                            every other roof stays at 72 F as a CONVENTION
    rho0, t0_k            CONVENTION        sea level at 72.4 F, the reference the columns have always used

Usage: python3 scripts/builders/build_neutral_movement.py [path to final_fit_smooth.json]
"""
import json
import os
import sys
import tempfile
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, 'data', 'neutral_movement_rs.json')
DEFAULT_SRC = os.path.join(ROOT, 'data', '_weather_audit', 'final_fit_smooth.json')
METRICS_SRC = os.path.join(ROOT, 'data', '_weather_audit', 'all_metrics_temp.json')
FLIGHT_SRC = os.path.join(ROOT, 'data', '_weather_audit', 'flight_final.json')
SWING_SRC = os.path.join(ROOT, 'data', '_weather_audit', 'swing_models.json')
VALUE_LAYOUT = 'la8 x ev6 (85..105 by 5, 110)'
VALUE_KAPPA = 0.85

ROOF_K = {'14': 0.4, '32': 0.5, '680': 0.6}      # Rogers Centre, American Family Field, T-Mobile Park


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    if not os.path.exists(src):
        raise SystemExit(f'{src} is missing. Run scripts/research/weather/wx_smooth_check.py first.')
    with open(src) as f:
        fit = json.load(f)
    k = fit['K']
    if k != 36 or len(fit['speed_centres']) != 3:
        raise SystemExit(f'unexpected cell layout (K={k}); the module expects 12 sectors x 3 speed centres')
    out = dict(version='nm1', built=str(date.today()), rho0=1.195, t0_k=295.6, temp_blend_feed=0.5,
               sector_deg=30.0, speed_centres=[round(x, 3) for x in fit['speed_centres']], roof_k=ROOF_K)
    for lab in ('run', 'ride'):
        b = fit['fit'][lab]['b']
        if len(b) < 2 * k + 2:
            raise SystemExit(f'{lab}: coefficient vector too short ({len(b)})')
        if b[2 * k + 2:] and any(abs(x) > 0 for x in b[2 * k + 2:]):
            raise SystemExit(f'{lab}: a hand or park coefficient is not zero; the shipped model has neither')
        out[lab] = dict(eP=fit['fit'][lab]['eP'], eT=fit['fit'][lab]['eT'],
                        bP=b[:k], bT=b[k:2 * k],
                        crosswind_in_per_mph=b[2 * k] if lab == 'run' else 0.0,
                        headwind_pct_per_mph=b[2 * k + 1])
    # The other pitch metrics (model wm1). Source: all_metrics_temp.json, written by
    # scripts/research/weather/wx_all_metrics.py temp. Six-season fit; each term passed the
    # held-out Coors, in-month heat and Triple-A altitude tests there. The pressure term of
    # the four pitcher-output metrics was fitted and rejected (it fails at Triple-A altitude).
    if not os.path.exists(METRICS_SRC):
        raise SystemExit(f'{METRICS_SRC} is missing. Run scripts/research/weather/wx_all_metrics.py temp first.')
    with open(METRICS_SRC) as f:
        mf = json.load(f)
    if mf.get('mode') != 'temp':
        raise SystemExit(f'{METRICS_SRC} is not the temp-mode fit')
    want = {'velo': ('aT',), 'spin': ('aT',), 'ext': ('aT',), 'arm_angle': ('aT',),
            'vaa': ('aP', 'aT', 'bP', 'bT'), 'haa_arm': ('aP', 'aT', 'bP', 'bT')}
    out['metrics_version'] = 'wm1'
    out['metrics'] = {}
    for key, terms in want.items():
        got = mf['fit'][key]
        extra = set(got) - set(terms) - {'loc', 'velo'}
        if extra or any(t not in got for t in terms):
            raise SystemExit(f'metric {key}: fit terms {sorted(got)} do not match the shipped form {terms}')
        out['metrics'][key] = {t: got[t] for t in terms}
    # The hitter side (model hm1). Sources, all written by scripts/research/weather/:
    #   flight_final.json  (wx_flight_final.py)  carry exponents (quadratic in launch angle; held-out
    #                      error flat past quadratic) and the ball-value sensitivities s per contact
    #                      band (layout la8 x ev6: INTERIOR optimum of the held-out error over 4 to
    #                      280 bands, flat from 35 to 105)
    #   swing_models.json  (wx_swing_models.py)  bat speed (3 seasons) and swing length (2), aT only
    # KAPPA 0.85 = the share of the pressure carry that reaches results, measured on Triple-A
    # altitude parks with the MLB fit unchanged: the altitude gap crosses zero at 0.86 (seasons
    # 0.64, 1.0, 1.0; physics says 1.0). The per-ball error objective there reads 0.5 to 0.6, but
    # noise in s pulls that optimum down; the gap is the unbiased objective for a mean. In MLB the
    # number cannot be measured: pressure is Coors, and Coors was built around its air.
    for src_ in (FLIGHT_SRC, SWING_SRC):
        if not os.path.exists(src_):
            raise SystemExit(f'{src_} is missing. Run the research script that writes it.')
    with open(FLIGHT_SRC) as f:
        ff = json.load(f)
    with open(SWING_SRC) as f:
        sw = json.load(f)
    lay = ff['layouts'][VALUE_LAYOUT]
    if ff['pick'] != VALUE_LAYOUT:
        raise SystemExit(f"the held-out search now picks {ff['pick']!r}, not {VALUE_LAYOUT!r}: read the curve before shipping")
    dfit = ff['distance']['fit']
    if ff['distance']['form'] != 'quadratic' or len(dfit) != 6 or len(lay['s']) != (len(lay['la']) - 1) * (len(lay['ev']) + 1):
        raise SystemExit('unexpected carry form or value layout')
    out['hitter_version'] = 'hm1'
    out['flight'] = dict(la_min=ff['distance']['la_min'], u_centre=ff['distance']['u_centre'], u_scale=ff['distance']['u_scale'],
                         eP=dfit[:3], eT=dfit[3:], value=dict(la_edges=lay['la'], ev_edges=lay['ev'], s=lay['s'], kappa=VALUE_KAPPA))
    out['swing'] = {'bat_speed': {'aT': sw['bs|T']['fit'][0]}, 'swing_length': {'aT': sw['sl|T']['fit'][0]}}
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT), suffix='.tmp')
    with os.fdopen(fd, 'w') as f:
        json.dump(out, f, indent=1)
    os.replace(tmp, OUT)
    print(f'wrote {OUT}: run eP {out["run"]["eP"]} eT {out["run"]["eT"]}, ride eP {out["ride"]["eP"]} eT {out["ride"]["eT"]}, '
          f'crosswind {out["run"]["crosswind_in_per_mph"]:+.4f} in/mph, headwind {out["run"]["headwind_pct_per_mph"]:+.3f} / '
          f'{out["ride"]["headwind_pct_per_mph"]:+.3f} %/mph')


if __name__ == '__main__':
    main()
