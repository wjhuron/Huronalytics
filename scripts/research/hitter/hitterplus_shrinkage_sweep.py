"""hitterplus_shrinkage_sweep.py — STEP 1 of the descriptive Hitter+ build
(2026-09-16). The 52/17/31 weights are already descriptive-optimal
(hitterplus_descriptive.py), so the only predictive ingredient left in
Hitter+ is the shrinkage toward league inside each atom:
    BB+  n0 130 BIP on the xwOBAcon half (EV95 half unshrunk)
    SD+  n0 190 decisions
    CT+  n0  66 swings
This sweeps a common multiplier lam on those pseudo-counts (lam=1 shipped,
lam=0 unshrunk) and each atom's multiplier alone, against
    same-season actual wOBA   (the descriptive objective, 6 seasons)
    next-season actual wOBA   (the predictive objective, 5 pairs)
at three PA floors (100 / 300 / qualified), with the weights held at
52/17/31 on z-scored atoms (and a LOSO-refit line as a check). Then the
2026 board at lam=0 vs the shipped construction: movers by PA band.

Floors here are the PRODUCTION computation floors (30 BIP / 190 dec / 65
swings), not the 80-BIP weight-derivation floor, because the descriptive
board grades unqualified hitters too.

Bat-tracking priors are omitted on both sides (research frames). The
BB+ slope match (1.2352) is an affine rescale and drops out under z.

Usage: python3 scripts/research/hitter/hitterplus_shrinkage_sweep.py
Output: console, data/_hitterplus_shrinkage_sweep.json,
        ~/Downloads/hitterplus_unshrunk_2026.csv
"""
import csv, json, math, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import izcontact_battery as B

SEASONS = B.SEASONS
PAIRS = B.PAIRS
HP_W = B.HP_W
OUT = os.path.join(ROOT, 'data', '_hitterplus_shrinkage_sweep.json')
CSV = os.path.expanduser('~/Downloads/hitterplus_unshrunk_2026.csv')
PA_QUAL = {Y: 502 for Y in SEASONS}; PA_QUAL[2026] = 430
FLOORS = {'100': 100, '300': 300, 'qual': None}
LAMS = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
# shipped pseudo-counts (single homes: process_data BB_PLUS_N0_CON, sdplus.HITTER_PRIOR_N, contact.HITTER_PRIOR_N)
N0 = {'bb': 130, 'sd': 190, 'ct': 66,
      # measured implied n0 of the candidate atoms (izcontact_battery T1a, 2026-09-16)
      'ocon': 34, 'ct_oz': 43, 'zcon': 73, 'con': 74, 'ct_iz': 111}
MIN = {'bb': 30, 'sd': 190, 'ct': 65, 'ocon': 30, 'ct_oz': 30, 'zcon': 30, 'con': 65, 'ct_iz': 30}


def _shrink(raw, n, k, lg):
    return (n * raw + k * lg) / (n + k) if (n + k) else raw


