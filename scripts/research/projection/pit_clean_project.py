"""pit_clean_project.py: the 2027 pitcher level refit on Stuff+ history with the target out of every fit, the start-share total, and the blend tests rerun on it (2026-11-05). Research only; nothing here changes the shipped file.
Part A  control: with FILE training channels the code must reproduce projections_pitchers.csv, else stop.
Part B  clean fit at N0 250 and 50 (scored 50 v 250 by the pit_fit_audit rule). Scoring input for 2027 stays the shipped one: its models never saw 2027.
Part C  fa_rank_blend's rate blend grid and multi-year fits for starters and relievers, with our rate held out on the clean fit.
Usage: PYTHONHASHSEED=0 python3 scripts/research/projection/pit_clean_project.py
Output: console + data/_proj/_pit_clean_project.json
"""
import csv, json, os, pickle, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import contextlib, io
with contextlib.redirect_stdout(io.StringIO()):
    import pit_fit_audit as A
T = A.T; pr = A.pr; pst = A.pst; ph = T.ph
import fa_rank_blend as B
P = T.P; H1 = T.H1; par = T.par; S = T.S; Bs = A.Bs
meta = json.load(open(os.path.join(T.ROOT, 'data', 'metadata_rs.json'))); wc = meta['eraPlusConstants']['war']; rpw = meta['hwarConstants']['rpw']; lg = wc['lgRA9']
stuff27 = dict(T.FILE); stuff27['2026'] = json.load(open(os.path.join(P, 'stuff_2026_loso.json')))
BASE = 2026; RK = {1: 1.0, 3: .70, 5: .40}


def fit(kind, n0):
    X = []; Y = []; W = []
    for b in Bs:
        m = A.M(b, kind, n0, (), 'ra9'); X.append(m[0]); Y.append(m[1]); W.append(m[2])
    X = np.vstack(X); Y = np.concatenate(Y); W = np.concatenate(W); off = X[:, -1]
    D_ = np.column_stack([np.ones(len(X)), X[:, :-1]]); sw = np.sqrt(W)
    return np.linalg.lstsq(D_ * sw[:, None], (Y - off) * sw, rcond=None)[0]


def score(beta, n0, gs):
    pids = set().union(*[set(S[BASE - k]) for k in range(3)])
    fake = []
    for pid in pids:
        hist = [S[BASE - k].get(pid) for k in range(3)]; k0 = next(k for k, x in enumerate(hist) if x)
        fake.append((pid, {'age': hist[k0]['age'] + k0 + 1, 'gs': gs, 'ra9': 0.0, 'fip': 0.0, 'ip': 1.0}, hist))
    Xp, _, _ = ph.feats(fake, 1, *par); c = pst.stuff_channel(fake, BASE + 1, stuff27, H1['d'], n0)[0]
    ex = np.array([1 / (1 + sum(h['bf'] for h in hist if h) / 20) for _, _, hist in fake])
    pk = []; ev = []
    for pid, _, hist in fake:
        n = d = 0.0
        for k, h in enumerate(hist):
            if h:
                n += par[0] ** k * h['bf'] * T.peff(BASE - k, T._club[BASE - k].get(pid)); d += par[0] ** k * h['bf']
        pk.append((n / d if d else 0.0, 0.0)); n = d = 0.0
        for k in range(3):
            r = T.EVT[BASE - k].get(int(pid))
            if r:
                n += par[0] ** k * r[1] * (r[0] - T.EVL[BASE - k]); d += par[0] ** k * r[1]
        ev.append(n / (d + 100))
    Z = np.column_stack([np.ones(len(fake)), Xp[:, :-1], c, ex, np.array(pk), ev])
    l1 = Z @ beta + Xp[:, -1]
    out = {}
    for (pid, t, _), v in zip(fake, l1):
        rec = {}
        for h in (1, 3, 5):
            a1, aT = t['age'], t['age'] + h - 1
            young = H1['yi'] * (min(aT, H1['peak']) - min(a1, H1['peak']))
            rec[h] = lg + RK[h] * float(v) - young
        out[int(pid)] = rec
    return out


