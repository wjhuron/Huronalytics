#!/usr/bin/env python3
"""stuff_pertype_v2_regate.py — re-gate the 2026-08-14 per-type candidates on
gate v2, with a per-type validity check.

Why: the twelve per-type rejections of the 08-14 atlas
(memory/project_stuffplus_pertype_atlas) ran on the v1 gate, which scored a
double-adjusted VAA and a within-season objective (CLAUDE.md failure log).
They were never re-run on v2. The sweeper validity gap (ST next-season r .11
vs .28-.42, memory/project_stuff_sweeper_validity_2026_09) makes the
breaking-ball candidates worth a second look: breaking-gated nHAA carried an
ST atlas signal of 4.0 and failed only the v1 gate.

The candidate list is RECONSTRUCTED from the memory note (the 08-14 results
JSON and report are gone). SPIN_MASK_BRK stands in for "spin mask wide",
whose exact type list was not recorded.

Decision rule, fixed before the run (said to Wally first). A candidate
ADVANCES if (a) gate nxt_r raw or rend z_comb >= 2 with within-hand and
within-role z > -1, or (b) nxt_r z_comb > -1 on raw and rend AND its target
type's per-type validity gains z >= 2 in >= 4/5 pairs AND no type loses at
z <= -2. Advancing candidates get two more seeds before any recommendation.
Twelve candidates x ~8 types: one z >= 2 per-type by chance is expected.

Gate v2 protocol, seed 0: aggregates and results.json exactly as
`stuff_gate_v2.py run` writes them (pooled z, within-hand, within-role via
`stuff_gate_v2.py summary`). haa_n (nHAA) = hand-mirrored HAA residualized on
hand-mirrored PlateX within pitcher, per type, slopes fit on each pair's
TRAINING seasons (stuff_pertype_atlas.fit_haa_slopes / apply_haa_n, copied:
that module's imports are stale). kin_eff is 85% filled in the 2026 frame
(sidecar lag), a training season for four pairs.

Per-type validity: rendered unit grade Y vs unit xRV Y+1, units >= 150 both
seasons, paired pitcher bootstrap vs SHIPPED s0, per pair.

Output: data/_pertype_v2_regate.json. Run from the repo root.
`--followup KIN_FB` fits seeds 1 and 2 for advancing candidates and adds
the per-type deltas by seed to the same file.
"""
import gc
import json
import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
import stuff_gate_v2 as G                               # noqa: E402

OUT = os.path.join(ROOT, 'data', '_pertype_v2_regate.json')
BRK = ['SL', 'ST', 'CU', 'KC', 'SV']
VARIANTS = {
    'NHAA_ALL':      {'add': ['haa_n']},
    'NHAA_BRK':      {'add_typed': {'haa_n': BRK}},
    'KIN_FB':        {'add_typed': {'kin_eff': ['FF', 'SI', 'FC']}},
    'KIN_CU':        {'add_typed': {'kin_eff': ['CU', 'KC']}},
    'KIN_SI':        {'add_typed': {'kin_eff': ['SI']}},
    'KIN_FC':        {'add_typed': {'kin_eff': ['FC']}},
    'SPINEFF_CU':    {'add_typed': {'spin_eff': ['CU', 'KC']}},
    'AXDEV_SL':      {'add_typed': {'axis_dev': ['SL']}},
    'VD_MASK_BRK':   {'mask': {'velo_diff': ['FF', 'SI'] + BRK}},
    'SPIN_MASK_ST':  {'mask': {'spin_rate': ['ST']}},
    'SPIN_MASK_BRK': {'mask': {'spin_rate': BRK}},
    'NO_EXT':        {'drop': ['extension']},
}
TARGET_TYPES = {'NHAA_ALL': ['ST', 'SL', 'CU'], 'NHAA_BRK': ['ST', 'SL', 'CU'],
                'KIN_FB': ['FF', 'SI', 'FC'], 'KIN_CU': ['CU'], 'KIN_SI': ['SI'],
                'KIN_FC': ['FC'], 'SPINEFF_CU': ['CU'], 'AXDEV_SL': ['SL'],
                'VD_MASK_BRK': ['SL', 'ST', 'CU'], 'SPIN_MASK_ST': ['ST'],
                'SPIN_MASK_BRK': ['SL', 'ST', 'CU'], 'NO_EXT': []}
TYPES = ['FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS']
SEED = 0
MIN_U = 150
BOOT_B = 1000


