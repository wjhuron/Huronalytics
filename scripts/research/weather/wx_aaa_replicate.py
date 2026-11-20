"""wx_aaa_replicate.py -- the altitude test on Triple-A, 2023-2026.

RESEARCH ONLY. Same within-(pitcher, pitch type) design as wx_density_slopes.py,
on a league with five parks at 3,000 ft or more instead of one. "High" = elevation
>= 3,000 ft, "low" = under 1,500 ft (both cutoffs are conventions that separate
the two clusters; no park sits between 1,500 and 3,000 ft).
"""
import os, sys, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_density_slopes as S

OUT = S.OUT
PT = S.PT


def load(yr):
    z = np.load(os.path.join(OUT, f'frame_aaa_{yr}.npz'))
    d = {k: z[k] for k in z.files}
    ok = np.isfinite(d['rho']) & np.isfinite(d['ivb']) & np.isfinite(d['hb_arm'])
    return {k: v[ok] for k, v in d.items()}


def alt_test(d, g, comp, e=S.E_SHIP):
    ng = g.max() + 1
    hi = d['elev'] >= 3000; lo = d['elev'] < 1500
    adj = d[comp] * (S.RHO0 / d['rho']) ** e
    B = lambda w, x=None: np.bincount(g, weights=(w if x is None else x * w), minlength=ng)
    nH, nL = B(hi), B(lo)
    ok = (nH >= 25) & (nL >= 25)
    ptg = np.zeros(ng, int); ptg[g] = d['pt']
    with np.errstate(invalid='ignore', divide='ignore'):
        diff = B(hi, adj) / nH - B(lo, adj) / nL
        lr = np.log((B(hi, d[comp]) / nH) / (B(lo, d[comp]) / nL))
        dln = B(hi, np.log(d['rho'])) / nH - B(lo, np.log(d['rho'])) / nL
        mean_lo = B(lo, d[comp]) / nL
    out = {}
    for i, p in enumerate(PT[:8]):
        m = ok & (ptg == i) & (np.abs(mean_lo) >= S.MIN_ABS)
        if m.sum() < 8:
            continue
        w = 1 / (1 / nH[m] + 1 / nL[m])
        dm = np.sum(w * diff[m]) / w.sum()
        se = np.sqrt(np.sum(w * w * (diff[m] - dm) ** 2)) / w.sum()
        out[p] = dict(k=int(m.sum()), diff=float(dm), se=float(se),
                      e=float(np.sum(w * lr[m]) / np.sum(w * dln[m])),
                      mean=float(np.sum(w * mean_lo[m]) / w.sum()))
    return out


if __name__ == '__main__':
    R = {}
    for yr in (2023, 2024, 2025, 2026):
        d = load(yr); g = S.groups(d)
        R[yr] = {}
        print(f'\n===== AAA {yr}: {len(g)} pitches; high-park pitches {(d["elev"]>=3000).sum()}')
        for comp, lab in (('ivb', 'ride'), ('hb_arm', 'run')):
            a = S.elasticity(d, g, comp); sp = S.elasticity(d, g, comp, split=True)
            t = alt_test(d, g, comp)
            R[yr][lab] = dict(all=a, split=sp, alt=t)
            print(f' {lab:4s} elasticity {a["b"][0]:.3f} ({a["se"][0]:.3f}) | split P {sp["b"][0]:.3f} ({sp["se"][0]:.3f})'
                  f' T {sp["b"][1]:.3f} ({sp["se"][1]:.3f})')
            print('      high minus low, adjusted at 1.05, inches: ' + '  '.join(
                f'{p} {v["diff"]:+.2f}±{v["se"]:.2f} (e {v["e"]:.2f}, k{v["k"]})' for p, v in t.items()))
        ok = np.isfinite(d['kdrag']) & (d['kdrag'] > 0) & S.select(d, g, 'ivb', only_minabs=False)
        gg = np.unique(g[ok], return_inverse=True)[1]
        el_m = d['elev'][ok] * 0.3048
        X = np.column_stack([5.2556 * np.log(1 - 2.2558e-5 * el_m), -np.log((d['temp'][ok] - 32) * 5 / 9 + 273.15)])
        b, se = S.fe_ols(np.log(d['kdrag'][ok]), X, gg, d['pk'][ok])
        print(f' drag probe split P {b[0]:.3f} ({se[0]:.3f}) T {b[1]:.3f} ({se[1]:.3f})')
        R[yr]['drag'] = dict(P=[float(b[0]), float(se[0])], T=[float(b[1]), float(se[1])])
        del d
    json.dump(R, open(os.path.join(OUT, 'aaa_replicate.json'), 'w'), indent=1)
