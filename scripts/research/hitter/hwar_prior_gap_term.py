"""hwar_prior_gap_term.py — does a prior-season gap term help the position-player hWAR batting rate (2026-09-15)?

The gap (wOBA - xhb) of a batter persists year to year at r ~.20 (hwar_hitter_rate_spray.py).
Candidate:  rate_y = sh(xhb_y, N0) + lam x gap_shrunk_{y-1}
            gap_{k} = (woba_k - lg_woba_k) - (xhb_k - lg_xhb_k), the batter's FULL season k, unshrunk
            gap_shrunk_k = gap_k x n_k / (n_k + N_G)
Arms:
  one    the prior season only (y-1); a batter with no y-1 row gets 0
  two    n-weighted mean of the shrunk gaps of y-1 and y-2 (y = 2022 has only y-1)
Gap kinds:
  raw    rate minus league within the season, as specified
  park   the same gap minus (PASS_woba - PASS_xhb) x park exposure, because the raw gap carries about half
         the published park factor (pass_woba ~ +.30, pass_xhb ~ -.22) and a batter's park persists too
Base shrink N0 of xhb: HWAR_N0_BAT (77, the shipped rate; lam = 0 there IS the shipped arm) and 0 (the
validation-script convention; lam = 0 at N0 = 0 must reproduce the spray JSON's 'xhb N0=0' rows).
Objectives are hwar_hitter_rate_validation.py's, on the seasons that have a prior (y = 2022..2026;
nxt pairs 2022->2023 .. 2025->2026): rel, ros, nxt300, nxt150, calib. rel and calib inflate
mechanically when actual prior outcomes enter the rate; nxt and ros decide.
Grid: lam in LAM_GRID x N_G in NG_GRID. Paired against lam = 0: mean delta, wins/n, paired bootstrap SE
(batters resampled within each season, seasons independent). Case per objective: interior / edge / flat.
Usage: PYTHONHASHSEED=0 python3 scripts/research/hitter/hwar_prior_gap_term.py
Output: console + data/_hwar_prior_gap_term.json
"""
import gc, json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'era'))
import hwar_hitter_rate_validation as V
import war_rate_validation as W
from pipeline.hwar import HWAR_N0_BAT

SEASONS = V.SEASONS; SCALE = V.SCALE; GATE_HALF, GATE_CAL = V.GATE_HALF, V.GATE_CAL
YS = [y for y in SEASONS if y - 1 in SEASONS]            # 2022..2026
CANDS = ['woba', 'xhb']
LAM_GRID = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25]
NG_GRID = [0, 100, 200, 400, 800]
BASE_N0 = [HWAR_N0_BAT, 0]
ARMS = ['one', 'two']; KINDS = ['raw', 'park']
OBJ = ['rel', 'ros', 'nxt300', 'nxt150', 'calib']
DECIDE = ['nxt300', 'nxt150', 'ros']
PROBE_LAM = [0.05, 0.10, 0.15, 0.25]; PROBE_NG = [0, 800, 1600, 3200]     # below the grid: lam x n/(n+NG) down to ~.01
PROBE_ARMS = ['one/raw/N0=77', 'one/park/N0=77', 'two/park/N0=77']
BOOT = 400; SEED = 0
ALTUVE = '514888'; LIVE = 2026


