"""wx_density_slopes.py -- is the density adjustment complete?

RESEARCH ONLY. Reads data/_weather_audit/frame_{yr}.npz (wx_build_frame.py).

Model under test:  adjusted = raw * (rho0 / rho) ** 1.05   (scrapers/pitcher2026.py)

Group = (pitcher, pitch type) inside one season. All slopes are WITHIN group,
so roster and pitch shape drop out and only game-to-game density identifies
the answer.

  A. elasticity of RAW movement on model density, y = raw / group mean,
     regressed on ln(rho) with group fixed effects, SE clustered by game.
     A complete model reads 1.05. By season (six independent replicates),
     pitch type, component (ride, run), with and without Coors, with
     velocity and spin controls, and with ln(rho) split into its pressure
     (elevation) part and its temperature part.
  B. exponent sweep (grid) by profile least squares on the raw inches,
     no log and no per-pitch truncation.
  C. the Coors test in inches: adjusted movement at Coors minus the same
     pitcher's adjusted movement elsewhere, Rockies and visitors apart.
  D. drag probe (2021-2025): drag deceleration / v^2 is proportional to
     air density, so its within-group slope on the model's ln(rho) tests
     the DENSITY model without touching movement.

Usage: .venv/bin/python scripts/research/weather/wx_density_slopes.py
Output: console + data/_weather_audit/density_slopes.json
"""
import os, sys, json

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT = os.path.join(ROOT, 'data', '_weather_audit')
PT = ['FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS', 'KC', 'SV']
YEARS = [2021, 2022, 2023, 2024, 2025, 2026]
RHO0 = 1.195
E_SHIP = 1.05
COORS = 19
MIN_N = 100        # pitches per group (convention: enough for a stable group mean)
MIN_ABS = 5.0      # inches, group MEAN of the component (convention; avoids dividing by ~0)


def load(yr):
    z = np.load(os.path.join(OUT, f'frame_{yr}.npz'))
    d = {k: z[k] for k in z.files}
    ok = np.isfinite(d['rho']) & np.isfinite(d['ivb']) & np.isfinite(d['hb_arm'])
    if 'minors' in d:
        ok &= d['minors'] == 0
    return {k: v[ok] for k, v in d.items()}


def groups(d):
    key = d['pid'].astype(np.int64) * 16 + d['pt']
    _, g = np.unique(key, return_inverse=True)
    return g


def gmean(x, g, ng):
    return (np.bincount(g, weights=x, minlength=ng) / np.maximum(np.bincount(g, minlength=ng), 1))[g]


def fe_ols(y, X, g, cl):
    """OLS of y on X with group fixed effects, cluster-robust SE by cl."""
    ng = g.max() + 1
    yd = y - gmean(y, g, ng)
    Xd = np.column_stack([x - gmean(x, g, ng) for x in X.T])
    XtX = Xd.T @ Xd
    b = np.linalg.solve(XtX, Xd.T @ yd)
    r = yd - Xd @ b
    _, ci = np.unique(cl, return_inverse=True)
    S = np.zeros((ci.max() + 1, Xd.shape[1]))
    for j in range(Xd.shape[1]):
        S[:, j] = np.bincount(ci, weights=Xd[:, j] * r)
    inv = np.linalg.inv(XtX)
    V = inv @ (S.T @ S) @ inv
    return b, np.sqrt(np.diag(V))


def select(d, g, comp, pt=None, drop_coors=False, only_minabs=True):
    ng = g.max() + 1
    x = d[comp]
    n = np.bincount(g, minlength=ng)[g]
    m = gmean(x, g, ng)
    ok = n >= MIN_N
    if only_minabs:
        ok &= np.abs(m) >= MIN_ABS
    if pt is not None:
        ok &= d['pt'] == pt
    if drop_coors:
        ok &= d['venue'] != COORS
    return ok


