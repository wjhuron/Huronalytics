"""wx_final_fit.py -- the two final versions, side by side.  RESEARCH ONLY.

Both: measured-pressure density (w50), pressure / temperature split exponents and
spin-axis cell shifts, crosswind, headwind. NO park offset.
    nohand     no hand term
    handride   right-hander x ln(pressure) term for RIDE only
Exponents and coefficients from five seasons, scored on the sixth. Then the
full-sample fit of each version is applied UNCHANGED to Triple-A (wind off).
"""
import os, sys, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wx_exponent_sweep import load, OUT, RHO0, YEARS, COORS
from wx_cell_shift import prep as prep_cs, gap_tables
from wx_aaa_validate import load_aaa
import wx_joint_split as J

VERS = ('nohand', 'handride')


def mask(C, K, ver, lab):
    m = np.zeros(C, bool); m[:2 * K + 2] = True              # cells P, cells T, crosswind, headwind
    if ver == 'handride' and lab == 'ride':
        m[2 * K + 2] = True
    return m


def fit(ST, years, lab, m):
    best = None
    for ep in J.EP:
        for et in J.ET:
            A = sum(ST[y][(lab, ep, et)][0] for y in years)[np.ix_(m, m)]; v = sum(ST[y][(lab, ep, et)][1] for y in years)[m]
            sxx = sum(ST[y][(lab, ep, et)][2] for y in years)
            b = np.linalg.solve(A + 1e-6 * np.eye(m.sum()), v)
            s = sxx - 2 * b @ v + b @ A @ b
            if best is None or s < best[0]:
                bf = np.zeros(len(m)); bf[m] = b
                best = (s, ep, et, bf)
    return best


def hand_gaps(d, adj, hi, store, key, min_hi=25):
    for hand, hm in (('R', d['rhp']), ('L', ~d['rhp'])):
        dd = {k: v[hm] for k, v in d.items() if isinstance(v, np.ndarray) and len(v) == len(hm)}
        dd['gpt'] = np.unique(dd['gpt'], return_inverse=True)[1]
        gt = gap_tables(dd, adj[hm], hi[hm], min_hi=min_hi)
        if 'FF' in gt:
            store.setdefault(f'{key}_FF_{hand}', []).append(gt['FF'][0])


