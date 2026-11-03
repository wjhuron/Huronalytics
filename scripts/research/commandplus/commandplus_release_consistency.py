"""commandplus_release_consistency.py: does release-angle consistency add to walk forecasts?

The open candidate from the 2026-08-24 survey (Kirby Index family). Per pitcher-season from the Statcast caches 2021-2025:
vertical and horizontal release angle per pitch from vx0, vy0, vz0 (arctan of velocity components at y=50 ft, a fixed
reference, so this is the launch direction of the pitch, not a biomechanical angle). Within pitcher x pitch type x season, the
residual SD after regressing the angle on release_pos_x and release_pos_z (a pitcher who moves his release moves his angle on
purpose). Pitcher score = pitch-weighted mean over types with >= 50 pitches, K_rel = sqrt(mean(vSD^2 + hSD^2)).

Questions, each on pitchers with >= 500 pitches in Y (and >= 30 IP-equivalent 120 BF in Y+1), Y 2021-2024 -> Y+1 2022-2025:
  1. year-over-year persistence of K_rel vs Command+ raw miss
  2. next-season BB% from BB%(Y), + Command+ miss, + K_rel, LOYO R
  3. relation with Command+ raw miss (does it measure the same thing)
Target: next-season BB% over BF, from _era_battery (bb_pct).

Usage: python3 scripts/research/commandplus/commandplus_release_consistency.py
Output: console + data/_cmd_release_consistency.json
"""
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
YEARS = [2021, 2022, 2023, 2024, 2025]


def season_scores(y):
    c = pd.read_pickle(os.path.join(ROOT, 'data', f'_statcast{y}_cache.pkl'))
    cols = ['pitcher', 'pitch_type', 'vx0', 'vy0', 'vz0', 'release_pos_x', 'release_pos_z']
    d = c[cols].copy()
    del c
    for k in cols[2:]:
        d[k] = pd.to_numeric(d[k], errors='coerce').to_numpy(dtype='float64', na_value=np.nan)
    d['pitcher'] = pd.to_numeric(d['pitcher'], errors='coerce')
    d = d.dropna()
    d['va'] = np.degrees(np.arctan2(d['vz0'], -d['vy0']))
    d['ha'] = np.degrees(np.arctan2(d['vx0'], -d['vy0']))
    out = {}
    for (p, t), g in d.groupby(['pitcher', 'pitch_type'], observed=True):
        if len(g) < 50:
            continue
        X = np.column_stack([np.ones(len(g)), g['release_pos_x'], g['release_pos_z']])
        rv = g['va'].values - X @ np.linalg.lstsq(X, g['va'].values, rcond=None)[0]
        rh = g['ha'].values - X @ np.linalg.lstsq(X, g['ha'].values, rcond=None)[0]
        out.setdefault(int(p), []).append((len(g), float(np.mean(rv ** 2)), float(np.mean(rh ** 2))))
    res = {}
    for p, v in out.items():
        n = sum(x[0] for x in v)
        res[str(p)] = dict(n=n, vsd=float(np.sqrt(sum(x[0] * x[1] for x in v) / n)), hsd=float(np.sqrt(sum(x[0] * x[2] for x in v) / n)),
                           k=float(np.sqrt(sum(x[0] * (x[1] + x[2]) for x in v) / n)))
    return res


