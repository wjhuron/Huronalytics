"""dd_process.py - deep-dive tests 1-5 (Process+): benchmark, weights within groups, form,
residual + platoon, small sample.  .venv/bin/python scripts/research/hitter/deep_dive/dd_process.py [t1 t2 ...]"""
import sys, os, itertools
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dd_lib as L

RES = {}
AT = L.all_atoms()


def first_n(Y, n, min_rest=150):
    """(atoms on the first n PA [date cut], rest-of-season wOBA, rest PA)."""
    S = L.load(Y); d = S['df']
    pa = d[d.wd == 1].groupby(['bid', 'date'], observed=True).size().rename('n').reset_index().sort_values(['bid', 'date'])
    pa['cum'] = pa.groupby('bid').n.cumsum()
    tot = pa.groupby('bid').n.sum()
    cut = pa[pa.cum >= n].groupby('bid').date.first()
    cut = cut[(tot.reindex(cut.index) - n) >= min_rest]
    c = d.bid.map(cut)
    early = d[c.notna() & (d.date <= c)]; late = d[c.notna() & (d.date > c)]
    A = L.add_plus(L.atoms(early, S['lgz']))
    r = late[late.wd == 1].groupby('bid', observed=True).wv.agg(['mean', 'size'])
    A['y'] = r['mean']; A['w'] = r['size']
    return A[A.w >= min_rest]


def t1():
    print("\n=== T1 benchmark: r with REST-OF-SEASON actual wOBA from the first n PA (weights = rest PA) ===")
    out = {}
    for n in (50, 100, 200, 400):
        rows = []
        for Y in L.SEASONS:
            A = first_n(Y, n)
            A = A[A.ok]
            rows.append({m: L.wcorr(A[m], A.y, A.w) for m in ('proc', 'proc_shr', 'woba', 'xwoba')} | {'n': len(A)})
        T = pd.DataFrame(rows, index=L.SEASONS)
        out[n] = T.mean().to_dict()
        print(f"n={n:3d}: proc {T.proc.mean():.3f}  proc_shr {T.proc_shr.mean():.3f}  wOBA {T.woba.mean():.3f}  xwOBA {T.xwoba.mean():.3f}"
              f"   proc>wOBA {int((T.proc > T.woba).sum())}/6  proc>xwOBA {int((T.proc > T.xwoba).sum())}/6  proc_shr>xwOBA {int((T.proc_shr > T.xwoba).sum())}/6  pool {T.n.mean():.0f}")
        for Y in L.SEASONS:
            L.drop(Y)
    print("\n--- full season Y -> next-season wOBA (gate on Y only: ok and PA>=200; weights = Y+1 PA) ---")
    rows = []
    for (y0, y1) in L.PAIRS:
        A, B = AT[y0][0], AT[y1][0]
        a = A[A.ok & (A.pa >= 200)].copy()
        a['y'] = B.woba.reindex(a.index); a['w'] = B.pa.reindex(a.index).fillna(0)
        surv = float((a.w > 0).mean())
        rows.append({m: L.wcorr(a[m], a.y, a.w) for m in ('proc', 'proc_shr', 'woba', 'xwoba')} | {'surv': surv, 'n': len(a)})
        q = a[(a.pa >= 502) & (a.w >= 502)]
        rows[-1] |= {'q_' + m: L.wcorr(q[m], q.y) ** 2 for m in ('proc', 'woba', 'xwoba')} | {'qn': len(q)}
        aq = A[A.ok & (A.pa >= 502)]
        rows[-1] |= {'same_r2': L.wcorr(aq.proc, aq.woba) ** 2, 'same_r2_x': L.wcorr(aq.xwoba, aq.woba) ** 2}
    T = pd.DataFrame(rows, index=[f"{a}-{b}" for a, b in L.PAIRS])
    print(T.round(3).to_string()); print("mean", T.mean().round(3).to_dict())
    out['next'] = T.mean().to_dict(); RES['t1'] = out


def desc_folds(min_pa):
    F = []
    for Y in L.SEASONS:
        A = AT[Y][0]; a = A[A.ok & (A.pa >= min_pa)]
        F.append(dict(z_bb=a.z_bb.values, z_sd=a.z_sd.values, z_ct=a.z_ct.values, y=a.woba.values, w=np.ones(len(a)), A=a))
    return F


