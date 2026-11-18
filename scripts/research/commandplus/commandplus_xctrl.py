#!/usr/bin/env python3
"""commandplus_xctrl.py — does an xCTRL-style scorer beat shipped Command+?

xCTRL (Ludwig, Brill, Wyner, arXiv 2508.19184) infers latent targets with a
Gaussian mixture per (pitcher, batter hand, pitch type): K from 1 to 6 chosen by
VALIDATION likelihood, 250-pitch minimum, score = posterior-weighted distance to
the component means, with bootstrap intervals. It reports year-to-year r .65.

Command+ dropped its mixture on 2026-08-12 (K=1 won 22 of 22). That ladder used
count-group cells of 20+ pitches and picked K by BIC, which is not xCTRL's design.
This runs xCTRL's own design through the SAME harness and objectives
(commandplus_ladder_multiseason.py: common pitcher pool, per-season replicates):

  CELLMEAN   (type, batter hand, count group) cells, one target   (shipped rule)
  PTB1       (type, batter hand) cells, one target                (xCTRL's cell, no mixture)
  XCTRL      (type, batter hand) cells; 250+ pitches (125+ in a half): K 1..6 by
             3-fold held-out likelihood, posterior-weighted distance; thinner
             cells take one target
  XCTRLMIN   same mixture, distance to the NEAREST target (isolates the weighting)

Objectives: split-half reliability, year-to-year persistence, walk rate same
season and next season. Reliability and persistence rise under any pooling, so
the walk-rate columns are the external check. Also: bootstrap interval width of a
pitcher's season score (resampled pitches), the part of xCTRL no test can reject.

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/commandplus/commandplus_xctrl.py
"""
import gc
import json
import math
import os
import sys
import time
import warnings
from collections import defaultdict
from multiprocessing import Pool

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import commandplus_ladder_multiseason as L  # noqa: E402
from pipeline.commandplus import MIN_CELL  # noqa: E402

OUT = os.path.join(ROOT, 'data', '_commandplus_xctrl.json')
SCORERS = ['CELLMEAN', 'PTB1', 'XCTRL', 'XCTRLMIN']
KMAX = 6
MIX_MIN_FULL, MIX_MIN_HALF = 250, 125
BOOT = 40
BOOT_PITCHERS = 60


