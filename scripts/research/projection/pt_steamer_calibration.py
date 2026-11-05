"""pt_steamer_calibration.py: map Steamer playing time onto a usable level for the hpWAR total (2026-11-04).

Steamer ranks next-season PA and IP better than pt_backtest but reads high: preseason IP runs 22-31 percent over actual on the projection pool. Form:
    pt = max(0, a + b x Steamer)
b is swept. a is SOLVED per season and side so the pool's sum equals the sum of our own held-out playing time, whose level is calibrated (slope near 1), so a uses no target information.
Objective: unweighted RMSE of projected against actual PT over the pool, absent = 0. Held out: b chosen on the other seasons, scored on the left-out one, against our model and the flat scale (a = 0).
Preseason Steamer only: November files have no history, so b is fitted on better-informed files.
Usage: PYTHONHASHSEED=0 python3 scripts/research/projection/pt_steamer_calibration.py
Output: console + data/_war_honest/pt_calibration.json
"""
import contextlib, io, json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import hpwar_total_backtest as B
GRID = [round(.5 + .05 * i, 2) for i in range(13)]; TS = [2018, 2019, 2021, 2022, 2023, 2024, 2025]; res = {}


def ip(x):
    x = float(x or 0); return int(x) + (x - int(x)) * 10 / 3


def solve(s, target, b):
    lo, hi = -500.0, 500.0
    for _ in range(60):
        a = (lo + hi) / 2
        if np.clip(a + b * s, 0, None).sum() > target:
            hi = a
        else:
            lo = a
    return (lo + hi) / 2


for side, key, conv, name in (('bat', 'PA', float, 'hit'), ('pit', 'IP', ip, 'pit')):
    with contextlib.redirect_stdout(io.StringIO()):
        pt = B.pt_heldout(name)
    tab = {}
    for T in TS:
        st = B.fg('steamer', T, side); a_ = B.fg('actual', T, side)
        if not a_ or not st:
            continue
        ids = [p for p in pt[T] if p in st and st[p].get(key)]
        tab[T] = (np.array([pt[T][p] for p in ids]), np.array([float(st[p][key]) for p in ids]), np.array([conv((a_.get(p) or {}).get(key) or 0) for p in ids]))
    Ts = sorted(tab); R = np.zeros((len(GRID), len(Ts)))
    FLOOR = {'bat': 5.0, 'pit': 2.0}[side]
    print(f'\n== {side}: floor rule, Steamer at or under {FLOOR} keeps our model (the November file uses that floor as a placeholder; Ragans, Taillon)')
    for T in sorted(tab):
        o, s, y = tab[T]; f = s <= FLOOR
        print(f'  {T}: {int(f.sum())} of {len(s)} at the floor, ours {o[f].sum():.0f}, actual {y[f].sum():.0f}')
    for fl in (0.0, 1.01, FLOOR, 10.0):
        Rf = []
        for b in (.70, .75, .80, .85, .90, .95):
            per = []
            for T in Ts:
                o, s, y = tab[T]; f = s <= fl; a = solve(s[~f], o[~f].sum(), b); pr = o.copy(); pr[~f] = np.clip(a + b * s[~f], 0, None); per.append(math.sqrt(np.mean((pr - y) ** 2)))
            Rf.append(per)
        Rf = np.array(Rf); own = np.mean([math.sqrt(np.mean((tab[T][0] - tab[T][2]) ** 2)) for T in Ts])
        wins = int((Rf[int(Rf.mean(axis=1).argmin())] < np.array([math.sqrt(np.mean((tab[T][0] - tab[T][2]) ** 2)) for T in Ts])).sum())
        print(f'  floor {fl:5}: RMSE by b .70-.95 ' + ' '.join(f'{v:.2f}' for v in Rf.mean(axis=1)) + f'  best b {[.70, .75, .80, .85, .90, .95][int(Rf.mean(axis=1).argmin())]}; ours {own:.2f}; best beats ours {wins}/{len(Ts)}')
    for i, b in enumerate(GRID):
        for j, T in enumerate(Ts):
            o, s, y = tab[T]; a = solve(s, o.sum(), b); R[i, j] = math.sqrt(np.mean((np.clip(a + b * s, 0, None) - y) ** 2))
    print(f'\n== {side}: RMSE of playing time by b, seasons {Ts}')
    for i, b in enumerate(GRID):
        print(f'  b {b:.2f}: mean {R[i].mean():.2f}   ' + ' '.join(f'{v:.1f}' for v in R[i]))
    best = GRID[int(R.mean(axis=1).argmin())]; print(f'  best on the grid b {best}; per-season best ' + ' '.join(str(GRID[int(R[:, j].argmin())]) for j in range(len(Ts))))
    held, ours, flat, chosen = [], [], [], []
    for j, T in enumerate(Ts):
        tr = [k for k in range(len(Ts)) if k != j]; b = GRID[int(R[:, tr].mean(axis=1).argmin())]; chosen.append(b); o, s, y = tab[T]; held.append(R[GRID.index(b), j]); ours.append(math.sqrt(np.mean((o - y) ** 2))); k = o.sum() / s.sum(); flat.append(math.sqrt(np.mean((k * s - y) ** 2)))
    print(f'  held out: chosen {chosen}; RMSE calibrated {np.mean(held):.2f}, flat scale {np.mean(flat):.2f}, ours {np.mean(ours):.2f}; calibrated beats ours {sum(h < u for h, u in zip(held, ours))}/{len(Ts)}, beats flat {sum(h < u for h, u in zip(held, flat))}/{len(Ts)}')
    top = []
    for T in Ts:
        o, s, y = tab[T]; a = solve(s, o.sum(), best); q = s >= np.percentile(s, 97); top.append((np.clip(a + best * s, 0, None)[q].mean(), k_ := (o.sum() / s.sum()) * s[q].mean(), y[q].mean(), o[q].mean()))
    print('  top 3 percent by Steamer, mean PT: calibrated, flat, actual, ours: ' + ' | '.join(f'{a:.0f} {b:.0f} {c:.0f} {d:.0f}' for a, b, c, d in top))
    res[side] = dict(grid=GRID, rmse=R.tolist(), best=best, chosen=chosen, held=held, ours=ours, flat=flat)
json.dump(res, open(os.path.join(ROOT, 'data', '_war_honest', 'pt_calibration.json'), 'w'), indent=1)
