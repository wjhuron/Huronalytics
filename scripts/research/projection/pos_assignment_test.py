"""pos_assignment_test.py: which history best predicts next season's positional runs per 600 PA?

The hpWAR assembly takes positional runs per PA from the base season only (the shipped 2026 hPosRuns per
PA), which over-credits a defensive replacement (innings without PA) and follows one season's role.
Truth: positional runs per 600 PA in T, from T's innings by position (MLB API; a DH game counts 9
innings, the hwar.py convention) on the shipped 2026 table (metadata hwarConstants.posAdj, the .57
spread), for hitters with >= 300 PA in T (the full-time players a 600-PA rate describes).
Candidates, all from seasons before T:
  last      T-1 runs per PA x 600 (the shipped method)
  wmix      innings SHARES by position, weighted d^k over T-1..T-3 by innings, times a full-timer's
            innings per 600 PA (FULL_INN, the median of the top 150 T-1 hitters by PA, measured), d swept
  wlast     wmix with d = 0 (last season's shares only)
Scored PA_T-weighted MSE, seasons 2019-2026.

Usage: python3 scripts/research/projection/pos_assignment_test.py
"""
import json
import os
from collections import defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
TD = os.path.join(ROOT, 'data', '_hwar_team')
P = os.path.join(ROOT, 'data', '_proj')
POS = ('C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH')
TARGETS = list(range(2019, 2027))


def innings(y):
    out = defaultdict(dict)
    for s in json.load(open(os.path.join(TD, f'innings_{y}.json')))['stats'][0]['splits']:
        p = s['position']['abbreviation']
        if p not in POS:
            continue
        st = s['stat']
        if p == 'DH':
            inn = 9.0 * float(st.get('games') or 0)
        else:
            whole, _, frac = str(st.get('innings') or '0').partition('.')
            inn = int(whole) + int(frac or 0) / 3
        out[s['player']['id']][p] = out[s['player']['id']].get(p, 0.0) + inn
    return out


def main():
    adj = json.load(open(os.path.join(ROOT, 'data', 'metadata_rs.json')))['hwarConstants']['posAdj']
    I = {y: innings(y) for y in range(2016, 2027)}
    PA = {y: {r['id']: int(r.get('plateAppearances') or 0) for r in json.load(open(os.path.join(P, f'lines_hitting_{y}.json')))}
          for y in range(2016, 2027)}
    runs = lambda inn: sum(v * adj[p] / 1458.0 for p, v in inn.items())
    res = defaultdict(list)
    for T in TARGETS:
        regs = sorted((pid for pid in PA[T - 1] if pid in I[T - 1]), key=lambda q: -PA[T - 1][q])[:150]   # top 150 by PA (2020 had no 500-PA season)
        full_inn = float(np.median([sum(I[T - 1][pid].values()) / PA[T - 1][pid] * 600 for pid in regs]))
        y, w, pred = [], [], defaultdict(list)
        for pid, pa in PA[T].items():
            if pa < (110 if T == 2020 else 300) or pid not in I[T]:    # 300 PA, scaled to 2020's 60 games
                continue
            hist = [(I[T - 1 - k].get(pid), PA[T - 1 - k].get(pid, 0)) for k in range(3)]
            if not hist[0][0] or not hist[0][1]:
                continue
            y.append(runs(I[T][pid]) / pa * 600); w.append(pa)
            pred['last'].append(runs(hist[0][0]) / hist[0][1] * 600)
            for d in (0.0, 0.3, 0.5, 0.7, 1.0):
                sh = defaultdict(float); tot = 0.0
                for k, (inn, _) in enumerate(hist):
                    if inn:
                        for p, v in inn.items():
                            sh[p] += d ** k * v; tot += d ** k * v
                pred[f'wmix d{d}'].append(sum(v / tot * adj[p] for p, v in sh.items()) * full_inn / 1458.0)
        y, w = np.array(y), np.array(w, float)
        for k, v in pred.items():
            res[k].append(float(np.average((np.array(v) - y) ** 2, weights=w)))
        res['_n'].append(len(y)); res['_full'].append(round(full_inn))
    print('n per season', res.pop('_n'), '| full-time innings per 600 PA', res.pop('_full'))
    base = res['last']
    for k, v in res.items():
        print(f'  {k:12s} mean MSE {np.mean(v):6.2f}   beats last {sum(a < b for a, b in zip(v, base))}/{len(v)}')


if __name__ == '__main__':
    main()
