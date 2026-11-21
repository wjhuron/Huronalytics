#!/usr/bin/env python3
"""hpera_nm1_refit.py -- hpERA weights on Stuff+ v19 (the neutral-movement columns).

Stuff+ v19 is the v18 design on new movement inputs (pipeline/neutral_move.py, model
nm1). hpERA's stuff channel reads that grade, so its weights are refit on it.

Step 1 (build): two new keys in data/_era_new_inputs.json, from the gate frames that
now hold the nm1 columns:
    stuff_nm1_full   season Y from the gate pair model fit on neither Y nor Y+1
                     (the installed SHIPPED aggregates, 2021-2025)
    stuff_nm1_h1     pitches on or before the All-Star date, from a model fit on the
                     other five seasons (2021-2026)
Step 2 (refit): the harness of hpera_location_refit.py (NEXT season, 5 replicates; REST
of season, 6; ERA relative to league; innings-weighted; held out by YEAR), same rows for
both arms. The loc channel is the shipped input in both (`loc_far`, unshrunk).
    old   stuff_hand  (v18, the input the live weights were fit on; the reference)
    new   stuff_nm1   (v19)

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/era/hpera_nm1_refit.py
"""
import contextlib
import gc
import io
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hpera_new_inputs_build as NB  # noqa: E402

G = NB.G
PRED = os.path.join(NB.ROOT, 'data', '_era_new_inputs_pred_nm1')
OUT = os.path.join(NB.ROOT, 'data', '_hpera_nm1_refit.json')
LOC = ('loc_far', 'n_locfar')


def build_inputs():
    res = json.load(open(NB.OUT))
    if any('stuff_nm1_h1' in r for r in res.get('2026', {}).values()):
        print('stuff_nm1 inputs already present')
        return
    os.makedirs(PRED, exist_ok=True)
    frames = {y: G.load_frame(y) for y in NB.YEARS}
    G.set_arm_side_sign(list(frames.values()))
    feats = G.variant_feats({})
    for Y in NB.YEARS:
        fn = os.path.join(PRED, f'nm1_{Y}.npy')
        if not os.path.exists(fn):
            train = [y for y in NB.YEARS if y != Y]
            slopes = G.fit_vaa_slopes([frames[y] for y in train])
            P = {y: G.prepare(frames[y], slopes, 'true') for y in train + [Y]}
            Xtr = pd.concat([G.design(P[y], {}, feats) for y in train], ignore_index=True)
            ytr = np.concatenate([P[y]['target_xrv'].values for y in train])
            pred = G.fit_predict(Xtr, ytr, G.design(P[Y], {}, feats), {}, 0)
            np.save(fn, (-pred).astype('float32'))
            print(f'  fit held-out {Y}', flush=True)
            del Xtr, P
            gc.collect()
        asg, nm = NB.TARGETS[str(Y)]['asg'], NB.name_map(Y)
        d = frames[Y][['pitcher', 'date']].copy()
        d['s'] = np.load(fn)
        g = d[(d['date'].astype(str).str[:10] <= asg).values].groupby('pitcher')['s'].agg(['mean', 'size'])
        g = g[g['size'] >= NB.MIN_N]
        NB.put(res, Y, {n: {'stuff_nm1_h1': float(r['mean'])} for n, r in g.iterrows()}, nm)
    for Y in NB.YEARS[:-1]:
        nm = NB.name_map(Y)
        s = pd.read_pickle(G.agg_path('SHIPPED', Y, 0))['pitch'][0]
        d = pd.DataFrame({'pitcher': frames[Y]['pitcher'].values, 's': s})
        g = d.groupby('pitcher')['s'].agg(['mean', 'size'])
        g = g[g['size'] >= NB.MIN_N]
        NB.put(res, Y, {n: {'stuff_nm1_full': float(r['mean'])} for n, r in g.iterrows()}, nm)
    del frames
    gc.collect()
    tmp = NB.OUT + '.tmp'
    json.dump(res, open(tmp, 'w'))
    os.replace(tmp, NB.OUT)
    print('wrote stuff_nm1 keys to', NB.OUT)