def elasticity(d, g, comp, **kw):
    controls = kw.pop('controls', False)
    split = kw.pop('split', False)
    ok = select(d, g, comp, **kw)
    if controls:
        ok &= np.isfinite(d['velo']) & np.isfinite(d['spin']) & (d['spin'] > 500)
    if ok.sum() < 5000:
        return None
    gg = np.unique(g[ok], return_inverse=True)[1]
    ng = gg.max() + 1
    x = d[comp][ok]
    y = x / gmean(x, gg, ng)
    if split:
        el_m = d['elev'][ok] * 0.3048
        lnP = 5.2556 * np.log(1 - 2.2558e-5 * el_m)
        lnT = -np.log((d['temp'][ok] - 32) * 5 / 9 + 273.15)
        X = np.column_stack([lnP, lnT])
    else:
        X = np.log(d['rho'][ok])[:, None]
    if controls:
        X = np.column_stack([X, np.log(d['velo'][ok]), np.log(d['spin'][ok])])
    b, se = fe_ols(y, X, gg, d['pk'][ok])
    return dict(b=[round(float(v), 4) for v in b], se=[round(float(v), 4) for v in se],
                n=int(ok.sum()), ng=int(ng))


def sweep(d, g, comp, grid, **kw):
    ok = select(d, g, comp, **kw)
    gg = np.unique(g[ok], return_inverse=True)[1]
    ng = gg.max() + 1
    x = d[comp][ok]
    lr = np.log(d['rho'][ok] / RHO0)
    out = []
    for e in grid:
        f = np.exp(e * lr)
        a = np.bincount(gg, weights=x * f, minlength=ng) / np.bincount(gg, weights=f * f, minlength=ng)
        out.append(float(np.mean((x - a[gg] * f) ** 2)))
    return out


def coors_test(d, g, comp, e=E_SHIP, min_each=25):
    """Adjusted movement at Coors minus the same group's adjusted movement elsewhere."""
    ng = g.max() + 1
    adj = d[comp] * (RHO0 / d['rho']) ** e
    at = d['venue'] == COORS
    nC = np.bincount(g, weights=at, minlength=ng)
    nE = np.bincount(g, weights=~at, minlength=ng)
    sC = np.bincount(g, weights=adj * at, minlength=ng)
    sE = np.bincount(g, weights=adj * ~at, minlength=ng)
    rC = np.bincount(g, weights=d[comp] * at, minlength=ng)
    rE = np.bincount(g, weights=d[comp] * ~at, minlength=ng)
    lC = np.bincount(g, weights=np.log(d['rho']) * at, minlength=ng)
    lE = np.bincount(g, weights=np.log(d['rho']) * ~at, minlength=ng)
    ptg = np.zeros(ng, dtype=int); ptg[g] = d['pt']
    ok = (nC >= min_each) & (nE >= min_each)
    with np.errstate(invalid='ignore', divide='ignore'):
        res = dict(g=np.where(ok)[0], pt=ptg[ok], nC=nC[ok], nE=nE[ok],
                   diff=(sC / nC - sE / nE)[ok], rawC=(rC / nC)[ok], rawE=(rE / nE)[ok],
                   dln=(lC / nC - lE / nE)[ok])
    # home staff = groups with at least 35% of pitches at Coors (convention)
    res['home'] = res['nC'] / (res['nC'] + res['nE']) >= 0.35
    return res