def main():
    K = {y: season_scores(y) for y in YEARS}
    print({y: len(K[y]) for y in K})
    Bat = json.load(open(os.path.join(ROOT, 'data', '_era_battery.json')))
    CL = json.load(open(os.path.join(ROOT, 'data', '_era_internal_cmdloc.json')))
    rows = []
    for y in YEARS[:-1]:
        for p, r in K[y].items():
            b0 = Bat[str(y)].get(p, {}).get('full'); b1 = Bat[str(y + 1)].get(p, {}).get('full'); c0 = CL[str(y)].get(p); c1 = CL[str(y + 1)].get(p)
            if not (b0 and b1 and c0 and c0.get('cmd_full') is not None) or r['n'] < 500 or b1['pa'] < 120 or b0.get('bb_pct') is None or b1.get('bb_pct') is None:
                continue
            k1 = K[y + 1].get(p)
            rows.append(dict(Y=y, p=p, k=r['k'], vsd=r['vsd'], hsd=r['hsd'], cmd=c0['cmd_full'], bb0=b0['bb_pct'], k_pct0=b0.get('k_pct'), bb1=b1['bb_pct'], w=b1['pa'],
                             k1=k1['k'] if k1 and k1['n'] >= 500 else np.nan, cmd1=c1['cmd_full'] if c1 and c1.get('cmd_full') is not None and c1.get('cmd_n_full', 0) >= 500 else np.nan))
    R = pd.DataFrame(rows)
    print('rows', len(R), R.groupby('Y').size().to_dict())
    pp = R.dropna(subset=['k1'])
    print('persistence K_rel', round(pp['k'].corr(pp['k1']), 3), 'n', len(pp))
    pc = R.dropna(subset=['cmd1'])
    print('persistence Command miss', round(pc['cmd'].corr(pc['cmd1']), 3), 'n', len(pc))
    print('r(K_rel, Command miss) same season', round(R['k'].corr(R['cmd']), 3), ' r(K_rel, BB%)', round(R['k'].corr(R['bb0']), 3), ' r(Command, BB%)', round(R['cmd'].corr(R['bb0']), 3))
    print('r with next BB%: BB%', round(R['bb0'].corr(R['bb1']), 3), 'Command', round(R['cmd'].corr(R['bb1']), 3), 'K_rel', round(R['k'].corr(R['bb1']), 3), 'vSD', round(R['vsd'].corr(R['bb1']), 3), 'hSD', round(R['hsd'].corr(R['bb1']), 3))
    arms = {'BB%': ['bb0'], 'BB%+Cmd': ['bb0', 'cmd'], 'BB%+Krel': ['bb0', 'k'], 'BB%+Cmd+Krel': ['bb0', 'cmd', 'k'], 'Cmd alone': ['cmd'], 'Cmd+Krel': ['cmd', 'k']}
    out = {}
    for name, cols in arms.items():
        mse, rr = [], []
        for y in YEARS[:-1]:
            tr, te = R[R.Y != y], R[R.Y == y]
            X = np.column_stack([np.ones(len(tr))] + [tr[c] for c in cols]); sw = np.sqrt(tr['w'].values)
            b = np.linalg.lstsq(X * sw[:, None], tr['bb1'].values * sw, rcond=None)[0]
            p = np.column_stack([np.ones(len(te))] + [te[c] for c in cols]) @ b
            mse.append(np.average((p - te['bb1']) ** 2, weights=te['w'])); rr.append(np.corrcoef(p, te['bb1'])[0, 1])
        out[name] = dict(mse=mse, r=rr)
        print(f'  {name:14s} held-out mean r {np.mean(rr):.4f}  mean MSE x1e4 {1e4*np.mean(mse):.3f}   per Y ' + ' '.join(f'{x:.3f}' for x in rr))
    base = np.array(out['BB%+Cmd']['mse'])
    for name in ('BB%+Cmd+Krel', 'BB%+Krel'):
        g = 100 * (1 - np.array(out[name]['mse']) / base)
        print(f'  {name} vs BB%+Cmd: gain {g.mean():+.2f}% se {g.std(ddof=1)/2:.2f} wins {(g>0).sum()}/4 {np.round(g,2).tolist()}')
    g = 100 * (1 - base / np.array(out['BB%']['mse'])); print(f'  BB%+Cmd vs BB%: gain {g.mean():+.2f}% se {g.std(ddof=1)/2:.2f} wins {(g>0).sum()}/4')
    with open(os.path.join(ROOT, 'data', '_cmd_release_consistency.json'), 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