def refit():
    import hpera_new_inputs_refit as NR
    HR, hr, ewf, REST = NR.HR, NR.hr, NR.ewf, NR.REST
    NEW = json.load(open(NB.OUT))

    def patch(stuff_key):
        st, cl = {}, {}
        for y, pit in NEW.items():
            for pid, r in pit.items():
                s, c = {}, {}
                for sc in ('full', 'h1'):
                    if f'{stuff_key}_{sc}' in r and f'n_stuff_{sc}' in r:
                        s[f'stuff_{sc}'], s[f'n_{sc}'] = r[f'{stuff_key}_{sc}'], r[f'n_stuff_{sc}']
                    if f'{LOC[0]}_{sc}' in r:
                        c[f'loc_{sc}'], c[f'loc_n_{sc}'] = r[f'{LOC[0]}_{sc}'], r[f'{LOC[1]}_{sc}']
                st.setdefault(y, {})[pid] = s
                cl.setdefault(y, {})[pid] = c
        ewf.STUFF, ewf.CMDLOC = st, cl

    n0_keep = ewf.N0['loc']
    ewf.N0['loc'] = 0.0
    reps = []
    try:
        for obj in ('next', 'ros'):
            for S in (range(2021, 2026) if obj == 'next' else range(2021, 2027)):
                scope = 'full' if obj == 'next' else 'h1'
                have = {pid for pid, r in NEW.get(str(S), {}).items()
                        if all(f'{k}_{scope}' in r for k in ('stuff_hand', 'stuff_nm1', LOC[0]))}
                Z = {}
                for arm, key in (('old', 'stuff_hand'), ('new', 'stuff_nm1')):
                    patch(key)
                    with contextlib.redirect_stdout(io.StringIO()):
                        Z[arm] = ewf.shrunk_features(S, scope)
                        if arm == 'old':
                            F = hr.base_features(S, scope)
                ty, tscope = (S + 1, 'full') if obj == 'next' else (S, 'h2')
                lg = HR.lg_era(ty, tscope)
                rows = []
                for p, z in Z['old'].items():
                    f, t = F.get(p), hr.line(ty, p, tscope)
                    if p not in have or not f or not t or t['outs'] <= 0 or f['outs'] < HR.MIN_OUTS[obj]:
                        continue
                    zn = Z['new'].get(p, {})
                    if not all(c in z for c in ['stuff', 'loc'] + REST) or 'stuff' not in zn or 'hpERA' not in f or 'SIERA' not in f:
                        continue
                    zz = {c: z[c] for c in REST}
                    zz['loc'] = z['loc']; zz['stuff_old'] = z['stuff']; zz['stuff_new'] = zn['stuff']
                    rows.append({'z': zz, 'ship': f['hpERA'], 'siera': f['SIERA'],
                                 'y': 27 * t['er'] / t['outs'] - lg, 'w': t['outs'] / 3})
                reps.append({'obj': obj, 'label': f"{obj} {S % 100}" + ('' if obj == 'ros' else f'->{(S + 1) % 100}'),
                             'years': {S, ty}, 'rows': rows})
    finally:
        ewf.N0['loc'] = n0_keep
    cands = {'old': ['stuff_old', 'loc'] + REST, 'new': ['stuff_new', 'loc'] + REST}
    HR.CANDS.clear(); HR.CANDS.update(cands)
    print('replicates: ' + ', '.join(f"{rp['label']} n {len(rp['rows'])}" for rp in reps))
    print('r(old stuff z, new stuff z) per replicate: ' + ' '.join(
        f"{np.corrcoef([r['z']['stuff_old'] for r in rp['rows']], [r['z']['stuff_new'] for r in rp['rows']])[0, 1]:.3f}" for rp in reps))
    res = HR.evaluate(reps, ['ship', 'SIERA', 'old', 'new'])
    out = {}
    for obj in ('next', 'ros'):
        labels = [rp['label'] for rp in reps if rp['obj'] == obj]
        b = np.array([res['old'][l][0] for l in labels])
        print(f'\n== {obj.upper()}: innings-weighted MSE of ERA relative to league, held out by year')
        for a in ('ship', 'SIERA', 'old', 'new'):
            m = np.array([res[a][l][0] for l in labels]); d = m - b
            z = d.mean() / (d.std(ddof=1) / np.sqrt(len(d))) if a != 'old' and d.std() > 0 else 0.0
            out[f'{obj}|{a}'] = dict(mse=float(m.mean()), pct_vs_old=float(100 * d.mean() / b.mean()), wins=int((d < 0).sum()), n=len(d), z=float(z))
            print(f'   {a:<6s} MSE {m.mean():.4f}  vs old {100 * d.mean() / b.mean():+.3f}%  better in {int((d < 0).sum())}/{len(d)}  z {z:+.1f}   '
                  + ' '.join(f'{x:.3f}' for x in m))
    final = {a: dict(zip(['intercept'] + cands[a], [float(x) for x in HR.fit(reps, a)])) for a in cands}
    print('\nweights fit on every replicate (ERA per z unit):')
    for a, dd in final.items():
        print(f'   {a:<4s} ' + ' '.join(f'{k.replace("stuff_old", "stuff").replace("stuff_new", "stuff")} {v:+.3f}' for k, v in dd.items() if k != 'intercept'))
    out['final'] = final
    tmp = OUT + '.tmp'
    json.dump(out, open(tmp, 'w'), indent=1)
    os.replace(tmp, OUT)


if __name__ == '__main__':
    build_inputs()
    refit()
