"""hwar_disagreement_class.py — inside the class where xhb and wOBA disagree most, which rate forecasts next season? (2026-09-15)

hWAR prices batting on xhb (Savant per-PA xwOBA plus the pulled-air term); fWAR prices it on actual wOBA.
Population-wide the park-adjusted xhb beats wOBA at forecasting next-season wOBA (nxt300 r .539 vs .487,
hwar_hitter_rate_validation.py). The two disagree most on hitters who beat their xwOBA year after year
(Altuve 514888, Arenado, Arraez). This script asks whether xhb still wins INSIDE that class, i.e. whether
the disagreement is worth having exactly where it is largest.

Classes in season y come from PRIOR seasons only (no peeking at y or y+1).
  gap_k = (woba_k - lg_woba_k) - (xhb_k - lg_xhb_k): the batter's FULL season k, unshrunk, raw (not park-
          adjusted), batter-seasons with >= 300 PA only; lg_* is the PA-weighted league mean of that season
  two    beaters: gap > 0 in y-1 AND y-2; unders: gap < 0 in both; mixed: both available, signs differ
  three  the same on y-1, y-2 and y-3
  terc   PA-weighted mean gap over y-1 and y-2 (both >= 300 PA), split into per-season terciles low/mid/high
  any    every batter with the priors the scheme needs (the union of its classes); all: no prior needed
Rates: woba and xhb, park-adjusted as the validation does, c - PASS_c x (pf - 1) x runs/PA x SCALE, with
PASS the LOSO PA-weighted slope over 2021-2026 (replicated against data/_hwar_hitter_rate_validation.json),
unshrunk (N0 = 0) and at the shipped N0 = HWAR_N0_BAT toward the season league mean (shrink, then park).
Tests within class, batter >= 300 PA in y and in y+1 (y = 2023..2025; three: 2024..2025):
  r      Pearson r of the rate with actual wOBA in y+1
  rmse   RMSE of (rate_y - lg_rate_y) - (woba_{y+1} - lg_woba_{y+1}); the level is removed per season
  bias   mean of the same signed error; positive = the rate over-forecasts the class
and same-season (y = 2023..2026; three: 2024..2026), batter >= 300 PA in y:
  calib  slope of woba_y on the park-adjusted rate_y within the class
Per season and pooled (season-centered). Paired bootstrap SE (batters resampled within class and season,
seasons independent, the same draw for both rates) on the xhb minus woba difference of r, rmse and calib,
and on each rate's bias. A season enters the per-season mean only with >= MIN_N class members.
Also: class shares, the persistence of the gap into y and y+1 by class, and Altuve's class each season.
Usage: PYTHONHASHSEED=0 python3 scripts/research/hitter/hwar_disagreement_class.py
Output: console + data/_hwar_disagreement_class.json
"""
import gc, json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'era'))
import hwar_hitter_rate_validation as V
import war_rate_validation as W
from pipeline.hwar import HWAR_N0_BAT

SEASONS = V.SEASONS; SCALE = V.SCALE
GATE = 300; MIN_N = 15
CANDS = ['woba', 'xhb']
N0S = [0, HWAR_N0_BAT]
LIVE = 2026; ALTUVE = '514888'
BOOT = 1000; SEED = 0
PRIORS = {'two': 2, 'three': 3, 'terc': 2}
CLASSES = {'two': ['beaters', 'unders', 'mixed'], 'three': ['beaters', 'unders', 'mixed'], 'terc': ['low', 'mid', 'high']}
LAST_NXT = SEASONS[-2]                                   # 2025 -> 2026 is the last next-season pair
NXT_Y = {s: [y for y in SEASONS if y - k in SEASONS and y <= LAST_NXT] for s, k in PRIORS.items()}
SAME_Y = {s: [y for y in SEASONS if y - k in SEASONS] for s, k in PRIORS.items()}
METRICS = ['r', 'rmse', 'bias', 'calib']


