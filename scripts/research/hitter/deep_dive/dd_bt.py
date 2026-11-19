"""dd_bt.py - deep-dive tests 12-13: bat-tracking signals (2024-2026, weak replicates) and the BB+/CT+
bat-tracking priors re-measured with a full 2026.  .venv/bin/python scripts/research/hitter/deep_dive/dd_bt.py [t12 t13]"""
import sys, os
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dd_lib as L
from dd_process import ols_fit

AT = L.all_atoms()
YS = [2024, 2025, 2026]
RES = {}
SW, BP = {}, {}


def prep():
    for Y in YS:
        S = L.load(Y); d = S['df']
        if Y != 2026:
            s = pd.read_pickle(os.path.join(L.ROOT, 'data', f'_bsr_swing_{Y}.pkl')); s = s[s.bat_speed.notna()]
            key = s.batter.astype(str) + '|' + s.game_date.astype(str).str[:10] + '|' + s.plate_x.astype('float32').round(2).astype(str) + '|' + s.plate_z.astype('float32').round(2).astype(str) + '|' + s.release_speed.astype('float32').round(1).astype(str)
            s = s.assign(_k=key.values).drop_duplicates('_k').set_index('_k')
            dk = d.bid.astype(str) + '|' + d.date.astype(str) + '|' + d.px.round(2).astype(str) + '|' + d.pz.round(2).astype(str) + '|' + d.velo.round(1).astype(str)
            d['bs'] = dk.map(s.bat_speed).astype('float32'); d['sl'] = dk.map(s.swing_length).astype('float32')
        sw = d[(d.dec == 'swing') & d.bs.notna() & (d.bs >= 50)][['bid', 'date', 's', 'b', 'bs', 'sl', 'ev', 'velo', 'bip', 'con', 'ct_el', 'lev', 'pwh', 'aa']].copy()
        sw['fast'] = sw.bs >= 75
        m = sw.bip & sw.ev.notna() & sw.velo.notna()
        sw['sq'] = np.where(m, (sw.ev >= 0.8 * (0.212 * sw.velo + 1.23 * sw.bs)).astype(float), np.nan)
        sw['blast'] = np.where(m, ((sw.sq == 1) & (sw.bs >= 75)).astype(float), np.nan)
        SW[Y] = sw
        BP[Y] = d[d.bip][['bid', 'date', 'xw', 'ev']].copy()
        L.drop(Y)
        print(f"{Y}: competitive swings {len(sw)}, hitters {sw.bid.nunique()}", flush=True)


def slope(g, x, y):
    xm = g[x] - g.groupby('bid', observed=True)[x].transform('mean'); ym = g[y] - g.groupby('bid', observed=True)[y].transform('mean')
    return (xm * ym).groupby(g.bid).sum() / (xm * xm).groupby(g.bid).sum()


def traits(sw, Y=None):
    g = sw.groupby('bid', observed=True)
    T = pd.DataFrame({'nsw': g.size(), 'bs': g.bs.mean(), 'fast': g.fast.mean(), 'sl': g.sl.mean(), 'bs_sd': g.bs.std(), 'squp': g.sq.mean(), 'blast': g.blast.mean(),
                      'bs90': g.bs.quantile(.9)})
    T['bs_strk'] = slope(sw, 's', 'bs'); T['sl_strk'] = slope(sw[sw.sl.notna()], 's', 'sl')
    two = sw[sw.s == 2].groupby('bid', observed=True).bs.mean(); T['bs_2s_drop'] = sw[sw.s < 2].groupby('bid', observed=True).bs.mean() - two
    if Y is not None:
        p = pd.read_csv(os.path.join(L.HDD, f'swingpath_{Y}.csv'), encoding='utf-8-sig'); p.index = p['id'].astype(str)
        for c, n in (('attack_angle', 'aa'), ('ideal_attack_angle_rate', 'ideal_aa'), ('attack_direction', 'adir'), ('swing_tilt', 'tilt'),
                     ('avg_intercept_y_vs_batter', 'int_bat'), ('avg_intercept_y_vs_plate', 'int_plate')):
            T[n] = pd.to_numeric(p[c], errors='coerce').reindex(T.index)
    return T


