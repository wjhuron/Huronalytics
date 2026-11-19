"""dd_bb_air.py - constants for the BB+ air-ball EV95 release (EV95 over balls at launch angle >= 10, w_ev .50).
Re-measures every constant that depends on the EV statistic: the live beta and its frozen fallback, the
minimum air-ball count (coverage), n0_con / n0_ev / w_ev, the slope match, the bat-tracking prior (betas, K, S0)
and the Process+ weights.  .venv/bin/python scripts/research/hitter/deep_dive/dd_bb_air.py [s1 s2 s3 s4 s5]"""
import sys, os
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dd_lib as L

AT = L.all_atoms()
RES = {}
FLOOR_LA = 10
WN = .45          # released EV weight (S6: forward optimum flat .45-.55, same-season not lower)
BIPS, SWS = {}, {}


def prep(bt=False):
    for Y in L.SEASONS:
        d = L.load(Y)['df']
        BIPS[Y] = d[d.bip][['bid', 'date', 'xw', 'ev', 'la', 'wv']].copy()
        L.drop(Y)


def ev95(b, air, minn=1):
    x = b[b.ev.notna() & (b.la >= FLOOR_LA)] if air else b[b.ev.notna()]
    g = x.groupby('bid', observed=True).ev
    q = g.quantile(.95); n = g.size()
    return q[n >= minn], n


def frame(b, air=True, minn=1):
    g = b.groupby('bid', observed=True)
    A = pd.DataFrame({'nbip': g.size(), 'xwcon': b[b.xw.notna()].groupby('bid', observed=True).xw.mean(), 'wcon': g.wv.mean(), 'la': g.la.mean()})
    e, n = ev95(b, air, minn); A['ev'] = e.reindex(A.index); A['n_ev'] = n.reindex(A.index).fillna(0)
    return A


def anchors(A, gate=30, bgate=80):
    pool = A[(A.nbip >= gate) & A.xwcon.notna() & A.ev.notna()]
    lgx = L.lg_mean(pool.xwcon, pool.nbip); lge = L.lg_mean(pool.ev, pool.nbip)
    g = pool[pool.nbip >= bgate]; x = 100 * g.ev / lge; y = 100 * g.xwcon / lgx
    beta = float(((x - x.mean()) * (y - y.mean())).sum() / ((x - x.mean()) ** 2).sum())
    return dict(lgx=lgx, lge=lge, beta=beta, nbeta=len(g))


def parts(A, anc):
    con = 100 * A.xwcon / anc['lgx']; evc = 100 + (100 * A.ev / anc['lge'] - 100) * anc['beta']
    return con, evc


def blend(A, anc, w, n0c=0, n0e=0):
    con, evc = parts(A, anc)
    return (1 - w) * (A.nbip * con + n0c * 100) / (A.nbip + n0c) + w * (A.nbip * evc + n0e * 100) / (A.nbip + n0e)


def s1():
    print("\n=== S1 anchors on the air statistic, and coverage of the air-ball count ===")
    betas = {True: [], False: []}
    for Y in L.SEASONS:
        for air in (False, True):
            A = frame(BIPS[Y], air); a = anchors(A); betas[air].append(a['beta'])
            if air:
                p = A[A.nbip >= 30]
                cov = {m: int((p.n_ev < m).sum()) for m in (1, 3, 5, 8, 12)}
                print(f" {Y}: league EV95 air {a['lge']:.2f} (all-ball {anchors(frame(BIPS[Y], False))['lge']:.2f}), beta air {a['beta']:.3f} (pool {a['nbeta']}), SD of 100*ev/lg (80+ BIP) "
                      f"{(100 * A.ev[A.nbip >= 80] / a['lge']).std():.2f}; hitters with 30+ BIP: {len(p)}, with fewer than m air balls {cov}; air share of BIP {p.n_ev.sum() / p.nbip.sum():.3f}")
    print(f" beta all-ball by season {np.round(betas[False], 3)} mean {np.mean(betas[False]):.3f} (shipped frozen 4.205)")
    print(f" beta air      by season {np.round(betas[True], 3)} mean {np.mean(betas[True]):.3f}  range {min(betas[True]):.3f}-{max(betas[True]):.3f}  (band 3.0-6.0)")
    RES['s1'] = dict(beta_air=betas[True], beta_all=betas[False])


