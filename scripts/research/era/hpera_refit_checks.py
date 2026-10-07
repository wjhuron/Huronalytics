"""hpera_refit_checks.py: two checks on the honest hpERA refit before it ships (2026-10-07).

1. DURABLE ARMS, defined from the HISTORY. The shipped weights beat the refit on the old pool gated at
   >= 60 IP in base AND target, but a target gate selects on the outcome and the shipped weights were
   fit on that pool. The fair question is how each forecast does for arms who LOOK durable before the
   target period: classes from the base period only (innings and start share), every target outcome
   counted (>= 1 out), innings-weighted, held out by year exactly as hpera_honest_refit.evaluate.
2. FIT WEIGHTING. The refit weights rows by target innings, which lets starters dominate the fit and
   may be what drives the start-share weight to zero. Refit with equal weights and square-root weights
   and report each weight set plus its held-out score (scoring stays innings-weighted throughout).

Usage: python3 scripts/research/era/hpera_refit_checks.py
Output: console + data/_hpera_refit_checks.json
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hpera_honest_refit as m  # noqa: E402


def heldout(reps, arm, wfun=lambda ip: ip):
    out = {}
    for rp in reps:
        train = [q for q in reps if not (q['years'] & rp['years'])]
        b = m.fit(train, arm, wfun)
        out[rp['label']] = np.column_stack([np.ones(len(rp['rows'])), m.design(rp['rows'], arm)]) @ b
    return out


def wmse(p, y, w):
    return float((w * (p - y) ** 2).sum() / w.sum())


def main():
    reps = m.build()
    rng = np.random.default_rng(0)
    P = {a: heldout(reps, a) for a in ('ship', 'refit', 'SIERA')}
    res = {}
    print('1. DURABLE ARMS from the history (target >= 1 out, innings-weighted, held out by year)')
    classes = {'next': [('starter, 150+ IP in B', lambda r: r['b_gs'] >= 0.5 and r['b_ip'] >= 150),
                        ('starter, 120+ IP in B', lambda r: r['b_gs'] >= 0.5 and r['b_ip'] >= 120),
                        ('starter, 30-120 IP in B', lambda r: r['b_gs'] >= 0.5 and r['b_ip'] < 120),
                        ('reliever, 50+ IP in B', lambda r: r['b_gs'] < 0.5 and r['b_ip'] >= 50),
                        ('reliever, 30-50 IP in B', lambda r: r['b_gs'] < 0.5 and r['b_ip'] < 50)],
               'ros': [('starter, 75+ IP in first half', lambda r: r['b_gs'] >= 0.5 and r['b_ip'] >= 75),
                       ('starter, 60+ IP in first half', lambda r: r['b_gs'] >= 0.5 and r['b_ip'] >= 60),
                       ('starter, 15-60 IP in first half', lambda r: r['b_gs'] >= 0.5 and r['b_ip'] < 60),
                       ('reliever, 25+ IP in first half', lambda r: r['b_gs'] < 0.5 and r['b_ip'] >= 25),
                       ('reliever, 15-25 IP in first half', lambda r: r['b_gs'] < 0.5 and r['b_ip'] < 25)]}
    for obj, cl in classes.items():
        R = [rp for rp in reps if rp['obj'] == obj]
        print(f'  {obj.upper()}')
        for name, sel in cl:
            per, num_s, num_r, num_q, n = [], 0.0, 0.0, 0.0, 0
            masks = []
            for rp in R:
                mk = np.array([sel(r) for r in rp['rows']]); masks.append(mk)
                y = np.array([r['y'] for r in rp['rows']])[mk]; w = np.array([r['w'] for r in rp['rows']])[mk]
                s, f, q = (wmse(P[a][rp['label']][mk], y, w) for a in ('ship', 'refit', 'SIERA'))
                per.append((s, f, q)); n += int(mk.sum())
            s_tot = sum(x[0] for x in per); f_tot = sum(x[1] for x in per); q_tot = sum(x[2] for x in per)
            bs = []
            for _ in range(1000):
                a = b = 0.0
                for rp, mk in zip(R, masks):
                    idx = np.where(mk)[0]; i = rng.choice(idx, len(idx))
                    y = np.array([r['y'] for r in rp['rows']])[i]; w = np.array([r['w'] for r in rp['rows']])[i]
                    a += wmse(P['refit'][rp['label']][i], y, w); b += wmse(P['ship'][rp['label']][i], y, w)
                bs.append(100 * (a / b - 1))
            ch = 100 * (f_tot / s_tot - 1); se = float(np.std(bs))
            wins = sum(x[1] < x[0] for x in per); wq = sum(x[1] < x[2] for x in per)
            print(f'    {name:34s} n {n:4d}   refit vs shipped {ch:+5.1f}% (SE {se:.1f}, z {ch / se:+.2f}) better {wins}/{len(R)}'
                  f'   refit vs SIERA better {wq}/{len(R)}')
            res[f'{obj}|{name}'] = {'n': n, 'change_pct': ch, 'se': se, 'wins_vs_ship': wins, 'wins_vs_siera': wq}

    print('\n2. FIT WEIGHTING (scoring stays innings-weighted; held out by year)')
    W = {'innings (as fit)': lambda ip: ip, 'sqrt innings': lambda ip: math.sqrt(ip), 'equal': lambda ip: 1.0}
    for name, wf in W.items():
        b = m.fit(reps, 'refit', wf)
        H = heldout(reps, 'refit', wf)
        line = []
        for obj in ('next', 'ros'):
            R = [rp for rp in reps if rp['obj'] == obj]
            mse = np.mean([wmse(H[rp['label']], np.array([r['y'] for r in rp['rows']]), np.array([r['w'] for r in rp['rows']])) for rp in R])
            beat = sum(wmse(H[rp['label']], np.array([r['y'] for r in rp['rows']]), np.array([r['w'] for r in rp['rows']]))
                       < wmse(P['ship'][rp['label']], np.array([r['y'] for r in rp['rows']]), np.array([r['w'] for r in rp['rows']])) for rp in R)
            line.append(f'{obj} MSE {mse:.3f} (beats shipped {beat}/{len(R)})')
        wts = dict(zip(m.CANDS['refit'], b[1:]))
        print(f'  {name:18s} ' + '  '.join(line))
        print(f'      weights (research sign; xrv production sign is the negative): ' + ' '.join(f'{k} {v:+.3f}' for k, v in wts.items()))
        res[f'weighting|{name}'] = {k: float(v) for k, v in wts.items()}
    with open(os.path.join(m.hr.ROOT, 'data', '_hpera_refit_checks.json'), 'w') as f:
        json.dump(res, f, indent=1)


if __name__ == '__main__':
    main()
