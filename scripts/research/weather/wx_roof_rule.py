"""wx_roof_rule.py -- is 72 F the right air for a closed roof?

RESEARCH ONLY. Production clamps every `dome` / `roof closed` game to 72 F.
This sweeps, per park, the indoor temperature model

    T_in = 72 + k * (T_outside_measured - 72)        k = 0 sealed and conditioned
                                                     k = 1 the roof is an umbrella
on k = 0 .. 1.2 step 0.1. Objective: profile MSE of RAW movement (ride and run)
inside each (pitcher, pitch type) group that threw under that closed roof, with
the density exponent held at the value given on the command line (default 1.2;
run it at 1.05 as well to show the answer does not lean on the exponent).
k is chosen on five seasons and scored on the sixth.

Open-air games keep the shipped inputs (elevation + feed temperature), so the
only thing that moves is the closed-roof air.
"""
import os, sys, json
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wx_exponent_sweep import load, OUT, RHO0, YEARS, ROOT
sys.path.insert(0, ROOT)
from scrapers.pitcher2026 import compute_air_density

PARKS = {15: 'Chase', 12: 'Tropicana', 14: 'Rogers', 32: 'AmFam', 680: 'T-Mobile',
         2392: 'Minute Maid/Daikin', 4169: 'loanDepot', 5325: 'Globe Life'}
KGRID = [round(0.1 * i, 1) for i in range(13)]


def run(e):
    obs = json.load(open(os.path.join(OUT, 'game_obs.json')))
    S = {v: {} for v in PARKS}          # S[v][yr] = array over k of SSE ; plus n
    for yr in YEARS:
        d = load(yr, obs)
        g = np.unique(d['pid'].astype(np.int64) * 16 + d['pt'], return_inverse=True)[1]
        ng = g.max() + 1
        big = np.bincount(g, minlength=ng) >= 100
        for v in PARKS:
            cl = d['closed'] & (d['venue'] == v)
            if cl.sum() < 2000:
                continue
            touched = np.zeros(ng, bool); touched[np.unique(g[cl])] = True
            m = touched[g] & big[g]
            gg = np.unique(g[m], return_inverse=True)[1]; k_ = gg.max() + 1
            clm = cl[m]
            sse = []
            for kk in KGRID:
                t_in = 72.0 + kk * (d['obs_t'][m] - 72.0)
                rho = np.where(clm, compute_air_density(d['elev'][m], t_in), d['rho_model'][m])
                f = np.exp(e * np.log(rho / RHO0))
                tot = 0.0
                for comp in ('ivb', 'hb_arm'):
                    x = d[comp][m]
                    a = np.bincount(gg, weights=x * f, minlength=k_) / np.bincount(gg, weights=f * f, minlength=k_)
                    tot += float(np.sum((x - a[gg] * f) ** 2))
                sse.append(tot)
            S[v][yr] = (np.array(sse), int(m.sum()), float(np.mean(d['obs_t'][cl])), int(cl.sum()))
        del d
    print(f'\nexponent {e}: MSE x1000 minus the minimum, by k (0 = shipped rule)')
    R = {}
    for v, name in PARKS.items():
        if not S[v]:
            continue
        tot = sum(s[0] for s in S[v].values()); n = sum(s[1] for s in S[v].values())
        mse = 1000 * tot / n
        ib = int(np.argmin(tot))
        picks, d_out = [], []
        for y in S[v]:
            tr = sum(S[v][t][0] for t in S[v] if t != y)
            i = int(np.argmin(tr)); picks.append(KGRID[i])
            d_out.append(1000 * (S[v][y][0][i] - S[v][y][0][0]) / S[v][y][1])
        t_out = np.mean([s[2] for s in S[v].values()])
        R[name] = dict(best_k=KGRID[ib], edge=ib in (0, len(KGRID) - 1), picks=picks, heldout_delta=d_out,
                       curve=[float(x) for x in mse - mse.min()], closed_pitches=sum(s[3] for s in S[v].values()))
        print(f' {name:20s} best k {KGRID[ib]:.1f}{" EDGE" if R[name]["edge"] else ""}  '
              f'LOSO picks {picks}  held-out delta vs shipped {" ".join(f"{x:+.1f}" for x in d_out)} '
              f'(wins {sum(x < 0 for x in d_out)}/{len(d_out)})  mean outside temp on closed days {t_out:.0f} F')
        print('      curve: ' + ' '.join(f'{k}:{x:.1f}' for k, x in zip(KGRID, mse - mse.min())))
    return R


if __name__ == '__main__':
    es = [float(a) for a in sys.argv[1:]] or [1.2, 1.05]
    out = {str(e): run(e) for e in es}
    json.dump(out, open(os.path.join(OUT, 'roof_rule.json'), 'w'), indent=1)
