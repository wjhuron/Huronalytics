"""fa_age_band_test.py: is the 3 and 5 year hitter value too high for 31-32 year olds, or is that band noise? (2026-11-05). Research only.
Held-out M2 (fa_rank_blend form) by target season, actual over predicted cumulative WAR by age band, positive-value hitters. Then candidate fixes, fit leaving T out:
  M2   shipped form       Q  M2 plus a quadratic age term on B and R       BAND  M2 plus a 31-32 band term on B
Rule: gap over 2 paired-bootstrap SE and most replicates, else TIE. A band only one replicate set supports is noise.
Usage: PYTHONHASHSEED=0 python3 scripts/research/projection/fa_age_band_test.py
"""
import os, pickle, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fa_rank_blend as B
rows = pickle.load(open(os.path.join(B.P, '_fa_upside_rows.pkl'), 'rb'))
w = (.5, .5, 0)
G = [r for r in rows if r['group'] == 'H' and B.blend_rate(r, w) is not None]
BANDS = [(25, 28), (29, 30), (31, 32), (33, 34), (35, 45)]
def X(R, form):
    b = np.array([B.blend_rate(r, w) * r['pt'] for r in R]); u = np.array([B.blend_rate(r, w) * 600 for r in R]); a = np.array([r['age'] - 30.0 for r in R])
    cols = [np.ones(len(R)), b, b * a, u, u * a, a]
    if form == 'Q':
        cols += [b * a * a, u * a * a, a * a]
    if form == 'BAND':
        bd = np.array([1.0 if 31 <= r['age'] <= 32 else 0.0 for r in R]); cols += [b * bd, bd]
    return np.column_stack(cols)
for h in (3, 5):
    use = [r for r in G if r[f'y{h}'] is not None]; Ts = sorted({r['T'] for r in use})
    pred = {f: {} for f in ('M2', 'Q', 'BAND')}; truth = {}; idx = {}
    for T in Ts:
        te = [r for r in use if r['T'] == T]; tr = [r for r in use if r['T'] != T]; y = np.array([r[f'y{h}'] for r in tr])
        truth[T] = np.array([r[f'y{h}'] for r in te]); idx[T] = te
        for f in pred:
            pred[f][T] = X(te, f) @ np.linalg.lstsq(X(tr, f), y, rcond=None)[0]
    print(f'\n== hitters, {h} seasons, T {Ts}: actual / predicted by band and season (players with B > .5)')
    for lo, hi in BANDS:
        per = []
        for T in Ts:
            m = [(p, t) for p, t, r in zip(pred['M2'][T], truth[T], idx[T]) if lo <= r['age'] <= hi and B.blend_rate(r, w) * r['pt'] > .5]
            if m:
                per.append((sum(t for _, t in m) / sum(p for p, _ in m), len(m)))
        rng = np.random.default_rng(0)
        allm = [(p, t, T) for T in Ts for p, t, r in zip(pred['M2'][T], truth[T], idx[T]) if lo <= r['age'] <= hi and B.blend_rate(r, w) * r['pt'] > .5]
        P_, T_ = np.array([x[0] for x in allm]), np.array([x[1] for x in allm])
        bs = [T_[ix].sum() / P_[ix].sum() for ix in (rng.integers(0, len(allm), len(allm)) for _ in range(2000))]
        print(f"  {lo}-{hi}: pooled {T_.sum() / P_.sum():.2f} (SE {np.std(bs):.2f}, n {len(allm)}); by T " + ' '.join(f'{x:.2f}' for x, _ in per) + f"; below 1 in {sum(x < 1 for x, _ in per)}/{len(per)}")
    for a_, b_ in (('Q', 'M2'), ('BAND', 'M2')):
        g, se, wi, n = B.paired_gap(pred[a_], pred[b_], truth)
        rm = [B.rmse(pred[a_][T], truth[T]) - B.rmse(pred[b_][T], truth[T]) for T in Ts]
        print(f'  {a_} v M2: r gap {g:+.4f} (SE {se:.4f}) wins {wi}/{n} -> {B.verdict(g, se, wi, n, a_, "M2")}; rmse change {np.mean(rm):+.4f}, lower in {sum(x < 0 for x in rm)}/{n}')

# Part 2 (added the same day): the miss sits in hitters with a real forecast (B > .5), the pool the lists rank. Fit and score on that pool only,
# defined by the forecast, never by the outcome. M2 fit on everyone v M2, Q and BAND fit on the pool.
print('\n== part 2: pool B > .5 (defined by the forecast)')
for h in (3, 5):
    use = [r for r in G if r[f'y{h}'] is not None]; Ts = sorted({r['T'] for r in use})
    keep = lambda r: B.blend_rate(r, w) * r['pt'] > .5
    pr_ = {k: {} for k in ('ALL', 'M2p', 'Qp', 'BANDp')}; tr_ = {}; old = {}
    for T in Ts:
        te = [r for r in use if r['T'] == T and keep(r)]; trn = [r for r in use if r['T'] != T]; trp = [r for r in trn if keep(r)]
        tr_[T] = np.array([r[f'y{h}'] for r in te]); old[T] = np.array([r['age'] >= 31 for r in te])
        pr_['ALL'][T] = X(te, 'M2') @ np.linalg.lstsq(X(trn, 'M2'), np.array([r[f'y{h}'] for r in trn]), rcond=None)[0]
        for k, f in (('M2p', 'M2'), ('Qp', 'Q'), ('BANDp', 'BAND')):
            pr_[k][T] = X(te, f) @ np.linalg.lstsq(X(trp, f), np.array([r[f'y{h}'] for r in trp]), rcond=None)[0]
    for k in pr_:
        rm = np.mean([B.rmse(pr_[k][T], tr_[T]) for T in Ts]); r_ = np.mean([B.wr(pr_[k][T], tr_[T]) for T in Ts])
        bias = np.mean([float(np.sum(tr_[T][old[T]]) / np.sum(pr_[k][T][old[T]])) for T in Ts])
        print(f'  {h} seasons {k:6s}: r {r_:.3f} rmse {rm:.3f}  actual/predicted age 31+ {bias:.2f}')
    for a_ in ('M2p', 'Qp', 'BANDp'):
        g, se, wi, n = B.paired_gap(pr_[a_], pr_['ALL'], tr_); lo = sum(B.rmse(pr_[a_][T], tr_[T]) < B.rmse(pr_['ALL'][T], tr_[T]) for T in Ts)
        print(f'    {a_} v ALL: r gap {g:+.4f} (SE {se:.4f}) wins {wi}/{n} -> {B.verdict(g, se, wi, n, a_, "ALL")}; lower rmse {lo}/{n}')

# Part 3: the adopted form for the lists (Wally 2026-11-05): M2 fit on the B > .5 pool, every season, written for fa_final_lists.py.
out = {}
for h in (3, 5):
    use = [r for r in G if r[f'y{h}'] is not None and B.blend_rate(r, w) * r['pt'] > .5]
    out[f'H_{h}'] = {'coef': {'M2': np.linalg.lstsq(X(use, 'M2'), np.array([r[f'y{h}'] for r in use]), rcond=None)[0].tolist()}, 'pool': 'B > .5', 'n': len(use)}
    print(f'pool fit {h} seasons, n {len(use)}: ' + ' '.join(f'{x:.3f}' for x in out[f'H_{h}']['coef']['M2']))
import json
json.dump(out, open(os.path.join(B.P, '_fa_age_band_fit.json'), 'w'), indent=1)
