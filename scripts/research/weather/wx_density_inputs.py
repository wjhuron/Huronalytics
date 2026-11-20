"""wx_density_inputs.py -- how good is the DENSITY the model computes?

RESEARCH ONLY. Two reads, 2021-2025 (the seasons with kinematics) plus the
feed-against-measured comparison for 2026.

  1. The model's inputs against measured weather (Open-Meteo archive):
     feed temperature against measured temperature, standard-atmosphere
     pressure against measured station pressure, and the humidity term.
     Density error in percent, league and Coors.
  2. A density meter the model never saw: drag deceleration / v^2 is
     proportional to air density. Its game mean, after removing each
     (pitcher, pitch type) mean, is a per-game density reading. The density
     input that explains more of it is the better input. Slope should be
     near 1 (drag coefficient rises a little as density falls).
"""
import os, sys, json

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT = os.path.join(ROOT, 'data', '_weather_audit')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wx_exponent_sweep import load, moist, COORS

YEARS = [2021, 2022, 2023, 2024, 2025, 2026]


def game_table(d):
    pk = d['pk']
    u, first, inv = np.unique(pk, return_index=True, return_inverse=True)
    t = {k: d[k][first] for k in ('venue', 'elev', 'temp', 'feed_temp', 'closed', 'rho_model',
                                  'rho_obsP', 'rho_obsPT', 'rho_obs', 'obs_t', 'obs_p', 'obs_rh')}
    t['pk'] = u
    t['n'] = np.bincount(inv)
    if 'kdrag' in d:
        ok = np.isfinite(d['kdrag']) & (d['kdrag'] > 0)
        key = d['pid'].astype(np.int64) * 16 + d['pt']
        _, g = np.unique(key, return_inverse=True)
        ng = g.max() + 1
        y = np.where(ok, np.log(np.where(ok, d['kdrag'], 1.0)), 0.0)
        gm = np.bincount(g, weights=y, minlength=ng) / np.maximum(np.bincount(g, weights=ok, minlength=ng), 1)
        big = np.bincount(g, weights=ok, minlength=ng)[g] >= 100
        use = ok & big
        r = y - gm[g]
        t['drag'] = np.bincount(inv, weights=np.where(use, r, 0.0)) / np.maximum(np.bincount(inv, weights=use), 1)
        t['drag_n'] = np.bincount(inv, weights=use)
    return t


def wls(y, x, w):
    xm = np.sum(w * x) / w.sum(); ym = np.sum(w * y) / w.sum()
    b = np.sum(w * (x - xm) * (y - ym)) / np.sum(w * (x - xm) ** 2)
    r2 = 1 - np.sum(w * (y - ym - b * (x - xm)) ** 2) / np.sum(w * (y - ym) ** 2)
    return b, r2


