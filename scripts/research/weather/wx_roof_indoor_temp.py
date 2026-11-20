"""wx_roof_indoor_temp.py -- indoor temperature sweep for the conditioned parks.

RESEARCH ONLY. wx_roof_rule.py put k at the grid edge (0) for the five
hot-climate roofs, so the open constant there is the indoor temperature
itself (shipped: 72 F). Sweep it 60..84 F step 2, same objective, exponent 1.2,
chosen on five seasons and scored on the sixth.
"""
import os, sys, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wx_exponent_sweep import load, OUT, RHO0, YEARS, ROOT
sys.path.insert(0, ROOT)
from scrapers.pitcher2026 import compute_air_density

PARKS = {15: 'Chase', 12: 'Tropicana', 2392: 'Minute Maid/Daikin', 4169: 'loanDepot', 5325: 'Globe Life'}
TG = list(range(60, 86, 2))
E = float(sys.argv[1]) if len(sys.argv) > 1 else 1.2

if __name__ == '__main__':
    obs = json.load(open(os.path.join(OUT, 'game_obs.json')))
    S = {v: {} for v in PARKS}
    for yr in YEARS:
        d = load(yr, obs)
        g = np.unique(d['pid'].astype(np.int64) * 16 + d['pt'], return_inverse=True)[1]; ng = g.max() + 1
        big = np.bincount(g, minlength=ng) >= 100
        for v in PARKS:
            cl = d['closed'] & (d['venue'] == v)
            if cl.sum() < 2000:
                continue
            touched = np.zeros(ng, bool); touched[np.unique(g[cl])] = True
            m = touched[g] & big[g]
            # a group that threw ONLY under this roof cannot tell the temperature
            gg = np.unique(g[m], return_inverse=True)[1]; k_ = gg.max() + 1
            clm = cl[m]; sse = []
            for t0 in TG:
                rho = np.where(clm, compute_air_density(d['elev'][m], float(t0)), d['rho_model'][m])
                f = np.exp(E * np.log(rho / RHO0)); tot = 0.0
                for comp in ('ivb', 'hb_arm'):
                    x = d[comp][m]
                    a = np.bincount(gg, weights=x * f, minlength=k_) / np.bincount(gg, weights=f * f, minlength=k_)
                    tot += float(np.sum((x - a[gg] * f) ** 2))
                sse.append(tot)
            S[v][yr] = (np.array(sse), int(m.sum()))
        del d
    R = {}
    print(f'exponent {E}: indoor temperature sweep (shipped 72 F); MSE x1000 minus minimum')
    for v, name in PARKS.items():
        tot = sum(s[0] for s in S[v].values()); n = sum(s[1] for s in S[v].values())
        mse = 1000 * tot / n; ib = int(np.argmin(tot))
        picks, dl = [], []
        for y in S[v]:
            i = int(np.argmin(sum(S[v][t][0] for t in S[v] if t != y))); picks.append(TG[i])
            dl.append(1000 * (S[v][y][0][i] - S[v][y][0][TG.index(72)]) / S[v][y][1])
        R[name] = dict(best=TG[ib], picks=picks, heldout=dl, curve=[float(x) for x in mse - mse.min()])
        print(f' {name:20s} best {TG[ib]} F{" EDGE" if ib in (0, len(TG)-1) else ""}  LOSO picks {picks}  '
              f'held-out delta vs 72 F: {" ".join(f"{x:+.1f}" for x in dl)} (wins {sum(x < 0 for x in dl)}/{len(dl)})')
        print('      ' + ' '.join(f'{t}:{x:.1f}' for t, x in zip(TG, mse - mse.min())))
    json.dump(R, open(os.path.join(OUT, 'roof_indoor_temp.json'), 'w'), indent=1)
