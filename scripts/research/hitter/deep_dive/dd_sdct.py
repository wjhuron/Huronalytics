"""dd_sdct.py - deep-dive tests 6-9: SD+ validity and in/out-zone split, count mix and pair re-read,
CT+ pitch-quality cells, opponent quality.  .venv/bin/python scripts/research/hitter/deep_dive/dd_sdct.py [t6 ...]"""
import sys, os
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dd_lib as L
from dd_process import ols_fit

AT = L.all_atoms()
RES = {}
IZ = ['heart', 'shadow_in']; OZ = ['shadow_out', 'chase', 'waste']


def held_ols(F, keyA, keyB):
    """fit each design on the other folds, paired r on the held-out fold."""
    P = {keyA: [], keyB: []}
    for k, f in enumerate(F):
        for key in (keyA, keyB):
            X = np.vstack([np.c_[np.ones(len(g['y'])), g[key]] for j, g in enumerate(F) if j != k])
            y = np.concatenate([g['y'] - np.average(g['y'], weights=g['w']) for j, g in enumerate(F) if j != k])
            w = np.concatenate([g['w'] / g['w'].mean() for j, g in enumerate(F) if j != k])
            P[key].append(np.c_[np.ones(len(f['y'])), f[key]] @ ols_fit(X, y, w))
    return L.paired([dict(a=a, b=b, y=f['y'], w=f['w']) for a, b, f in zip(P[keyA], P[keyB], F)], lambda q: q['a'], lambda q: q['b'])


