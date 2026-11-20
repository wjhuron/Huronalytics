"""wx_module_check.py -- pipeline/neutral_move.py against the research code.

1. Core math: the module's neutral_components must equal wx_smooth_check.adjust
   (smooth cells, multiplicative headwind) on every 2026 pitch, to rounding error.
2. Air: the module's game_air must reproduce the research density for every game.
3. Per-pitch entry point: neutral_movement on sheet-style values equals the vector core.
Run from the repo that holds pipeline/neutral_move.py; reads the audit scratch via WX_OUT.
"""
import os, sys, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wx_exponent_sweep as E
if os.environ.get('WX_OUT'):
    E.OUT = os.environ['WX_OUT']
from wx_exponent_sweep import load, RHO0
from wx_cell_shift import prep as prep_cs
from wx_wind_hand_month import wind_arrays
import wx_cell_shift, wx_joint_split as J, wx_smooth_check as S
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
from pipeline import neutral_move as NM

if __name__ == '__main__':
    OUT = E.OUT
    for m in (wx_cell_shift, J, S):
        m.OUT = OUT
    coef = NM.load_coefficients()
    fit = json.load(open(os.path.join(OUT, 'final_fit_smooth.json')))
    S.SPEED_C = np.array(fit['speed_centres']); K = fit['K']
    obs = json.load(open(os.path.join(OUT, 'game_obs.json'))); W = json.load(open(os.path.join(OUT, 'wind.json')))
    d = prep_cs(load(2026, obs), 'w50')
    lnP, lnT = J.parts(d)
    head, cross = wind_arrays(d['pk'], W)
    head = np.where(d['closed'] | ~np.isfinite(head), 0.0, head); cross = np.where(d['closed'] | ~np.isfinite(cross), 0.0, cross)
    ref = {}
    for comp, lab in (('hb_arm', 'run'), ('ivb', 'ride')):
        f = dict(eP=fit['fit'][lab]['eP'], eT=fit['fit'][lab]['eT'], b=np.array(fit['fit'][lab]['b']))
        ref[lab], _, _ = S.adjust(d, lab, comp, f, K, lnP, lnT, head, cross, True, True)
    run, ride, has = NM.neutral_components(d['hb_arm'], d['ivb'], d['rhp'], d['axis'], d['velo'], lnP, lnT, head, cross, coef)
    print(f'1. core math on {len(run)} pitches: max |diff| run {np.max(np.abs(run - ref["run"])):.2e}, ride {np.max(np.abs(ride - ref["ride"])):.2e}')
    # 2. air per game
    side = json.load(open(os.path.join(os.environ.get('WX_SIDECAR', os.path.join(os.path.dirname(OUT), 'game_weather_rs.json')))))
    u, first = np.unique(d['pk'], return_index=True)
    worst = 0.0; nchk = 0
    for pk, i in zip(u, first):
        s = side.get(str(int(pk))); o = obs.get(str(int(pk)))
        if not s or not o or d['venue'][i] in (14, 32, 680) and d['closed'][i]:
            continue                       # the three damped roofs differ from the research w50 density by design
        feed = None if d['closed'][i] else s.get('tempF')
        air = NM.game_air(s.get('elevationFt'), feed, s.get('condition'), s.get('venueId'), o, W.get(str(int(pk))), coef)
        worst = max(worst, abs(air['lnP'] - lnP[i]), abs(air['lnT'] - lnT[i]), abs(air['head'] - head[i]), abs(air['cross'] - cross[i]))
        nchk += 1
    print(f'2. air on {nchk} games: max |diff| in lnP / lnT / wind {worst:.2e}')
    # 3. scalar entry point on 2,000 pitches
    rng = np.random.default_rng(0); idx = rng.choice(len(run), 2000, replace=False); worst = 0.0
    for i in idx:
        hb = d['hb_arm'][i] if d['rhp'][i] else -d['hb_arm'][i]
        tilt = ((d['axis'][i] / 30.0 - 6.0) % 12.0) * 60.0
        air = dict(lnP=lnP[i], lnT=lnT[i], head=head[i], cross=cross[i], source='measured')
        x_ivb, x_hb, mode = NM.neutral_movement(d['ivb'][i], hb, 'R' if d['rhp'][i] else 'L', float(tilt), d['velo'][i], air, coef)
        worst = max(worst, abs(x_ivb - ride[i]), abs((x_hb if d['rhp'][i] else -x_hb) - run[i]))
    print(f'3. per-pitch entry point on 2000 pitches: max |diff| {worst:.2e}')
