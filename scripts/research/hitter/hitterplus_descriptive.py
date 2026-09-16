"""hitterplus_descriptive.py — a DESCRIPTIVE Hitter+: the same three
luck-free atoms (BB+, SD+, CT+), weighted to explain SAME-season actual
production instead of next-season production. (2026-09-16, per Wally:
"there should be a descriptive version and a predictive version".)

Frames come from izcontact_battery.season_frame (2021-2026, production
atoms, cached to data/_hitter_frames_2026_09.pkl after the first build).
Target = same-season actual wOBA (an OUTCOME target, per
reference_grader_traps_hitter_channels; xwOBA would share BB+'s model
family). Luck averages out across the pool, so the fitted composite reads
as "the production this process should have yielded".

  D1  leave-one-SEASON-out weights on (bb, sd, ct_all): fit on 5, score the
      6th; simplex (.01) argmax + 0.001-flat region; per-season argmax
      stability; the same at the qualified PA floor
  D2  held-out same-season r: SHIP 52/17/31 vs DESC-LOSO vs in-sample OLS,
      paired bootstrap SE
  D3  candidate atoms under the descriptive objective (partial r given the
      three, LOSO composites with the random-split placebo)
  D4  predictive COST of the descriptive weights (next-season pairs,
      izcontact_battery.build_pairs) — the trade-off Wally is choosing
  D5  2026 board: descriptive Hitter+ from weights derived on 2021-2025
      only, scale-matched to the qualified pool's wRC+ exactly as
      production does (r x SD(wRC+)), movers vs shipped hitterPlus, and
      wRC+ minus descriptive Hitter+ as the residual (luck + unmodelled)

Usage: python3 scripts/research/hitter/hitterplus_descriptive.py [--rebuild]
Output: console, data/_hitterplus_descriptive.json,
        ~/Downloads/hitterplus_descriptive_2026.csv
"""
import csv, json, math, os, pickle, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import izcontact_battery as B

SEASONS = B.SEASONS
OUT = os.path.join(ROOT, 'data', '_hitterplus_descriptive.json')
CSV = os.path.expanduser('~/Downloads/hitterplus_descriptive_2026.csv')
PA_FLOOR = 300
PA_QUAL = {Y: 502 for Y in SEASONS}; PA_QUAL[2026] = 430   # 3.1 x games, 2026 partial
HP_W = B.HP_W
ATOMS3 = ('bb', 'sd', 'ct_all')
CANDS = ['ct_iz', 'ct_oz', 'ct_heart', 'zcon', 'ocon', 'con']


def load_frames(rebuild=False):
    return B.load_frames(rebuild)


def season_pool(rows, pa_floor, atoms):
    ks = [h for h, r in rows.items() if all(r.get(k) is not None for k in atoms)
          and r.get('n_ct_all', 0) >= B.FULL_MIN_SW and r.get('n_dec', 0) >= B.FULL_MIN_DEC and r.get('nbip', 0) >= B.FULL_MIN_BIP
          and r.get('woba_same') is not None and r.get('pa_same', 0) >= pa_floor]
    Z = {k: B.z([rows[h][k] for h in ks]) for k in atoms}
    Z['y'] = np.array([rows[h]['woba_same'] for h in ks], float)
    Z['n'] = len(ks); Z['keys'] = ks
    return Z


def loso(frames, cols, fixed_w=None):
    """Per season: weights fit on the other five (or fixed), held-out r."""
    res = []
    for i, Zt in enumerate(frames):
        if fixed_w is None:
            train = [Z for j, Z in enumerate(frames) if j != i]
            X = np.vstack([np.column_stack([Z[c] for c in cols]) for Z in train]); y = np.concatenate([Z['y'] for Z in train])
            w = B.ols_w(X, y)
        else:
            w = np.asarray(fixed_w, float)
        comp = B.composite_fixed(Zt, w, cols)
        res.append((B.pear(comp, Zt['y']), comp, tuple(round(float(x), 3) for x in w)))
    return res


def norm_w(w):
    w = np.asarray(w, float); return w / np.sum(np.abs(w))


def simplex(frames, cols, step=0.01):
    """Mean same-season r over seasons on the unit simplex; argmax and the
    0.001-flat region. Weights act on z-scored atoms, so a simplex point IS
    the published weight triple."""
    best, bw, grid = None, None, []
    n = int(round(1 / step))
    for a in range(n + 1):
        for b in range(n + 1 - a):
            w = (a * step, b * step, 1 - a * step - b * step)
            m = float(np.mean([B.pear(B.composite_fixed(Z, w, cols), Z['y']) for Z in frames]))
            grid.append((m, w))
            if best is None or m > best:
                best, bw = m, w
    within = [w for m, w in grid if m >= best - 0.001]
    lo = tuple(min(w[i] for w in within) for i in range(3)); hi = tuple(max(w[i] for w in within) for i in range(3))
    return best, bw, lo, hi, grid


