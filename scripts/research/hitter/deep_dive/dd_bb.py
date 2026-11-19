"""dd_bb.py - deep-dive tests 10-11 (BB+): EV ingredient variants, the EV weight by objective,
pulled air in the Process+ atom; plus T4c (what the strikeout rate adds).
.venv/bin/python scripts/research/hitter/deep_dive/dd_bb.py [t10 t10w t11 t4c]"""
import sys, os
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dd_lib as L
from dd_process import ols_fit

AT = L.all_atoms()
RES = {}
BIP = {}
CG = [0, .05, .10, .15, .20, .25, .30, .40, .50]
EVV = ['ev95', 'ev90', 'ev85', 'ev80', 'ev75', 'ev95_la0', 'ev95_la10', 'ev95_sweet', 'ev95_adj', 'ev90_adj', 'evmean', 'ev_bysample']


def bip(Y):
    if Y not in BIP:
        d = L.load(Y)['df']; b = d[d.bip][['bid', 'date', 'xw', 'ev', 'la', 'spray', 'wv', 'bats']].copy()
        lab = pd.cut(b.la, [-91, -10, 0, 10, 20, 30, 40, 91], labels=False)
        b['ev_adj'] = b.ev - b.groupby(lab).ev.transform('mean') + b.ev.mean()     # EV against the league mean at that launch-angle band
        b['air'] = b.la >= 20; b['pa_'] = b.air & (b.spray < -15)
        BIP[Y] = b; L.drop(Y)
    return BIP[Y]


def parts(b):
    g = b.groupby('bid', observed=True)
    P = pd.DataFrame({'nbip': g.size(), 'xwcon': g.xw.mean(), 'wcon': g.wv.mean(), 'la': g.la.mean(), 'n_air': g.air.sum(), 'n_pa': g.pa_.sum()})
    e = b[b.ev.notna()]; ge = e.groupby('bid', observed=True)
    for q in (95, 90, 85, 80, 75):
        P[f'ev{q}'] = ge.ev.quantile(q / 100)
    P['evmean'] = ge.ev.mean()
    P['ev95_la0'] = e[e.la >= 0].groupby('bid', observed=True).ev.quantile(.95)
    P['ev95_la10'] = e[e.la >= 10].groupby('bid', observed=True).ev.quantile(.95)
    P['ev95_sweet'] = e[(e.la >= 8) & (e.la <= 32)].groupby('bid', observed=True).ev.quantile(.95)
    P['ev95_adj'] = ge.ev_adj.quantile(.95); P['ev90_adj'] = ge.ev_adj.quantile(.90)
    return P


def blend(P, evcol, w=0.4, C=0.0, gate=30):
    """prior-free BB raw on a parts frame: (1-w) con + w ev (unit-converted with a live beta)."""
    pool = P[(P.nbip >= gate) & P.xwcon.notna() & P[evcol if evcol != 'ev_bysample' else 'ev95'].notna()]
    share = pool.n_pa.sum() / pool.n_air.sum()
    xh = P.xwcon + C * (P.n_pa - share * P.n_air) / P.nbip
    lgx = float((xh[pool.index] * pool.nbip).sum() / pool.nbip.sum())
    con = 100 * xh / lgx

    def evc(col):
        lge = float((pool[col] * pool.nbip).sum() / pool.nbip.sum()); evp = 100 * P[col] / lge
        g = pool[pool.nbip >= max(gate, 80 if gate >= 30 else gate)]
        x = evp[g.index]; y = con[g.index]; m = x.notna() & y.notna()
        beta = float(((x[m] - x[m].mean()) * (y[m] - y[m].mean())).sum() / ((x[m] - x[m].mean()) ** 2).sum())
        return 100 + (evp - 100) * beta
    if evcol == 'ev_bysample':
        e = np.where(P.nbip < 110, evc('ev95'), np.where(P.nbip < 300, evc('ev85'), evc('ev75')))
        e = pd.Series(e, index=P.index)
    else:
        e = evc(evcol)
    return (1 - w) * con + w * e