def main():
    obs = json.load(open(os.path.join(OUT, 'game_obs.json')))
    R = {}
    allg = []
    for yr in YEARS:
        d = load(yr, obs)
        t = game_table(d); t['yr'] = np.full(len(t['pk']), yr)
        allg.append(t)
        del d
        op = ~t['closed']
        p_std = 1013.25 * (1 - 2.2558e-5 * t['elev'] * 0.3048) ** 5.2556
        dT = (t['feed_temp'] - t['obs_t'])[op]
        e_tot = 100 * (t['rho_obs'] / t['rho_model'] - 1)
        e_P = 100 * (t['rho_obsP'] / t['rho_model'] - 1)
        e_T = 100 * (t['rho_obsPT'] / t['rho_obsP'] - 1)
        e_H = 100 * (t['rho_obs'] / t['rho_obsPT'] - 1)
        c = t['venue'] == COORS
        R[str(yr)] = dict(
            feed_minus_obs_temp=[float(np.nanmean(dT)), float(np.nanstd(dT))],
            dens_err_total=[float(e_tot.mean()), float(e_tot.std())],
            dens_err_pressure=[float(e_P.mean()), float(e_P.std())],
            dens_err_temp=[float(e_T.mean()), float(e_T.std())],
            dens_err_humidity=[float(e_H.mean()), float(e_H.std())],
            coors_total=[float(e_tot[c].mean()), float(e_tot[c].std())],
            coors_pressure=float(e_P[c].mean()), coors_temp=float(e_T[c].mean()),
            coors_humidity=float(e_H[c].mean()),
            coors_p_std=float(p_std[c].mean()), coors_p_obs=float(t['obs_p'][c].mean()),
            coors_feed_temp=float(np.nanmean(t['feed_temp'][c])), coors_obs_temp=float(t['obs_t'][c].mean()))
        r = R[str(yr)]
        print(f'\n{yr}: open-air feed temp minus measured {r["feed_minus_obs_temp"][0]:+.1f} F (sd {r["feed_minus_obs_temp"][1]:.1f})')
        print(f'  measured density minus model density, %: total {r["dens_err_total"][0]:+.2f} (sd {r["dens_err_total"][1]:.2f})'
              f' | pressure {r["dens_err_pressure"][0]:+.2f} (sd {r["dens_err_pressure"][1]:.2f})'
              f' | temperature {r["dens_err_temp"][0]:+.2f} (sd {r["dens_err_temp"][1]:.2f})'
              f' | humidity {r["dens_err_humidity"][0]:+.2f} (sd {r["dens_err_humidity"][1]:.2f})')
        print(f'  Coors: total {r["coors_total"][0]:+.2f} (sd {r["coors_total"][1]:.2f}); pressure {r["coors_pressure"]:+.2f}'
              f' temp {r["coors_temp"]:+.2f} humidity {r["coors_humidity"]:+.2f}; '
              f'std-atm {r["coors_p_std"]:.1f} hPa vs measured {r["coors_p_obs"]:.1f}; '
              f'feed temp {r["coors_feed_temp"]:.1f} vs measured {r["coors_obs_temp"]:.1f}')
        if 'drag' in t:
            m = t['drag_n'] >= 100
            w = t['drag_n'][m]
            row = {}
            for dens in ('model', 'obsP', 'obsPT', 'obs'):
                b, r2 = wls(t['drag'][m], np.log(t[f'rho_{dens}'][m]), w)
                mo = m & ~t['closed'] & (t['venue'] != COORS)
                b2, r22 = wls(t['drag'][mo], np.log(t[f'rho_{dens}'][mo]), t['drag_n'][mo])
                row[dens] = dict(slope=float(b), r2=float(r2), slope_open_noCoors=float(b2), r2_open_noCoors=float(r22))
            R[str(yr)]['drag'] = row
            print('  drag meter, game level:  ' + '  '.join(
                f'{k}: slope {v["slope"]:.2f} R2 {v["r2"]:.3f}' for k, v in row.items()))
            print('     open air, no Coors:   ' + '  '.join(
                f'{k}: slope {v["slope_open_noCoors"]:.2f} R2 {v["r2_open_noCoors"]:.3f}' for k, v in row.items()))
    # venue-level residual of the drag meter against each density (2021-2025 pooled)
    G = {k: np.concatenate([t[k] for t in allg if 'drag' in t]) for k in
         ('venue', 'drag', 'drag_n', 'rho_model', 'rho_obs', 'closed', 'yr')}
    m = G['drag_n'] >= 100
    print('\nvenue mean of the drag-meter residual (%, slope fixed at the fitted pooled value), 2021-2025')
    out = {}
    for dens in ('model', 'obs'):
        x = np.log(G[f'rho_{dens}'][m]); y = G['drag'][m]; w = G['drag_n'][m]
        # demean within season: the ball itself changes by season
        for yr in np.unique(G['yr'][m]):
            s = G['yr'][m] == yr
            y[s] -= np.sum(w[s] * y[s]) / w[s].sum(); x[s] -= np.sum(w[s] * x[s]) / w[s].sum()
        b = np.sum(w * x * y) / np.sum(w * x * x)
        res = y - b * x
        vv = {}
        for v in np.unique(G['venue'][m]):
            s = G['venue'][m] == v
            if s.sum() >= 150:
                vv[int(v)] = float(100 * np.sum(w[s] * res[s]) / w[s].sum())
        out[dens] = dict(slope=float(b), venue=vv, sd=float(np.std(list(vv.values()))))
        top = sorted(vv.items(), key=lambda kv: -abs(kv[1]))[:8]
        print(f' {dens}: slope {b:.3f}, sd across venues {out[dens]["sd"]:.2f}%  largest: ' +
              '  '.join(f'{k}:{v:+.1f}' for k, v in top) + f'   Coors {vv.get(COORS, float("nan")):+.2f}')
    R['venue_drag_resid'] = out
    json.dump(R, open(os.path.join(OUT, 'density_inputs.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