def t6():
    print("\n=== T6 SD+: validity, zone contributions, in-zone / out-of-zone split ===")
    parts = {k: {} for k in ('iz', 'oz', 'r1', 'r2', 'contrib')}
    for Y in L.SEASONS:
        S = L.load(Y); d = S['df']; lgz = S['lgz']
        e = d[d.sd_el]
        parts['iz'][Y] = L.sd_raw(e[e.zone.isin(IZ)], lgz)[0]; parts['oz'][Y] = L.sd_raw(e[e.zone.isin(OZ)], lgz)[0]
        rng = np.random.default_rng(Y); share = float(e.zone.isin(IZ).mean()); m = rng.random(len(e)) < share
        parts['r1'][Y] = L.sd_raw(e[m], lgz)[0]; parts['r2'][Y] = L.sd_raw(e[~m], lgz)[0]
        zm = e.groupby(['bid', 'zone'], observed=True).dv.mean().unstack()
        parts['contrib'][Y] = zm * pd.Series(lgz).reindex(zm.columns)
        L.drop(Y)
    # validity
    rows = []
    for Y in L.SEASONS:
        A = AT[Y][0]; a = A[A.ok & (A.pa >= 300)]
        rows.append({t: L.wcorr(a.sd_raw, a[t]) for t in ('bbr', 'chase', 'zswing', 'swing', 'k', 'woba', 'z_bb', 'z_ct', 'hr')})
    print("same-season r of SD raw with:", pd.DataFrame(rows).mean().round(3).to_dict())
    rows = []
    for y0, y1 in L.PAIRS:
        A, B = AT[y0][0], AT[y1][0]; a = A[A.ok & (A.pa >= 300)]
        rows.append({t: L.wcorr(a.sd_shr, B[t].reindex(a.index), B.pa.reindex(a.index).fillna(0)) for t in ('bbr', 'chase', 'k', 'woba', 'sd_raw')}
                    | {'chase->bbr': L.wcorr(a.chase, B.bbr.reindex(a.index), B.pa.reindex(a.index).fillna(0)),
                       'chase->woba': L.wcorr(a.chase, B.woba.reindex(a.index), B.pa.reindex(a.index).fillna(0))})
    T = pd.DataFrame(rows, index=[f"{a}-{b}" for a, b in L.PAIRS]); print("SD (shrunk) Y vs next-season:"); print(T.round(3).to_string())
    # zone variance shares
    sh = []
    for Y in L.SEASONS:
        A = AT[Y][0]; c = parts['contrib'][Y].reindex(A[A.ok & (A.pa >= 300)].index).fillna(0); tot = c.sum(axis=1)
        sh.append({z: float(np.cov(c[z], tot)[0, 1] / tot.var()) for z in c.columns})
    print("share of SD raw variance by zone (cov share):", pd.DataFrame(sh).mean().round(3).to_dict(), "| league zone weights:", {k: round(v, 3) for k, v in L.load(2025)['lgz'].items()})
    L.drop(2025)
    print("year-to-year r: sd_raw", L.yy({Y: AT[Y][0].sd_raw[AT[Y][0].pa >= 300] for Y in L.SEASONS}), "| in-zone part", L.yy({Y: parts['iz'][Y][AT[Y][0].pa.reindex(parts['iz'][Y].index) >= 300] for Y in L.SEASONS}),
          "| out-zone part", L.yy({Y: parts['oz'][Y][AT[Y][0].pa.reindex(parts['oz'][Y].index) >= 300] for Y in L.SEASONS}))
    out = {}
    for mode in ('DESC', 'PRED'):
        F = []
        for Y in (L.SEASONS if mode == 'DESC' else [p[0] for p in L.PAIRS]):
            A = AT[Y][0]; a = A[A.ok & (A.pa >= 300)]
            if mode == 'DESC':
                y, w = a.woba.values, np.ones(len(a))
            else:
                B = AT[Y + 1][0]; y = B.woba.reindex(a.index).values; w = B.pa.reindex(a.index).fillna(0).values
            cols = {k: L.zc(parts[k][Y].reindex(a.index).fillna(parts[k][Y].reindex(a.index).mean()).values) for k in ('iz', 'oz', 'r1', 'r2')}
            m = np.isfinite(y) & (w > 0)
            base = np.c_[a.z_bb, a.z_sd, a.z_ct]
            F.append(dict(X3=base[m], XIO=np.c_[a.z_bb, cols['iz'], cols['oz'], a.z_ct][m], XR=np.c_[a.z_bb, cols['r1'], cols['r2'], a.z_ct][m],
                          XI=np.c_[a.z_bb, cols['iz'], a.z_ct][m], XO=np.c_[a.z_bb, cols['oz'], a.z_ct][m], y=y[m], w=w[m]))
        for key, nm in (('XIO', 'in + out as two atoms'), ('XR', 'PLACEBO random two-way split'), ('XI', 'in-zone decisions only'), ('XO', 'out-of-zone decisions only')):
            res = held_ols(F, 'X3', key); print(f"   {mode} {nm:30s} {L.fmt(res)}"); out[f'{mode} {key}'] = res
        # pooled weights of the two halves
        X = np.vstack([np.c_[np.ones(len(f['y'])), f['XIO']] for f in F]); y = np.concatenate([f['y'] - np.average(f['y'], weights=f['w']) for f in F]); w = np.concatenate([f['w'] / f['w'].mean() for f in F])
        print(f"   {mode} pooled betas (bb, sd_in, sd_out, ct): {np.round(ols_fit(X, y, w)[1:], 4)}")
    RES['t6'] = out