ship = {int(r['mlbId']): r for r in csv.DictReader(open(os.path.join(P, 'projections_pitchers.csv')))}
b0 = fit('FILE', 250); sp0 = score(b0, 250, 1.0)
gap = [abs(sp0[i][1] - float(ship[i]['RA9_SP_2027'])) for i in sp0 if i in ship and ship[i].get('RA9_SP_2027')]
gap3 = [abs(sp0[i][3] - float(ship[i]['RA9_SP_2029'])) for i in sp0 if i in ship and ship[i].get('RA9_SP_2029')]
print(f'control: FILE fit v shipped RA9, n {len(gap)}, max gap 2027 {max(gap):.3f}, 2029 {max(gap3):.3f}')
if max(gap) > .011:
    raise SystemExit('control failed: code does not reproduce the shipped projection')
n50, d = A.cmp(A.run('CLEAN', 50, (), 'ra9')[0], A.run('CLEAN', 250, (), 'ra9')[0], 'ra9'); print('N0 50 v 250, RA9:', n50)
n50f, d = A.cmp(A.run('CLEAN', 50, (), 'fip')[0], A.run('CLEAN', 250, (), 'fip')[0], 'fip'); print('N0 50 v 250, FIP:', n50f)
out = {'FILE_coef': b0.tolist()}
for n0 in (250, 50):
    bc = fit('CLEAN', n0); out[f'CLEAN_{n0}_coef'] = bc.tolist()
    print(f'coefs [const ra9 fip kbb xw gs stuff exp parkH parkT ev] FILE: ' + ' '.join(f'{x:.3f}' for x in b0)); print(f'                CLEAN {n0}: ' + ' '.join(f'{x:.3f}' for x in bc))
    out[f'sp_{n0}'] = {str(k): v for k, v in score(bc, n0, 1.0).items()}; out[f'rp_{n0}'] = {str(k): v for k, v in score(bc, n0, 0.0).items()}
json.dump(out, open(os.path.join(P, '_pit_clean_project.json'), 'w'), default=float)

# Part C: rate blends on the clean held-out rate
preds = A.run('CLEAN', 250, (), 'ra9')[0]
P_ = {}
for b in Bs:
    P_[b + 1] = {int(pid): float(v) for (pid, _, _), v in zip(A.D[b][0], preds[b])}
rows = pickle.load(open(os.path.join(P, '_fa_upside_rows.pkl'), 'rb'))
HB = B.HB; ch = 0
for r in rows:
    if r['group'] == 'H':
        continue
    rep = HB.REPL_SP if r['group'] == 'SP' else HB.REPL_RP
    if r['hp_rate'] is not None:
        if r['T'] in P_ and r['pid'] in P_[r['T']]:
            r['hp_rate_old'] = r['hp_rate']; r['hp_rate'] = (-P_[r['T']][r['pid']] / HB.RPW + rep) / 9; ch += 1
        else:
            r['hp_rate'] = None
print('rows with the clean rate', ch)
FA = B.fa_class(); res = {'part1': {}, 'part3': {}}
FIX = {'SP': (.5, .5, 0), 'RP': (.5, 0, .5)}
for g in ('SP', 'RP'):
    G_ = [r for r in rows if r['group'] == g]
    got = B.part1(G_, (2018, 2019, 2021, 2022, 2023, 2024, 2025), g, res['part1'])
    pool = got[1]
    Y_ = {T_: np.array([r['y1'] for r in R]) for T_, R in pool.items()}
    def tot(w): return {T_: np.array([B.blend_rate(r, w) * r['pt'] for r in R]) for T_, R in pool.items()}
    for w, w2, lab in ((.5, .5, 0), (1, 0, 0), 'even ours+Steamer v ours'), ((0, 1, 0), (.5, .5, 0), 'Steamer v even ours+Steamer'), ((.5, 0, .5), (.5, .5, 0), 'ours+ZiPS v ours+Steamer'), ((.5, 0, .5), (1, 0, 0), 'ours+ZiPS v ours'):
        w = tuple(float(x) for x in w); w2 = tuple(float(x) for x in w2)
        gp, se, wi, n = B.paired_gap(tot(w), tot(w2), Y_); print(f'  {lab}: gap {gp:+.3f} (SE {se:.3f}) wins {wi}/{n} -> {B.verdict(gp, se, wi, n, "first", "second")}')
    w = FIX[g]
    for h in (3, 5):
        B.part3(G_, (2018, 2019, 2021, 2022, 2023, 2024, 2025), h, w, g, FA, res['part3'])
json.dump(res, open(os.path.join(P, '_pit_clean_blend.json'), 'w'), default=float, indent=1)
print('done')
