"""dd_follow.py - follow-ups: t10b launch-angle floor sweep for the EV95 ingredient; t16b per-atom n0 at
production sample size (first n PA -> rest of season); t17 the two survivors combined.
.venv/bin/python scripts/research/hitter/deep_dive/dd_follow.py [t10b t16b t17]"""
import sys, os
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dd_lib as L

AT = L.all_atoms()
RES = {}


def neutral2(e):
    """SD raw, mix-neutral over zone x two-strike flag."""
    e = e[e.sd_el]
    s2 = (e.s == 2).astype(int)
    lgw = e.groupby(['zone', s2], observed=True).size() / len(e)
    hm = e.groupby(['bid', 'zone', s2], observed=True).dv.mean().rename('m').reset_index()
    hm['w'] = pd.MultiIndex.from_frame(hm[['zone', 's']]).map(lgw).values.astype(float)
    return (hm.m * hm.w).groupby(hm.bid).sum() / hm.w.groupby(hm.bid).sum()


def ev95_win(b, lo, hi=91, minn=8):
    x = b[b.ev.notna() & (b.la >= lo) & (b.la < hi)]; g = x.groupby('bid', observed=True).ev
    q = g.quantile(.95); n = g.size(); return q[n >= minn]


def bb_from(A, ev, w=0.4, gate=30):
    """prior-free BB raw with a replacement EV statistic (live beta, own pool)."""
    pool = A[(A.nbip >= gate) & A.xwcon.notna() & ev.reindex(A.index).notna()]
    e = ev.reindex(A.index)
    lgx = L.lg_mean(pool.xwcon, pool.nbip); lge = float((e[pool.index] * pool.nbip).sum() / pool.nbip.sum())
    con = 100 * A.xwcon / lgx; evp = 100 * e / lge; g = pool[pool.nbip >= min(80, max(gate, 30))]
    x, y = evp[g.index], con[g.index]; beta = float(((x - x.mean()) * (y - y.mean())).sum() / ((x - x.mean()) ** 2).sum())
    return (1 - w) * con + w * (100 + (evp - 100) * beta)