def t7():
    print("\n=== T7 SD+ count mix; per-pair re-read on full 2026 ===")
    cn, cs = {}, {}
    for Y in L.SEASONS:
        S = L.load(Y); d = S['df']; e = d[d.sd_el]
        # count-neutral, strikes x zone (15 cells) and full count x zone (60 cells), league cell weights
        for name, keys, store in (('strike', ['zone', 's'], cs), ('count', ['zone', 'b', 's'], cn)):
            lgw = e.groupby(keys, observed=True).size() / len(e)
            hm = e.groupby(['bid'] + keys, observed=True).dv.mean().rename('m').reset_index()
            hm['w'] = pd.MultiIndex.from_frame(hm[keys]).map(lgw).values
            store[Y] = (hm.m * hm.w).groupby(hm.bid).sum() / hm.w.groupby(hm.bid).sum()
        L.drop(Y)
    for name, store in (('strikes x zone (15 cells)', cs), ('count x zone (60 cells)', cn)):
        r = [L.wcorr(store[Y].reindex(AT[Y][0].index)[AT[Y][0].ok & (AT[Y][0].pa >= 300)], AT[Y][0].sd_raw[AT[Y][0].ok & (AT[Y][0].pa >= 300)]) for Y in L.SEASONS]
        diff = {Y: (AT[Y][0].sd_raw - store[Y].reindex(AT[Y][0].index))[AT[Y][0].ok & (AT[Y][0].pa >= 300)] for Y in L.SEASONS}
        rk = [L.wcorr(diff[Y], AT[Y][0].k.reindex(diff[Y].index)) for Y in L.SEASONS]; rb = [L.wcorr(diff[Y], AT[Y][0].bbr.reindex(diff[Y].index)) for Y in L.SEASONS]
        vs = [float(diff[Y].var() / AT[Y][0].sd_raw.reindex(diff[Y].index).var()) for Y in L.SEASONS]
        print(f"{name}: r with shipped {np.mean(r):.3f}; count-mix part = {np.mean(vs):.1%} of SD raw variance, y-t-y r {L.yy(diff)[0]:+.3f}, r with K% {np.mean(rk):+.3f}, with BB% {np.mean(rb):+.3f}")
        print(f"   y-t-y r: shipped {L.yy({Y: AT[Y][0].sd_raw[AT[Y][0].pa >= 300] for Y in L.SEASONS})[0]:.3f} vs count-neutral {L.yy({Y: store[Y][AT[Y][0].pa.reindex(store[Y].index) >= 300] for Y in L.SEASONS})[0]:.3f}")
        RES['t7 ' + name] = L.eval_var(AT, 'sd', store, label='count-neutral ' + name.split()[0])
    print("--- per-pair forward r of each shrunk atom with next-season wOBA (gate Y pa>=200, weights Y+1 PA), and atom y-t-y ---")
    rows = []
    for y0, y1 in L.PAIRS:
        A, B = AT[y0][0], AT[y1][0]; a = A[A.ok & (A.pa >= 200)]; w = B.pa.reindex(a.index).fillna(0)
        rows.append({'bb->woba': L.wcorr(a.zs_bb, B.woba.reindex(a.index), w), 'sd->woba': L.wcorr(a.zs_sd, B.woba.reindex(a.index), w), 'ct->woba': L.wcorr(a.zs_ct, B.woba.reindex(a.index), w),
                     'proc->woba': L.wcorr(a.proc_shr, B.woba.reindex(a.index), w), 'sd yy': L.wcorr(a.sd_raw, B.sd_raw.reindex(a.index), w), 'ct yy': L.wcorr(a.ct_raw, B.ct_raw.reindex(a.index), w),
                     'bb yy': L.wcorr(a.bb_raw, B.bb_raw.reindex(a.index), w), 'sd->bbr': L.wcorr(a.zs_sd, B.bbr.reindex(a.index), w)})
    T = pd.DataFrame(rows, index=[f"{a}-{b}" for a, b in L.PAIRS]); print(T.round(3).to_string()); RES['t7 pairs'] = T.to_dict()
    # league table drift: mean |dv| by zone per season (ABS-challenge season check)
    rows = []
    for Y in L.SEASONS:
        d = L.load(Y)['df']; e = d[d.sd_el]
        rows.append((e.sw_rv - e.tk_rv).groupby(e.zone, observed=True).mean().round(4).to_dict() | {'sd_pool_sd': float(AT[Y][0].sd_raw[AT[Y][0].pa >= 502].std())}); L.drop(Y)
    print("league mean swing-minus-take value by zone, and qualified-pool SD of SD raw:"); print(pd.DataFrame(rows, index=L.SEASONS).round(4).to_string())


