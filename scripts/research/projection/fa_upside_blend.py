"""fa_upside_blend.py: a second free-agent ranking with direct weight on talent rate and upside (per Wally 2026-11-05). Research only.

Three parts, each in WAR over the term, a season absent = 0 in the truth:
  E  expected total: the fa_rank_blend form (M2 hitters and starters, M1 relievers, one-season B at h = 1).
  F  full-time value: the rate aged year by year and summed, what he is worth if he holds the job and stays on the field.
     Hitters: the project_players aging rule in wins per 600. Pitchers: the project_players chain, level above replacement x R(k), R 1 / .85 / .70 / .55 / .40.
  U  upside: the 90th percentile of the outcome, quantile regression on B, B x age, R, R x age, age, fit leaving T out.
Parts are scaled by their pooled SD (group and horizon), score = we E/sdE + wf F/sdF + wu U/sdU. Weight grid .1 simplex.
Objectives, mean over held-out target seasons, reported side by side because they trade: r with actual total; TOP, overlap of the score's top decile with the actual top decile; TOPRATE, the same overlap on actual WAR per full season, target-PT weighted is not usable for a decile, so players with target PT under a quarter season count as not top (no gate on the pool).
Rule: A beats B at a gap over 2 paired-bootstrap SE and most replicates, else TIE.
Add-on tests for U only: history EV95 percent (hitters), Stuff+ (pitchers).

Usage: PYTHONHASHSEED=0 python3 scripts/research/projection/fa_upside_blend.py
Output: console + data/_proj/_fa_upside_blend.json
"""
import csv, json, os, pickle, sys
import numpy as np
from sklearn.linear_model import QuantileRegressor
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fa_rank_blend as B
FIXED = {'H': (.5, .5, 0), 'SP': (.5, .5, 0), 'RP': (.5, 0, .5)}
META = B.HB.META; HC = META['hwarConstants']; EW = META['eraPlusConstants']['war']
RK = [1, .85, .70, .55, .40]
Q = .9
CACHE = os.path.join(B.P, '_fa_upside_rows.pkl')


def aged_sum(R, age, group, h):
    """R per full season at the unit. Same function for history and 2027."""
    tot = 0.0
    if group == 'H':
        per = 600 / HC['wobaScale'] / HC['rpw']
        for k in range(h):
            aa = age + k; lo = min(aa, 30) - min(age, 30); hi = max(aa, 30) - max(age, 30)
            tot += R + (.002 * lo - .0045 * hi) * per
    else:
        rep = EW['replSp'] * 20 if group == 'SP' else EW['replRp'] * 60 / 9
        for k in range(h):
            tot += rep + RK[k] * (R - rep)
    return tot


def dz(R, g, h, form):
    w = FIXED[g]
    b = np.array([B.blend_rate(r, w) * r['pt'] for r in R]); u = np.array([B.blend_rate(r, w) * r['unit'] for r in R]); a = np.array([r['age'] - 30.0 for r in R])
    return np.column_stack([np.ones(len(R)), b, b * a, u, u * a, a]) if form == 'M2' else np.column_stack([np.ones(len(R)), b, b * a])


def qfit(X, y):
    m = QuantileRegressor(quantile=Q, alpha=0.0, solver='highs', fit_intercept=False).fit(X, y)
    return m.coef_


def pin(p, y):
    e = y - p
    return float(np.mean(np.maximum(Q * e, (Q - 1) * e)))


def top_overlap(s, y, f=.1):
    n = max(1, int(round(len(y) * f))); a = set(np.argsort(-s)[:n]); b = set(np.argsort(-y)[:n])
    return len(a & b) / n


