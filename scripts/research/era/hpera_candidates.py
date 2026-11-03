"""hpera_candidates.py: can hpERA forecast better? Channel-surface and prior-season candidates on the honest pools.

Same harness as hpera_honest_refit.py (honest pools, target-innings weight, held out by year, NEXT and ROS stacked).
Rows are restricted to pitchers whose alternate Loc surface exists, so every arm is scored on identical rows.

Arms
  refit        shipped channel set (control; must match hpera_honest_refit)
  ctlTab       refit with loc rebuilt from the audit's shipped table (mapping check; must be near refit)
  loc9 / loc13 / loc9K / loc13K   loc channel from the Loc+ target-audit tables at 9 in/.55, 13 in/.75, and both with K a16 b256
  noLoc        drop the loc channel
  +prior       refit + prior-season composite: sum over stuff, loc, k, izwh, xrv, gb of the final refit weight x that
               channel's z in season S-1 (0 if he has no S-1 season; S 2021 has none). hpERA reads one season today.
  +prior+loc9  both
Alternate loc values: table raw_full (NEXT) or raw_1h (ROS), z-scored on the 30+ IP pool of that season/scope the way
era_weights_final does (pitch-weighted mean, SD over pitchers). The audit's raw_1h surfaces are full-season surfaces,
which is why ctlTab is printed: it bounds what that does to the ROS rows.

Usage: python3 scripts/research/era/hpera_candidates.py
Output: console + data/_hpera_candidates.json
"""
import contextlib
import io
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hpera_honest_refit as hh

ewf = hh.ewf
hr = hh.hr
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
AUD = os.path.join(ROOT, 'data', '_loc_target_audit')
BASE = hh.BASE_CH + ['lhp']
ARMS = {'refit': BASE, 'ctlTab': [c if c != 'loc' else 'loc_ship' for c in BASE],
        'loc9': [c if c != 'loc' else 'loc_x9_z0.55' for c in BASE], 'loc13': [c if c != 'loc' else 'loc_x13_z0.75' for c in BASE],
        'loc9K': [c if c != 'loc' else 'loc_x9_z0.55_a16_b256' for c in BASE], 'loc13K': [c if c != 'loc' else 'loc_x13_z0.75_a16_b256' for c in BASE],
        'noLoc': [c for c in BASE if c != 'loc'], '+prior': BASE + ['prior'],
        '+prior+loc9': [c if c != 'loc' else 'loc_x9_z0.55' for c in BASE] + ['prior']}
SURF = {'loc_ship': 'shipped', 'loc_x9_z0.55': 'x9_z0.55', 'loc_x13_z0.75': 'x13_z0.75',
        'loc_x9_z0.55_a16_b256': 'x9_z0.55_a16_b256', 'loc_x13_z0.75_a16_b256': 'x13_z0.75_a16_b256'}
PRIOR_CH = ['stuff', 'loc', 'k', 'izwh', 'xrv', 'gb']


def name_key(s):
    return s.strip().lower()


def tab_values(S, surf, scope):
    t = pd.read_pickle(os.path.join(AUD, f'tab_{surf}_{S}.pkl'))
    col, ncol = ('raw_full', 'n_raw_full') if scope == 'full' else ('raw_1h', 'n_raw_1h')
    out = {}
    for (name, _th), v, n in zip(t.index, t[col], t[ncol]):
        if pd.notna(v) and n and n > 0:
            last, _, first = name.partition(', ')
            out.setdefault(name_key(f'{first} {last}'), []).append((float(v), float(n)))
    return {k: max(v, key=lambda x: x[1]) for k, v in out.items()}