def fine_table(s, parent_keys, band, k):
    """p_whiff per (parent cell x band), shrunk to the frame's parent p (pwh) with k pseudo-swings."""
    g = s.groupby(parent_keys + [band], observed=True).agg(n=('con', 'size'), wh=('con', lambda v: (1 - v).sum()), pp=('pwh', 'mean'))
    g['p'] = (g.wh + k * g.pp) / (g.n + k)
    return g.p


def t8():
    print("\n=== T8 CT+ expected contact with velocity / movement bands (cascade to the shipped cell, k swept) ===")
    PK = ['zone', 'b', 's', 'cat']
    SW = {}
    for Y in L.SEASONS:
        d = L.load(Y)['df']; s = d[d.ct_el & (d.lev > 0)][['bid', 'zone', 'b', 's', 'cat', 'lev', 'pwh', 'con', 'velo', 'ivb', 'hb', 'pt']].copy()
        for c, nm in (('velo', 'vb'), ('ivb', 'ib'), ('hb', 'hbb')):
            s[nm] = s.groupby('cat', observed=True)[c].transform(lambda v: pd.qcut(v, 3, labels=False, duplicates='drop')).fillna(-1).astype(int)
        s['vib'] = s.vb * 10 + s.ib
        rng = np.random.default_rng(Y)
        for nm in ('vb', 'vib'):
            s['pl_' + nm] = s.groupby(PK, observed=True)[nm].transform(lambda v: rng.permutation(v.values))
        s['ptb'] = s.pt.astype(str)
        SW[Y] = s; L.drop(Y)
    # (a) cell-fit objective: table from season A, log loss on season B, against the parent cell from A
    def ll(p, y):
        p = np.clip(p, 1e-4, 1 - 1e-4); return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    print("(a) out-of-sample cell fit: mean log-loss change vs the shipped parent cell, 30 ordered season pairs (negative = better)")
    for band in ('vb', 'ib', 'hbb', 'vib', 'ptb', 'pl_vb', 'pl_vib'):
        line = []
        for k in (5, 15, 50, 150, 500):
            ds, wins = [], 0
            for A_ in L.SEASONS:
                ft = fine_table(SW[A_], PK, band, k).rename('pf').reset_index()
                par = SW[A_].groupby(PK, observed=True).pwh.mean().rename('ppar').reset_index()
                for B_ in L.SEASONS:
                    if A_ == B_:
                        continue
                    t = SW[B_][PK + [band, 'con']].merge(par, on=PK, how='left').merge(ft, on=PK + [band], how='left')
                    t['pf'] = t.pf.fillna(t.ppar); t = t[t.ppar.notna()]
                    dd = ll(t.pf.values, 1 - t.con.values) - ll(t.ppar.values, 1 - t.con.values)
                    ds.append(dd); wins += dd < 0
            line.append(f"k{k}: {np.mean(ds)*1e4:+.2f}e-4 ({wins}/30)")
        print(f"   {band:7s} " + " | ".join(line))
    # (b) hitter-level: CT raw with the fine expected contact
    print("(b) hitter level, own-season fine table, shipped weights; base = shipped CT")
    for band in ('vb', 'ib', 'vib', 'ptb', 'pl_vb', 'pl_vib'):
        for k in (15, 50, 150):
            var = {}
            for Y in L.SEASONS:
                s = SW[Y]; ft = fine_table(s, PK, band, k).rename('pf').reset_index()
                t = s[['bid', 'lev', 'con'] + PK + [band]].merge(ft, on=PK + [band], how='left')
                var[Y] = (t.lev * t.con).groupby(t.bid).sum() / (t.lev * (1 - t.pf)).groupby(t.bid).sum()
            rr = np.mean([L.wcorr(var[Y].reindex(AT[Y][0].index)[AT[Y][0].ok], AT[Y][0].ct_raw[AT[Y][0].ok]) for Y in L.SEASONS])
            print(f"  band {band} k {k}: r with shipped {rr:.4f}; y-t-y {L.yy({Y: var[Y][AT[Y][0].pa.reindex(var[Y].index) >= 300] for Y in L.SEASONS})[0]:.3f}")
            RES[f't8 {band} k{k}'] = L.eval_var(AT, 'ct', var, label=f'{band} k{k}')
            # own-target: next-season K%
            ks = []
            for y0, y1 in L.PAIRS:
                A, B = AT[y0][0], AT[y1][0]; a = A[A.ok & (A.pa >= 200)]; w = B.pa.reindex(a.index).fillna(0)
                ks.append((L.wcorr(a.ct_raw, B.k.reindex(a.index), w), L.wcorr(var[y0].reindex(a.index), B.k.reindex(a.index), w)))
            print(f"      r with next-season K%: shipped {np.mean([x[0] for x in ks]):+.4f}, variant {np.mean([x[1] for x in ks]):+.4f}")


