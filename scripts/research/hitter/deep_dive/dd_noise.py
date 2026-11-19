"""dd_noise.py - sampling noise of one Process+ grade as a function of PA, on the RELEASED atoms
(BB: air EV95 at 55/45, unshrunk; SD: mix-neutral over zone x two-strike; CT: raw).

Design: each season's dates are split at random into two halves (3 seeds). Both halves are scored against the
FULL season's anchors and standardization. For a hitter, (half A - half B) has variance 2 * SE^2 at the half's PA.
The squared half-differences are fitted as SE_z^2 = a + b / PA (composite z units), six seasons, with a
leave-one-season-out check of b and a check of the exponent. The site shows SE_z * (points per composite z).
.venv/bin/python scripts/research/hitter/deep_dive/dd_noise.py"""
import sys, os
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dd_lib as L
import dd_bb_air as BA

W = L.W
RES = {}


def sd_mix(e, lgw):
    e = e[e.sd_el]; s2 = (e.s == 2).astype(int)
    hm = e.groupby(['bid', 'zone', s2], observed=True).dv.mean().rename('m').reset_index()
    hm['w'] = pd.MultiIndex.from_frame(hm[['zone', 's']]).map(lgw).values.astype(float)
    return (hm.m * hm.w).groupby(hm.bid).sum() / hm.w.groupby(hm.bid).sum()


def score(d, lgz, lgw, anc, Z=None):
    A = L.atoms(d, lgz)
    F = BA.frame(d[d.bip][['bid', 'date', 'xw', 'ev', 'la', 'wv']])
    A['bb'] = BA.blend(F, anc, BA.WN).reindex(A.index)
    A['sd'] = sd_mix(d, lgw).reindex(A.index)
    A['ct'] = A.ct_raw
    if Z is not None:
        A['p'] = sum(w * (A[k] - Z[k][0]) / Z[k][1] for w, k in zip(W, ('bb', 'sd', 'ct')))
    return A