def pred_folds(min_pa=200, shr=True):
    F = []
    pre = 'zs_' if shr else 'z_'
    for (y0, y1) in L.PAIRS:
        A, B = AT[y0][0], AT[y1][0]; a = A[A.ok & (A.pa >= min_pa)]
        w = B.pa.reindex(a.index).fillna(0).values; y = B.woba.reindex(a.index).values
        F.append(dict(z_bb=a[pre + 'bb'].values, z_sd=a[pre + 'sd'].values, z_ct=a[pre + 'ct'].values, y=y, w=w, A=a))
    return F


def comp(w):
    return lambda F: w[0] * F['z_bb'] + w[1] * F['z_sd'] + w[2] * F['z_ct']


GRID = [(b / 100, s / 100, round(1 - b / 100 - s / 100, 2)) for b in range(30, 75, 1) for s in range(5, 36, 1) if 100 - b - s > 5]


def sweep(F):
    return np.array([[L.wcorr(comp(w)(f), f['y'], f['w']) for f in F] for w in GRID])   # grid x folds


def t2():
    print("\n=== T2 weights: simplex sweep (step .01), LOSO, and within-group reads ===")
    out = {}
    for label, F in (('DESC pa>=100', desc_folds(100)), ('DESC pa>=300', desc_folds(300)), ('DESC qualified', desc_folds(502)),
                     ('PRED gateY>=200 shrunk', pred_folds(200, True)), ('PRED gateY>=200 unshrunk', pred_folds(200, False))):
        M = sweep(F); mean = M.mean(axis=1); i = int(mean.argmax()); ship = GRID.index((0.52, 0.17, 0.31))
        flat = [GRID[j] for j in np.where(mean >= mean[i] - 0.001)[0]]
        fb = (min(w[0] for w in flat), max(w[0] for w in flat)); fs = (min(w[1] for w in flat), max(w[1] for w in flat))
        # leave-one-fold-out: pick on the others, score on the held-out fold, against shipped
        ds, picks = [], []
        for k in range(M.shape[1]):
            j = int(np.delete(M, k, axis=1).mean(axis=1).argmax()); picks.append(GRID[j]); ds.append(M[j, k] - M[ship, k])
        res = L.paired(F, comp(L.W), comp(GRID[i]))
        edge = GRID[i][0] in (0.30, 0.74) or GRID[i][1] in (0.05, 0.35)
        print(f"{label}: shipped {mean[ship]:.4f} | argmax {GRID[i][0]:.2f}/{GRID[i][1]:.2f}/{GRID[i][2]:.2f} {mean[i]:.4f} ({'EDGE' if edge else 'interior'})"
              f" | .001-flat bb {fb} sd {fs} | held-out d {np.mean(ds):+.4f} wins {sum(d > 0 for d in ds)}/{len(ds)} | in-sample paired SE {res['se']:.4f}")
        print("    held-out picks:", [f"{p[0]:.2f}/{p[1]:.2f}/{p[2]:.2f}" for p in picks])
        out[label] = dict(ship=float(mean[ship]), argmax=GRID[i], r=float(mean[i]), flat_bb=fb, flat_sd=fs, heldout=float(np.mean(ds)), picks=picks)
    # within-group reads on the descriptive pa>=300 pool and the predictive pool
    print("--- within-group r of the SHIPPED composite (mean over folds); pooled r for reference ---")
    for label, F in (('DESC pa>=300', desc_folds(300)), ('PRED', pred_folds(200, True))):
        rows = {}
        for f in F:
            a = f['A']; s = comp(L.W)(f)
            hand = np.where(a.bats_L > .9, 'L', np.where(a.bats_L < .1, 'R', 'S'))
            pab = pd.cut(a.pa, [0, 300, 450, 2000], labels=['<300', '300-450', '450+']).astype(str).values
            kb = pd.qcut(a.k, 3, labels=['lowK', 'midK', 'highK']).astype(str).values
            pw = pd.qcut(a.z_bb, 3, labels=['lowBB+', 'midBB+', 'highBB+']).astype(str).values
            rows.setdefault('pooled', []).append(L.wcorr(s, f['y'], f['w']))
            for gname, g in (('hand', hand), ('pa', pab), ('K', kb), ('power', pw)):
                # pooled-within: demean score and target inside each group
                sd_, yd_ = s.copy(), np.array(f['y'], float).copy()
                for v in set(g):
                    m = (g == v) & np.isfinite(yd_) & (f['w'] > 0)
                    if m.sum() > 2:
                        sd_[m] -= np.average(sd_[m], weights=f['w'][m]); yd_[m] -= np.average(yd_[m], weights=f['w'][m])
                rows.setdefault('within ' + gname, []).append(L.wcorr(sd_, yd_, f['w']))
                for v in sorted(set(g)):
                    m = g == v
                    rows.setdefault(f'{gname}={v}', []).append(L.wcorr(s[m], np.array(f['y'])[m], f['w'][m]))
        print(label, {k: round(float(np.nanmean(v)), 3) for k, v in rows.items()})
        out['groups ' + label] = {k: float(np.nanmean(v)) for k, v in rows.items()}
        # do the argmax weights differ by group? sweep within hand and within PA band
        for gname in ('hand', 'pa'):
            for v in (('L', 'R') if gname == 'hand' else ('<300', '300-450', '450+')):
                FF = []
                for f in F:
                    a = f['A']
                    g = np.where(a.bats_L > .9, 'L', np.where(a.bats_L < .1, 'R', 'S')) if gname == 'hand' else pd.cut(a.pa, [0, 300, 450, 2000], labels=['<300', '300-450', '450+']).astype(str).values
                    m = g == v
                    if m.sum() >= 25:
                        FF.append({k: (f[k][m] if k != 'A' else None) for k in f})
                if len(FF) < 3:
                    continue
                M = sweep(FF); mean = np.nanmean(M, axis=1); i = int(np.nanargmax(mean)); ship = GRID.index((0.52, 0.17, 0.31))
                print(f"    {label} {gname}={v}: argmax {GRID[i][0]:.2f}/{GRID[i][1]:.2f}/{GRID[i][2]:.2f} r {mean[i]:.4f} vs shipped {mean[ship]:.4f} (d {mean[i]-mean[ship]:+.4f}, folds {len(FF)})")
    RES['t2'] = out


