"""pit_fit_audit.py: the three open questions on the pitcher projection, on Stuff+ history with the target season out of every fit (2026-11-05). Research only.
  1. How much of the Stuff+ gain was target leakage? FILE (data/_era_internal_stuff.json, model saw T) v CLEAN (pit_stuff_clean_build.py) v NONE.
  2. Raw or atom form, on clean history.
  3. Shrinkage N0, swept on the clean forms until the optimum is bracketed.
  4. The wrong-signed runs-allowed channel: drop it, or drop xwOBA (coefficient about 0). Fit coefficients are printed by fold.
Design as project_players: pooled h=1 settings, experience, park with target park, EV N0 100, age offset. Every pitcher with >= 1 out in T, IP_T weighted, T 2022-2026, T left out of the OLS.
Rule: gap over 2 paired-bootstrap SE and 4 of 5 replicates, else TIE.
Usage: PYTHONHASHSEED=0 python3 scripts/research/projection/pit_fit_audit.py
Output: console + data/_proj/_pit_fit_audit.json
"""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import pit_stuff_scale_test as T
pr, pst = T.pr, T.pst
P = T.P; Bs = [2021, 2022, 2023, 2024, 2025]; NB = 2000
CL = json.load(open(os.path.join(P, '_stuff_clean.json')))
def tab(kind):
    if kind == 'FILE':
        return {B + 1: T.FILE for B in Bs}
    out = {}
    for B in Bs:
        t = str(B + 1)
        out[B + 1] = {y: {pid: {'stuff_full': (r['s'] if kind == 'CLEAN' else r['s_r'] - 100.0), 'n_full': r['n']} for pid, r in d.items()} for y, d in CL[t].items()}
    return out
D = {B: (lambda R: (R,) + T.base_design(R, B))(T.rows_all(B)) for B in Bs}
TAB = {k: tab(k) for k in ('FILE', 'CLEAN', 'ATOM')}
CH = {'ra9': 0, 'fip': 1, 'kbb': 2, 'xw': 3}
def M(b, kind, n0, drop, tgt):
    _, Xf, O, y, fip, w, role = D[b]
    cols = [Xf[:, i] for i in range(Xf.shape[1] - 1) if i not in [CH[d] for d in drop]]
    if kind != 'NONE':
        cols.append(pst.stuff_channel(D[b][0], b + 1, TAB[kind][b + 1], T.H1['d'], n0)[0])
    return np.column_stack(cols + [O, Xf[:, -1]]), (y if tgt == 'ra9' else fip), w
def run(kind, n0, drop, tgt):
    out = {}; betas = []
    for B in Bs:
        tr = [M(b, kind, n0, drop, tgt) for b in Bs if b != B]
        p, beta = pr.fit_predict(np.vstack([t[0] for t in tr]), np.concatenate([t[1] for t in tr]), np.concatenate([t[2] for t in tr]), M(B, kind, n0, drop, tgt)[0])
        out[B] = p; betas.append(beta)
    return out, np.array(betas)
def mse(p, tgt):
    v = []
    for B in Bs:
        _, _, _, y, fip, w, _ = D[B]; t = y if tgt == 'ra9' else fip
        v.append(float(np.average((p[B] - t) ** 2, weights=w)))
    return v
def cmp(a, b, tgt):
    rng = np.random.default_rng(0); gaps = []; dr = np.zeros((NB, len(Bs)))
    for j, B in enumerate(Bs):
        _, _, _, y, fip, w, _ = D[B]; t = y if tgt == 'ra9' else fip
        A, C = a[B], b[B]; base = np.average((C - t) ** 2, weights=w); gaps.append(100 * (np.average((A - t) ** 2, weights=w) - base) / base); n = len(t)
        for i in range(NB):
            ix = rng.integers(0, n, n); bb = np.average((C[ix] - t[ix]) ** 2, weights=w[ix]); dr[i, j] = 100 * (np.average((A[ix] - t[ix]) ** 2, weights=w[ix]) - bb) / bb
    g = float(np.mean(gaps)); se = float(dr.mean(axis=1).std()); wi = sum(x < 0 for x in gaps)
    tag = 'first' if g < -2 * se and wi >= 4 else 'second' if g > 2 * se and 5 - wi >= 4 else 'TIE'
    return f"{g:+.3f}% (SE {se:.3f}) first wins {wi}/5 -> {tag}  per T " + ' '.join(f'{x:+.2f}' for x in gaps), dict(g=g, se=se, wins=wi, per=gaps, tag=tag)
res = {}
for tgt in ('ra9', 'fip'):
    print(f'\n===== target {tgt}')
    R = {}
    base = {k: run(k, 250, (), tgt) for k in ('NONE', 'FILE', 'CLEAN', 'ATOM')}
    for k, v in base.items():
        print(f'  {k:6s} MSE {np.mean(mse(v[0], tgt)):.4f}  mean coefs [const ra9 fip kbb xw gs stuff ...] ' + ' '.join(f'{x:.3f}' for x in v[1].mean(axis=0)[:7]))
    for a, b in (('FILE', 'NONE'), ('CLEAN', 'NONE'), ('ATOM', 'NONE'), ('CLEAN', 'FILE'), ('ATOM', 'CLEAN')):
        s, d = cmp(base[a][0], base[b][0], tgt); print(f'  {a} v {b}: {s}'); res[f'{tgt}_{a}_{b}'] = d
    for kind in ('CLEAN', 'ATOM'):
        curve = {}
        for n0 in (0, 25, 50, 100, 250, 500, 1000, 2000, 4000, 8000):
            curve[n0] = float(np.mean(mse(run(kind, n0, (), tgt)[0], tgt)))
        print(f'  {kind} N0 curve: ' + ' '.join(f'{k}:{v:.4f}' for k, v in curve.items()) + f'  best {min(curve, key=curve.get)}'); res[f'{tgt}_{kind}_N0'] = curve
    betas = base['CLEAN'][1]
    print('  CLEAN ra9 coefficient by fold: ' + ' '.join(f'{x:.3f}' for x in betas[:, 1]) + '; xw: ' + ' '.join(f'{x:.2f}' for x in betas[:, 4]))
    for drop in (('ra9',), ('xw',), ('ra9', 'xw')):
        v = run('CLEAN', 250, drop, tgt); s, d = cmp(v[0], base['CLEAN'][0], tgt); print(f'  CLEAN drop {drop} v CLEAN: {s}'); res[f'{tgt}_drop_{"_".join(drop)}'] = d
json.dump(res, open(os.path.join(P, '_pit_fit_audit.json'), 'w'), indent=1, default=float)
print('wrote')
