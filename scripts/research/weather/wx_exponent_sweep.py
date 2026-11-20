"""wx_exponent_sweep.py -- sweep the density exponent and the density input.

RESEARCH ONLY. Reads the audit frames and data/_weather_audit/game_obs.json.

OBJECTIVE (decides): held-out-season profile MSE in RAW inches,
    raw_ij = a_g * (rho_ij / rho0) ** e,   a_g free per (pitcher, pitch type)
The exponents are chosen on five seasons and scored on the sixth, six ways.
It cannot be gamed by the search direction: the target is the raw inches,
the group constant absorbs any scale, and a wrong exponent only adds error.

SECOND READ (does not decide): adjusted movement at Coors minus the same
pitcher's adjusted movement elsewhere, inches, in the held-out season.

DESIGNS
  ship   e = 1.05 everywhere
  one    one exponent
  comp   one for ride, one for run
  cell   one per (pitch type x component)
DENSITY INPUTS
  model  shipped: standard-atmosphere pressure from elevation + feed temperature
  obsP   measured station pressure, feed temperature, dry
  obsPT  measured pressure and measured temperature, dry
  obs    measured pressure, temperature and humidity (moist air)
Closed roof: 72 F and (for obs) 50% relative humidity, measured pressure.
Both roof values are conventions, not measurements.
"""
import os, sys, json

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT = os.path.join(ROOT, 'data', '_weather_audit')
PT = ['FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS']
YEARS = [2021, 2022, 2023, 2024, 2025, 2026]
RHO0 = 1.195
COORS = 19
MIN_N = 100
GRID = [round(0.50 + 0.05 * i, 2) for i in range(45)]      # 0.50 .. 2.70
COMPS = (('ivb', 'ride'), ('hb_arm', 'run'))


def moist(p_hpa, temp_f, rh):
    T = (temp_f - 32) * 5 / 9 + 273.15
    P = p_hpa * 100.0
    es = 610.94 * np.exp(17.625 * (T - 273.15) / (T - 30.11))
    e = np.clip(rh, 0, 100) / 100.0 * es
    return (P - e) / (287.05 * T) + e / (461.495 * T)


def load(yr, obs):
    z = np.load(os.path.join(OUT, f'frame_{yr}.npz'))
    d = {k: z[k] for k in z.files}
    ok = np.isfinite(d['rho']) & np.isfinite(d['ivb']) & np.isfinite(d['hb_arm']) & (d['pt'] < 8)
    if 'minors' in d:
        ok &= d['minors'] == 0
    d = {k: v[ok] for k, v in d.items()}
    n = len(d['pk'])
    p = np.full(n, np.nan); t = np.full(n, np.nan); rh = np.full(n, np.nan)
    for pk in np.unique(d['pk']):
        o = obs.get(str(int(pk)))
        if o:
            m = d['pk'] == pk
            p[m], t[m], rh[m] = o['p_hpa'], o['tempF'], o['rh']
    cl = d['closed']
    d['rho_obsP'] = moist(p, d['temp'], 0.0)
    d['rho_obsPT'] = moist(p, np.where(cl, 72.0, t), 0.0)
    d['rho_obs'] = moist(p, np.where(cl, 72.0, t), np.where(cl, 50.0, rh))
    d['rho_obsPH'] = moist(p, d['temp'], np.where(cl, 50.0, rh))   # measured P and RH, feed temperature
    d['rho_model'] = d['rho']
    # temperature blends: w * feed reading + (1 - w) * measured 3-hour mean (open air only)
    for w in (0.25, 0.5, 0.75):
        d[f'rho_w{int(100*w)}'] = moist(p, np.where(cl, 72.0, w * d['temp'] + (1 - w) * t), np.where(cl, 50.0, rh))
    d['obs_t'] = t; d['obs_p'] = p; d['obs_rh'] = rh
    keep = np.isfinite(d['rho_obs'])
    return {k: v[keep] for k, v in d.items()}


