"""fa_rundown_constants.py: the two hitter FA corrections as measured on what the rundown actually reads.

 1. wOBA gap on the 50/50 ours + Steamer blend, T 2021-2025 (no complete Steamer 2026), matched set, centered as in h2h_batting,
    controlled for T x age-bin x experience-bin (fa_class_calibration.controlled), with bootstrap SE.
 2. PA gap by tier of held-out projected PA, T 2021-2026, zeros counted. Tells a constant from a share-of-playing-time gap.

Usage: python3 scripts/research/projection/fa_rundown_constants.py
Output: console + data/_proj/_fa_rundown_constants.json
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fa_class_calibration as fc
import fa_class_followup as ff
import h2h_batting as h2
import pt_backtest as pt


def main():
    FA = fc.fa_rows()
    A = ff.frame(FA)
    f0 = ff.flag(A, FA, 0)
    rows = {n: [] for n in ('T', 'p', 'y', 'w', 'fa', 'age', 'E')}
    for T in range(2021, 2026):
        st = h2.fg('steamer', T)
        ix = np.where(A['T'] == T)[0]
        keep = [i for i in ix if int(A['id'][i]) in st]
        y, w = A['y'][keep], A['w'][keep]
        ctr = lambda v: v - np.average(v, weights=w) + np.average(y, weights=w)
        p = 0.5 * ctr(A['p'][keep]) + 0.5 * ctr(np.array([st[int(A['id'][i])] for i in keep]))
        for n, v in (('T', A['T'][keep]), ('p', p), ('y', y), ('w', w), ('fa', f0[keep]), ('age', A['age'][keep]), ('E', A['E'][keep])):
            rows[n].append(v)
    R = {k: np.concatenate(v) for k, v in rows.items()}
    res = {'blend_gap': fc.report('50/50 blend', R['y'] - R['p'], R['fa'], R['age'], R['E'], R['w'], R['T'], 'wOBA')}

    S = {y: pt.hit_season(y) for y in range(pt.TARGETS[0] - 3, 2027)}
    Aa = {y: pt.aaa_pt(y, 'plateAppearances') for y in S}
    Rr = {T: pt.rows('hit', S, Aa, T - 1) for T in pt.TARGETS}
    cols = pt.ARMS['hit']['full']
    X = {T: pt.design(Rr[T], cols) for T in Rr}; Y = {T: np.array([y for _, _, y in Rr[T]]) for T in Rr}
    out = []
    for T in range(2021, 2027):
        tr = [s for s in Rr if s != T]
        b = np.linalg.lstsq(np.vstack([X[s] for s in tr]), np.concatenate([Y[s] for s in tr]), rcond=None)[0]
        q = np.clip(X[T] @ b, 0, max(Y[s].max() for s in tr))
        out += [(T, (T, int(pid)) in FA, y, v) for (pid, _, y), v in zip(Rr[T], q)]
    a = np.array(out, float); fa = a[:, 1] > 0; y = a[:, 2]; q = a[:, 3]; r = y - q
    print('\nPA gap by projected PA tier, T 2021-2026 (FA residual; rest in brackets)')
    res['pa_tiers'] = {}
    for lo, hi in ((0, 150), (150, 300), (300, 450), (450, 1000)):
        m = (q >= lo) & (q < hi)
        se = r[m & fa].std(ddof=1) / np.sqrt((m & fa).sum())
        print(f'  {lo}-{hi}: FA {r[m&fa].mean():+.1f} se {se:.1f} n {int((m&fa).sum())} mean proj {q[m&fa].mean():.0f} share {r[m&fa].mean()/q[m&fa].mean():+.3f} [rest {r[m&~fa].mean():+.1f} n {int((m&~fa).sum())}] diff {r[m&fa].mean()-r[m&~fa].mean():+.1f}')
        res['pa_tiers'][f'{lo}-{hi}'] = dict(fa=float(r[m & fa].mean()), se=float(se), rest=float(r[m & ~fa].mean()), n=int((m & fa).sum()), proj=float(q[m & fa].mean()))
    with open(os.path.join(pt.P, '_fa_rundown_constants.json'), 'w') as f:
        json.dump(res, f, indent=1)


if __name__ == '__main__':
    main()
