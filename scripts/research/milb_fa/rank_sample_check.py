"""Does the free-agent pitcher ranking hold up across SAMPLE SIZE and MLB TIME, and does the
PRIOR season help? (2026-11-11, per Wally: "while accounting for sample size", "accounting for
MLB time", "feel free to use previous years as well, if it helps. 2026 most valuable sample")

Frame: rank_small.build(), one row per pitcher-season Y (2021..2025) with 30+ TBF at all levels,
MLB included; groups MLB-primary (more MLB than minor TBF, MLB under 250), small MiLB (under 75
TBF at every minor level) and gated MiLB (the shipped projection's population). Target: Y+1 RA9
over every level, translated to AAA, sign flipped, weighted by Y+1 TBF. Ranker: the xallm spec
of rank_small / rank_live, leave-one-pair-out, k as shipped per group (25, small 800). The
gated group's shipped projection correlates .91 with this spec (rank_live), so it stands in.

Pool: the free-agent shape, age 25+, highest minor level AAA or MLB-primary.

A. By bin (total TBF; MLB share of TBF): within-role weighted r of prediction and target, and
   the calibration slope (target on prediction, demeaned by pair and role). A slope under 1
   means the bin's spread of projections is wider than its outcomes support: too little
   shrinkage for that sample size.
B. Prior season: the spec plus season Y-1 all-level translated K-BB%, SwStr%, xFIP, GB%, each
   shrunk toward the mean on Y-1 TBF with the shipped k. A pitcher with no Y-1 line gets the
   mean with weight 0 (shrinkage with n = 0, stated here, not a silent fill). The fit weighs
   Y against Y-1 itself. Pairs 2022..2025 (2021 has no Y-1 in the pull). Decision rule, fixed
   before the run: adopt only if it wins 3 of 4 pairs AND the pooled delta clears 2 SE.

    python3 scripts/research/milb_fa/rank_sample_check.py
Writes data/_milb_fa/_rank_sample_check.json.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_run as BT  # noqa: E402
import rank_small as RS  # noqa: E402
from rank_backtest import wr  # noqa: E402

D = os.path.join(BT.ROOT, 'data', '_milb_fa')
PREV = ['K-BB%', 'SwStr%', 'xFIP', 'GB%']
B = 1000


def add_prev(fr):
    data = {y: BT.load(y, 'pit') for y in BT.YEARS}
    offs = {y: {s: BT.offsets(data[y], s)[0] for s in PREV} for y in BT.YEARS}
    for y in sorted(fr.pair.unique()):
        m = fr.pair == y
        if y - 1 not in data:
            continue
        g = data[y - 1]
        fr.loc[m, 'nPrev'] = fr.loc[m, 'mlbId'].map(g.groupby('mlbId').w.sum()).fillna(0)
        for s in PREV:
            q = g[g[s].notna()].assign(x=lambda d: (d[s] - d.lvl.map(offs[y - 1][s])) * d.w)
            v = q.groupby('mlbId')[['x', 'w']].sum().pipe(lambda d: d.x / d.w)
            fr.loc[m, 'prev_' + s] = fr.loc[m, 'mlbId'].map(v)
    return fr


def fit_prev(train, test, k):
    """rank_small.fit_predict_m plus the Y-1 columns, each shrunk on its own n (nPrev)."""
    cols = RS.SPEC + ['prev_' + s for s in PREV]
    tr = train[(train.tw > 0) & train.T_nRA9.notna()].dropna(subset=RS.SPEC)
    sh = [c for c in RS.SPEC if c.startswith('xallm_')]
    pv = ['prev_' + s for s in PREV]
    mu = {c: np.average(tr[c].dropna(), weights=tr.loc[tr[c].notna(), 'tw']) for c in sh + pv}

    def X(df):
        out = df[RS.SPEC].copy()
        f = df.nAll / (df.nAll + k)
        for c in sh:
            out[c] = mu[c] + (df[c] - mu[c]) * f
        fp = df.nPrev.fillna(0) / (df.nPrev.fillna(0) + RS.K)
        for c in pv:
            out[c] = mu[c] + (df[c].fillna(mu[c]) - mu[c]) * fp
        return np.column_stack([np.ones(len(df))] + [out[c] for c in cols])
    sw = np.sqrt(tr.tw.values)
    beta = np.linalg.lstsq(X(tr) * sw[:, None], tr.T_nRA9.values * sw, rcond=None)[0]
    return X(test) @ beta, beta


def build_big():
    """rank_small.build() for the pitchers it skips: 250+ MLB BF and more MLB than minors."""
    data = {y: BT.load(y, 'pit') for y in BT.YEARS}
    offs = {y: {s: BT.offsets(data[y], s)[0] for s in RS.STATS} for y in BT.YEARS}
    rows = []
    for y in list(BT.YEARS)[:-1]:
        base, nxt = data[y], data[y + 1]
        n2 = nxt[nxt.nRA9.notna()].assign(x=lambda q: (q.nRA9 - q.lvl.map(offs[y + 1]['nRA9'])) * q.w)
        tgt = n2.groupby('mlbId')[['x', 'w']].sum().pipe(lambda q: q.x / q.w)
        tw = nxt.groupby('mlbId').w.sum()
        for mid, g in base.groupby('mlbId'):
            mlb = g[g.lvl == 'MLB'].w.sum()
            if mlb < 250 or mlb <= g[g.lvl != 'MLB'].w.sum():
                continue
            gg = g[['G', 'GS']].sum()
            rec = {'pair': y, 'mlbId': mid, 'grp': 'MLB-big', 'nAll': g.w.sum(), 'mlbN': mlb,
                   'age': g.Age.dropna().iloc[0] if g.Age.notna().any() else np.nan,
                   'role': 'SP' if gg.G and gg.GS / gg.G >= BT.SP_GS_SHARE else 'RP',
                   'tw': tw.get(mid, 0), 'T_nRA9': tgt.get(mid, np.nan)}
            for s in RS.STATS:
                q = g[g[s].notna()]
                rec['xallm_' + s] = np.average(q[s] - q.lvl.map(offs[y][s]), weights=q.w) if len(q) else np.nan
            rows.append(rec)
    fb = pd.DataFrame(rows)
    fb['isSP'] = (fb.role == 'SP').astype(float)
    return fb


def heldout(fr, sc, fn):
    train = fr[(fr.tw > 0) & fr.T_nRA9.notna()].dropna(subset=RS.SPEC)
    out = pd.Series(np.nan, index=sc.index)
    for hp in sorted(sc.pair.unique()):
        for small in (True, False):
            te = sc[(sc.pair == hp) & ((sc.grp == 'small MiLB') == small)]
            if len(te):
                out[te.index] = fn(train[train.pair != hp], te, RS.K_SMALL if small else RS.K)
    return out


def demean(sc, col):
    x = sc[col].astype(float).copy()
    for _, g in sc.groupby(['pair', 'role']):
        x[g.index] -= np.average(g[col], weights=g.tw)
    return x


def bin_table(sc, pred, label, bins):
    sc = sc.assign(pred=pred).dropna(subset=['pred'])
    rows = []
    for name, m in bins(sc):
        g = sc[m]
        # demean INSIDE the bin (pair x role), so a bin's level offset cannot inflate r or slope
        g = g.assign(pd_=demean(g, 'pred'), td_=demean(g, 'T_nRA9'))
        if len(g) < 40:
            rows.append({'bin': name, 'n': int(len(g))})
            continue
        w = g.tw
        slope = np.sum(w * g.pd_ * g.td_) / np.sum(w * g.pd_ ** 2)
        per = [wr(h.pred, h.T_nRA9, h.tw, h.role) for _, h in g.groupby('pair') if len(h) >= 15]
        rows.append({'bin': name, 'n': int(len(g)), 'r_pooled': round(float(
            np.sum(w * g.pd_ * g.td_) / np.sqrt(np.sum(w * g.pd_ ** 2) * np.sum(w * g.td_ ** 2))), 3),
            'r_pairs': [round(x, 3) for x in per], 'slope': round(float(slope), 2),
            'pred_sd_runs': round(float(np.sqrt(np.average(g.pd_ ** 2, weights=w))), 2)})
    print(f'\n== A. {label} ==')
    print(pd.DataFrame(rows).to_string(index=False))
    return rows


def main():
    fr = add_prev(RS.build())
    pool = fr[(fr.age >= 25) & ((fr.top == 'AAA') | (fr.grp == 'MLB-primary'))]
    sc = pool[(pool.tw > 0) & pool.T_nRA9.notna()].dropna(subset=RS.SPEC)
    print(sc.groupby(['grp', 'pair']).size().unstack())
    base = heldout(fr, sc, lambda tr, te, k: RS.fit_predict_m(tr, te, RS.SPEC, 'nRA9', k)[0])
    share = sc.mlbN / sc.nAll
    out = {'A_tbf': bin_table(sc, base, 'by total 2026-style TBF (all levels, MLB included)', lambda d: [
        ('30-99', d.nAll < 100), ('100-199', (d.nAll >= 100) & (d.nAll < 200)),
        ('200-399', (d.nAll >= 200) & (d.nAll < 400)), ('400+', d.nAll >= 400)]),
        'A_mlb': bin_table(sc, base, 'by MLB share of TBF', lambda d: [
            ('no MLB', d.mlbN == 0), ('MLB under half', (d.mlbN > 0) & (d.mlbN <= d.nAll / 2)),
            ('MLB-primary', d.grp == 'MLB-primary')])}
    out['A_mlb_share_check'] = {'corr_share_nAll': round(float(np.corrcoef(share, sc.nAll)[0, 1]), 3)}

    # B. prior season
    sb = sc[sc.pair >= 2022]
    prev = heldout(fr, sb, lambda tr, te, k: fit_prev(tr[tr.pair >= 2022], te, k)[0])
    b0 = base[sb.index]
    _, beta = fit_prev(fr[(fr.pair >= 2022)], sb.iloc[:1], RS.K)
    print('\nB. prior-season fit (all pairs, k 25):',
          dict(zip(['const'] + RS.SPEC + ['prev_' + s for s in PREV], np.round(beta, 3))))
    rng = np.random.default_rng(0)
    res = {}
    for grp in ('all', 'MLB-primary', 'small MiLB', 'gated MiLB'):
        g = sb if grp == 'all' else sb[sb.grp == grp]
        pairs = sorted(g.pair.unique())
        d = []
        for hp in pairs:
            h = g[g.pair == hp]
            d.append(wr(prev[h.index], h.T_nRA9, h.tw, h.role) - wr(b0[h.index], h.T_nRA9, h.tw, h.role))
        boots = []
        for _ in range(B):
            ds = []
            for hp in pairs:
                idx = g.index[g.pair == hp]
                i = rng.choice(idx, len(idx))
                h = g.loc[i]
                ds.append(wr(prev[i], h.T_nRA9, h.tw, h.role) - wr(b0[i], h.T_nRA9, h.tw, h.role))
            boots.append(np.mean(ds))
        se = float(np.std(boots))
        res[grp] = {'n': int(len(g)), 'd_pairs': [round(x, 4) for x in d], 'd_mean': round(float(np.mean(d)), 4),
                    'se': round(se, 4), 'wins': int(sum(x > 0 for x in d)),
                    'adopt': bool(sum(x > 0 for x in d) >= 3 and np.mean(d) > 2 * se),
                    'with_prev_share': round(float(g.nPrev.gt(0).mean()), 3)}
        r = res[grp]
        print(f'  {grp:12s} n {r["n"]:4d} prev line {r["with_prev_share"]:.0%}  d {r["d_mean"]:+.4f} '
              f'se {r["se"]:.4f} wins {r["wins"]}/{len(pairs)} per pair {r["d_pairs"]} adopt {r["adopt"]}')
    out['B_prev'] = res

    # C. head to head on the shipped projection's own population (AAA primary, 25+, gated):
    # shipped (rank_backtest.predict, xall_ inputs, bt_run.fit_predict) vs the xallm spec vs
    # xallm + prior season, same rows, pairs 2022..2025
    import rank_backtest as RB
    bf = RB.frame()
    bp = bf[(bf.lvl == 'AAA') & (bf.age >= 25)]
    ship = pd.Series(np.nan, index=bp.index)
    for hp in sorted(bp.pair.unique()):
        te = bp[bp.pair == hp]
        ship[te.index] = RB.predict(bf[bf.pair != hp], te, RB.SHIP, 'nRA9')
    sm = pd.Series(ship.values, index=pd.MultiIndex.from_arrays([bp.pair, bp.mlbId])).dropna()
    sm = sm[~sm.index.duplicated()]
    g = sb[sb.grp == 'gated MiLB']
    key = pd.MultiIndex.from_arrays([g.pair, g.mlbId])
    g = g.assign(ship=sm.reindex(key).values, xs=b0[g.index].values, xp=prev[g.index].values).dropna(subset=['ship'])
    cmp = {}
    for nm in ('ship', 'xs', 'xp'):
        cmp[nm] = [round(wr(h[nm], h.T_nRA9, h.tw, h.role), 4) for _, h in g.groupby('pair')]
    d = [a - b for a, b in zip(cmp['xp'], cmp['ship'])]
    print(f'\nC. gated AAA 25+, n {len(g)}: shipped {cmp["ship"]} | xallm {cmp["xs"]} | xallm+prev {cmp["xp"]}'
          f' | xallm+prev minus shipped mean {np.mean(d):+.4f}, wins {sum(x > 0 for x in d)}/{len(d)}')
    out['C_vs_shipped'] = {'n': int(len(g)), **cmp, 'd_xp_ship': d}
    # D. one MIXED list: does a per-group calibration (target = a_G + s_G * prediction, fit
    # leave-one-pair-out) order a list that mixes MLB-time and minor-league pitchers better than
    # the raw prediction, or than a level shift alone (a_G + prediction)? Groups by MLB share.
    # Decision rule fixed before the run: 4 of 5 pairs AND pooled delta over 2 SE.
    sd = sc.assign(pred=base, G=np.select([sc.grp == 'small MiLB', sc.mlbN == 0, sc.mlbN <= sc.nAll / 2],
                                          ['small', 'noMLB', 'MLBminor'], 'MLBprimary'))
    def calib(mode):
        outp = pd.Series(np.nan, index=sd.index)
        for hp in sorted(sd.pair.unique()):
            tr, te = sd[sd.pair != hp], sd[sd.pair == hp]
            for G, tg in tr.groupby('G'):
                m = te.G == G
                if mode == 'shift':
                    a, b = np.average(tg.T_nRA9 - tg.pred, weights=tg.tw), 1.0
                else:
                    X = np.column_stack([np.ones(len(tg)), tg.pred])
                    w = np.sqrt(tg.tw.values)
                    a, b = np.linalg.lstsq(X * w[:, None], tg.T_nRA9.values * w, rcond=None)[0]
                outp[te.index[m]] = a + b * te.pred[m]
        return outp
    arms = {'raw': sd.pred, 'shift': calib('shift'), 'slope+shift': calib('full')}
    pairs = sorted(sd.pair.unique())
    rr = {k: [wr(v[sd.pair == hp], sd.T_nRA9[sd.pair == hp], sd.tw[sd.pair == hp], sd.role[sd.pair == hp])
              for hp in pairs] for k, v in arms.items()}
    full = {}
    for _, x in sd.groupby('G'):
        X = np.column_stack([np.ones(len(x)), x.pred]); w = np.sqrt(x.tw.values)
        full[x.G.iloc[0]] = np.round(np.linalg.lstsq(X * w[:, None], x.T_nRA9.values * w, rcond=None)[0], 3).tolist()
    rngd = np.random.default_rng(1)
    resd = {}
    for k in ('shift', 'slope+shift'):
        d = [a - b for a, b in zip(rr[k], rr['raw'])]
        boots = []
        for _ in range(B):
            ds = []
            for hp in pairs:
                idx = sd.index[sd.pair == hp]
                i = rngd.choice(idx, len(idx))
                h = sd.loc[i]
                ds.append(wr(arms[k][i], h.T_nRA9, h.tw, h.role) - wr(arms['raw'][i], h.T_nRA9, h.tw, h.role))
            boots.append(np.mean(ds))
        se = float(np.std(boots))
        resd[k] = {'r': [round(x, 4) for x in rr[k]], 'd': round(float(np.mean(d)), 4), 'se': round(se, 4),
                   'wins': int(sum(x > 0 for x in d)), 'adopt': bool(sum(x > 0 for x in d) >= 4 and np.mean(d) > 2 * se)}
        print(f'D. mixed list {k:12s} r {resd[k]["r"]} d {resd[k]["d"]:+.4f} se {resd[k]["se"]:.4f} '
              f'wins {resd[k]["wins"]}/{len(pairs)} adopt {resd[k]["adopt"]}')
    print('   raw r', [round(x, 4) for x in rr['raw']], '| all-pair fits (a, s) by group', full)
    out['D_mixed'] = {**resd, 'raw_r': [round(x, 4) for x in rr['raw']], 'fits_all_pairs': full}
    # E. pitchers with 250+ MLB BF in Y (rank_small.build leaves them out): held-out r of the
    # xallm spec and the calibration fit (a, s) for that group, so a list that carries MLB
    # regulars does not borrow the under-250 slope. Same frame recipe, threshold lifted.
    big = build_big()
    big = big[(big.age >= 25) & (big.tw > 0) & big.T_nRA9.notna()].dropna(subset=RS.SPEC)
    trn = fr[(fr.tw > 0) & fr.T_nRA9.notna()].dropna(subset=RS.SPEC)
    pb = pd.Series(np.nan, index=big.index)
    for hp in sorted(big.pair.unique()):
        te = big[big.pair == hp]
        pb[te.index], _ = RS.fit_predict_m(trn[trn.pair != hp], te, RS.SPEC, 'nRA9', RS.K)
    rb = [round(wr(pb[big.pair == hp], big.T_nRA9[big.pair == hp], big.tw[big.pair == hp], big.role[big.pair == hp]), 3)
          for hp in sorted(big.pair.unique())]
    fits = []
    for hp in sorted(big.pair.unique()):
        x = big[big.pair != hp]; X = np.column_stack([np.ones(len(x)), pb[x.index]]); w = np.sqrt(x.tw.values)
        fits.append(np.linalg.lstsq(X * w[:, None], x.T_nRA9.values * w, rcond=None)[0].round(3).tolist())
    X = np.column_stack([np.ones(len(big)), pb]); w = np.sqrt(big.tw.values)
    fa = np.linalg.lstsq(X * w[:, None], big.T_nRA9.values * w, rcond=None)[0].round(3).tolist()
    print(f'E. MLB 250+ BF, n {len(big)}: held-out r per pair {rb}; calibration (a, s) all pairs {fa}; '
          f'leave-one-out fits {fits}')
    out['E_mlb_big'] = {'n': int(len(big)), 'r': rb, 'fit_all': fa, 'fits_lopo': fits}
    # F. AGE (2026-11-11, per Wally after the Mikolas question): the spec fit on every level
    # gives age +0.127 runs a year, which partly measures level (frame mean age 24). Refit the
    # spec on the free-agent POOL ONLY (age 25+, AAA top level or MLB-primary, plus the 250+
    # MLB rows of part E) and score a mixed list of that pool, groups calibrated leave-one-pair-
    # out as in part D, against the all-level fit. Rule fixed before the run: adopt the pool
    # fit unless it loses the pooled delta by more than 2 SE (it removes a measured bias; it
    # does not need to win on order).
    big2 = build_big()
    big2 = big2[(big2.age >= 25) & (big2.tw > 0) & big2.T_nRA9.notna()].dropna(subset=RS.SPEC)
    allf = pd.concat([fr, big2], ignore_index=True)
    allf['top'] = allf['top'].fillna('MLB')
    ok = (allf.tw > 0) & allf.T_nRA9.notna() & allf[RS.SPEC].notna().all(axis=1)
    inpool = (allf.age >= 25) & ((allf.top == 'AAA') | allf.grp.isin(['MLB-primary', 'MLB-big']))
    ev = allf[ok & inpool].copy()
    ev['G'] = np.select([ev.grp == 'small MiLB', ev.mlbN == 0, ev.mlbN <= ev.nAll / 2, ev.mlbN >= 250],
                        ['small', 'noMLB', 'MLBminor', 'MLBbig'], 'MLBprimary')
    preds = {}
    ages = {}
    for arm, trmask in (('all-level fit', ok), ('pool fit', ok & inpool)):
        col = pd.Series(np.nan, index=ev.index)
        ag = []
        for hp in sorted(ev.pair.unique()):
            tr = allf[trmask & (allf.pair != hp)]
            for small in (True, False):
                te = ev[(ev.pair == hp) & ((ev.grp == 'small MiLB') == small)]
                if len(te):
                    col[te.index], b = RS.fit_predict_m(tr, te, RS.SPEC, 'nRA9', RS.K_SMALL if small else RS.K)
                    if not small:
                        ag.append(round(float(b[-1]), 3))
        ages[arm] = ag
        cal = pd.Series(np.nan, index=ev.index)
        for hp in sorted(ev.pair.unique()):
            trn, te = ev[ev.pair != hp], ev[ev.pair == hp]
            for G, tg in trn.groupby('G'):
                m = te.G == G
                X = np.column_stack([np.ones(len(tg)), col[tg.index]]); w = np.sqrt(tg.tw.values)
                a, b = np.linalg.lstsq(X * w[:, None], tg.T_nRA9.values * w, rcond=None)[0]
                cal[te.index[m]] = a + b * col[te.index[m]]
        preds[arm] = (col, cal)
    pairs = sorted(ev.pair.unique())
    rr = {arm: [wr(c[ev.pair == hp], ev.T_nRA9[ev.pair == hp], ev.tw[ev.pair == hp], ev.role[ev.pair == hp])
                for hp in pairs] for arm, (_, c) in preds.items()}
    d = [a - b for a, b in zip(rr['pool fit'], rr['all-level fit'])]
    rngf = np.random.default_rng(2)
    boots = []
    for _ in range(B):
        ds = []
        for hp in pairs:
            idx = ev.index[ev.pair == hp]
            i = rngf.choice(idx, len(idx))
            h = ev.loc[i]
            ds.append(wr(preds['pool fit'][1][i], h.T_nRA9, h.tw, h.role)
                      - wr(preds['all-level fit'][1][i], h.T_nRA9, h.tw, h.role))
        boots.append(np.mean(ds))
    se = float(np.std(boots))
    # calibration fits on all pairs for the pool fit (what rank_all applies)
    colp = preds['pool fit'][0]
    fits = {}
    for G, g in ev.groupby('G'):
        X = np.column_stack([np.ones(len(g)), colp[g.index]]); w = np.sqrt(g.tw.values)
        fits[G] = np.round(np.linalg.lstsq(X * w[:, None], g.T_nRA9.values * w, rcond=None)[0], 3).tolist()
    print(f'F. mixed list incl. 250+ MLB, n {len(ev)}: all-level fit r {np.round(rr["all-level fit"], 4)} | '
          f'pool fit r {np.round(rr["pool fit"], 4)} | d {np.mean(d):+.4f} se {se:.4f} wins {sum(x > 0 for x in d)}/{len(d)}'
          f' | adopt {bool(np.mean(d) > -2 * se)}')
    print(f'   age coefficient per held-out fit: all-level {ages["all-level fit"]}, pool {ages["pool fit"]}')
    print(f'   pool-fit calibration (a, s) by group, all pairs: {fits}')
    out['F_age_pool'] = {'n': int(len(ev)), 'r': {k: [round(x, 4) for x in v] for k, v in rr.items()},
                         'd': round(float(np.mean(d)), 4), 'se': round(se, 4), 'ages': ages, 'cal_pool_fit': fits,
                         'adopt': bool(np.mean(d) > -2 * se)}
    tmp = os.path.join(D, '_rank_sample_check.json.tmp')
    json.dump(out, open(tmp, 'w'), indent=1)
    os.replace(tmp, os.path.join(D, '_rank_sample_check.json'))


if __name__ == '__main__':
    main()
