"""wed_n0.py - the hitter hdWAR shrink constant HWAR_N0_BAT (77) on the shipped PA-level target mu = a + b ln(PA).

shrunk rate = (n x + N0 mu) / (n + N0), x = the hitter's park-adjusted xhb per PA. Same-season, descriptive: every
criterion compares the shrunk rate with the SAME season's actual wOBA or actual club runs. No target period, no gate
on one. Seasons 2021-2026, each rebuilt self-contained (hwar_component_scale / hwar_forecast_honest).

Criteria (each read on a grid from 0 to 300):
  ALL   slope of actual wOBA on the shrunk rate, every hitter, PA weighted, season centered. 1.0 = one deserved
        point is one actual point. Also the fixed-slope error: PA-weighted mean of (actual dev - shrunk dev)^2.
  CLUB  slope of club runs scored on the club's summed batting runs (with baserunning and park beside it), and the
        club-run error with the batting slope fixed at 1.
  REG   the ALL slope on hitters with 300+ PA in the SAME season (the pool behind 77). Playing time follows results
        inside a season, so this pool is gated on the outcome.
  REGP  the same slope on hitters with 300+ PA in the PREVIOUS season, every PA of the current one counted.
.venv/bin/python scripts/research/war_era_deep_dive/wed_n0.py"""
import sys, os, json, io, contextlib
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'hitter')); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'era')); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'projection'))
import hwar_component_scale as CS
HH = CS.HH; SEASONS = list(CS.SEASONS)
RAW = {y: HH.rates(y, 'full', 0) for y in SEASONS}
GRID = [0, 5, 10, 15, 20, 25, 30, 40, 50, 60, 70, 77, 90, 110, 150, 200, 300]
RPW = 10.2


def mu_log(a):
    ln = np.log(a['n'].clip(lower=1)); X = np.column_stack([np.ones(len(a)), ln]); sw = np.sqrt(a['n'].values)
    return pd.Series(X @ np.linalg.lstsq(X * sw[:, None], a['xhb'].values * sw, rcond=None)[0], index=a.index)


MU = {y: mu_log(RAW[y]) for y in SEASONS}


def variant(n0):
    out = {}
    for y in SEASONS:
        a = RAW[y]; sh = (a['n'] * a['xhb'] + n0 * MU[y]) / (a['n'] + n0) if n0 else a['xhb']
        out[y] = pd.DataFrame(dict(n=a['n'], sh=sh, woba=a['woba']))
    return out


def dev(V, y):
    a = V[y]; return a['sh'] - np.average(a['sh'], weights=a['n']), a['woba'] - np.average(a['woba'], weights=a['n']), a['n'].astype(float)


def slope(V, mask=None, seasons=SEASONS):
    sxy = sxx = 0.0
    for y in seasons:
        x, yv, w = dev(V, y); m = mask(y, V[y]) if mask else np.ones(len(x), bool); sxy += float((w * x * yv)[m].sum()); sxx += float((w * x * x)[m].sum())
    return sxy / sxx


def mse(V, y):
    x, yv, w = dev(V, y); return float((w * (yv - x) ** 2).sum() / w.sum())


def club(V):
    rows = []
    for y in SEASONS:
        b, _p = CS.shares(y); a = V[y]; sc = HH.SCALE[y]; L = float(np.average(a['sh'], weights=a['n'])); C = defaultdict(float)
        for pid, r in a.iterrows():
            for c, v in CS.spread(str(pid), (r['sh'] - L) * r['n'] / sc, b).items():
                C[c] += v
        rows += [dict(r, bat=C.get(r['club'], 0.0)) for r in CS.ROWS if r['y'] == y]
    for r in rows:
        r['rs_less_bat'] = r['rs'] - r['bat']
    with contextlib.redirect_stdout(io.StringIO()):
        f = CS.fit('rs', ['bat', 'bsr', 'park'], rows=rows); g = CS.fit('rs_less_bat', ['bsr', 'park'], rows=rows)
    per = {}
    for y in SEASONS:
        rr = [r for r in rows if r['y'] == y]
        with contextlib.redirect_stdout(io.StringIO()):
            per[y] = CS.fit('rs_less_bat', ['bsr', 'park'], rows=rr)['rmse']
    return f['slopes']['bat']['b'], f['slopes']['bat']['se'], f['slopes']['bat']['per'], g['rmse'], per


reg = lambda y, a: (a['n'] >= 300).values
low = lambda y, a: (a['n'] < 100).values
mid = lambda y, a: ((a['n'] >= 100) & (a['n'] < 300)).values
def regp(y, a):
    p = RAW.get(y - 1); return a.index.isin(p.index[p['n'] >= 300]) if p is not None else np.zeros(len(a), bool)


print(f"seasons {SEASONS}; hitters per season {[len(RAW[y]) for y in SEASONS]}; target mu = a + b ln PA fitted per season")
print("\n N0 | ALL slope | ALL error x1e4 (pooled) | CLUB slope (SE) | CLUB error, runs (slope fixed at 1) | REG slope | REGP slope | under 100 PA | 100-300 PA")
T = {}
for n0 in GRID:
    V = variant(n0); cb, cse, cper, crm, crm_y = club(V); ms = {y: mse(V, y) for y in SEASONS}
    T[n0] = dict(all=slope(V), all_y={y: slope(V, seasons=[y]) for y in SEASONS}, mse=ms, club=cb, club_se=cse, club_y=cper, club_rmse=crm, club_rmse_y=crm_y,
                 reg=slope(V, reg), reg_y={y: slope(V, reg, [y]) for y in SEASONS}, regp=slope(V, regp, [y for y in SEASONS if y - 1 in RAW]), low=slope(V, low), mid=slope(V, mid))
    t = T[n0]; print(f" {n0:3d} | {t['all']:.3f} | {1e4 * np.mean(list(ms.values())):.4f} | {cb:.3f} ({cse:.3f}) | {crm:.3f} | {t['reg']:.3f} | {t['regp']:.3f} | {t['low']:.3f} | {t['mid']:.3f}", flush=True)