def main():
    rows = []
    for Y in L.SEASONS:
        S = L.load(Y); d = S['df']; e = d[d.sd_el]
        lgw = e.groupby(['zone', (e.s == 2).astype(int)], observed=True).size() / len(e)
        Ffull = BA.frame(d[d.bip][['bid', 'date', 'xw', 'ev', 'la', 'wv']]); anc = BA.anchors(Ffull)
        A = score(d, S['lgz'], lgw, anc)
        ok = (A.nbip >= 30) & (A.n_dec >= 190) & (A.n_sw >= 66) & A.bb.notna() & A.sd.notna() & A.ct.notna()
        q = ok & (A.pa >= L.QUAL_PA)
        Z = {k: (float(A.loc[q, k].mean()), float(A.loc[q, k].std())) for k in ('bb', 'sd', 'ct')}
        A['p'] = sum(w * (A[k] - Z[k][0]) / Z[k][1] for w, k in zip(W, ('bb', 'sd', 'ct')))
        print(f"{Y}: qualified {int(q.sum())}, SD of the composite z in the qualified pool {A.p[q].std():.3f}", flush=True)
        dates = np.array(sorted(d.date.unique()))
        for seed in range(3):
            rng = np.random.default_rng(1000 * seed + Y); hs = set(rng.choice(dates, len(dates) // 2, replace=False)); m = d.date.isin(hs)
            a = score(d[m], S['lgz'], lgw, anc, Z); b = score(d[~m], S['lgz'], lgw, anc, Z)
            k = a.index.intersection(b.index); a, b = a.loc[k], b.loc[k]
            fl = (a.nbip >= 5) & (b.nbip >= 5) & (a.n_dec >= 25) & (b.n_dec >= 25) & (a.n_sw >= 10) & (b.n_sw >= 10) & a.p.notna() & b.p.notna() & (a.pa >= 20) & (b.pa >= 20)
            rows.append(pd.DataFrame({'Y': Y, 'seed': seed, 'n': ((a.pa + b.pa) / 2)[fl].values, 'd2': ((a.p - b.p) ** 2 / 2)[fl].values,
                                      **{f'd2_{c}': (((a[c] - b[c]) / Z[c][1]) ** 2 / 2)[fl].values for c in ('bb', 'sd', 'ct')}}))
        L.drop(Y)
    R = pd.concat(rows, ignore_index=True)
    R.to_pickle(os.path.join(L.HDD, 'noise_rows.pkl'))
    print(f"\nrows {len(R)} (hitter x season x seed), half-sample PA {R.n.min():.0f}-{R.n.max():.0f}")
    bands = [(20, 40), (40, 60), (60, 80), (80, 100), (100, 130), (130, 160), (160, 200), (200, 250), (250, 300), (300, 350), (350, 420)]
    print("half-sample PA band | n | SE of one grade, composite z | implied b = SE^2 * PA | atoms' SE in their own qualified-pool SD units (bb / sd / ct)")
    for lo, hi in bands:
        g = R[(R.n >= lo) & (R.n < hi)]
        if len(g) < 30:
            continue
        se = np.sqrt(g.d2.mean())
        print(f"   {lo:3d}-{hi:3d} | {len(g):5d} | {se:.4f} | {g.d2.mean() * g.n.mean():7.2f} | " + " / ".join(f"{np.sqrt(g['d2_' + c].mean()):.3f}" for c in ('bb', 'sd', 'ct')))

    def fit(g, intercept=True):
        x = 1.0 / g.n.values; y = g.d2.values
        if intercept:
            Xm = np.c_[np.ones(len(x)), x]; a, b = np.linalg.lstsq(Xm, y, rcond=None)[0]; return float(a), float(b)
        return 0.0, float((x * y).sum() / (x * x).sum())
    a, b = fit(R); a0, b0 = fit(R, False)
    print(f"\nfit SE_z^2 = a + b / PA: a {a:+.5f}, b {b:.3f} | through the origin: b {b0:.3f}")
    lg = R[R.d2 > 0]
    bm = lg.groupby(pd.cut(lg.n, [20, 30, 45, 65, 90, 130, 180, 250, 420])).agg(n=('n', 'mean'), v=('d2', 'mean')).dropna()
    ex = np.polyfit(np.log(bm.n), np.log(bm.v), 1)[0]
    print(f"exponent of variance on PA from the binned curve (theory -1): {ex:.3f}")
    print("leave-one-season-out (b fitted on five seasons, origin form): held-out ratio of observed to predicted variance")
    lo = []
    for Y in L.SEASONS:
        _, bt = fit(R[R.Y != Y], False); h = R[R.Y == Y]; ratio = float(h.d2.sum() / (bt / h.n).sum()); lo.append((bt, ratio))
        print(f"   {Y}: b {bt:.3f}, observed / predicted {ratio:.3f}")
    print("by seed (b, origin form): " + " ".join(f"{fit(R[R.seed == s], False)[1]:.3f}" for s in range(3)))
    print("observed / predicted variance by half-sample PA band, origin form: " + " ".join(
        f"{lo_}-{hi}:{R[(R.n >= lo_) & (R.n < hi)].d2.sum() / (b0 / R[(R.n >= lo_) & (R.n < hi)].n).sum():.2f}" for lo_, hi in bands if len(R[(R.n >= lo_) & (R.n < hi)]) >= 30))
    print("with the intercept: " + " ".join(
        f"{lo_}-{hi}:{R[(R.n >= lo_) & (R.n < hi)].d2.sum() / (a + b / R[(R.n >= lo_) & (R.n < hi)].n).sum():.2f}" for lo_, hi in bands if len(R[(R.n >= lo_) & (R.n < hi)]) >= 30))
    import json
    md = json.load(open(os.path.join(L.ROOT, 'data', 'metadata_rs.json'))); st = md['processPlusStandardization']
    ppz = st['scale'] * st['wrcScaleMatch']['factor']
    print(f"\npoints per composite z on the live board (scale x factor): {ppz:.2f}")
    for nm, aa, bb in (('origin form', 0.0, b0), ('with intercept', a, b)):
        print(f" {nm}: plus-minus in Process+ points at PA 50/100/150/200/300/450/600/700: " + " ".join(f"{ppz * np.sqrt(max(aa + bb / n, 0)):.1f}" for n in (50, 100, 150, 200, 300, 450, 600, 700)))
    RES.update(a=a, b=b, b_origin=b0, exponent=float(ex), loso=lo, ppz=ppz)
    L.save('res_noise.json', RES)


if __name__ == '__main__':
    main()