def fit_haa_slopes(dfs, min_n=2000):
    pool = pd.concat([d[['pitch_type', 'pitcher', 'throws', 'haa_meas', 'plate_x']]
                      for d in dfs], ignore_index=True).dropna()
    s = np.where(pool['throws'] == 'R', 1.0, -1.0)
    pool = pool.assign(hm=pool['haa_meas'] * s, pm=pool['plate_x'] * s)
    out = {}
    for pt, sub in pool.groupby('pitch_type'):
        if len(sub) < min_n:
            continue
        g = sub.groupby('pitcher')
        hm_d = (sub['hm'] - g['hm'].transform('mean')).values
        pm_d = (sub['pm'] - g['pm'].transform('mean')).values
        var = float(np.var(pm_d))
        if var <= 0:
            continue
        out[pt] = (float(np.mean(hm_d * pm_d) / var), float(sub['pm'].mean()))
    return out


def apply_haa_n(d, slopes):
    s = np.where(d['throws'] == 'R', 1.0, -1.0)
    hm = (d['haa_meas'] * s).values
    pm = (d['plate_x'] * s).values
    out = np.full(len(d), np.nan)
    for pt, (sl, pbar) in slopes.items():
        m = (d['pitch_type'] == pt).values
        out[m] = (hm - sl * (pm - pbar))[m]
    d['haa_n'] = out.astype('float32')
    return d


def run_fits(names=None, seed=SEED):
    names = names or list(VARIANTS)
    frames = {y: G.load_frame(y) for y in G.SEASONS}
    G.set_arm_side_sign(list(frames.values()))
    for Y, Y1 in G.PAIRS:
        todo = [n for n in names if not os.path.exists(G.agg_path(n, Y, seed))]
        if not todo:
            print(f'  {Y}->{Y1}: cached', flush=True)
            continue
        train_years = [y for y in G.SEASONS if y not in (Y, Y1)]
        slopes = G.fit_vaa_slopes([frames[y] for y in train_years])
        hs = fit_haa_slopes([frames[y] for y in train_years])
        print(f'  {Y}->{Y1}: HAA slopes ' + ', '.join(f'{k} {v[0]:.2f}' for k, v in sorted(hs.items())), flush=True)
        P = {y: apply_haa_n(G.prepare(frames[y], slopes), hs) for y in train_years + [Y, Y1]}
        ytr = np.concatenate([P[y]['target_xrv'].values for y in train_years])
        for name in todo:
            t0 = time.time()
            spec = VARIANTS[name]
            feats = G.variant_feats(spec)
            Xtr = pd.concat([G.design(P[y], spec, feats) for y in train_years], ignore_index=True)
            pred = G.fit_predict(Xtr, ytr, G.design(P[Y], spec, feats), spec, seed)
            del Xtr
            agg = G.aggregates(P[Y].assign(stuff=-pred), P[Y1])
            met = G.metrics_from(agg)
            met.update(n_train=int(len(ytr)), feats=feats, partial_target=(Y == G.PARTIAL_Y),
                       note='2026-09-23 re-gate of an 08-14 per-type candidate')
            pd.to_pickle(agg, G.agg_path(name, Y, seed))
            res = json.load(open(G.RESULTS))
            res.setdefault(name, {}).setdefault(str(Y), {})[str(seed)] = met
            with open(G.RESULTS + '.tmp', 'w') as f:
                json.dump(res, f, indent=1)
            os.replace(G.RESULTS + '.tmp', G.RESULTS)
            print(f'  {name:<14} s{seed} {Y}->{Y1}: nxt raw {met["nxt_r"]:.4f} rend {met["nxt_r_rend"]:.4f} '
                  f'[{time.time() - t0:.0f}s]', flush=True)
            del pred, agg
            gc.collect()
        del P, ytr
        gc.collect()


def units(name, Y, seed=SEED):
    a = pd.read_pickle(G.agg_path(name, Y, seed))
    j = a['uy'].join(a['uy1'], lsuffix='_y', rsuffix='_y1', how='inner').reset_index()
    j = j[(j['n_y'] >= MIN_U) & (j['n_y1'] >= MIN_U)]
    return j[['pitcher', 'pitch_type', 's_r', 't']].assign(pair=Y)


