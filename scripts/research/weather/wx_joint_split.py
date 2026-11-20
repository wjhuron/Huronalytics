"""wx_joint_split.py -- the joint model with pressure and temperature split.

RESEARCH ONLY. The feed temperature is a noisy reading (drag responds to it with
about .75 of the physical slope), so a coefficient fitted on total density is
biased low for altitude. Here ln(f) = lnP (pressure + humidity) + lnT (temperature),
and each gets its own exponent and its own cell shifts:

    raw = n_g * exp(eP*lnP + eT*lnT) + cellP @ bP * lnP + cellT @ bT * lnT + wind + hand*lnP + park

Compared, held out by season, with the unsplit model on the same pitches.
Writes the full-sample coefficients to data/_weather_audit/joint_split_full.json
for the Triple-A validation.
"""
import os, sys, json
import numpy as np
import scipy.sparse as sp
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wx_exponent_sweep import load, OUT, RHO0, YEARS, PT, COORS
from wx_cell_shift import cells, prep as prep_cs, gap_tables
from wx_wind_hand_month import wind_arrays

EP = [round(0.80 + 0.05 * i, 2) for i in range(19)]      # 0.80 .. 1.70
ET = [round(0.40 + 0.10 * i, 2) for i in range(12)]      # 0.40 .. 1.50
CELL = 'axis_30_3'
T0K = 295.6


def parts(d):
    tb = np.where(d['closed'], 72.0, 0.5 * d['temp'] + 0.5 * d['obs_t'])
    lnT = -np.log(((tb - 32) * 5 / 9 + 273.15) / T0K)
    return d['lr'] - lnT, lnT


def build(d, W, venues, park=True):
    n = len(d['g']); c, K = cells(d, CELL)
    lnP, lnT = parts(d)
    head, cross = (wind_arrays(d['pk'], W) if W is not None else (np.zeros(n), np.zeros(n)))
    head = np.where(d['closed'] | ~np.isfinite(head), 0.0, head)
    cross = np.where(d['closed'] | ~np.isfinite(cross), 0.0, cross)
    s = np.where(d['rhp'], -1.0, 1.0); rows = np.arange(n)
    vidx = np.array([venues.get(int(v), -1) for v in d['venue']]); ok = vidx >= 0; V = len(venues)
    out = {}
    for comp, lab in (('hb_arm', 'run'), ('ivb', 'ride')):
        g, ng = d['g'], d['g'].max() + 1
        gmean = (np.bincount(g, weights=d[comp], minlength=ng) / np.bincount(g, minlength=ng))[g]
        B = [sp.csr_matrix((lnP, (rows, c)), shape=(n, K)), sp.csr_matrix((lnT, (rows, c)), shape=(n, K)),
             sp.csr_matrix((cross * s if lab == 'run' else np.zeros(n))[:, None]),
             sp.csr_matrix((head * gmean / 100.0)[:, None]),
             sp.csr_matrix((lnP * d['rhp'])[:, None]),
             sp.csr_matrix(((s[ok] if (lab == 'run' and park) else np.zeros(ok.sum())), (rows[ok], vidx[ok])), shape=(n, V))]
        out[lab] = sp.hstack(B, format='csr')
    return out, lnP, lnT, K


def stats(d, ZZ, lnP, lnT):
    g, ng, n = d['g'], d['g'].max() + 1, len(d['g'])
    Mg = sp.csr_matrix((np.ones(n), (g, np.arange(n))), shape=(ng, n))
    S = {}
    for comp, lab in (('hb_arm', 'run'), ('ivb', 'ride')):
        Z = ZZ[lab]; x = d[comp]
        ZtZ = (Z.T @ Z).toarray(); Ztx = Z.T @ x; xx = float(x @ x)
        for ep in EP:
            for et in ET:
                f = np.exp(ep * lnP + et * lnT)
                ff = Mg @ (f * f); xf = Mg @ (x * f)
                G = (Mg @ sp.diags(f) @ Z).toarray()
                S[(lab, ep, et)] = (ZtZ - G.T @ (G / ff[:, None]), Ztx - G.T @ (xf / ff), xx - float(np.sum(xf * xf / ff)))
    return S


