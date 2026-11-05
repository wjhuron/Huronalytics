"""pit_stuff_scale_test.py: which Stuff+ form belongs in the pitcher projection? (2026-11-05, per Wally, from the Gray question). Research only.

The projection reads the raw pooled xRV mean across a pitcher's pitches (data/_era_internal_stuff.json, stuff_2026_loso.json). The site's Stuff+ is the mean of per-type atoms: each pitch against its own type's anchor.
The raw form therefore credits the pitch MIX: breaking balls carry a better raw value than fastballs before any pitch is graded. Both come from the same gate frames: agg_SHIPPED_{Y}_s{0,1,2}.pkl, 's' raw and 's_r' atoms, season Y held out of the fit.
Variants, each fit with T left out, full projection design, every pitcher with >= 1 out in T, IP_T weighted, T 2022-2026:
  NONE  no Stuff+ channel      FILE  shipped input      RAW   agg s (replicates FILE)      REND  agg s_r      BOTH  REND plus the mix part (RAW minus what REND implies)
Targets: RA9 (the production target) and FIP. Rule: A beats B at a gap over 2 paired-bootstrap SE and most replicates, else TIE. N0 swept on REND, 250 is the shipped value.
Also: the same comparison within history-defined role, because relievers throw more breaking balls and grade higher.
Usage: PYTHONHASHSEED=0 python3 scripts/research/projection/pit_stuff_scale_test.py
Output: console + data/_proj/_pit_stuff_scale_test.json
"""
import json, os, pickle, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'research', 'era'))
import pit_rate_backtest as pr, pit_horizon_backtest as ph, pit_stuff_addon as pst, pit_ev_addon as pev
import era_stuff_loso_v2 as E
P = pr.P; ROOT = pr.ROOT; NB = 2000
S = {y: pr.season(y) for y in range(2015, 2027)}
FILE = json.load(open(os.path.join(ROOT, 'data', '_era_internal_stuff.json')))
H1 = json.load(open(os.path.join(P, '_pit_horizon_backtest.json')))['1']['pooled']; par = (H1['d'], H1['n0'], H1['peak'], H1['yi'], H1['od'])
_pl = {y: json.load(open(f'{P}/lines_pitching_{y}.json')) for y in range(2017, 2027)}
_club = {y: {r['id']: r.get('team') for r in _pl[y]} for y in _pl}
_lg = {y: 27 * sum(int(r.get('runs') or 0) for r in _pl[y]) / sum(int(r.get('outs') or 0) for r in _pl[y]) for y in _pl}
PF = json.load(open(P + '/park_factors_hist.json'))
peff = lambda y, t: 0.0 if PF.get(str(y), {}).get(str(t)) is None else ((PF[str(y)][str(t)] / 100 + 1) / 2 - 1) * _lg[y]
EVT, EVL = pev.ev_table()


def agg_tables():
    raw, rend = {}, {}
    for y in range(2021, 2026):
        nm = E.name_map(y); ss, sr, ns = {}, {}, {}
        for seed in range(3):
            py = pickle.load(open(os.path.join(ROOT, 'data', '_gate_v2', f'agg_SHIPPED_{y}_s{seed}.pkl'), 'rb'))['py']
            for name, row in py.iterrows():
                pid = nm.get(str(name).lower())
                if pid is None or row['n'] < E.MIN_N:
                    continue
                ss.setdefault(pid, []).append(row['s']); sr.setdefault(pid, []).append(row['s_r']); ns[pid] = int(row['n'])
        raw[str(y)] = {str(k): {'stuff_full': float(np.mean(v)), 'n_full': ns[k]} for k, v in ss.items()}
        rend[str(y)] = {str(k): {'stuff_full': float(np.mean(sr[k])) - 100.0, 'n_full': ns[k]} for k in ss}
    return raw, rend


def rows_all(B):
    return [(pid, t, [S[B - k].get(pid) for k in range(3)]) for pid, t in S[B + 1].items() if any(S[B - k].get(pid) for k in range(3))]


def base_design(R, B):
    Xf, y, w = ph.feats(R, 1, *par)
    ex = np.array([1 / (1 + sum(h['bf'] for h in hist if h) / 20) for _, _, hist in R])
    pk = []
    ev = []
    for pid, _, hist in R:
        n = d = 0.0
        for k, h in enumerate(hist):
            if h:
                n += par[0] ** k * h['bf'] * peff(B - k, _club[B - k].get(pid)); d += par[0] ** k * h['bf']
        pk.append((n / d if d else 0.0, peff(B + 1, _club[B + 1].get(pid))))
        n = d = 0.0
        for k in range(3):
            r = EVT[B - k].get(int(pid))
            if r:
                n += par[0] ** k * r[1] * (r[0] - EVL[B - k]); d += par[0] ** k * r[1]
        ev.append(n / (d + 100))
    fip = np.array([t['fip'] for _, t, _ in R])
    role = np.array([next((h['gs'] for h in hist if h), 0.0) for _, _, hist in R])
    return Xf, np.column_stack([ex, np.array(pk), ev]), y, fip, w, role


