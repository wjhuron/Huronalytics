"""dd_other.py - deep-dive tests 14-16: xwOBAsp / SACQ / spray-aware outcome table, xwRC+ calibration,
n0 re-measure.  .venv/bin/python scripts/research/hitter/deep_dive/dd_other.py [t14 t15 t16]"""
import sys, os
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dd_lib as L

AT = L.all_atoms()
RES = {}
LA_EDGES = [-999, -10, 0, 5, 10, 15, 20, 25, 30, 35, 40, 50, 999]
EV_EDGES = [0, 70, 80, 85, 90, 95, 100, 105, 110, 200]
B = {}


def bip(Y):
    if Y not in B:
        d = L.load(Y)['df']; b = d[d.bip & d.la.notna() & d.spray.notna() & d.bats.notna()][['bid', 'date', 'xw', 'ev', 'la', 'spray', 'wv', 'bats']].copy()
        b['lab'] = pd.cut(b.la, LA_EDGES, labels=False, right=False)
        b['sp'] = pd.cut(b.spray, [-200, -30, -15, 0, 15, 30, 200], labels=False, right=False)     # 0 = pull ... 5 = oppo
        b['evb'] = pd.cut(b.ev, EV_EDGES, labels=False, right=False)
        b['hand'] = (b.bats == 'L').astype(int)
        b['air'] = b.la >= 20; b['pa_'] = b.air & (b.spray < -15)
        B[Y] = b.reset_index(drop=True); L.drop(Y)
    return B[Y]


def cell_mean(tr, keys, k=0.0, parent=None, minn=0, col='wv'):
    g = tr.groupby(keys, observed=True)[col].agg(['sum', 'size'])
    if parent is not None:
        pk = [c for c in keys if c in parent.index.names]
        pm = parent.reindex(pd.MultiIndex.from_frame(g.reset_index()[pk]) if len(pk) > 1 else g.reset_index()[pk[0]]).values
        v = (g['sum'].values + k * pm) / (g['size'].values + k)
    else:
        v = g['sum'].values / g['size'].values
    out = pd.Series(v, index=g.index)
    return out[g['size'].values >= minn] if minn else out


def look(te, tab, keys):
    return tab.reindex(pd.MultiIndex.from_frame(te[keys])).values if len(keys) > 1 else tab.reindex(te[keys[0]]).values


def predictors(tr, te, sacq_min=20, k3=10):
    """per-BIP predictions on te from tables built on tr."""
    out = {}
    lg = tr.wv.mean()
    hand = cell_mean(tr, ['sp', 'lab', 'hand'], minn=sacq_min); pooled = cell_mean(tr, ['sp', 'lab'], minn=sacq_min)
    v = look(te, hand, ['sp', 'lab', 'hand']); v2 = look(te, pooled, ['sp', 'lab'])
    out['sacq'] = np.where(np.isfinite(v), v, np.where(np.isfinite(v2), v2, lg))
    lah = cell_mean(tr, ['lab', 'hand']); out['la_only'] = look(te, lah, ['lab', 'hand'])
    out['xw'] = te.xw.values
    out['xw+sprayval'] = te.xw.values + out['sacq'] - out['la_only']
    # spray residual patch on Savant xwOBA: mean (actual - xw) by spray x LA x hand, shrunk to 0
    t2 = tr[tr.xw.notna()].assign(res=lambda x: x.wv - x.xw)
    g = t2.groupby(['sp', 'lab', 'hand'], observed=True).res.agg(['sum', 'size']); patch = g['sum'] / (g['size'] + 50)
    out['xw+patch'] = te.xw.values + np.nan_to_num(look(te, patch, ['sp', 'lab', 'hand']))
    share = tr.pa_.sum() / tr.air.sum()
    out['xw+pullair.20'] = te.xw.values + 0.20 * te.air.values * (te.pa_.values - share)
    # EV x LA x spray x hand on OUTCOME wOBA, shrunk to the EV x LA cell
    t3 = tr[tr.evb.notna()]
    p2 = cell_mean(t3, ['evb', 'lab'])
    e3 = cell_mean(t3, ['evb', 'lab', 'sp', 'hand'], k=k3, parent=p2)
    v3 = look(te, e3, ['evb', 'lab', 'sp', 'hand']); vp = look(te, p2, ['evb', 'lab'])
    out['e3'] = np.where(np.isfinite(v3), v3, np.where(np.isfinite(vp), vp, out['sacq']))
    out['evla'] = np.where(np.isfinite(vp), vp, out['la_only'])
    return out


