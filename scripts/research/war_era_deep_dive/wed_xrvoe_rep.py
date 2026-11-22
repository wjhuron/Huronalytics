"""wed_xrvoe_rep.py - the xRVOE shrinkage constant on six independent seasons.

wed_xrvoe.py measured XRVOE_N0 on 2026 alone, from the real score-only path: about 1,800 pitches at the pitcher
level and 900 at the pitch type, against the shipped 275. This replicates it on 2021-2025 and repeats 2026 as the
check. Per season Y: the Stuff+ model of the gate's SHIPPED design is fitted on the other five seasons and
predicts Y (stuff_gate_v2: frames, VAA slopes, prepare, design, fit_predict); the location term is the frame's
l_loc; the expectation is the per-group stack of compute_xrvoe (target ~ 1 + stuff + loc, groups with 5,000+
pitches); the residual is target minus expectation.
LIMITS, stated: l_loc is the Loc+ expected value of the 2026-09-08 frames (the kernel before 2026-11-18), and the
Stuff+ fit is leave-one-SEASON-out, not production's pitcher folds. The 2026 row is the check on both: it must
land near the released-model measurement before the other seasons are read.
PYTHONHASHSEED=0 .venv/bin/python scripts/research/war_era_deep_dive/wed_xrvoe_rep.py"""
import sys, os, gc, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'stuff'))
import stuff_gate_v2 as G
import pipeline.locplus as LOC
OUT = os.path.join(ROOT, 'data', '_wed')


def residual_frame(Y, frames):
    out = os.path.join(OUT, f'xrvoe_rep_{Y}.pkl')
    if os.path.exists(out):
        return pd.read_pickle(out)
    train = [y for y in G.SEASONS if y != Y]
    slopes = G.fit_vaa_slopes([frames[y] for y in train])
    spec = {}; feats = G.variant_feats(spec)
    Xtr = pd.concat([G.design(G.prepare(frames[y], slopes, 'true'), spec, feats) for y in train], ignore_index=True)
    ytr = np.concatenate([frames[y]['target_xrv'].values for y in train])
    dY = G.prepare(frames[Y], slopes, 'true'); XY = G.design(dY, spec, feats)
    assert len(Xtr) == len(ytr) and len(XY) == len(dY)
    pred = G.fit_predict(Xtr, ytr, XY, spec, 0); del Xtr, ytr, XY; gc.collect()
    d = pd.DataFrame({'pitcher': dY['pitcher'].values, 'team': dY['team'].values, 'pitch_type': dY['pitch_type'].values, 'date': dY['date'].values,
                      'target': dY['target_xrv'].values.astype(float), 'stuff': pred.astype(float), 'loc': dY['l_loc'].values.astype(float)})
    d = d[np.isfinite(d.target) & np.isfinite(d.stuff) & np.isfinite(d['loc'])].copy()
    d['grp'] = d['pitch_type'].map(LOC.group_of_code)

    def stack(s):
        A = np.column_stack([np.ones(len(s)), s['stuff'].values, s['loc'].values]); return np.linalg.lstsq(A, s['target'].values, rcond=None)[0]
    bg = stack(d); d['expect'] = np.nan
    for g, s in d.groupby('grp'):
        b = stack(s) if len(s) >= 5000 else bg
        d.loc[s.index, 'expect'] = np.column_stack([np.ones(len(s)), s['stuff'].values, s['loc'].values]) @ b
    d['resid'] = d['target'] - d['expect']
    r2 = 1 - float(((d.target - d.expect) ** 2).sum() / ((d.target - d.target.mean()) ** 2).sum())
    print(f"{Y}: pitches {len(d)}, expectation R2 {r2:.4f}, per-pitch residual SD {d.resid.std():.4f}", flush=True)
    d[['pitcher', 'team', 'pitch_type', 'date', 'resid']].to_pickle(out)
    return d


def measure(d, keys, grid):
    idx = {k: v.values for k, v in d.groupby(keys)['resid']}; res = {}
    for n in grid:
        rs = []
        for seed in range(5):
            rng = np.random.default_rng(seed); a, b = [], []
            for v in idx.values():
                if len(v) >= 2 * n:
                    p = rng.permutation(len(v)); a.append(v[p[:n]].mean()); b.append(v[p[n:2 * n]].mean())
            if len(a) >= 30:
                rs.append(np.corrcoef(a, b)[0, 1])
        if rs:
            r = float(np.mean(rs)); res[n] = (r, n * (1 - r) / r if r > 0 else float('inf'), len(a))
    u = d.groupby(keys)['resid'].agg(['mean', 'size', 'var']); u = u[u['size'] >= 300]
    noise = (u['var'] / u['size']).mean(); tv = u['mean'].var() - noise
    return res, (float(d.resid.var() / tv) if tv > 0 else float('inf')), float(100 * np.sqrt(max(tv, 0))), float(100 * u['mean'].std())


def main():
    frames = {y: G.load_frame(y) for y in G.SEASONS}; G.set_arm_side_sign(list(frames.values()))
    out = {}
    done = []
    for Y in (2026, 2021, 2022, 2023, 2024, 2025):
        # A frame with no location term cannot give a residual (the 2026 frame installed with the
        # neutral inputs on 2026-11-21 has an empty l_loc until build-loc runs): say so, do not crash.
        if not np.isfinite(frames[Y]['l_loc'].values.astype(float)).any():
            print(f"{Y}: SKIPPED, the frame has no l_loc; measure this season with wed_xrvoe.py (the production path)", flush=True)
            continue
        done.append(Y)
        d = residual_frame(Y, frames)
        for tag, keys, grid in (('pitcher', ['pitcher', 'team'], (300, 500, 800)), ('pitch type', ['pitcher', 'team', 'pitch_type'], (150, 300))):
            res, n0v, tsd, osd = measure(d, keys, grid)
            print(f"   {Y} {tag}: " + "  ".join(f"n {n}: r {r:.3f} N0 {k:.0f} ({u})" for n, (r, k, u) in res.items()) + f" | variance method N0 {n0v:.0f} (true SD {tsd:.3f}, observed {osd:.3f} runs/100)", flush=True)
            out[f'{Y} {tag}'] = dict(samples={n: v[1] for n, v in res.items()}, variance=n0v, true_sd=tsd)
        json.dump(out, open(os.path.join(OUT, 'res_xrvoe_rep.json'), 'w'), indent=1, default=float)
    for tag in ('pitcher', 'pitch type'):
        v = [out[f'{Y} {tag}']['variance'] for Y in done]; s = [np.mean(list(out[f'{Y} {tag}']['samples'].values())) for Y in done]
        print(f"\n{tag}: variance-method N0 by season {np.round(v).astype(int).tolist()} median {np.median(v):.0f}, mean {np.mean(v):.0f} (SE {np.std(v, ddof=1)/np.sqrt(len(v)):.0f}) | sample-method mean by season {np.round(s).astype(int).tolist()} median {np.median(s):.0f}")


if __name__ == '__main__':
    main()