def t12():
    print("\n=== T12 bat-tracking signals, 2024-2026 (3 seasons, 2 pairs: WEAK replicates) ===")
    TR = {Y: traits(SW[Y], Y) for Y in YS}
    names = ['bs', 'fast', 'bs90', 'sl', 'bs_sd', 'squp', 'blast', 'bs_strk', 'sl_strk', 'bs_2s_drop', 'aa', 'ideal_aa', 'adir', 'tilt', 'int_bat', 'int_plate']
    print("trait | y-t-y r (2 pairs) | same-season partial r with wOBA given (bb,sd,ct) [3 seasons] | next-season partial r with wOBA given shrunk atoms [2 pairs] | partial with next BB raw given BB raw | partial with next CT raw given CT raw")

    def part(x, y, C, w=None):
        m = np.isfinite(x) & np.isfinite(y) & np.all(np.isfinite(C), axis=1)
        if w is not None:
            m &= w > 0
        X = np.c_[np.ones(m.sum()), C[m]]; ww = np.ones(m.sum()) if w is None else w[m]
        rx = x[m] - X @ ols_fit(X, x[m], ww); ry = y[m] - X @ ols_fit(X, y[m], ww)
        return L.wcorr(rx, ry, ww)
    for t in names:
        yy, same, nxt, pbb, pct = [], [], [], [], []
        for Y in YS:
            A = AT[Y][0]; a = A[A.ok & (A.pa >= 300)]; T = TR[Y].reindex(a.index); ok = (T.nsw >= 150).values
            same.append(part(T[t].values[ok], a.woba.values[ok], np.c_[a.z_bb, a.z_sd, a.z_ct][ok]))
        for y0 in (2024, 2025):
            A, B = AT[y0][0], AT[y0 + 1][0]; a = A[A.ok & (A.pa >= 300)]; T = TR[y0].reindex(a.index); T1 = TR[y0 + 1].reindex(a.index)
            w = B.pa.reindex(a.index).fillna(0).values; ok = (T.nsw >= 150).values
            k = ok & (T1.nsw >= 150).values; yy.append(L.wcorr(T[t].values[k], T1[t].values[k]))
            nxt.append(part(T[t].values[ok], B.woba.reindex(a.index).values[ok], np.c_[a.zs_bb, a.zs_sd, a.zs_ct][ok], w[ok]))
            pbb.append(part(T[t].values[ok], B.bb_raw.reindex(a.index).values[ok], np.c_[a.bb_raw.values][ok], w[ok]))
            pct.append(part(T[t].values[ok], B.ct_raw.reindex(a.index).values[ok], np.c_[a.ct_raw.values][ok], w[ok]))
        print(f"   {t:11s} {np.nanmean(yy):+.3f} | {np.nanmean(same):+.3f} {np.round(same, 2)} | {np.nanmean(nxt):+.3f} {np.round(nxt, 2)} | {np.nanmean(pbb):+.3f} {np.round(pbb, 2)} | {np.nanmean(pct):+.3f} {np.round(pct, 2)}")
        RES['t12 ' + t] = dict(yy=float(np.nanmean(yy)), same=[float(x) for x in same], nxt=[float(x) for x in nxt], bb=[float(x) for x in pbb], ct=[float(x) for x in pct])
    print("--- held-out gain of adding one trait to (bb, sd, ct): DESC fit on the other 2 seasons; PRED fit on the other pair ---")
    for t in names:
        line = []
        for mode in ('DESC', 'PRED'):
            F = []
            for Y in (YS if mode == 'DESC' else (2024, 2025)):
                A = AT[Y][0]; a = A[A.ok & (A.pa >= 300)]; T = TR[Y].reindex(a.index)
                if mode == 'DESC':
                    y, w = a.woba.values, np.ones(len(a)); Z = np.c_[a.z_bb, a.z_sd, a.z_ct]
                else:
                    B = AT[Y + 1][0]; y = B.woba.reindex(a.index).values; w = B.pa.reindex(a.index).fillna(0).values; Z = np.c_[a.zs_bb, a.zs_sd, a.zs_ct]
                tv = T[t].values; m = np.isfinite(y) & (w > 0) & np.isfinite(tv) & (T.nsw >= 150).values
                F.append(dict(X0=Z[m], X1=np.c_[Z[m], L.zc(tv[m])], y=y[m], w=w[m]))
            P0, P1 = [], []
            for k, f in enumerate(F):
                for key, P in (('X0', P0), ('X1', P1)):
                    X = np.vstack([np.c_[np.ones(len(g['y'])), g[key]] for j, g in enumerate(F) if j != k])
                    yv = np.concatenate([g['y'] - np.average(g['y'], weights=g['w']) for j, g in enumerate(F) if j != k]); wv = np.concatenate([g['w'] / g['w'].mean() for j, g in enumerate(F) if j != k])
                    P.append(np.c_[np.ones(len(f['y'])), f[key]] @ ols_fit(X, yv, wv))
            res = L.paired([dict(a=a_, b=b_, y=f['y'], w=f['w']) for a_, b_, f in zip(P0, P1, F)], lambda q: q['a'], lambda q: q['b'], n_boot=200)
            line.append(f"{mode} d {res['d']:+.4f} (SE {res['se']:.4f}) {res['wins']}/{res['n']}")
        print(f"   +{t:11s} " + " | ".join(line))


