"""hpera_honest_refit.py: refit hpERA to forecast ERA year to year AND within season, on honest pools.

hpera_recheck.py (2026-10-07) showed the shipped hpERA beats SIERA only on pools gated on the TARGET
period's innings (>= 60 IP in base and target), which select on the outcome. On honest pools (every
arm with >= 1 out in the target, innings-weighted) it trails SIERA year to year (0/5) and ties it within
season. Wally (2026-10-07): hpERA must be predictive year to year as well as within season.

Objectives, both on honest pools, target = ERA in the target period minus that period's league ERA,
weighted by target innings:
  NEXT  season B (>= 30 IP, the full-season z pool) -> B + 1, B 2021-2025
  ROS   first half of S (>= 15 IP, the h1 z pool) -> second half of S, S 2021-2026
Held out by YEAR: to score year Y, every replicate touching Y (as base or target) leaves the fit, so the
two objectives cannot leak into each other. Weights are fit on the stacked training replicates with each
objective's rows rescaled to equal total weight (the two count the same).

Candidates (fixed before any result was seen):
  ship        shipped W_PH + W_LHP, a fixed formula (in-sample for these seasons: an upper bound)
  SIERA       the pipeline's SIERA
  refit       the shipped channel set (Stuff+, Loc+, K%, in-zone whiff, xRV, GB%, start share, park, hand)
  refit+bb    + BB% (SIERA's walk term, absent from hpERA)
  refit+bb+age  + age
ship and SIERA get the same held-out linear calibration (a + b x) as the refits get weights, so every
arm is scored on the same footing. Score: innings-weighted MSE per held-out replicate, and r.
Decision rule: a candidate replaces the shipped weights only if it beats BOTH ship and SIERA in most
held-out replicates of BOTH objectives.

Usage: python3 scripts/research/era/hpera_honest_refit.py
Output: console + data/_hpera_honest_refit.json (incl. final weights fit on every replicate)
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hpera_recheck as hr  # noqa: E402

ewf = hr.ewf
TG = hr.TG
BASE_CH = ['stuff', 'loc', 'k', 'izwh', 'xrv', 'gb', 'gs_share', 'park']
CANDS = {'refit': BASE_CH + ['lhp'], 'refit+bb': BASE_CH + ['bb', 'lhp'], 'refit+bb+age': BASE_CH + ['bb', 'age', 'lhp']}
MIN_OUTS = {'next': 90, 'ros': 45}


def lg_era(year, scope):
    v = [hr.line(year, p, scope) for p in TG[str(year)]['pitchers']]
    v = [x for x in v if x and x['outs'] > 0]
    return sum(x['er'] for x in v) * 27 / sum(x['outs'] for x in v)


def build():
    """replicates: list of dicts {obj, years, rows: [{z: {...}, ship, siera, y, w}]}"""
    import contextlib
    import io
    reps = []
    for obj in ('next', 'ros'):
        seasons = range(2021, 2026) if obj == 'next' else range(2021, 2027)
        for S in seasons:
            scope = 'full' if obj == 'next' else 'h1'
            with contextlib.redirect_stdout(io.StringIO()):
                Z = ewf.shrunk_features(S, scope)
                F = hr.base_features(S, scope)
            ty, tscope = (S + 1, 'full') if obj == 'next' else (S, 'h2')
            lg = lg_era(ty, tscope)
            rows = []
            for p, z in Z.items():
                f = F.get(p)
                t = hr.line(ty, p, tscope)
                if not f or not t or t['outs'] <= 0 or f['outs'] < MIN_OUTS[obj]:
                    continue
                if not all(c in z for c in BASE_CH + ['bb', 'age']) or 'SIERA' not in f or 'hpERA' not in f:
                    continue
                zz = dict(z); zz['lhp'] = 1.0 if TG[str(S)]['pitchers'][p].get('hand') == 'L' else 0.0
                bl = hr.line(S, p, scope)
                rows.append({'z': zz, 'ship': f['hpERA'], 'siera': f['SIERA'],
                             'y': 27 * t['er'] / t['outs'] - lg, 'w': t['outs'] / 3,
                             'b_ip': f['outs'] / 3, 'b_gs': (bl['gs'] / bl['g']) if bl.get('g') else 0.0})
            reps.append({'obj': obj, 'label': f"{obj} {S % 100}" + ('' if obj == 'ros' else f'->{(S + 1) % 100}'),
                         'years': {S, ty}, 'rows': rows})
    return reps


def design(rows, arm):
    if arm == 'ship':
        return np.array([[r['ship']] for r in rows])
    if arm == 'SIERA':
        return np.array([[r['siera']] for r in rows])
    return np.array([[r['z'][c] for c in CANDS[arm]] for r in rows])


def fit(reps, arm, wfun=lambda ip: ip):
    """weighted OLS on stacked replicates, each objective rescaled to equal total weight. wfun maps
    target innings to the FIT weight (scoring stays innings-weighted); the default is innings."""
    tot = {o: sum(sum(wfun(r['w']) for r in rp['rows']) for rp in reps if rp['obj'] == o) for o in ('next', 'ros')}
    X, y, w = [], [], []
    for rp in reps:
        X.append(design(rp['rows'], arm)); y.extend(r['y'] for r in rp['rows'])
        w.extend(wfun(r['w']) / tot[rp['obj']] for r in rp['rows'])
    X = np.vstack(X); y = np.array(y); w = np.array(w)
    A = np.column_stack([np.ones(len(X)), X]); sw = np.sqrt(w)
    beta, *_ = np.linalg.lstsq(A * sw[:, None], y * sw, rcond=None)
    return beta


def evaluate(reps, arms):
    res = {a: {} for a in arms}
    for rp in reps:
        Y = rp['years']
        train = [q for q in reps if not (q['years'] & Y)]
        y = np.array([r['y'] for r in rp['rows']]); w = np.array([r['w'] for r in rp['rows']])
        for a in arms:
            b = fit(train, a)
            p = np.column_stack([np.ones(len(rp['rows'])), design(rp['rows'], a)]) @ b
            mse = float((w * (p - y) ** 2).sum() / w.sum())
            mx, my = np.average(p, weights=w), np.average(y, weights=w)
            r = np.average((p - mx) * (y - my), weights=w) / math.sqrt(np.average((p - mx) ** 2, weights=w) * np.average((y - my) ** 2, weights=w))
            res[a][rp['label']] = (mse, float(r), len(train))
    return res


def main():
    reps = build()
    for rp in reps:
        print(f"{rp['label']:12s} n {len(rp['rows']):4d}")
    arms = ['ship', 'SIERA'] + list(CANDS)
    res = evaluate(reps, arms)
    out = {}
    for obj in ('next', 'ros'):
        labels = [rp['label'] for rp in reps if rp['obj'] == obj]
        print(f'\n== {obj.upper()}: innings-weighted MSE of target ERA (relative to league), held out by year; r in brackets')
        for a in arms:
            mses = [res[a][l][0] for l in labels]; rs = [res[a][l][1] for l in labels]
            line = f'   {a:13s} MSE {np.mean(mses):.3f} [r {np.mean(rs):+.3f}]  ' + ' '.join(f'{res[a][l][0]:.3f}' for l in labels)
            if a not in ('ship', 'SIERA'):
                ws = sum(res[a][l][0] < res['SIERA'][l][0] for l in labels)
                wh = sum(res[a][l][0] < res['ship'][l][0] for l in labels)
                line += f'   beats SIERA {ws}/{len(labels)}, beats ship {wh}/{len(labels)}'
            elif a == 'ship':
                line += f'   beats SIERA {sum(res[a][l][0] < res["SIERA"][l][0] for l in labels)}/{len(labels)}'
            print(line)
            out[f'{obj}|{a}'] = {l: res[a][l] for l in labels}
        print(f'   training replicates per held-out year: {[res["refit"][l][2] for l in labels]}')
    final = {}
    for a in CANDS:
        b = fit(reps, a)
        final[a] = dict(zip(['intercept'] + CANDS[a], [float(x) for x in b]))
    print('\nfinal weights, fit on every replicate (ERA per z unit; lhp per left-hander):')
    print('   shipped   ' + ' '.join(f'{k} {v:+.3f}' for k, v in hr.W_PH.items()) + f' lhp {hr.W_LHP:+.3f}')
    for a, d in final.items():
        print(f'   {a:13s} ' + ' '.join(f'{k} {v:+.3f}' for k, v in d.items() if k != 'intercept'))
    out['final'] = final
    with open(os.path.join(hr.ROOT, 'data', '_hpera_honest_refit.json'), 'w') as f:
        json.dump(out, f, indent=1, default=float)


if __name__ == '__main__':
    main()
