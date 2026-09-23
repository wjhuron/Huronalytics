#!/usr/bin/env python3
"""stuff_platoon_pertype_gate.py — gate the per-type platoon fix.

Background (Wally, 2026-09-23; memory/project_stuff_platoon_location_fixed).
Stuff+ gives the same-hand credit through ONE `platoon_same` flag in a
pitch-type-agnostic model. Its average credit per type disagrees with the
realized gap (too low on SL/FC/CU). Candidates, all trained on the shipped
label:

  HBBAT   + hb_bat = hb * (+1 same / -1 opposite): horizontal break signed
          toward/away from the batter. Keeps the model type-agnostic.
  BATREL  HBBAT + rel_x_bat = rel_x * (+1 / -1): release side vs the batter.
  TYPED   + plt_<T> = platoon_same * [pitch_type == T] for FF SI FC SL ST CU
          CH FS. Puts pitch LABELS into the model, which the shipped design
          forbids (train_stuff.design docstring); a comparison arm only.

The FF over-credit is a LABEL effect (location), which no feature can fix;
these arms target the under-credited types.

Decision rule, fixed before the run (said to Wally first):
  1. gate nxt_r (raw, rendered, within-hand) does not lose,
  2. per-hand unit accuracy improves, paired z >= 2 and >= 4/5 pairs,
  3. the per-type average gap moves toward the realized gap.

Per variant and pair (seed 0, gate v2 protocol: fit on seasons other than Y
and Y+1): the gate aggregates are written to data/_gate_v2 exactly as
`stuff_gate_v2.py run` writes them (so `stuff_gate_v2.py summary --names
SHIPPED,HBBAT,...` gives the paired z), and every Y pitch is also scored at
platoon 0 and 1 for the split metrics:

  hand_r      per-(unit, hand) predicted mean in Y vs realized mean target in
              Y+1, demeaned within (pair, type), n-weighted; units need
              MIN_SIDE pitches per side in Y+1
  gap         per type: mean predicted same-hand credit (points) vs the
              realized pitcher-fixed gap in Y+1 (and in Y)
  split       the pitcher-specific split persistence slope/r
              (stuff_platoon_split_persistence.py)

SHIPPED s0 per-pitch predictions come from data/_platoon_split/pred_{Y}.pkl
(same config, seed, frames), checked against the gate's cached aggregates.
Output: data/_platoon_split/pertype_gate.json. Run from the repo root.
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
import stuff_platoon_split_persistence as SP            # noqa: E402

OUT = os.path.join(ROOT, 'data', '_platoon_split', 'pertype_gate.json')
TYPES = ['FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS']
VARIANTS = {
    'HBBAT': {'add': ['hb_bat']},
    'BATREL': {'add': ['hb_bat', 'rel_x_bat']},
    'TYPED': {'add': [f'plt_{t}' for t in TYPES]},
}
SEED = 0
MIN_SIDE = SP.MIN_SIDE
BOOT_B = 1000

_prepare = G.prepare


def prepare_plus(d, slopes, anchor='true'):
    d = _prepare(d, slopes, anchor)
    sgn = (2 * d['platoon_same'] - 1).astype('float32')
    d['hb_bat'] = (d['hb'] * sgn).astype('float32')
    d['rel_x_bat'] = (d['rel_x'] * sgn).astype('float32')
    for t in TYPES:
        d[f'plt_{t}'] = (d['platoon_same'] * (d['pitch_type'] == t)).astype('float32')
    return d


G.prepare = prepare_plus


def pred_file(name, Y):
    if name == 'SHIPPED':
        return os.path.join(ROOT, 'data', '_platoon_split', f'pred_{Y}.pkl')
    return os.path.join(ROOT, 'data', '_platoon_split', f'pred_{name}_{Y}.pkl')


def fit_variants(frames):
    results = json.load(open(G.RESULTS)) if os.path.exists(G.RESULTS) else {}
    for Y, Y1 in G.PAIRS:
        todo = [n for n in VARIANTS if not (os.path.exists(pred_file(n, Y))
                                            and os.path.exists(G.agg_path(n, Y, SEED)))]
        if not todo:
            print(f'  pair {Y}->{Y1}: cached', flush=True)
            continue
        train_years = [y for y in G.SEASONS if y not in (Y, Y1)]
        slopes = G.fit_vaa_slopes([frames[y] for y in train_years])
        P = {y: G.prepare(frames[y], slopes) for y in train_years + [Y, Y1]}
        ytr = np.concatenate([P[y]['target_xrv'].values for y in train_years])
        for name in todo:
            t0 = time.time()
            spec = VARIANTS[name]
            feats = G.variant_feats(spec)
            Xtr = pd.concat([G.design(P[y], spec, feats) for y in train_years],
                            ignore_index=True)
            m = SP._fit(Xtr, ytr)
            del Xtr
            gc.collect()
            dY = P[Y]
            XY = G.design(dY, spec, feats)
            pa = m.predict(XY)
            # counterfactual hand: platoon_same AND every batter-relative
            # column flip together
            Xc = {}
            for v in (0, 1):
                X = XY.copy()
                X['platoon_same'] = v
                sgn = 2 * v - 1
                if 'hb_bat' in X:
                    X['hb_bat'] = dY['hb'].values * sgn
                if 'rel_x_bat' in X:
                    X['rel_x_bat'] = dY['rel_x'].values * sgn
                for t in TYPES:
                    c = f'plt_{t}'
                    if c in X:
                        X[c] = float(v) * (dY['pitch_type'].values == t)
                Xc[v] = m.predict(X)
            del m
            pr = pd.DataFrame({
                'pitcher': dY['pitcher'].values, 'throws': dY['throws'].values,
                'pitch_type': dY['pitch_type'].values,
                'platoon_same': dY['platoon_same'].values,
                'stuff': -pa, 'gap': (Xc[0] - Xc[1]).astype('float64'),
                'p0': Xc[0], 'p1': Xc[1],
            })
            pr.to_pickle(pred_file(name, Y))
            agg = G.aggregates(dY.assign(stuff=-pa), P[Y1])
            met = G.metrics_from(agg)
            met['n_train'] = int(len(ytr))
            met['feats'] = feats
            met['partial_target'] = (Y == G.PARTIAL_Y)
            pd.to_pickle(agg, G.agg_path(name, Y, SEED))
            results = json.load(open(G.RESULTS)) if os.path.exists(G.RESULTS) else {}
            results.setdefault(name, {}).setdefault(str(Y), {})[str(SEED)] = met
            with open(G.RESULTS + '.tmp', 'w') as f:
                json.dump(results, f, indent=1)
            os.replace(G.RESULTS + '.tmp', G.RESULTS)
            print(f'  {name:<7} {Y}->{Y1}: nxt raw {met["nxt_r"]:.4f} rend '
                  f'{met["nxt_r_rend"]:.4f} [{time.time() - t0:.0f}s]', flush=True)
            del XY, Xc, pr, agg
            gc.collect()
        del P, ytr
        gc.collect()


def shipped_counterfactual(Y):
    """pred_{Y}.pkl carries stuff (actual hand) and gap; rebuild p0/p1:
    p_actual = -stuff, p0 - p1 = gap."""
    pr = pd.read_pickle(pred_file('SHIPPED', Y))
    pact = -pr['stuff'].values
    same = pr['platoon_same'].values == 1
    p1 = np.where(same, pact, pact - pr['gap'].values)
    p0 = np.where(same, pact + pr['gap'].values, pact)
    return pr.assign(p0=p0, p1=p1)


def hand_rows(pr, frame1, sd):
    """(unit, hand) rows: predicted Y mean at that hand vs realized Y+1 mean."""
    key = ['pitcher', 'throws', 'pitch_type']
    pu = pr.groupby(key).agg(p0=('p0', 'mean'), p1=('p1', 'mean'), n_y=('p0', 'size'))
    x = frame1[key + ['platoon_same', 'target_xrv']]
    r = x.groupby(key + ['platoon_same'])['target_xrv'].agg(['mean', 'size']).unstack('platoon_same')
    r.columns = [f'{a}{int(b)}' for a, b in r.columns]
    j = pu.join(r, how='inner').reset_index()
    j = j[(j['n_y'] >= SP.MIN_UNIT_Y) & (j['size0'] >= MIN_SIDE)
          & (j['size1'] >= MIN_SIDE) & j['pitch_type'].isin(TYPES)]
    conv = 10.0 / j['pitch_type'].map(sd).astype(float)
    rows = []
    for h in (0, 1):
        rows.append(pd.DataFrame({
            'pitcher': j['pitcher'].values, 'pitch_type': j['pitch_type'].values,
            'hand': h,
            'pred': (-j[f'p{h}'] * conv).values,               # pitcher-positive
            'real': (-j[f'mean{h}'] * conv).values,
            'w': j[f'size{h}'].values.astype(float)}))
    return pd.concat(rows, ignore_index=True)


def wr(df):
    x = df['pred'] - np.average(df['pred'], weights=df['w'])
    y = df['real'] - np.average(df['real'], weights=df['w'])
    w = df['w']
    return float(np.sum(w * x * y) / np.sqrt(np.sum(w * x * x) * np.sum(w * y * y)))


def demean_within(df, by):
    out = df.copy()
    for c in ('pred', 'real'):
        out[c] = out[c] - (out[c] * out['w']).groupby([out[k] for k in by]).transform('sum') \
            / out['w'].groupby([out[k] for k in by]).transform('sum')
    return out


def realized_gap(frame, sd, t):
    g = frame[frame['pitch_type'] == t]
    if len(g) < 1500:
        return float('nan')
    codes = pd.factorize(g['pitcher'].values)[0]
    y = g['target_xrv'].values.astype(float)
    d = g['platoon_same'].values.astype(float)
    ry, rd = y.copy(), d.copy()
    n = np.bincount(codes)
    ry -= (np.bincount(codes, ry) / n)[codes]
    rd -= (np.bincount(codes, rd) / n)[codes]
    b = np.sum(rd * ry) / np.sum(rd * rd)
    return float(-b * 10.0 / sd[t])


def main():
    t0 = time.time()
    frames = {y: G.load_frame(y) for y in G.SEASONS}
    G.set_arm_side_sign(list(frames.values()))

    # consistency: pred_{Y}.pkl (SHIPPED s0) vs the gate's cached SHIPPED s0
    for Y, _ in G.PAIRS:
        pr = pd.read_pickle(pred_file('SHIPPED', Y))
        agg = pd.read_pickle(G.agg_path('SHIPPED', Y, SEED))
        s = pr.groupby('pitcher')['stuff'].mean()
        j = agg['py'][['s']].join(s.rename('mine'), how='inner')
        dmax = float((j['s'] - j['mine']).abs().max())
        print(f'  SHIPPED s0 {Y}: pitcher means vs gate cache, max |d| {dmax:.2e}', flush=True)
        if dmax > 1e-4:
            print(f'  WARNING: SHIPPED predictions differ from the gate cache for {Y}; '
                  f'split metrics compare a refit, not the gate baseline', flush=True)

    fit_variants(frames)

    names = ['SHIPPED'] + list(VARIANTS)
    out = {'decision_rule': 'gate nxt_r no loss; hand_r paired z>=2 and >=4/5; '
                            'type gaps move toward realized', 'variants': {}}
    H = {n: [] for n in names}
    gaps = {n: {} for n in names}
    real_gap = {}
    for Y, Y1 in G.PAIRS:
        base = shipped_counterfactual(Y)
        sd = {k: v[1] for k, v in G.anchors_for(base).items()}
        for t in TYPES:
            real_gap.setdefault(t, {})[str(Y)] = {
                'Y': realized_gap(frames[Y], sd, t), 'Y1': realized_gap(frames[Y1], sd, t)}
        for n in names:
            pr = base if n == 'SHIPPED' else pd.read_pickle(pred_file(n, Y))
            sdn = {k: v[1] for k, v in G.anchors_for(pr).items()}
            h = hand_rows(pr, frames[Y1], sdn).assign(pair=Y)
            H[n].append(h)
            for t in TYPES:
                q = pr[pr['pitch_type'] == t]
                if len(q) >= 1500:
                    gaps[n].setdefault(t, {})[str(Y)] = float(q['gap'].mean() * 10.0 / sdn[t])
    for n in names:
        H[n] = demean_within(pd.concat(H[n], ignore_index=True), ['pair', 'pitch_type'])

    base = H['SHIPPED']
    kb = base.set_index(['pair', 'pitcher', 'pitch_type', 'hand'])
    pits = base['pitcher'].unique()
    rng = np.random.default_rng(11)
    boot_idx = [rng.choice(pits, len(pits)) for _ in range(BOOT_B)]
    for n in names:
        h = H[n]
        rec = {'hand_r': wr(h), 'hand_r_pair': {str(y): wr(h[h['pair'] == y]) for y in sorted(h['pair'].unique())}}
        if n != 'SHIPPED':
            k = h.set_index(['pair', 'pitcher', 'pitch_type', 'hand'])
            common = kb.index.intersection(k.index)
            A = kb.loc[common].reset_index()
            Bv = k.loc[common].reset_index()
            d_all = wr(Bv) - wr(A)
            d_pair = {str(y): wr(Bv[Bv['pair'] == y]) - wr(A[A['pair'] == y]) for y in sorted(A['pair'].unique())}
            idx = {p: np.flatnonzero(A['pitcher'].values == p) for p in pits}
            ds = []
            for bi in boot_idx:
                take = np.concatenate([idx[p] for p in bi if p in idx])
                ds.append(wr(Bv.iloc[take]) - wr(A.iloc[take]))
            se = float(np.std(ds))
            rec.update({'d_hand_r': d_all, 'd_hand_r_se': se, 'z': d_all / se if se else float('nan'),
                        'd_hand_r_pair': d_pair,
                        'wins': int(sum(v > 0 for v in d_pair.values()))})
        rec['gap_pts'] = {t: float(np.mean(list(v.values()))) for t, v in gaps[n].items()}
        out['variants'][n] = rec
    out['realized_gap_pts'] = {t: {'Y': float(np.nanmean([v['Y'] for v in d.values()])),
                                   'Y1': float(np.nanmean([v['Y1'] for v in d.values()]))}
                               for t, d in real_gap.items()}
    json.dump(out, open(OUT + '.tmp', 'w'), indent=1)
    os.replace(OUT + '.tmp', OUT)

    print('\nper-hand accuracy (r of per-hand Y grade vs Y+1 per-hand result, within type):')
    for n in names:
        r = out['variants'][n]
        extra = (f"  d {r['d_hand_r']:+.4f} (se {r['d_hand_r_se']:.4f}, z {r['z']:.1f}), "
                 f"wins {r['wins']}/5  {r['d_hand_r_pair']}" if n != 'SHIPPED' else '')
        print(f'  {n:<8} r {r["hand_r"]:.4f}{extra}')
    print('\naverage same-hand credit, points (mean over the 5 Y seasons):')
    print('  type  realizedY  realizedY1  ' + '  '.join(f'{n:>8}' for n in names))
    for t in TYPES:
        rg = out['realized_gap_pts'].get(t, {})
        print(f'  {t:4}  {rg.get("Y", float("nan")):9.1f}  {rg.get("Y1", float("nan")):10.1f}  '
              + '  '.join(f'{out["variants"][n]["gap_pts"].get(t, float("nan")):8.1f}' for n in names))
    print(f'\nwrote {OUT} [{time.time() - t0:.0f}s]')
    print('gate: python3 scripts/research/stuff/stuff_gate_v2.py summary --names SHIPPED,'
          + ','.join(VARIANTS))


if __name__ == '__main__':
    main()