def sim_bb(Y, n, min_rem=100):
    """first-n-BIP estimate, bat window to the same date, remainder target (all in season anchors)."""
    b = BP[Y]; anc = AT[Y][1]
    c = b.groupby(['bid', 'date'], observed=True).size().rename('k').reset_index().sort_values(['bid', 'date']); c['cum'] = c.groupby('bid').k.cumsum()
    tot = c.groupby('bid').k.sum(); cut = c[c.cum >= n].groupby('bid').date.first(); cm = b.bid.map(cut)
    e, r = b[cm.notna() & (b.date <= cm)], b[cm.notna() & (b.date > cm)]

    def raw(x):
        g = x.groupby('bid', observed=True); con = 100 * g.xw.mean() / anc['lgx']; evc = 100 + (100 * x[x.ev.notna()].groupby('bid', observed=True).ev.quantile(.95) / anc['lge'] - 100) * anc['beta']
        return pd.DataFrame({'n': g.size(), 'con': con, 'evc': evc})
    E, R = raw(e), raw(r); R = R[R.n >= min_rem]
    sw = SW[Y]; sm = sw.bid.map(cut); se = sw[sm.notna() & (sw.date <= sm)]; T = traits(se)
    k = E.index.intersection(R.index).intersection(T.index)
    E, R, T = E.loc[k], R.loc[k], T.loc[k]
    e0 = 0.6 * (E.n * E.con + 130 * 100) / (E.n + 130) + 0.4 * E.evc
    return pd.DataFrame({'n': E.n, 'e0': e0, 'tgt': 0.6 * R.con + 0.4 * R.evc, 'nsw': T.nsw, 'bs': T.bs, 'squp': T.squp, 'sl': T.sl, 'fast': T.fast}).dropna(subset=['e0', 'tgt', 'bs'])