def halves():
    H = {}
    for Y in L.SEASONS:
        b = BIPS[Y]; dates = np.array(sorted(b.date.unique()))
        for seed in range(3):
            rng = np.random.default_rng(31 * seed + Y); hs = set(rng.choice(dates, len(dates) // 2, replace=False)); m = b.date.isin(hs)
            H[(Y, seed)] = (b[m], b[~m])
    return H


def s2():
    print("\n=== S2 w_ev x n0_con x n0_ev on the air statistic: half A shrunk BB -> half B ACTUAL wOBAcon (6 seasons x 3 seeds, 20+ BIP each half) ===")
    H = halves()
    W = (.30, .40, .45, .50, .55, .60, .70); NC = (0, 40, 80, 100, 130, 160, 200, 260, 400); NE = (0, 3, 5, 10, 20, 40, 80)
    R = {}
    for (Y, seed), (a, b) in H.items():
        A = frame(a); B = frame(b); anc = anchors(A, gate=20, bgate=40)
        k = A.index[(A.nbip >= 20) & A.ev.notna()].intersection(B.index[B.nbip >= 20])
        for w in W:
            for nc in NC:
                for ne in NE:
                    R.setdefault((w, nc, ne), {})[(Y, seed)] = L.wcorr(blend(A, anc, w, nc, ne)[k].values, B.wcon[k].values)
        A0 = frame(a, air=False); anc0 = anchors(A0, gate=20, bgate=40)
        R.setdefault('ship', {})[(Y, seed)] = L.wcorr(blend(A0, anc0, .4, 130, 0)[k].values, B.wcon[k].values)
    mean = lambda key, ys=None: float(np.mean([v for (Y, s), v in R[key].items() if ys is None or Y in ys]))
    print(f" shipped (all-ball, .40, 130, 0): {mean('ship'):.4f}")
    print(" n0_ev 0, rows w_ev, columns n0_con " + " ".join(f"{nc:>6d}" for nc in NC))
    for w in W:
        print(f"   w {w:.2f}: " + " ".join(f"{mean((w, nc, 0)):.4f}" for nc in NC))
    print(f" w_ev {WN}, rows n0_ev, columns n0_con")
    for ne in NE:
        print(f"   n0_ev {ne:3d}: " + " ".join(f"{mean((WN, nc, ne)):.4f}" for nc in NC))
    best = max((k for k in R if k != 'ship'), key=mean); print(f" pooled argmax {best} r {mean(best):.4f}; at (WN, 130, 0) {mean((WN, 130, 0)):.4f}")
    print(" leave-one-season-out: config chosen on the other five seasons, scored on the held-out season, against (.50, 130, 0) and shipped")
    for Y in L.SEASONS:
        oth = [y for y in L.SEASONS if y != Y]; c = max((k for k in R if k != 'ship'), key=lambda k: mean(k, oth))
        print(f"   {Y}: chosen {c} held-out {mean(c, [Y]):.4f} | (WN,130,0) {mean((WN, 130, 0), [Y]):.4f} | shipped {mean('ship', [Y]):.4f}")
    # paired SE of (.50,130,0) against neighbours
    for alt in ((WN, 80, 0), (WN, 100, 0), (WN, 160, 0), (WN, 200, 0), (WN, 130, 5), (WN, 130, 10), (WN, 130, 20), (.5, 130, 0), (.4, 130, 0), 'ship'):
        d = np.array([R[(WN, 130, 0)][c] - R[alt][c] for c in R['ship']]); print(f"   (WN,130,0) minus {alt}: {d.mean():+.4f} (SE {d.std(ddof=1) / np.sqrt(len(d)):.4f}) wins {int((d > 0).sum())}/18")
    RES['s2'] = {str(k): mean(k) for k in R}


def s3():
    print("\n=== S3 slope match: candidate estimators on full seasons; the shipped config must reproduce 1.2352 ===")
    out = {}
    for label, air, w in (('shipped all-ball .40', False, .4), ('air .50', True, .5), ('air .40', True, .4), ('all-ball .50', False, .5)):
        rows = []
        for Y in L.SEASONS:
            A = frame(BIPS[Y], air); anc = anchors(A); con, evc = parts(A, anc)
            bl = blend(A, anc, w, 130, 0)
            r = {}
            for pg in (30, 150, 300):
                p = A.index[(A.nbip >= pg) & bl.notna()]
                for n0p in (60, 130):
                    pure = (A.nbip * con + n0p * 100) / (A.nbip + n0p)
                    x, y = bl[p] - 100, pure[p] - 100
                    r[f'sd{pg}/{n0p}'] = float(y.std() / x.std()); r[f'thru{pg}/{n0p}'] = float((x * y).sum() / (x * x).sum())
                x, y = bl[p] - 100, con[p] - 100
                r[f'rawcon_ols{pg}'] = float(np.polyfit(x, y, 1)[0]); r[f'rawcon_sd{pg}'] = float(y.std() / x.std())
            r['meanbip300'] = float(A.nbip[A.nbip >= 300].mean())
            rows.append(r)
        m = pd.DataFrame(rows, index=L.SEASONS)
        out[label] = m.mean().to_dict()
        print(f" {label}:"); print("   " + "  ".join(f"{c} {v:.4f}" for c, v in m.mean().items()))
    RES['s3'] = out
    # forward calibration: slope of next-season xwOBAcon percent (and actual wOBAcon percent) on this season's raw shrunk blend
    print(" forward calibration, Y -> Y+1 (150+ BIP both years): slope of next-season percent on (blend - 100), K = 1 / slope would make the display slope 1")
    for label, air, w in (('shipped all-ball .40', False, .4), ('air .50', True, .5)):
        sx, sw = [], []
        for y0, y1 in L.PAIRS:
            A = frame(BIPS[y0], air); B = frame(BIPS[y1], air); a0, a1 = anchors(A), anchors(B)
            bl = blend(A, a0, w, 130, 0); k = A.index[(A.nbip >= 150) & bl.notna()].intersection(B.index[B.nbip >= 150])
            lgw = L.lg_mean(B.wcon[B.nbip >= 30], B.nbip[B.nbip >= 30])
            sx.append(np.polyfit(bl[k] - 100, 100 * B.xwcon[k] / a1['lgx'] - 100, 1)[0]); sw.append(np.polyfit(bl[k] - 100, 100 * B.wcon[k] / lgw - 100, 1)[0])
        print(f"   {label}: on next xwOBAcon% {np.round(sx, 3)} mean {np.mean(sx):.4f} | on next actual wOBAcon% {np.round(sw, 3)} mean {np.mean(sw):.4f}")
        RES['s3 fwd ' + label] = dict(x=float(np.mean(sx)), w=float(np.mean(sw)))


def s4():
    print("\n=== S4 bat-tracking prior on the air raw (w .50): standardized betas, K and S0 in the call-up simulation (2024-2026) ===")
    import dd_bt as BT
    BT.prep(); YS = BT.YS
    FULL = {}
    for Y in YS:
        for tag, air, w in (('new', True, WN), ('old', False, .4)):
            A = frame(BIPS[Y], air); anc = anchors(A); A['raw'] = blend(A, anc, w)
            T = BT.traits(BT.SW[Y]); p = A[A.nbip >= 80].join(T, how='inner'); p = p[(p.nsw >= 50) & p.raw.notna()]
            FULL[(Y, tag)] = dict(anc=anc, mean=float(p.raw.mean()), bs=(float(p.bs.mean()), float(p.bs.std())), sq=(float(p.squp.mean()), float(p.squp.std())), pool=p)

    def fit(excl, tag, cols):
        X, y = [], []
        for Y in YS:
            if Y == excl:
                continue
            F = FULL[(Y, tag)]; p = F['pool']; zs = np.c_[tuple(((p[c] - F[dict(bs='bs', squp='sq')[c]][0]) / F[dict(bs='bs', squp='sq')[c]][1]).values for c in cols)]
            m = np.all(np.isfinite(zs), axis=1); X.append(zs[m]); y.append((p.raw.values - F['mean'])[m])
        return np.linalg.lstsq(np.vstack(X), np.concatenate(y), rcond=None)[0]
    for tag in ('old', 'new'):
        print(f" {tag}: all-season std betas bs+squp {np.round(fit(None, tag, ['bs', 'squp']), 2)}, leave-season-out " + ", ".join(f"{Y} {np.round(fit(Y, tag, ['bs', 'squp']), 2)}" for Y in YS)
              + f" | bs only {np.round(fit(None, tag, ['bs']), 2)} | pool raw mean " + ", ".join(f"{Y} {FULL[(Y, tag)]['mean']:.3f}" for Y in YS))

    def sim(Y, n, tag, w, n0c=130, n0e=0, min_rem=100):
        b = BIPS[Y]; F = FULL[(Y, tag)]; anc = F['anc']; air = tag == 'new'
        c = b.groupby(['bid', 'date'], observed=True).size().rename('k').reset_index().sort_values(['bid', 'date']); c['cum'] = c.groupby('bid').k.cumsum()
        cut = c[c.cum >= n].groupby('bid').date.first(); cm = b.bid.map(cut)
        E = frame(b[cm.notna() & (b.date <= cm)], air); Rm = frame(b[cm.notna() & (b.date > cm)], air); Rm = Rm[Rm.nbip >= min_rem]
        sw = BT.SW[Y]; sm = sw.bid.map(cut); T = BT.traits(sw[sm.notna() & (sw.date <= sm)])
        k = E.index.intersection(Rm.index).intersection(T.index); E, Rm, T = E.loc[k], Rm.loc[k], T.loc[k]
        df = pd.DataFrame({'n': E.nbip, 'e0': blend(E, anc, w, n0c, n0e), 'tgt': blend(Rm, anc, w), 'nsw': T.nsw, 'bs': T.bs, 'squp': T.squp, 'n_ev': E.n_ev, 'con': parts(E, anc)[0], 'evc': parts(E, anc)[1]})
        return df.dropna(subset=['e0', 'tgt', 'bs'])
    cells = [(Y, n) for Y in YS for n in (20, 40, 80)]
    SIM = {(c, tag): sim(c[0], c[1], tag, WN if tag == 'new' else .4) for c in cells for tag in ('old', 'new')}
    print(" pools (new):", {c: len(SIM[(c, 'new')]) for c in cells}, "| share with fewer than 8 air balls at n=20:", round(float(np.mean([(SIM[((Y, 20), 'new')].n_ev < 8).mean() for Y in YS])), 3))

    def rmse(c, tag, betas, K, S0, e0=None):
        s = SIM[(c, tag)]; F = FULL[(c[0], tag)]; e = s.e0 if e0 is None else e0(s)
        if betas is not None:
            b = betas(c[0]); pr = F['mean'] + b[0] * (s.bs - F['bs'][0]) / F['bs'][1] + (b[1] * ((s.squp - F['sq'][0]) / F['sq'][1]).fillna(0) if len(b) > 1 else 0)
            pe = (s.nsw * pr + S0 * 100) / (s.nsw + S0); e = (s.n * e + K * pe) / (s.n + K)
        return float(np.sqrt(np.mean((e - s.tgt) ** 2)))
    ship_b = lambda Y: (14.24, 4.97)
    refit2 = lambda Y: fit(Y, 'new', ['bs', 'squp']); refit1 = lambda Y: fit(Y, 'new', ['bs'])
    mm = lambda tag, betas, K=20, S0=10: float(np.mean([rmse(c, tag, betas, K, S0) for c in cells]))
    print(f" old statistic: no prior {mm('old', None):.3f}, shipped prior {mm('old', ship_b):.3f}")
    print(f" new statistic: no prior {mm('new', None):.3f}, shipped betas 14.24/4.97 {mm('new', ship_b):.3f}, refit two-term (leave-season-out) {mm('new', refit2):.3f}, refit bs only {mm('new', refit1):.3f}")
    KS = (0, 5, 10, 15, 20, 30, 40, 60, 80, 120, 160)
    print(" K sweep, new statistic, S0 10: shipped betas " + " ".join(f"K{K}:{mm('new', ship_b, K):.3f}" for K in KS))
    print("                               refit two-term " + " ".join(f"K{K}:{mm('new', refit2, K):.3f}" for K in KS))
    print("                               refit bs only  " + " ".join(f"K{K}:{mm('new', refit1, K):.3f}" for K in KS))
    for n in (20, 40, 80):
        print(f"    refit two-term, n={n}: " + " ".join(f"K{K}:{np.mean([rmse((Y, n), 'new', refit2, K, 10) for Y in YS]):.3f}" for K in KS))
    print(" S0 sweep, new statistic, refit two-term, K 20: " + " ".join(f"S{S}:{mm('new', refit2, 20, S):.3f}" for S in (0, 5, 10, 25, 50, 100)))
    wins = {nm: sum(rmse(c, 'new', b, 20, 10) < rmse(c, 'new', None, 20, 10) for c in cells) for nm, b in (('shipped betas', ship_b), ('refit two-term', refit2))}
    print(" cells better than no prior (of 9):", wins, "| refit two-term better than shipped betas:", sum(rmse(c, 'new', refit2, 20, 10) < rmse(c, 'new', ship_b, 20, 10) for c in cells))
    # n0 in the same simulation (calibration objective), prior off and on
    print(" n0_con x n0_ev in the call-up simulation (RMSE to the remainder raw, shipped-form prior with refit betas, K 20, S0 10):")
    for ne in (0, 3, 5, 10, 20, 40):
        line = []
        for nc in (40, 80, 100, 130, 160, 200, 260):
            e0 = lambda s, nc=nc, ne=ne: (1 - WN) * (s.n * s.con + nc * 100) / (s.n + nc) + WN * (s.n * s.evc + ne * 100) / (s.n + ne)
            line.append(f"{nc}:{np.mean([rmse(c, 'new', refit2, 20, 10, e0) for c in cells]):.3f}")
        print(f"    n0_ev {ne:3d}: " + " ".join(line))
    # full-season footprint of the prior
    for Y in YS:
        F = FULL[(Y, 'new')]; p = F['pool']; b = fit(Y, 'new', ['bs', 'squp'])
        pr = F['mean'] + b[0] * (p.bs - F['bs'][0]) / F['bs'][1] + b[1] * (p.squp - F['sq'][0]) / F['sq'][1]
        sh = blend(p, F['anc'], WN, 130, 0); new = (p.nbip * sh + 20 * pr) / (p.nbip + 20)
        print(f"   {Y} full season (80+ BIP): corr(with prior, without) {np.corrcoef(new, sh)[0, 1]:.4f}, mean |d| {np.mean(np.abs(new - sh)):.2f}")
    RES['s4'] = dict(betas_all=fit(None, 'new', ['bs', 'squp']).tolist(), betas_loso={Y: fit(Y, 'new', ['bs', 'squp']).tolist() for Y in YS})


def s5():
    print("\n=== S5 Process+ weights on the released SD atom (zone x two-strike) and the air BB atom (w .50) ===")
    from dd_follow import neutral2
    V = {}
    for Y in L.SEASONS:
        d = L.load(Y)['df']; A = frame(BIPS[Y]); V[Y] = dict(sd=neutral2(d), bb=blend(A, anchors(A), WN), bb0=None); L.drop(Y)
        A0 = frame(BIPS[Y], False); V[Y]['bb0'] = blend(A0, anchors(A0), .4)

    def folds(mode, mp, bbkey):
        F = []
        for Y in (L.SEASONS if mode == 'DESC' else [p[0] for p in L.PAIRS]):
            A = AT[Y][0]; a = A[A.ok & (A.pa >= mp)]; q = a.pa >= L.QUAL_PA
            sdv, bbv = V[Y]['sd'].reindex(a.index), V[Y][bbkey].reindex(a.index)
            if mode == 'PRED':
                sdv = (a.n_dec * sdv + L.N0['sd'] * np.average(sdv[sdv.notna()], weights=a.n_dec[sdv.notna()])) / (a.n_dec + L.N0['sd'])
                y = AT[Y + 1][0].woba.reindex(a.index).values; w = AT[Y + 1][0].pa.reindex(a.index).fillna(0).values; zc = a.zs_ct
            else:
                y, w, zc = a.woba.values, np.ones(len(a)), a.z_ct
            F.append(dict(zb=L._zq(bbv, q).values, zs=L._zq(sdv, q).values, zc=np.asarray(zc), y=y, w=w))
        return F
    for mode, mp in (('DESC', 300), ('DESC', 100), ('PRED', 200)):
        F0, F1 = folds(mode, mp, 'bb0'), folds(mode, mp, 'bb')
        comp = lambda f, wb=.52, ws=.17: wb * f['zb'] + ws * f['zs'] + (1 - wb - ws) * f['zc']
        FF = [dict(a=comp(f0), b=comp(f1), y=f1['y'], w=f1['w']) for f0, f1 in zip(F0, F1)]
        print(f" {mode} pa>={mp}: all-ball .40 -> air .50 at 52/17/31: {L.fmt(L.paired(FF, lambda f: f['a'], lambda f: f['b']))}")
        grid = {}
        for wb in np.arange(.40, .661, .01):
            for ws in np.arange(.08, .301, .01):
                grid[(round(wb, 2), round(ws, 2))] = [L.wcorr(comp(f, wb, ws), f['y'], f['w']) for f in F1]
        best = max(grid, key=lambda k: np.mean(grid[k])); r0 = np.mean(grid[(.52, .17)])
        d = np.array(grid[best]) - np.array(grid[(.52, .17)])
        print(f"    weights on the new atoms: argmax {best[0]}/{best[1]}/{round(1 - best[0] - best[1], 2)} r {np.mean(grid[best]):.4f}; 52/17/31 r {r0:.4f}; gain {d.mean():+.4f} (wins {int((d > 0).sum())}/{len(d)})")
        print("    BB weight curve at SD .17: " + " ".join(f"{wb:.2f}:{np.mean(grid[(round(wb, 2), .17)]):.4f}" for wb in np.arange(.40, .661, .04)))
        # held-out: weights chosen on the other seasons
        ho = []
        for i in range(len(F1)):
            c = max(grid, key=lambda k: np.mean([v for j, v in enumerate(grid[k]) if j != i])); ho.append(grid[c][i] - grid[(.52, .17)][i])
        print(f"    held-out refit minus 52/17/31: {np.mean(ho):+.4f} (wins {int((np.array(ho) > 0).sum())}/{len(ho)})")
        RES[f's5 {mode}{mp}'] = dict(best=list(best), r_best=float(np.mean(grid[best])), r_ship=float(r0), heldout=float(np.mean(ho)))


def s6():
    """The EV weight on the air statistic at PRODUCTION sample size: displayed (shrunk) BB of season Y against
    season Y+1 actual wOBAcon and xwOBAcon (gate on Y only, weights Y+1 BIP), the Process+ composite on both
    objectives, and the forward slope ratio that sets the slope match, each on a w grid."""
    print("\n=== S6 EV weight on the air statistic at full-season size ===")
    WG = (.20, .30, .35, .40, .45, .50, .55, .60)
    FR = {(Y, air): frame(BIPS[Y], air) for Y in L.SEASONS for air in (True, False)}
    AN = {k: anchors(v) for k, v in FR.items()}
    print(" displayed BB (n0 130 / 0) of Y -> Y+1, hitters with 30+ BIP in Y, weights Y+1 BIP: r with next ACTUAL wOBAcon | next xwOBAcon | paired delta vs shipped on actual (SE, wins/5) | forward slope ratio vs shipped (xwOBAcon)")
    def fwd(air, w):
        ra, rx, sl = [], [], []
        for y0, y1 in L.PAIRS:
            A, B = FR[(y0, air)], FR[(y1, True)]; bl = blend(A, AN[(y0, air)], w, 130, 0)
            k = A.index[(A.nbip >= 30) & bl.notna()].intersection(B.index[B.nbip >= 1]); wt = B.nbip[k].values
            ra.append(L.wcorr(bl[k].values, B.wcon[k].values, wt)); rx.append(L.wcorr(bl[k].values, B.xwcon[k].values, wt))
            k2 = A.index[(A.nbip >= 150) & bl.notna()].intersection(B.index[B.nbip >= 150])
            sl.append(np.polyfit(bl[k2] - 100, 100 * B.xwcon[k2] / AN[(y1, True)]['lgx'] - 100, 1)[0])
        return np.array(ra), np.array(rx), np.array(sl)
    s_a, s_x, s_s = fwd(False, .4)
    print(f"   shipped all-ball .40: {s_a.mean():.4f} | {s_x.mean():.4f} | slope {s_s.mean():.4f}")
    for air in (True, False):
        for w in WG:
            a, x, s = fwd(air, w); d = a - s_a; r = s / s_s
            print(f"   {'air     ' if air else 'all-ball'} w {w:.2f}: {a.mean():.4f} | {x.mean():.4f} | {d.mean():+.4f} (SE {d.std(ddof=1) / np.sqrt(5):.4f}) {int((d > 0).sum())}/5 | ratio {r.mean():.4f} (SE {r.std(ddof=1) / np.sqrt(5):.4f}) -> slope match {1.2352 * r.mean():.4f}")
            RES[f's6 fwd {air} {w}'] = dict(actual=float(a.mean()), x=float(x.mean()), d=float(d.mean()), ratio=float(r.mean()))
    from dd_follow import neutral2
    SDV = {}
    for Y in L.SEASONS:
        d = L.load(Y)['df']; SDV[Y] = neutral2(d); L.drop(Y)
    def comp(mode, mp, air, w):
        out = []
        for Y in (L.SEASONS if mode == 'DESC' else [p[0] for p in L.PAIRS]):
            A = AT[Y][0]; a = A[A.ok & (A.pa >= mp)]; q = a.pa >= L.QUAL_PA
            sdv = SDV[Y].reindex(a.index); bbv = blend(FR[(Y, air)], AN[(Y, air)], w).reindex(a.index)
            if mode == 'PRED':
                sdv = (a.n_dec * sdv + L.N0['sd'] * np.average(sdv[sdv.notna()], weights=a.n_dec[sdv.notna()])) / (a.n_dec + L.N0['sd'])
                y = AT[Y + 1][0].woba.reindex(a.index).values; wt = AT[Y + 1][0].pa.reindex(a.index).fillna(0).values; zc = a.zs_ct
            else:
                y, wt, zc = a.woba.values, np.ones(len(a)), a.z_ct
            out.append(L.wcorr((.52 * L._zq(bbv, q) + .17 * L._zq(sdv, q) + .31 * zc).values, y, wt))
        return np.array(out)
    print(" Process+ composite (released SD atom), delta vs the shipped BB atom: same-season wOBA pa>=300 (wins/6) | pa>=100 | next-season wOBA (SE, wins/5)")
    base = {k: comp(k[0], k[1], False, .4) for k in (('DESC', 300), ('DESC', 100), ('PRED', 200))}
    for air in (True, False):
        for w in WG:
            line = []
            for k in base:
                d = comp(k[0], k[1], air, w) - base[k]; line.append(f"{d.mean():+.4f} (SE {d.std(ddof=1) / np.sqrt(len(d)):.4f}) {int((d > 0).sum())}/{len(d)}")
                RES[f's6 comp {air} {w} {k}'] = float(d.mean())
            print(f"   {'air     ' if air else 'all-ball'} w {w:.2f}: " + " | ".join(line))
    print(" half-season displayed BB (n0 130 / 0, 20+ BIP halves) -> other-half actual wOBAcon, paired vs shipped:")
    H = halves()
    for w in (.30, .40, .50):
        d = []
        for (Y, seed), (a, b) in H.items():
            A = frame(a); B = frame(b); A0 = frame(a, False); k = A.index[(A.nbip >= 20) & A.ev.notna()].intersection(B.index[B.nbip >= 20])
            d.append(L.wcorr(blend(A, anchors(A, 20, 40), w, 130, 0)[k].values, B.wcon[k].values) - L.wcorr(blend(A0, anchors(A0, 20, 40), .4, 130, 0)[k].values, B.wcon[k].values))
        d = np.array(d); print(f"   air w {w:.2f}: {d.mean():+.4f} (SE {d.std(ddof=1) / np.sqrt(len(d)):.4f}) wins {int((d > 0).sum())}/18")


def s7():
    """Launch-angle bias of the displayed blend: half A blend -> half B xwOBAcon percent, residual by mean launch angle."""
    print("\n=== S7 launch-angle bias (half A blend predicts half B xwOBAcon percent; 50+ BIP halves, 6 seasons x 3 seeds) ===")
    H = halves()
    for label, air, w in (('shipped all-ball .40', False, .4), (f'air {WN}', True, WN)):
        rs, Q = [], []
        for (Y, seed), (a, b) in H.items():
            A = frame(a, air); B = frame(b, air); anc = anchors(A, 20, 40); bl = blend(A, anc, w, 130, 0)
            k = A.index[(A.nbip >= 50) & bl.notna()].intersection(B.index[B.nbip >= 50])
            y = 100 * B.xwcon[k] / L.lg_mean(B.xwcon[k], B.nbip[k]); c = np.polyfit(bl[k], y, 1); res = y - np.polyval(c, bl[k])
            rs.append(L.wcorr(res.values, A.la[k].values)); q = pd.qcut(A.la[k], 5, labels=False)
            Q.append([res[q == i].mean() for i in range(5)] + [A.la[k][q == i].mean() for i in range(5)])
        Q = np.mean(Q, axis=0)
        print(f" {label}: r(residual, mean LA) {np.mean(rs):+.3f}; quintile residuals " + " ".join(f"{Q[5 + i]:.1f}deg:{Q[i]:+.2f}" for i in range(5)) + f"; Q1-Q5 spread {Q[4] - Q[0]:.2f}")
        RES['s7 ' + label] = dict(r=float(np.mean(rs)), q=Q.tolist())


if __name__ == '__main__':
    which = sys.argv[1:] or ['s1', 's2', 's3', 's4', 's5', 's6', 's7']
    prep()
    for t in which:
        globals()[t]()
    L.save('res_bb_air_' + '_'.join(which) + '.json', RES)
