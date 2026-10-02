"""pit_stuff_addon.py: does Stuff+ history add to the pitcher projection (targets 2022-2026)?

Paired test on identical rows: pit_rate_backtest's model at its pooled settings, with and
without one extra channel, the LOSO Stuff+ of each history season (data/_era_internal_stuff.json:
stuff_full, a per-pitch mean in run units from fold models that never saw that season, n_full
pitches; 2021-2025). History weighted d^k by pitches and shrunk at N0_S pitches (swept).
OLS weights refit LOSO over the five target seasons, so both arms get the same fitting freedom.

Pitchers with no Stuff+ history (none of B-2..B in the file) get the channel at 0 (league), the
same thing the shrink does to a thin sample; their count is printed.

Usage: python3 scripts/research/projection/pit_stuff_addon.py
Output: console + data/_proj/_pit_stuff_addon.json
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pit_rate_backtest as pr

ROOT = pr.ROOT
TARGETS = [2022, 2023, 2024, 2025, 2026]
POOLED = {'ra9': (0.65, 500, 28, 0.04, 0.01), 'fip': (0.5, 500, 30, 0.04, 0.01)}
N0_S = [0, 100, 250, 500, 1000, 2000]


def stuff_channel(rows, T, S, d, n0s):
    out, missing = [], 0
    for pid, _, _ in rows:
        num = den = 0.0
        for k in range(3):
            rec = S.get(str(T - 1 - k), {}).get(str(pid))
            if rec and rec.get('n_full'):
                num += d ** k * rec['n_full'] * rec['stuff_full']
                den += d ** k * rec['n_full']
        missing += den == 0
        out.append(num / (den + n0s) if den + n0s > 0 else 0.0)
    return np.array(out), missing


def main():
    S = json.load(open(os.path.join(ROOT, 'data', '_era_internal_stuff.json')))
    D = pr.build()
    res = {}
    for tgt, par in POOLED.items():
        yi = 1 if tgt == 'ra9' else 2
        F = {T: pr.features(D[T], *par) for T in TARGETS}
        base = []
        for j, T in enumerate(TARGETS):
            tr = [F[s] for s in TARGETS if s != T]
            p, _ = pr.fit_predict(np.vstack([f[0] for f in tr]), np.concatenate([f[yi] for f in tr]),
                                  np.concatenate([f[3] for f in tr]), F[T][0])
            base.append(pr.wmse(p, F[T][yi], F[T][3]))
        print(f'\n== target {tgt}  (base settings d n0 peak yi od = {par})')
        out = {'base': base, 'with': {}}
        for n0s in N0_S:
            Fx, miss = {}, {}
            for T in TARGETS:
                ch, miss[T] = stuff_channel(D[T], T, S, par[0], n0s)
                X = F[T][0]
                Fx[T] = np.column_stack([X[:, :-1], ch, X[:, -1]])   # age offset stays last
            L, betas = [], []
            for j, T in enumerate(TARGETS):
                tr = [s for s in TARGETS if s != T]
                p, beta = pr.fit_predict(np.vstack([Fx[s] for s in tr]), np.concatenate([F[s][yi] for s in tr]),
                                         np.concatenate([F[s][3] for s in tr]), Fx[T])
                L.append(pr.wmse(p, F[T][yi], F[T][3])); betas.append(beta[-1])
            wins = sum(l < b for l, b in zip(L, base))
            gain = 100 * (1 - np.mean(L) / np.mean(base))
            out['with'][n0s] = {'L': L, 'wins': wins, 'stuff_beta': float(np.mean(betas))}
            print(f'  N0_S {n0s:>5}: wins {wins}/5  mean gain {gain:5.2f}%  stuff weight {np.mean(betas):8.2f}  '
                  + ' '.join(f'{T}:{l:.4f}/{b:.4f}' for T, l, b in zip(TARGETS, L, base)))
        print('  pitchers with no Stuff+ history:', {T: int(miss[T]) for T in TARGETS}, 'of', {T: len(D[T]) for T in TARGETS})
        res[tgt] = out
    tmp = os.path.join(pr.P, '_pit_stuff_addon.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(res, f, indent=1)
    os.replace(tmp, os.path.join(pr.P, '_pit_stuff_addon.json'))


if __name__ == '__main__':
    main()