def ols_fit(X, y, w):
    Xw = X * np.sqrt(w)[:, None]; return np.linalg.lstsq(Xw, y * np.sqrt(w), rcond=None)[0]


def t3():
    print("\n=== T3 form: linear vs interaction / quadratic / log-product, fit on the other folds ===")
    forms = {
        'LIN': lambda f: np.c_[f['z_bb'], f['z_sd'], f['z_ct']],
        'LIN+bb*ct': lambda f: np.c_[f['z_bb'], f['z_sd'], f['z_ct'], f['z_bb'] * f['z_ct']],
        'LIN+bb*sd': lambda f: np.c_[f['z_bb'], f['z_sd'], f['z_ct'], f['z_bb'] * f['z_sd']],
        'LIN+sd*ct': lambda f: np.c_[f['z_bb'], f['z_sd'], f['z_ct'], f['z_sd'] * f['z_ct']],
        'LIN+all3x': lambda f: np.c_[f['z_bb'], f['z_sd'], f['z_ct'], f['z_bb'] * f['z_ct'], f['z_bb'] * f['z_sd'], f['z_sd'] * f['z_ct']],
        'LIN+sq': lambda f: np.c_[f['z_bb'], f['z_sd'], f['z_ct'], f['z_bb'] ** 2, f['z_sd'] ** 2, f['z_ct'] ** 2],
        'PLACEBO bb*noise': None,
    }
    out = {}
    for label, F in (('DESC pa>=300', desc_folds(300)), ('DESC pa>=100', desc_folds(100)), ('PRED', pred_folds(200, True))):
        for f in F:
            m = np.isfinite(f['y']) & (f['w'] > 0) & np.isfinite(f['z_bb'] + f['z_sd'] + f['z_ct'])
            for k in ('z_bb', 'z_sd', 'z_ct', 'y', 'w'):
                f[k] = np.asarray(f[k], float)[m]
        rng = np.random.default_rng(1)
        for f in F:
            f['noise'] = rng.permutation(f['z_ct'])
        forms['PLACEBO bb*noise'] = lambda f: np.c_[f['z_bb'], f['z_sd'], f['z_ct'], f['z_bb'] * f['noise']]

        def held(form):
            preds = []
            for k, f in enumerate(F):
                X = np.vstack([np.c_[np.ones(len(g['y'])), forms[form](g)] for j, g in enumerate(F) if j != k])
                y = np.concatenate([g['y'] - np.average(g['y'], weights=g['w']) for j, g in enumerate(F) if j != k])
                w = np.concatenate([g['w'] / g['w'].mean() for j, g in enumerate(F) if j != k])
                b = ols_fit(X, y, w); preds.append(np.c_[np.ones(len(f['y'])), forms[form](f)] @ b)
            return preds
        base = held('LIN')
        for form in forms:
            if form == 'LIN':
                r = np.mean([L.wcorr(p, f['y'], f['w']) for p, f in zip(base, F)])
                rs = np.mean([L.wcorr(comp(L.W)(f), f['y'], f['w']) for f in F])
                print(f"{label}: LIN (refit) {r:.4f}; shipped 52/17/31 {rs:.4f}")
                continue
            pr = held(form)
            FF = [dict(a=a, b=b, y=f['y'], w=f['w']) for a, b, f in zip(base, pr, F)]
            res = L.paired(FF, lambda q: q['a'], lambda q: q['b'])
            print(f"   {form:18s} {L.fmt(res)}"); out[f'{label} {form}'] = res
        # log-product form on the raw ratio atoms
        def logp(f_idx):
            return None
    RES['t3'] = out


