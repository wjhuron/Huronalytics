"""izcontact_battery.py — does IN-ZONE contact carry information that the
shipped CT+ (all-swing, leverage-weighted, location-adjusted) and Hitter+
52/17/31 leave on the table?  (2026-09-16, prompted by a team source who
values in-zone contact highly.)

Self-contained seasons 2021-2026 (public Statcast via the adapter for
2021-2025, the sheet cache for 2026), production zones/cells/tables via
pipeline.contact and pipeline.sdplus, the same LOPO protocol as
hitterplus_weights_v2 (z-scored within pair, derive on 4 pairs / score on
the 5th).

Atoms per hitter-season (all CT variants scored against the SAME shipped
cell table, lift ratio actual/expected, shrunk toward the pool mean with
the shipped n0=66):
  ct_all    shipped CT+ (all swings)              — parity-checked vs pipeline
  ct_iz     CT+ restricted to in-zone swings     (heart + shadow_in)
  ct_oz     CT+ restricted to out-of-zone swings (shadow_out + chase + waste)
  ct_heart  CT+ restricted to heart swings
  zcon      plain in-zone contact per swing (Z-Contact%), shrunk n0=66
  ocon      plain out-of-zone contact per swing
  con       plain contact per swing
  sd        production SD+ (pipeline.sdplus.compute_sd_plus)
  bb        production BB+ recipe (process_data constants, prior-free)

Targets: next-season wOBA (the Hitter+ objective), next-season K% and
same-season wOBA as diagnostics.

Tests:
  T0  where CT+'s weight already sits: leverage share, swing share and
      whiff rate by zone
  T1  univariate next-season r per atom (5 pairs) + split-half reliability
      per season (3 game-date seeds) with the implied n0
  T2  partial r of each candidate given z(bb), z(sd), z(ct_all)
      (the 0.15 gate the 2026-08-14 4th-atom screen used)
  T3  composite LOPO, 5 folds: SHIP 52/17/31, OLS3 (bb,sd,ct_all),
      IZOZ (bb,sd,ct_iz,ct_oz), IZ (bb,sd,ct_iz), ZCON4 (bb,sd,ct_all,zcon),
      ZCON3 (bb,sd,zcon), and a PLACEBO that splits each hitter's swings at
      random in his own in-zone proportion (3 seeds) — the partition-
      flexibility control from the SD+ cat3 lesson
      Paired bootstrap SE of every delta vs OLS3 (300 resamples per fold).
  T4  calibration: residual of the held-out SHIP composite vs the hitter's
      Z-Contact% (is the composite blind to it?)

Usage: python3 scripts/research/hitter/izcontact_battery.py
Output: console + data/_izcontact_battery.json
"""
import gc, json, math, os, random, sys
from collections import defaultdict
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import statcast_hitter_adapter as A
import hitter_phase2_multiseason as H
import pipeline.sdplus as sd
import pipeline.contact as ct
from pipeline.utils import safe_float

SEASONS = [2021, 2022, 2023, 2024, 2025, 2026]
PAIRS = [(y, y + 1) for y in (2021, 2022, 2023, 2024, 2025)]
SEEDS = (0, 1, 2)
N_BOOT = 300
# BB+ recipe constants, single home pipeline/process_data.py (read 2026-09-05)
BB_W_CON, BB_W_EV, BB_N0_CON, BB_N0_EV = 0.60, 0.40, 130, 0
BB_SLOPE_MATCH, BB_BETA_FROZEN, BB_BETA_BAND = 1.2352, 4.205, (3.0, 6.0)
BB_BETA_GATE_BIP, BB_BETA_MIN_POOL, BB_MIN_BIP = 80, 40, 30
HP_W = (0.52, 0.17, 0.31)
CT_N0 = ct.HITTER_PRIOR_N            # 66, applied to every CT variant and plain rate
FULL_MIN_SW, FULL_MIN_DEC, FULL_MIN_BIP, NEXT_MIN_PA = ct.MIN_HITTER_SWINGS, sd.MIN_HITTER_DECISIONS, 80, 200
SUB_MIN_SW = 30                      # floor inside a zone subset (full season and per half)
HALF_MIN_SW = 30
IZ_ZONES = {'heart', 'shadow_in'}
OZ_ZONES = {'shadow_out', 'chase', 'waste'}
BUNT_BB = ('bunt', 'bunt_grounder', 'bunt_popup', 'bunt_line_drive')
WOBA_EV = {'single': 0.9, 'double': 1.25, 'triple': 1.6, 'home_run': 2.0,
           'Single': 0.9, 'Double': 1.25, 'Triple': 1.6, 'Home Run': 2.0,
           'field_error': 0.9, 'fielders_choice': 0.9, 'fielders_choice_out': 0.9,
           'Field Error': 0.9, 'Fielders Choice': 0.9, 'Fielders Choice Out': 0.9}
