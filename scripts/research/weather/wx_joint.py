"""wx_joint.py -- the joint tag-free candidate, swept as one model (stage 2).

RESEARCH ONLY. Per component (run in the arm-side frame, ride):

    raw_i = n_g * f_i**e  +  Z_i @ b            f = rho / rho0

rho: measured pressure and humidity, temperature = 50/50 feed and measured (w50).
n_g: one neutral value per (pitcher, pitch type, base axis cell) group, estimation only.
Z columns, switched on by design:
    cell    ln(f) x [spin-axis 30-degree sector x 3 speed bands]     (reads no tag)
    xwind   feed crosswind mph, signed into the arm frame            (run only)
    hwind   feed headwind mph x the group's mean movement / 100      (percent per mph)
    hand    ln(f) x [right-hander]                                   (a hand gap in the density response)
    park    one sideways offset per park, lab frame (catcher view), signed into the arm frame (run only)
Exponent and b come from five seasons and are scored on the sixth; same pitches
and same target for every design, so the held-out errors compare directly.

Usage: .venv/bin/python scripts/research/weather/wx_joint.py [density]
"""
import os, sys, json
import numpy as np
import scipy.sparse as sp

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wx_exponent_sweep import load, OUT, RHO0, YEARS, PT, COORS
from wx_cell_shift import cells, prep as prep_cs, gap_tables
from wx_wind_hand_month import wind_arrays

EG = [round(0.5 + 0.05 * i, 2) for i in range(23)]
DESIGNS = {'exp': [], 'cell': ['cell'], 'cell+xw': ['cell', 'xwind'], 'cell+xw+hw': ['cell', 'xwind', 'hwind'],
           'cell+w+hand': ['cell', 'xwind', 'hwind', 'hand'], 'cell+w+park': ['cell', 'xwind', 'hwind', 'park'],
           'cell+w+hand+park': ['cell', 'xwind', 'hwind', 'hand', 'park']}
CELL = 'axis_30_3'


def build(d, W, venues):
    """Sparse design blocks per component. Returns {lab: (Z csr, {block: column slice})}."""
    n = len(d['g'])
    c, K = cells(d, CELL)
    lr = d['lr']
    head, cross = wind_arrays(d['pk'], W)
    head = np.where(d['closed'] | ~np.isfinite(head), 0.0, head)
    cross = np.where(d['closed'] | ~np.isfinite(cross), 0.0, cross)
    s = np.where(d['rhp'], -1.0, 1.0)                 # catcher-frame x -> arm-side frame
    rows = np.arange(n)
    vidx = np.array([venues.get(int(v), -1) for v in d['venue']])
    out = {}
    for comp, lab in (('hb_arm', 'run'), ('ivb', 'ride')):
        g, ng = d['g'], d['g'].max() + 1
        gmean = (np.bincount(g, weights=d[comp], minlength=ng) / np.bincount(g, minlength=ng))[g]
        blocks, sl, col = [], {}, 0
        blocks.append(sp.csr_matrix((lr, (rows, c)), shape=(n, K))); sl['cell'] = slice(col, col + K); col += K
        blocks.append(sp.csr_matrix((cross * s if lab == 'run' else np.zeros(n))[:, None])); sl['xwind'] = slice(col, col + 1); col += 1
        blocks.append(sp.csr_matrix((head * gmean / 100.0)[:, None])); sl['hwind'] = slice(col, col + 1); col += 1
        blocks.append(sp.csr_matrix((lr * d['rhp'])[:, None])); sl['hand'] = slice(col, col + 1); col += 1
        ok = vidx >= 0
        V = len(venues)
        blocks.append(sp.csr_matrix(((s[ok] if lab == 'run' else np.zeros(ok.sum())), (rows[ok], vidx[ok])), shape=(n, V)))
        sl['park'] = slice(col, col + V); col += V
        out[lab] = (sp.hstack(blocks, format='csr'), sl)
    return out


def stats(d, ZZ):
    g, ng, n = d['g'], d['g'].max() + 1, len(d['g'])
    Mg = sp.csr_matrix((np.ones(n), (g, np.arange(n))), shape=(ng, n))
    S = {}
    for comp, lab in (('hb_arm', 'run'), ('ivb', 'ride')):
        Z, _ = ZZ[lab]; x = d[comp]
        ZtZ = (Z.T @ Z).toarray(); Ztx = Z.T @ x; xx = float(x @ x)
        for e in EG:
            f = np.exp(e * d['lr'])
            ff = Mg @ (f * f); xf = Mg @ (x * f)
            G = (Mg @ sp.diags(f) @ Z).toarray()                     # ng x C
            S[(lab, e)] = (ZtZ - G.T @ (G / ff[:, None]), Ztx - G.T @ (xf / ff), xx - float(np.sum(xf * xf / ff)))
    return S