def curves(d):
    """SSE of the profile fit and the Coors gap, per density, component, type, exponent."""
    key = d['pid'].astype(np.int64) * 16 + d['pt']
    _, g = np.unique(key, return_inverse=True)
    ng = g.max() + 1
    big = np.bincount(g, minlength=ng)[g] >= MIN_N
    at = d['venue'] == COORS
    out = {}
    for dens in ('model', 'obsP', 'obsPH', 'obsPT', 'obs'):
        lr_all = np.log(d[f'rho_{dens}'] / RHO0)
        for comp, lab in COMPS:
            for i, p in enumerate(PT):
                m = big & (d['pt'] == i)
                if m.sum() < 3000:
                    continue
                gg = np.unique(g[m], return_inverse=True)[1]
                k = gg.max() + 1
                x = d[comp][m]; lr = lr_all[m]; a_ = at[m]
                nC = np.bincount(gg, weights=a_, minlength=k); nE = np.bincount(gg, weights=~a_, minlength=k)
                okg = (nC >= 25) & (nE >= 25)
                w = np.where(okg, 1.0 / (1.0 / np.maximum(nC, 1) + 1.0 / np.maximum(nE, 1)), 0.0)
                sse, gap, gapl, sxx, sxl, sll = [], [], [], [], [], []
                for e in GRID:
                    f = np.exp(e * lr)
                    ff = np.bincount(gg, weights=f * f, minlength=k)
                    a = np.bincount(gg, weights=x * f, minlength=k) / ff
                    sse.append(float(np.sum((x - a[gg] * f) ** 2)))
                    # additive design: x = a_g f + b * ln(rho/rho0); partial f out of both
                    xt = x - a[gg] * f
                    lt = lr - (np.bincount(gg, weights=lr * f, minlength=k) / ff)[gg] * f
                    sxx.append(float(xt @ xt)); sxl.append(float(xt @ lt)); sll.append(float(lt @ lt))
                    adj = x / f
                    dC = np.bincount(gg, weights=adj * a_, minlength=k) / np.maximum(nC, 1)
                    dE = np.bincount(gg, weights=adj * ~a_, minlength=k) / np.maximum(nE, 1)
                    gap.append(float(np.sum(w * (dC - dE)) / max(w.sum(), 1e-9)))
                    al = lr / f
                    lC = np.bincount(gg, weights=al * a_, minlength=k) / np.maximum(nC, 1)
                    lE = np.bincount(gg, weights=al * ~a_, minlength=k) / np.maximum(nE, 1)
                    gapl.append(float(np.sum(w * (lC - lE)) / max(w.sum(), 1e-9)))
                mE = np.bincount(gg, weights=x * ~a_, minlength=k) / np.maximum(nE, 1)
                out[(dens, lab, p)] = dict(sse=np.array(sse), gap=np.array(gap), n=int(m.sum()),
                                           sxx=np.array(sxx), sxl=np.array(sxl), sll=np.array(sll), gapl=np.array(gapl),
                                           wsum=float(w.sum()), kC=int(okg.sum()),
                                           mean_else=float(np.sum(w * mE) / max(w.sum(), 1e-9)))
    return out


