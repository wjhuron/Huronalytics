"""wx_cell_shift.py -- can a tag-free cell replace the pitch tag? (stage 2)

RESEARCH ONLY. Model, per component (ride, run):

    raw_i = n_g * f_i**e + b[cell_i] * ln(rho_i / rho0),     f = rho / rho0

n_g is one neutral value per (pitcher, pitch type) group (estimation only).
`cell` decides which extra shift a pitch gets. Designs:
    none     no shift (the one-exponent-per-component model)
    tag      cell = pitch type                      (reads the tag)
    axis..   cell = spin-axis sector x speed band   (reads no tag: RTilt + velocity)
Exponents and shifts come from five seasons and are scored on the sixth, on the
same pitches and the same target for every design. Second reads: the Coors gap
by pitch type, and the Mexico City games (7,349 ft, never in a fit for 2023 /
2024 / 2026 when that season is the held-out one).

Usage: .venv/bin/python scripts/research/weather/wx_cell_shift.py [model|obsPH]
"""
import os, sys, json
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wx_exponent_sweep import load, OUT, RHO0, YEARS, PT, COORS, MIN_N

EG = [round(0.5 + 0.05 * i, 2) for i in range(23)]      # 0.50 .. 1.60
GROUP_MIN = 50      # pitches per (pitcher, pitch type, base axis cell); convention
MEX = 5340
COMPS = (('hb_arm', 'run'), ('ivb', 'ride'))


