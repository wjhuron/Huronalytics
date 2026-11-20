"""wx_roof_ingame.py -- two last inputs, on the measured-pressure density.  RESEARCH ONLY.

ROOF     closed-roof air temperature T_in = 72 + k (T_outside - 72), k swept 0..1.2 per park,
         measured pressure, 50% humidity indoors. Objective: profile MSE of raw ride + run in
         the groups that pitched under that roof, exponents 1.25 (run) / 1.15 (ride).
         k from five seasons, scored on the sixth.
IN-GAME  2026 only (the only season with at-bat order): temperature moves from the first-hour
         reading to the fourth-hour reading across the game's at-bats, against one game mean.
         One season, so this is a screen, not a validated result.
"""
import os, sys, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wx_exponent_sweep import load, OUT, RHO0, YEARS, moist

PARKS = {15: 'Chase', 12: 'Tropicana', 14: 'Rogers', 32: 'AmFam', 680: 'T-Mobile',
         2392: 'Daikin', 4169: 'loanDepot', 5325: 'Globe Life'}
KG = [round(0.1 * i, 1) for i in range(13)]
E = {'hb_arm': 1.25, 'ivb': 1.15}


def sse(d, m, rho, gg, k_):
    tot = 0.0
    for comp, e in E.items():
        f = np.exp(e * np.log(rho / RHO0)); x = d[comp][m]
        a = np.bincount(gg, weights=x * f, minlength=k_) / np.bincount(gg, weights=f * f, minlength=k_)
        tot += float(np.sum((x - a[gg] * f) ** 2))
    return tot


if __name__ == '__main__':
    obs = json.load(open(os.path.join(OUT, 'game_obs.json')))
    S = {v: {} for v in PARKS}; ingame = None
    for yr in YEARS:
        d = load(yr, obs)
        g = np.unique(d['pid'].astype(np.int64) * 16 + d['pt'], return_inverse=True)[1]; ng = g.max() + 1
        big = np.bincount(g, minlength=ng) >= 100
        for v in PARKS:
            cl = d['closed'] & (d['venue'] == v)
            if cl.sum() < 2000:
                continue
            touched = np.zeros(ng, bool); touched[np.unique(g[cl])] = True
            m = touched[g] & big[g]; gg = np.unique(g[m], return_inverse=True)[1]; k_ = gg.max() + 1
            clm = cl[m]; out = []
            for kk in KG:
                t_in = 72.0 + kk * (d['obs_t'][m] - 72.0)
                rho = np.where(clm, moist(d['obs_p'][m], t_in, 50.0), d['rho_w50'][m])
                out.append(sse(d, m, rho, gg, k_))
            S[v][yr] = (np.array(out), int(m.sum()))
        if yr == 2026 and 'ab' in d:
            op = ~d['closed'] & np.isfinite(d['ab']) & big[g]
            pk = d['pk'][op]; u, inv = np.unique(pk, return_inverse=True)
            abmax = np.zeros(len(u)); np.maximum.at(abmax, inv, d['ab'][op])
            frac = d['ab'][op] / np.maximum(abmax[inv], 1)
            tf = np.array([obs[str(int(k))]['temp_first'] for k in u])[inv]
            tl = np.array([obs[str(int(k))]['temp_last'] for k in u])[inv]
            gg = np.unique(g[op], return_inverse=True)[1]; k_ = gg.max() + 1
            res = {}
            for lam in (0.0, 0.5, 1.0, 1.5):
                # temperature path around the measured game mean; lam = 0 is the constant mean
                t_obs = d['obs_t'][op] + lam * (tl - tf) * (frac - 0.5)
                rho = moist(d['obs_p'][op], 0.5 * d['temp'][op] + 0.5 * t_obs, d['obs_rh'][op])
                res[lam] = 1000 * sse(d, op, rho, gg, k_) / op.sum()
            ingame = (res, float(np.mean(tl - tf)), float(np.std(tl - tf)))
        del d
    print('ROOF on the measured-pressure density: MSE x1000 minus minimum by k (0 = 72 F fixed)')
    R = {}
    for v, name in PARKS.items():
        if not S[v]:
            continue
        tot = sum(s[0] for s in S[v].values()); n = sum(s[1] for s in S[v].values()); ib = int(np.argmin(tot))
        picks, dl = [], []
        for y in S[v]:
            i = int(np.argmin(sum(S[v][t][0] for t in S[v] if t != y))); picks.append(KG[i])
            dl.append(1000 * (S[v][y][0][i] - S[v][y][0][0]) / S[v][y][1])
        R[name] = dict(best=KG[ib], picks=picks, heldout=dl)
        print(f' {name:11s} best k {KG[ib]}{" EDGE" if ib in (0, len(KG)-1) else ""}  picks {picks}  held-out vs 72 F '
              f'{" ".join(f"{x:+.1f}" for x in dl)} ({sum(x < 0 for x in dl)}/{len(dl)})   curve ' +
              ' '.join(f'{k}:{1000*(t-tot.min())/n:.1f}' for k, t in zip(KG, tot))[:150])
    if ingame:
        res, mu, sd = ingame
        print(f'\nIN-GAME temperature, 2026 open-air: first-to-fourth-hour change mean {mu:+.1f} F (sd {sd:.1f})')
        print('  MSE x1000 by share of that change applied along the game: ' + '  '.join(f'{k}: {v:.3f}' for k, v in res.items()))
        R['ingame'] = dict(res={str(k): v for k, v in res.items()}, mean_change=mu, sd=sd)
    json.dump(R, open(os.path.join(OUT, 'roof_ingame.json'), 'w'), indent=1)
