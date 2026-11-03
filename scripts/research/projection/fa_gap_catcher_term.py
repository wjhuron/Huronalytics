"""fa_gap_catcher_term.py: the hitter FA gap re-measured with the shipped catcher-by-age prior term (2026-11-03).

fa_rundown_table.py's FA_WOBA -.0060 was measured before project_players.py carried the catcher term. FA catchers are older
than the pool, so the term may already hold part of that gap. Same frame and control as fa_rundown_constants.py (held-out
projection, T x age-bin x experience-bin), with the term's coefficients fit leaving the target season out.
  site   projection alone, T 2021-2026
  blend  50/50 with Steamer, centered as in h2h_batting, T 2021-2025: what the rundown reads

Usage: python3 scripts/research/projection/fa_gap_catcher_term.py
Output: console + data/_proj/_fa_gap_catcher_term.json
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bat_thin_prior_followup as tf
import bat_thin_prior_test as t
import fa_class_calibration as fc
import fa_class_followup as ff
import h2h_batting as h2

KT, A0, CAP = 800, 24, 5


def term_map():
    Z = t.build()
    out = {}
    for T in t.TARGETS:
        g = tf.fit_capped(Z, [x for x in t.TARGETS if x != T], KT, A0, CAP)
        v = tf.capped(Z[T], KT, A0, CAP) @ g
        for i, pid in enumerate(Z[T]['id']):
            out[(T, int(pid))] = (float(v[i]), bool(Z[T]['isC'][i]))
    return out


def block(lab, p, A, f0, isC, keep, res):
    y, w, T_, age, E = A['y'][keep], A['w'][keep], A['T'][keep], A['age'][keep], A['E'][keep]
    fa, c = f0[keep], isC[keep]
    r = y - p
    print(f'\n{lab}: rows {len(r)}, FA rows {int(fa.sum())}, FA catchers {int((fa & c).sum())}')
    res[lab] = {'all': fc.report('all FA vs rest', r, fa, age, E, w, T_, 'wOBA'),
                'catchers': fc.report('FA catchers vs other catchers', r, fa, age, E, w, T_, 'wOBA', sub=c),
                'others': fc.report('FA non-catchers vs non-catchers', r, fa, age, E, w, T_, 'wOBA', sub=~c)}


def main():
    FA = fc.fa_rows()
    A = ff.frame(FA)
    f0 = ff.flag(A, FA, 0)
    M = term_map()
    n = len(A['y'])
    d = np.zeros(n); isC = np.zeros(n, bool)
    for i in range(n):
        d[i], isC[i] = M.get((int(A['T'][i]), int(A['id'][i])), (0.0, False))
    miss = sum((int(A['T'][i]), int(A['id'][i])) not in M for i in range(n))
    print(f'frame {n} rows, {miss} with no term row (scored as no term)')
    res = {}
    keep = np.where(A['T'] >= 2021)[0]
    block('site before', A['p'][keep], A, f0, isC, keep, res)
    block('site after', A['p'][keep] + d[keep], A, f0, isC, keep, res)
    for lab, shift in (('blend before', 0.0), ('blend after', 1.0)):
        idx, P = [], []
        for T in range(2021, 2026):
            st = h2.fg('steamer', T)
            ix = [i for i in np.where(A['T'] == T)[0] if int(A['id'][i]) in st]
            y, w = A['y'][ix], A['w'][ix]
            ctr = lambda v: v - np.average(v, weights=w) + np.average(y, weights=w)
            P.append(0.5 * ctr(A['p'][ix] + shift * d[ix]) + 0.5 * ctr(np.array([st[int(A['id'][i])] for i in ix])))
            idx.extend(ix)
        block(lab, np.concatenate(P), A, f0, isC, np.array(idx), res)
    tmp = os.path.join(t.v1.P, '_fa_gap_catcher_term.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(res, f, indent=1, default=float)
    os.replace(tmp, os.path.join(t.v1.P, '_fa_gap_catcher_term.json'))


if __name__ == '__main__':
    main()