def main():
    if os.path.exists(CACHE):
        rows = pickle.load(open(CACHE, 'rb'))
    else:
        rows = B.build('bat') + B.build('pit'); pickle.dump(rows, open(CACHE, 'wb'))
    out = {}
    ev = {}
    for y in range(2015, 2027):
        with open(os.path.join(B.P, f'ev_batter_{y}.csv'), encoding='utf-8-sig') as f:
            ev[y] = {int(r['player_id']): (float(r['ev95percent'] or 0), int(r['attempts'] or 0)) for r in csv.DictReader(f)}
    stuff = json.load(open(os.path.join(B.ROOT, 'data', '_era_internal_stuff.json')))

    def addon(r):
        if r['group'] == 'H':
            n = d = 0.0
            for k in range(3):
                v = ev.get(r['T'] - 1 - k, {}).get(r['pid'])
                if v and v[1]:
                    n += .7 ** k * v[1] * v[0]; d += .7 ** k * v[1]
            return (n + 100 * 38) / (d + 100) - 38
        n = d = 0.0
        for k in range(3):
            v = stuff.get(str(r['T'] - 1 - k), {}).get(str(r['pid']))
            if v and v.get('stuff_full') is not None:
                n += .7 ** k * v['n_full'] * v['stuff_full']; d += .7 ** k * v['n_full']
        return n / (d + 250) * 100

    for g in ('H', 'SP', 'RP'):
        w = FIXED[g]; form = 'M2' if g != 'RP' else 'M1'
        G = [r for r in rows if r['group'] == g and B.blend_rate(r, w) is not None]
        for h in (1, 3, 5):
            use = [r for r in G if r[f'y{h}'] is not None]; Ts = sorted({r['T'] for r in use})
            print(f'\n=== {g} {h} seasons: T {Ts}, n {len(use)}', flush=True)
            E, U, U0, Ua, Y, F, RT, RR = {}, {}, {}, {}, {}, {}, {}, {}
            for T in Ts:
                te = [r for r in use if r['T'] == T]; tr = [r for r in use if r['T'] != T]; ytr = np.array([r[f'y{h}'] for r in tr]); Y[T] = np.array([r[f'y{h}'] for r in te]); RR[T] = te
                if h == 1:
                    E[T] = np.array([B.blend_rate(r, w) * r['pt'] for r in te]); Etr = np.array([B.blend_rate(r, w) * r['pt'] for r in tr])
                else:
                    c = np.linalg.lstsq(dz(tr, g, h, form), ytr, rcond=None)[0]; E[T] = dz(te, g, h, form) @ c; Etr = dz(tr, g, h, form) @ c
                F[T] = np.array([aged_sum(B.blend_rate(r, w) * r['unit'], r['age'], g, h) for r in te])
                U[T] = dz(te, g, h, 'M2') @ qfit(dz(tr, g, h, 'M2'), ytr)
                U0[T] = np.column_stack([np.ones(len(te)), E[T]]) @ qfit(np.column_stack([np.ones(len(tr)), Etr]), ytr)
                if h == 3 or h == 1:
                    Xa = np.column_stack([dz(tr, g, h, 'M2'), [addon(r) for r in tr]]); Xt = np.column_stack([dz(te, g, h, 'M2'), [addon(r) for r in te]]); Ua[T] = Xt @ qfit(Xa, ytr)
            p, p0 = [pin(U[T], Y[T]) for T in Ts], [pin(U0[T], Y[T]) for T in Ts]
            print(f'  U pinball {np.mean(p):.4f} v scaled expected {np.mean(p0):.4f}, wins {sum(a < b for a, b in zip(p, p0))}/{len(Ts)}; coverage {np.mean([np.mean(Y[T] <= U[T]) for T in Ts]):.3f} (target {Q})')
            if Ua:
                pa = [pin(Ua[T], Y[T]) for T in Ts]; print(f'  U + add-on pinball {np.mean(pa):.4f}, beats U {sum(a < b for a, b in zip(pa, p))}/{len(Ts)}')
            allE = np.concatenate([E[T] for T in Ts]); allF = np.concatenate([F[T] for T in Ts]); allU = np.concatenate([U[T] for T in Ts])
            sd = (float(allE.std()), float(allF.std()), float(allU.std()))
            print(f'  SD E {sd[0]:.3f} F {sd[1]:.3f} U {sd[2]:.3f}; r(E,F) {np.corrcoef(allE, allF)[0, 1]:.3f} r(E,U) {np.corrcoef(allE, allU)[0, 1]:.3f} r(F,U) {np.corrcoef(allF, allU)[0, 1]:.3f}')
            grid = [(a / 10, b / 10, round((10 - a - b) / 10, 1)) for a in range(11) for b in range(11 - a)]
            res = {}
            # top by actual full-season rate: truth from y over the unit is not available by season here, so use y and a talent-weighted version: y / max(expected share) is noisy. Report on totals.
            for wt in grid:
                S = {T: wt[0] * E[T] / sd[0] + wt[1] * F[T] / sd[1] + wt[2] * U[T] / sd[2] for T in Ts}
                res[wt] = dict(r={T: B.wr(S[T], Y[T]) for T in Ts}, top={T: top_overlap(S[T], Y[T]) for T in Ts}, top5={T: top_overlap(S[T], Y[T], .05) for T in Ts}, mean_top={T: float(Y[T][np.argsort(-S[T])[:max(1, int(round(len(Y[T]) * .1)))]].mean()) for T in Ts})
            m = lambda wt, k: float(np.mean(list(res[wt][k].values())))
            print('  corners  [E, F, U]: r / top decile / top 5pct / mean actual WAR of the top decile')
            for wt in ((1, 0, 0), (0, 1, 0), (0, 0, 1), (.5, .25, .25), (.4, .3, .3), (.34 if False else .3, .4, .3), (.5, .5, 0), (.5, 0, .5), (.7, .1, .2), (.2, .4, .4)):
                wt = tuple(float(x) for x in wt)
                if wt in res:
                    print(f'    {wt}: {m(wt, "r"):.4f} {m(wt, "top"):.3f} {m(wt, "top5"):.3f} {m(wt, "mean_top"):.2f}')
            for k in ('r', 'top', 'top5', 'mean_top'):
                bst = max(res, key=lambda x: m(x, k)); print(f'  best on {k}: {bst} {m(bst, k):.4f}')
            print('  curve, E share with the rest split evenly: ' + ' '.join(f'{a/10:.1f}:{m((a/10, round((10-a)/20, 2) if (10-a)%2==0 else None, 0) if False else min(res, key=lambda x: abs(x[0]-a/10)+abs(x[1]-(1-a/10)/2)), "r"):.3f}/{m(min(res, key=lambda x: abs(x[0]-a/10)+abs(x[1]-(1-a/10)/2)), "top"):.3f}' for a in range(0, 11, 2)))
            aX = dz(use, g, h, 'M2'); ay = np.array([r[f'y{h}'] for r in use])
            out[f'{g}_{h}'] = dict(sd=sd, qcoef=qfit(aX, ay).tolist(), T=Ts, grid={str(k): dict(r=m(k, 'r'), top=m(k, 'top'), top5=m(k, 'top5'), mean_top=m(k, 'mean_top')) for k in res}, per_T={str(k): {kk: res[k][kk] for kk in ('r', 'top', 'top5')} for k in res})
    json.dump(out, open(os.path.join(B.P, '_fa_upside_blend.json.tmp'), 'w'), default=float); os.replace(os.path.join(B.P, '_fa_upside_blend.json.tmp'), os.path.join(B.P, '_fa_upside_blend.json'))
    print('\nwrote data/_proj/_fa_upside_blend.json')


if __name__ == '__main__':
    main()
