"""wx_aaa_validate.py -- the MLB-fitted joint model, applied unchanged to Triple-A.

RESEARCH ONLY. Nothing here is fitted on Triple-A. Coefficients come from
data/_weather_audit/joint_split_full.json (six MLB seasons). Wind and park terms
are off (no Triple-A wind pull, and the park offsets are MLB parks). The test:
adjusted movement in the five parks at 3,000 ft or more minus the same pitcher
under 1,500 ft, by pitch type (the tag is a label for the table only).
"""
import os, sys, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wx_exponent_sweep import OUT, RHO0, PT, moist
from wx_cell_shift import prep as prep_cs, gap_tables
import wx_joint_split as J


def load_aaa(yr, obs):
    z = np.load(os.path.join(OUT, f'frame_aaa_{yr}.npz')); d = {k: z[k] for k in z.files}
    ok = np.isfinite(d['rho']) & np.isfinite(d['ivb']) & np.isfinite(d['hb_arm']) & (d['pt'] < 8)
    d = {k: v[ok] for k, v in d.items()}
    n = len(d['pk']); p = np.full(n, np.nan); t = np.full(n, np.nan); rh = np.full(n, np.nan)
    for pk in np.unique(d['pk']):
        o = obs.get(str(int(pk)))
        if o:
            m = d['pk'] == pk; p[m], t[m], rh[m] = o['p_hpa'], o['tempF'], o['rh']
    cl = d['closed']
    d['obs_t'] = t
    d['rho_w50'] = moist(p, np.where(cl, 72.0, 0.5 * d['temp'] + 0.5 * t), np.where(cl, 50.0, rh))
    d['rho_model'] = d['rho']
    keep = np.isfinite(d['rho_w50'])
    return {k: v[keep] for k, v in d.items()}


if __name__ == '__main__':
    obs = json.load(open(os.path.join(OUT, 'game_obs_aaa.json')))
    F = json.load(open(os.path.join(OUT, 'joint_split_full.json'))); K = F['K']
    ALL = {}
    for yr in (2023, 2024, 2025, 2026):
        d = prep_cs(load_aaa(yr, obs), 'w50')
        ZZ, lnP, lnT, _ = J.build(d, None, {}, park=False)
        hi = d['elev'] >= 3000; lo = d['elev'] < 1500
        keep = hi | lo
        res = {}
        for comp, lab in (('hb_arm', 'run'), ('ivb', 'ride')):
            fit = F['fit'][lab]; b = np.array(fit['b'])[:ZZ[lab].shape[1]].copy()
            b[2 * K] = 0.0; b[2 * K + 1] = 0.0                       # wind off
            adj_new = (d[comp] - ZZ[lab] @ b) / np.exp(fit['eP'] * lnP + fit['eT'] * lnT)
            lr_model = np.log(d['rho_model'] / RHO0)
            for name, adj in (('ship', d[comp] / np.exp(1.05 * lr_model)), ('exp120', d[comp] / np.exp(1.20 * lr_model)),
                              ('joint', adj_new)):
                dd = {k: v[keep] for k, v in d.items() if isinstance(v, np.ndarray) and len(v) == len(keep)}
                dd['gpt'] = np.unique(dd['gpt'], return_inverse=True)[1]
                for p, (v, k) in gap_tables(dd, adj[keep], hi[keep]).items():
                    res.setdefault(name, {})[f'{lab}_{p}'] = v
                    ALL.setdefault(name, {}).setdefault(f'{lab}_{p}', []).append(v)
        print(f'AAA {yr}: {len(d["g"])} pitches; high-park share {hi.mean():.3f}')
        del d
    print('\nTRIPLE-A, high parks minus low parks, adjusted, inches (mean of the seasons, sd, seasons)')
    for key in sorted(ALL['ship']):
        if len(ALL['ship'][key]) < 3:
            continue
        print(f'  {key:8s} ' + ' | '.join(f'{n} {np.mean(ALL[n][key]):+.2f} ({np.std(ALL[n][key]):.2f})' for n in ('ship', 'exp120', 'joint'))
              + f'   n {len(ALL["ship"][key])}')
    rms = lambda n: np.sqrt(np.mean([np.mean(v) ** 2 for v in ALL[n].values() if len(v) >= 3]))
    print('  RMS      ' + ' | '.join(f'{n} {rms(n):.2f}' for n in ('ship', 'exp120', 'joint')))
    json.dump(ALL, open(os.path.join(OUT, 'aaa_validate.json'), 'w'), indent=1)
