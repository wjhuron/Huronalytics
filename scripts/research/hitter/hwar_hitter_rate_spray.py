"""hwar_hitter_rate_spray.py — does a spray-aware batting rate beat the shipped hWAR basis (2026-09-15)?

Extends hwar_hitter_rate_validation.py (same PA tables, park pass-through, objectives and gates)
with two candidates the 2026-09-05 validation never tested:
  xsp   the shipped xwOBAsp lookup: league wOBAcon by spray direction x LA bin x bats, same season,
        SACQ_MIN_BIP 20, hand table first then pooled (process_data.py sacq_lookup); no EV at all.
        A BIP with no lookup (bunt, no hit coordinates) falls back to Savant xwOBA.
  xwr   Savant xwOBA + the full spray residual on EVERY ball in play: zone wOBAcon minus LA-only
        wOBAcon (process_data.py compute_sprayval), the generalization of the shipped pulled-air
        term (xhb) from one cell to all 6 directions x 12 LA bins.
Both tables are built on the season's own league BIP, the way production builds them.
Also reports the PERSISTENCE of the wOBA-minus-rate gap (r of the gap in y with the gap in y+1,
>= 300 PA both sides): the Altuve question, whether a hitter who beats the rate keeps beating it.
Usage: python3 scripts/research/hitter/hwar_hitter_rate_spray.py
Output: console + data/_hwar_hitter_rate_spray.json
"""
import gc, json, os, sys
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'era'))
from pipeline.utils import K_EVENTS, BB_EVENTS, HBP_EVENTS, spray_angle, spray_direction
import hwar_hitter_rate_validation as V
import war_rate_validation as W
import era_battery_build as EB
import war_pullair_fixed as PX

SEASONS = V.SEASONS; SCALE = V.SCALE; N0_GRID = V.N0_GRID; GATE_HALF, GATE_CAL = V.GATE_HALF, V.GATE_CAL
CANDS = ['woba', 'xw', 'xhb', 'xsp', 'xwr']
LA_BINS = [(-999, -10), (-10, 0), (0, 5), (5, 10), (10, 15), (15, 20),
           (20, 25), (25, 30), (30, 35), (35, 40), (40, 50), (50, 999)]   # process_data SACQ bins
SACQ_MIN_BIP = 20
ALTUVE = '514888'


def _la_bin(la):
    if la is None or np.isnan(la):
        return None
    for i, (lo, hi) in enumerate(LA_BINS):
        if lo <= la < hi:
            return i
    return None


def spray_columns(ev, xw, la, bbt, hcx, hcy, stand, is_bip):
    """Per-PA xsp and xwr on the season's own league table (hand first, pooled fallback)."""
    w_act = pd.Series(ev).map(PX.W_ACT).fillna(0.0).values
    n = len(ev)
    key_h, key_p, key_lh, key_lp = [None] * n, [None] * n, [None] * n, [None] * n
    for i in range(n):
        if not is_bip[i]:
            continue
        b = bbt[i]
        if b is None or (isinstance(b, float) and np.isnan(b)) or 'bunt' in str(b).lower() or 'bunt' in str(ev[i]).lower():
            continue
        s = stand[i]
        if s not in ('L', 'R'):
            continue
        d = spray_direction(spray_angle(hcx[i], hcy[i]) if not (np.isnan(hcx[i]) or np.isnan(hcy[i])) else None, s)
        lb = _la_bin(la[i])
        if d is None or lb is None:
            continue
        key_h[i] = (d, lb, s); key_p[i] = (d, lb); key_lh[i] = (lb, s); key_lp[i] = (lb,)
    tabs = []
    for keys in (key_h, key_p, key_lh, key_lp):
        acc = defaultdict(lambda: [0.0, 0])
        for k, v in zip(keys, w_act):
            if k is not None:
                a = acc[k]; a[0] += v; a[1] += 1
        tabs.append({k: a[0] / a[1] for k, a in acc.items() if a[1] >= SACQ_MIN_BIP})
    th, tp, tlh, tlp = tabs

    def look(t1, k1, t2, k2):
        if k1 is not None and k1 in t1:
            return t1[k1]
        if k2 is not None and k2 in t2:
            return t2[k2]
        return None
    xsp = xw.copy(); xwr = xw.copy(); nz = 0
    for i in range(n):
        if key_h[i] is None:
            continue
        z = look(th, key_h[i], tp, key_p[i]); l = look(tlh, key_lh[i], tlp, key_lp[i])
        if z is not None:
            xsp[i] = z
        if z is not None and l is not None:
            xwr[i] = xw[i] + (z - l); nz += 1
    return xsp, xwr, nz, len(th), len(tp)


