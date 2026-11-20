"""wx_smooth_check.py -- two production choices, checked before the build.

RESEARCH ONLY.
  SMOOTH   the fit uses hard cells (30-degree sector x 3 speed bands), which is what keeps
           the fit honest (cells nested in the estimation group). In production a pitch near
           a cell edge would jump between two shifts. `smooth` applies the SAME fitted
           coefficients by linear interpolation between cell centres (angle periodic;
           speed centres = the mean velocity of each band, clamped at the ends).
  HEADWIND fitted as percent of the group's mean movement; `mult` applies it as a factor on
           the pitch itself: neutral = (raw - shift) / (F * (1 + h * head / 100)).
Coefficients from five seasons at the final exponents, applied to the sixth; then the
full-sample coefficients applied to Triple-A. Same target for every variant.
"""
import os, sys, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wx_exponent_sweep import load, OUT, RHO0, YEARS, COORS
from wx_cell_shift import prep as prep_cs, gap_tables, cells
from wx_aaa_validate import load_aaa
from wx_wind_hand_month import wind_arrays
import wx_joint_split as J
from wx_final_fit import mask

EXP = {'run': (1.25, 0.7), 'ride': (1.45, 1.0)}
J.EP = sorted({v[0] for v in EXP.values()}); J.ET = sorted({v[1] for v in EXP.values()})
SPEED_C = None


def coef_per_pitch(d, bvec, K, smooth):
    """Per-pitch (bP, bT) from the 36-cell vectors, hard or interpolated."""
    c, _ = cells(d, 'axis_30_3')
    if not smooth:
        return bvec[c], bvec[K + c]
    phi = np.radians(d['axis'])
    ux = np.where(d['rhp'], -np.sin(phi), np.sin(phi)); uz = -np.cos(phi)
    ang = (np.degrees(np.arctan2(uz, ux)) + 360.0) % 360.0
    a = (ang - 15.0) / 30.0; a0 = np.floor(a).astype(int); wa = a - a0
    s0 = np.clip(np.searchsorted(SPEED_C, d['velo']) - 1, 0, 1)
    ws = np.clip((d['velo'] - SPEED_C[s0]) / (SPEED_C[s0 + 1] - SPEED_C[s0]), 0.0, 1.0)
    out = []
    for off in (0, K):
        tot = 0.0
        for da, w1 in ((0, 1 - wa), (1, wa)):
            for ds, w2 in ((0, 1 - ws), (1, ws)):
                tot = tot + w1 * w2 * bvec[off + ((a0 + da) % 12) * 3 + (s0 + ds)]
        out.append(tot)
    return out[0], out[1]


def adjust(d, lab, comp, f, K, lnP, lnT, head, cross, smooth, mult, gmean=None, wind=True):
    b = np.asarray(f['b']); bP, bT = coef_per_pitch(d, b, K, smooth)
    shift = bP * lnP + bT * lnT
    F = np.exp(f['eP'] * lnP + f['eT'] * lnT)
    if wind:
        if lab == 'run':
            shift = shift + b[2 * K] * cross * np.where(d['rhp'], -1.0, 1.0)
        if mult:
            F = F * (1.0 + b[2 * K + 1] * head / 100.0)
        else:
            shift = shift + b[2 * K + 1] * head * gmean / 100.0
    return (d[comp] - shift) / F, shift, F


def sse(d, x, shift, F):
    g, ng = d['g'], d['g'].max() + 1
    r = x - shift
    return float(r @ r - np.sum(np.bincount(g, weights=r * F, minlength=ng) ** 2 / np.bincount(g, weights=F * F, minlength=ng)))