def fit_mix(X):
    """K by 3-fold held-out log-likelihood; returns the fitted mixture (or None for K=1)."""
    from sklearn.mixture import GaussianMixture
    n = len(X)
    rng = np.random.default_rng(0)
    fold = rng.permutation(n) % 3
    best_k, best_ll = 1, -np.inf
    for k in range(1, min(KMAX, n // 40) + 1):
        ll = 0.0
        try:
            for f in range(3):
                g = GaussianMixture(k, covariance_type='full', reg_covar=1e-3, random_state=0).fit(X[fold != f])
                ll += g.score_samples(X[fold == f]).sum()
        except ValueError:
            continue
        if ll > best_ll:
            best_k, best_ll = k, ll
    if best_k == 1:
        return None, 1
    return GaussianMixture(best_k, covariance_type='full', reg_covar=1e-3, random_state=0).fit(X), best_k


def score(pitches, mode, mix_min):
    """pitches = [(pt, bats, cgroup, x_in, z_in, ...)] -> (mean miss, n, cells with K > 1)."""
    cells = defaultdict(list)
    for p in pitches:
        key = (p[0], p[1], p[2]) if mode == 'CELLMEAN' else (p[0], p[1])
        cells[key].append((p[3], p[4]))
    tot, n_tot, nmix = 0.0, 0, 0
    for pts in cells.values():
        if len(pts) < MIN_CELL:
            continue
        X = np.asarray(pts, dtype=float)
        g = None
        if mode in ('XCTRL', 'XCTRLMIN') and len(X) >= mix_min:
            g, k = fit_mix(X)
        if g is None:
            d = np.hypot(*(X - X.mean(0)).T)
        else:
            nmix += 1
            D = np.sqrt(((X[:, None, :] - g.means_[None, :, :]) ** 2).sum(2))
            d = (g.predict_proba(X) * D).sum(1) if mode == 'XCTRL' else D.min(1)
        tot += float(d.sum())
        n_tot += len(X)
    return (tot / n_tot, n_tot, nmix) if n_tot else (None, 0, 0)


def job(arg):
    warnings.filterwarnings('ignore')
    key, pitches = arg
    out = {}
    for mode in SCORERS:
        full, nf, nmix = score(pitches, mode, MIX_MIN_FULL)
        if full is not None and nf >= L.MIN_FULL:
            out[(mode, 'full')] = full
            out[(mode, 'nmix')] = nmix
        for h in (0, 1):
            m, nh, _ = score([p for p in pitches if p[5] == h], mode, MIX_MIN_HALF)
            if m is not None and nh >= L.MIN_HALF:
                out[(mode, f'h{h}')] = m
    return key, out


def boot_job(arg):
    warnings.filterwarnings('ignore')
    key, pitches = arg
    rng = np.random.default_rng(abs(hash(key)) % (2 ** 32))
    out = {}
    for mode in ('CELLMEAN', 'XCTRL'):
        vals = []
        for _ in range(BOOT):
            idx = rng.integers(0, len(pitches), len(pitches))
            m, _n, _k = score([pitches[i] for i in idx], mode, MIX_MIN_FULL)
            if m is not None:
                vals.append(m)
        out[mode] = float(np.std(vals)) if len(vals) > 5 else None
    return key, len(pitches), out


def main():
    full = {m: {} for m in SCORERS}
    half = {m: {} for m in SCORERS}
    bbr, mixshare, boot = {}, {}, {}
    _cache = OUT.replace('.json', '_scores.pkl')
    if os.path.exists(_cache):
        import pickle as _pk
        full, half, bbr, mixshare, boot = _pk.load(open(_cache, 'rb'))
        print('scores read from the cache', flush=True)
    for y in ([] if os.path.exists(_cache) else L.SEASONS):
        t0 = time.time()
        by_p, bb_rate, _zone = L.load_season(y)
        bbr[y] = bb_rate
        jobs = [(k, v) for k, v in by_p.items() if len(v) >= L.MIN_FULL]
        with Pool() as pool:
            res = pool.map(job, jobs, chunksize=4)
        c_full = set.intersection(*[{k for k, o in res if (m, 'full') in o} for m in SCORERS])
        c_half = set.intersection(*[{k for k, o in res if (m, 'h0') in o and (m, 'h1') in o} for m in SCORERS])
        for m in SCORERS:
            full[m][y] = {k: o[(m, 'full')] for k, o in res if k in c_full}
            half[m][y] = {k: (o[(m, 'h0')], o[(m, 'h1')]) for k, o in res if k in c_half}
        mixshare[y] = float(np.mean([o[('XCTRL', 'nmix')] > 0 for k, o in res if k in c_full]))
        if y == 2025:
            rng = np.random.default_rng(0)
            pick = [jobs[i] for i in rng.choice(len(jobs), min(BOOT_PITCHERS, len(jobs)), replace=False)]
            with Pool() as pool:
                boot = {k: (n, o) for k, n, o in pool.map(boot_job, pick, chunksize=2)}
        print(f'{y}: {len(jobs)} candidates, common pool {len(c_full)} full / {len(c_half)} half, '
              f'{mixshare[y]:.0%} of pitchers get a mixture in some cell ({time.time() - t0:.0f}s)', flush=True)
        del by_p
        gc.collect()
    import pickle
    pickle.dump((full, half, bbr, mixshare, boot), open(OUT.replace('.json', '_scores.pkl'), 'wb'))
    out = {'mix_share': mixshare}
    pairs = list(zip(L.SEASONS, L.SEASONS[1:]))

    def table(title, fn, cols):
        print(f'\n{title}')
        lab = lambda c: f'{c[0] % 100}->{c[1] % 100}' if isinstance(c, tuple) else str(c)
        print(f'{"scorer":<10}' + ''.join(f'{lab(c):>8}' for c in cols) + f'{"mean":>8}')
        for m in SCORERS:
            rs = [fn(m, c) for c in cols]
            ok = [r for r in rs if r is not None]
            out[f'{title}:{m}'] = {'by': rs, 'mean': (sum(ok) / len(ok) if ok else None)}
            print(f'{m:<10}' + ''.join(L.fmt(r) for r in rs) + L.fmt(sum(ok) / len(ok) if ok else None))

    table('SPLIT-HALF RELIABILITY',
          lambda m, y: L.pearson(*L.paired({k: v[0] for k, v in half[m][y].items()},
                                           {k: v[1] for k, v in half[m][y].items()})[:2]), L.SEASONS)
    table('PERSISTENCE (year N -> N+1)', lambda m, ab: L.pearson(*L.paired(full[m][ab[0]], full[m][ab[1]])[:2]), pairs)
    table('WALK RATE, SAME SEASON', lambda m, y: L.pearson(*L.paired(full[m][y], bbr[y])[:2]), L.SEASONS)
    table('WALK RATE, NEXT SEASON', lambda m, ab: L.pearson(*L.paired(full[m][ab[0]], bbr[ab[1]])[:2]), pairs)
    if boot:
        sd_between = {m: float(np.std(list(full[m][2025].values()))) for m in ('CELLMEAN', 'XCTRL')}
        print('\nBOOTSTRAP SE OF A SEASON SCORE (2025, resampled pitches), inches and share of the between-pitcher SD')
        for lo, hi in ((300, 600), (600, 1200), (1200, 99999)):
            for m in ('CELLMEAN', 'XCTRL'):
                v = [o[m] for n, o in boot.values() if lo <= n < hi and o[m] is not None]
                if v:
                    out[f'boot:{m}:{lo}'] = {'n': len(v), 'se': float(np.median(v)), 'sd_between': sd_between[m]}
                    print(f'  {lo:>5}-{hi:<6} pitches  {m:<9} n {len(v):>3}  median SE {np.median(v):.3f} in '
                          f'({np.median(v) / sd_between[m]:.2f} of the between-pitcher SD {sd_between[m]:.3f})')
    json.dump(out, open(OUT, 'w'), indent=1, default=str)


if __name__ == '__main__':
    main()
