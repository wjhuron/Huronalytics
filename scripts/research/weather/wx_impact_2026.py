"""wx_impact_2026.py -- what a different exponent would move, 2026 MLB rows.

RESEARCH ONLY. Recomputes the adjusted movement from the RAW sheet columns
under (a) the shipped exponent and (b) a candidate set read from
data/_weather_audit/exponent_sweep.json (full-sample cell optima on the
model density), and reports the change in each pitcher x pitch type season
mean, league-wide and for Colorado. Changes nothing.
"""
import os, sys, json, pickle, zlib
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT = os.path.join(ROOT, 'data', '_weather_audit')
PT = ['FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS']

if __name__ == '__main__':
    key = sys.argv[1] if len(sys.argv) > 1 else 'cell_opt_model'
    sw = json.load(open(os.path.join(OUT, 'exponent_sweep.json')))
    z = np.load(os.path.join(OUT, 'frame_2026.npz')); d = {k: z[k] for k in z.files}
    ok = (d['minors'] == 0) & np.isfinite(d['ivb']) & np.isfinite(d['hb_arm']) & (d['pt'] < 8)
    d = {k: v[ok] for k, v in d.items()}
    lr = np.log(1.195 / d['rho'])
    g = np.unique(d['pid'] * 16 + d['pt'], return_inverse=True)[1]; ng = g.max() + 1
    n = np.bincount(g, minlength=ng)
    share_c = np.bincount(g, weights=d['venue'] == 19, minlength=ng) / n
    ptg = np.zeros(ng, int); ptg[g] = d['pt']
    print(f'candidate = {key}; groups with 100+ pitches: {(n>=100).sum()}')
    for comp, lab in (('ivb', 'ride'), ('hb_arm', 'run')):
        e_new = np.array([sw[key].get(f'{lab}_{p}', {}).get('e', 1.05) for p in PT])[d['pt']]
        delta = d[comp] * (np.exp(e_new * lr) - np.exp(1.05 * lr))
        dg = np.bincount(g, weights=delta, minlength=ng) / n
        big = n >= 100
        print(f'\n{lab}: change in season mean, inches (new minus shipped)')
        for i, p in enumerate(PT):
            m = big & (ptg == i)
            if m.sum() < 10:
                continue
            col = m & (share_c >= 0.35)
            x = dg[m]
            print(f'  {p} e {sw[key].get(f"{lab}_{p}", {}).get("e", 1.05):.2f}: league mean {x.mean():+.2f}  sd {x.std():.2f}  '
                  f'max |change| {np.abs(x).max():.2f}  | Colorado staff ({col.sum()} groups) mean {dg[col].mean() if col.any() else float("nan"):+.2f}'
                  f'  | single Coors pitch {np.mean(delta[(d["venue"]==19)&(d["pt"]==i)]):+.2f}')
