"""stuff_seed_ensemble.py: does averaging Stuff+ models over fit seeds help, using the gate's own aggregates?

Production scores each pitcher with ONE fold model. xgboost subsampling makes the fit seed matter: the gate's seed SD of
d_nxt is about .005 per pair. An average over K seeds removes that noise at the cost of K x the training time. Reads the
cached aggregates (no refit): pitcher-level s and s_r averaged over seeds, joined to Y+1 target by nxt_table's own rule,
and per-type unit validity including sweepers. Pairs 2021..2025.

Usage: python3 scripts/research/stuff/stuff_seed_ensemble.py [NAME ...]    (default SHIPPED)
"""
import glob
import itertools
import os
import pickle
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
GATE = os.path.join(ROOT, 'data', '_gate_v2')
MIN_NXT, MIN_NXT_U = None, None
sys.path.insert(0, HERE)
import stuff_gate_v2 as G  # noqa: E402


def r(a, b):
    return float(np.corrcoef(a, b)[0, 1])


def main():
    for name in (sys.argv[1:] or ['SHIPPED']):
        print(f'\n===== {name}')
        allk = {}
        for Y in range(2021, 2026):
            files = sorted(glob.glob(os.path.join(GATE, f'agg_{name}_{Y}_s*.pkl')))
            A = [pickle.load(open(f, 'rb')) for f in files]
            seeds = len(A)
            tabs = [G.nxt_table(a) for a in A]
            idx = tabs[0].index
            assert all(t.index.equals(idx) for t in tabs)
            t = tabs[0]['t'].values
            S = np.column_stack([x['s'].values for x in tabs]); SR = np.column_stack([x['s_r'].values for x in tabs])
            rows = {}
            for K in range(1, seeds + 1):
                combos = list(itertools.combinations(range(seeds), K))
                rows[K] = (np.mean([r(S[:, list(c)].mean(1), t) for c in combos]), np.mean([r(SR[:, list(c)].mean(1), t) for c in combos]))
                allk.setdefault(K, []).append(rows[K])
            sd = np.std([r(S[:, j], t) for j in range(seeds)])
            # unit level by type
            ju = []
            for a in A:
                j = a['uy'].join(a['uy1'], lsuffix='_y', rsuffix='_y1', how='inner')
                ju.append(j[(j['n_y'] >= G.MIN_NXT_U) & (j['n_y1'] >= G.MIN_NXT_U)])
            print(f' {Y}: n {len(t)} seeds {seeds} single seed SD {sd:.4f} ' + ' '.join(f'K{K} raw {rows[K][0]:.4f} rend {rows[K][1]:.4f}' for K in rows))
        for K, v in allk.items():
            v = np.array(v); print(f' K={K}: mean raw {v[:,0].mean():.4f} rend {v[:,1].mean():.4f}   gain vs K=1 raw {v[:,0].mean()-np.array(allk[1])[:,0].mean():+.4f} ({(v[:,0]>np.array(allk[1])[:,0]).sum()}/5)  rend {v[:,1].mean()-np.array(allk[1])[:,1].mean():+.4f} ({(v[:,1]>np.array(allk[1])[:,1]).sum()}/5)')


if __name__ == '__main__':
    main()