def halves(Y, seed):
    b = bip(Y); dates = np.array(sorted(b.date.unique())); rng = np.random.default_rng(31 * seed + Y)
    hs = set(rng.choice(dates, len(dates) // 2, replace=False)); m = b.date.isin(hs)
    return parts(b[m]), parts(b[~m])


def split_folds(fn_a, fn_b, gate=50):
    """half A metric -> half B ACTUAL wOBAcon (outcome target), 6 seasons x 3 seeds."""
    F = []
    for Y in L.SEASONS:
        for seed in range(3):
            A, B = HALF[(Y, seed)]
            k = A.index[(A.nbip >= gate)].intersection(B.index[B.nbip >= gate])
            a = A.loc[k]
            F.append(dict(a=fn_a(A).reindex(k).values, b=fn_b(A).reindex(k).values, y=B.wcon[k].values, w=np.ones(len(k)), la=a.la.values, n=a.nbip.values, yx=B.xwcon[k].values))
    return F


def cal(F, key):
    """mean correlation of the held-out residual with the hitter's mean launch angle."""
    out = []
    for f in F:
        m = np.isfinite(f[key]) & np.isfinite(f['yx'])
        b = np.polyfit(f[key][m], f['yx'][m], 1); out.append(L.wcorr(f['yx'][m] - np.polyval(b, f[key][m]), f['la'][m]))
    return float(np.mean(out))


def lognctl(F, key):
    """partial r of the metric with the target given log(nBIP)."""
    out = []
    for f in F:
        m = np.isfinite(f[key]) & np.isfinite(f['y']); ln = np.log(f['n'][m])
        rx = f[key][m] - np.polyval(np.polyfit(ln, f[key][m], 1), ln); ry = f['y'][m] - np.polyval(np.polyfit(ln, f['y'][m], 1), ln)
        out.append(L.wcorr(rx, ry))
    return float(np.mean(out))


def season_var(evcol, w=0.4, C=0.0):
    return {Y: blend(FULL[Y], evcol, w, C) for Y in L.SEASONS}


def prep():
    global HALF, FULL
    FULL = {Y: parts(bip(Y)) for Y in L.SEASONS}
    HALF = {(Y, s): halves(Y, s) for Y in L.SEASONS for s in range(3)}
    # parity with the atom frame
    for Y in (2021, 2026):
        A = AT[Y][0]; v = blend(FULL[Y], 'ev95').reindex(A.index); m = A.ok
        print(f"parity {Y}: max|bb_raw diff| {np.nanmax(np.abs(v[m] - A.bb_raw[m])):.4f}")


def t10():
    print("\n=== T10 BB+ exit-velocity ingredient (w_ev .40 fixed; beta live per variant) ===")
    print("variant | split-half r with other-half ACTUAL wOBAcon (d vs EV95, SE, wins/18) | partial r given log nBIP | residual-vs-LA r | composite DESC300 / PRED deltas")
    base = lambda P: blend(P, 'ev95', gate=20)
    for v in EVV:
        F = split_folds(base, lambda P, v=v: blend(P, v, gate=20))
        res = L.paired(F, lambda f: f['a'], lambda f: f['b'], n_boot=200)
        print(f" {v:11s} {res['ra']:.4f} -> {res['rb']:.4f} d {res['d']:+.4f} (SE {res['se']:.4f}) wins {res['wins']}/{res['n']} | logn-partial {lognctl(F,'a'):.4f} -> {lognctl(F,'b'):.4f} | LA bias {cal(F,'a'):+.3f} -> {cal(F,'b'):+.3f}")
        if v != 'ev95':
            RES['t10 ' + v] = L.eval_var(AT, 'bb', season_var(v), label=v) | {'split': res}
    print("--- pure ingredients, same split-half grader: xwOBAcon only, EV95 only ---")
    for nm, fn in (('con only', lambda P: blend(P, 'ev95', w=0.0, gate=20)), ('EV95 only', lambda P: blend(P, 'ev95', w=1.0, gate=20))):
        F = split_folds(base, fn); res = L.paired(F, lambda f: f['a'], lambda f: f['b'], n_boot=100)
        print(f" {nm:11s} {L.fmt(res)[:95]} | LA bias {cal(F,'b'):+.3f}")


def t10w():
    print("\n=== T10w the EV weight under each objective (EV95; shipped .40) ===")
    print(" w_ev | split-half outcome r | composite DESC pa>=300 (same-season wOBA) | DESC pa>=100 | composite PRED (next-season wOBA) | atom-level same-season r with actual wOBAcon")
    base = lambda P: blend(P, 'ev95', gate=20)
    for w in (0, .1, .2, .3, .4, .5, .6, .7, .85, 1.0):
        F = split_folds(base, lambda P, w=w: blend(P, 'ev95', w=w, gate=20)); sp = np.mean([L.wcorr(f['b'], f['y']) for f in F])
        var = season_var('ev95', w)
        d3 = L.paired(L.var_folds(AT, 'bb', var, None, 'DESC', 300), lambda f: f['base'], lambda f: f['var'], n_boot=200)
        d1 = L.paired(L.var_folds(AT, 'bb', var, None, 'DESC', 100), lambda f: f['base'], lambda f: f['var'], n_boot=200)
        pr = L.paired(L.var_folds(AT, 'bb', var, None, 'PRED', 200), lambda f: f['base'], lambda f: f['var'], n_boot=200)
        same = np.mean([L.wcorr(var[Y][FULL[Y].nbip >= 150], FULL[Y].wcon[FULL[Y].nbip >= 150]) for Y in L.SEASONS])
        print(f" {w:.2f} | {sp:.4f} | {d3['rb']:.4f} (d {d3['d']:+.4f}, SE {d3['se']:.4f}, {d3['wins']}/6) | {d1['rb']:.4f} ({d1['wins']}/6) | {pr['rb']:.4f} (d {pr['d']:+.4f}, SE {pr['se']:.4f}, {pr['wins']}/5) | {same:.4f}")
        RES[f't10w {w}'] = dict(split=float(sp), desc300=d3, desc100=d1, pred=pr)
    # joint: re-sweep the composite weights at w_ev 0 (the descriptive candidate)
    print("--- composite weights re-swept with w_ev = 0 and .20 (DESC pa>=300) ---")
    for w in (0.0, 0.2, 0.4):
        var = season_var('ev95', w); best = None
        for wb in np.arange(.40, .71, .01):
            for ws in np.arange(.08, .26, .01):
                wc = 1 - wb - ws; rs = []
                for Y in L.SEASONS:
                    A = AT[Y][0]; a = A[A.ok & (A.pa >= 300)]; v = var[Y].reindex(a.index); q = a.pa >= L.QUAL_PA
                    zb = (v - v[q].mean()) / v[q].std(); rs.append(L.wcorr(wb * zb + ws * a.z_sd + wc * a.z_ct, a.woba))
                if best is None or np.mean(rs) > best[0]:
                    best = (float(np.mean(rs)), round(wb, 2), round(ws, 2), round(wc, 2))
        print(f"   w_ev {w}: best composite r {best[0]:.4f} at {best[1]}/{best[2]}/{best[3]}")


def t11():
    print("\n=== T11 pulled-air term inside the Process+ batted-ball atom: xwOBAcon + C*(pulled air - league share) ===")
    print(" C | split-half outcome r (d vs C=0, wins/18) | composite DESC300 | DESC100 | PRED | within-hand DESC300 r")
    base = lambda P: blend(P, 'ev95', gate=20)
    for C in CG:
        F = split_folds(base, lambda P, C=C: blend(P, 'ev95', C=C, gate=20)); res = L.paired(F, lambda f: f['a'], lambda f: f['b'], n_boot=150)
        var = season_var('ev95', 0.4, C)
        FD = L.var_folds(AT, 'bb', var, None, 'DESC', 300)
        d3 = L.paired(FD, lambda f: f['base'], lambda f: f['var'], n_boot=200)
        d1 = L.paired(L.var_folds(AT, 'bb', var, None, 'DESC', 100), lambda f: f['base'], lambda f: f['var'], n_boot=200)
        pr = L.paired(L.var_folds(AT, 'bb', var, None, 'PRED', 200), lambda f: f['base'], lambda f: f['var'], n_boot=200)
        wh = []
        for f in FD:
            a = f['A']; hand = np.where(a.bats_L > .9, 'L', np.where(a.bats_L < .1, 'R', 'S')); s = f['var'].copy(); y = f['y'].copy()
            for h in 'LRS':
                m = hand == h; s[m] -= np.nanmean(s[m]); y[m] -= np.nanmean(y[m])
            wh.append(L.wcorr(s, y))
        print(f" {C:.2f} | {res['rb']:.4f} (d {res['d']:+.4f}, {res['wins']}/18) | {d3['rb']:.4f} (d {d3['d']:+.4f}, SE {d3['se']:.4f}, {d3['wins']}/6 {d3['per']}) | {d1['rb']:.4f} ({d1['wins']}/6) | {pr['rb']:.4f} (d {pr['d']:+.4f}, {pr['wins']}/5) | {np.mean(wh):.4f}")
        RES[f't11 {C}'] = dict(split=res, desc300=d3, desc100=d1, pred=pr, within_hand=float(np.mean(wh)))


def t4c():
    print("\n=== T4c what the strikeout rate adds to the composite, and which PROCESS traits recover it ===")
    TR = {}
    for Y in L.SEASONS:
        S = L.load(Y); d = S['df']; lgz = S['lgz']
        s2 = d[d.s == 2]; n2 = d[d.s < 2]
        T = pd.DataFrame(index=AT[Y][0].index)
        T['ct_2s'] = L.ct_raw(s2)[0]; T['ct_e'] = L.ct_raw(n2)[0]
        T['sd_2s'] = L.sd_raw(s2, lgz)[0]; T['sd_e'] = L.sd_raw(n2, lgz)[0]
        sw = d[d.ct_el]
        T['foul_sw'] = (sw.desc == 'Foul').groupby(sw.bid).mean()
        sw2 = sw[sw.s == 2]; T['foul_2s'] = (sw2.desc == 'Foul').groupby(sw2.bid).mean(); T['whiff_2s'] = (1 - sw2.con).groupby(sw2.bid).mean()
        e2 = s2[s2.sd_el]; T['look_2s'] = ((e2.dec == 'take') & e2.iz).groupby(e2.bid).sum() / e2.iz.groupby(e2.bid).sum()     # in-zone takes with two strikes
        T['zsw_2s'] = 1 - T.look_2s; T['chase_2s'] = ((e2.dec == 'swing') & ~e2.iz).groupby(e2.bid).sum() / (~e2.iz).groupby(e2.bid).sum()
        el = d[d.sd_el]; T['p_2s'] = (el.s == 2).groupby(el.bid).mean(); T['p_ahead'] = (el.b > el.s).groupby(el.bid).mean()
        pa = d[d.wd == 1]; T['ppa'] = el.groupby('bid', observed=True).size() / pa.groupby('bid', observed=True).size()
        fp = el[(el.b == 0) & (el.s == 0)]; T['fp_sw'] = (fp.dec == 'swing').groupby(fp.bid).mean(); T['fp_strike'] = ((fp.dec == 'swing') | fp.iz).groupby(fp.bid).mean()
        A = AT[Y][0]
        for c in ('k', 'bbr', 'swing', 'zswing', 'chase', 'la'):
            T[c] = A[c]
        TR[Y] = T; L.drop(Y)
    # how much of K% and BB% the atoms explain
    for tgt in ('k', 'bbr'):
        r2a, r2b = [], []
        for Y in L.SEASONS:
            A = AT[Y][0]; a = A[A.ok & (A.pa >= 300)]; T = TR[Y].loc[a.index]
            X = np.c_[np.ones(len(a)), a.z_bb, a.z_sd, a.z_ct]; y = a[tgt].values
            r2a.append(1 - np.var(y - X @ np.linalg.lstsq(X, y, rcond=None)[0]) / np.var(y))
            X2 = np.c_[X, L.zc(T.swing.values), L.zc(T.zswing.values), L.zc(T.chase.values)]
            r2b.append(1 - np.var(y - X2 @ np.linalg.lstsq(X2, y, rcond=None)[0]) / np.var(y))
        print(f"R2 of {tgt} on (bb, sd, ct): {np.mean(r2a):.3f}; adding swing/zswing/chase rates: {np.mean(r2b):.3f}")
    print("--- add one trait to (bb, sd, ct); coefficients fit on the other seasons ---")
    for t in ('k', 'ct_2s', 'ct_e', 'sd_2s', 'sd_e', 'whiff_2s', 'foul_2s', 'foul_sw', 'look_2s', 'chase_2s', 'p_2s', 'p_ahead', 'ppa', 'fp_sw', 'fp_strike', 'swing', 'zswing', 'chase'):
        line = []
        for mode in ('DESC', 'PRED'):
            F = []
            for Y in (L.SEASONS if mode == 'DESC' else [p[0] for p in L.PAIRS]):
                A = AT[Y][0]; a = A[A.ok & (A.pa >= 300)]; tv = TR[Y][t].reindex(a.index)
                if mode == 'DESC':
                    y, w = a.woba.values, np.ones(len(a))
                else:
                    B = AT[Y + 1][0]; y = B.woba.reindex(a.index).values; w = B.pa.reindex(a.index).fillna(0).values
                tz = L.zc(tv.fillna(tv.mean()).values); m = np.isfinite(y) & (w > 0)
                F.append(dict(X0=np.c_[a.z_bb, a.z_sd, a.z_ct][m], X1=np.c_[a.z_bb, a.z_sd, a.z_ct, tz][m], y=y[m], w=w[m]))
            P0, P1 = [], []
            for k, f in enumerate(F):
                for key, P in (('X0', P0), ('X1', P1)):
                    X = np.vstack([np.c_[np.ones(len(g['y'])), g[key]] for j, g in enumerate(F) if j != k])
                    yy = np.concatenate([g['y'] - np.average(g['y'], weights=g['w']) for j, g in enumerate(F) if j != k]); ww = np.concatenate([g['w'] / g['w'].mean() for j, g in enumerate(F) if j != k])
                    P.append(np.c_[np.ones(len(f['y'])), f[key]] @ ols_fit(X, yy, ww))
            res = L.paired([dict(a=a_, b=b_, y=f['y'], w=f['w']) for a_, b_, f in zip(P0, P1, F)], lambda q: q['a'], lambda q: q['b'], n_boot=200)
            line.append(f"{mode} d {res['d']:+.4f} (SE {res['se']:.4f}) {res['wins']}/{res['n']}"); RES[f't4c {t} {mode}'] = res
        print(f"   +{t:10s} " + " | ".join(line))


if __name__ == '__main__':
    which = sys.argv[1:] or ['t10', 't10w', 't11']
    if any(t in which for t in ('t10', 't10w', 't11')):
        prep()
    for t in which:
        globals()[t]()
    L.save('res_bb_' + '_'.join(which) + '.json', RES)