def main():
    obs = json.load(open(os.path.join(OUT, 'game_obs.json')))
    C = {}
    for yr in YEARS:
        d = load(yr, obs)
        C[yr] = curves(d)
        print(f'{yr}: {len(d["pk"])} pitches with measured weather', flush=True)
        del d
    cells = sorted({(lab, p) for c in C.values() for (_, lab, p) in c})
    gi = {e: i for i, e in enumerate(GRID)}
    R = {'grid': GRID}

    def best(dens, cell_list, train):
        s = sum(C[y][(dens, lab, p)]['sse'] for y in train for (lab, p) in cell_list if (dens, lab, p) in C[y])
        return int(np.argmin(s)), s

    print('\n--- full-sample optimum per cell (model density); curve = MSE minus its minimum, x1000 in^2')
    for dens in ('model', 'obs'):
        R[f'cell_opt_{dens}'] = {}
        for (lab, p) in cells:
            per = []
            for y in YEARS:
                if (dens, lab, p) in C[y]:
                    per.append(GRID[int(np.argmin(C[y][(dens, lab, p)]['sse']))])
            i, s = best(dens, [(lab, p)], YEARS)
            n = sum(C[y][(dens, lab, p)]['n'] for y in YEARS if (dens, lab, p) in C[y])
            mse = s / n
            edge = i in (0, len(GRID) - 1)
            # width of the region within one "season SE": report per-season optima instead
            R[f'cell_opt_{dens}'][f'{lab}_{p}'] = dict(e=GRID[i], per_season=per, n=n, edge=edge,
                                                      d_mse_vs_105=float(mse[gi[1.05]] - mse[i]))
            if dens == 'model':
                print(f' {lab:4s} {p}: best {GRID[i]:.2f}{" EDGE" if edge else ""}  per season {per}  '
                      f'MSE(1.05)-MSE(best) {1000*(mse[gi[1.05]]-mse[i]):.2f}  n {n}')

    print('\n--- pooled curve, model density (MSE x1000 minus minimum), ride then run')
    for lab in ('ride', 'run'):
        i, s = best('model', [c for c in cells if c[0] == lab], YEARS)
        n = sum(C[y][('model', l, p)]['n'] for y in YEARS for (l, p) in cells if l == lab and ('model', l, p) in C[y])
        mse = s / n
        print(f' {lab}: ' + ' '.join(f'{e:.2f}:{1000*(m-mse.min()):.1f}' for e, m in zip(GRID, mse) if 0.8 <= e <= 1.6))
        R[f'pooled_curve_{lab}'] = [float(v) for v in mse]

    print('\n--- leave-one-season-out: exponents from five seasons, scored on the sixth')
    print(' design/density      ' + '  '.join(str(y) for y in YEARS) + '   mean  (held-out MSE, in^2; delta vs ship/model x1000)')
    res = {}
    for dens in ('model', 'obsP', 'obsPH', 'obsPT', 'obs'):
        for design in ('ship', 'one', 'comp', 'cell', 'add'):
            row, chosen = [], []
            for y in YEARS:
                train = [t for t in YEARS if t != y]
                sse_tot = 0.0; n_tot = 0; pick = {}
                if design == 'one':
                    i_all, _ = best(dens, cells, train)
                if design in ('comp', 'add'):
                    i_c = {lab: best(dens, [c for c in cells if c[0] == lab], train)[0] for lab in ('ride', 'run')}
                for (lab, p) in cells:
                    if (dens, lab, p) not in C[y]:
                        continue
                    if design == 'ship':
                        i = gi[1.05]
                    elif design == 'one':
                        i = i_all
                    elif design == 'comp':
                        i = i_c[lab]
                    elif design == 'add':
                        # component exponent from the training seasons, plus one additive
                        # slope per cell (inches per unit ln density), also from training
                        i = i_c[lab]
                        num = sum(C[t][(dens, lab, p)]['sxl'][i] for t in train if (dens, lab, p) in C[t])
                        den = sum(C[t][(dens, lab, p)]['sll'][i] for t in train if (dens, lab, p) in C[t])
                        b = num / den
                        c = C[y][(dens, lab, p)]
                        pick[f'{lab}_{p}'] = GRID[i]; pick[f'{lab}_{p}_b'] = b
                        sse_tot += c['sxx'][i] - 2 * b * c['sxl'][i] + b * b * c['sll'][i]; n_tot += c['n']
                        continue
                    else:
                        i = best(dens, [(lab, p)], train)[0]
                    pick[f'{lab}_{p}'] = GRID[i]
                    sse_tot += C[y][(dens, lab, p)]['sse'][i]; n_tot += C[y][(dens, lab, p)]['n']
                row.append(sse_tot / n_tot); chosen.append(pick)
            res[(dens, design)] = (row, chosen)
    base = res[('model', 'ship')][0]
    for (dens, design), (row, chosen) in res.items():
        dl = [1000 * (a - b) for a, b in zip(row, base)]
        wins = sum(1 for v in dl if v < 0)
        print(f' {design:5s} {dens:6s}  ' + '  '.join(f'{v:+6.2f}' for v in dl) +
              f'   {np.mean(dl):+6.2f}   wins {wins}/6' +
              (f'   e: {sorted(set(c.get("ride_FF") for c in chosen))}' if design in ('one',) else '') +
              (f'   e ride {sorted(set(c.get("ride_FF") for c in chosen))} run {sorted(set(c.get("run_FF") for c in chosen))}'
               if design in ('comp', 'add') else ''))
        R[f'loso_{design}_{dens}'] = dict(mse=row, delta_x1000=dl, chosen=chosen)
    print(f' (ship/model held-out MSE by season: ' + ' '.join(f'{v:.3f}' for v in base) + ')')

    print('\n--- held-out Coors gap, inches (adjusted at Coors minus elsewhere; 0 = complete)')
    for dens, design in (('model', 'ship'), ('model', 'one'), ('model', 'cell'), ('model', 'add'),
                         ('obsPH', 'ship'), ('obsPH', 'one'), ('obsPH', 'add')):
        row, chosen = res[(dens, design)]
        print(f' {design} / {dens}')
        R[f'coors_{design}_{dens}'] = {}
        for (lab, p) in cells:
            gaps = []
            for y, pick in zip(YEARS, chosen):
                c = C[y].get((dens, lab, p))
                if c is None or c['kC'] < 5 or f'{lab}_{p}' not in pick:
                    gaps.append(None); continue
                ii = gi[pick[f'{lab}_{p}']]
                gaps.append(c['gap'][ii] - pick.get(f'{lab}_{p}_b', 0.0) * c['gapl'][ii])
            v = [x for x in gaps if x is not None]
            if len(v) < 3:
                continue
            means = [C[y][(dens, lab, p)]['mean_else'] for y in YEARS if (dens, lab, p) in C[y]]
            R[f'coors_{design}_{dens}'][f'{lab}_{p}'] = gaps
            print(f'   {lab:4s} {p} (typical {np.mean(means):+5.1f} in): ' +
                  ' '.join('  n/a ' if x is None else f'{x:+5.2f}' for x in gaps) +
                  f'   mean {np.mean(v):+5.2f}  sd {np.std(v):.2f}')
    # additive slopes on the full sample, model density, at the pooled component optimum
    print('\n--- additive design, full sample (model density): inches of shift per unit ln(density); x 0.193 = at Coors')
    R['add_full'] = {}
    for lab in ('ride', 'run'):
        i = best('model', [c for c in cells if c[0] == lab], YEARS)[0]
        for (l, p) in cells:
            if l != lab:
                continue
            per = [C[y][('model', l, p)]['sxl'][i] / C[y][('model', l, p)]['sll'][i] for y in YEARS if ('model', l, p) in C[y]]
            b = (sum(C[y][('model', l, p)]['sxl'][i] for y in YEARS if ('model', l, p) in C[y]) /
                 sum(C[y][('model', l, p)]['sll'][i] for y in YEARS if ('model', l, p) in C[y]))
            R['add_full'][f'{l}_{p}'] = dict(e=GRID[i], b=b, per_season=per)
            print(f' {l:4s} {p}: e {GRID[i]:.2f}  b {b:+6.2f}  (at Coors {-0.193*b:+5.2f} in)  per season ' +
                  ' '.join(f'{v:+.1f}' for v in per))
    json.dump(R, open(os.path.join(OUT, 'exponent_sweep.json'), 'w'), indent=1, default=float)


if __name__ == '__main__':
    main()
