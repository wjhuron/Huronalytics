#!/usr/bin/env python3
"""bubble_overlap.py — how often do the social card's usage-sized centroid
discs collide, under each sizing rule?

The daily and season social cards draw one disc per pitch type at its mean
movement, with marker area = K x the type's share of the outing (since
2026-09-16). A bigger K buys more size contrast between a 30% pitch and a
10% pitch; it also makes more discs touch. The two goods have no stated
exchange rate, so K is a display convention. This script is the diagnostic
that informs it: for every 2026 MLB outing (pitcher x gamePk) with two or
more pitch types that carry movement, it places the discs in the card's own
axes geometry and counts the outings where

  touch    — any two discs overlap (distance < r1 + r2),
  hidden   — any disc centre lies inside another disc,
  enclosed — any disc lies entirely inside another,

for the retired fixed 320 pt^2 disc, the rejected per-card max anchor, and
three share scales. It also reports how often the cap and the floor bind.

Result 2026-09-16 (18,876 outings): touch rises monotonically with K, so no
interior optimum exists. K=1667 (30% -> 500 pt^2) equals the fixed disc's
touch rate (4.9% vs 4.7%; 7.9% vs 9.3% on starters); K=2333 costs two more
points. Wally chose 1667 as the cleaner card.

Geometry: 8x10 in figure, movement axes 0.872 x 0.436 of it, +/-25 in on
both axes (cards/pitcher.py render_social_card). Cap 1200, floor 90.

Usage: python3 scripts/research/cards/bubble_overlap.py [out.json]
       (default out: data/_bubble_overlap.json)
"""
import json
import math
import os
import pickle
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

PT_X = (0.872 * 8 * 72) / 50.0     # pt per inch of horizontal break
PT_Y = (0.436 * 10 * 72) / 50.0    # pt per inch of induced vertical break
S_MIN, S_CAP = 90.0, 1200.0
SHARE_KS = (1667.0, 2333.0, 3000.0)


def sf(v):
    try:
        return None if v in (None, '') else float(v)
    except (TypeError, ValueError):
        return None


def load_outings():
    with open(os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl'), 'rb') as f:
        rows = pickle.load(f)
    by_outing = defaultdict(lambda: defaultdict(list))
    npitch = defaultdict(int)
    for p in rows:
        if p.get('_source') != 'MLB' or not p.get('Pitch Type'):
            continue
        key = (p.get('Pitcher'), str(p.get('PitchID', '')).split('_')[0])
        npitch[key] += 1
        hb, iv = sf(p.get('HorzBrk')), sf(p.get('IndVertBrk'))
        if hb is not None and iv is not None:
            by_outing[key][p['Pitch Type']].append((hb, iv))
    outings = []
    for key, by in by_outing.items():
        if len(by) < 2:
            continue
        cents = [(sum(q[0] for q in pl) / len(pl), sum(q[1] for q in pl) / len(pl), len(pl))
                 for pl in by.values()]
        outings.append((key, cents, npitch[key]))
    return outings


def share_rule(K):
    return lambda n, nmax, ntot: min(S_CAP, max(S_MIN, K * n / ntot))


RULES = {'fixed 320 (retired)': lambda n, nmax, ntot: 320.0,
         'max-anchored 700 (rejected)': lambda n, nmax, ntot: max(S_MIN, 700.0 * n / nmax)}
for _K in SHARE_KS:
    RULES[f'share K={_K:.0f} (30%->{0.3 * _K:.0f})'] = share_rule(_K)


def diag(rule, subset):
    touch = hidden = enclosed = 0
    for key, cents, npt in subset:
        nmax = max(c[2] for c in cents)
        ntot = sum(c[2] for c in cents)
        rs = [0.5 * math.sqrt(rule(c[2], nmax, ntot)) for c in cents]
        t = h = e = False
        for i in range(len(cents)):
            for j in range(i + 1, len(cents)):
                dist = math.hypot((cents[i][0] - cents[j][0]) * PT_X,
                                  (cents[i][1] - cents[j][1]) * PT_Y)
                rb, rsm = max(rs[i], rs[j]), min(rs[i], rs[j])
                t |= dist < rs[i] + rs[j]
                h |= dist < rb
                e |= dist + rsm < rb
        touch += t
        hidden += h
        enclosed += e
    n = len(subset)
    return {'outings': n, 'touch%': 100.0 * touch / n, 'hidden%': 100.0 * hidden / n,
            'enclosed%': 100.0 * enclosed / n}


def bind_rates(K, subset):
    cap = floor = tot = 0
    for key, cents, npt in subset:
        ntot = sum(c[2] for c in cents)
        for c in cents:
            tot += 1
            s = K * c[2] / ntot
            cap += s > S_CAP
            floor += s < S_MIN
    return 100.0 * cap / tot, 100.0 * floor / tot


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'data', '_bubble_overlap.json')
    outings = load_outings()
    subsets = {'all outings (>=2 types)': outings,
               'starters (>=60 pitches)': [o for o in outings if o[2] >= 60],
               'relievers (<30 pitches)': [o for o in outings if o[2] < 30]}
    res = {}
    for sname, sub in subsets.items():
        res[sname] = {}
        print(f"\n== {sname}: {len(sub)} outings")
        print(f"{'rule':30s} {'touch%':>7s} {'hidden%':>8s} {'encl%':>7s}")
        for rname, rule in RULES.items():
            r = diag(rule, sub)
            res[sname][rname] = r
            print(f"{rname:30s} {r['touch%']:7.1f} {r['hidden%']:8.1f} {r['enclosed%']:7.1f}")
        for K in SHARE_KS:
            c, f = bind_rates(K, sub)
            res[sname][f'bind K={K:.0f}'] = {'cap%': c, 'floor%': f}
            print(f"  K={K:.0f}: cap binds on {c:.1f}% of types, floor on {f:.1f}%")
    with open(out_path, 'w') as f:
        json.dump(res, f, indent=1)
    print(f"\nwrote {out_path}")


if __name__ == '__main__':
    main()