def main():
    out = {'gate': GATE, 'min_n': MIN_N, 'n0s': N0S, 'boot': BOOT, 'seed': SEED, 'nxt_seasons': NXT_Y, 'same_seasons': SAME_Y}
    S, LG, RPA = {}, {}, {}
    print("PER-PA TABLES (hwar_hitter_rate_validation machinery)")
    for y in SEASONS:
        P, _ = V.pa_savant(y) if y < LIVE else V.pa_sheet(y)
        ph = V.T[str(y)]['pitchers']; RPA[y] = sum(v['r'] for v in ph.values()) / sum(v['bf'] for v in ph.values())
        LG[y] = {c: float(P[c].mean()) for c in CANDS}
        g = P.groupby('bid').agg(woba=('woba', 'mean'), xhb=('xhb', 'mean'), n=('woba', 'size'), pf=('pf', 'mean'))
        g['pf'] = g['pf'].fillna(1.0); S[y] = g
        print(f"  {y}: {len(P)} PA, {len(g)} batters, {int((g['n'] >= GATE).sum())} at >= {GATE} PA, "
              f"league woba {LG[y]['woba']:.4f} xhb {LG[y]['xhb']:.4f}, runs/PA {RPA[y]:.4f}", flush=True)
        del P; gc.collect()
    out['league'] = {y: LG[y] for y in SEASONS}

    def full_park(y, g):
        return (g['pf'] - 1.0) * RPA[y] * SCALE[y]

    print("\nPARK PASS-THROUGH (LOSO over six seasons, >= 300 PA; 1.0 = the published factor)")
    ref_path = os.path.join(ROOT, 'data', '_hwar_hitter_rate_validation.json')
    ref = json.load(open(ref_path)) if os.path.exists(ref_path) else {}
    PASS = {}
    for c in CANDS:
        folds = []
        for hold in SEASONS:
            x, yv, w = [], [], []
            for y in SEASONS:
                if y == hold:
                    continue
                g = S[y]; g = g[g['n'] >= GATE]
                x += list(full_park(y, g)); yv += list(g[c] - LG[y][c]); w += list(g['n'])
            folds.append(W.wls_slope(np.array(x), np.array(yv), np.array(w, float)))
        PASS[c] = float(np.mean(folds)); out[f'pass_{c}'] = folds
        chk = ''
        if ref.get(f'pass_{c}'):
            d = float(np.max(np.abs(np.array(folds) - np.array(ref[f'pass_{c}'])))); chk = f"  max |diff| vs validation JSON {d:.5f}"
        print(f"  {c:5} folds " + " ".join(f"{f:.3f}" for f in folds) + f"  mean {PASS[c]:.3f}{chk}")

    def rate(y, c, n0):
        """Shrunk toward the season league mean, then park-adjusted; every batter of season y."""
        g = S[y]; sh = (g[c] * g['n'] + n0 * LG[y][c]) / (g['n'] + n0)
        return sh - PASS[c] * full_park(y, g)

    # the gap of every batter-season at >= 300 PA, raw, league-centered
    GAP, NPA = {}, {}
    for y in SEASONS:
        g = S[y][S[y]['n'] >= GATE]
        GAP[y] = (g['woba'] - LG[y]['woba']) - (g['xhb'] - LG[y]['xhb']); NPA[y] = g['n'].astype(float)
    out['gap_sd'] = {y: float(GAP[y].std()) for y in SEASONS}
    print("\nGAP (woba - xhb, league-centered) SD across batters >= 300 PA: " + " ".join(f"{y} {GAP[y].std():.4f}" for y in SEASONS))
    print("  year-to-year r of the gap, >= 300 PA both: " + " ".join(
        f"{y}->{y + 1} {W.pear(GAP[y].reindex(GAP[y].index.intersection(GAP[y + 1].index)).values, GAP[y + 1].reindex(GAP[y].index.intersection(GAP[y + 1].index)).values):.3f}"
        for y in SEASONS[:-1]))

    def classes(scheme, y):
        """{bid: label} for season y from prior seasons only; an empty dict when a prior season is missing."""
        priors = [y - i for i in range(1, PRIORS[scheme] + 1)]
        if any(p not in SEASONS for p in priors):
            return {}
        idx = GAP[priors[0]].index
        for p in priors[1:]:
            idx = idx.intersection(GAP[p].index)
        if scheme == 'terc':
            num = sum(GAP[p].loc[idx] * NPA[p].loc[idx] for p in priors); den = sum(NPA[p].loc[idx] for p in priors)
            m = num / den
            lab = pd.qcut(m, 3, labels=CLASSES['terc'])
            return {b: str(lab[b]) for b in idx}
        lab = {}
        for b in idx:
            pos = [bool(GAP[p][b] > 0) for p in priors]
            lab[b] = 'beaters' if all(pos) else ('unders' if not any(pos) else 'mixed')
        return lab

    CL = {s: {y: classes(s, y) for y in SAME_Y[s]} for s in PRIORS}

    def members(scheme, cls, y):
        if cls == 'all':
            return S[y].index
        lab = CL[scheme][y]
        if cls == 'any':
            return pd.Index(list(lab.keys()))
        return pd.Index([b for b, l in lab.items() if l == cls])

    # vectors: nxt[(scheme, cls)][n0][c] = [(x, t)] per season in NXT_Y; same[...] = [(x, t)] per season in SAME_Y
    def vectors(scheme, cls):
        nxt = {n0: {c: [] for c in CANDS} for n0 in N0S}; same = {n0: {c: [] for c in CANDS} for n0 in N0S}
        n_nxt, n_same = [], []
        for y in NXT_Y[scheme]:
            g, g2 = S[y], S[y + 1]
            ks = members(scheme, cls, y).intersection(g.index[g['n'] >= GATE]).intersection(g2.index[g2['n'] >= GATE])
            n_nxt.append(len(ks)); t = (g2.loc[ks, 'woba'] - LG[y + 1]['woba']).values
            for n0 in N0S:
                for c in CANDS:
                    nxt[n0][c].append(((rate(y, c, n0).loc[ks] - LG[y][c]).values, t))
        for y in SAME_Y[scheme]:
            g = S[y]; ks = members(scheme, cls, y).intersection(g.index[g['n'] >= GATE])
            n_same.append(len(ks)); t = (g.loc[ks, 'woba'] - LG[y]['woba']).values
            for n0 in N0S:
                for c in CANDS:
                    same[n0][c].append(((rate(y, c, n0).loc[ks] - LG[y][c]).values, t))
        return nxt, same, n_nxt, n_same

    def slope(x, t):
        return float(np.polyfit(x, t, 1)[0]) if len(x) > 2 and np.std(x) > 0 else float('nan')

    def score(nxt, same, idx_n=None, idx_s=None):
        """Per (n0, c): per-season lists and pooled values of each metric."""
        res = {}
        for n0 in N0S:
            res[n0] = {}
            for c in CANDS:
                r, rmse, bias, cal = [], [], [], []; X, Tt = [], []; Xs, Ts = [], []
                for s, (x, t) in enumerate(nxt[n0][c]):
                    if idx_n is not None:
                        x, t = x[idx_n[s]], t[idx_n[s]]
                    ok = len(x) >= MIN_N
                    r.append(W.pear(x, t) if ok else float('nan'))
                    rmse.append(float(np.sqrt(np.mean((x - t) ** 2))) if ok else float('nan'))
                    bias.append(float(np.mean(x - t)) if ok else float('nan'))
                    X.append(x); Tt.append(t)
                for s, (x, t) in enumerate(same[n0][c]):
                    if idx_s is not None:
                        x, t = x[idx_s[s]], t[idx_s[s]]
                    cal.append(slope(x, t) if len(x) >= MIN_N else float('nan')); Xs.append(x); Ts.append(t)
                X, Tt, Xs, Ts = (np.concatenate(v) if v else np.array([]) for v in (X, Tt, Xs, Ts))
                res[n0][c] = {'r': r, 'rmse': rmse, 'bias': bias, 'calib': cal,
                              'pooled': {'r': W.pear(X, Tt) if len(X) >= MIN_N else float('nan'),
                                         'rmse': float(np.sqrt(np.mean((X - Tt) ** 2))) if len(X) else float('nan'),
                                         'bias': float(np.mean(X - Tt)) if len(X) else float('nan'),
                                         'calib': slope(Xs, Ts) if len(Xs) >= MIN_N else float('nan')}}
        return res

    rng = np.random.default_rng(SEED)

    def deltas(sc):
        """xhb minus woba per n0: season-mean delta (over seasons with a value) and pooled delta, per metric."""
        d = {}
        for n0 in N0S:
            d[n0] = {}
            for k in METRICS:
                a = np.array(sc[n0]['xhb'][k], float); b = np.array(sc[n0]['woba'][k], float)
                d[n0][k] = {'mean': float(np.nanmean(a - b)) if np.isfinite(a - b).any() else float('nan'),
                            'pooled': float(sc[n0]['xhb']['pooled'][k] - sc[n0]['woba']['pooled'][k])}
        return d

    print(f"\nCLASS TABLES: r / rmse / bias against wOBA in y+1 (>= {GATE} PA both years), calib same-season; "
          f"delta = xhb - woba, SE = paired bootstrap ({BOOT} draws); a season needs >= {MIN_N} members")
    results = {}
    for scheme in PRIORS:
        results[scheme] = {}
        print(f"\n[{scheme}]  next-season y {NXT_Y[scheme]}  same-season y {SAME_Y[scheme]}")
        for cls in CLASSES[scheme] + ['any', 'all']:
            nxt, same, n_nxt, n_same = vectors(scheme, cls)
            sc = score(nxt, same); dl = deltas(sc)
            # bootstrap: the same batter draw for every rate and shrink
            idx_n = [[rng.integers(0, len(x), len(x)) if len(x) else np.array([], int) for (x, _) in nxt[0]['woba']] for _ in range(BOOT)]
            idx_s = [[rng.integers(0, len(x), len(x)) if len(x) else np.array([], int) for (x, _) in same[0]['woba']] for _ in range(BOOT)]
            reps = {n0: {k: {'mean': [], 'pooled': []} for k in METRICS} for n0 in N0S}
            breps = {n0: {c: {'mean': [], 'pooled': []} for c in CANDS} for n0 in N0S}
            for b in range(BOOT):
                sb = score(nxt, same, idx_n[b], idx_s[b]); db = deltas(sb)
                for n0 in N0S:
                    for k in METRICS:
                        reps[n0][k]['mean'].append(db[n0][k]['mean']); reps[n0][k]['pooled'].append(db[n0][k]['pooled'])
                    for c in CANDS:
                        bb = np.array(sb[n0][c]['bias'], float)
                        breps[n0][c]['mean'].append(float(np.nanmean(bb)) if np.isfinite(bb).any() else float('nan'))
                        breps[n0][c]['pooled'].append(sb[n0][c]['pooled']['bias'])
            rec = {'n_nxt': n_nxt, 'n_same': n_same, 'scores': sc, 'delta': {}}
            for n0 in N0S:
                rec['delta'][n0] = {}
                for k in METRICS:
                    a = np.array(sc[n0]['xhb'][k], float); b = np.array(sc[n0]['woba'][k], float); ok = np.isfinite(a - b)
                    wins = int(((a - b) > 0)[ok].sum()) if k in ('r',) else int(((a - b) < 0)[ok].sum()) if k == 'rmse' else None
                    rec['delta'][n0][k] = {'mean': dl[n0][k]['mean'], 'se_mean': float(np.nanstd(reps[n0][k]['mean'], ddof=1)),
                                           'pooled': dl[n0][k]['pooled'], 'se_pooled': float(np.nanstd(reps[n0][k]['pooled'], ddof=1)),
                                           'wins': wins, 'n_seasons': int(ok.sum())}
                rec['delta'][n0]['bias_se'] = {c: {'mean': float(np.nanstd(breps[n0][c]['mean'], ddof=1)),
                                                   'pooled': float(np.nanstd(breps[n0][c]['pooled'], ddof=1))} for c in CANDS}
            results[scheme][cls] = rec
            print(f"\n  class {cls:8} n(y,y+1) " + " ".join(f"{y}:{n}" for y, n in zip(NXT_Y[scheme], n_nxt)) +
                  "   n(same) " + " ".join(f"{y}:{n}" for y, n in zip(SAME_Y[scheme], n_same)))
            for n0 in N0S:
                for k in METRICS:
                    wv, xv = sc[n0]['woba'][k], sc[n0]['xhb'][k]; d = rec['delta'][n0][k]
                    fmt = (lambda v: f"{v:+.4f}") if k == 'bias' else (lambda v: f"{v:.3f}")
                    line = (f"    N0={n0:<3} {k:5} woba " + " ".join(fmt(v) for v in wv) + f" | pool {fmt(sc[n0]['woba']['pooled'][k])}"
                            f"   xhb " + " ".join(fmt(v) for v in xv) + f" | pool {fmt(sc[n0]['xhb']['pooled'][k])}"
                            f"   delta {d['mean']:+.4f} (SE {d['se_mean']:.4f}) pool {d['pooled']:+.4f} (SE {d['se_pooled']:.4f})")
                    if k == 'r':
                        line += f" xhb wins {d['wins']}/{d['n_seasons']}"
                    elif k == 'rmse':
                        line += f" xhb lower {d['wins']}/{d['n_seasons']}"
                    elif k == 'bias':
                        bs = rec['delta'][n0]['bias_se']
                        line += f" [bias SE woba {bs['woba']['mean']:.4f} xhb {bs['xhb']['mean']:.4f}]"
                    print(line)
    out['results'] = results

    # class shares and gap persistence
    print(f"\nCLASS SHARES AND GAP PERSISTENCE (gap_y = the class member's gap in the classified season y, gap_y1 = in y+1; >= {GATE} PA)")
    persist = {}
    for scheme in PRIORS:
        persist[scheme] = {}
        for y in SAME_Y[scheme]:
            lab = CL[scheme][y]; n_any = len(lab); n_gate = int((S[y]['n'] >= GATE).sum()); persist[scheme][y] = {'n_with_priors': n_any, 'n_gated': n_gate}
            for cls in CLASSES[scheme]:
                ks = members(scheme, cls, y); rec = {'n': len(ks), 'share_of_priors': len(ks) / n_any if n_any else float('nan')}
                priors = [y - i for i in range(1, PRIORS[scheme] + 1)]
                rec['prior_gap_mean'] = float(np.mean([float(GAP[p].loc[ks].mean()) for p in priors])) if len(ks) else float('nan')
                ky = ks.intersection(GAP[y].index); gy = GAP[y].loc[ky]
                rec['gap_y'] = {'n': len(ky), 'mean': float(gy.mean()) if len(ky) else float('nan'), 'sd': float(gy.std()) if len(ky) > 1 else float('nan'),
                                'share_pos': float((gy > 0).mean()) if len(ky) else float('nan')}
                if y + 1 in SEASONS:
                    k1 = ks.intersection(GAP[y + 1].index); g1 = GAP[y + 1].loc[k1]
                    rec['gap_y1'] = {'n': len(k1), 'mean': float(g1.mean()) if len(k1) else float('nan'), 'sd': float(g1.std()) if len(k1) > 1 else float('nan'),
                                     'share_pos': float((g1 > 0).mean()) if len(k1) else float('nan')}
                persist[scheme][y][cls] = rec
            line = f"  [{scheme}] {y}: {n_any} with priors of {n_gate} at >= {GATE} PA; "
            line += "; ".join(f"{cls} {persist[scheme][y][cls]['n']} ({persist[scheme][y][cls]['share_of_priors']:.0%}) prior gap {persist[scheme][y][cls]['prior_gap_mean']:+.4f}"
                              f" -> gap_y n {persist[scheme][y][cls]['gap_y']['n']} mean {persist[scheme][y][cls]['gap_y']['mean']:+.4f} sd {persist[scheme][y][cls]['gap_y']['sd']:.4f} pos {persist[scheme][y][cls]['gap_y']['share_pos']:.0%}"
                              + (f" | gap_y1 n {persist[scheme][y][cls]['gap_y1']['n']} mean {persist[scheme][y][cls]['gap_y1']['mean']:+.4f} pos {persist[scheme][y][cls]['gap_y1']['share_pos']:.0%}" if 'gap_y1' in persist[scheme][y][cls] else '')
                              for cls in CLASSES[scheme])
            print(line)
        # pooled over seasons
        pooled = {}
        for cls in CLASSES[scheme]:
            gy = np.concatenate([GAP[y].loc[members(scheme, cls, y).intersection(GAP[y].index)].values for y in SAME_Y[scheme]])
            g1 = np.concatenate([GAP[y + 1].loc[members(scheme, cls, y).intersection(GAP[y + 1].index)].values for y in SAME_Y[scheme] if y + 1 in SEASONS])
            pooled[cls] = {'gap_y': {'n': len(gy), 'mean': float(gy.mean()), 'sd': float(gy.std(ddof=1)), 'share_pos': float((gy > 0).mean())},
                           'gap_y1': {'n': len(g1), 'mean': float(g1.mean()), 'sd': float(g1.std(ddof=1)), 'share_pos': float((g1 > 0).mean())}}
            print(f"  [{scheme}] pooled {cls:8} gap_y n {len(gy)} mean {gy.mean():+.4f} sd {gy.std(ddof=1):.4f} pos {(gy > 0).mean():.0%}"
                  f" | gap_y1 n {len(g1)} mean {g1.mean():+.4f} sd {g1.std(ddof=1):.4f} pos {(g1 > 0).mean():.0%}")
        persist[scheme]['pooled'] = pooled
    out['persistence'] = persist

    # Altuve
    alt = {'seasons': {}, 'class': {}}
    for y in SEASONS:
        if ALTUVE in S[y].index:
            g = S[y].loc[ALTUVE]
            alt['seasons'][y] = {'pa': int(g['n']), 'woba': float(g['woba']), 'xhb': float(g['xhb']), 'pf': float(g['pf']),
                                 'gap': float(GAP[y].get(ALTUVE, np.nan)),
                                 'adj_woba_n0': float(rate(y, 'woba', 0).loc[ALTUVE]), 'adj_xhb_n0': float(rate(y, 'xhb', 0).loc[ALTUVE]),
                                 'adj_woba_77': float(rate(y, 'woba', HWAR_N0_BAT).loc[ALTUVE]), 'adj_xhb_77': float(rate(y, 'xhb', HWAR_N0_BAT).loc[ALTUVE]),
                                 'next_woba': float(S[y + 1].loc[ALTUVE, 'woba']) if y + 1 in SEASONS and ALTUVE in S[y + 1].index else None}
    for scheme in PRIORS:
        alt['class'][scheme] = {y: CL[scheme][y].get(ALTUVE, 'no prior') for y in SAME_Y[scheme]}
    out['altuve'] = alt
    print(f"\nALTUVE {ALTUVE}")
    for y, a in alt['seasons'].items():
        nx = f"  next woba {a['next_woba']:.4f}" if a['next_woba'] is not None else ''
        print(f"  {y}: {a['pa']} PA woba {a['woba']:.4f} xhb {a['xhb']:.4f} gap {a['gap']:+.4f} (league gap SD {out['gap_sd'][y]:.4f}) "
              f"adj N0=0 woba {a['adj_woba_n0']:.4f} xhb {a['adj_xhb_n0']:.4f}; N0=77 woba {a['adj_woba_77']:.4f} xhb {a['adj_xhb_77']:.4f}{nx}")
    for scheme in PRIORS:
        print(f"  class [{scheme}]: " + " ".join(f"{y} {c}" for y, c in alt['class'][scheme].items()))

    json.dump(out, open(os.path.join(ROOT, 'data', '_hwar_disagreement_class.json'), 'w'), indent=1, default=float)
    print("wrote data/_hwar_disagreement_class.json")


if __name__ == '__main__':
    main()
