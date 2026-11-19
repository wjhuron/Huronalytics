"""dd_sd2.py - follow-ups to tests 6 and 7: SD+ against plain chase rate; count-partition sweep for the
mix-neutral aggregation with a permuted-label placebo.  .venv/bin/python scripts/research/hitter/deep_dive/dd_sd2.py [t6b t7b]"""
import sys, os
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dd_lib as L

AT = L.all_atoms()
RES = {}


def neutral(e, keys):
    lgw = e.groupby(keys, observed=True).size() / len(e)
    hm = e.groupby(['bid'] + keys, observed=True).dv.mean().rename('m').reset_index()
    hm['w'] = (pd.MultiIndex.from_frame(hm[keys]).map(lgw) if len(keys) > 1 else hm[keys[0]].map(lgw)).values.astype(float)
    return (hm.m * hm.w).groupby(hm.bid).sum() / hm.w.groupby(hm.bid).sum()


def t6b():
    print("\n=== T6b does SD+ beat plain rates in the composite? (variant replaces the SD atom; shipped weights) ===")
    for nm, fn in (('minus chase rate', lambda A: -A.chase), ('zswing minus chase', lambda A: A.zswing - A.chase), ('walk rate (outcome, reference)', lambda A: A.bbr)):
        var = {Y: fn(AT[Y][0]) for Y in L.SEASONS}
        RES['t6b ' + nm] = L.eval_var(AT, 'sd', var, label=nm)
    # partial value of SD given chase, and of chase given SD, for next-season BB% and wOBA
    rows = []
    for y0, y1 in L.PAIRS:
        A, B = AT[y0][0], AT[y1][0]; a = A[A.ok & (A.pa >= 300)]; w = B.pa.reindex(a.index).fillna(0).values
        for tgt in ('bbr', 'woba'):
            y = B[tgt].reindex(a.index).values; m = np.isfinite(y) & (w > 0)
            def part(x, c):
                rx = x[m] - np.polyval(np.polyfit(c[m], x[m], 1), c[m]); ry = y[m] - np.polyval(np.polyfit(c[m], y[m], 1), c[m]); return L.wcorr(rx, ry, w[m])
            rows.append(dict(pair=y0, tgt=tgt, sd_given_chase=part(a.sd_raw.values, a.chase.values), chase_given_sd=part(a.chase.values, a.sd_raw.values)))
    T = pd.DataFrame(rows).groupby('tgt')[['sd_given_chase', 'chase_given_sd']].mean(); print("partial r with next-season target:"); print(T.round(3).to_string())