def t9():
    print("\n=== T9 opponent quality: remove the pitchers' own effect from CT, SD and xwOBAcon ===")
    for K in (50, 150, 400):
        vct, vsd, vbb, spread = {}, {}, {}, []
        for Y in L.SEASONS:
            S = L.load(Y); d = S['df']; lgz = S['lgz']
            s = d[d.ct_el & (d.lev > 0)]
            g = s.groupby('pid', observed=True).agg(n=('con', 'size'), act=('con', lambda v: (1 - v).sum()), ex=('pwh', 'sum'))
            dlt = ((g.act - g.ex) / (g.n + K)).rename('dp')            # shrunk whiff-rate excess of the pitcher
            p2 = (s.pwh + s.pid.map(dlt).fillna(0)).clip(0.01, 0.99)
            vct[Y] = (s.lev * s.con).groupby(s.bid).sum() / (s.lev * (1 - p2)).groupby(s.bid).sum()
            e = d[d.sd_el]
            zmean = e.groupby('zone', observed=True).dv.transform('mean')
            ge = (e.dv - zmean).groupby(e.pid, observed=True).agg(['sum', 'size'])
            dsd = (ge['sum'] / (ge['size'] + K * 4)).rename('dd')
            e2 = e.assign(dv2=e.dv - e.pid.map(dsd).fillna(0).astype('float32'))
            vsd[Y] = L.sd_raw(e2, lgz, col='dv2')[0]
            b = d[d.bip & d.xw.notna()]; lg = b.xw.mean()
            gb = (b.xw - lg).groupby(b.pid, observed=True).agg(['sum', 'size']); dx = gb['sum'] / (gb['size'] + K * 2)
            xw2 = (b.xw - b.pid.map(dx).fillna(0)).groupby(b.bid).mean()
            A = AT[Y][0]; anc = AT[Y][1]
            con2 = 100 * xw2.reindex(A.index) / anc['lgx']; vbb[Y] = 0.6 * con2 + 0.4 * A.evc
            a = A[A.ok & (A.pa >= 300)]
            spread.append((float((vct[Y].reindex(a.index) - a.ct_raw).std() / a.ct_raw.std()), float((vsd[Y].reindex(a.index) - a.sd_raw).std() / a.sd_raw.std()),
                           float((vbb[Y].reindex(a.index) - a.bb_raw).std() / a.bb_raw.std())))
            L.drop(Y)
        sp = np.mean(spread, axis=0)
        print(f"K={K}: SD of the schedule adjustment across hitters, as a share of the atom's SD: CT {sp[0]:.3f}, SD {sp[1]:.3f}, BB {sp[2]:.3f}")
        RES[f't9 ct K{K}'] = L.eval_var(AT, 'ct', vct, label=f'CT opp-adj K{K}')
        RES[f't9 sd K{K}'] = L.eval_var(AT, 'sd', vsd, label=f'SD opp-adj K{K}')
        RES[f't9 bb K{K}'] = L.eval_var(AT, 'bb', vbb, label=f'BB opp-adj K{K}')


if __name__ == '__main__':
    which = sys.argv[1:] or ['t6', 't7', 't8', 't9']
    for t in which:
        globals()[t]()
    L.save('res_sdct_' + '_'.join(which) + '.json', RES)