def cols(sl, terms, C):
    m = np.zeros(C, bool)
    for t in terms:
        m[sl[t]] = True
    return m


def fit(ST, years, lab, m):
    best = None
    for e in EG:
        A = sum(ST[y][(lab, e)][0] for y in years)[np.ix_(m, m)]; v = sum(ST[y][(lab, e)][1] for y in years)[m]
        sxx = sum(ST[y][(lab, e)][2] for y in years)
        b = np.linalg.solve(A + 1e-6 * np.eye(m.sum()), v) if m.any() else np.zeros(0)
        s = sxx - (2 * b @ v - b @ A @ b if m.any() else 0.0)
        if best is None or s < best[0]:
            best = (s, e, b)
    return best


def score(ST, y, lab, m, e, b):
    A, v, sxx = ST[y][(lab, e)]
    if not m.any():
        return sxx
    A = A[np.ix_(m, m)]; v = v[m]
    return sxx - 2 * b @ v + b @ A @ b


def main():
    dens = sys.argv[1] if len(sys.argv) > 1 else 'w50'
    obs = json.load(open(os.path.join(OUT, 'game_obs.json')))
    W = json.load(open(os.path.join(OUT, 'wind.json')))
    vset = set()
    for yr in YEARS:
        z = np.load(os.path.join(OUT, f'frame_{yr}.npz')); v, cnt = np.unique(z['venue'], return_counts=True)
        vset |= {int(a) for a, b_ in zip(v, cnt) if b_ >= 20000 and a > 0}
    venues = {v: i for i, v in enumerate(sorted(vset))}
    ST, N, SL = {}, {}, None
    for yr in YEARS:
        d = prep_cs(load(yr, obs), dens)
        ZZ = build(d, W, venues); SL = {lab: ZZ[lab][1] for lab in ZZ}; C = ZZ['run'][0].shape[1]
        ST[yr] = stats(d, ZZ); N[yr] = len(d['g'])
        print(f'{yr}: {N[yr]} pitches, {C} columns', flush=True)
        del d, ZZ
    R = dict(density=dens, venues=venues)
    base = {y: sum(ST[y][(lab, 1.05)][2] for lab in ('run', 'ride')) for y in YEARS}
    FIT = {}
    print(f'\nLEAVE ONE SEASON OUT ({dens}): held-out MSE minus shipped exponent on this density, x1000 in^2')
    for name, terms in DESIGNS.items():
        row = []
        for y in YEARS:
            tr = [t for t in YEARS if t != y]; sse = 0.0
            for lab in ('run', 'ride'):
                m = cols(SL[lab], terms, C)
                _, e, b = fit(ST, tr, lab, m)
                FIT[(name, y, lab)] = (e, b, m)
                sse += score(ST, y, lab, m, e, b)
            row.append(1000 * (sse - base[y]) / N[y])
        R[name] = row
        es = lambda lab: sorted({FIT[(name, y, lab)][0] for y in YEARS})
        print(f' {name:17s} ' + ' '.join(f'{v:+7.2f}' for v in row) + f'   mean {np.mean(row):+7.2f}  wins {sum(v < 0 for v in row)}/6'
              f'   e run {es("run")} ride {es("ride")}')
    print(' step gains (mean, and seasons in which the larger model is better):')
    order = ['exp', 'cell', 'cell+xw', 'cell+xw+hw', 'cell+w+hand', 'cell+w+park', 'cell+w+hand+park']
    for a, b_ in (('exp', 'cell'), ('cell', 'cell+xw'), ('cell+xw', 'cell+xw+hw'), ('cell+xw+hw', 'cell+w+hand'),
                  ('cell+xw+hw', 'cell+w+park'), ('cell+w+park', 'cell+w+hand+park')):
        dl = [y2 - y1 for y1, y2 in zip(R[a], R[b_])]
        print(f'   {a} -> {b_}: {np.mean(dl):+.2f}  ({sum(v < 0 for v in dl)}/6)')

    # full-sample fit of each design, and the terms' sizes
    print('\nFULL-SAMPLE terms (six seasons)')
    FULL = {}
    for name, terms in DESIGNS.items():
        for lab in ('run', 'ride'):
            m = cols(SL[lab], terms, C); _, e, b = fit(ST, YEARS, lab, m)
            bf = np.zeros(C); bf[m] = b
            FULL[(name, lab)] = (e, bf)
    for name in ('cell+xw+hw', 'cell+w+hand+park'):
        for lab in ('run', 'ride'):
            e, bf = FULL[(name, lab)]; sl = SL[lab]
            msg = f' {name} {lab}: e {e}'
            if lab == 'run':
                msg += f' | crosswind {bf[sl["xwind"]][0]:+.4f} in per mph'
            msg += f' | headwind {bf[sl["hwind"]][0]:+.3f}% per mph'
            if 'hand' in name:
                msg += f' | hand x ln(f) {bf[sl["hand"]][0]:+.2f} in (at Coors {-0.19*bf[sl["hand"]][0]:+.2f} in for a right-hander)'
            print(msg)
            if 'park' in name and lab == 'run':
                pv = bf[sl['park']]; inv = {i: v for v, i in venues.items()}
                top = sorted(range(len(pv)), key=lambda i: -abs(pv[i] - np.median(pv)))[:8]
                print('    park sideways offsets, inches (catcher view, minus the median): ' +
                      '  '.join(f'{inv[i]}:{pv[i]-np.median(pv):+.2f}' for i in top) + f'   sd {np.std(pv):.2f}')
    R['full'] = {f'{k[0]}|{k[1]}': dict(e=v[0], b=[float(x) for x in v[1]]) for k, v in FULL.items()}
    R['slices'] = {lab: {k: [s.start, s.stop] for k, s in SL[lab].items()} for lab in SL}

    # held-out Coors gaps by tag (diagnostic only) and by hand
    show = ['exp', 'cell', 'cell+xw+hw', 'cell+w+hand', 'cell+w+hand+park']
    GC = {k: {} for k in ['ship'] + show}; GH = {k: {} for k in ['ship'] + show}
    for y in YEARS:
        d = prep_cs(load(y, obs), dens); ZZ = build(d, W, venues)
        at = d['venue'] == COORS
        for name in ['ship'] + show:
            for comp, lab in (('hb_arm', 'run'), ('ivb', 'ride')):
                if name == 'ship':
                    adj = d[comp] / np.exp(1.05 * d['lr'])
                else:
                    e, b, m = FIT[(name, y, lab)]
                    bf = np.zeros(C); bf[m] = b
                    adj = (d[comp] - ZZ[lab][0] @ bf) / np.exp(e * d['lr'])
                for p, (v, k) in gap_tables(d, adj, at).items():
                    GC[name].setdefault(f'{lab}_{p}', []).append(v)
                for hand, hm in (('R', d['rhp']), ('L', ~d['rhp'])):
                    dd = {k: v[hm] for k, v in d.items() if isinstance(v, np.ndarray) and len(v) == len(hm)}
                    dd['gpt'] = np.unique(dd['gpt'], return_inverse=True)[1]
                    gt = gap_tables(dd, adj[hm], at[hm])
                    if 'FF' in gt:
                        GH[name].setdefault(f'{lab}_FF_{hand}', []).append(gt['FF'][0])
        del d, ZZ
    print('\nHELD-OUT COORS GAP, inches, mean of six seasons')
    for key in sorted(GC['ship']):
        if len(GC['ship'][key]) >= 4:
            print(f'  {key:8s} ' + ' | '.join(f'{n_} {np.mean(GC[n_][key]):+.2f}' for n_ in ['ship'] + show))
    rms = lambda n_: np.sqrt(np.mean([np.mean(v) ** 2 for v in GC[n_].values() if len(v) >= 4]))
    print('  RMS      ' + ' | '.join(f'{n_} {rms(n_):.2f}' for n_ in ['ship'] + show))
    for key in sorted(GH['ship']):
        print(f'  {key:10s} ' + ' | '.join(f'{n_} {np.mean(GH[n_][key]):+.2f}' for n_ in ['ship'] + show))
    R['coors'] = GC; R['coors_hand'] = GH
    json.dump(R, open(os.path.join(OUT, f'joint_{dens}.json'), 'w'), indent=1, default=float)


if __name__ == '__main__':
    main()