def t7b():
    print("\n=== T7b mix-neutral aggregation of SD: which count partition (shipped = zone only) ===")
    parts = {'zone only (shipped)': None, 'zone x two-strike flag': ['zone', 's2'], 'zone x strikes': ['zone', 's'], 'zone x balls': ['zone', 'b'],
             'zone x ahead/even/behind': ['zone', 'st'], 'zone x count (60)': ['zone', 'b', 's'],
             'PLACEBO zone x permuted strikes': ['zone', 'sp'], 'PLACEBO zone x permuted count': ['zone', 'bp', 'sp']}
    V = {k: {} for k in parts}
    REL = {k: [] for k in parts}
    for Y in L.SEASONS:
        S = L.load(Y); d = S['df']; e = d[d.sd_el][['bid', 'date', 'zone', 'b', 's', 'dv']].copy()
        e['s2'] = (e.s == 2).astype(int); e['st'] = np.sign(e.b - e.s).astype(int)
        rng = np.random.default_rng(Y); idx = rng.permutation(len(e)); e['sp'] = e.s.values[idx]; e['bp'] = e.b.values[idx]
        dates = np.array(sorted(e.date.unique())); hs = set(rng.choice(dates, len(dates) // 2, replace=False)); m = e.date.isin(hs)
        for k, keys in parts.items():
            keys = keys or ['zone']
            V[k][Y] = neutral(e, keys)
            a, b = neutral(e[m], keys), neutral(e[~m], keys); na = e[m].groupby('bid', observed=True).size(); nb = e[~m].groupby('bid', observed=True).size()
            kk = [i for i in a.index.intersection(b.index) if na[i] >= 300 and nb[i] >= 300]
            REL[k].append(L.wcorr(a[kk], b[kk]))
        L.drop(Y)
    for k in parts:
        A0 = AT[2025][0]
        print(f"{k}: split-half r {np.mean(REL[k]):.4f}; y-t-y r {L.yy({Y: V[k][Y][AT[Y][0].pa.reindex(V[k][Y].index) >= 300] for Y in L.SEASONS})[0]:.4f}")
        if k != 'zone only (shipped)':
            RES['t7b ' + k] = L.eval_var(AT, 'sd', V[k], label=k[:26])
    # forward validity of the atom itself
    print("--- atom-level: r with next-season BB%, wOBA (gate pa>=300, weights Y+1 PA) ---")
    for k in parts:
        rb, rw = [], []
        for y0, y1 in L.PAIRS:
            A, B = AT[y0][0], AT[y1][0]; a = A[A.ok & (A.pa >= 300)]; w = B.pa.reindex(a.index).fillna(0)
            rb.append(L.wcorr(V[k][y0].reindex(a.index), B.bbr.reindex(a.index), w)); rw.append(L.wcorr(V[k][y0].reindex(a.index), B.woba.reindex(a.index), w))
        print(f"   {k:34s} BB% {np.mean(rb):+.4f}  wOBA {np.mean(rw):+.4f} {np.round(rw, 3)}")
    # re-sweep composite weights with the strikes partition; movers in 2026
    var = V['zone x strikes']
    best = None
    for wb in np.arange(.44, .61, .01):
        for ws in np.arange(.10, .30, .01):
            wc = 1 - wb - ws; rs = []
            for Y in L.SEASONS:
                A = AT[Y][0]; a = A[A.ok & (A.pa >= 300)]; v = var[Y].reindex(a.index); q = a.pa >= L.QUAL_PA
                rs.append(L.wcorr(wb * a.z_bb + ws * (v - v[q].mean()) / v[q].std() + wc * a.z_ct, a.woba))
            if best is None or np.mean(rs) > best[0]:
                best = (float(np.mean(rs)), round(wb, 2), round(ws, 2), round(wc, 2))
    print(f"composite weights re-swept with the strikes partition (DESC pa>=300): best r {best[0]:.4f} at {best[1]}/{best[2]}/{best[3]}")
    A = AT[2026][0]; a = A[A.ok & (A.pa >= 300)].copy(); v = var[2026].reindex(a.index); lg = float(np.average(v, weights=a.n_dec)); lg0 = float(np.average(a.sd_raw, weights=a.n_dec))
    a['sd_new'] = 100 * v / lg; a['sd_old'] = 100 * a.sd_raw / lg0; a['d'] = a.sd_new - a.sd_old
    print(f"2026 movers in SD ratio points (unshrunk, pa>=300): SD of change {a.d.std():.1f}, max |change| {a.d.abs().max():.1f}; r(change, K%) {L.wcorr(a.d, a.k):+.3f}")
    import json
    lb = json.load(open(os.path.join(L.ROOT, 'data', 'hitter_leaderboard_rs.json'))); nm = {str(int(r['mlbId'])): r['hitter'] for r in lb if r.get('mlbId') is not None}
    t = a.sort_values('d'); print("   biggest fallers:", [(nm.get(i, i), round(float(x), 1)) for i, x in t.d.head(6).items()]); print("   biggest risers:", [(nm.get(i, i), round(float(x), 1)) for i, x in t.d.tail(6).items()])
    w = [i for i in a.index if 'Wood, James' == nm.get(i)]
    if w:
        print("   James Wood:", a.loc[w, ['sd_old', 'sd_new', 'k', 'pa']].round(2).to_dict('records'))


if __name__ == '__main__':
    which = sys.argv[1:] or ['t6b', 't7b']
    for t in which:
        globals()[t]()
    L.save('res_sd2_' + '_'.join(which) + '.json', RES)