def t10b():
    print("\n=== T10b EV95 over balls at or above a launch-angle floor (and windows): sweep ===")
    BIPS = {}
    for Y in L.SEASONS:
        d = L.load(Y)['df']; BIPS[Y] = d[d.bip][['bid', 'date', 'xw', 'ev', 'la', 'wv']].copy(); L.drop(Y)
    HALF = {}
    for Y in L.SEASONS:
        b = BIPS[Y]; dates = np.array(sorted(b.date.unique()))
        for seed in range(3):
            rng = np.random.default_rng(31 * seed + Y); hs = set(rng.choice(dates, len(dates) // 2, replace=False)); m = b.date.isin(hs)
            HALF[(Y, seed)] = (b[m], b[~m])

    def simple(b):
        g = b.groupby('bid', observed=True); return pd.DataFrame({'nbip': g.size(), 'xwcon': g.xw.mean(), 'wcon': g.wv.mean(), 'la': g.la.mean()})
    HS = {k: (simple(a), simple(b)) for k, (a, b) in HALF.items()}
    print(" floor/window | split-half r with other-half ACTUAL wOBAcon (d vs all-ball EV95, SE, wins/18) | LA bias | DESC300 d (wins) | DESC100 d | PRED d (wins) | share of pool hitters kept")
    grid = [(-91, 91), (-10, 91), (0, 91), (5, 91), (8, 91), (10, 91), (12, 91), (15, 91), (20, 91), (25, 91), (10, 40), (10, 50), (5, 40), (8, 32), (15, 45)]
    for lo, hi in grid:
        F = []
        for (Y, seed), (a, b) in HALF.items():
            A, B = HS[(Y, seed)]; k = A.index[A.nbip >= 50].intersection(B.index[B.nbip >= 50])
            base = bb_from(A, ev95_win(a, -91), gate=20).reindex(k); var = bb_from(A, ev95_win(a, lo, hi), gate=20).reindex(k)
            F.append(dict(a=base.values, b=var.values, y=B.wcon[k].values, w=np.ones(len(k)), la=A.la[k].values, yx=B.xwcon[k].values))
        res = L.paired(F, lambda f: f['a'], lambda f: f['b'], n_boot=150)
        bias = []
        for f in F:
            m = np.isfinite(f['b']) & np.isfinite(f['yx']); c = np.polyfit(f['b'][m], f['yx'][m], 1); bias.append(L.wcorr(f['yx'][m] - np.polyval(c, f['b'][m]), f['la'][m]))
        var = {Y: bb_from(AT[Y][0], ev95_win(BIPS[Y], lo, hi)) for Y in L.SEASONS}
        kept = np.mean([var[Y][AT[Y][0].ok].notna().mean() for Y in L.SEASONS])
        d3 = L.paired(L.var_folds(AT, 'bb', var, None, 'DESC', 300), lambda f: f['base'], lambda f: f['var'], n_boot=150)
        d1 = L.paired(L.var_folds(AT, 'bb', var, None, 'DESC', 100), lambda f: f['base'], lambda f: f['var'], n_boot=150)
        pr = L.paired(L.var_folds(AT, 'bb', var, None, 'PRED', 200), lambda f: f['base'], lambda f: f['var'], n_boot=150)
        print(f" [{lo:4d},{hi:3d}) | {res['rb']:.4f} d {res['d']:+.4f} (SE {res['se']:.4f}) {res['wins']}/18 | {np.mean(bias):+.3f} | {d3['d']:+.4f} (SE {d3['se']:.4f}) {d3['wins']}/6 | {d1['d']:+.4f} {d1['wins']}/6 | {pr['d']:+.4f} (SE {pr['se']:.4f}) {pr['wins']}/5 | {kept:.3f}", flush=True)
        RES[f't10b {lo},{hi}'] = dict(split=res, bias=float(np.mean(bias)), desc300=d3, desc100=d1, pred=pr)
    print("--- EV weight re-swept at the floor 10 (split-half outcome r / PRED composite r) ---")
    for w in (.2, .3, .4, .5, .6):
        F = []
        for (Y, seed), (a, b) in HALF.items():
            A, B = HS[(Y, seed)]; k = A.index[A.nbip >= 50].intersection(B.index[B.nbip >= 50]); F.append((bb_from(A, ev95_win(a, 10), w=w, gate=20).reindex(k).values, B.wcon[k].values))
        var = {Y: bb_from(AT[Y][0], ev95_win(BIPS[Y], 10), w=w) for Y in L.SEASONS}
        pr = L.paired(L.var_folds(AT, 'bb', var, None, 'PRED', 200), lambda f: f['base'], lambda f: f['var'], n_boot=50)
        print(f"   w_ev {w}: split-half {np.mean([L.wcorr(x, y) for x, y in F]):.4f} | PRED {pr['rb']:.4f}")


def t16b():
    print("\n=== T16b shrinkage constants at production sample size: first n PA -> rest-of-season raw atom ===")
    from dd_process import first_n
    grids = dict(con=[0, 30, 60, 100, 130, 180, 250, 400], evc=[0, 5, 10, 20, 40, 80], sd=[0, 60, 120, 190, 260, 350, 500, 800], ct=[0, 20, 40, 66, 100, 150, 250, 400])
    acc = {(a, n, g): [] for a in grids for n in (50, 100, 200) for g in grids[a]}
    slo = {(a, n, g): [] for a in grids for n in (50, 100, 200) for g in grids[a]}
    for Y in L.SEASONS:
        S = L.load(Y); d = S['df']
        for n in (50, 100, 200):
            pa = d[d.wd == 1].groupby(['bid', 'date'], observed=True).size().rename('k').reset_index().sort_values(['bid', 'date']); pa['cum'] = pa.groupby('bid').k.cumsum()
            tot = pa.groupby('bid').k.sum(); cut = pa[pa.cum >= n].groupby('bid').date.first(); cut = cut[(tot.reindex(cut.index) - n) >= 200]
            c = d.bid.map(cut); E = L.add_plus(L.atoms(d[c.notna() & (d.date <= c)], S['lgz']), anc=AT[Y][1]); R = L.add_plus(L.atoms(d[c.notna() & (d.date > c)], S['lgz']), anc=AT[Y][1])
            k = E.index.intersection(R.index); E, R = E.loc[k], R.loc[k]; anc = AT[Y][1]
            for a, col, ncol, lg, rmin in (('con', 'con', 'nbip', 100.0, 100), ('evc', 'evc', 'nbip', 100.0, 100), ('sd', 'sd_raw', 'n_dec', anc['lsd'], 500), ('ct', 'ct_raw', 'n_sw', anc['lct'], 250)):
                m = E[col].notna() & R[col].notna() & (R[ncol] >= rmin) & (E[ncol] >= 5)
                for g in grids[a]:
                    sh = (E.loc[m, ncol] * E.loc[m, col] + g * lg) / (E.loc[m, ncol] + g)
                    acc[(a, n, g)].append(L.wcorr(sh, R.loc[m, col])); slo[(a, n, g)].append(float(np.polyfit(sh - lg, R.loc[m, col] - lg, 1)[0]))
        L.drop(Y)
    ship = dict(con=130, evc=0, sd=190, ct=66)
    for a in grids:
        print(f"{a} (shipped n0 {ship[a]}): r with the rest-of-season raw atom | slope of rest on shrunk (1.0 = calibrated)")
        for n in (50, 100, 200):
            print(f"   first {n:3d} PA: " + " ".join(f"{g}:{np.mean(acc[(a, n, g)]):.4f}|{np.mean(slo[(a, n, g)]):.2f}" for g in grids[a]))
        RES['t16b ' + a] = {f'{n}/{g}': (float(np.mean(acc[(a, n, g)])), float(np.mean(slo[(a, n, g)]))) for n in (50, 100, 200) for g in grids[a]}


def t17():
    print("\n=== T17 the two survivors together: SD mix-neutral over zone x two-strike, EV95 on balls at LA >= 10 ===")
    V = {'sd2': {}, 'bbair': {}}
    HF = []
    for Y in L.SEASONS:
        S = L.load(Y); d = S['df']; A = AT[Y][0]
        V['sd2'][Y] = neutral2(d); V['bbair'][Y] = bb_from(A, ev95_win(d[d.bip], 10))
        dates = np.array(sorted(d.date.unique()))
        for seed in range(2):
            rng = np.random.default_rng(7 * seed + Y); hs = set(rng.choice(dates, len(dates) // 2, replace=False)); m = d.date.isin(hs)
            a = L.add_plus(L.atoms(d[m], S['lgz'])); b = L.atoms(d[~m], S['lgz'])
            a['sd2'] = neutral2(d[m]); a['bbair'] = bb_from(a, ev95_win(d[m & d.bip], 10), gate=20)
            k = a.index[a.ok.values & (a.pa >= 150).values].intersection(b.index[b.pa >= 150]); a = a.loc[k]
            q = a.pa >= a.pa.quantile(.5)
            z = lambda v: ((v - v[q].mean()) / v[q].std()).values
            HF.append(dict(base=L.W[0] * z(a.bb_raw) + L.W[1] * z(a.sd_raw) + L.W[2] * z(a.ct_raw), sd=L.W[0] * z(a.bb_raw) + L.W[1] * z(a.sd2) + L.W[2] * z(a.ct_raw),
                           bb=L.W[0] * z(a.bbair) + L.W[1] * z(a.sd_raw) + L.W[2] * z(a.ct_raw), both=L.W[0] * z(a.bbair) + L.W[1] * z(a.sd2) + L.W[2] * z(a.ct_raw),
                           y=b.woba[k].values, w=np.ones(len(k))))
        L.drop(Y)
    print("split-half: composite on half A -> ACTUAL wOBA on half B (150+ PA each half; 6 seasons x 2 seeds)")
    for nm in ('sd', 'bb', 'both'):
        print(f"   {nm:5s} {L.fmt(L.paired(HF, lambda f: f['base'], lambda f, nm=nm: f[nm], n_boot=200))}")

    def folds(mode, mp):
        F = []
        for Y in (L.SEASONS if mode == 'DESC' else [p[0] for p in L.PAIRS]):
            A = AT[Y][0]; a = A[A.ok & (A.pa >= mp)]; q = a.pa >= L.QUAL_PA
            sdv, bbv = V['sd2'][Y].reindex(a.index), V['bbair'][Y].reindex(a.index)
            if mode == 'PRED':
                sdv = (a.n_dec * sdv + L.N0['sd'] * np.average(sdv[sdv.notna()], weights=a.n_dec[sdv.notna()])) / (a.n_dec + L.N0['sd'])
                y = AT[Y + 1][0].woba.reindex(a.index).values; w = AT[Y + 1][0].pa.reindex(a.index).fillna(0).values; zb0, zs0, zc0 = L._zq(a.bb_raw, q), a.zs_sd, a.zs_ct
            else:
                y, w = a.woba.values, np.ones(len(a)); zb0, zs0, zc0 = a.z_bb, a.z_sd, a.z_ct
            zb, zs = L._zq(bbv, q), L._zq(sdv, q)
            F.append(dict(base=(L.W[0] * zb0 + L.W[1] * zs0 + L.W[2] * zc0).values, both=(L.W[0] * zb + L.W[1] * zs + L.W[2] * zc0).values, zb=zb.values, zs=zs.values, zc=np.asarray(zc0), y=y, w=w, A=a))
        return F
    for mode, mp in (('DESC', 300), ('DESC', 100), ('PRED', 200)):
        F = folds(mode, mp); print(f"   both, {mode} pa>={mp}: {L.fmt(L.paired(F, lambda f: f['base'], lambda f: f['both']))}")
        RES[f't17 {mode}{mp}'] = L.paired(F, lambda f: f['base'], lambda f: f['both'], n_boot=100)
        if mode == 'DESC' and mp == 300 or mode == 'PRED':
            best = None
            for wb in np.arange(.44, .62, .01):
                for ws in np.arange(.10, .28, .01):
                    r = np.mean([L.wcorr(wb * f['zb'] + ws * f['zs'] + (1 - wb - ws) * f['zc'], f['y'], f['w']) for f in F])
                    if best is None or r > best[0]:
                        best = (float(r), round(wb, 2), round(ws, 2), round(1 - wb - ws, 2))
            r0 = np.mean([L.wcorr(f['both'], f['y'], f['w']) for f in F])
            print(f"      weights re-swept on the new atoms ({mode}): best r {best[0]:.4f} at {best[1]}/{best[2]}/{best[3]}; at 52/17/31 {r0:.4f}")
    # within-hand read and 2026 movers
    F = folds('DESC', 300); wh = {'base': [], 'both': []}
    for f in F:
        a = f['A']; hand = np.where(a.bats_L > .9, 'L', np.where(a.bats_L < .1, 'R', 'S'))
        for key in wh:
            s = f[key].copy(); y = f['y'].copy()
            for h in 'LRS':
                m = hand == h; s[m] -= np.nanmean(s[m]); y[m] -= np.nanmean(y[m])
            wh[key].append(L.wcorr(s, y))
    print(f"   within-hand DESC300 r: shipped {np.mean(wh['base']):.4f}, both {np.mean(wh['both']):.4f}")
    import json
    lb = json.load(open(os.path.join(L.ROOT, 'data', 'hitter_leaderboard_rs.json'))); nm = {str(int(r['mlbId'])): r['hitter'] for r in lb if r.get('mlbId') is not None}
    f = folds('DESC', 200)[-1]; a = f['A']; dlt = pd.Series((f['both'] - f['base']) * 36.0, index=a.index)
    print(f"2026, PA>=200 ({len(a)} hitters): Process+ change in points (36 per z): SD {dlt.std():.1f}, max |change| {dlt.abs().max():.1f}, rank r {pd.Series(f['both']).corr(pd.Series(f['base']), method='spearman'):.4f}")
    t = dlt.sort_values(); print("   fallers:", [(nm.get(i, i), round(float(x), 1)) for i, x in t.head(8).items()]); print("   risers:", [(nm.get(i, i), round(float(x), 1)) for i, x in t.tail(8).items()])
    w = [i for i in a.index if nm.get(i) == 'Wood, James']
    if w:
        print(f"   James Wood change: {float(dlt[w[0]]):+.1f} points")


if __name__ == '__main__':
    which = sys.argv[1:] or ['t10b', 't16b', 't17']
    for t in which:
        globals()[t]()
    L.save('res_follow_' + '_'.join(which) + '.json', RES)