OUT = os.path.join(ROOT, 'data', '_izcontact_battery.json')


def is_bip(p):
    return p.get('Description') == 'In Play' and (p.get('BBType') or '') not in BUNT_BB


def in_zone(p):
    return p.get('InZone') in (True, 1, 'Yes', 'yes', 'Y')


def pct(vals, q):
    return float(np.percentile(vals, q)) if vals else None


def shrink(raw_by_h, n_by_h, k, floor):
    """(n*raw + k*lg)/(n+k) toward the mean of hitters at/above `floor`."""
    pool = [raw_by_h[h] for h in raw_by_h if n_by_h[h] >= floor]
    if not pool:
        return {}
    lg = float(np.mean(pool))
    return {h: (n_by_h[h] * raw_by_h[h] + k * lg) / (n_by_h[h] + k)
            for h in raw_by_h if n_by_h[h] >= floor}


def lift_ratio(swings, table):
    """CT+ raw form on a swing subset: leverage-weighted actual over
    leverage-weighted expected contact. Returns (ratio | None, n_used)."""
    a = e = 0.0; n = 0
    for p in swings:
        lev, con = ct.compute_ct_swing(p, table)
        if lev <= 0:
            continue
        cell = table[(ct.classify_zone(p), ct.get_count(p), ct.cat_of(p))]
        a += lev * con; e += lev * (1.0 - cell['p_whiff']); n += 1
    return ((a / e) if e > 0 else None), n


def plain_rate(swings):
    n = len(swings)
    if not n:
        return None, 0
    return sum(1 for p in swings if ct.classify_contact_outcome(p) == 'contact') / n, n


def score_ct_atoms(by_h_sw, table, floor_all, floor_sub, rng=None):
    """Per-hitter raw CT atoms. With `rng`, ct_iz/ct_oz are replaced by a
    random split of each hitter's swings in his own in-zone proportion."""
    raw, n = defaultdict(dict), defaultdict(dict)
    for h, sw in by_h_sw.items():
        z = [ct.classify_zone(p) for p in sw]
        if rng is None:
            iz = [p for p, zz in zip(sw, z) if zz in IZ_ZONES]
            oz = [p for p, zz in zip(sw, z) if zz in OZ_ZONES]
        else:
            share = sum(1 for zz in z if zz in IZ_ZONES) / len(sw)
            flags = [rng.random() < share for _ in sw]
            iz = [p for p, f in zip(sw, flags) if f]
            oz = [p for p, f in zip(sw, flags) if not f]
        heart = [p for p, zz in zip(sw, z) if zz == 'heart']
        for name, subset in (('ct_all', sw), ('ct_iz', iz), ('ct_oz', oz), ('ct_heart', heart)):
            v, k = lift_ratio(subset, table)
            if v is not None:
                raw[name][h] = v; n[name][h] = k
        izp = [p for p in sw if in_zone(p)]
        ozp = [p for p in sw if not in_zone(p)]
        for name, subset in (('con', sw), ('zcon', izp), ('ocon', ozp)):
            v, k = plain_rate(subset)
            if v is not None:
                raw[name][h] = v; n[name][h] = k
    out = {}
    for name in raw:
        fl = floor_all if name in ('ct_all', 'con') else floor_sub
        out[name] = shrink(raw[name], n[name], CT_N0, fl)
    return out, raw, n