def main():
    raw, rend = agg_tables()
    common = [(FILE[y][k]['stuff_full'], raw[y][k]['stuff_full']) for y in raw for k in raw[y] if k in FILE[y]]
    a = np.array(common); print(f'replication: agg raw v shipped file r {np.corrcoef(a[:, 0], a[:, 1])[0, 1]:.4f}, n {len(a)}, rms gap {np.sqrt(np.mean((a[:, 0] - a[:, 1]) ** 2)):.5f}')
    x = [(raw[y][k]['stuff_full'], rend[y][k]['stuff_full']) for y in raw for k in raw[y] if raw[y][k]['n_full'] >= 500]; x = np.array(x); print(f'raw v rendered at 500+ pitches: r {np.corrcoef(x[:, 0], x[:, 1])[0, 1]:.3f}')
    Bs = [2021, 2022, 2023, 2024, 2025]
    D = {B: (lambda R: (R,) + base_design(R, B))(rows_all(B)) for B in Bs}
    def chan(B, tab, n0=250):
        return pst.stuff_channel(D[B][0], B + 1, tab, H1['d'], n0)[0]
    def preds(variant, target):
        out = {}
        for B in Bs:
            def M(b):
                _, Xf, O, y, fip, w, role = D[b]
                extra = []
                for tab, n0 in variant:
                    extra.append(chan(b, tab, n0))
                return np.column_stack([Xf[:, :-1]] + extra + [O, Xf[:, -1]]), (y if target == 'ra9' else fip), w
            tr = [M(b) for b in Bs if b != B]
            p, _ = pr.fit_predict(np.vstack([t[0] for t in tr]), np.concatenate([t[1] for t in tr]), np.concatenate([t[2] for t in tr]), M(B)[0])
            out[B] = p
        return out
    VAR = {'NONE': [], 'FILE': [(FILE, 250)], 'RAW': [(raw, 250)], 'REND': [(rend, 250)], 'BOTH': [(raw, 250), (rend, 250)]}
    for n0 in (50, 100, 500, 1000, 2000):
        VAR[f'REND_{n0}'] = [(rend, n0)]
    res = {}
    def score(p, B, target, mask=None):
        _, _, _, y, fip, w, role = D[B]; t = y if target == 'ra9' else fip
        m = np.ones(len(t), bool) if mask is None else mask
        return float(np.average((p[m] - t[m]) ** 2, weights=w[m]))
    def cmp(a, b, target, maskf=None):
        rng = np.random.default_rng(0); gaps = []; draws = np.zeros((NB, len(Bs)))
        for j, B in enumerate(Bs):
            _, _, _, y, fip, w, role = D[B]; t = y if target == 'ra9' else fip
            m = np.ones(len(t), bool) if maskf is None else maskf(role)
            A, C, Y, W = a[B][m], b[B][m], t[m], w[m]
            base = np.average((C - Y) ** 2, weights=W); gaps.append(100 * (np.average((A - Y) ** 2, weights=W) - base) / base)
            n = len(Y)
            for i in range(NB):
                ix = rng.integers(0, n, n); bb = np.average((C[ix] - Y[ix]) ** 2, weights=W[ix]); draws[i, j] = 100 * (np.average((A[ix] - Y[ix]) ** 2, weights=W[ix]) - bb) / bb
        g = float(np.mean(gaps)); se = float(draws.mean(axis=1).std()); wins = sum(x < 0 for x in gaps)
        tag = 'first' if g < -2 * se and wins >= 4 else 'second' if g > 2 * se and len(Bs) - wins >= 4 else 'TIE'
        return dict(gap_pct=g, se=se, wins=wins, n=len(Bs), per=gaps, verdict=tag)
    for tgt in ('ra9', 'fip'):
        P_ = {k: preds(v, tgt) for k, v in VAR.items()}
        print(f'\n== target {tgt}: weighted MSE, mean over T 2022-2026')
        for k in VAR:
            print(f'  {k:10s} {np.mean([score(P_[k][B], B, tgt) for B in Bs]):.4f}')
        for a_, b_ in (('FILE', 'NONE'), ('RAW', 'FILE'), ('REND', 'FILE'), ('REND', 'NONE'), ('BOTH', 'REND'), ('BOTH', 'FILE')):
            c = cmp(P_[a_], P_[b_], tgt); res[f'{tgt}_{a_}_{b_}'] = c
            print(f"  {a_} v {b_}: {c['gap_pct']:+.3f}% MSE (SE {c['se']:.3f}), first wins {c['wins']}/{c['n']} -> {c['verdict']}  per T " + ' '.join(f'{x:+.2f}' for x in c['per']))
        for lab, f in (('starters by history (gs share >= .5)', lambda r: r >= .5), ('relievers by history', lambda r: r < .5)):
            c = cmp(P_['REND'], P_['FILE'], tgt, f); res[f'{tgt}_REND_FILE_{lab[:5]}'] = c
            print(f"  REND v FILE, {lab}: {c['gap_pct']:+.3f}% (SE {c['se']:.3f}) {c['wins']}/{c['n']} -> {c['verdict']}")
        if tgt == 'ra9':
            print('  REND N0 curve: ' + ' '.join(f"{n}:{np.mean([score(P_[k][B], B, tgt) for B in Bs]):.4f}" for n, k in ((50, 'REND_50'), (100, 'REND_100'), (250, 'REND'), (500, 'REND_500'), (1000, 'REND_1000'), (2000, 'REND_2000'))))
    json.dump(res, open(os.path.join(P, '_pit_stuff_scale_test.json'), 'w'), indent=1, default=float)


if __name__ == '__main__':
    main()
