"""wed_xrvoe_floor.py - can an objective choose the xRVOE display floors (XRVOE_MIN_PT 150, XRVOE_MIN_OV 300)?

The floor removes all four xRVOE keys from a row under it, and at the pitch-type level it is also the percentile
pool gate. Read at the SHIPPED shrinkage only (N0 800 pitch type, 1700 pitcher): reliability is gameable by shrinkage.
Six seasons of per-pitch residuals (data/_wed/xrvoe_rep_Y.pkl, built by wed_xrvoe_rep.py). Each unit's pitches are
split at random into two halves of m pitches (5 seeds); a half stands for a displayed unit of m pitches.
Per band of m:
  r        split-half correlation of the raw half means (the reliability of a unit of that size)
  slope    other-half raw mean on the shrunk value, through the origin, pitch weighted. 1.0 = the displayed value is
           calibrated at that size.
  gain     1 - MSE(shrunk value) / MSE(zero) against the other half: positive = showing the value beats showing
           nothing. A floor that accuracy can defend is the size under which this is not positive.
Last block: what the pitch-type percentile pool looks like on the shipped board, by pitch count.
.venv/bin/python scripts/research/war_era_deep_dive/wed_xrvoe_floor.py"""
import os, json
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))); W = os.path.join(ROOT, 'data', '_wed')
LEVELS = (('pitch type', ['pitcher', 'team', 'pitch_type'], 800, 150, [25, 50, 75, 100, 150, 200, 300, 500, 10 ** 6]),
          ('pitcher', ['pitcher', 'team'], 1700, 300, [50, 100, 150, 200, 300, 400, 600, 1000, 10 ** 6]))
rows = []
for Y in range(2021, 2027):
    d = pd.read_pickle(os.path.join(W, f'xrvoe_rep_{Y}.pkl')); d['team'] = d['team'].fillna('X')
    for tag, keys, n0, floor, edges in LEVELS:
        for seed in range(5):
            rng = np.random.default_rng(100 * seed + Y)
            for v in d.groupby(keys)['resid']:
                x = v[1].values; m = len(x) // 2
                if m < edges[0]:
                    continue
                p = rng.permutation(len(x)); rows.append((Y, tag, seed, m, x[p[:m]].mean() * 100, x[p[m:2 * m]].mean() * 100))
    del d
R = pd.DataFrame(rows, columns=['y', 'lvl', 'seed', 'm', 'a', 'b']); R.to_pickle(os.path.join(W, 'xrvoe_floor_rows.pkl'))
OUT = {}
for tag, keys, n0, floor, edges in LEVELS:
    g = R[R.lvl == tag].copy(); g['sh'] = g.m / (g.m + n0) * g.a
    print(f"\n{tag} (N0 {n0}, shipped floor {floor}). Band of pitches | units per season | kept share | split-half r | slope: mean over six seasons (SE), seasons above 0 | gain %: pooled, mean over seasons (SE), seasons positive")
    for lo, hi in zip(edges[:-1], edges[1:]):
        b = g[(g.m >= lo) & (g.m < hi)]; per = []
        for y, s in b.groupby('y'):
            if s[s.seed == 0].shape[0] < 20:
                continue
            sl = float((s.m * s.sh * s.b).sum() / (s.m * s.sh ** 2).sum()); gain = 1 - float((s.m * (s.b - s.sh) ** 2).sum() / (s.m * s.b ** 2).sum())
            per.append((y, sl, gain, float(np.mean([np.corrcoef(q.a, q.b)[0, 1] for _, q in s.groupby('seed')]))))
        if len(per) < 3:
            continue
        sl = np.array([p[1] for p in per]); ga = np.array([p[2] for p in per]); rr = np.array([p[3] for p in per]); pooled = 1 - float((b.m * (b.b - b.sh) ** 2).sum() / (b.m * b.b ** 2).sum())
        se = lambda v: v.std(ddof=1) / np.sqrt(len(v))
        print(f"   {lo:4d}-{hi if hi < 10 ** 6 else '+':>4} | {len(b) / 5 / b.y.nunique():6.0f} | {(b.m / (b.m + n0)).mean():.2f} | {rr.mean():.3f} | {sl.mean():.2f} ({se(sl):.2f}), {int((sl > 0).sum())}/{len(sl)} | {100 * pooled:.2f}, {100 * ga.mean():.2f} ({100 * se(ga):.2f}), {int((ga > 0).sum())}/{len(ga)}")
        OUT[f'{tag} {lo}'] = dict(r=float(rr.mean()), slope=float(sl.mean()), slope_se=float(se(sl)), gain=float(ga.mean()), gain_se=float(se(ga)), pos=int((ga > 0).sum()), n=len(ga))
    print("   the same at a stated reliability level: pitches at which r = N / (N + N0) reaches .10 / .15 / .25 / .50: " + " / ".join(f"{n0 * q / (1 - q):.0f}" for q in (.10, .15, .25, .50)))

print("\nshipped board, MLB club rows: the pitch-type percentile pool is every row over the floor")
T = [r for r in json.load(open(os.path.join(ROOT, 'data', 'pitch_leaderboard_rs.json'))) if r.get('xrvoe100') is not None and r.get('team') not in ('ROC', 'AAA') and not str(r.get('team', '')).endswith('TM')]
t = pd.DataFrame([dict(n=r['count'], v=r['xrvoe100'], p=r.get('xrvoe100_pctl'), pt=r['pitchType']) for r in T]).dropna()
print(f"   rows {len(t)}; share under 300 pitches {np.mean(t.n < 300):.2f}, under 500 {np.mean(t.n < 500):.2f}; correlation of |percentile - 50| with pitch count {np.corrcoef((t.p - 50).abs(), t.n)[0, 1]:.2f}")
for lo, hi in ((150, 250), (250, 400), (400, 700), (700, 5000)):
    b = t[(t.n >= lo) & (t.n < hi)]; print(f"   {lo}-{hi} pitches: {len(b)} rows, SD of the value {b.v.std():.3f}, share with a percentile outside 20-80: {np.mean((b.p < 20) | (b.p > 80)):.2f}")
json.dump(OUT, open(os.path.join(W, 'res_xrvoe_floor.json'), 'w'), indent=1)