def main():
    R = {}
    grid = [round(0.60 + 0.05 * i, 2) for i in range(23)]   # 0.60 .. 1.70
    for yr in YEARS:
        d = load(yr)
        g = groups(d)
        ry = R[str(yr)] = {}
        print(f'\n===== {yr}: {len(g)} pitches, {g.max()+1} groups, '
              f'Coors pitches {(d["venue"]==COORS).sum()}')
        for comp, lab in (('ivb', 'ride'), ('hb_arm', 'run')):
            rc = ry[lab] = {}
            rc['all'] = elasticity(d, g, comp)
            rc['noCoors'] = elasticity(d, g, comp, drop_coors=True)
            rc['ctrl'] = elasticity(d, g, comp, controls=True)
            rc['split'] = elasticity(d, g, comp, split=True)
            rc['split_ctrl'] = elasticity(d, g, comp, split=True, controls=True)
            s = sweep(d, g, comp, grid)
            rc['sweep'] = s
            rc['sweep_best'] = grid[int(np.argmin(s))]
            s2 = sweep(d, g, comp, grid, drop_coors=True)
            rc['sweep_noCoors_best'] = grid[int(np.argmin(s2))]
            print(f' {lab:4s} elasticity all {rc["all"]["b"][0]:.3f} ({rc["all"]["se"][0]:.3f})'
                  f'  noCoors {rc["noCoors"]["b"][0]:.3f} ({rc["noCoors"]["se"][0]:.3f})'
                  f'  +velo,spin {rc["ctrl"]["b"][0]:.3f} ({rc["ctrl"]["se"][0]:.3f})'
                  f' | split P {rc["split"]["b"][0]:.3f} ({rc["split"]["se"][0]:.3f})'
                  f' T {rc["split"]["b"][1]:.3f} ({rc["split"]["se"][1]:.3f})'
                  f' | split+ctrl P {rc["split_ctrl"]["b"][0]:.3f} T {rc["split_ctrl"]["b"][1]:.3f}'
                  f' | sweep best {rc["sweep_best"]} (noCoors {rc["sweep_noCoors_best"]})')
            rc['bypt'] = {}
            for i, p in enumerate(PT[:8]):
                e1 = elasticity(d, g, comp, pt=i)
                e2 = elasticity(d, g, comp, pt=i, split=True)
                if e1:
                    rc['bypt'][p] = dict(all=e1, split=e2)
            print('      by type: ' + '  '.join(
                f'{p} {v["all"]["b"][0]:.2f}({v["all"]["se"][0]:.2f})' for p, v in rc['bypt'].items()))
            # Coors test
            ct = coors_test(d, g, comp)
            rows = {}
            for who, mask in (('visitors', ~ct['home']), ('rockies', ct['home'])):
                for i, p in enumerate(PT[:8]):
                    m = mask & (ct['pt'] == i) & (np.abs(ct['rawE']) >= MIN_ABS)
                    if m.sum() < 5:
                        continue
                    w = 1.0 / (1.0 / ct['nC'][m] + 1.0 / ct['nE'][m])
                    diff = float(np.sum(w * ct['diff'][m]) / w.sum())
                    se = float(np.sqrt(np.sum(w * w * (ct['diff'][m] - diff) ** 2)) / w.sum())
                    # exponent that closes the gap, ratio of weighted sums
                    eimp = float(np.sum(w * np.log(ct['rawC'][m] / ct['rawE'][m])) /
                                 np.sum(w * ct['dln'][m]))
                    rows[f'{who}_{p}'] = dict(k=int(m.sum()), nC=int(ct['nC'][m].sum()),
                                              diff_in=round(diff, 3), se=round(se, 3),
                                              mean_in=round(float(np.sum(w * ct['rawE'][m]) / w.sum()), 2),
                                              e_implied=round(eimp, 3))
            rc['coors'] = rows
            for who in ('visitors', 'rockies'):
                print(f'      Coors {who:8s}: ' + '  '.join(
                    f'{k.split("_")[1]} {v["diff_in"]:+.2f}±{v["se"]:.2f} (e {v["e_implied"]:.2f}, k{v["k"]})'
                    for k, v in rows.items() if k.startswith(who)))
        if 'kdrag' in d:
            ok = np.isfinite(d['kdrag']) & (d['kdrag'] > 0) & select(d, g, 'ivb', only_minabs=False)
            gg = np.unique(g[ok], return_inverse=True)[1]
            y = np.log(d['kdrag'][ok])
            b, se = fe_ols(y, np.log(d['rho'][ok])[:, None], gg, d['pk'][ok])
            nc = ok & (d['venue'] != COORS)
            gg2 = np.unique(g[nc], return_inverse=True)[1]
            b2, se2 = fe_ols(np.log(d['kdrag'][nc]), np.log(d['rho'][nc])[:, None], gg2, d['pk'][nc])
            el_m = d['elev'][ok] * 0.3048
            X = np.column_stack([5.2556 * np.log(1 - 2.2558e-5 * el_m),
                                 -np.log((d['temp'][ok] - 32) * 5 / 9 + 273.15)])
            b3, se3 = fe_ols(y, X, gg, d['pk'][ok])
            ry['drag'] = dict(all=[float(b[0]), float(se[0])], noCoors=[float(b2[0]), float(se2[0])],
                              P=[float(b3[0]), float(se3[0])], T=[float(b3[1]), float(se3[1])])
            print(f' drag probe: ln(drag/v^2) on ln(rho) all {b[0]:.3f} ({se[0]:.3f})  '
                  f'noCoors {b2[0]:.3f} ({se2[0]:.3f})  split P {b3[0]:.3f} ({se3[0]:.3f}) '
                  f'T {b3[1]:.3f} ({se3[1]:.3f})')
        del d
    json.dump(dict(grid=grid, results=R), open(os.path.join(OUT, 'density_slopes.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
