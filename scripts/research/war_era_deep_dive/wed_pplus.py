"""wed_pplus.py - WAR/ERA deep dive, test 4: Pitcher+ weights on honest pools.

The shipped weights (.20 / .06 / .21 / .19 / .23 / .12) were fitted 2026-07-24 on Stuff+ v11 and the old Loc+,
on panels gated on BOTH sides (800 pitches full season, 300 a half). Here: Stuff+ v18 and the released Loc+
(far-miss series), base period gated only, every target row counted and weighted by its pitches.
  panel Y  season Y (300+ pitches) -> season Y+1 xRV/100 (1+ pitch, pitch weighted), 2021-2025, 4 pairs
  panel S  half A (150+ pitches) -> half B xRV/100 (1+ pitch, weighted), both directions, 5 seasons
Refit = weighted OLS on the shipped six shrunk z columns (shipped k), held out by season.
.venv/bin/python scripts/research/war_era_deep_dive/wed_pplus.py"""
import sys, os, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'stuff')); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'misc'))
import pitcherplus_v14_audit as A
ps = A.ps
ps.LOC_CSV = os.path.join(ROOT, 'data', '_pplus_locplus_far_1119.csv')
FE = A.SHIPPED_SUBSET; W0 = np.array([w for _f, w, _k in A.SHIPPED]); KM = {f: k for f, _w, k in A.SHIPPED}


def wcorr(x, y, w):
    mx, my = np.average(x, weights=w), np.average(y, weights=w)
    return float(np.sum(w * (x - mx) * (y - my)) / np.sqrt(np.sum(w * (x - mx) ** 2) * np.sum(w * (y - my) ** 2)))


def panels(t, base_full, base_half, gate_target):
    sz = [f + '_sz' for f in FE]
    full = A.shrunk_z(t[t['half'] == 'full'], FE, KM, A.Q_FULL)
    b = full[full['n'] >= base_full]; tg = full[full['n'] >= (A.MIN_FULL if gate_target else 1)].assign(season=lambda d: d['season'] - 1)
    p = b.merge(tg[['pid', 'season', 'xrv100', 'n']], on=['pid', 'season'], suffixes=('', '_n1')); p = p[np.isfinite(p['xrv100_n1'])]
    Y = (p[sz].to_numpy(float), p['xrv100_n1'].to_numpy(float), p['n_n1'].to_numpy(float) if not gate_target else np.ones(len(p)), p['season'].to_numpy())
    hv = A.shrunk_z(t[t['half'].isin(['A', 'B'])], FE, KM, A.Q_HALF)
    Xs, ys, ws, gs = [], [], [], []
    for a, bb in (('A', 'B'), ('B', 'A')):
        x = hv[(hv['half'] == a) & (hv['n'] >= base_half)]; y = hv[(hv['half'] == bb) & (hv['n'] >= (A.MIN_HALF if gate_target else 1))]
        m = x.merge(y[['pid', 'season', 'xrv100', 'n']], on=['pid', 'season'], suffixes=('', '_t')); m = m[np.isfinite(m['xrv100_t'])]
        Xs.append(m[sz].to_numpy(float)); ys.append(m['xrv100_t'].to_numpy(float)); ws.append(m['n_t'].to_numpy(float) if not gate_target else np.ones(len(m))); gs.append(m['season'].to_numpy())
    return Y, (np.vstack(Xs), np.concatenate(ys), np.concatenate(ws), np.concatenate(gs))


def fit(X, y, w):
    Am = np.column_stack([np.ones(len(X)), X]); sw = np.sqrt(w)
    return np.linalg.lstsq(Am * sw[:, None], y * sw, rcond=None)[0]


def evaluate(name, P):
    X, y, w, g = P
    seas = np.unique(g); r0, r1, betas = [], [], []
    for s in seas:
        te = g == s; b = fit(X[~te], y[~te], w[~te]); betas.append(b[1:] / b[1:].sum())
        r0.append(wcorr(X[te] @ W0, y[te], w[te])); r1.append(wcorr(X[te] @ b[1:], y[te], w[te]))
    r0, r1 = np.array(r0), np.array(r1); d = r1 - r0; ball = fit(X, y, w)[1:]; ball = ball / ball.sum()
    print(f" {name}: rows {len(y)}, replicates {len(seas)} | frozen shipped r {r0.mean():.4f} | held-out refit r {r1.mean():.4f} | refit minus shipped {d.mean():+.4f} (SE {d.std(ddof=1)/np.sqrt(len(d)):.4f}), better in {int((d > 0).sum())}/{len(d)}")
    print("    refit weights, all rows:   " + "  ".join(f"{f} {v:+.3f}" for f, v in zip(FE, ball)) + "   | shipped " + " ".join(f"{v:.2f}" for v in W0))
    print("    by held-out fold (stuff):  " + " ".join(f"{b[0]:.3f}" for b in betas) + "  (loc): " + " ".join(f"{b[1]:.3f}" for b in betas))
    # stuff weight curve: move weight between stuff and the other five in proportion
    line = []
    for ws_ in (0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50):
        wv = W0.copy(); rest = 1 - ws_; wv[1:] = W0[1:] / W0[1:].sum() * rest; wv[0] = ws_
        line.append(f"{ws_:.2f}:{np.mean([wcorr(X[g == s] @ wv, y[g == s], w[g == s]) for s in seas]):.4f}")
    print("    stuff weight curve (others in shipped proportion): " + "  ".join(line))
    line = []
    for wl in (0.0, 0.03, 0.06, 0.10, 0.15, 0.20):
        wv = W0.copy(); rest = 1 - wl; o = [0, 2, 3, 4, 5]; wv[o] = W0[o] / W0[o].sum() * rest; wv[1] = wl
        line.append(f"{wl:.2f}:{np.mean([wcorr(X[g == s] @ wv, y[g == s], w[g == s]) for s in seas]):.4f}")
    print("    loc weight curve:   " + "  ".join(line))
    return dict(r_ship=float(r0.mean()), r_refit=float(r1.mean()), d=float(d.mean()), w=ball.tolist())


def main():
    t = A.load_tables(os.path.join(ROOT, 'data', '_pplus_stuff_v18.csv'))
    print("seasons in the tables:", sorted(t['season'].unique()))
    res = {}
    for label, bf, bh, gt in (('GATED both sides (the shipped design: 800 / 300)', A.MIN_FULL, A.MIN_HALF, True),
                              ('HONEST: base 300 full / 150 half, target 1+ pitch, pitch weighted', 300, 150, False),
                              ('HONEST, wider base: 100 full / 60 half', 100, 60, False)):
        print(f"\n== {label}")
        Y, S = panels(t, bf, bh, gt)
        res[label + ' Y'] = evaluate('panel Y (next season)', Y); res[label + ' S'] = evaluate('panel S (other half)', S)
    json.dump(res, open(os.path.join(ROOT, 'data', '_wed', 'res_pplus.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