def t14():
    print("\n=== T14 xwOBAsp / SACQ: per-BIP out-of-sample fit to ACTUAL wOBA (table from season A, scored on season B; 30 pairs) ===")
    names = ['la_only', 'sacq', 'evla', 'xw', 'xw+sprayval', 'xw+patch', 'xw+pullair.20', 'e3']
    mse = {n: [] for n in names}
    for A_ in L.SEASONS:
        for B_ in L.SEASONS:
            if A_ == B_:
                continue
            te = bip(B_); P = predictors(bip(A_), te); m = te.xw.notna().values & te.evb.notna().values
            for n in names:
                mse[n].append(float(np.mean((P[n][m] - te.wv.values[m]) ** 2)))
    base = np.array(mse['xw'])
    for n in names:
        v = np.array(mse[n]); print(f"   {n:14s} MSE {v.mean():.5f}  vs Savant xwOBA {100*(v.mean()/base.mean()-1):+.2f}%  better in {int((v < base).sum())}/30")
    RES['t14 mse'] = {n: float(np.mean(v)) for n, v in mse.items()}
    print("--- constants: SACQ minimum BIP per cell (shipped 20) and the E3 shrink k, same objective ---")
    for mn in (0, 5, 10, 20, 50, 100, 200):
        v = []
        for A_ in L.SEASONS:
            for B_ in L.SEASONS:
                if A_ != B_:
                    te = bip(B_); v.append(float(np.mean((predictors(bip(A_), te, sacq_min=mn)['sacq'] - te.wv.values) ** 2)))
        print(f"   SACQ min {mn:3d}: MSE {np.mean(v):.6f}")
    for k3 in (0, 2, 5, 10, 20, 40, 80, 160):
        v = []
        for A_ in L.SEASONS:
            for B_ in L.SEASONS:
                if A_ != B_:
                    te = bip(B_); m = te.xw.notna().values & te.evb.notna().values
                    v.append(float(np.mean((predictors(bip(A_), te, k3=k3)['e3'][m] - te.wv.values[m]) ** 2)))
        print(f"   E3 k {k3:3d}: MSE {np.mean(v):.6f}")
    # SACQ calibration by cell: actual wOBA in season B against the table from A
    rows = []
    for A_, B_ in L.PAIRS:
        te = bip(B_).copy(); te['p'] = predictors(bip(A_), te)['sacq']
        g = te.groupby(['sp', 'lab', 'hand'], observed=True).agg(p=('p', 'mean'), y=('wv', 'mean'), n=('wv', 'size'))
        rows.append((float(np.polyfit(g.p, g.y, 1, w=np.sqrt(g.n))[0]), float(np.sqrt(np.average((g.p - g.y) ** 2, weights=g.n)))))
    print(f"SACQ cell calibration, next season: slope of actual on table {np.mean([r[0] for r in rows]):.3f}, weighted RMS cell error {np.mean([r[1] for r in rows]):.4f} wOBA")
    # hitter level
    print("--- hitter level (150+ BIP): mean of each per-BIP value; tables leave-one-season-out pooled for E3/patch (never the scored season) ---")
    H = {}
    for Y in L.SEASONS:
        tr = pd.concat([bip(y) for y in L.SEASONS if y != Y], ignore_index=True)
        te = bip(Y); P = predictors(tr, te, k3=5)
        own = predictors(te, te)       # production practice for SACQ: same-season table
        df = pd.DataFrame({n: P[n] for n in names}); df['sacq_own'] = own['sacq']; df['bid'] = te.bid.values; df['wv'] = te.wv.values; df['date'] = te.date.values
        H[Y] = df
    cols = ['xw', 'sacq_own', 'sacq', 'xw+sprayval', 'xw+patch', 'xw+pullair.20', 'e3', 'evla']
    same, half, nxt, yyr = {c: [] for c in cols}, {c: [] for c in cols}, {c: [] for c in cols}, {c: [] for c in cols}
    folds_half, folds_nxt = [], []
    for Y in L.SEASONS:
        df = H[Y]; g = df.groupby('bid', observed=True); n = g.size(); keep = n[n >= 150].index
        M = g[cols + ['wv']].mean().loc[keep]
        for c in cols:
            same[c].append(L.wcorr(M[c], M.wv))
        dates = np.array(sorted(df.date.unique())); rng = np.random.default_rng(Y); hs = set(rng.choice(dates, len(dates) // 2, replace=False)); m = df.date.isin(hs)
        a = df[m].groupby('bid', observed=True)[cols + ['wv']].mean(); b = df[~m].groupby('bid', observed=True).wv.agg(['mean', 'size']); na = df[m].groupby('bid', observed=True).size()
        k = a.index[na.reindex(a.index) >= 75].intersection(b.index[b['size'] >= 75])
        for c in cols:
            half[c].append(L.wcorr(a.loc[k, c], b.loc[k, 'mean']))
        folds_half.append({c: a.loc[k, c].values for c in cols} | {'y': b.loc[k, 'mean'].values, 'w': np.ones(len(k))})
    for y0, y1 in L.PAIRS:
        g0 = H[y0].groupby('bid', observed=True); n0 = g0.size(); M0 = g0[cols].mean()[n0 >= 150]
        g1 = H[y1].groupby('bid', observed=True); M1 = g1.wv.agg(['mean', 'size']); X1 = g1[cols].mean()
        k = M0.index.intersection(M1.index[M1['size'] >= 50])
        for c in cols:
            nxt[c].append(L.wcorr(M0.loc[k, c], M1.loc[k, 'mean'], M1.loc[k, 'size'])); yyr[c].append(L.wcorr(M0.loc[k, c], X1.loc[k, c], M1.loc[k, 'size']))
        folds_nxt.append({c: M0.loc[k, c].values for c in cols} | {'y': M1.loc[k, 'mean'].values, 'w': M1.loc[k, 'size'].values})
    print(" metric | same-season r with actual wOBAcon | half A -> half B actual wOBAcon | Y -> Y+1 actual wOBAcon | own year-to-year r")
    for c in cols:
        print(f"   {c:14s} {np.mean(same[c]):.4f} | {np.mean(half[c]):.4f} | {np.mean(nxt[c]):.4f} | {np.mean(yyr[c]):.4f}")
    for c in ('xw+patch', 'xw+pullair.20', 'e3', 'xw+sprayval'):
        print(f"   paired vs Savant xwOBAcon, {c}: half {L.fmt(L.paired(folds_half, lambda f: f['xw'], lambda f, c=c: f[c], n_boot=200))}")
        print(f"   {'':30s} next {L.fmt(L.paired(folds_nxt, lambda f: f['xw'], lambda f, c=c: f[c], n_boot=200))}")
    RES['t14 hitter'] = {c: dict(same=float(np.mean(same[c])), half=float(np.mean(half[c])), nxt=float(np.mean(nxt[c])), yy=float(np.mean(yyr[c]))) for c in cols}


def t15():
    print("\n=== T15 xwRC+ input calibration: actual wOBA on xwOBA with the pulled-air term (C swept) ===")
    PA = {}
    for Y in L.SEASONS:
        d = L.load(Y)['df']; pa = d[d.wd == 1]
        xv = np.where(pa.bip.values & pa.xw.notna().values, pa.xw.values, pa.wv.values)
        air = (pa.bip & (pa.la >= 20)).values; pull = air & (pa.spray < -15).values
        g = pd.DataFrame({'bid': pa.bid.values, 'xv': xv, 'air': air, 'pull': pull, 'wv': pa.wv.values}).groupby('bid', observed=True)
        T = g.agg(pa=('wv', 'size'), woba=('wv', 'mean'), xsum=('xv', 'sum'), n_air=('air', 'sum'), n_pull=('pull', 'sum'))
        T['share'] = T.n_pull.sum() / T.n_air.sum(); PA[Y] = T; L.drop(Y)
    print(" C | r with same-season wOBA, pa>=300 (per season) | slope of actual on expected | next-season r (gate Y pa>=200, weights Y+1 PA)")
    for C in (0, .05, .10, .15, .20, .25, .30, .40):
        rs, sl, nx = [], [], []
        for Y in L.SEASONS:
            T = PA[Y]; x = (T.xsum + C * (T.n_pull - T.share * T.n_air)) / T.pa; q = T.pa >= 300
            rs.append(L.wcorr(x[q], T.woba[q])); sl.append(float(np.polyfit(x[q], T.woba[q], 1)[0]))
        for y0, y1 in L.PAIRS:
            T = PA[y0]; x = (T.xsum + C * (T.n_pull - T.share * T.n_air)) / T.pa; q = T.index[T.pa >= 200]; T1 = PA[y1]
            nx.append(L.wcorr(x[q], T1.woba.reindex(q), T1.pa.reindex(q).fillna(0)))
        print(f" {C:.2f} | {np.mean(rs):.4f} {np.round(rs, 3)} | {np.mean(sl):.3f} {np.round(sl, 2)} | {np.mean(nx):.4f} {np.round(nx, 3)}")
        RES[f't15 C{C}'] = dict(r=rs, slope=sl, nxt=nx)
    print("--- at C = .20: slope by pool, decile calibration, archetype residuals ---")
    C = .20; dec = []; tr = {t: [] for t in ('bats_L', 'gb', 'la', 'k', 'bbr', 'airpull', 'ev95', 'hr')}
    for gate in (150, 300, 502):
        sl = []
        for Y in L.SEASONS:
            T = PA[Y]; x = (T.xsum + C * (T.n_pull - T.share * T.n_air)) / T.pa; q = T.pa >= gate
            sl.append(float(np.polyfit(x[q], T.woba[q], 1)[0]))
        print(f"   slope of actual wOBA on xwOBA_hb, PA>={gate}: {np.mean(sl):.3f} {np.round(sl, 2)}  (shipped cap XWRC_RUN_TRUTH .85 was measured on the qualified pool)")
    for Y in L.SEASONS:
        T = PA[Y]; x = (T.xsum + C * (T.n_pull - T.share * T.n_air)) / T.pa; q = T.pa >= 300
        t = pd.DataFrame({'x': x[q], 'y': T.woba[q]}); t['d'] = pd.qcut(t.x, 10, labels=False)
        dec.append((t.groupby('d').y.mean() - t.groupby('d').x.mean()).values)
        b = np.polyfit(t.x, t.y, 1); res = t.y - np.polyval(b, t.x); A = AT[Y][0]
        for k in tr:
            tr[k].append(L.wcorr(res, A[k].reindex(res.index)))
    print("   actual minus expected by expected-decile (wOBA points, low to high):", np.round(np.mean(dec, axis=0) * 1000, 1))
    print("   residual vs trait (mean r, same-sign seasons):", {k: (round(float(np.mean(v)), 3), int(sum(np.sign(x) == np.sign(np.mean(v)) for x in v))) for k, v in tr.items()})


def t16():
    print("\n=== T16 n0 re-measure per season (split-half by dates, 3 seeds): implied n0 = n_half (1 - r) / r ===")
    rows = []
    for Y in L.SEASONS:
        S = L.load(Y); d = S['df']; dates = np.array(sorted(d.date.unique())); acc = {k: [] for k in ('con', 'sd', 'ct', 'ev95')}
        for seed in range(3):
            rng = np.random.default_rng(17 * seed + Y); hs = set(rng.choice(dates, len(dates) // 2, replace=False)); m = d.date.isin(hs)
            a, b = L.atoms(d[m], S['lgz']), L.atoms(d[~m], S['lgz']); k = a.index.intersection(b.index); a, b = a.loc[k], b.loc[k]
            for nm, col, ncol, fl in (('con', 'xwcon', 'nbip', 40), ('sd', 'sd_raw', 'n_dec', 125), ('ct', 'ct_raw', 'n_sw', 45), ('ev95', 'ev95', 'nbip', 40)):
                mm = (a[ncol] >= fl) & (b[ncol] >= fl); r = L.wcorr(a.loc[mm, col], b.loc[mm, col]); nh = float((a.loc[mm, ncol].mean() + b.loc[mm, ncol].mean()) / 2)
                acc[nm].append((r, nh * (1 - r) / r))
        rows.append({f'{k} r': np.mean([x[0] for x in v]) for k, v in acc.items()} | {f'{k} n0': np.mean([x[1] for x in v]) for k, v in acc.items()}); L.drop(Y)
    T = pd.DataFrame(rows, index=L.SEASONS); print(T.round(3).to_string()); print("mean", T.mean().round(1).to_dict(), "| shipped: BB con 130, SD 190, CT 66, EV95 0")
    RES['t16'] = T.to_dict()


def t16c():
    print("\n=== T16c hitter hWAR batting basis: calibration crossing of the shrink N0 (shipped 77), no park term ===")
    rows = {}
    for Y in L.SEASONS:
        d = L.load(Y)['df']; pa = d[d.wd == 1]
        xv = np.where(pa.bip.values & pa.xw.notna().values, pa.xw.values, pa.wv.values)
        air = (pa.bip & (pa.la >= 20)).values; pull = air & (pa.spray < -15).values
        T = pd.DataFrame({'bid': pa.bid.values, 'xv': xv, 'air': air, 'pull': pull, 'wv': pa.wv.values}).groupby('bid', observed=True).agg(pa=('wv', 'size'), woba=('wv', 'mean'), xsum=('xv', 'sum'), n_air=('air', 'sum'), n_pull=('pull', 'sum'))
        x = (T.xsum + 0.20 * (T.n_pull - T.n_pull.sum() / T.n_air.sum() * T.n_air)) / T.pa; lg = float((x * T.pa).sum() / T.pa.sum()); lgw = float((T.woba * T.pa).sum() / T.pa.sum())
        for n0 in (0, 25, 50, 77, 100, 150, 200, 300):
            sh = (T.pa * x + n0 * lg) / (T.pa + n0); w = T.pa.values
            b = np.polyfit(sh - lg, T.woba - lgw, 1, w=np.sqrt(w))[0]; rows.setdefault(n0, []).append(float(b))
        L.drop(Y)
    for n0, v in rows.items():
        print(f"   N0 {n0:3d}: PA-weighted slope of actual wOBA on the shrunk rate {np.mean(v):.3f} {np.round(v, 2)}")
    RES['t16c'] = rows


def t16d():
    print("\n=== T16d xwOBA3D ROC/AAA fill: MLB table (production bins) applied to AAA balls that carry Savant xwOBA ===")
    import pickle
    EVB = [0, 70, 80, 88, 95, 102, 200]; LAB = [-90, -10, 0, 10, 20, 30, 40, 91]
    def prep(b):
        b = b[b.ev.notna() & b.la.notna() & b.spray.notna() & b.xw.notna()].copy()
        b['e'] = pd.cut(b.ev, EVB, labels=False, right=False); b['l'] = pd.cut(b.la, LAB, labels=False, right=False)
        b['s'] = pd.cut(b.spray, [-200, -30, -15, 0, 15, 30, 200], labels=False, right=False); return b.dropna(subset=['e', 'l', 's'])
    out = {}
    for Y in (2023, 2024, 2025, 2026):
        f = os.path.join(L.ROOT, 'data', f'_aaa_statcast{Y}_cache.pkl')
        a = pickle.load(open(f, 'rb')); a = a[a.description.isin(['hit_into_play', 'hit_into_play_no_out', 'hit_into_play_score'])]
        hp_x, hp_y = 125.42, 198.27
        num = lambda c: pd.to_numeric(a[c], errors='coerce').to_numpy(dtype='float64', na_value=np.nan)
        ang = np.degrees(np.arctan2(num('hc_x') - hp_x, hp_y - num('hc_y'))); ang = np.where((hp_y - num('hc_y')) > 0, ang, np.nan)
        A = pd.DataFrame({'ev': num('launch_speed'), 'la': num('launch_angle'), 'xw': num('estimated_woba_using_speedangle'), 'hand': (a.stand.values == 'L').astype(int)})
        A['spray'] = np.where(A.hand == 1, -ang, ang); A = prep(A)
        d = L.load(Y)['df']; m = d[d.bip][['ev', 'la', 'spray', 'xw', 'bats']].copy(); m['hand'] = (m.bats == 'L').astype(int); M = prep(m); L.drop(Y)
        g3 = M.groupby(['e', 'l', 's', 'hand']).xw.agg(['sum', 'size'])
        mg = [M.groupby(k).xw.mean() for k in (['e', 'l', 'hand'], ['l', 's', 'hand'], ['e', 's', 'hand'])]
        def pred(T, k):
            pr = np.nanmean(np.c_[tuple(mgi.reindex(pd.MultiIndex.from_frame(T[kk])).values for mgi, kk in zip(mg, (['e', 'l', 'hand'], ['l', 's', 'hand'], ['e', 's', 'hand'])))], axis=1)
            c = g3.reindex(pd.MultiIndex.from_frame(T[['e', 'l', 's', 'hand']])); n = np.nan_to_num(c['size'].values); sm = np.nan_to_num(c['sum'].values)
            return (sm + k * pr) / (n + k) if k > 0 else np.where(n > 0, sm / np.maximum(n, 1), pr)
        line = []
        for k in (0, 1, 2, 3, 5, 10, 20, 50, 200):
            p = pred(A, k); line.append((k, float(np.sqrt(np.mean((p - A.xw.values) ** 2))), float(np.corrcoef(p, A.xw.values)[0, 1]), float(np.mean(p - A.xw.values))))
            out.setdefault(k, []).append(line[-1][1])
        el = M.groupby(['e', 'l']).xw.mean().reindex(pd.MultiIndex.from_frame(A[['e', 'l']])).values
        print(f"   {Y}: AAA balls {len(A)}; " + " ".join(f"k{k}: rmse {r:.4f} r {c:.3f} bias {b:+.4f} |" for k, r, c, b in line[:5]) + f" EVxLA-only rmse {np.sqrt(np.nanmean((el - A.xw.values) ** 2)):.4f}")
    print("   mean RMSE by k:", {k: round(float(np.mean(v)), 5) for k, v in out.items()}, "(shipped k 3)")
    RES['t16d'] = out


if __name__ == '__main__':
    which = sys.argv[1:] or ['t14', 't15', 't16']
    for t in which:
        globals()[t]()
    L.save('res_other_' + '_'.join(which) + '.json', RES)
