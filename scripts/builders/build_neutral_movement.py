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
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT), suffix='.tmp')
    with os.fdopen(fd, 'w') as f:
        json.dump(out, f, indent=1)
    os.replace(tmp, OUT)
    print(f'wrote {OUT}: run eP {out["run"]["eP"]} eT {out["run"]["eT"]}, ride eP {out["ride"]["eP"]} eT {out["ride"]["eT"]}, '
          f'crosswind {out["run"]["crosswind_in_per_mph"]:+.4f} in/mph, headwind {out["run"]["headwind_pct_per_mph"]:+.3f} / '
          f'{out["ride"]["headwind_pct_per_mph"]:+.3f} %/mph')


if __name__ == '__main__':
    main()