def cross(key, src=None):
    v = [(n0, (src(T[n0]) if src else T[n0][key])) for n0 in GRID]
    for (a, fa), (b, fb) in zip(v[:-1], v[1:]):
        if (fa - 1) * (fb - 1) <= 0 and fa != fb:
            return a + (1 - fa) * (b - a) / (fb - fa)
    return None


def argmin(f):
    v = [f(T[n0]) for n0 in GRID]; i = int(np.argmin(v)); flat = [GRID[k] for k in range(len(GRID)) if v[k] <= v[i] * 1.001]
    return GRID[i], ('interior' if 0 < i < len(GRID) - 1 else 'GRID EDGE'), flat, v


fmt = lambda c: 'no crossing on the grid' if c is None else f"{c:.0f}"
print("\nN0 where each slope reads 1.0 (linear between grid points): pooled, then by season")
print("   ALL  : " + fmt(cross('all')) + " | " + " ".join(f"{y}:{fmt(cross(None, lambda t, y=y: t['all_y'][y]))}" for y in SEASONS))
print("   CLUB : " + fmt(cross('club')) + f" (the slope SE near the crossing is {T[20]['club_se']:.3f}; N0 where the slope is 1 +/- 1 SE: {fmt(cross(None, lambda t: t['club'] + t['club_se']))} to {fmt(cross(None, lambda t: t['club'] - t['club_se']))}) | " + " ".join(f"{y}:{fmt(cross(None, lambda t, i=i: t['club_y'][i]))}" for i, y in enumerate(SEASONS)))
print("   REG  : " + fmt(cross('reg')) + " | " + " ".join(f"{y}:{fmt(cross(None, lambda t, y=y: t['reg_y'][y]))}" for y in SEASONS))
print("   REGP : " + fmt(cross('regp')))
print("\nerror objectives (slope fixed at 1): best N0, position, N0 within 0.1% of the best")
b, pos, flat, v = argmin(lambda t: np.mean(list(t['mse'].values()))); i77 = GRID.index(77)
print(f"   ALL error pooled: best {b} ({pos}), flat {min(flat)}-{max(flat)}; 77 costs {100 * (v[i77] / min(v) - 1):.2f}%")
by = {y: argmin(lambda t, y=y: t['mse'][y])[0] for y in SEASONS}; print("      by season: " + " ".join(f"{y}:{by[y]}" for y in SEASONS))
w = 0; out = []
for h in SEASONS:
    pick = argmin(lambda t, h=h: np.mean([t['mse'][y] for y in SEASONS if y != h]))[0]; a, s = T[pick]['mse'][h], T[77]['mse'][h]; w += a < s; out.append(f"{h}:{pick} {1e4 * a:.4f}/{1e4 * s:.4f}")
print(f"      leave-one-season-out (pick on five, score the sixth against 77): wins {w}/{len(SEASONS)} | " + " ".join(out))
b, pos, flat, v = argmin(lambda t: t['club_rmse']); print(f"   CLUB error pooled: best {b} ({pos}), flat {min(flat)}-{max(flat)}; 77 costs {100 * (v[i77] / min(v) - 1):.2f}%")
print("      by season: " + " ".join(f"{y}:{argmin(lambda t, y=y: t['club_rmse_y'][y])[0]}" for y in SEASONS))
w = 0; out = []
for h in SEASONS:
    pick = argmin(lambda t, h=h: np.mean([t['club_rmse_y'][y] ** 2 for y in SEASONS if y != h]))[0]; a, s = T[pick]['club_rmse_y'][h], T[77]['club_rmse_y'][h]; w += a < s; out.append(f"{h}:{pick} {a:.2f}/{s:.2f}")
print(f"      leave-one-season-out: wins {w}/{len(SEASONS)} | " + " ".join(out))

print(f"\nmovement of hdWAR batting value on {SEASONS[-1]} against N0 77, in wins at {RPW} runs per win (research rebuild, not the shipped rows)")
y = SEASONS[-1]; sc = HH.SCALE[y]; names = {}
try:
    for r in json.load(open(os.path.join(ROOT, 'data', 'hitter_leaderboard_rs.json'))):
        if r.get('mlbId') is not None:
            names[str(r['mlbId'])] = r['hitter']
except (OSError, KeyError) as e:
    print('   names not loaded:', e)
def wins(n0):
    a = variant(n0)[y]; return (a['sh'] - np.average(a['sh'], weights=a['n'])) * a['n'] / sc / RPW
base = wins(77); n = RAW[y]['n']
for alt in (0, 10, 20, 40, 150):
    d = wins(alt) - base; print(f"   N0 {alt}:")
    for nm, m in (('under 100 PA', n < 100), ('100-300 PA', (n >= 100) & (n < 300)), ('300+ PA', n >= 300)):
        dd = d[m]; top = dd.abs().sort_values(ascending=False).index[:3]
        print(f"      {nm}: {int(m.sum())} hitters, mean |change| {dd.abs().mean():.3f}, largest {dd.abs().max():.2f} | " + "; ".join(f"{names.get(str(p), p)} ({int(n[p])} PA) {base[p]:.2f} -> {base[p] + d[p]:.2f}" for p in top))
json.dump({str(k): {kk: (vv if not isinstance(vv, dict) else {str(a): b for a, b in vv.items()}) for kk, vv in v.items()} for k, v in T.items()}, open(os.path.join(ROOT, 'data', '_wed', 'res_n0.json'), 'w'), indent=1)