def per_season_argmax(frames, cols, step=0.01):
    out = []
    n = int(round(1 / step))
    for Z in frames:
        best, bw = None, None
        for a in range(n + 1):
            for b in range(n + 1 - a):
                w = (a * step, b * step, 1 - a * step - b * step)
                m = B.pear(B.composite_fixed(Z, w, cols), Z['y'])
                if best is None or m > best:
                    best, bw = m, w
        out.append((bw, best))
    return out


def main():
    rebuild = '--rebuild' in sys.argv
    F = load_frames(rebuild)
    out = {}
    all_atoms = list(ATOMS3) + CANDS + [f'{n}_r{s}' for n in ('ct_iz', 'ct_oz') for s in B.SEEDS]
    frames = [season_pool(F[Y], PA_FLOOR, all_atoms) for Y in SEASONS]
    frames_q = [season_pool(F[Y], PA_QUAL[Y], all_atoms) for Y in SEASONS]
    print("pools (>=300 PA / qualified): " + ', '.join(f"{Y} {Z['n']}/{Zq['n']}" for Y, Z, Zq in zip(SEASONS, frames, frames_q)))
    out['pools'] = {Y: [Z['n'], Zq['n']] for Y, Z, Zq in zip(SEASONS, frames, frames_q)}

    print("\n===== D1: descriptive weights, same-season actual wOBA =====")
    best, bw, lo, hi, grid = simplex(frames, ATOMS3)
    ship_m = float(np.mean([B.pear(B.composite_fixed(Z, HP_W, ATOMS3), Z['y']) for Z in frames]))
    print(f"  pooled simplex argmax bb/sd/ct = {bw[0]:.2f}/{bw[1]:.2f}/{bw[2]:.2f} at r {best:.4f}; shipped 52/17/31 at {ship_m:.4f}")
    print(f"  0.001-flat region: bb [{lo[0]:.2f},{hi[0]:.2f}] sd [{lo[1]:.2f},{hi[1]:.2f}] ct [{lo[2]:.2f},{hi[2]:.2f}]")
    ps = per_season_argmax(frames, ATOMS3)
    print("  per-season argmax: " + '  '.join(f"{Y} {w[0]:.2f}/{w[1]:.2f}/{w[2]:.2f} (r {r:.3f})" for Y, (w, r) in zip(SEASONS, ps)))
    bestq, bwq, loq, hiq, _ = simplex(frames_q, ATOMS3)
    print(f"  qualified-floor argmax {bwq[0]:.2f}/{bwq[1]:.2f}/{bwq[2]:.2f} at r {bestq:.4f}; flat bb [{loq[0]:.2f},{hiq[0]:.2f}] sd [{loq[1]:.2f},{hiq[1]:.2f}] ct [{loq[2]:.2f},{hiq[2]:.2f}]")
    desc_loso = loso(frames, ATOMS3)
    print("  LOSO OLS weights (normalised), fit on the other five: " + '  '.join(f"{Y} " + '/'.join(f"{x:.2f}" for x in norm_w(w)) for Y, (_, _, w) in zip(SEASONS, desc_loso)))
    X = np.vstack([np.column_stack([Z[c] for c in ATOMS3]) for Z in frames]); y = np.concatenate([Z['y'] for Z in frames])
    w_pooled = norm_w(B.ols_w(X, y))
    print(f"  pooled OLS (all six seasons), normalised: {w_pooled[0]:.3f}/{w_pooled[1]:.3f}/{w_pooled[2]:.3f}")
    out['d1'] = dict(argmax=bw, r_argmax=best, r_ship=ship_m, flat_lo=lo, flat_hi=hi, per_season=[(w, r) for w, r in ps],
                     argmax_qual=bwq, r_argmax_qual=bestq, flat_qual=(loq, hiq), loso_w=[list(norm_w(w)) for _, _, w in desc_loso], pooled_w=list(w_pooled))
    DESC_W = tuple(round(float(x), 2) for x in w_pooled)

    print("\n===== D2: held-out same-season r per season =====")
    ship = loso(frames, ATOMS3, HP_W)
    ins = [(B.pear(B.composite_fixed(Z, B.ols_w(np.column_stack([Z[c] for c in ATOMS3]), Z['y']), ATOMS3), Z['y']), None, None) for Z in frames]

    def show(name, rr, base=None):
        rs = [x[0] for x in rr]
        line = f"  {name:28s} mean {np.mean(rs):.4f}  " + ' '.join(f"{v:.4f}" for v in rs)
        rec = dict(r=rs, mean=float(np.mean(rs)))
        if base is not None:
            d, se, m, sem = B.boot_delta(frames, rr, base)
            line += f"   d vs SHIP {m:+.4f} (SE {sem:.4f}, wins {sum(1 for x in d if x > 0)}/{len(d)})"
            rec.update(delta=d, mean_delta=m, se=sem, wins=sum(1 for x in d if x > 0))
        print(line); return rec
    d2 = {}
    d2['ship'] = show('SHIP 52/17/31', ship)
    d2['desc_loso'] = show('DESC LOSO (fit on other 5)', desc_loso, ship)
    d2['desc_fixed'] = show(f'DESC fixed {DESC_W[0]:.2f}/{DESC_W[1]:.2f}/{DESC_W[2]:.2f}', loso(frames, ATOMS3, DESC_W), ship)
    print(f"  {'in-sample OLS (ceiling)':28s} mean {np.mean([x[0] for x in ins]):.4f}  " + ' '.join(f"{v:.4f}" for v, _, _ in ins))
    out['d2'] = d2

    print("\n===== D3: candidate atoms under the descriptive objective =====")
    d3 = {'partial': {}, 'loso': {}}
    for nm in CANDS + [f'ct_iz_r{s}' for s in B.SEEDS]:
        pr = [B.partial_r(Z, nm) for Z in frames]; d3['partial'][nm] = pr
        print(f"  partial {nm:9s} mean {np.mean(pr):+.4f}  " + ' '.join(f"{v:+.4f}" for v in pr))
    base3 = desc_loso
    for name, cols in (('IZOZ bb,sd,ct_iz,ct_oz', ('bb', 'sd', 'ct_iz', 'ct_oz')), ('ZCON4 bb,sd,ct_all,zcon', ('bb', 'sd', 'ct_all', 'zcon')),
                       ('OCON4 bb,sd,ct_all,ocon', ('bb', 'sd', 'ct_all', 'ocon')), ('IZ bb,sd,ct_iz', ('bb', 'sd', 'ct_iz'))):
        rr = loso(frames, cols); d, se, m, sem = B.boot_delta(frames, rr, base3)
        d3['loso'][name] = dict(r=[x[0] for x in rr], mean_delta=m, se=sem, wins=sum(1 for x in d if x > 0), w=[x[2] for x in rr])
        print(f"  {name:26s} mean {np.mean([x[0] for x in rr]):.4f}   d vs DESC LOSO {m:+.4f} (SE {sem:.4f}, wins {sum(1 for x in d if x > 0)}/6)  w " + ' '.join('/'.join(f"{v:+.2f}" for v in norm_w(x[2])) for x in rr[:2]) + ' ...')
    pl = []
    for s in B.SEEDS:
        rr = loso(frames, ('bb', 'sd', f'ct_iz_r{s}', f'ct_oz_r{s}')); d, se, m, sem = B.boot_delta(frames, rr, base3); pl.append(m)
    print(f"  PLACEBO iz/oz random split: mean delta over 3 seeds {np.mean(pl):+.4f}")
    d3['placebo'] = pl
    out['d3'] = d3

    print("\n===== D4: predictive COST of the descriptive weights (next-season wOBA, 5 pairs) =====")
    pairs = B.build_pairs(F)
    pred_ship = B.lopo(pairs, ATOMS3, HP_W); pred_desc = B.lopo(pairs, ATOMS3, DESC_W)
    d, se, m, sem = B.boot_delta(pairs, pred_desc, pred_ship)
    print(f"  SHIP {HP_W} next-season r mean {np.mean([x[0] for x in pred_ship]):.4f}; DESC {DESC_W} {np.mean([x[0] for x in pred_desc]):.4f}; d {m:+.4f} (SE {sem:.4f}, wins {sum(1 for x in d if x > 0)}/5)")
    out['d4'] = dict(ship=[x[0] for x in pred_ship], desc=[x[0] for x in pred_desc], delta=m, se=sem)

    print("\n===== D5: 2026 board — descriptive Hitter+ from 2021-2025 weights =====")
    X = np.vstack([np.column_stack([Z[c] for c in ATOMS3]) for Z, Y in zip(frames, SEASONS) if Y != 2026]); y = np.concatenate([Z['y'] for Z, Y in zip(frames, SEASONS) if Y != 2026])
    w26 = tuple(float(x) for x in norm_w(B.ols_w(X, y)))
    print(f"  weights derived on 2021-2025 only: {w26[0]:.3f}/{w26[1]:.3f}/{w26[2]:.3f}")
    lb = json.load(open(os.path.join(ROOT, 'data', 'hitter_leaderboard_rs.json')))
    best = {}
    for x in lb:
        if x.get('mlbId') is None or x.get('team') in ('ROC', 'AAA'):
            continue
        k = str(int(x['mlbId']))
        if k not in best or (x.get('pa') or 0) > (best[k].get('pa') or 0):
            best[k] = x
    rows = F[2026]
    # production construction: z against the qualified pool, scale = r x SD(wRC+)/SD(zcomp) on that pool
    q = [h for h, r in rows.items() if all(r.get(k) is not None for k in ATOMS3) and h in best and (best[h].get('pa') or 0) >= PA_QUAL[2026] and best[h].get('wRCplus') is not None]
    m = {k: float(np.mean([rows[h][k] for h in q])) for k in ATOMS3}; s = {k: float(np.std([rows[h][k] for h in q])) for k in ATOMS3}
    def zc(h, w):
        return sum(wi * (rows[h][k] - m[k]) / s[k] for wi, k in zip(w, ATOMS3))
    zq = np.array([zc(h, w26) for h in q]); wq = np.array([best[h]['wRCplus'] for h in q], float)
    r26 = B.pear(zq, wq); scale = r26 * float(np.std(wq)) / float(np.std(zq))
    zq_ship = np.array([zc(h, HP_W) for h in q]); r26_ship = B.pear(zq_ship, wq)
    print(f"  qualified pool {len(q)}: r(desc comp, wRC+) {r26:.3f} (shipped weights {r26_ship:.3f}; production live r .739), scale {scale:.2f}")
    table = []
    for h, r in rows.items():
        if not all(r.get(k) is not None for k in ATOMS3) or h not in best:
            continue
        b = best[h]
        hp_desc = 100 + scale * zc(h, w26)
        table.append(dict(mlbId=h, hitter=b.get('hitter'), team=b.get('team'), pa=b.get('pa'), bbPlus=r['bb'], sdPlus=r['sd'], ctPlus=100 * r['ct_all'] / float(np.mean([rows[k]['ct_all'] for k in q])),
                          hitterPlus=b.get('hitterPlus'), hitterPlusDesc=hp_desc, wRCplus=b.get('wRCplus'), xWRCplus=b.get('xWRCplus'),
                          delta_desc_minus_ship=(hp_desc - b['hitterPlus']) if b.get('hitterPlus') is not None else None,
                          resid_wrc_minus_desc=(b['wRCplus'] - hp_desc) if b.get('wRCplus') is not None else None))
    tq = [t for t in table if (t['pa'] or 0) >= PA_QUAL[2026] and t['hitterPlus'] is not None]
    tq.sort(key=lambda t: -abs(t['delta_desc_minus_ship']))
    print(f"  qualified movers, |desc - shipped| largest (of {len(tq)}):")
    print("    hitter                  team   PA   BB+   SD+   CT+  ship  desc   d   wRC+  xwRC+")
    for t in tq[:14]:
        print(f"    {t['hitter'][:22]:22s}  {t['team']:4s} {t['pa']:4d} {t['bbPlus']:5.0f} {t['sdPlus']:5.0f} {t['ctPlus']:5.0f} {t['hitterPlus']:5.0f} {t['hitterPlusDesc']:5.0f} {t['delta_desc_minus_ship']:+4.0f}  {t['wRCplus']:5.0f}  {t['xWRCplus'] if t['xWRCplus'] is not None else float('nan'):5.0f}")
    ds = np.array([t['delta_desc_minus_ship'] for t in tq]); print(f"  qualified: mean |d| {np.mean(np.abs(ds)):.1f}, max |d| {np.max(np.abs(ds)):.1f}, rank corr desc vs shipped {np.corrcoef(np.argsort(np.argsort([t['hitterPlusDesc'] for t in tq])), np.argsort(np.argsort([t['hitterPlus'] for t in tq])))[0,1]:.3f}")
    tq.sort(key=lambda t: -(t['resid_wrc_minus_desc'] or 0))
    print("  wRC+ minus descriptive Hitter+ (results above process), top 8 and bottom 8:")
    for t in tq[:8] + tq[-8:]:
        print(f"    {t['hitter'][:22]:22s}  {t['team']:4s} {t['pa']:4d}  desc {t['hitterPlusDesc']:5.0f}  wRC+ {t['wRCplus']:5.0f}  resid {t['resid_wrc_minus_desc']:+5.0f}  xwRC+ {t['xWRCplus'] if t['xWRCplus'] is not None else float('nan'):5.0f}")
    out['d5'] = dict(w26=w26, r26=r26, r26_ship=r26_ship, scale=scale, n_qual=len(q))
    with open(CSV, 'w', newline='') as f:
        wr = csv.DictWriter(f, fieldnames=list(table[0].keys())); wr.writeheader()
        for t in sorted(table, key=lambda t: -(t['hitterPlusDesc'] or -999)):
            wr.writerow({k: (round(v, 1) if isinstance(v, float) else v) for k, v in t.items()})
    json.dump(out, open(OUT, 'w'), indent=1, default=float)
    print(f"\nwrote {os.path.relpath(OUT, ROOT)} and {CSV}")


if __name__ == '__main__':
    main()
