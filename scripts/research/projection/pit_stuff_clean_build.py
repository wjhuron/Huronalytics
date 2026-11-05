"""pit_stuff_clean_build.py: Stuff+ history for the pitcher backtest with the TARGET season out of every fit (2026-11-05). Research only.

data/_era_internal_stuff.json scores season Y with a model fit on the other 2021-2025 seasons. In a projection backtest for target T, that model has seen T's pitches and outcomes whenever T is one of them,
so the Stuff+ channel carries information from the target. Production never has this: the 2027 model never saw 2027. Here, for each T in 2022-2026 and each history season Y in T-3..T-1 (from 2021),
the model is fit on 2021-2026 less Y and less T, the SHIPPED gate features, seed 0. Writes raw 's' and atom 's_r' by pitcher.
Usage: PYTHONHASHSEED=0 python3 scripts/research/projection/pit_stuff_clean_build.py
Output: data/_proj/_stuff_clean.json {T: {Y: {pid: {s, s_r, n}}}}
"""
import gc, json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'stuff')); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'era'))
import stuff_gate_v2 as G
import era_stuff_loso_v2 as E
OUT = os.path.join(ROOT, 'data', '_proj', '_stuff_clean.json')
ALL = (2021, 2022, 2023, 2024, 2025, 2026)
res = json.load(open(OUT)) if os.path.exists(OUT) else {}
frames = {y: G.load_frame(y) for y in ALL}
G.set_arm_side_sign(list(frames.values()))
feats = G.variant_feats({})
print('feats', len(feats), flush=True)
for T in (2022, 2023, 2024, 2025, 2026):
    for Y in range(max(2021, T - 3), T):
        if str(Y) in res.get(str(T), {}):
            continue
        train = [y for y in ALL if y not in (Y, T)]
        slopes = G.fit_vaa_slopes([frames[y] for y in train])
        P = {y: G.prepare(frames[y], slopes, 'true') for y in train + [Y]}
        Xtr = pd.concat([G.design(P[y], {}, feats) for y in train], ignore_index=True)
        ytr = np.concatenate([P[y]['target_xrv'].values for y in train]); keep = np.isfinite(ytr)
        dY = P[Y]; pred = G.fit_predict(Xtr[keep], ytr[keep], G.design(dY, {}, feats), {}, 0)
        dY = dY.assign(stuff=-pred.astype('float32'))
        dY = dY.assign(atom=G.atoms(dY, G.anchors_for(dY)))
        nm = E.name_map(Y); rec = {}
        for name, g in dY.groupby('pitcher'):
            pid = nm.get(str(name).lower())
            if pid is not None and len(g) >= E.MIN_N:
                rec[str(pid)] = dict(s=float(g['stuff'].mean()), s_r=float(g['atom'].mean()), n=int(len(g)))
        res.setdefault(str(T), {})[str(Y)] = rec
        tmp = OUT + '.tmp'; json.dump(res, open(tmp, 'w')); os.replace(tmp, OUT)
        print(f'T {T} Y {Y} train {train}: {len(rec)} pitchers, rows {int(keep.sum())}', flush=True)
        del P, Xtr, ytr, dY, pred; gc.collect()
print('done', flush=True)