def cells(d, design):
    if design == 'none':
        return np.zeros(len(d['pt']), dtype=np.int64), 1
    if design == 'tag':
        return d['pt'].astype(np.int64), 8
    _, width, bands = design.split('_')          # axis_30_2
    width = int(width)
    phi = np.radians(d['axis'])
    ux = np.where(d['rhp'], -np.sin(phi), np.sin(phi)); uz = -np.cos(phi)
    ang = (np.degrees(np.arctan2(uz, ux)) + 360.0) % 360.0
    sec = np.minimum((ang // width).astype(np.int64), 360 // width - 1)
    cuts = {'1': [], '2': [88.0], '3': [84.0, 90.0]}[bands]      # conventions, compared below
    band = np.digitize(d['velo'], cuts)
    nb = len(cuts) + 1
    return sec * nb + band, (360 // width) * nb


def prep(d, dens):
    ok = np.isfinite(d['axis']) & np.isfinite(d['velo'])
    d = {k: v[ok] for k, v in d.items()}
    # ESTIMATION groups are (pitcher, pitch type, base axis cell: 15 degrees x 3 speed bands).
    # Every design's cell is nested in that group, so a shift is identified only by
    # density changes inside a group. Without the nesting the shift term lets the spin
    # axis predict movement inside a pitcher's group (2026-11-20: a false -55 gain).
    base, _ = cells(d, 'axis_15_3')
    key = (d['pid'].astype(np.int64) * 16 + d['pt']) * 128 + base
    g = np.unique(key, return_inverse=True)[1]
    big = np.bincount(g)[g] >= GROUP_MIN
    d = {k: v[big] for k, v in d.items()}
    key = key[big]
    d['g'] = np.unique(key, return_inverse=True)[1]
    d['gpt'] = np.unique(d['pid'].astype(np.int64) * 16 + d['pt'], return_inverse=True)[1]
    d['lr'] = np.log(d[f'rho_{dens}'] / RHO0)
    return d


def stats(d, cell, K):
    """Sufficient statistics per component and exponent: the K x K normal equations
    for b after the group-specific f is partialled out."""
    g, ng, lr = d['g'], d['g'].max() + 1, d['lr']
    S = {}
    for comp, lab in COMPS:
        x = d[comp]
        for e in EG:
            f = np.exp(e * lr)
            ff = np.bincount(g, weights=f * f, minlength=ng)
            xf = np.bincount(g, weights=x * f, minlength=ng)
            G = np.zeros((ng, K))
            np.add.at(G, (g, cell), lr * f)
            zz = np.bincount(cell, weights=lr * lr, minlength=K)
            zx = np.bincount(cell, weights=lr * x, minlength=K)
            A = np.diag(zz) - G.T @ (G / ff[:, None])
            v = zx - G.T @ (xf / ff)
            sxx = float(x @ x - np.sum(xf * xf / ff))
            S[(lab, e)] = (A, v, sxx)
    return S


def solve(A, v):
    return np.linalg.solve(A + 1e-9 * np.eye(len(v)), v)


def gap_tables(d, adj, mask, min_hi=25):
    g, ng = d['gpt'], d['gpt'].max() + 1
    nC = np.bincount(g, weights=mask, minlength=ng); nE = np.bincount(g, weights=~mask, minlength=ng)
    ok = (nC >= min_hi) & (nE >= 25)
    w = np.where(ok, 1 / (1 / np.maximum(nC, 1) + 1 / np.maximum(nE, 1)), 0.0)
    ptg = np.zeros(ng, int); ptg[g] = d['pt']
    dd = (np.bincount(g, weights=adj * mask, minlength=ng) / np.maximum(nC, 1)
          - np.bincount(g, weights=adj * ~mask, minlength=ng) / np.maximum(nE, 1))
    out = {}
    for i, p in enumerate(PT):
        m = ok & (ptg == i)
        if m.sum() >= (5 if min_hi >= 25 else 3):
            out[p] = (float(np.sum(w[m] * dd[m]) / w[m].sum()), int(m.sum()))
    return out


def main():
    dens = sys.argv[1] if len(sys.argv) > 1 else 'obsPH'
    designs = ['none', 'tag', 'axis_15_1', 'axis_15_3', 'axis_30_1', 'axis_30_3', 'axis_45_3', 'axis_90_3']
    if len(sys.argv) > 2:
        designs = sys.argv[2].split(',')
    obs = json.load(open(os.path.join(OUT, 'game_obs.json')))
    ST, N = {}, {}
    for yr in YEARS:
        d = prep(load(yr, obs), dens)
        N[yr] = len(d['g'])
        for des in designs:
            c, K = cells(d, des)
            ST[(yr, des)] = stats(d, c, K)
        print(f'{yr}: {N[yr]} pitches', flush=True)
        del d
    R = dict(density=dens)
    base = {y: sum(ST[(y, 'none')][(lab, 1.05)][2] for _, lab in COMPS) for y in YEARS}
    fits = {}
    ABS = {}
    print(f'\nLEAVE ONE SEASON OUT ({dens} density): held-out MSE minus shipped exponent, x1000 in^2')
    for des in designs:
        row = []
        for y in YEARS:
            tr = [t for t in YEARS if t != y]
            sse = 0.0; fit = {}
            for _, lab in COMPS:
                best = None
                for e in EG:
                    A = sum(ST[(t, des)][(lab, e)][0] for t in tr); v = sum(ST[(t, des)][(lab, e)][1] for t in tr)
                    sxx = sum(ST[(t, des)][(lab, e)][2] for t in tr)
                    b = solve(A, v) if des != 'none' else np.zeros(1)
                    s = sxx - 2 * b @ v + b @ A @ b
                    if best is None or s < best[0]:
                        best = (s, e, b)
                _, e, b = best
                A, v, sxx = ST[(y, des)][(lab, e)]
                sse += sxx - 2 * b @ v + b @ A @ b
                fit[lab] = (e, b)
            fits[(des, y)] = fit
            row.append(1000 * (sse - base[y]) / N[y])
            ABS.setdefault(des, []).append(1000 * sse / N[y])
        R[des] = row
        print(f' {des:10s} ' + ' '.join(f'{v:+7.2f}' for v in row) + f'   mean {np.mean(row):+7.2f}  wins {sum(v < 0 for v in row)}/6'
              f'   e run {sorted({fits[(des, y)]["run"][0] for y in YEARS})} ride {sorted({fits[(des, y)]["ride"][0] for y in YEARS})}'
              f'   ABS {" ".join(f"{v:.2f}" for v in ABS[des])} mean {np.mean(ABS[des]):.2f}')

    show = [x for x in ['none', 'tag', 'axis_30_3', 'axis_15_3'] if x in designs]
    print('\nHELD-OUT GAPS, inches: adjusted in the high park minus the same pitcher elsewhere')
    GC = {des: {} for des in show}; GM = {des: {} for des in show}; GS = {}
    for y in YEARS:
        d = prep(load(y, obs), dens)
        for des in ['ship'] + show:
            c, K = cells(d, des if des != 'ship' else 'none')
            for comp, lab in COMPS:
                if des == 'ship':
                    adj = d[comp] / np.exp(1.05 * d['lr'])
                else:
                    e, b = fits[(des, y)][lab]
                    adj = (d[comp] - b[c] * d['lr']) / np.exp(e * d['lr'])
                tgt = GS if des == 'ship' else GC[des]
                for p, (v, k) in gap_tables(d, adj, d['venue'] == COORS).items():
                    tgt.setdefault(f'{lab}_{p}', []).append(v)
                if (d['venue'] == MEX).sum() > 200:
                    gm = gap_tables(d, adj, d['venue'] == MEX, min_hi=10)
                    (GM.setdefault('ship', {}) if des == 'ship' else GM[des]).setdefault(lab, []).append(
                        {p: v for p, v in gm.items()})
        del d
    print(' Coors, mean of six held-out seasons (sd):')
    for key in sorted(GS):
        if len(GS[key]) < 4:
            continue
        print(f'  {key:8s} ship {np.mean(GS[key]):+.2f} | ' + ' | '.join(
            f'{des} {np.mean(GC[des][key]):+.2f} ({np.std(GC[des][key]):.2f})' for des in show))
    rms = lambda des, src: np.sqrt(np.mean([np.mean(v) ** 2 for k, v in src.items() if len(v) >= 4]))
    print('  RMS of the mean gap over pitch types x components: ship %.2f | ' % rms('ship', GS) +
          ' | '.join(f'{des} {rms(des, GC[des]):.2f}' for des in show))
    print(' Mexico City (each series: type gap (groups)), ride then run:')
    for des in ['ship'] + show:
        for lab in ('ride', 'run'):
            for s in GM.get(des, {}).get(lab, []):
                print(f'  {des:10s} {lab:4s} ' + '  '.join(f'{p} {v[0]:+.2f} (k{v[1]})' for p, v in s.items()))
    R['coors'] = dict(ship=GS, **GC); R['mexico'] = GM
    R['fits_2026_heldout'] = {des: {lab: dict(e=fits[(des, 2026)][lab][0], b=[float(x) for x in fits[(des, 2026)][lab][1]])
                                    for lab in ('run', 'ride')} for des in show}
    json.dump(R, open(os.path.join(OUT, f'cell_shift_{dens}.json'), 'w'), indent=1, default=float)


if __name__ == '__main__':
    main()
