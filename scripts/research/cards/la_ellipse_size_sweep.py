"""Does the LA x spray ellipse tell hitters apart, and at what size?

For each hitter, draw the ellipse in season Y and ask whether it matches HIS OWN
ellipse in Y+1 better than other hitters' Y+1 ellipses (mean rank = AUC; .5 is no
information). IoU is measured inside the plotted area (spray +-50, LA -20 to 60),
with pull mirrored to positive. Independent seasons, full-season samples: hitters
with at least 250 BIP in both years, 2021-2025. Compared against the two points the
card can show without an ellipse: the center of the same dots, and the median of
all BIP (the purple marker). The card's 1.51 sigma is about 68% coverage.

    python3 scripts/research/cards/la_ellipse_size_sweep.py
Writes data/_la_ellipse_sweep.json.
"""
import gc
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
COVERAGE = [.10, .20, .30, .40, .50, .60, .68, .80, .90]
YEARS = [2021, 2022, 2023, 2024, 2025]
MIN_BIP = 250
AIR = {'fly_ball', 'line_drive', 'popup'}
HX, HY = 125.42, 198.27
GX, GY = np.meshgrid(np.arange(-49.5, 50), np.arange(-19.5, 60))


def season(year):
    d = pd.read_pickle(os.path.join(ROOT, 'data', f'_statcast{year}_cache.pkl'))
    d = d[d['type'] == 'X']
    d = d[~d.bb_type.astype('object').isin(['bunt']) & d.description.astype('object').ne('hit_into_play_bunt')]
    out = pd.DataFrame({'id': pd.to_numeric(d.batter, errors='coerce').to_numpy('float64', na_value=np.nan),
                        'stand': d.stand.astype('object').to_numpy(),
                        'ev': pd.to_numeric(d.launch_speed, errors='coerce').to_numpy('float64', na_value=np.nan),
                        'la': pd.to_numeric(d.launch_angle, errors='coerce').to_numpy('float64', na_value=np.nan),
                        'x': pd.to_numeric(d.hc_x, errors='coerce').to_numpy('float64', na_value=np.nan),
                        'y': pd.to_numeric(d.hc_y, errors='coerce').to_numpy('float64', na_value=np.nan),
                        'bb': d.bb_type.astype('object').to_numpy()})
    del d
    gc.collect()
    out = out.dropna(subset=['id', 'la', 'x', 'y'])
    out = out[HY - out.y > 0]
    ang = np.degrees(np.arctan2(out.x - HX, HY - out.y))
    out['a'] = np.where(out.stand == 'R', -ang, ang)
    out['la'] = out.la.clip(-20, 60)
    out['hard'] = out.ev >= 95   # every barrel is at least 98 mph, so barrels are inside this
    out['air'] = out.bb.isin(AIR)
    return out


def describe(g, which):
    q = {'air': g[g.hard & g.air], 'all_hard': g[g.hard], 'all_bip': g}[which]
    if len(q) < 6:
        return None
    X = q[['a', 'la']].to_numpy()
    return {'c': X.mean(0), 'inv': np.linalg.pinv(np.cov(X.T)), 'det': np.linalg.det(np.cov(X.T)),
            'med': np.array([g.a.median(), g.la.median()]), 'n': len(q), 'X': X}


def mask(e, cov):
    k2 = -2 * np.log(1 - cov)
    dx, dy = GX - e['c'][0], GY - e['c'][1]
    i = e['inv']
    return (i[0, 0] * dx * dx + 2 * i[0, 1] * dx * dy + i[1, 1] * dy * dy) <= k2


def rank_auc(sim):
    """sim[i, j]: similarity of hitter i in Y to hitter j in Y+1. Mean rank of own match."""
    n = len(sim)
    wins = [(np.sum(sim[i, np.arange(n) != i] < sim[i, i])
             + .5 * np.sum(sim[i, np.arange(n) != i] == sim[i, i])) / (n - 1) for i in range(n)]
    return float(np.mean(wins))


def main():
    frames = {y: season(y) for y in YEARS}
    res = {}
    for which in ('air', 'all_hard', 'all_bip'):
        res[which] = {}
        for y0, y1 in zip(YEARS, YEARS[1:]):
            d0, d1 = {}, {}
            for src, dst in ((frames[y0], d0), (frames[y1], d1)):
                for key, g in src.groupby(['id', 'stand'], sort=False):
                    if len(g) >= MIN_BIP:
                        e = describe(g, which)
                        if e:
                            dst[key] = e
            keys = sorted(set(d0) & set(d1))
            row = {'n': len(keys), 'dots': float(np.median([d0[k]['n'] for k in keys]))}
            A = np.array([d0[k]['c'] for k in keys])
            B = np.array([d1[k]['c'] for k in keys])
            row['center_auc'] = rank_auc(-np.linalg.norm(A[:, None] - B[None], axis=2))
            A = np.array([d0[k]['med'] for k in keys])
            B = np.array([d1[k]['med'] for k in keys])
            row['purple_auc'] = rank_auc(-np.linalg.norm(A[:, None] - B[None], axis=2))
            for cov in COVERAGE:
                M0 = np.array([mask(d0[k], cov).ravel() for k in keys], dtype=np.float32)
                M1 = np.array([mask(d1[k], cov).ravel() for k in keys], dtype=np.float32)
                inter = M0 @ M1.T
                union = M0.sum(1)[:, None] + M1.sum(1)[None] - inter
                iou = inter / np.maximum(union, 1)
                n = len(keys)
                own = float(np.mean(np.diag(iou)))
                other = float((iou.sum() - np.trace(iou)) / (n * n - n))
                row[f'{cov:.2f}'] = {'auc': rank_auc(iou), 'own_iou': own, 'other_iou': other,
                                     'plot_pct': float(M0.mean() * 100),
                                     'radius_deg': float(np.mean([np.sqrt(M0[i].sum() / np.pi) for i in range(n)]))}
            res[which][f'{y0}-{y1}'] = row
            print(which, y0, y1, row['n'], flush=True)
    tmp = os.path.join(ROOT, 'data', '_la_ellipse_sweep.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(res, f, indent=1)
    os.replace(tmp, os.path.join(ROOT, 'data', '_la_ellipse_sweep.json'))
    for which, rows in res.items():
        print(f'\n{which}: pairs {list(rows)} median dots {[r["dots"] for r in rows.values()]}')
        print(f'  purple dot AUC {[round(r["purple_auc"], 3) for r in rows.values()]}')
        print(f'  center AUC     {[round(r["center_auc"], 3) for r in rows.values()]}')
        print('  cover  plot%  radius  own_iou other_iou   AUC by pair                  mean')
        for cov in COVERAGE:
            k = f'{cov:.2f}'
            au = [r[k]['auc'] for r in rows.values()]
            print(f"  {cov:.2f}  {np.mean([r[k]['plot_pct'] for r in rows.values()]):5.1f}  "
                  f"{np.mean([r[k]['radius_deg'] for r in rows.values()]):5.1f}  "
                  f"{np.mean([r[k]['own_iou'] for r in rows.values()]):.3f}   "
                  f"{np.mean([r[k]['other_iou'] for r in rows.values()]):.3f}    "
                  f"{[round(x, 3) for x in au]}  {np.mean(au):.3f}")


if __name__ == '__main__':
    main()
