"""fa_rank_age_check.py: is the multi-year form in fa_rank_blend.py calibrated at old ages? (2026-11-05). Research only.
Bins held-out predicted against actual cumulative WAR by age. Then tests an older-age kink: M4 adds B x k and R x k with k = max(age - K, 0), K swept. A kink must win by the fa_rank_blend rule.
Usage: PYTHONHASHSEED=0 python3 scripts/research/projection/fa_rank_age_check.py
"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fa_rank_blend as B
FIXED = {'H': (.5, .5, 0), 'SP': (.5, .5, 0), 'RP': (.5, 0, .5)}
BIN = [(25, 28), (29, 30), (31, 32), (33, 34), (35, 36), (37, 45)]

def D(R, w, form, K=None):
    X = B.design(R, 'M2', w)
    if form == 'M2':
        return X
    k = np.array([max(r['age'] - K, 0.0) for r in R]); Bv = np.array([B.blend_rate(r, w) * r['pt'] for r in R]); U = np.array([B.blend_rate(r, w) * r['unit'] for r in R])
    return np.column_stack([X, Bv * k, U * k, k])

def held(use, h, w, form, K=None):
    pred = {}; idx = {}
    for T in sorted({r['T'] for r in use}):
        te = [r for r in use if r['T'] == T]; tr = [r for r in use if r['T'] != T]
        b = np.linalg.lstsq(D(tr, w, form, K), np.array([r[f'y{h}'] for r in tr]), rcond=None)[0]; pred[T] = D(te, w, form, K) @ b; idx[T] = te
    return pred, idx

out = {}
for side, gs in (('bat', ('H',)), ('pit', ('SP', 'RP'))):
    rows = B.build(side)
    for g in gs:
        w = FIXED[g]; G = [r for r in rows if r['group'] == g and B.blend_rate(r, w) is not None]
        for h in (3, 5):
            use = [r for r in G if r[f'y{h}'] is not None]
            p, ix = held(use, h, w, 'M2'); truth = {T: np.array([r[f'y{h}'] for r in ix[T]]) for T in ix}
            print(f'\n[{g} {h} seasons] by age at T: n, sum 1-season B, predicted, actual (positive-B arms and bats only)')
            for lo, hi in BIN:
                a = [(r, pr) for T in ix for r, pr in zip(ix[T], p[T]) if lo <= r['age'] <= hi and B.blend_rate(r, w) * r['pt'] > .5]
                if a:
                    print(f"  {lo}-{hi}: n {len(a):4d}  B {sum(B.blend_rate(r, w) * r['pt'] for r, _ in a):7.1f}  pred {sum(x for _, x in a):7.1f}  actual {sum(r[f'y{h}'] for r, _ in a):7.1f}")
            best = None
            for K in (30, 31, 32, 33, 34, 35, 36, 37):
                q, _ = held(use, h, w, 'M4', K)
                r_ = float(np.mean([B.wr(q[T], truth[T]) for T in truth])); e = float(np.mean([B.rmse(q[T], truth[T]) for T in truth]))
                old = [(a_, tt) for T in q for a_, tt, r in zip(q[T], truth[T], ix[T]) if r['age'] >= 33]
                eo = B.rmse([x for x, _ in old], [y for _, y in old])
                print(f'  K {K}: r {r_:.4f} rmse {e:.4f} rmse age 33+ {eo:.3f}')
                if best is None or e < best[1]:
                    best = (K, e, q)
            base = float(np.mean([B.rmse(p[T], truth[T]) for T in truth])); old = [(a_, tt) for T in p for a_, tt, r in zip(p[T], truth[T], ix[T]) if r['age'] >= 33]
            print(f'  M2: r {np.mean([B.wr(p[T], truth[T]) for T in truth]):.4f} rmse {base:.4f} rmse age 33+ {B.rmse([x for x, _ in old], [y for _, y in old]):.3f}')
            g_, se, wi, n = B.paired_gap(best[2], p, truth)
            print(f'  best K {best[0]} v M2 on r: gap {g_:+.4f} (SE {se:.4f}) wins {wi}/{n} -> {B.verdict(g_, se, wi, n, "kink", "M2")}; rmse wins {sum(B.rmse(best[2][T], truth[T]) < B.rmse(p[T], truth[T]) for T in truth)}/{n}')
            aa = [r for r in use]; b = np.linalg.lstsq(D(aa, w, 'M4', best[0]), np.array([r[f'y{h}'] for r in aa]), rcond=None)[0]
            out[f'{g}_{h}'] = dict(K=best[0], coef=b.tolist())
json.dump(out, open(os.path.join(B.P, '_fa_rank_age_check.json'), 'w'), indent=1)
