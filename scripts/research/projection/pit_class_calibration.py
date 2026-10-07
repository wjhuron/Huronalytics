"""pit_class_calibration.py: is the 1-season pitcher projection biased for a CLASS of arm?

Prompted by Chris Paddack (2026-10-07): 4.95 RA9 projected as a starter after three seasons of
RA9 5.09 / 5.58 / 6.95 with FIP well below each. The question is whether the production model
under-projects runs for arms whose runs run persistently above their FIP, or for arms whose
recent run level is far worse than league.

Rebuilds the production 1-year model exactly as project_players.py fits it (pooled h=1 settings,
the four shrunk channels + starter share, Stuff+ channel at N0 250, experience term, park terms
with the target park in, age offset) and scores each target season 2022-2026 with OLS weights fit
on the OTHER four (LOSO). Pool: every pitcher with >= 30 IP in the target (the scoring pool of the
backtests). Residual = actual RA9 - projected, IP-weighted, with a standard error over pitchers.

Classes (history = B-2..B weighted d^k by BF, raw, unshrunk):
    gap   history RA9 minus history FIP, runs/9
    lvl   history RA9 relative to league, runs/9

Usage: python3 scripts/research/projection/pit_class_calibration.py
Output: console + data/_proj/_pit_class_calibration.json
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pit_rate_backtest as pr
import pit_horizon_backtest as ph
import pit_stuff_addon as pst

P = pr.P
PIT_EXP_K = 20
MIN_IP_T = 30


def heldout_records(min_ip_t=MIN_IP_T):
    """The production 1-year pitcher model, each target season 2022-2026 projected with OLS weights
    fit on the other four. One record per pitcher with >= min_ip_t IP in T."""
    S = {y: pr.season(y) for y in range(2015, 2027)}
    stuff = json.load(open(os.path.join(pr.ROOT, 'data', '_era_internal_stuff.json')))
    H1 = json.load(open(os.path.join(P, '_pit_horizon_backtest.json')))['1']['pooled']
    par = (H1['d'], H1['n0'], H1['peak'], H1['yi'], H1['od'])
    d = par[0]

    _pl = {y: json.load(open(os.path.join(P, f'lines_pitching_{y}.json'))) for y in range(2017, 2027)}
    _club = {y: {r['id']: r.get('team') for r in _pl[y]} for y in _pl}
    _lgra9 = {y: 27 * sum(int(r.get('runs') or 0) for r in _pl[y]) / sum(int(r.get('outs') or 0) for r in _pl[y]) for y in _pl}
    _PF = json.load(open(os.path.join(P, 'park_factors_hist.json')))

    def peff(y, team):
        pf = _PF.get(str(y), {}).get(str(team))
        return 0.0 if pf is None else ((pf / 100 + 1) / 2 - 1) * _lgra9[y]

    def rows_all(B):
        return [(pid, t, [S[B - k].get(pid) for k in range(3)]) for pid, t in S[B + 1].items()
                if any(S[B - k].get(pid) for k in range(3))]

    def design(rows, B):
        X, _, _ = ph.feats(rows, 1, *par)
        c, _ = pst.stuff_channel(rows, B + 1, stuff, d, 250)
        xe = np.array([1 / (1 + sum(h['bf'] for h in hist if h) / PIT_EXP_K) for _, _, hist in rows])
        xp = []
        for pid, _, hist in rows:
            num = den = 0.0
            for k, h in enumerate(hist):
                if h:
                    num += d ** k * h['bf'] * peff(B - k, _club[B - k].get(pid)); den += d ** k * h['bf']
            xp.append((num / den if den else 0.0, peff(B + 1, _club[B + 1].get(pid))))
        return np.column_stack([X[:, :-1], c, xe, np.array(xp), X[:, -1]])

    def hist_raw(hist, ch):
        num = den = 0.0
        for k, h in enumerate(hist):
            if h and h[ch] is not None:
                num += d ** k * h['bf'] * h[ch]; den += d ** k * h['bf']
        return num / den if den else np.nan

    bases = [2021, 2022, 2023, 2024, 2025]
    R = {B: rows_all(B) for B in bases}
    Xd = {B: design(R[B], B) for B in bases}
    y = {B: np.array([t['ra9'] for _, t, _ in R[B]]) for B in bases}
    w = {B: np.array([t['ip'] for _, t, _ in R[B]]) for B in bases}

    recs = []
    for B in bases:
        tr = [b for b in bases if b != B]
        p, _ = pr.fit_predict(np.vstack([Xd[b] for b in tr]), np.concatenate([y[b] for b in tr]),
                              np.concatenate([w[b] for b in tr]), Xd[B])
        for (pid, t, hist), pi in zip(R[B], p):
            if t['ip'] < min_ip_t:
                continue
            recs.append({'T': B + 1, 'pid': pid, 'ip': t['ip'], 'gs': t['gs'], 'pred': float(pi), 'act': t['ra9'],
                         'gap': hist_raw(hist, 'ra9') - hist_raw(hist, 'fip'), 'lvl': hist_raw(hist, 'ra9'),
                         'hist_ip': sum(h['ip'] for h in hist if h)})
    return recs


def main():
    recs = heldout_records()

    def summarize(sel, label):
        r = [x for x in recs if sel(x)]
        if not r:
            return None
        res = np.array([x['act'] - x['pred'] for x in r]); ww = np.array([x['ip'] for x in r])
        m = float((ww * res).sum() / ww.sum())
        # SE of a weighted mean, Kish effective n
        neff = ww.sum() ** 2 / (ww ** 2).sum()
        sd = float(np.sqrt((ww * (res - m) ** 2).sum() / ww.sum()))
        by_t = {}
        for T in sorted({x['T'] for x in r}):
            rr = [x for x in r if x['T'] == T]
            a = np.array([x['act'] - x['pred'] for x in rr]); b = np.array([x['ip'] for x in rr])
            by_t[T] = round(float((a * b).sum() / b.sum()), 2)
        out = {'class': label, 'n': len(r), 'resid': round(m, 3), 'se': round(sd / np.sqrt(neff), 3), 'by_T': by_t}
        print(f"{label:38s} n={out['n']:4d}  actual-proj {out['resid']:+.2f} ± {out['se']:.2f}   " +
              ' '.join(f"{T % 100}:{v:+.2f}" for T, v in by_t.items()))
        return out

    print('IP-weighted residual, actual RA9 minus projected (runs/9); positive = projection too kind')
    out = [summarize(lambda x: True, 'all')]
    for lo, hi in ((-9, -0.5), (-0.5, 0), (0, 0.5), (0.5, 1.0), (1.0, 9)):
        out.append(summarize(lambda x, lo=lo, hi=hi: lo <= x['gap'] < hi, f'gap RA9-FIP [{lo}, {hi})'))
    for lo, hi in ((-9, -0.5), (-0.5, 0.5), (0.5, 1.0), (1.0, 9)):
        out.append(summarize(lambda x, lo=lo, hi=hi: lo <= x['lvl'] < hi, f'level RA9 vs lg [{lo}, {hi})'))
    out.append(summarize(lambda x: x['gap'] >= 0.5 and x['lvl'] >= 0.5, 'Paddack class: gap>=.5 and lvl>=.5'))
    out.append(summarize(lambda x: x['gap'] >= 0.5 and x['lvl'] >= 0.5 and x['gs'] >= 0.5, '  same, starters in T'))
    out.append(summarize(lambda x: x['gap'] >= 0.5 and x['lvl'] >= 0.5 and x['hist_ip'] >= 150, '  same, >=150 hist IP'))
    with open(os.path.join(P, '_pit_class_calibration.json'), 'w') as f:
        json.dump([o for o in out if o], f, indent=1)


if __name__ == '__main__':
    main()