if __name__ == '__main__':
    obs = json.load(open(os.path.join(OUT, 'game_obs.json'))); W = json.load(open(os.path.join(OUT, 'wind.json')))
    ST, N, sp_sum = {}, {}, np.zeros((3, 2))
    for yr in YEARS:
        d = prep_cs(load(yr, obs), 'w50'); ZZ, lnP, lnT, K = J.build(d, W, {}, park=False); C = ZZ['run'].shape[1]
        ST[yr] = J.stats(d, ZZ, lnP, lnT); N[yr] = len(d['g'])
        band = np.digitize(d['velo'], [84.0, 90.0])
        for b_ in range(3):
            sp_sum[b_] += [d['velo'][band == b_].sum(), (band == b_).sum()]
        del d, ZZ
    SPEED_C = sp_sum[:, 0] / sp_sum[:, 1]
    print('speed centres (mean velocity of each band):', np.round(SPEED_C, 2))

    def fit(years, lab):
        ep, et = EXP[lab]; m = mask(C, K, 'nohand', lab)
        A = sum(ST[y][(lab, ep, et)][0] for y in years)[np.ix_(m, m)]; v = sum(ST[y][(lab, ep, et)][1] for y in years)[m]
        bf = np.zeros(C); bf[m] = np.linalg.solve(A + 1e-6 * np.eye(m.sum()), v)
        return dict(eP=ep, eT=et, b=bf)
    VAR = (('hard', False, False), ('smooth', True, False), ('smooth+mult', True, True))
    ABS = {v[0]: [] for v in VAR}; GC = {v[0]: {} for v in VAR}
    for y in YEARS:
        fits = {lab: fit([t for t in YEARS if t != y], lab) for lab in ('run', 'ride')}
        d = prep_cs(load(y, obs), 'w50'); ZZ, lnP, lnT, K = J.build(d, W, {}, park=False)
        head, cross = wind_arrays(d['pk'], W)
        head = np.where(d['closed'] | ~np.isfinite(head), 0.0, head); cross = np.where(d['closed'] | ~np.isfinite(cross), 0.0, cross)
        g, ng = d['g'], d['g'].max() + 1
        for name, sm, mu in VAR:
            tot = 0.0
            for comp, lab in (('hb_arm', 'run'), ('ivb', 'ride')):
                gmean = (np.bincount(g, weights=d[comp], minlength=ng) / np.bincount(g, minlength=ng))[g]
                adj, shift, F = adjust(d, lab, comp, fits[lab], K, lnP, lnT, head, cross, sm, mu, gmean)
                tot += sse(d, d[comp], shift, F)
                for p, (v, k) in gap_tables(d, adj, d['venue'] == COORS).items():
                    GC[name].setdefault(f'{lab}_{p}', []).append(v)
            ABS[name].append(1000 * tot / N[y])
        del d, ZZ
    print('\nHELD-OUT MSE x1000 (coefficients from the other five seasons)')
    for name in ABS:
        print(f' {name:12s} ' + ' '.join(f'{v:.2f}' for v in ABS[name]) + f'   mean {np.mean(ABS[name]):.2f}')
    for a, b_ in (('hard', 'smooth'), ('smooth', 'smooth+mult')):
        dl = [y2 - y1 for y1, y2 in zip(ABS[a], ABS[b_])]
        print(f'   {a} -> {b_}: {np.mean(dl):+.2f} ({sum(v < 0 for v in dl)}/6 better)')
    rms = lambda G, k=4: np.sqrt(np.mean([np.mean(v) ** 2 for v in G.values() if len(v) >= k]))
    print(' Coors RMS gap: ' + ' | '.join(f'{n} {rms(GC[n]):.3f}' for n in GC))

    FULL = {lab: fit(YEARS, lab) for lab in ('run', 'ride')}
    obsA = json.load(open(os.path.join(OUT, 'game_obs_aaa.json'))); GA = {v[0]: {} for v in VAR[:2]}
    for yr in (2023, 2024, 2025, 2026):
        d = prep_cs(load_aaa(yr, obsA), 'w50'); ZZ, lnP, lnT, _ = J.build(d, None, {}, park=False)
        hi = d['elev'] >= 3000; keep = hi | (d['elev'] < 1500)
        dk = {k: v[keep] for k, v in d.items() if isinstance(v, np.ndarray) and len(v) == len(keep)}
        dk['gpt'] = np.unique(dk['gpt'], return_inverse=True)[1]
        for name, sm, mu in VAR[:2]:
            for comp, lab in (('hb_arm', 'run'), ('ivb', 'ride')):
                adj, _, _ = adjust(d, lab, comp, FULL[lab], K, lnP, lnT, None, None, sm, False, wind=False)
                for p, (v, k) in gap_tables(dk, adj[keep], hi[keep]).items():
                    GA[name].setdefault(f'{lab}_{p}', []).append(v)
        del d, ZZ
    print(' Triple-A RMS gap: ' + ' | '.join(f'{n} {rms(GA[n], 3):.3f}' for n in GA))
    json.dump(dict(speed_centres=[float(x) for x in SPEED_C], K=K,
                   fit={lab: dict(eP=FULL[lab]['eP'], eT=FULL[lab]['eT'], b=[float(x) for x in FULL[lab]['b']]) for lab in FULL},
                   heldout=ABS), open(os.path.join(OUT, 'final_fit_smooth.json'), 'w'), indent=1)
