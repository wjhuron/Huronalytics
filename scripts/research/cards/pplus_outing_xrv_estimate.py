"""Should the daily card's Pitching+ tile use the same-day xRV estimate?

The outing grade (cards/pitcher.py, _outing_pitching_plus) takes xRV/100
from the sheet's RunExp and xwOBA. Before the morning backfill both are
blank, the slot scores league-average, and the card logs a warning
("drift ~0.5 pts, p95 1.5"). The social table already fills the two
columns from league tables (_xrv_fill_estimates). This script measures
the tile three ways on every 2026 MLB outing at or above the render floor
in the second half of the season, with the estimate tables fit on the
first half only:
    none   RunExp and xwOBA blanked on every pitch (the pre-backfill tile)
    est    blanked, then filled by _xrv_fill_estimates
    true   the sheet supplement (what the next-day rerun prints)
Reported against `true`: mean and p95 |grade gap| in points, and the share
of outings whose ROUNDED grade differs (the tile prints an integer).
Herz 2026-09-21 is scored the same three ways from the sheet rows saved by
the session that found the gap, when that file exists.

Run from the repo root:
    PYTHONHASHSEED=0 python3 scripts/research/cards/pplus_outing_xrv_estimate.py
"""
import json
import os
import sys
from collections import defaultdict

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, ROOT)
import cards.pitcher as cp  # noqa: E402

HERZ = os.environ.get('HERZ_ROWS', '')


def blank(ps):
    out = []
    for p in ps:
        q = dict(p)
        q['RunExp'] = None
        if q.get('Description') == 'In Play':
            q['xwOBA'] = None
        out.append(q)
    return out


def grade(ps, pool):
    return cp._outing_pitching_plus(ps, pool)


def main():
    mlb = cp._load_mlb_pickle()
    pool = cp._build_outing_pool(mlb)
    print(f"pool: {len(pool['pool'])} outings; xrv100 mu {pool['params']['xrv100'][0]:.3f} "
          f"sd {pool['params']['xrv100'][1]:.3f}; composite sd {pool['sd']:.4f}")
    dates = sorted(set(str(p.get('Game Date')) for p in mlb))
    mid = dates[len(dates) // 2]
    first = [p for p in mlb if str(p.get('Game Date')) < mid]
    # Estimate tables from the first half only.
    cp._XRV_EST_CACHE = None
    _orig = cp._load_mlb_pickle
    cp._load_mlb_pickle = lambda: first
    cp._xrv_estimate_tables()
    cp._load_mlb_pickle = _orig
    outings = defaultdict(list)
    for p in mlb:
        if str(p.get('Game Date')) >= mid:
            outings[(p.get('Pitcher'), str(p.get('Game Date')))].append(p)
    rows = []
    for key, ps in outings.items():
        if len(ps) < cp.PP_OUTING_MIN_N:
            continue
        t = grade(ps, pool)[0]
        b = blank(ps)
        n_ = grade(b, pool)[0]
        f, nf = cp._xrv_fill_estimates(b)
        e = grade(f, pool)[0]
        # unrounded, for the continuous gap
        ct = cp._outing_raw(cp._outing_components(ps), pool['params'])
        cn = cp._outing_raw(cp._outing_components(b), pool['params'])
        ce = cp._outing_raw(cp._outing_components(f), pool['params'])
        s = 10.0 / pool['sd']
        rows.append((len(ps), t, n_, e, (cn - ct) * s, (ce - ct) * s))
    a = np.array([(r[4], r[5]) for r in rows])
    R = np.array([(r[1], r[2], r[3]) for r in rows], dtype=float)
    print(f"\n{len(rows)} second-half outings >= {cp.PP_OUTING_MIN_N} pitches, split at {mid}")
    for lab, col, rc in (('none (pre-backfill tile)', 0, 1), ('estimate', 1, 2)):
        g = np.abs(a[:, col])
        flip = np.mean(R[:, rc] != R[:, 0])
        big = np.mean(np.abs(R[:, rc] - R[:, 0]) >= 2)
        print(f"  {lab:<26} |gap| mean {g.mean():.3f}  p95 {np.percentile(g, 95):.3f}  "
              f"max {g.max():.2f}  rounded grade differs {flip:.1%}  by 2+ {big:.1%}")
    # by outing length
    for lo, hi in ((10, 30), (30, 60), (60, 200)):
        m = np.array([(lo <= r[0] < hi) for r in rows])
        if m.sum():
            print(f"  {lo:>3}-{hi:<3} pitches n {m.sum():>5}: none mean {np.abs(a[m, 0]).mean():.3f} "
                  f"est mean {np.abs(a[m, 1]).mean():.3f}; rounded differs none "
                  f"{np.mean(R[m, 1] != R[m, 0]):.1%} est {np.mean(R[m, 2] != R[m, 0]):.1%}")
    if HERZ and os.path.exists(HERZ):
        herz = json.load(open(HERZ))
        # atoms: the sheet cells are blank on a fresh game; the tile resolves
        # them through the scratch context. Stuff/Loc are identical across
        # the three scenarios, so only the xRV term moves the grade.
        b = blank(herz)
        f, nf = cp._xrv_fill_estimates(b)
        cn = cp._outing_components(b); ce = cp._outing_components(f)
        print(f"\nHerz 2026-09-21: {len(herz)} pitches, xrv100 none {cn['xrv100']} est {ce['xrv100']:.3f}; "
              f"tile shift from the estimate: {(cp._outing_raw(ce, pool['params']) - cp._outing_raw(cn, pool['params'])) * 10 / pool['sd']:+.2f} pts")


if __name__ == '__main__':
    main()