def main():
    fw = json.load(open(os.path.join(ROOT, 'data', '_hpera_honest_refit.json')))['final']['refit']
    reps = []
    dropped = {}
    for obj in ('next', 'ros'):
        seasons = range(2021, 2026) if obj == 'next' else range(2021, 2027)
        for S in seasons:
            scope = 'full' if obj == 'next' else 'h1'
            with contextlib.redirect_stdout(io.StringIO()):
                Z = ewf.shrunk_features(S, scope); F = hr.base_features(S, scope)
                Zp = ewf.shrunk_features(S - 1, 'full') if S > 2021 else {}
            pitchers = hh.TG[str(S)]['pitchers']
            names = {p: name_key(pitchers[p].get('name', '')) for p in Z if p in pitchers}
            cnt = pd.Series(list(names.values())).value_counts()
            ty, tscope = (S + 1, 'full') if obj == 'next' else (S, 'h2')
            lg = hh.lg_era(ty, tscope)
            Tabs = {k: tab_values(S, s, scope) for k, s in SURF.items()}
            # z of each surface on the 30+ IP pool of Z (the population shrunk_features returns)
            Zs = {}
            for k, tv in Tabs.items():
                vals = {p: tv[names[p]] for p in names if names[p] in tv and cnt[names[p]] == 1}
                pool = [p for p in vals if p in Z]
                m = sum(vals[p][0] * vals[p][1] for p in pool) / sum(vals[p][1] for p in pool)
                sd = float(np.std([vals[p][0] for p in pool]))
                Zs[k] = {p: (vals[p][0] - m) / sd for p in vals}
            rows = []; miss = 0
            for p, z in Z.items():
                f = F.get(p); t = hr.line(ty, p, tscope)
                if not f or not t or t['outs'] <= 0 or f['outs'] < hh.MIN_OUTS[obj]:
                    continue
                if not all(c in z for c in hh.BASE_CH + ['bb', 'age']) or 'SIERA' not in f or 'hpERA' not in f:
                    continue
                if not all(p in Zs[k] for k in SURF):
                    miss += 1; continue
                zz = dict(z); zz['lhp'] = 1.0 if pitchers[p].get('hand') == 'L' else 0.0
                for k in SURF:
                    zz[k] = Zs[k][p]
                zp = Zp.get(p)
                zz['prior'] = sum(fw[c] * zp[c] for c in PRIOR_CH if c in zp) if zp else 0.0
                rows.append({'z': zz, 'y': 27 * t['er'] / t['outs'] - lg, 'w': t['outs'] / 3})
            dropped[f'{obj}{S}'] = (len(rows), miss)
            reps.append({'obj': obj, 'label': f'{obj} {S}', 'S': S, 'years': {S, ty}, 'rows': rows})
    print('rows kept, dropped for no alt surface:', dropped)
    chk = []
    for rp in reps:
        a = np.array([r['z']['loc'] for r in rp['rows']]); b = np.array([r['z']['loc_ship'] for r in rp['rows']])
        chk.append((rp['label'], round(float(np.corrcoef(a, b)[0, 1]), 4)))
    print('r(harness loc z, audit shipped table z) per replicate:', chk)

    def design(rows, arm):
        return np.array([[r['z'][c] for c in ARMS[arm]] for r in rows])

    def fit(train, arm):
        tot = {o: sum(r['w'] for q in train if q['obj'] == o for r in q['rows']) for o in ('next', 'ros')}
        X = np.vstack([design(q['rows'], arm) for q in train])
        y = np.array([r['y'] for q in train for r in q['rows']])
        w = np.array([r['w'] / tot[q['obj']] for q in train for r in q['rows']])
        A = np.column_stack([np.ones(len(X)), X]); sw = np.sqrt(w)
        return np.linalg.lstsq(A * sw[:, None], y * sw, rcond=None)[0]

    res = {a: {} for a in ARMS}; coef = {a: [] for a in ARMS}
    for rp in reps:
        train = [q for q in reps if not (q['years'] & rp['years'])]
        y = np.array([r['y'] for r in rp['rows']]); w = np.array([r['w'] for r in rp['rows']])
        for a in ARMS:
            b = fit(train, a); coef[a].append(b)
            p = np.column_stack([np.ones(len(y)), design(rp['rows'], a)]) @ b
            res[a][rp['label']] = float((w * (p - y) ** 2).sum() / w.sum())
    out = {}
    for obj in ('next', 'ros'):
        labs = [rp['label'] for rp in reps if rp['obj'] == obj]
        base = np.array([res['refit'][l] for l in labs])
        print(f'\n== {obj.upper()}: refit MSE ' + ' '.join(f'{x:.3f}' for x in base))
        for a in ARMS:
            m = np.array([res[a][l] for l in labs]); d = 100 * (1 - m / base)
            se = d.std(ddof=1) / np.sqrt(len(d))
            print(f'  {a:14s} mean gain {d.mean():+.2f}%  se {se:.2f}  z {d.mean()/se if se else 0:+.1f}  wins {int((m < base - 1e-12).sum())}/{len(labs)}  {np.round(d, 2).tolist()}')
            out[f'{obj}|{a}'] = {l: res[a][l] for l in labs}
    print('\nmean weights')
    for a in ARMS:
        print(f'  {a:14s}', dict(zip(['int'] + ARMS[a], np.round(np.mean(coef[a], axis=0), 3).tolist())))
    with open(os.path.join(ROOT, 'data', '_hpera_candidates.json'), 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