def per_type(name, base):
    V = pd.concat([units(name, Y) for Y, _ in G.PAIRS])
    J = base.merge(V, on=['pitcher', 'pitch_type', 'pair'], suffixes=('_a', '_b'))
    rng = np.random.default_rng(17)
    out = {}
    for t in TYPES:
        g = J[J['pitch_type'] == t].reset_index(drop=True)
        if len(g) < 60:
            continue
        ra = np.corrcoef(g['s_r_a'], g['t_a'])[0, 1]
        rb = np.corrcoef(g['s_r_b'], g['t_b'])[0, 1]
        pits = g['pitcher'].unique()
        idx = {p: np.flatnonzero(g['pitcher'].values == p) for p in pits}
        ds = []
        for _ in range(BOOT_B):
            q = g.iloc[np.concatenate([idx[p] for p in rng.choice(pits, len(pits))])]
            ds.append(np.corrcoef(q['s_r_b'], q['t_b'])[0, 1] - np.corrcoef(q['s_r_a'], q['t_a'])[0, 1])
        se = float(np.std(ds))
        pp = [float(np.corrcoef(h['s_r_b'], h['t_b'])[0, 1] - np.corrcoef(h['s_r_a'], h['t_a'])[0, 1])
              for _, h in g.groupby('pair')]
        out[t] = {'units': int(len(g)), 'shipped': float(ra), 'variant': float(rb),
                  'delta': float(rb - ra), 'se': se, 'z': float((rb - ra) / se),
                  'wins': int(sum(v > 0 for v in pp)), 'per_pair': pp}
    return out


def seed_followup(names, seeds):
    """Advancing candidates: extra seeds, per-type validity vs SHIPPED on the
    SAME seed, averaged over seeds (the gate summary folds seed SD itself)."""
    for sd in seeds:
        run_fits(names, sd)
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    fol = out.setdefault('seed_followup', {})
    for name in names:
        per = {}
        for sd in [SEED] + list(seeds):
            base = pd.concat([units('SHIPPED', Y, sd) for Y, _ in G.PAIRS])
            V = pd.concat([units(name, Y, sd) for Y, _ in G.PAIRS])
            J = base.merge(V, on=['pitcher', 'pitch_type', 'pair'], suffixes=('_a', '_b'))
            for t in TYPES:
                g = J[J['pitch_type'] == t]
                if len(g) >= 60:
                    per.setdefault(t, []).append(float(np.corrcoef(g['s_r_b'], g['t_b'])[0, 1]
                                                       - np.corrcoef(g['s_r_a'], g['t_a'])[0, 1]))
        fol[name] = {t: {'deltas_by_seed': v, 'mean': float(np.mean(v)), 'seed_sd': float(np.std(v, ddof=1))}
                     for t, v in per.items()}
        print(f'{name} per-type delta by seed [s0, ' + ', '.join(f's{x}' for x in seeds) + ']:')
        for t, v in fol[name].items():
            print(f"  {t}: {' '.join(f'{x:+.4f}' for x in v['deltas_by_seed'])}  mean {v['mean']:+.4f}  seed sd {v['seed_sd']:.4f}")
    json.dump(out, open(OUT + '.tmp', 'w'), indent=1)
    os.replace(OUT + '.tmp', OUT)


def main():
    t0 = time.time()
    if '--followup' in sys.argv:
        names = sys.argv[sys.argv.index('--followup') + 1].split(',')
        seed_followup(names, (1, 2))
        return
    run_fits()
    base = pd.concat([units('SHIPPED', Y) for Y, _ in G.PAIRS])
    out = {'variants': VARIANTS, 'per_type': {}}
    for name in VARIANTS:
        out['per_type'][name] = per_type(name, base)
    json.dump(out, open(OUT + '.tmp', 'w'), indent=1)
    os.replace(OUT + '.tmp', OUT)
    print('\nper-type validity delta vs SHIPPED s0 (z, wins/5); * = a target type of the candidate')
    print('variant         ' + ' '.join(f'{t:>13}' for t in TYPES))
    for name in VARIANTS:
        pt = out['per_type'][name]
        cells = []
        for t in TYPES:
            if t not in pt:
                cells.append(f'{"-":>13}')
                continue
            v = pt[t]
            mark = '*' if t in TARGET_TYPES[name] else ' '
            cells.append(f'{mark}{v["delta"]:+.3f}({v["z"]:+.1f},{v["wins"]})')
        print(f'{name:<15} ' + ' '.join(f'{c:>13}' for c in cells))
    print(f'\nwrote {OUT} [{time.time() - t0:.0f}s]')
    print('gate: python3 scripts/research/stuff/stuff_gate_v2.py summary --names SHIPPED,' + ','.join(VARIANTS))


if __name__ == '__main__':
    main()