def atoms_lambda(rows, lam, lam_by=None):
    """Per-hitter atoms at shrinkage multiplier lam (per-atom overrides in
    lam_by). Pools and league anchors follow production: BB+ pool >=30 BIP,
    SD+ >=190 decisions, CT+ >=65 swings; candidate atoms >=30 in their
    own subset. Returns {hitter: {atom: value, 'n_<atom>': n, traits}}."""
    lam_by = lam_by or {}
    L = lambda a: lam_by.get(a, lam)
    out = {}
    # ---- BB+ (process_data recipe, prior-free) ----
    pool = [r for r in rows.values() if r.get('nbip', 0) >= MIN['bb'] and r.get('xwcon') is not None and r.get('ev95') is not None]
    lg_xc = sum(r['xwcon'] * r['nbip'] for r in pool) / sum(r['nbip'] for r in pool)
    lg_ev = sum(r['ev95'] * r['nbip'] for r in pool) / sum(r['nbip'] for r in pool)
    bx = np.array([100 * r['ev95'] / lg_ev for r in pool if r['nbip'] >= B.BB_BETA_GATE_BIP])
    by = np.array([100 * r['xwcon'] / lg_xc for r in pool if r['nbip'] >= B.BB_BETA_GATE_BIP])
    beta = B.BB_BETA_FROZEN
    if len(bx) >= B.BB_BETA_MIN_POOL:
        cand = float(np.sum((bx - bx.mean()) * (by - by.mean())) / np.sum((bx - bx.mean()) ** 2))
        if B.BB_BETA_BAND[0] <= cand <= B.BB_BETA_BAND[1]:
            beta = cand
    k = L('bb') * N0['bb']
    pool_ids = {id(r) for r in pool}
    for h, r in rows.items():
        if id(r) in pool_ids:
            con = 100 * r['xwcon'] / lg_xc; evp = 100 + (100 * r['ev95'] / lg_ev - 100) * beta
            out.setdefault(h, {})['bb'] = B.BB_W_CON * _shrink(con, r['nbip'], k, 100.0) + B.BB_W_EV * evp
            out[h]['n_bb'] = r['nbip']
    # ---- SD+ and CT+ from their raw values ----
    for atom, rawk, nk in (('sd', 'sd_raw', 'n_dec'), ('ct', 'raw_ct_all', 'n_ct_all'),
                           ('ocon', 'raw_ocon', 'n_ocon'), ('ct_oz', 'raw_ct_oz', 'n_ct_oz'),
                           ('zcon', 'raw_zcon', 'n_zcon'), ('con', 'raw_con', 'n_con'), ('ct_iz', 'raw_ct_iz', 'n_ct_iz')):
        pool = {h: r for h, r in rows.items() if r.get(rawk) is not None and r.get(nk, 0) >= MIN[atom]}
        if not pool:
            continue
        lg = float(np.mean([r[rawk] for r in pool.values()]))
        k = L(atom) * N0[atom]
        for h, r in pool.items():
            out.setdefault(h, {})[atom] = _shrink(r[rawk], r[nk], k, lg); out[h]['n_' + atom] = r[nk]
        if atom == 'ocon':   # random-subset placebo, same n and the same shrinkage as ocon
            for s in B.SEEDS:
                for h, r in pool.items():
                    if r.get(f'ocon_r{s}') is not None:
                        out[h][f'ocon_r{s}'] = _shrink(r[f'ocon_r{s}'], r[nk], k, lg)
    for h, r in rows.items():
        if h in out:
            out[h]['swing_pct'] = r.get('swing_pct'); out[h]['chase'] = r.get('chase')
            out[h]['log_nsw'] = math.log(r['n_con']) if r.get('n_con') else None
            out[h]['woba_same'] = r.get('woba_same'); out[h]['pa_same'] = r.get('pa_same', 0)
    return out


def pool_same(at, pa_floor, keys, extra=()):
    ks = [h for h, a in at.items() if all(a.get(k) is not None for k in keys + tuple(extra)) and a.get('woba_same') is not None and a.get('pa_same', 0) >= pa_floor]
    Z = {k: B.z([at[h][k] for h in ks]) for k in keys}
    for e in extra:
        Z['raw_' + e] = np.array([at[h][e] for h in ks], float)
    Z['y'] = np.array([at[h]['woba_same'] for h in ks], float); Z['n'] = len(ks); Z['keys'] = ks
    return Z


def pool_next(at, rows_next, keys, extra=()):
    ks = [h for h, a in at.items() if all(a.get(k) is not None for k in keys + tuple(extra)) and h in rows_next
          and rows_next[h].get('woba_same') is not None and rows_next[h].get('pa_same', 0) >= B.NEXT_MIN_PA
          and a.get('n_bb', 0) >= B.FULL_MIN_BIP]
    Z = {k: B.z([at[h][k] for h in ks]) for k in keys}
    for e in extra:
        Z['raw_' + e] = np.array([at[h][e] for h in ks], float)
    Z['y'] = np.array([rows_next[h]['woba_same'] for h in ks], float); Z['n'] = len(ks); Z['keys'] = ks
    return Z