if __name__ == '__main__':
    obs = json.load(open(os.path.join(OUT, 'game_obs.json'))); W = json.load(open(os.path.join(OUT, 'wind.json')))
    ST, N = {}, {}
    for yr in YEARS:
        d = prep_cs(load(yr, obs), 'w50')
        ZZ, lnP, lnT, K = J.build(d, W, {}, park=False); C = ZZ['run'].shape[1]
        ST[yr] = J.stats(d, ZZ, lnP, lnT); N[yr] = len(d['g'])
        print(f'{yr}: {N[yr]} pitches', flush=True)
        del d, ZZ
    FIT, FULL, ABS = {}, {}, {v: [] for v in VERS}
    ship = []
    for y in YEARS:
        tr = [t for t in YEARS if t != y]
        for ver in VERS:
            sse = 0.0
            for lab in ('run', 'ride'):
                m = mask(C, K, ver, lab); _, ep, et, bf = fit(ST, tr, lab, m); FIT[(ver, y, lab)] = (ep, et, bf)
                A, v, sxx = ST[y][(lab, ep, et)]; sse += sxx - 2 * bf @ v + bf @ A @ bf
            ABS[ver].append(1000 * sse / N[y])
    print('\nHELD-OUT MSE x1000 in^2 by season')
    for ver in VERS:
        print(f' {ver:9s} ' + ' '.join(f'{v:.2f}' for v in ABS[ver]) + f'   mean {np.mean(ABS[ver]):.2f}')
    dl = [a - b for a, b in zip(ABS['handride'], ABS['nohand'])]
    print(f' handride minus nohand: ' + ' '.join(f'{v:+.2f}' for v in dl) + f'   mean {np.mean(dl):+.2f}  ({sum(v < 0 for v in dl)}/6 better)')
    for ver in VERS:
        for lab in ('run', 'ride'):
            m = mask(C, K, ver, lab); _, ep, et, bf = fit(ST, YEARS, lab, m)
            FULL[(ver, lab)] = dict(eP=ep, eT=et, b=[float(x) for x in bf])
            picks = sorted({FIT[(ver, y, lab)][:2] for y in YEARS})
            print(f' {ver} {lab}: full sample eP {ep} eT {et}; held-out picks {picks}; crosswind {bf[2*K]:+.4f}; headwind {bf[2*K+1]:+.3f}%; hand {bf[2*K+2]:+.2f}')
    json.dump({f'{k[0]}|{k[1]}': v for k, v in FULL.items()} | {'K': K}, open(os.path.join(OUT, 'final_fit.json'), 'w'), indent=1)

    GC = {v: {} for v in ('ship',) + VERS}; GH = {v: {} for v in ('ship',) + VERS}
    for y in YEARS:
        d = prep_cs(load(y, obs), 'w50'); ZZ, lnP, lnT, K = J.build(d, W, {}, park=False); at = d['venue'] == COORS
        for ver in ('ship',) + VERS:
            for comp, lab in (('hb_arm', 'run'), ('ivb', 'ride')):
                if ver == 'ship':
                    adj = d[comp] / np.exp(1.05 * np.log(d['rho_model'] / RHO0))
                else:
                    ep, et, bf = FIT[(ver, y, lab)]
                    adj = (d[comp] - ZZ[lab] @ bf) / np.exp(ep * lnP + et * lnT)
                for p, (v, k) in gap_tables(d, adj, at).items():
                    GC[ver].setdefault(f'{lab}_{p}', []).append(v)
                hand_gaps(d, adj, at, GH[ver], lab)
        del d, ZZ
    rms = lambda G: np.sqrt(np.mean([np.mean(v) ** 2 for v in G.values() if len(v) >= 4]))
    print('\nCOORS, held out, adjusted at Coors minus same pitcher elsewhere, inches (mean of six seasons)')
    for key in sorted(GC['ship']):
        if len(GC['ship'][key]) >= 4:
            print(f'  {key:8s} ' + ' | '.join(f'{v} {np.mean(GC[v][key]):+.2f}' for v in ('ship',) + VERS))
    print('  RMS      ' + ' | '.join(f'{v} {rms(GC[v]):.2f}' for v in ('ship',) + VERS))
    for key in sorted(GH['ship']):
        print(f'  {key:10s} ' + ' | '.join(f'{v} {np.mean(GH[v][key]):+.2f} (sd {np.std(GH[v][key]):.2f})' for v in ('ship',) + VERS))

    obsA = json.load(open(os.path.join(OUT, 'game_obs_aaa.json')))
    GA = {v: {} for v in ('ship',) + VERS}; GAH = {v: {} for v in ('ship',) + VERS}
    for yr in (2023, 2024, 2025, 2026):
        d = prep_cs(load_aaa(yr, obsA), 'w50'); ZZ, lnP, lnT, _ = J.build(d, None, {}, park=False)
        hi = d['elev'] >= 3000; keep = hi | (d['elev'] < 1500)
        dk = {k: v[keep] for k, v in d.items() if isinstance(v, np.ndarray) and len(v) == len(keep)}
        dk['gpt'] = np.unique(dk['gpt'], return_inverse=True)[1]
        for ver in ('ship',) + VERS:
            for comp, lab in (('hb_arm', 'run'), ('ivb', 'ride')):
                if ver == 'ship':
                    adj = d[comp] / np.exp(1.05 * np.log(d['rho_model'] / RHO0))
                else:
                    f = FULL[(ver, lab)]; b = np.array(f['b']); b[2 * K] = 0.0; b[2 * K + 1] = 0.0
                    adj = (d[comp] - ZZ[lab] @ b) / np.exp(f['eP'] * lnP + f['eT'] * lnT)
                for p, (v, k) in gap_tables(dk, adj[keep], hi[keep]).items():
                    GA[ver].setdefault(f'{lab}_{p}', []).append(v)
                hand_gaps(dk, adj[keep], hi[keep], GAH[ver], lab)
        del d, ZZ
    rms3 = lambda G: np.sqrt(np.mean([np.mean(v) ** 2 for v in G.values() if len(v) >= 3]))
    print('\nTRIPLE-A altitude parks, nothing fitted there, inches (mean of the seasons)')
    for key in sorted(GA['ship']):
        if len(GA['ship'][key]) >= 3:
            print(f'  {key:8s} ' + ' | '.join(f'{v} {np.mean(GA[v][key]):+.2f}' for v in ('ship',) + VERS))
    print('  RMS      ' + ' | '.join(f'{v} {rms3(GA[v]):.2f}' for v in ('ship',) + VERS))
    for key in sorted(GAH['ship']):
        print(f'  {key:10s} ' + ' | '.join(f'{v} {np.mean(GAH[v][key]):+.2f} (sd {np.std(GAH[v][key]):.2f})' for v in ('ship',) + VERS))
    json.dump(dict(abs=ABS, coors=GC, coors_hand=GH, aaa=GA, aaa_hand=GAH), open(os.path.join(OUT, 'final_compare.json'), 'w'), indent=1, default=float)
