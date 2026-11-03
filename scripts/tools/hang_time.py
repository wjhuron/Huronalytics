#!/usr/bin/env python3
"""Hang time (contact to landing) from launch angle, exit velo and distance.

The Sheets carry no hang time. Savant's range plays carry the opportunity
time (pitch release to landing), so on the plays joined to the feed by
`scripts/builders/range_plays_pull.py`:

    hang = opportunity_time - 37.6 / pitch_mph

(37.6 / velo reproduces pitch flight to about 3 ms over 69-100 mph). The
model is k-nearest neighbours on (LA, EV, distance), each scaled by its SD.
k is the one knob: it is chosen by 5-fold cross-validated mean absolute
error over a grid, grouped by batter so no batter is in both folds, and the
sweep must bracket an interior optimum. `--exclude` holds a batter out of
the training set so his own balls are true out-of-sample predictions.

Usage (from the repo root):
    python3 scripts/tools/hang_time.py --season 2024 2025 2026 --exclude 695578
"""
import argparse
import json
import os

import numpy as np
from scipy.spatial import cKDTree

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
K_GRID = [1, 2, 3, 5, 8, 12, 18, 25, 35, 50, 70, 100, 140]
FEATS = ('la', 'ev', 'total_distance')


def load(seasons, exclude=None):
    plays = []
    for season in ([seasons] if isinstance(seasons, int) else seasons):
        with open(os.path.join(REPO, 'data', f'_range_plays_{season}.json')) as f:
            plays += json.load(f)
    seen, X, y, g = set(), [], [], []
    for r in plays:
        if r['play_id'] in seen or r.get('batter_id') == exclude:
            continue
        vals = [r.get(k) for k in FEATS]
        if any(v is None for v in vals) or not r.get('pitch_mph'):
            continue
        seen.add(r['play_id'])
        X.append(vals)
        y.append(float(r['opportunity_time']) - 37.6 / r['pitch_mph'])
        g.append(r['batter_id'])
    return np.array(X, float), np.array(y), np.array(g)


class KNN:
    def __init__(self, X, y, k):
        self.mu, self.sd = X.mean(0), X.std(0)
        self.tree = cKDTree((X - self.mu) / self.sd)
        self.y, self.k = y, k

    def predict(self, X):
        _d, i = self.tree.query((np.asarray(X, float) - self.mu) / self.sd, k=self.k)
        return self.y[i].mean(1) if self.k > 1 else self.y[i]


def sweep(X, y, groups, folds=5, seed=0):
    rng = np.random.default_rng(seed)
    ug = np.unique(groups)
    fold_of = dict(zip(ug, rng.integers(0, folds, len(ug))))
    f = np.array([fold_of[b] for b in groups])
    out = []
    for k in K_GRID:
        err = np.empty(len(y))
        for j in range(folds):
            tr, te = f != j, f == j
            err[te] = np.abs(KNN(X[tr], y[tr], k).predict(X[te]) - y[te])
        out.append((k, err.mean()))
    return out


def fit(seasons, exclude=None):
    """Return (model, sweep, chosen k, 'interior' | 'GRID EDGE')."""
    X, y, g = load(seasons, exclude)
    sw = sweep(X, y, g)
    i = int(np.argmin([e for _k, e in sw]))
    where = 'interior' if 0 < i < len(sw) - 1 else 'GRID EDGE'
    return KNN(X, y, sw[i][0]), sw, sw[i][0], where


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--season', type=int, nargs='+', required=True)
    ap.add_argument('--exclude', type=int, default=None, help='batter id held out')
    args = ap.parse_args()
    X, y, g = load(args.season, args.exclude)
    print(f'{len(y)} plays, {len(np.unique(g))} batters; hang mean {y.mean():.2f} s, sd {y.std():.2f}')
    _m, sw, k, where = fit(args.season, args.exclude)
    for kk, e in sw:
        print(f'  k={kk:4d}  MAE {e:.4f} s{"   <- best" if kk == k else ""}')
    print(f'chosen k={k} ({where})')


if __name__ == '__main__':
    main()