def main():
    out = {'lam_grid': LAM_GRID, 'ng_grid': NG_GRID, 'base_n0': BASE_N0, 'seasons': YS}
    P, LG, RPA = {}, {}, {}
    print("PER-PA TABLES (hwar_hitter_rate_validation machinery)")
    for y in SEASONS:
        P[y], _ = V.pa_savant(y) if y < LIVE else V.pa_sheet(y)
        ph = V.T[str(y)]['pitchers']; RPA[y] = sum(v['r'] for v in ph.values()) / sum(v['bf'] for v in ph.values())
        LG[y] = {sc: {c: float(P[y].loc[m, c].mean()) for c in CANDS}
                 for sc, m in (('full', slice(None)), ('h1', P[y]['h1'].values), ('h2', ~P[y]['h1'].values))}
        print(f"  {y}: {len(P[y])} PA, {P[y]['bid'].nunique()} batters, league woba {LG[y]['full']['woba']:.4f} xhb {LG[y]['full']['xhb']:.4f}", flush=True)
        gc.collect()
    S = {}
    for y in SEASONS:
        S[y] = {}
        for sc, m in (('full', np.ones(len(P[y]), bool)), ('h1', P[y]['h1'].values), ('h2', ~P[y]['h1'].values)):
            g = P[y][m].groupby('bid').agg(woba=('woba', 'mean'), xhb=('xhb', 'mean'), n=('woba', 'size'), pf=('pf', 'mean'))
            g['pf'] = g['pf'].fillna(1.0); S[y][sc] = g
    del P; gc.collect()

    def sh(y, sc, c, n0):
        g = S[y][sc]; return (g[c] * g['n'] + n0 * LG[y][sc][c]) / (g['n'] + n0)

    def full_park(y, g):
        return (g['pf'] - 1.0) * RPA[y] * SCALE[y]

    print("\nPARK PASS-THROUGH (LOSO over all six seasons, >= 300 PA; 1.0 = the published factor)")
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

    # the gap of every batter-season, full scope, unshrunk, both kinds
    GAP = {}
    for y in SEASONS:
        g = S[y]['full']
        raw = (g['woba'] - LG[y]['full']['woba']) - (g['xhb'] - LG[y]['full']['xhb'])
        GAP[y] = {'raw': raw, 'park': raw - (PASS['woba'] - PASS['xhb']) * full_park(y, g), 'n': g['n'].astype(float)}

    def shrunk_gap(k, kind, ng):
        return GAP[k][kind] * GAP[k]['n'] / (GAP[k]['n'] + ng)

    def term(arm, kind, lam, ng, y):
        """lam x the shrunk prior gap, a Series over every batter with at least one prior season."""
        if arm == 'one':
            return lam * shrunk_gap(y - 1, kind, ng)
        ks = [k for k in (y - 1, y - 2) if k in SEASONS]
        parts = [shrunk_gap(k, kind, ng) * GAP[k]['n'] for k in ks]; dens = [GAP[k]['n'] for k in ks]
        num = pd.concat(parts, axis=1).sum(axis=1); den = pd.concat(dens, axis=1).sum(axis=1)
        return lam * num / den

    def rate(arm, kind, lam, ng, n0, y, sc):
        g = S[y][sc]
        return sh(y, sc, 'xhb', n0) + term(arm, kind, lam, ng, y).reindex(g.index, fill_value=0.0)

    def vectors(arm, kind, lam, ng, n0):
        """Per season: the (rate, target) pairs each objective correlates, so the bootstrap can resample batters."""
        v = {k: [] for k in OBJ}
        for y in YS:
            a, b = S[y]['h1'], S[y]['h2']; ks = a.index[a['n'] >= GATE_HALF].intersection(b.index[b['n'] >= GATE_HALF])
            r1 = rate(arm, kind, lam, ng, n0, y, 'h1').loc[ks].values; r2 = rate(arm, kind, lam, ng, n0, y, 'h2').loc[ks].values
            v['rel'].append((r1, r2)); v['ros'].append((r1, b.loc[ks, 'woba'].values))
            g = S[y]['full']; ks = g.index[g['n'] >= GATE_CAL]
            adj = (rate(arm, kind, lam, ng, n0, y, 'full') - PASS['xhb'] * full_park(y, g)).loc[ks]
            v['calib'].append((adj.values, g.loc[ks, 'woba'].values))
        for gate in (300, 150):
            for y in YS[:-1]:
                g, g2 = S[y]['full'], S[y + 1]['full']; ks = g.index[g['n'] >= gate].intersection(g2.index[g2['n'] >= gate])
                adj = (rate(arm, kind, lam, ng, n0, y, 'full') - PASS['xhb'] * full_park(y, g)).loc[ks]
                v[f'nxt{gate}'].append((adj.values, g2.loc[ks, 'woba'].values))
        return v

    def score(v, idx=None):
        res = {}
        for k in OBJ:
            vals = []
            for s, (x, t) in enumerate(v[k]):
                if idx is not None:
                    x, t = x[idx[k][s]], t[idx[k][s]]
                vals.append(float(np.polyfit(x, t, 1)[0]) if k == 'calib' else W.pear(x, t))
            res[k] = vals
        return res

    # coverage: how many gated batters carry a prior term
    print("\nCOVERAGE of the prior term in the gated sets (batters with a y-1 row / y-1 or y-2 row)")
    cov = {}
    for y in YS:
        g = S[y]['full']; ks = g.index[g['n'] >= GATE_CAL]
        one = int(ks.isin(GAP[y - 1]['raw'].index).sum())
        two = int(ks.isin(GAP[y - 1]['raw'].index.union(GAP[y - 2]['raw'].index if y - 2 in SEASONS else GAP[y - 1]['raw'].index)).sum())
        cov[y] = {'n300': len(ks), 'one': one, 'two': two}
        print(f"  {y}: {len(ks)} batters >= 300 PA, {one} with y-1, {two} with y-1 or y-2")
    out['coverage'] = cov

    # replication check against the spray JSON (same caches): lam = 0, N0 = 0 on 2022..2026
    ref_path = os.path.join(ROOT, 'data', '_hwar_hitter_rate_spray.json')
    base00 = score(vectors('one', 'raw', 0.0, 0, 0))
    if os.path.exists(ref_path):
        ref = json.load(open(ref_path)).get('xhb N0=0')
        if ref:
            print("\nREPLICATION CHECK vs data/_hwar_hitter_rate_spray.json 'xhb N0=0', seasons 2022..2026 (nxt 2022..2025):")
            worst = 0.0
            for k in OBJ:   # the reference lists start at 2021; this script starts at 2022 (nxt: the 2022->2023 pair)
                r = np.array(ref[k][1:1 + len(base00[k])]); d = np.abs(np.array(base00[k]) - r); worst = max(worst, float(d.max()))
                print(f"  {k:7} max |diff| {d.max():.5f}")
            out['replication_max_abs_diff'] = worst
            print("  " + ("OK: reproduces the validation rows" if worst < 1e-6 else "MISMATCH: the caches moved since the spray run"))

    rng = np.random.default_rng(SEED)

    def boot_idx(v):
        return [{k: [rng.integers(0, len(x), len(x)) for (x, _) in v[k]] for k in OBJ} for _ in range(BOOT)]

    def paired(v1, v0, idxs):
        """Mean-over-seasons delta of each objective, its paired bootstrap SE, and season wins."""
        p1, p0 = score(v1), score(v0); res = {}
        for k in OBJ:
            d = np.array(p1[k]) - np.array(p0[k])
            reps = [float(np.mean(np.array(score(v1, ix)[k]) - np.array(score(v0, ix)[k]))) for ix in idxs]
            res[k] = {'delta': float(d.mean()), 'se': float(np.std(reps, ddof=1)), 'wins': int((d > 0).sum()), 'n': len(d), 'per_season': d.tolist()}
        return res

    print(f"\nGRID: mean over seasons; base xhb shrink N0 and the shipped arm is lam = 0 at N0 = {HWAR_N0_BAT}")
    grid = {}
    VEC = {}
    for n0 in BASE_N0:
        for arm in ARMS:
            for kind in KINDS:
                key = f'{arm}/{kind}/N0={n0}'; grid[key] = {}
                print(f"\n  [{key}]")
                for k in OBJ:
                    print(f"    {k:7}" + "".join(f"  NG={ng:>4}" for ng in NG_GRID))
                    for lam in LAM_GRID:
                        line = []
                        for ng in NG_GRID:
                            ck = (lam, ng)
                            if ck not in grid[key]:
                                VEC[(key, ck)] = vectors(arm, kind, lam, ng, n0); grid[key][ck] = score(VEC[(key, ck)])
                            line.append(np.mean(grid[key][ck][k]))
                        print(f"      lam {lam:4.2f}" + "".join(f"  {m:7.4f}" for m in line))
                out.setdefault('grid', {})[key] = {f'lam={lam},ng={ng}': {k: grid[key][(lam, ng)][k] for k in OBJ} for lam in LAM_GRID for ng in NG_GRID}

    # case per deciding objective: interior / edge / flat, paired against lam = 0 with the bootstrap SE
    print("\nCASE per deciding objective (argmax over the grid, paired vs lam = 0 of the same arm; flat = best delta < 1 SE)")
    idxs = None
    cases = {}
    for key in grid:
        n0 = int(key.split('N0=')[1]); base_v = VEC[(key, (0.0, 0))]
        if idxs is None:
            idxs = boot_idx(base_v)
        cases[key] = {}
        for k in DECIDE:
            best = max(grid[key], key=lambda ck: np.mean(grid[key][ck][k])); lam, ng = best
            pr = paired(VEC[(key, best)], base_v, idxs)[k]
            interior = (lam not in (LAM_GRID[0], LAM_GRID[-1])) and (ng not in (NG_GRID[0], NG_GRID[-1]))
            if lam == 0.0:
                case = 'off (lam = 0 wins)'
            elif pr['delta'] < pr['se']:
                case = 'flat (best delta inside one SE)'
            elif interior:
                case = 'interior'
            else:
                case = 'edge'
            cases[key][k] = {'lam': lam, 'ng': ng, 'value': float(np.mean(grid[key][best][k])), 'base': float(np.mean(grid[key][(0.0, 0)][k])),
                             'delta': pr['delta'], 'se': pr['se'], 'wins': pr['wins'], 'n': pr['n'], 'case': case}
            print(f"  {key:22} {k:7} best lam {lam:4.2f} NG {ng:>3}: {cases[key][k]['value']:.4f} vs base {cases[key][k]['base']:.4f}, "
                  f"delta {pr['delta']:+.4f} SE {pr['se']:.4f} wins {pr['wins']}/{pr['n']}  -> {case}")
    out['cases'] = cases

    # one-dimensional cuts at the best NG of the primary arm, full paired stats for every lam
    prim = f'one/raw/N0={HWAR_N0_BAT}'
    print(f"\nPAIRED vs lam = 0 for every lam, primary arm {prim}, each NG (delta, SE, wins/n) on nxt300 / nxt150 / ros / rel / calib")
    out['paired_primary'] = {}
    for ng in NG_GRID:
        for lam in LAM_GRID[1:]:
            pr = paired(VEC[(prim, (lam, ng))], VEC[(prim, (0.0, 0))], idxs)
            out['paired_primary'][f'lam={lam},ng={ng}'] = pr
            print(f"  NG {ng:>3} lam {lam:4.2f}  " + "  ".join(f"{k} {pr[k]['delta']:+.4f}({pr[k]['se']:.4f}) {pr[k]['wins']}/{pr[k]['n']}" for k in OBJ))

    # PROBE below the grid: does a small effective weight (lam x n / (n + NG)) sit on a flat region or a tiny interior optimum?
    print(f"\nSMALL-WEIGHT PROBE, paired vs lam = 0 (delta, SE, wins/n): lam in {PROBE_LAM} x NG in {PROBE_NG}, N0 = {HWAR_N0_BAT}")
    out['probe'] = {}
    for key in PROBE_ARMS:
        arm, kind = key.split('/')[:2]; base_v = VEC[(key, (0.0, 0))]; out['probe'][key] = {}
        print(f"  [{key}]")
        for ng in PROBE_NG:
            for lam in PROBE_LAM:
                v1 = VEC.get((key, (lam, ng))) or vectors(arm, kind, lam, ng, HWAR_N0_BAT)
                pr = paired(v1, base_v, idxs); out['probe'][key][f'lam={lam},ng={ng}'] = pr
                print(f"    NG {ng:>4} lam {lam:4.2f}  " + "  ".join(f"{k} {pr[k]['delta']:+.4f}({pr[k]['se']:.4f}) {pr[k]['wins']}/{pr[k]['n']}" for k in DECIDE))

    # DIAGNOSTIC: the regression weight the data itself puts on the prior gap
    print("\nDIAGNOSTIC per (y-1, y, y+1) triple, batters >= 300 PA in all three:")
    print("  r(gap_{y-1}, gap_y) = the persistence; r(gap_{y-1}, adj xhb_y); OLS woba_{y+1} ~ adj xhb_y + gap_{y-1}: the gap coefficient (SE) IS the lam the data wants")
    diag = {}
    for y in YS[:-1]:
        g0, g, g2 = S[y - 1]['full'], S[y]['full'], S[y + 1]['full']
        ks = g0.index[g0['n'] >= GATE_CAL].intersection(g.index[g['n'] >= GATE_CAL]).intersection(g2.index[g2['n'] >= GATE_CAL])
        gp = GAP[y - 1]['raw'].loc[ks].values; gy = GAP[y]['raw'].loc[ks].values
        adj = (sh(y, 'full', 'xhb', HWAR_N0_BAT) - PASS['xhb'] * full_park(y, g)).loc[ks].values; t = g2.loc[ks, 'woba'].values
        X = np.column_stack([np.ones(len(ks)), adj, gp]); beta, *_ = np.linalg.lstsq(X, t, rcond=None)
        resid = t - X @ beta; s2 = float(resid @ resid) / (len(ks) - 3); se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))
        r_only = W.pear(adj, t); r_both = W.pear(X @ beta, t)
        diag[y] = {'n': len(ks), 'persist': W.pear(gp, gy), 'r_gap_xhb': W.pear(gp, adj), 'beta_xhb': float(beta[1]), 'beta_gap': float(beta[2]),
                   'se_gap': float(se[2]), 'r_xhb_only': r_only, 'r_fitted_both': r_both}
        d = diag[y]
        print(f"  {y - 1}->{y}->{y + 1} n {d['n']:3d}  persist {d['persist']:.3f}  r(gap,xhb) {d['r_gap_xhb']:+.3f}  "
              f"beta xhb {d['beta_xhb']:.3f}  beta gap {d['beta_gap']:+.3f} (SE {d['se_gap']:.3f})  r xhb-only {d['r_xhb_only']:.4f}  r both (in-sample) {d['r_fitted_both']:.4f}")
    bg = np.array([diag[y]['beta_gap'] for y in diag]); print(f"  mean beta gap {bg.mean():+.3f}, seasons positive {int((bg > 0).sum())}/{len(bg)}")
    out['diagnostic'] = diag

    # the size of the term on the live season at the best nxt300 config of each arm, and at a fixed reference
    print(f"\nTERM SIZE on {LIVE} (wOBA points, and runs = term x PA / {SCALE[LIVE]}), best nxt300 config of each N0={HWAR_N0_BAT} arm")
    sizes = {}
    g26 = S[LIVE]['full']
    for key in [k for k in grid if k.endswith(f'N0={HWAR_N0_BAT}')]:
        arm, kind = key.split('/')[:2]
        best = cases[key]['nxt300']; lam, ng = best['lam'], best['ng']
        if lam == 0.0:
            lam = 0.5; ng = 200; ref = ' (lam = 0 won; sized at the reference lam .5 NG 200)'
        else:
            ref = ''
        t = term(arm, kind, lam, ng, LIVE).reindex(g26.index)
        have = t.notna(); runs = (t * g26['n'] / SCALE[LIVE])
        d = {'lam': lam, 'ng': ng, 'batters': int(len(g26)), 'with_prior': int(have.sum()),
             'term_mean_abs': float(t[have].abs().mean()), 'term_sd': float(t[have].std()), 'term_max': float(t[have].max()), 'term_min': float(t[have].min()),
             'runs_mean_abs': float(runs[have].abs().mean()), 'runs_sum_abs': float(runs[have].abs().sum()), 'runs_max': float(runs[have].max()), 'runs_min': float(runs[have].min())}
        top = runs[have].abs().sort_values(ascending=False).index[:5]
        d['top5_runs'] = {b: {'term': float(t[b]), 'pa': int(g26.loc[b, 'n']), 'runs': float(runs[b])} for b in top}
        if ALTUVE in g26.index:
            d['altuve'] = {'term': float(t[ALTUVE]) if have[ALTUVE] else None, 'pa': int(g26.loc[ALTUVE, 'n']),
                           'runs': float(runs[ALTUVE]) if have[ALTUVE] else None,
                           'gap_prior_raw': float(GAP[LIVE - 1]['raw'].get(ALTUVE, np.nan)), 'gap_prior_park': float(GAP[LIVE - 1]['park'].get(ALTUVE, np.nan)),
                           'n_prior': float(GAP[LIVE - 1]['n'].get(ALTUVE, np.nan))}
        sizes[key] = d
        print(f"  {key:22} lam {lam:4.2f} NG {ng:>3}{ref}: {d['with_prior']}/{d['batters']} batters carry a term; "
              f"mean |term| {d['term_mean_abs']:.4f} sd {d['term_sd']:.4f} range [{d['term_min']:+.4f}, {d['term_max']:+.4f}]; "
              f"runs mean |r| {d['runs_mean_abs']:.2f} sum |r| {d['runs_sum_abs']:.1f} range [{d['runs_min']:+.2f}, {d['runs_max']:+.2f}]")
        if 'altuve' in d and d['altuve']['term'] is not None:
            a = d['altuve']
            print(f"    Altuve: prior gap raw {a['gap_prior_raw']:+.4f} park {a['gap_prior_park']:+.4f} on {a['n_prior']:.0f} PA; "
                  f"term {a['term']:+.4f} wOBA on {a['pa']} PA = {a['runs']:+.2f} runs")
        print("    top 5 |runs|: " + ", ".join(f"{b} {v['runs']:+.2f} ({v['term']:+.4f} x {v['pa']})" for b, v in d['top5_runs'].items()))
    out['sizes'] = sizes
    json.dump(out, open(os.path.join(ROOT, 'data', '_hwar_prior_gap_term.json'), 'w'), indent=1, default=float)
    print("wrote data/_hwar_prior_gap_term.json")


if __name__ == '__main__':
    main()