def t4():
    print("\n=== T4 residual (actual wOBA minus the Process+ fit): persistence and traits ===")
    R = {}
    for Y in L.SEASONS:
        A = AT[Y][0]; a = A[A.ok & (A.pa >= 250)].copy()
        b = np.polyfit(a.proc, a.woba, 1); a['resid'] = a.woba - np.polyval(b, a.proc)
        bx = np.polyfit(a.xwoba, a.woba, 1); a['resid_x'] = a.woba - np.polyval(bx, a.xwoba)
        a['kbb'] = a.bbr - a.k
        R[Y] = a
    rr, rx, rt = [], [], {}
    traits = ['bats_L', 'la', 'gb', 'airpull', 'pullair_rate', 'k', 'bbr', 'hr', 'chase', 'swing', 'zswing', 'z_bb', 'z_sd', 'z_ct', 'xwoba', 'ev95']
    for (y0, y1) in L.PAIRS:
        k = R[y0].index.intersection(R[y1].index)
        rr.append(L.wcorr(R[y0].resid[k], R[y1].resid[k])); rx.append(L.wcorr(R[y0].resid_x[k], R[y1].resid_x[k]))
    print(f"year-to-year r of the residual: Process+ {np.mean(rr):.3f} {np.round(rr, 2)} | xwOBA residual {np.mean(rx):.3f} {np.round(rx, 2)}")
    for t in traits:
        same = [L.wcorr(R[Y][t], R[Y].resid) for Y in L.SEASONS]
        nxt = [L.wcorr(R[y0][t].reindex(R[y1].index), R[y1].resid) for y0, y1 in L.PAIRS]
        rt[t] = (float(np.mean(same)), float(np.mean(nxt)), int(sum(np.sign(s) == np.sign(np.mean(same)) for s in same)))
    print("trait: r(trait, same-season residual) | r(trait Y, residual Y+1) | same-sign seasons")
    for t, v in sorted(rt.items(), key=lambda kv: -abs(kv[1][0])):
        print(f"   {t:13s} {v[0]:+.3f} | {v[1]:+.3f} | {v[2]}/6")
    # does adding a trait to the composite improve the held-out descriptive r? (fit on other seasons)
    print("--- add one trait to (bb, sd, ct), coefficients fit on the other seasons; DESC pa>=250 and PRED ---")
    out = {}
    for t in ('pullair_rate', 'airpull', 'la', 'gb', 'bbr', 'k', 'kbb', 'bats_L', 'hr'):
        for mode in ('DESC', 'PRED'):
            F = []
            for Y in (L.SEASONS if mode == 'DESC' else [p[0] for p in L.PAIRS]):
                a = R[Y]
                if mode == 'DESC':
                    y, w = a.woba.values, np.ones(len(a))
                else:
                    B = AT[Y + 1][0]; y = B.woba.reindex(a.index).values; w = B.pa.reindex(a.index).fillna(0).values
                tz = L.zc(a[t].fillna(a[t].mean()).values)
                m = np.isfinite(y) & (w > 0)
                F.append(dict(X0=np.c_[a.z_bb, a.z_sd, a.z_ct][m], X1=np.c_[a.z_bb, a.z_sd, a.z_ct, tz][m], y=y[m], w=w[m]))
            P0, P1 = [], []
            for k, f in enumerate(F):
                for key, P in (('X0', P0), ('X1', P1)):
                    X = np.vstack([np.c_[np.ones(len(g['y'])), g[key]] for j, g in enumerate(F) if j != k])
                    y = np.concatenate([g['y'] - np.average(g['y'], weights=g['w']) for j, g in enumerate(F) if j != k])
                    w = np.concatenate([g['w'] / g['w'].mean() for j, g in enumerate(F) if j != k])
                    P.append(np.c_[np.ones(len(f['y'])), f[key]] @ ols_fit(X, y, w))
            res = L.paired([dict(a=a, b=b, y=f['y'], w=f['w']) for a, b, f in zip(P0, P1, F)], lambda q: q['a'], lambda q: q['b'])
            print(f"   +{t:13s} {mode}: {L.fmt(res)}"); out[f'{t} {mode}'] = res
    RES['t4'] = dict(resid_yy=float(np.mean(rr)), resid_x_yy=float(np.mean(rx)), traits=rt, add=out)


