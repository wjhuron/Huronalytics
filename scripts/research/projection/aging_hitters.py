"""aging_hitters.py: the hitter aging curve for wOBA, delta method, 2000-2026.

wOBA per player-season from MLB season lines (fixed 2026 Guts weights; each season is then
expressed relative to its own PA-weighted league mean, so the weight drift cancels). Pairs of
consecutive seasons for the same hitter give delta = rel_{Y+1} - rel_Y at age a = age in Y+1.
Weight = harmonic mean of the two PAs.

Two estimators per age:
  raw     weighted mean delta
  shrunk  each season shrunk toward the mean of hitters at that PA level before differencing
          (N0 PA toward 0 relative), which removes the regression-to-the-mean pull a short
          season has on its partner. N0 is swept.

Out-of-sample test (the curve is a forecasting device): fit on one era, score on the other,
both directions (2000-2013 pairs / 2014-2026 pairs). Objective: harmonic-weighted MSE of the
held-out deltas, against zero aging and against the v1 linear rule (+.002 below 29,
-.0015 above). Curve smoothing: per-age means pooled at the tails (<= 22, >= 38) and then a
centered moving average of width W ages (W swept, 1 = none).

Usage: python3 scripts/research/projection/aging_hitters.py
Output: console + data/_proj/_aging_hitters.json
"""
import json
import os
from collections import defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
P = os.path.join(ROOT, 'data', '_proj')
W = {'BB': 0.698, 'HBP': 0.729, '1B': 0.89, '2B': 1.261, '3B': 1.596, 'HR': 2.049}  # 2026 Guts
YEARS = range(2000, 2027)
MIN_PA = 50
AGE_LO, AGE_HI = 22, 38
ERA_SPLIT = 2014          # pairs whose second season is < ERA_SPLIT vs >=
N0_GRID = [0, 100, 200, 300, 450, 700, 1000]
W_GRID = [1, 3, 5, 7]


def season(y):
    rows = json.load(open(os.path.join(P, f'lines_hitting_{y}.json')))
    out = {}
    for r in rows:
        if r.get('pos') == 'P' or r.get('age') is None:
            continue
        ab, bb, ibb, hbp, sf = (int(r.get(k) or 0) for k in ('atBats', 'baseOnBalls', 'intentionalWalks', 'hitByPitch', 'sacFlies'))
        h, d2, d3, hr = (int(r.get(k) or 0) for k in ('hits', 'doubles', 'triples', 'homeRuns'))
        den = ab + bb - ibb + sf + hbp
        if den <= 0:
            continue
        num = W['BB'] * (bb - ibb) + W['HBP'] * hbp + W['1B'] * (h - d2 - d3 - hr) + W['2B'] * d2 + W['3B'] * d3 + W['HR'] * hr
        out[r['id']] = (int(r.get('plateAppearances') or den), num / den, r['age'], den)
    lg = sum(v[1] * v[3] for v in out.values()) / sum(v[3] for v in out.values())
    return {k: (pa, w - lg, age) for k, (pa, w, age, _) in out.items()}


def pairs():
    S = {y: season(y) for y in YEARS}
    out = []
    for y in list(YEARS)[:-1]:
        a, b = S[y], S[y + 1]
        for pid in a.keys() & b.keys():
            pa1, r1, _ = a[pid]
            pa2, r2, age2 = b[pid]
            if pa1 < MIN_PA or pa2 < MIN_PA:
                continue
            out.append((y + 1, min(max(age2, AGE_LO), AGE_HI), pa1, r1, pa2, r2))
    return np.array(out, float)


def curve(Pm, n0, width):
    """per-age mean delta, shrunk at n0, smoothed by a centered moving average of `width` ages."""
    pa1, r1, pa2, r2 = Pm[:, 2], Pm[:, 3], Pm[:, 4], Pm[:, 5]
    d = r2 * pa2 / (pa2 + n0) - r1 * pa1 / (pa1 + n0)
    w = 2 * pa1 * pa2 / (pa1 + pa2)
    ages = np.arange(AGE_LO, AGE_HI + 1)
    m = np.array([np.average(d[Pm[:, 1] == a], weights=w[Pm[:, 1] == a]) if (Pm[:, 1] == a).any() else 0.0 for a in ages])
    if width > 1:
        h = width // 2
        m = np.array([m[max(0, i - h):i + h + 1].mean() for i in range(len(m))])
    return dict(zip(ages.tolist(), m.tolist()))


def score(Pm, c, n0):
    """weighted MSE of held-out deltas (measured on the same n0 scale the curve was fit on)."""
    pa1, r1, pa2, r2 = Pm[:, 2], Pm[:, 3], Pm[:, 4], Pm[:, 5]
    d = r2 * pa2 / (pa2 + n0) - r1 * pa1 / (pa1 + n0)
    w = 2 * pa1 * pa2 / (pa1 + pa2)
    pred = np.array([c[int(a)] for a in Pm[:, 1]])
    return float((w * (d - pred) ** 2).sum() / w.sum())


def linear(age):
    return 0.002 if age < 29 else -0.0015 if age >= 30 else 0.0


def main():
    Pm = pairs()
    early, late = Pm[Pm[:, 0] < ERA_SPLIT], Pm[Pm[:, 0] >= ERA_SPLIT]
    print(f'pairs: {len(Pm)} ({len(early)} before {ERA_SPLIT}, {len(late)} after)')
    res = []
    for n0 in N0_GRID:
        for width in W_GRID:
            row = {'n0': n0, 'W': width}
            for name, fit, test in (('e->l', early, late), ('l->e', late, early)):
                c = curve(fit, n0, width)
                row[name] = score(test, c, n0)
                row[name + '_zero'] = score(test, {a: 0.0 for a in c}, n0)
                row[name + '_lin'] = score(test, {a: linear(a) for a in c}, n0)
            res.append(row)
    # n0 changes the target scale, so compare curves only WITHIN an n0 against that n0's baselines
    print(f'{"n0":>5} {"W":>2} | {"e->l":>9} {"zero":>9} {"lin":>9} | {"l->e":>9} {"zero":>9} {"lin":>9}   (MSE x1e4)')
    for r in res:
        print(f'{r["n0"]:>5} {r["W"]:>2} | ' + ' | '.join(
            f'{r[k]*1e4:9.3f} {r[k+"_zero"]*1e4:9.3f} {r[k+"_lin"]*1e4:9.3f}' for k in ('e->l', 'l->e')))
    full = {n0: curve(Pm, n0, 3) for n0 in (0, 450)}
    print('\nfull-sample curve (W 3), delta per age, wOBA points x1000:')
    for a in range(AGE_LO, AGE_HI + 1):
        print(f'  {a}: raw {full[0][a]*1e3:+6.1f}   shrunk450 {full[450][a]*1e3:+6.1f}')
    out = {'grid': res, 'curve_raw_W3': full[0], 'curve_n450_W3': full[450], 'n_pairs': len(Pm)}
    tmp = os.path.join(P, '_aging_hitters.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(out, f, indent=1)
    os.replace(tmp, os.path.join(P, '_aging_hitters.json'))


if __name__ == '__main__':
    main()