def t13():
    print("\n=== T13 BB+ bat-tracking prior, call-up simulation (first n BIP -> remainder unshrunk raw); RMSE by season x n ===")
    FULL = {}
    for Y in YS:
        A = AT[Y][0]; T = traits(SW[Y]); p = A[(A.nbip >= 80)].join(T, how='inner'); p = p[p.nsw >= 50]
        FULL[Y] = dict(mean=float(p.bb_raw.mean()), bs=(float(p.bs.mean()), float(p.bs.std())), sq=(float(p.squp.mean()), float(p.squp.std())), sl=(float(p.sl.mean()), float(p.sl.std())), pool=p)
    def zf(Y, col, v):
        key = dict(bs='bs', squp='sq', sl='sl')[col]; return (v - FULL[Y][key][0]) / FULL[Y][key][1]
    # leave-season-out standardized betas on the full-season unshrunk raw
    def fit(excl, cols, hinge=False, quad=False):
        X, y = [], []
        for Y in YS:
            if Y == excl:
                continue
            p = FULL[Y]['pool']; zs = [zf(Y, c, p[c]).values for c in cols]
            if quad:
                zs.append(zs[0] ** 2 - 1)
            if hinge:
                zs.append(np.maximum(zs[0], 0))
            m = np.all(np.isfinite(np.c_[tuple(zs)]), axis=1)
            X.append(np.c_[tuple(zs)][m]); y.append((p.bb_raw.values - FULL[Y]['mean'])[m])
        X = np.vstack(X); y = np.concatenate(y); return np.linalg.lstsq(X, y, rcond=None)[0]
    for Y in YS:
        print(f"   {Y} leave-season-out std betas: bs-only {np.round(fit(Y, ['bs']), 2)}, bs+squp {np.round(fit(Y, ['bs', 'squp']), 2)} (shipped 14.24, 4.97), bs+squp+sl {np.round(fit(Y, ['bs', 'squp', 'sl']), 2)}")
    SIM = {(Y, n): sim_bb(Y, n) for Y in YS for n in (20, 40, 80)}

    def rmse(Y, n, prior_fn, K=20, S0=10):
        s = SIM[(Y, n)]
        if prior_fn is None:
            est = s.e0
        else:
            pr = prior_fn(Y, s); pe = (s.nsw * pr + S0 * 100) / (s.nsw + S0); est = (s.n * s.e0 + K * pe) / (s.n + K)
        return float(np.sqrt(np.mean((est - s.tgt) ** 2)))
    designs = {
        'no prior': None,
        'shipped 14.24/4.97': lambda Y, s: FULL[Y]['mean'] + 14.24 * zf(Y, 'bs', s.bs) + 4.97 * zf(Y, 'squp', s.squp).fillna(0),
        'refit bs+squp': lambda Y, s: FULL[Y]['mean'] + fit(Y, ['bs', 'squp'])[0] * zf(Y, 'bs', s.bs) + fit(Y, ['bs', 'squp'])[1] * zf(Y, 'squp', s.squp).fillna(0),
        'refit bs only': lambda Y, s: FULL[Y]['mean'] + fit(Y, ['bs'])[0] * zf(Y, 'bs', s.bs),
        'refit bs + bs^2': lambda Y, s: FULL[Y]['mean'] + fit(Y, ['bs'], quad=True)[0] * zf(Y, 'bs', s.bs) + fit(Y, ['bs'], quad=True)[1] * (zf(Y, 'bs', s.bs) ** 2 - 1),
        'refit bs + hinge': lambda Y, s: FULL[Y]['mean'] + fit(Y, ['bs'], hinge=True)[0] * zf(Y, 'bs', s.bs) + fit(Y, ['bs'], hinge=True)[1] * np.maximum(zf(Y, 'bs', s.bs), 0),
        'refit bs+squp+sl': lambda Y, s: FULL[Y]['mean'] + fit(Y, ['bs', 'squp', 'sl'])[0] * zf(Y, 'bs', s.bs) + fit(Y, ['bs', 'squp', 'sl'])[1] * zf(Y, 'squp', s.squp).fillna(0) + fit(Y, ['bs', 'squp', 'sl'])[2] * zf(Y, 'sl', s.sl).fillna(0),
    }
    cells = [(Y, n) for Y in YS for n in (20, 40, 80)]
    print("   pools:", {c: len(SIM[c]) for c in cells})
    base = {c: rmse(c[0], c[1], None) for c in cells}; ship = {c: rmse(c[0], c[1], designs['shipped 14.24/4.97']) for c in cells}
    for nm, fn in designs.items():
        v = {c: rmse(c[0], c[1], fn) for c in cells}
        print(f"   {nm:20s} mean RMSE {np.mean(list(v.values())):.3f} | vs no prior: better {sum(v[c] < base[c] for c in cells)}/9 | vs shipped: better {sum(v[c] < ship[c] - 1e-9 for c in cells)}/9 | " + " ".join(f"{v[c]:.2f}" for c in cells))
        RES['t13 bb ' + nm] = {str(c): v[c] for c in cells}
    print("   K sweep (shipped betas, S0 10):", {K: round(float(np.mean([rmse(c[0], c[1], designs['shipped 14.24/4.97'], K=K) for c in cells])), 4) for K in (0, 5, 10, 20, 30, 40, 60, 80, 160)})
    for n in (20, 40, 80):
        print(f"      n={n}:", {K: round(float(np.mean([rmse(Y, n, designs['shipped 14.24/4.97'], K=K) for Y in YS])), 4) for K in (0, 5, 10, 20, 30, 40, 60, 80, 160)})
    print("   S0 sweep (K 20):", {S: round(float(np.mean([rmse(c[0], c[1], designs['shipped 14.24/4.97'], S0=S) for c in cells])), 4) for S in (0, 5, 10, 25, 50, 100)})
    print("   K sweep with refit bs-only:", {K: round(float(np.mean([rmse(c[0], c[1], designs['refit bs only'], K=K) for c in cells])), 4) for K in (0, 5, 10, 20, 30, 40, 60, 80, 160)})

    print("\n=== T13 CT+ bat-tracking prior, call-up simulation (first n swings -> remainder raw CT); RMSE x 100 ===")
    CF = {}
    for Y in YS:
        A = AT[Y][0]; T = traits(SW[Y]); p = A[(A.n_sw >= 200)].join(T, how='inner'); p = p[p.nsw >= 50]
        CF[Y] = dict(lg=AT[Y][1]['lct'], bs=(float(p.bs.mean()), float(p.bs.std())), sl=(float(p.sl.mean()), float(p.sl.std())), pool=p)
    def cfit(excl, cols):
        X, y = [], []
        for Y in YS:
            if Y != excl:
                p = CF[Y]['pool']; X.append(np.c_[tuple(((p[c] - CF[Y][c][0]) / CF[Y][c][1]).values for c in cols)]); y.append(p.ct_raw.values - p.ct_raw.mean())
        return np.linalg.lstsq(np.vstack(X), np.concatenate(y), rcond=None)[0]
    for Y in YS:
        print(f"   {Y} leave-season-out std beta: bs-only {np.round(cfit(Y, ['bs']), 4)} (shipped -0.0421), bs+sl {np.round(cfit(Y, ['bs', 'sl']), 4)}")
    CS = {}
    for Y in YS:
        d = L.load(Y)['df']; s = d[d.ct_el][['bid', 'date', 'lev', 'pwh', 'con']].copy(); L.drop(Y)
        for n in (50, 100, 200):
            c = s.groupby(['bid', 'date'], observed=True).size().rename('k').reset_index().sort_values(['bid', 'date']); c['cum'] = c.groupby('bid').k.cumsum()
            cut = c[c.cum >= n].groupby('bid').date.first(); cm = s.bid.map(cut); e, r = s[cm.notna() & (s.date <= cm)], s[cm.notna() & (s.date > cm)]
            def rc(x):
                x = x[x.lev > 0]; return (x.lev * x.con).groupby(x.bid).sum() / (x.lev * (1 - x.pwh)).groupby(x.bid).sum()
            ne = e.groupby('bid', observed=True).size(); nr = r.groupby('bid', observed=True).size(); sw = SW[Y]; sm = sw.bid.map(cut); T = traits(sw[sm.notna() & (sw.date <= sm)])
            df = pd.DataFrame({'n': ne, 'raw': rc(e), 'tgt': rc(r), 'nr': nr}).join(T[['nsw', 'bs', 'sl']], how='inner'); df = df[(df.nr >= 200)].dropna(subset=['raw', 'tgt', 'bs'])
            CS[(Y, n)] = df
    def crmse(Y, n, beta_fn, K=40, S0=10):
        s = CS[(Y, n)]; lg = CF[Y]['lg']; adj = (s.n * s.raw + 66 * lg) / (s.n + 66)
        if beta_fn is not None:
            pr = lg + beta_fn(Y, s); pe = (s.nsw * pr + S0 * lg) / (s.nsw + S0); adj = (s.n * adj + K * pe) / (s.n + K)
        return float(100 * np.sqrt(np.mean((adj - s.tgt) ** 2)))
    zb = lambda Y, s, c='bs': (s[c] - CF[Y][c][0]) / CF[Y][c][1]
    cd = {'no prior': None, 'shipped -0.0421': lambda Y, s: -0.042082 * zb(Y, s), 'refit bs only': lambda Y, s: cfit(Y, ['bs'])[0] * zb(Y, s),
          'refit bs+sl': lambda Y, s: cfit(Y, ['bs', 'sl'])[0] * zb(Y, s) + cfit(Y, ['bs', 'sl'])[1] * zb(Y, s, 'sl').fillna(0)}
    cells = [(Y, n) for Y in YS for n in (50, 100, 200)]
    print("   pools:", {c: len(CS[c]) for c in cells})
    b0 = {c: crmse(c[0], c[1], None) for c in cells}; sh = {c: crmse(c[0], c[1], cd['shipped -0.0421']) for c in cells}
    for nm, fn in cd.items():
        v = {c: crmse(c[0], c[1], fn) for c in cells}
        print(f"   {nm:18s} mean {np.mean(list(v.values())):.3f} | vs no prior: better {sum(v[c] < b0[c] for c in cells)}/9 | vs shipped: better {sum(v[c] < sh[c] - 1e-9 for c in cells)}/9 | " + " ".join(f"{v[c]:.2f}" for c in cells))
        RES['t13 ct ' + nm] = {str(c): v[c] for c in cells}
    print("   K sweep (shipped beta):", {K: round(float(np.mean([crmse(c[0], c[1], cd['shipped -0.0421'], K=K) for c in cells])), 4) for K in (0, 10, 20, 40, 60, 80, 160, 320)})
    print("   K sweep (refit bs+sl):", {K: round(float(np.mean([crmse(c[0], c[1], cd['refit bs+sl'], K=K) for c in cells])), 4) for K in (0, 10, 20, 40, 60, 80, 160, 320)})