def fit(ST, years, lab, C):
    best = None
    for ep in EP:
        for et in ET:
            A = sum(ST[y][(lab, ep, et)][0] for y in years); v = sum(ST[y][(lab, ep, et)][1] for y in years)
            sxx = sum(ST[y][(lab, ep, et)][2] for y in years)
            b = np.linalg.solve(A + 1e-6 * np.eye(C), v)
            s = sxx - 2 * b @ v + b @ A @ b
            if best is None or s < best[0]:
                best = (s, ep, et, b)
    return best


if __name__ == '__main__':
    obs = json.load(open(os.path.join(OUT, 'game_obs.json'))); W = json.load(open(os.path.join(OUT, 'wind.json')))
    venues = {int(k): v for k, v in json.load(open(os.path.join(OUT, 'joint_w50.json')))['venues'].items()}
    ST, N = {}, {}
    for yr in YEARS:
        d = prep_cs(load(yr, obs), 'w50')
        ZZ, lnP, lnT, K = build(d, W, venues); C = ZZ['run'].shape[1]
        ST[yr] = stats(d, ZZ, lnP, lnT); N[yr] = len(d['g'])
        base = sum(float(d[c] @ d[c]) for c in ('hb_arm', 'ivb'))
        print(f'{yr}: {N[yr]} pitches', flush=True)
        del d, ZZ
    prev = json.load(open(os.path.join(OUT, 'joint_w50.json')))
    FIT = {}; row = []
    for y in YEARS:
        tr = [t for t in YEARS if t != y]; sse = 0.0
        for lab in ('run', 'ride'):
            _, ep, et, b = fit(ST, tr, lab, C); FIT[(y, lab)] = (ep, et, b)
            A, v, sxx = ST[y][(lab, ep, et)]; sse += sxx - 2 * b @ v + b @ A @ b
        row.append(1000 * sse / N[y])
    print('\nheld-out picks (eP, eT): run', [FIT[(y, 'run')][:2] for y in YEARS], ' ride', [FIT[(y, 'ride')][:2] for y in YEARS])
    FULL = {}
    for lab in ('run', 'ride'):
        _, ep, et, b = fit(ST, YEARS, lab, C); FULL[lab] = dict(eP=ep, eT=et, b=[float(x) for x in b])
        edge = ep in (EP[0], EP[-1]) or et in (ET[0], ET[-1])
        print(f' full sample {lab}: eP {ep} eT {et}{" EDGE" if edge else ""} | crosswind {b[2*K]:+.4f} | headwind {b[2*K+1]:+.3f}% | hand {b[2*K+2]:+.2f}')
    json.dump(dict(K=K, venues=venues, fit=FULL, heldout_abs=row), open(os.path.join(OUT, 'joint_split_full.json'), 'w'), indent=1)
    # compare with the unsplit model on absolute held-out error: recompute the unsplit base
    print(' split model held-out MSE x1000: ' + ' '.join(f'{v:.2f}' for v in row) + f'  mean {np.mean(row):.2f}')
    # Coors gaps, held out
    GC, GH = {}, {}
    for y in YEARS:
        d = prep_cs(load(y, obs), 'w50'); ZZ, lnP, lnT, K = build(d, W, venues); at = d['venue'] == COORS
        for comp, lab in (('hb_arm', 'run'), ('ivb', 'ride')):
            ep, et, b = FIT[(y, lab)]
            adj = (d[comp] - ZZ[lab] @ b) / np.exp(ep * lnP + et * lnT)
            for p, (v, k) in gap_tables(d, adj, at).items():
                GC.setdefault(f'{lab}_{p}', []).append(v)
            for hand, hm in (('R', d['rhp']), ('L', ~d['rhp'])):
                dd = {k: v[hm] for k, v in d.items() if isinstance(v, np.ndarray) and len(v) == len(hm)}
                dd['gpt'] = np.unique(dd['gpt'], return_inverse=True)[1]
                gt = gap_tables(dd, adj[hm], at[hm])
                if 'FF' in gt:
                    GH.setdefault(f'{lab}_FF_{hand}', []).append(gt['FF'][0])
        del d, ZZ
    print('\nHELD-OUT COORS GAP, split model, inches (mean of six seasons, sd):')
    print('  ' + '  '.join(f'{k} {np.mean(v):+.2f} ({np.std(v):.2f})' for k, v in sorted(GC.items()) if len(v) >= 4))
    print('  RMS %.2f' % np.sqrt(np.mean([np.mean(v) ** 2 for v in GC.values() if len(v) >= 4])))
    print('  by hand: ' + '  '.join(f'{k} {np.mean(v):+.2f}' for k, v in sorted(GH.items())))
