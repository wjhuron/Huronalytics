"""pit_role_rep_test.py: does a swingman's hpWAR total read better on his start share than on the SP180 / RP60 cut? (2026-11-05, FA tab audit). Research only.
Production gives a pitcher the role of his unit: start share >= .5 starter, else reliever, for both the runs level and the replacement rate. A 15 GS, 32 G arm then counts at reliever replacement over 74 projected innings, mostly thrown as a starter.
UNIT  the production cut. SHARE  level and replacement interpolated by his base-season start share (what hpwar_total_backtest scored as hp). Same held-out rate and playing time. Absent = 0.
Rule: gap over 2 paired-bootstrap SE and most replicates, else TIE. Truth: fWAR, runs-allowed WAR, even mix. Pools: all; swingmen by history (share .2 to .8).
Usage: PYTHONHASHSEED=0 python3 scripts/research/projection/pit_role_rep_test.py
"""
import json, os, sys, pickle
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fa_rank_blend as B
HB = B.HB
G = -0.103     # the fit's start-share coefficient, runs per 9, starter minus reliever
m = B.capture(HB.pitchers)
P = B.P
LN = {y: {x['id']: x for x in json.load(open(os.path.join(P, f'lines_pitching_{y}.json')))} for y in range(2017, 2027)}
A = B.actuals('pit')
out = {}
for T, R in m.items():
    lg = 27 * sum(int(x.get('runs') or 0) for x in LN[T].values()) / sum(int(x.get('outs') or 0) for x in LN[T].values())
    rows = []
    for r in R:
        L = LN[T - 1].get(r['pid']) or LN[T - 2].get(r['pid']) or LN[T - 3].get(r['pid']) or {}
        g_, gs = int(L.get('gamesPitched') or 0), int(L.get('gamesStarted') or 0); sh = gs / g_ if g_ else 0.0
        pt = r['pt'] or 0.0
        share = (-r['pred'] / HB.RPW + HB.REPL_RP + (HB.REPL_SP - HB.REPL_RP) * sh) * pt / 9
        cut = 1.0 if sh >= .5 else 0.0
        # pred carries the fit at his target role through gs; move it to the cut by the fit's coefficient at most, reported with and without
        unit = (-r['pred'] / HB.RPW + (HB.REPL_SP if cut else HB.REPL_RP)) * pt / 9
        unit2 = (-(r['pred'] + G * (cut - sh)) / HB.RPW + (HB.REPL_SP if cut else HB.REPL_RP)) * pt / 9
        l = LN[T].get(r['pid']); o = int((l or {}).get('outs') or 0); ra = 0.0
        if o:
            g2, gs2 = int(l.get('gamesPitched') or 0), int(l.get('gamesStarted') or 0)
            ra = ((lg - 27 * int(l.get('runs') or 0) / o) / HB.RPW + HB.REPL_RP + (HB.REPL_SP - HB.REPL_RP) * (gs2 / g2 if g2 else 0)) * o / 27
        rows.append(dict(sh=sh, share=share, unit=unit, unit2=unit2, f=r['wT'], ra=ra, mix=(r['wT'] + ra) / 2))
    out[T] = rows
Ts = sorted(out)
for lab, pool in (('all', lambda x: True), ('swingmen, share .2-.8', lambda x: .2 <= x['sh'] <= .8), ('share .2-.5, reliever unit', lambda x: .2 <= x['sh'] < .5), ('share .5-.8, starter unit', lambda x: .5 <= x['sh'] <= .8)):
    print(f'\n{lab}: n {[sum(pool(x) for x in out[T]) for T in Ts]}')
    for tgt in ('f', 'ra', 'mix'):
        P_ = {T: [x for x in out[T] if pool(x)] for T in Ts}
        a = {T: np.array([x['share'] for x in P_[T]]) for T in Ts}; b = {T: np.array([x['unit2'] for x in P_[T]]) for T in Ts}; y = {T: np.array([x[tgt] for x in P_[T]]) for T in Ts}
        g, se, wi, n = B.paired_gap(a, b, y)
        rm = [(B.rmse(a[T], y[T]), B.rmse(b[T], y[T]), float(np.mean(a[T] - y[T])), float(np.mean(b[T] - y[T]))) for T in Ts]; rm = np.mean(rm, axis=0)
        print(f'  {tgt:4s} r SHARE v UNIT gap {g:+.4f} (SE {se:.4f}) wins {wi}/{n} -> {B.verdict(g, se, wi, n, "SHARE", "UNIT")}; rmse {rm[0]:.3f} v {rm[1]:.3f}; mean error {rm[2]:+.3f} v {rm[3]:+.3f}')
