"""wx_wind_hand_month.py -- three checks the first audit skipped.  RESEARCH ONLY.

  WIND   the feed reports speed and a direction word. Head component (mph, positive
         = blows out, against the pitch) and cross component (positive = left field
         to right field = toward +x, catcher view). Physics at full strength: 1 mph
         of headwind is about +1.1% movement and +2.2% drag; 10 mph of crosswind is
         about 3 in of sideways push. Does any of it reach the mound?
  HAND   the density elasticity, right-handers against left-handers.
  MONTH  the density elasticity with month inside the fixed-effect group.

Within (pitcher, pitch type) groups, measured-pressure density (obsPH), SE clustered by game.
"""
import os, sys, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wx_exponent_sweep import load, OUT, RHO0, YEARS
from wx_density_slopes import fe_ols

DIRS = {'Out To CF': (1.0, 0.0), 'Out To RF': (0.707, 0.707), 'Out To LF': (0.707, -0.707),
        'In From CF': (-1.0, 0.0), 'In From RF': (-0.707, -0.707), 'In From LF': (-0.707, 0.707),
        'L To R': (0.0, 1.0), 'R To L': (0.0, -1.0), 'Calm': (0.0, 0.0), 'None': (0.0, 0.0)}


def wind_arrays(pk, W):
    head = np.full(len(pk), np.nan); cross = np.full(len(pk), np.nan)
    for k in np.unique(pk):
        s = W.get(str(int(k)))
        if not s or ',' not in s:
            continue
        sp, dr = s.split(',', 1)
        try:
            mph = float(sp.split()[0])
        except ValueError:
            continue
        v = DIRS.get(dr.strip())
        if v is None:
            continue
        m = pk == k
        head[m] = mph * v[0]; cross[m] = mph * v[1]
    return head, cross


if __name__ == '__main__':
    obs = json.load(open(os.path.join(OUT, 'game_obs.json')))
    W = json.load(open(os.path.join(OUT, 'wind.json')))
    R = {}
    for yr in YEARS:
        d = load(yr, obs)
        g = np.unique(d['pid'].astype(np.int64) * 16 + d['pt'], return_inverse=True)[1]
        big = np.bincount(g)[g] >= 100
        d = {k: v[big] for k, v in d.items()}
        g = np.unique(d['pid'].astype(np.int64) * 16 + d['pt'], return_inverse=True)[1]
        ng = g.max() + 1
        lr = np.log(d['rho_obsPH'] / RHO0)
        head, cross = wind_arrays(d['pk'], W)
        head = np.where(d['closed'], 0.0, head); cross = np.where(d['closed'], 0.0, cross)
        ok = np.isfinite(head)
        px = np.where(d['rhp'], -d['hb_arm'], d['hb_arm'])            # catcher frame, inches
        out = {}
        # WIND: ride (inches, group mean about 9) and sideways push, density controlled
        gm = lambda x: (np.bincount(g, weights=x, minlength=ng) / np.bincount(g, minlength=ng))[g]
        mz = gm(d['ivb'])
        X = np.column_stack([lr * mz, head * mz / 100.0])[ok]         # coefficient on head = % movement per mph
        gg = np.unique(g[ok], return_inverse=True)[1]
        b, se = fe_ols(d['ivb'][ok], X, gg, d['pk'][ok])
        out['ride_pct_per_mph_head'] = [float(b[1]), float(se[1])]
        X = np.column_stack([lr * gm(px), cross])[ok]
        b2, se2 = fe_ols(px[ok], X, gg, d['pk'][ok])
        out['side_in_per_mph_cross'] = [float(b2[1]), float(se2[1])]
        msg = (f'{yr} WIND  ride {b[1]:+.3f}% per mph of headwind (se {se[1]:.3f}; full strength +1.1)   '
               f'sideways {b2[1]:+.4f} in per mph of crosswind (se {se2[1]:.4f}; full strength +0.3)')
        if 'kdrag' in d:
            o2 = ok & np.isfinite(d['kdrag']) & (d['kdrag'] > 0)
            gg2 = np.unique(g[o2], return_inverse=True)[1]
            b3, se3 = fe_ols(np.log(d['kdrag'][o2]), np.column_stack([lr, head])[o2], gg2, d['pk'][o2])
            out['drag_pct_per_mph_head'] = [float(100 * b3[1]), float(100 * se3[1])]
            msg += f'   drag {100*b3[1]:+.3f}% per mph (se {100*se3[1]:.3f}; full strength +2.2)'
        print(msg)
        # HAND and MONTH: elasticity of ride and run (ratio form, group mean >= 5 in)
        mo = np.array([int(s[5:7]) for s in d['date']])
        for comp, lab in (('ivb', 'ride'), ('hb_arm', 'run')):
            m_ = gm(d[comp]); sel = np.abs(m_) >= 5
            y = d[comp] / np.where(sel, m_, 1.0)
            res = {}
            for name, mask, key in (('R', sel & d['rhp'], g), ('L', sel & ~d['rhp'], g),
                                    ('all', sel, g), ('month', sel, g.astype(np.int64) * 16 + mo)):
                kk = np.unique(key[mask], return_inverse=True)[1]
                if name == 'month':
                    keep = np.bincount(kk)[kk] >= 30
                    idx = np.where(mask)[0][keep]; kk = np.unique(key[idx], return_inverse=True)[1]
                else:
                    idx = np.where(mask)[0]
                bb, ss = fe_ols(y[idx], lr[idx][:, None], kk, d['pk'][idx])
                res[name] = [float(bb[0]), float(ss[0])]
            out[lab] = res
            print(f'{yr} {lab:4s} elasticity  RHP {res["R"][0]:.3f} ({res["R"][1]:.3f})  LHP {res["L"][0]:.3f} ({res["L"][1]:.3f})'
                  f'  | all {res["all"][0]:.3f}  with month in the group {res["month"][0]:.3f} ({res["month"][1]:.3f})')
        R[yr] = out
        del d
    json.dump(R, open(os.path.join(OUT, 'wind_hand_month.json'), 'w'), indent=1)