def season_frame(Y, name2id):
    P = H.load_season(Y)
    lg, sc = H.guts(Y)
    if Y == 2026:
        for p in P:
            p['_bid'] = name2id.get(p.get('Batter'))
    else:
        for p in P:
            p['_bid'] = p.get('Batter')
    P = [p for p in P if p.get('_bid')]
    by_h = defaultdict(list)
    for p in P:
        by_h[(p['_bid'], '')].append(p)
    # production SD+ and CT+ (parity reference)
    sdn, _ = sd.compute_sd_plus(P, by_h, lg, sc)
    ctn, _ = ct.compute_ct_plus(P, by_h, lg, sc)
    elig = H.precompute(P)
    rows = defaultdict(dict)
    with H.patched('_z16', True):
        swings = [p for p in elig if ct.is_ct_eligible(p)]
        offsets = ct.build_bip_count_offsets(swings, lg, sc)
        rv_fn = ct.make_rv_xrv(lg, sc, offsets)
        table = ct.shrink_contact_cells(ct.build_contact_cell_weights(swings, rv_fn),
                                        ct.zone_level_contact_means(swings, rv_fn))
        by_h_sw = defaultdict(list)
        for p in swings:
            by_h_sw[p['_bid']].append(p)
        # T0: where the leverage sits
        zl = defaultdict(lambda: [0.0, 0, 0])
        for p in swings:
            lev, con = ct.compute_ct_swing(p, table)
            if lev <= 0:
                continue
            z = ct.classify_zone(p); zl[z][0] += lev; zl[z][1] += 1; zl[z][2] += (1 - con)
        tl = sum(v[0] for v in zl.values()); tn = sum(v[1] for v in zl.values())
        t0 = {z: dict(lev_share=v[0] / tl, swing_share=v[1] / tn, whiff=v[2] / v[1], lev_per_swing=v[0] / v[1])
              for z, v in zl.items()}
        atoms, raw, nn = score_ct_atoms(by_h_sw, table, FULL_MIN_SW, SUB_MIN_SW)
        for name, d in atoms.items():
            for h, v in d.items():
                rows[h][name] = v; rows[h]['n_' + name] = nn[name][h]; rows[h]['raw_' + name] = raw[name][h]
        # random-subset contact placebo for the O-Contact% atom: plain contact
        # rate on a random subset of each hitter's swings, sized like his
        # out-of-zone set (3 seeds), raw and unshrunk
        for s in SEEDS:
            rr = random.Random(5000 * s + Y)
            for h, sw in by_h_sw.items():
                n_oz = sum(1 for p in sw if not in_zone(p))
                if n_oz < SUB_MIN_SW:
                    continue
                sub = rr.sample(sw, n_oz)
                rows[h][f'ocon_r{s}'] = sum(1 for p in sub if ct.classify_contact_outcome(p) == 'contact') / n_oz
        # placebo splits (3 seeds)
        for s in SEEDS:
            pa, _, _ = score_ct_atoms(by_h_sw, table, FULL_MIN_SW, SUB_MIN_SW, rng=random.Random(1000 * s + Y))
            for name in ('ct_iz', 'ct_oz'):
                for h, v in pa[name].items():
                    rows[h][f'{name}_r{s}'] = v
        # split-half reliability, 3 game-date seeds, table held at full season
        dates = sorted({p.get('Game Date') for p in swings if p.get('Game Date')})
        rel = {}
        for s in SEEDS:
            rr = random.Random(s * 7919 + Y); ds = set(rr.sample(dates, len(dates) // 2))
            halves = []
            for keep in (True, False):
                bh = defaultdict(list)
                for p in swings:
                    if (p.get('Game Date') in ds) == keep:
                        bh[p['_bid']].append(p)
                halves.append(score_ct_atoms(bh, table, HALF_MIN_SW, HALF_MIN_SW))
            (h1, _, n1), (h2, _, n2) = halves
            for name in h1:
                ks = [h for h in h1[name] if h in h2[name]]
                if len(ks) < 40:
                    continue
                r = float(np.corrcoef([h1[name][h] for h in ks], [h2[name][h] for h in ks])[0, 1])
                nh = float(np.mean([n1[name][h] for h in ks] + [n2[name][h] for h in ks]))
                rel.setdefault(name, []).append(dict(r=r, n=len(ks), n_half=nh, n0=nh * (1 - r) / r if r > 0 else None))
    # BB+ ingredients, outcomes
    for (b, _t), ps in by_h.items():
        bip = [p for p in ps if is_bip(p)]
        xw = [safe_float(p.get('xwOBA')) for p in bip]; xw = [v for v in xw if v is not None]
        ev = [safe_float(p.get('ExitVelo')) for p in bip]; ev = [v for v in ev if v is not None]
        r = rows[b]
        r['nbip'] = len(bip); r['xwcon'] = (sum(xw) / len(xw)) if xw else None; r['ev95'] = pct(ev, 95)
        s = sdn.get((b, '')) or {}
        r['sd'] = s.get('sdPlus'); r['n_dec'] = s.get('n_decisions') or 0; r['sd_raw'] = s.get('raw_sd')
        sw_all = [p for p in ps if p.get('Description') in ('Swinging Strike', 'Foul', 'In Play') and (p.get('BBType') or '') not in BUNT_BB]
        ooz = [p for p in ps if not in_zone(p) and p.get('Description') is not None]
        r['swing_pct'] = (len(sw_all) / len(ps)) if ps else None
        sw_ids = {id(p) for p in sw_all}
        r['chase'] = (sum(1 for p in ooz if id(p) in sw_ids) / len(ooz)) if ooz else None
        c = ctn.get((b, '')) or {}
        r['ct_prod'] = c.get('ctPlus')
        if Y != 2026:
            evs = [(p.get('event_raw') or '') for p in ps]
            pa_ev = [e for e in evs if e and e != 'intent_walk']
            r['pa_same'] = len(pa_ev)
            r['k_same'] = (sum(1 for e in pa_ev if 'strikeout' in e) / len(pa_ev)) if pa_ev else None
    if Y == 2026:
        lb = json.load(open(os.path.join(ROOT, 'data', 'hitter_leaderboard_rs.json')))
        best = {}
        for x in lb:
            if x.get('mlbId') is None or x.get('team') in ('ROC', 'AAA'):
                continue
            k = str(int(x['mlbId']))
            if k not in best or (x.get('pa') or 0) > (best[k].get('pa') or 0):
                best[k] = x
        for k, x in best.items():
            if k in rows:
                rows[k]['woba_same'] = x.get('wOBA'); rows[k]['pa_same'] = x.get('pa') or 0; rows[k]['k_same'] = x.get('kPct')
    else:
        for b, (num, den) in A.target_y(Y).items():
            if b in rows:
                rows[b]['woba_same'] = (num / den) if den else None; rows[b]['pa_same'] = den
    for r in rows.values():
        r.setdefault('woba_same', None); r.setdefault('pa_same', 0); r.setdefault('k_same', None)
    # BB+ displayed (prior-free process_data recipe)
    pool = [r for r in rows.values() if r.get('nbip', 0) >= BB_MIN_BIP and r.get('xwcon') is not None and r.get('ev95') is not None]
    lg_xc = sum(r['xwcon'] * r['nbip'] for r in pool) / sum(r['nbip'] for r in pool)
    lg_ev = sum(r['ev95'] * r['nbip'] for r in pool) / sum(r['nbip'] for r in pool)
    bx = [100 * r['ev95'] / lg_ev for r in pool if r['nbip'] >= BB_BETA_GATE_BIP]
    by = [100 * r['xwcon'] / lg_xc for r in pool if r['nbip'] >= BB_BETA_GATE_BIP]
    beta = BB_BETA_FROZEN
    if len(bx) >= BB_BETA_MIN_POOL:
        mx, my = np.mean(bx), np.mean(by)
        cand = float(np.sum((np.array(bx) - mx) * (np.array(by) - my)) / np.sum((np.array(bx) - mx) ** 2))
        if BB_BETA_BAND[0] <= cand <= BB_BETA_BAND[1]:
            beta = cand
    for r in pool:
        con = 100 * r['xwcon'] / lg_xc; evp = 100 + (100 * r['ev95'] / lg_ev - 100) * beta
        con_adj = (r['nbip'] * con + BB_N0_CON * 100) / (r['nbip'] + BB_N0_CON)
        ev_adj = (r['nbip'] * evp + BB_N0_EV * 100) / (r['nbip'] + BB_N0_EV)
        r['bb'] = 100 + (BB_W_CON * con_adj + BB_W_EV * ev_adj - 100) * BB_SLOPE_MATCH
    # parity: my ct_all (ratio to pool mean) vs production ctPlus
    ks = [h for h, r in rows.items() if r.get('ct_all') is not None and r.get('ct_prod') is not None and r.get('n_ct_all', 0) >= FULL_MIN_SW]
    if ks:
        lgm = float(np.mean([rows[h]['ct_all'] for h in ks]))
        mine = np.array([100 * rows[h]['ct_all'] / lgm for h in ks]); prod = np.array([rows[h]['ct_prod'] for h in ks])
        print(f"  {Y}: parity ct_all vs pipeline ctPlus on {len(ks)}: r {np.corrcoef(mine, prod)[0,1]:.4f}, max|diff| {np.max(np.abs(mine - prod)):.3f}", flush=True)
    print(f"  {Y}: hitters {len(rows)}, BB+ pool {len(pool)} (beta {beta:.3f}); leverage share by zone: "
          + ', '.join(f"{z} {v['lev_share']:.2f}" for z, v in sorted(t0.items(), key=lambda kv: -kv[1]['lev_share'])), flush=True)
    del P, elig, swings; gc.collect()
    return dict(rows), t0, rel


FRAMES_CACHE = os.path.join(ROOT, 'data', '_hitter_frames_2026_09.pkl')


def load_frames(rebuild=False):
    """Six season frames (rows only), cached after the first build."""
    import pickle
    if os.path.exists(FRAMES_CACHE) and not rebuild:
        return pickle.load(open(FRAMES_CACHE, 'rb'))
    lb = json.load(open(os.path.join(ROOT, 'data', 'hitter_leaderboard_rs.json')))
    name2id = {r['hitter']: str(int(r['mlbId'])) for r in lb if r.get('mlbId') is not None and r.get('hitter')}
    F = {}
    for Y in SEASONS:
        print(f"season {Y} ...", flush=True)
        F[Y], _, _ = season_frame(Y, name2id)
    pickle.dump(F, open(FRAMES_CACHE, 'wb'))
    return F


def z(v):
    v = np.asarray(v, float); return (v - v.mean()) / v.std()


def pear(a, b):
    return float(np.corrcoef(a, b)[0, 1])


def ols_w(X, y):
    Xd = np.column_stack([np.ones(len(y)), X]); beta, *_ = np.linalg.lstsq(Xd, y, rcond=None); return beta[1:]


def build_pairs(F):
    """Per pair: z-scored atoms on the composite pool, next-season targets."""
    ATOMS = ['bb', 'sd', 'ct_all', 'ct_iz', 'ct_oz', 'ct_heart', 'zcon', 'ocon', 'con'] + [f'{n}_r{s}' for n in ('ct_iz', 'ct_oz') for s in SEEDS]
    out = []
    for Y, Y1 in PAIRS:
        a, b = F[Y], F[Y1]
        ks = [h for h in a if h in b and all(a[h].get(k) is not None for k in ATOMS)
              and a[h].get('n_ct_all', 0) >= FULL_MIN_SW and a[h].get('n_dec', 0) >= FULL_MIN_DEC and a[h].get('nbip', 0) >= FULL_MIN_BIP
              and b[h].get('woba_same') is not None and b[h].get('pa_same', 0) >= NEXT_MIN_PA]
        Z = {k: z([a[h][k] for h in ks]) for k in ATOMS}
        Z['y'] = np.array([b[h]['woba_same'] for h in ks], float)
        kk = [b[h].get('k_same') for h in ks]
        Z['k_next'] = np.array([v if v is not None else np.nan for v in kk], float)
        Z['zcon_raw'] = np.array([a[h]['zcon'] for h in ks], float)
        Z['n'] = len(ks); Z['pair'] = f'{Y}-{Y1}'
        out.append(Z)
        print(f"  pair {Y}->{Y1}: composite pool {len(ks)}", flush=True)
    return out


def composite_fixed(Z, w, cols):
    return sum(wi * Z[c] for wi, c in zip(w, cols))


def lopo(pairs, cols, fixed_w=None):
    """Return per-fold (r, comp vector, weights)."""
    res = []
    for i, Zt in enumerate(pairs):
        if fixed_w is None:
            train = [Z for j, Z in enumerate(pairs) if j != i]
            X = np.vstack([np.column_stack([Z[c] for c in cols]) for Z in train]); y = np.concatenate([Z['y'] for Z in train])
            w = ols_w(X, y)
        else:
            w = np.asarray(fixed_w, float)
        comp = composite_fixed(Zt, w, cols)
        res.append((pear(comp, Zt['y']), comp, tuple(round(float(x), 3) for x in w)))
    return res


def boot_delta(pairs, resA, resB, seed=0):
    """Paired bootstrap over hitters, per fold, of r(A) - r(B); returns
    (per-fold delta, per-fold SE, mean delta, SE of the mean)."""
    rng = np.random.default_rng(seed)
    deltas, ses = [], []
    for Zt, (rA, cA, _), (rB, cB, _) in zip(pairs, resA, resB):
        n = Zt['n']; y = Zt['y']; d = []
        for _ in range(N_BOOT):
            idx = rng.integers(0, n, n)
            d.append(pear(cA[idx], y[idx]) - pear(cB[idx], y[idx]))
        deltas.append(rA - rB); ses.append(float(np.std(d)))
    m = float(np.mean(deltas)); se = math.sqrt(sum(s * s for s in ses)) / len(ses)
    return deltas, ses, m, se


def partial_r(Z, cand, given=('bb', 'sd', 'ct_all')):
    X = np.column_stack([Z[g] for g in given]); Xd = np.column_stack([np.ones(Z['n']), X])
    def resid(v):
        b, *_ = np.linalg.lstsq(Xd, v, rcond=None); return v - Xd @ b
    return pear(resid(Z[cand]), resid(Z['y']))


def main():
    lb = json.load(open(os.path.join(ROOT, 'data', 'hitter_leaderboard_rs.json')))
    name2id = {r['hitter']: str(int(r['mlbId'])) for r in lb if r.get('mlbId') is not None and r.get('hitter')}
    F, T0, REL = {}, {}, {}
    for Y in SEASONS:
        print(f"season {Y} ...", flush=True)
        F[Y], T0[Y], REL[Y] = season_frame(Y, name2id)
    out = {'t0': T0, 'reliability': REL}

    print("\n===== T0: where CT+'s weight sits (mean over seasons) =====")
    zones = ['heart', 'shadow_in', 'shadow_out', 'chase', 'waste']
    print("  zone         lev share  swing share  whiff  lev/swing")
    for zn in zones:
        v = [T0[Y][zn] for Y in SEASONS if zn in T0[Y]]
        print(f"  {zn:11s}  {np.mean([x['lev_share'] for x in v]):8.3f}  {np.mean([x['swing_share'] for x in v]):10.3f}  {np.mean([x['whiff'] for x in v]):5.3f}  {np.mean([x['lev_per_swing'] for x in v]):8.4f}")
    izs = float(np.mean([sum(T0[Y][zn]['lev_share'] for zn in IZ_ZONES if zn in T0[Y]) for Y in SEASONS]))
    print(f"  in-zone share of CT+ leverage: {izs:.3f}")
    out['iz_lev_share'] = izs

    print("\n===== T1a: split-half reliability (3 seeds x 6 seasons), implied n0 =====")
    names = ['ct_all', 'ct_iz', 'ct_oz', 'ct_heart', 'con', 'zcon', 'ocon']
    rel_sum = {}
    for nm in names:
        rs = [x['r'] for Y in SEASONS for x in REL[Y].get(nm, [])]
        n0s = [x['n0'] for Y in SEASONS for x in REL[Y].get(nm, []) if x['n0'] is not None]
        nh = [x['n_half'] for Y in SEASONS for x in REL[Y].get(nm, [])]
        rel_sum[nm] = dict(r=float(np.mean(rs)), n0=float(np.median(n0s)) if n0s else None, n_half=float(np.mean(nh)), cells=len(rs))
        print(f"  {nm:9s} rel r {np.mean(rs):.3f} (sd {np.std(rs):.3f}, {len(rs)} cells)  mean n/half {np.mean(nh):6.1f}  implied n0 median {np.median(n0s) if n0s else float('nan'):6.1f}")
    out['reliability_summary'] = rel_sum

    print("\n===== building pairs =====")
    pairs = build_pairs(F)
    out['pools'] = {Z['pair']: Z['n'] for Z in pairs}

    print("\n===== T1b: univariate r with next-season wOBA / next-season K% =====")
    uni = {}
    for nm in ['bb', 'sd'] + names:
        rw = [pear(Z[nm], Z['y']) for Z in pairs]
        rk = []
        for Z in pairs:
            m = np.isfinite(Z['k_next'])
            rk.append(pear(Z[nm][m], Z['k_next'][m]))
        uni[nm] = dict(woba=rw, k=rk)
        print(f"  {nm:9s} wOBA+1: mean {np.mean(rw):+.3f}  " + ' '.join(f"{v:+.3f}" for v in rw) + f"   | K%+1: mean {np.mean(rk):+.3f}  " + ' '.join(f"{v:+.3f}" for v in rk))
    out['univariate'] = uni

    print("\n===== T2: partial r given z(bb), z(sd), z(ct_all)  [gate 0.15] =====")
    part = {}
    for nm in ['ct_iz', 'ct_oz', 'ct_heart', 'zcon', 'ocon', 'con'] + [f'ct_iz_r{s}' for s in SEEDS]:
        pr = [partial_r(Z, nm) for Z in pairs]
        part[nm] = pr
        print(f"  {nm:9s} mean {np.mean(pr):+.4f}  " + ' '.join(f"{v:+.4f}" for v in pr))
    # in-zone given out-of-zone too: does iz add beyond (bb, sd, ct_oz)?
    pr = [partial_r(Z, 'ct_iz', given=('bb', 'sd', 'ct_oz')) for Z in pairs]; part['ct_iz|oz'] = pr
    print(f"  ct_iz | bb,sd,ct_oz: mean {np.mean(pr):+.4f}  " + ' '.join(f"{v:+.4f}" for v in pr))
    pr = [partial_r(Z, 'ct_oz', given=('bb', 'sd', 'ct_iz')) for Z in pairs]; part['ct_oz|iz'] = pr
    print(f"  ct_oz | bb,sd,ct_iz: mean {np.mean(pr):+.4f}  " + ' '.join(f"{v:+.4f}" for v in pr))
    out['partial'] = part

    print("\n===== T3: composite LOPO (5 folds), r with next-season wOBA =====")
    CONFIGS = {
        'SHIP 52/17/31': (('bb', 'sd', 'ct_all'), HP_W),
        'OLS3 bb,sd,ct_all': (('bb', 'sd', 'ct_all'), None),
        'IZOZ bb,sd,ct_iz,ct_oz': (('bb', 'sd', 'ct_iz', 'ct_oz'), None),
        'IZ bb,sd,ct_iz': (('bb', 'sd', 'ct_iz'), None),
        'HEART bb,sd,ct_heart': (('bb', 'sd', 'ct_heart'), None),
        'ZCON4 bb,sd,ct_all,zcon': (('bb', 'sd', 'ct_all', 'zcon'), None),
        'ZCON3 bb,sd,zcon': (('bb', 'sd', 'zcon'), None),
        'IZ4 bb,sd,ct_all,ct_iz': (('bb', 'sd', 'ct_all', 'ct_iz'), None),
    }
    res = {k: lopo(pairs, cols, w) for k, (cols, w) in CONFIGS.items()}
    base = res['OLS3 bb,sd,ct_all']
    t3 = {}
    for k, rr in res.items():
        rs = [x[0] for x in rr]
        d, se, m, sem = boot_delta(pairs, rr, base)
        wins = sum(1 for x in d if x > 0)
        t3[k] = dict(r=rs, mean=float(np.mean(rs)), delta_vs_ols3=d, se=se, mean_delta=m, se_mean=sem, wins=wins, weights=[x[2] for x in rr])
        print(f"  {k:26s} mean {np.mean(rs):+.4f}  " + ' '.join(f"{v:+.4f}" for v in rs)
              + f"   d vs OLS3 {m:+.4f} (SE {sem:.4f}, wins {wins}/5)")
        if CONFIGS[k][1] is None:
            print(f"    {'':26s} fold weights: " + '  '.join(str(w) for w in [x[2] for x in rr]))
    # placebo: random iz/oz split, 3 seeds
    pl = []
    for s in SEEDS:
        rr = lopo(pairs, ('bb', 'sd', f'ct_iz_r{s}', f'ct_oz_r{s}'), None)
        d, se, m, sem = boot_delta(pairs, rr, base)
        pl.append(dict(seed=s, r=[x[0] for x in rr], mean=float(np.mean([x[0] for x in rr])), mean_delta=m, se_mean=sem, wins=sum(1 for x in d if x > 0)))
        print(f"  PLACEBO iz/oz seed {s:<15d} mean {pl[-1]['mean']:+.4f}  " + ' '.join(f"{v:+.4f}" for v in pl[-1]['r']) + f"   d vs OLS3 {m:+.4f} (SE {sem:.4f}, wins {pl[-1]['wins']}/5)")
    t3['PLACEBO'] = pl
    print(f"  PLACEBO mean delta over seeds {np.mean([p['mean_delta'] for p in pl]):+.4f}; real IZOZ delta {t3['IZOZ bb,sd,ct_iz,ct_oz']['mean_delta']:+.4f}")
    # pooled OLS weights (all 5 pairs) for interpretation
    for k in ('OLS3 bb,sd,ct_all', 'IZOZ bb,sd,ct_iz,ct_oz', 'ZCON4 bb,sd,ct_all,zcon'):
        cols = CONFIGS[k][0]
        X = np.vstack([np.column_stack([Z[c] for c in cols]) for Z in pairs]); y = np.concatenate([Z['y'] for Z in pairs])
        w = ols_w(X, y); wn = w / np.sum(np.abs(w))
        t3[k]['pooled_w'] = [float(x) for x in w]; t3[k]['pooled_w_norm'] = [float(x) for x in wn]
        print(f"  pooled OLS {k}: " + ', '.join(f"{c} {x:+.3f}" for c, x in zip(cols, wn)) + "  (normalised to |sum| 1)")
    out['t3'] = t3

    print("\n===== T4: calibration — residual of held-out SHIP composite vs Z-Contact% =====")
    cal = []
    for Zt, (r, comp, _) in zip(pairs, res['SHIP 52/17/31']):
        sl, ic = np.polyfit(comp, Zt['y'], 1); resid = Zt['y'] - (sl * comp + ic)
        cal.append(pear(resid, Zt['zcon_raw']))
    print(f"  residual vs zcon: mean {np.mean(cal):+.3f}  " + ' '.join(f"{v:+.3f}" for v in cal))
    out['t4_resid_vs_zcon'] = cal

    json.dump(out, open(OUT, 'w'), indent=1, default=float)
    print(f"\nwrote {os.path.relpath(OUT, ROOT)}")


if __name__ == '__main__':
    main()