def t13b():
    """bat-speed-only BB prior against the shipped two-term prior, K and S0 by n; and attack angle against the air-EV atom."""
    from dd_follow import bb_from, ev95_win, neutral2
    print("\n=== T13b BB prior: bat speed only (leave-season-out beta) against shipped (14.24, 4.97, K 20, S0 10) ===")
    FULL = {}
    for Y in YS:
        A = AT[Y][0]; T = traits(SW[Y]); p = A[(A.nbip >= 80)].join(T, how='inner'); p = p[p.nsw >= 50]
        FULL[Y] = dict(mean=float(p.bb_raw.mean()), bs=(float(p.bs.mean()), float(p.bs.std())), sq=(float(p.squp.mean()), float(p.squp.std())), pool=p)
    def beta(excl):
        X, y = [], []
        for Y in YS:
            if Y != excl:
                p = FULL[Y]['pool']; X.append(((p.bs - FULL[Y]['bs'][0]) / FULL[Y]['bs'][1]).values); y.append(p.bb_raw.values - FULL[Y]['mean'])
        X = np.concatenate(X); y = np.concatenate(y); return float((X * y).sum() / (X * X).sum())
    SIM = {(Y, n): sim_bb(Y, n) for Y in YS for n in (20, 40, 80)}
    def rm(Y, n, kind, K, S0, bmul=1.0):
        s = SIM[(Y, n)]; zb = (s.bs - FULL[Y]['bs'][0]) / FULL[Y]['bs'][1]
        if kind == 'ship':
            pr = FULL[Y]['mean'] + 14.24 * zb + 4.97 * ((s.squp - FULL[Y]['sq'][0]) / FULL[Y]['sq'][1]).fillna(0)
        else:
            pr = FULL[Y]['mean'] + bmul * beta(Y) * zb
        pe = (s.nsw * pr + S0 * 100) / (s.nsw + S0); est = (s.n * s.e0 + K * pe) / (s.n + K)
        return float(np.sqrt(np.mean((est - s.tgt) ** 2)))
    cells = [(Y, n) for Y in YS for n in (20, 40, 80)]
    ship = {c: rm(c[0], c[1], 'ship', 20, 10) for c in cells}
    print("   shipped by cell:", {c: round(v, 2) for c, v in ship.items()}, "mean", round(float(np.mean(list(ship.values()))), 3))
    print("   bat speed only, K x S0 grid: mean RMSE (cells better than shipped /9)")
    for S0 in (0, 10, 25, 50):
        print(f"      S0 {S0:3d}: " + " ".join(f"K{K}:{np.mean([rm(c[0], c[1], 'bs', K, S0) for c in cells]):.3f}({sum(rm(c[0], c[1], 'bs', K, S0) < ship[c] for c in cells)})" for K in (10, 20, 30, 40, 60, 80, 120, 160, 240)))
    for n in (20, 40, 80):
        print(f"      n={n} (S0 10): " + " ".join(f"K{K}:{np.mean([rm(Y, n, 'bs', K, 10) for Y in YS]):.3f}" for K in (10, 20, 30, 40, 60, 80, 120, 160, 240)))
    print("   beta multiplier at K 60, S0 10:", {m: round(float(np.mean([rm(c[0], c[1], 'bs', 60, 10, m) for c in cells])), 3) for m in (.5, .75, 1.0, 1.25, 1.5, 2.0)})
    print("   shipped two-term, K sweep by n:")
    for n in (20, 40, 80):
        print(f"      n={n}: " + " ".join(f"K{K}:{np.mean([rm(Y, n, 'ship', K, 10) for Y in YS]):.3f}" for K in (10, 20, 30, 40, 60, 80, 120)))
    # full-season invariance: how far the bs-only K 60 prior moves a full-season BB raw
    for Y in YS:
        p = FULL[Y]['pool']; zb = (p.bs - FULL[Y]['bs'][0]) / FULL[Y]['bs'][1]; pr = FULL[Y]['mean'] + beta(Y) * zb
        new = (p.nbip * p.bb_shr + 60 * pr) / (p.nbip + 60); old = (p.nbip * p.bb_shr + 20 * (FULL[Y]['mean'] + 14.24 * zb + 4.97 * ((p.squp - FULL[Y]['sq'][0]) / FULL[Y]['sq'][1]))) / (p.nbip + 20)
        print(f"   {Y} full season (80+ BIP): corr(bs-only K60, shipped) {np.corrcoef(new, old)[0,1]:.4f}, mean |d| {np.mean(np.abs(new - old)):.2f}, max {np.max(np.abs(new - old)):.2f}")
    print("\n=== T12b attack angle and bat speed against the candidate atoms (air EV95, two-strike SD) ===")
    TR = {Y: traits(SW[Y], Y) for Y in YS}
    for Y in YS:
        S = L.load(Y); d = S['df']; A = AT[Y][0]; a = A[A.ok & (A.pa >= 300)]; q = a.pa >= L.QUAL_PA
        bbv = bb_from(A, ev95_win(d[d.bip], 10)).reindex(a.index); L.drop(Y)
        zb = ((bbv - bbv[q].mean()) / bbv[q].std()).values; T = TR[Y].reindex(a.index)
        for nm, Z in (('shipped atoms', np.c_[a.z_bb, a.z_sd, a.z_ct]), ('air-EV BB atom', np.c_[zb, a.z_sd, a.z_ct])):
            out = []
            for t in ('aa', 'bs', 'ideal_aa'):
                x = T[t].values; m = np.isfinite(x) & np.all(np.isfinite(Z), axis=1) & (T.nsw >= 150).values
                X = np.c_[np.ones(m.sum()), Z[m]]; rx = x[m] - X @ np.linalg.lstsq(X, x[m], rcond=None)[0]; ry = a.woba.values[m] - X @ np.linalg.lstsq(X, a.woba.values[m], rcond=None)[0]
                out.append(f"{t} {L.wcorr(rx, ry):+.3f}")
            print(f"   {Y} same-season partial r with wOBA given {nm}: " + ", ".join(out))


if __name__ == '__main__':
    which = sys.argv[1:] or ['t12', 't13']
    prep()
    for t in which:
        globals()[t]()
    L.save('res_bt_' + '_'.join(which) + '.json', RES)