_orig_finish = V.finish


def finish(y, bid, date, ev, xw, la, bbt, hcx, hcy, stand, venue):
    df, share = _orig_finish(y, bid, date, ev, xw, la, bbt, hcx, hcy, stand, venue)
    evs = pd.Series(ev)
    is_bip = ~(evs.isin(BB_EVENTS) | evs.isin(HBP_EVENTS) | evs.isin(K_EVENTS)).values
    xw0 = np.nan_to_num(np.asarray(xw, float), nan=0.0)
    xsp, xwr, nz, nh, npool = spray_columns(ev, xw0, np.asarray(la, float), bbt, np.asarray(hcx, float), np.asarray(hcy, float), stand, is_bip)
    # non-BIP PAs keep the K / BB / HBP values the base candidates use
    xsp = np.where(is_bip, xsp, df['xw'].values); xwr = np.where(is_bip, xwr, df['xw'].values)
    df['xsp'] = xsp; df['xwr'] = xwr
    print(f"    {y}: spray residual on {nz} of {int(is_bip.sum())} BIP, {nh} hand cells / {npool} pooled cells at >= {SACQ_MIN_BIP}", flush=True)
    return df, share


V.finish = finish


def main():
    out = {}
    P, SHARE, LG, RPA = {}, {}, {}, {}
    print("PER-PA TABLES")
    for y in SEASONS:
        P[y], SHARE[y] = V.pa_savant(y) if y < 2026 else V.pa_sheet(y)
        ph = V.T[str(y)]['pitchers']; RPA[y] = sum(v['r'] for v in ph.values()) / sum(v['bf'] for v in ph.values())
        LG[y] = {sc: {c: float(P[y].loc[m, c].mean()) for c in CANDS} for sc, m in (('full', slice(None)), ('h1', P[y]['h1'].values), ('h2', ~P[y]['h1'].values))}
        print(f"  {y}: {len(P[y])} PA, {P[y]['bid'].nunique()} batters, league " + " ".join(f"{c} {LG[y]['full'][c]:.4f}" for c in CANDS), flush=True)
        gc.collect()
    S = {}
    for y in SEASONS:
        S[y] = {}
        for sc, m in (('full', np.ones(len(P[y]), bool)), ('h1', P[y]['h1'].values), ('h2', ~P[y]['h1'].values)):
            g = P[y][m].groupby('bid').agg(**{c: (c, 'mean') for c in CANDS}, n=('woba', 'size'), pf=('pf', 'mean'))
            g['pf'] = g['pf'].fillna(1.0); S[y][sc] = g

    def sh(y, sc, c, n0):
        g = S[y][sc]; return (g[c] * g['n'] + n0 * LG[y][sc][c]) / (g['n'] + n0)

    def full_park(y, g):
        return (g['pf'] - 1.0) * RPA[y] * SCALE[y]

    print("\nPARK PASS-THROUGH (LOSO, >= 300 PA; 1.0 = the published factor)")
    PASS = {}
    for c in CANDS:
        folds = []
        for hold in SEASONS:
            x, yv, w = [], [], []
            for y in SEASONS:
                if y == hold:
                    continue
                g = S[y]['full']; g = g[g['n'] >= GATE_CAL]
                x += list(full_park(y, g)); yv += list(g[c] - LG[y]['full'][c]); w += list(g['n'])
            folds.append(W.wls_slope(np.array(x), np.array(yv), np.array(w, float)))
        PASS[c] = float(np.mean(folds)); out[f'pass_{c}'] = folds
        print(f"  {c:5} folds " + " ".join(f"{f:.3f}" for f in folds) + f"  mean {PASS[c]:.3f}")

    def evaluate(c, n0, tag=None):
        res = {'rel': [], 'ros': [], 'nxt300': [], 'nxt150': [], 'calib': []}
        for y in SEASONS:
            a, b = S[y]['h1'], S[y]['h2']; ks = a.index[a['n'] >= GATE_HALF].intersection(b.index[b['n'] >= GATE_HALF])
            r1 = sh(y, 'h1', c, n0).loc[ks]; res['rel'].append(W.pear(r1.values, sh(y, 'h2', c, n0).loc[ks].values))
            res['ros'].append(W.pear(r1.values, b.loc[ks, 'woba'].values))
            g = S[y]['full']; ks = g.index[g['n'] >= GATE_CAL]
            adj = (sh(y, 'full', c, n0) - PASS[c] * full_park(y, g)).loc[ks]
            res['calib'].append(float(np.polyfit(adj.values, g.loc[ks, 'woba'].values, 1)[0]))
        for gate in (300, 150):
            for y in SEASONS[:-1]:
                g, g2 = S[y]['full'], S[y + 1]['full']; ks = g.index[g['n'] >= gate].intersection(g2.index[g2['n'] >= gate])
                adj = (sh(y, 'full', c, n0) - PASS[c] * full_park(y, g)).loc[ks]
                res[f'nxt{gate}'].append(W.pear(adj.values, g2.loc[ks, 'woba'].values))
        name = tag or f'{c} N0={n0}'; out[name] = res
        print(f"  {name:14} rel {np.mean(res['rel']):.3f}  nxt300 {np.mean(res['nxt300']):.3f}  nxt150 {np.mean(res['nxt150']):.3f}  "
              f"ros {np.mean(res['ros']):.3f}  calib {np.mean(res['calib']):.3f}", flush=True)
        return res

    print("\nCANDIDATES, unshrunk (N0 = 0):")
    base = {c: evaluate(c, 0) for c in CANDS}

    print("\nDISAGREEMENT SET (50 batters/season where xw and woba differ most, >= 300 PA both years; r with next-season wOBA)")
    dis = {c: [] for c in CANDS}
    for y in SEASONS[:-1]:
        g, g2 = S[y]['full'], S[y + 1]['full']; ks = g.index[g['n'] >= 300].intersection(g2.index[g2['n'] >= 300])
        top = (g.loc[ks, 'xw'] - g.loc[ks, 'woba']).abs().sort_values(ascending=False).index[:50]
        for c in CANDS:
            dis[c].append(W.pear((g.loc[top, c] - PASS[c] * full_park(y, g.loc[top])).values, g2.loc[top, 'woba'].values))
    for c in CANDS:
        print(f"  {c:5} " + " ".join(f"{v:.3f}" for v in dis[c]) + f"  mean {np.mean(dis[c]):.3f}")
    out['disagree'] = dis

    print("\nPAIRED vs xhb, the shipped basis (unshrunk): mean delta, wins/n")
    for c in ('xsp', 'xwr', 'xw', 'woba'):
        line = []
        for k in ('rel', 'nxt300', 'nxt150', 'ros', 'calib'):
            d = np.array(base[c][k]) - np.array(base['xhb'][k]); line.append(f"{k} {d.mean():+.4f} ({int((d > 0).sum())}/{len(d)})")
        print(f"  {c:5} " + "  ".join(line))

    print("\nGAP PERSISTENCE: r of (wOBA - rate) in y with (wOBA - rate) in y+1, >= 300 PA both sides. 0 = the gap is noise the rate should ignore")
    pers = {c: [] for c in CANDS if c != 'woba'}
    for y in SEASONS[:-1]:
        g, g2 = S[y]['full'], S[y + 1]['full']; ks = g.index[g['n'] >= 300].intersection(g2.index[g2['n'] >= 300])
        for c in pers:
            pers[c].append(W.pear((g.loc[ks, 'woba'] - g.loc[ks, c]).values, (g2.loc[ks, 'woba'] - g2.loc[ks, c]).values))
    for c in pers:
        print(f"  {c:5} " + " ".join(f"{v:.3f}" for v in pers[c]) + f"  mean {np.mean(pers[c]):.3f}")
    out['persist'] = pers

    print("\nALTUVE per season (full, unshrunk, rate minus league):")
    alt = {}
    for y in SEASONS:
        g = S[y]['full']
        if ALTUVE in g.index:
            alt[y] = {c: float(g.loc[ALTUVE, c] - LG[y]['full'][c]) for c in CANDS}; alt[y]['n'] = int(g.loc[ALTUVE, 'n'])
            print(f"  {y} n {alt[y]['n']:3d} " + " ".join(f"{c} {alt[y][c]:+.4f}" for c in CANDS))
    out['altuve'] = alt

    print("\nN0 SWEEP for the spray candidates (reliability inflates under shrinkage: diagnostic; nxt and ros decide)")
    for c in ('xhb', 'xsp', 'xwr'):
        print(f"  {c}:")
        for n0 in N0_GRID:
            evaluate(c, n0)
    json.dump(out, open(os.path.join(ROOT, 'data', '_hwar_hitter_rate_spray.json'), 'w'), indent=1, default=float)
    print("wrote data/_hwar_hitter_rate_spray.json")


if __name__ == '__main__':
    main()