def t4b():
    print("\n=== T4b platoon: Process+ split (vs opposite hand minus vs same hand), reliability and ballast ===")
    rows = []
    SP = {}
    for Y in L.SEASONS:
        S = L.load(Y); d = S['df']; anc = AT[Y][1]
        same = d[(d.bats.astype(str) == d.throws.astype(str))]; opp = d[(d.bats.astype(str) != d.throws.astype(str))]
        dates = np.array(sorted(d.date.unique())); rng = np.random.default_rng(Y); hs = set(rng.choice(dates, len(dates) // 2, replace=False))
        out = {}
        for nm, sub in (('same', same), ('opp', opp)):
            for h, hm in (('all', None), ('h1', True), ('h2', False)):
                s2 = sub if hm is None else sub[sub.date.isin(hs) == hm]
                A = L.add_plus(L.atoms(s2, S['lgz']), anc=anc)
                # split floors: a third of the season floors
                okk = (A.nbip >= 15) & (A.n_dec >= 60) & (A.n_sw >= 25)
                A['p'] = L.W[0] * A.z_bb + L.W[1] * A.z_sd + L.W[2] * A.z_ct; A.loc[~okk, 'p'] = np.nan
                out[(nm, h)] = A[['p', 'pa', 'woba', 'bats_L']]
        T = pd.DataFrame({'split': out[('opp', 'all')].p - out[('same', 'all')].p, 'h1': out[('opp', 'h1')].p - out[('same', 'h1')].p,
                          'h2': out[('opp', 'h2')].p - out[('same', 'h2')].p, 'pa_same': out[('same', 'all')].pa, 'pa_opp': out[('opp', 'all')].pa,
                          'wsplit': out[('opp', 'all')].woba - out[('same', 'all')].woba, 'wh1': out[('opp', 'h1')].woba - out[('same', 'h1')].woba,
                          'wh2': out[('opp', 'h2')].woba - out[('same', 'h2')].woba, 'L': out[('opp', 'all')].bats_L})
        T['minpa'] = T[['pa_same', 'pa_opp']].min(axis=1)
        SP[Y] = T; L.drop(Y)
    for hand, hm in (('LHH', lambda T: T.L > .9), ('RHH', lambda T: T.L < .1)):
        for gate in (60, 120):
            sh, shw, yy, yyw, npa, mu, sdv = [], [], [], [], [], [], []
            for Y in L.SEASONS:
                T = SP[Y]; t = T[hm(T) & (T.minpa >= gate)]
                sh.append(L.wcorr(t.h1, t.h2)); shw.append(L.wcorr(t.wh1, t.wh2)); npa.append(t.minpa.mean()); mu.append(t.split.mean()); sdv.append(t.split.std())
            for (y0, y1) in L.PAIRS:
                a, b = SP[y0], SP[y1]; k = a[hm(a) & (a.minpa >= gate)].index.intersection(b[hm(b) & (b.minpa >= gate)].index)
                yy.append(L.wcorr(a.split[k], b.split[k])); yyw.append(L.wcorr(a.wsplit[k], b.wsplit[k]))
            r_h = float(np.nanmean(sh)); r_full = 2 * r_h / (1 + r_h) if r_h > -1 else np.nan
            n0 = np.mean(npa) * (1 - r_full) / r_full if r_full > 0 else float('inf')
            print(f"{hand} min side PA>={gate}: mean split {np.mean(mu):+.3f} z (SD {np.mean(sdv):.3f}); split-half r {r_h:+.3f} -> full {r_full:+.3f}; "
                  f"year-to-year r {np.nanmean(yy):+.3f}; wOBA split: split-half {np.nanmean(shw):+.3f}, y-t-y {np.nanmean(yyw):+.3f}; "
                  f"mean smaller-side PA {np.mean(npa):.0f}; implied ballast (smaller-side PA) {n0:.0f}")
            RES[f't4b {hand} {gate}'] = dict(mean=float(np.mean(mu)), sd=float(np.mean(sdv)), half=r_h, yy=float(np.nanmean(yy)), woba_half=float(np.nanmean(shw)), woba_yy=float(np.nanmean(yyw)), ballast=float(n0))


def t5():
    print("\n=== T5 small sample: split-half noise of unshrunk and shrunk Process (odd/even dates, season anchors) ===")
    import json
    lb = json.load(open(os.path.join(L.ROOT, 'data', 'hitter_leaderboard_rs.json')))
    A26 = AT[2026][0]
    pts = {str(int(r['mlbId'])): r.get('processPlus') for r in lb if r.get('mlbId') is not None and r.get('team') not in ('ROC', 'AAA') and r.get('processPlus') is not None and (r.get('pa') or 0) >= 400}
    k = [b for b in pts if b in A26.index and np.isfinite(A26.loc[b, 'proc'])]
    slope = np.polyfit(A26.loc[k, 'proc'].values, [pts[b] for b in k], 1)[0]
    print(f"points per composite z (2026 leaderboard, {len(k)} rows): {slope:.1f}; r {np.corrcoef(A26.loc[k,'proc'].values,[pts[b] for b in k])[0,1]:.4f}")
    bands = [(50, 100), (100, 150), (150, 200), (200, 300), (300, 400), (400, 502), (502, 900)]
    acc = {b: dict(u=[], s=[], ru=[], rs=[], n=[]) for b in bands}
    for Y in L.SEASONS:
        S = L.load(Y); d = S['df']; anc = AT[Y][1]
        dates = np.array(sorted(d.date.unique()))
        for seed in range(3):
            rng = np.random.default_rng(100 * seed + Y); hs = set(rng.choice(dates, len(dates) // 2, replace=False))
            m = d.date.isin(hs)
            H = []
            for sub in (d[m], d[~m]):
                A = L.add_plus(L.atoms(sub, S['lgz']), anc=anc)
                A['p'] = L.W[0] * A.z_bb + L.W[1] * A.z_sd + L.W[2] * A.z_ct
                A['ps'] = L.W[0] * A.zs_bb + L.W[1] * A.zs_sd + L.W[2] * A.zs_ct
                H.append(A)
            a, b = H; kk = a.index.intersection(b.index)
            a, b = a.loc[kk], b.loc[kk]; hp = (a.pa + b.pa) / 2
            fl = (a.nbip >= 8) & (b.nbip >= 8) & (a.n_dec >= 40) & (b.n_dec >= 40) & (a.n_sw >= 15) & (b.n_sw >= 15)
            for lo, hi in bands:
                mm = fl & (hp >= lo) & (hp < hi)
                if mm.sum() < 20:
                    continue
                acc[(lo, hi)]['u'].append(float(np.nanstd(a.p[mm] - b.p[mm]) / np.sqrt(2))); acc[(lo, hi)]['s'].append(float(np.nanstd(a.ps[mm] - b.ps[mm]) / np.sqrt(2)))
                acc[(lo, hi)]['ru'].append(L.wcorr(a.p[mm], b.p[mm])); acc[(lo, hi)]['rs'].append(L.wcorr(a.ps[mm], b.ps[mm])); acc[(lo, hi)]['n'].append(int(mm.sum()))
        L.drop(Y)
    print("half-sample PA band | SE of one grade, unshrunk (points) | shrunk (points) | split-half r unshrunk | shrunk | n")
    out = {}
    for b in bands:
        v = acc[b]
        if not v['u']:
            continue
        print(f"   {b[0]:3d}-{b[1]:3d} | {np.mean(v['u'])*slope:5.1f} | {np.mean(v['s'])*slope:5.1f} | {np.mean(v['ru']):.3f} | {np.mean(v['rs']):.3f} | {np.mean(v['n']):.0f}")
        out[str(b)] = dict(se_u=float(np.mean(v['u']) * slope), se_s=float(np.mean(v['s']) * slope), r_u=float(np.mean(v['ru'])), r_s=float(np.mean(v['rs'])))
    RES['t5'] = out


if __name__ == '__main__':
    which = sys.argv[1:] or ['t1', 't2', 't3', 't4', 't4b', 't5']
    for t in which:
        globals()[t]()
    L.save('res_process_' + '_'.join(which) + '.json', RES)