def loso_r(frames, cols, fixed_w=None):
    rs = []
    for i, Zt in enumerate(frames):
        if fixed_w is None:
            train = [Z for j, Z in enumerate(frames) if j != i]
            X = np.vstack([np.column_stack([Z[c] for c in cols]) for Z in train]); y = np.concatenate([Z['y'] for Z in train])
            w = B.ols_w(X, y)
        else:
            w = np.asarray(fixed_w, float)
        rs.append(B.pear(B.composite_fixed(Zt, w, cols), Zt['y']))
    return rs


def main():
    F = B.load_frames()
    A3 = ('bb', 'sd', 'ct')
    out = {'common': {}, 'per_atom': {}}

    def curves(lam, lam_by=None):
        AT = {Y: atoms_lambda(F[Y], lam, lam_by) for Y in SEASONS}
        rec = {}
        for fname, fl in FLOORS.items():
            fr = [pool_same(AT[Y], fl if fl else PA_QUAL[Y], A3) for Y in SEASONS]
            rec[f'same_{fname}'] = loso_r(fr, A3, HP_W)
            rec[f'same_{fname}_refit'] = loso_r(fr, A3)
            rec[f'n_{fname}'] = [Z['n'] for Z in fr]
        pr = [pool_next(AT[Y], F[Y1], A3) for Y, Y1 in PAIRS]
        rec['next'] = loso_r(pr, A3, HP_W); rec['next_refit'] = loso_r(pr, A3); rec['n_next'] = [Z['n'] for Z in pr]
        return rec

    print("===== common shrinkage multiplier lam on all three atoms (weights 52/17/31) =====")
    print("  lam    same@100  same@300  same@qual   next     | refit: same@300  next     | n@100 n@qual")
    for lam in LAMS:
        rec = curves(lam); out['common'][lam] = rec
        print(f"  {lam:4.2f}   {np.mean(rec['same_100']):.4f}    {np.mean(rec['same_300']):.4f}    {np.mean(rec['same_qual']):.4f}    {np.mean(rec['next']):.4f}   |        {np.mean(rec['same_300_refit']):.4f}    {np.mean(rec['next_refit']):.4f}   | {int(np.mean(rec['n_100'])):4d}  {int(np.mean(rec['n_qual'])):4d}", flush=True)
    for fname in ('same_100', 'same_300', 'same_qual', 'next'):
        vals = {lam: float(np.mean(out['common'][lam][fname])) for lam in LAMS}
        best = max(vals, key=vals.get)
        flat = [lam for lam in LAMS if vals[lam] >= vals[best] - 0.001]
        print(f"  {fname:9s}: argmax lam {best}, 0.001-flat lam [{min(flat)}, {max(flat)}], curve span {max(vals.values()) - min(vals.values()):.4f}")
        # per-season wins of lam=0 vs lam=1
        w = sum(1 for a, b in zip(out['common'][0.0][fname], out['common'][1.0][fname]) if a > b)
        print(f"             lam=0 beats lam=1 in {w}/{len(out['common'][1.0][fname])} seasons; d {np.mean(out['common'][0.0][fname]) - np.mean(out['common'][1.0][fname]):+.4f}")

    print("\n===== one atom's multiplier at a time (others at shipped lam=1) =====")
    print("  atom   lam    same@100  same@300  same@qual   next")
    for atom in A3:
        out['per_atom'][atom] = {}
        for lam in (0.0, 0.5, 1.0, 2.0, 3.0):
            rec = curves(1.0, {atom: lam}); out['per_atom'][atom][lam] = rec
            print(f"  {atom:4s}   {lam:4.2f}   {np.mean(rec['same_100']):.4f}    {np.mean(rec['same_300']):.4f}    {np.mean(rec['same_qual']):.4f}    {np.mean(rec['next']):.4f}", flush=True)

    print("\n===== 2026 board: lam=0 (unshrunk) vs lam=1 (shipped construction), weights 52/17/31 =====")
    lb = json.load(open(os.path.join(ROOT, 'data', 'hitter_leaderboard_rs.json')))
    best = {}
    for x in lb:
        if x.get('mlbId') is None or x.get('team') in ('ROC', 'AAA'):
            continue
        k = str(int(x['mlbId']))
        if k not in best or (x.get('pa') or 0) > (best[k].get('pa') or 0):
            best[k] = x
    AT0, AT1 = atoms_lambda(F[2026], 0.0), atoms_lambda(F[2026], 1.0)
    board = {}
    for tag, AT in (('unshrunk', AT0), ('shipped', AT1)):
        q = [h for h, a in AT.items() if all(a.get(k) is not None for k in A3) and h in best and (best[h].get('pa') or 0) >= PA_QUAL[2026] and best[h].get('wRCplus') is not None]
        m = {k: float(np.mean([AT[h][k] for h in q])) for k in A3}; s = {k: float(np.std([AT[h][k] for h in q])) for k in A3}
        zc = lambda h: sum(wi * (AT[h][k] - m[k]) / s[k] for wi, k in zip(HP_W, A3))
        zq = np.array([zc(h) for h in q]); wq = np.array([best[h]['wRCplus'] for h in q], float)
        r = B.pear(zq, wq); scale = r * float(np.std(wq)) / float(np.std(zq))
        board[tag] = {h: 100 + scale * zc(h) for h, a in AT.items() if all(a.get(k) is not None for k in A3) and h in best}
        print(f"  {tag:8s}: qualified {len(q)}, r vs wRC+ {r:.3f}, scale {scale:.2f}")
    common = [h for h in board['unshrunk'] if h in board['shipped']]
    bands = [('qualified', lambda pa: pa >= PA_QUAL[2026]), ('200-429 PA', lambda pa: 200 <= pa < PA_QUAL[2026]), ('100-199 PA', lambda pa: 100 <= pa < 200)]
    for bname, f in bands:
        hs = [h for h in common if f(best[h].get('pa') or 0)]
        if len(hs) < 5:
            continue
        d = np.array([board['unshrunk'][h] - board['shipped'][h] for h in hs])
        rc = B.pear(np.argsort(np.argsort([board['unshrunk'][h] for h in hs])), np.argsort(np.argsort([board['shipped'][h] for h in hs])))
        sd_u, sd_s = np.std([board['unshrunk'][h] for h in hs]), np.std([board['shipped'][h] for h in hs])
        print(f"  {bname:11s} n {len(hs):3d}  mean |d| {np.mean(np.abs(d)):4.1f}  max |d| {np.max(np.abs(d)):4.1f}  rank corr {rc:.3f}  SD unshrunk {sd_u:4.1f} vs shipped {sd_s:4.1f}")
        top = sorted(hs, key=lambda h: -abs(board['unshrunk'][h] - board['shipped'][h]))[:6]
        for h in top:
            print(f"      {best[h]['hitter'][:22]:22s} {best[h]['team']:4s} {best[h].get('pa') or 0:4d}  shipped {board['shipped'][h]:5.0f}  unshrunk {board['unshrunk'][h]:5.0f}  d {board['unshrunk'][h] - board['shipped'][h]:+4.0f}  wRC+ {best[h]['wRCplus'] if best[h].get('wRCplus') is not None else float('nan'):5.0f}")
    with open(CSV, 'w', newline='') as f:
        wr = csv.writer(f); wr.writerow(['mlbId', 'hitter', 'team', 'pa', 'bbPlus_unshrunk', 'sdPlus_unshrunk', 'ctPlus_unshrunk', 'hitterPlus_shipped_construction', 'hitterPlus_unshrunk', 'delta', 'wRCplus', 'xWRCplus'])
        for h in sorted(common, key=lambda h: -board['unshrunk'][h]):
            b = best[h]; a = AT0[h]
            wr.writerow([h, b.get('hitter'), b.get('team'), b.get('pa'), round(a['bb'], 1), round(a['sd'], 4), round(a['ct'], 4), round(board['shipped'][h], 1), round(board['unshrunk'][h], 1), round(board['unshrunk'][h] - board['shipped'][h], 1), b.get('wRCplus'), b.get('xWRCplus')])
    json.dump(out, open(OUT, 'w'), indent=1, default=float)
    print(f"\nwrote {os.path.relpath(OUT, ROOT)} and {CSV}")


if __name__ == '__main__':
    main()
