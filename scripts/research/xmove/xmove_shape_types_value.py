#!/usr/bin/env python3
"""xmove_shape_types_value.py — the results test for the name-free shape-type expectation.

xmove_shape_types.py showed on 2026 that the shape-type model is rename-proof and keeps
sweepers apart from curveballs. Not shown there: whether its ARROW (actual minus expected)
still explains results, whether the number of types K is stable across seasons, and how far
the expectation moves when pitches really change group. Three modes, 2021-2025.

  value    Same protocol as xmove_agnostic_v2.py. Every form is cross-fit by game parity
           inside a season: the group traits, the mixture and the type fits all come from one
           half of the games, the other half is scored. Units are pitcher x type x hand x
           season (50+ pitches, 20+ swings); outcome ~ arrow is fit on four seasons and scored
           on the fifth. Forms: S shipped per type, F1 tag families, T<K> shape types.
           Reported: the residual-only r, the r with raw movement added, and the GUARD (slot,
           extension, velocity and raw movement given: what does the arrow still add?).
           NOTE the half-season build: group traits come from half a season (15+ pitches), so
           the types are a little more blurred than a full-season production build.
  k        K stability. BIC per season on full-season groups (30+ pitches), three seeds, and
           a held-out read: the mixture fit on one season, mean log-likelihood on each other.
  regroup  2025, full season. A pitcher's sliders are split in two and one half is called a
           sweeper: (a) a RANDOM half, (b) the half with the most sweep. The mixture and the
           type fits stay fixed; only the group traits move. Expectation shift per pitcher,
           against the shipped per-type model on the same relabel.

  XMOVE_DIR=/scratch PYTHONHASHSEED=0 .venv/bin/python scripts/research/xmove/xmove_shape_types_value.py value
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import xmove_residual_value as RV  # noqa: E402
import xmove_pertype_ladder as LAD  # noqa: E402
import xmove_hitter_basis_candidates as HC  # noqa: E402

SEASONS, PTS = RV.SEASONS, RV.PTS
OUT = os.path.join(ROOT, 'data', '_xmove_shape_types_value.json')
KS = (6, 7, 8, 9, 10, 12, 15)
MIN_GROUP = 30
MIN_W = 150.0
NB = 300
TRAITS = ('dv', 'ivb', 'hb_s')


def arrays():
    d = pd.concat([HC.load(y) for y in SEASONS], ignore_index=True)
    d = d[d['Pitch Type'].isin(PTS) & d['Throws'].isin(['L', 'R'])]
    d = d.dropna(subset=['xIndVrtBrk', 'xHorzBrk', 'Velocity', 'Extension', 'ArmAngle', 'SpinAxis', 'Spin Rate', 'KinEff',
                         'RelPosZ', 'RelPosX']).reset_index(drop=True)
    A = LAD.to_arrays(d)
    ps = pd.Series(A['pitcher']).astype(str) + '|' + pd.Series(A['season']).astype(str)
    A['dv'] = A['velo'] - pd.Series(A['velo']).groupby(ps.values).transform(lambda s: s.quantile(0.95)).values
    A['grp'] = pd.factorize(ps + '|' + pd.Series(A['thr']) + '|' + pd.Series(A['pt']))[0]
    return d, A


def traits(A, idx, min_n, grp=None):
    g = A['grp'][idx] if grp is None else grp[idx]
    t = pd.DataFrame({'g': g, **{c: A[c][idx] for c in TRAITS}}).groupby('g').agg(n=('dv', 'size'), **{c: (c, 'mean') for c in TRAITS})
    return t[t['n'] >= min_n]


def mixture(T, K, seed=0, n_init=3):
    from sklearn.mixture import GaussianMixture
    X = T[list(TRAITS)].values
    mu, sd = X.mean(0), X.std(0)
    return GaussianMixture(n_components=K, covariance_type='full', n_init=n_init, random_state=seed).fit((X - mu) / sd), mu, sd


def shares_of(M, T):
    gm, mu, sd = M
    return pd.DataFrame(gm.predict_proba((T[list(TRAITS)].values - mu) / sd), index=T.index)


def type_fits(A, idx, R, grp=None):
    """Weighted least squares per shape type and hand; weight = the pitch's group share."""
    g = A['grp'][idx] if grp is None else grp[idx]
    pos = pd.Series(np.arange(len(R)), index=R.index).reindex(g).values
    ok = np.isfinite(pos)
    idx, W = idx[ok], R.values[pos[ok].astype(int)]
    X = LAD.design(A, LAD.B0, idx)
    co = {}
    for hand in ('L', 'R'):
        m = A['thr'][idx] == hand
        for k in range(W.shape[1]):
            w = W[m, k]
            if w.sum() < MIN_W:
                continue
            sw = np.sqrt(w)
            Xw = X[m] * sw[:, None]
            co[(k, hand)] = (np.linalg.lstsq(Xw, A['ivb'][idx][m] * sw, rcond=None)[0], np.linalg.lstsq(Xw, A['hb_s'][idx][m] * sw, rcond=None)[0])
    return co


def score(A, idx, R, co, grp=None):
    g = A['grp'][idx] if grp is None else grp[idx]
    pos = pd.Series(np.arange(len(R)), index=R.index).reindex(g).values
    ok = np.isfinite(pos)
    xi, xh = np.full(len(idx), np.nan), np.full(len(idx), np.nan)
    ix = idx[ok]
    W = R.values[pos[ok].astype(int)]
    X = LAD.design(A, LAD.B0, ix)
    si, sh, tot = np.zeros(len(ix)), np.zeros(len(ix)), np.zeros(len(ix))
    for (k, hand), (bi, bh) in co.items():
        m = A['thr'][ix] == hand
        si[m] += W[m, k] * (X[m] @ bi)
        sh[m] += W[m, k] * (X[m] @ bh)
        tot[m] += W[m, k]
    good = tot > 0.5                      # a skipped thin type: renormalise over the types that were fit
    xi[np.where(ok)[0][good]], xh[np.where(ok)[0][good]] = si[good] / tot[good], sh[good] / tot[good]
    return xi, xh


def shape_cv(A, K):
    n = len(A['ivb'])
    xi, xh = np.full(n, np.nan), np.full(n, np.nan)
    par = A['game'] % 2
    for yr in SEASONS:
        for p in (0, 1):
            tr, te = np.where((A['season'] == yr) & (par == p))[0], np.where((A['season'] == yr) & (par == 1 - p))[0]
            T = traits(A, tr, MIN_GROUP // 2)
            R = shares_of(mixture(T, K), T)
            xi[te], xh[te] = score(A, te, R, type_fits(A, tr, R))
    return xi, xh


def value():
    d, A = arrays()
    res = {'S SHIPPED per type': LAD.fit_cv(A, LAD.B0)}
    tagfam = {'FF': 'H', 'SI': 'H', 'FC': 'H', 'SL': 'B', 'ST': 'B', 'CU': 'B', 'CH': 'O', 'FS': 'O'}
    A2 = dict(A)
    A2['gid'] = pd.factorize(pd.Series([tagfam[t] for t in A['pt']]) + '_' + pd.Series(A['thr']) + '_' + pd.Series(A['season']).astype(str))[0]
    res['F1 tag families'] = LAD.fit_cv(A2, LAD.B0)
    del A2
    for K in KS:
        res[f'T{K} shape types'] = shape_cv(A, K)
        print(f'K = {K} fitted', flush=True)
    names = list(res)
    ok = np.all([np.isfinite(res[n][0]) for n in names], axis=0)
    print(f'{ok.mean():.1%} of pitches scored by every form', flush=True)
    d = d[ok].reset_index(drop=True)
    s = np.where(d['Throws'] == 'R', 1.0, -1.0)
    d['ivb'], d['hb'] = d['xIndVrtBrk'], d['xHorzBrk'] * s
    for n in names:
        d[f'oi_{n}'], d[f'oh_{n}'] = d['ivb'] - res[n][0][ok], d['hb'] - res[n][1][ok]
    d['swing'] = d['Description'].isin(RV.SWINGS).astype(float)
    d['whiff'] = d['Description'].isin(RV.WHIFFS).astype(float)
    agg = {'n': ('ivb', 'size'), 'ivb': ('ivb', 'mean'), 'hb': ('hb', 'mean'), 'swings': ('swing', 'sum'), 'whiffs': ('whiff', 'sum'),
           'rv': ('RunExp', 'mean'), 'aa': ('ArmAngle', 'mean'), 'ext': ('Extension', 'mean'), 'velo': ('Velocity', 'mean')}
    for n in names:
        agg[f'oi_{n}'], agg[f'oh_{n}'] = (f'oi_{n}', 'mean'), (f'oh_{n}', 'mean')
    u = d.groupby(['Pitcher', 'Pitch Type', 'Throws', 'season']).agg(**agg).reset_index()
    u = u[(u.n >= 50) & (u.swings >= 20)].copy().reset_index(drop=True)
    u['whiff_rate'] = u.whiffs / u.swings
    print(f'{len(d):,} pitches, {len(u):,} units\n')
    ptv = u['Pitch Type'].values

    def preds(feats, y):
        p = pd.Series(np.nan, index=u.index)
        for pt in PTS:
            b = u[u['Pitch Type'] == pt]
            for yr in SEASONS:
                tr, te = b[b.season != yr], b[b.season == yr]
                if len(tr) < 60 or len(te) < 20:
                    continue
                X = np.column_stack([np.ones(len(tr))] + [tr[f].values for f in feats])
                beta = np.linalg.lstsq(X, tr[y].values, rcond=None)[0]
                p.loc[te.index] = np.column_stack([np.ones(len(te))] + [te[f].values for f in feats]) @ beta
        return p.values

    def tmr(p, y, ix=None):
        rs = []
        for pt in PTS:
            m = np.where((ptv == pt) & np.isfinite(p))[0] if ix is None else ix[(ptv[ix] == pt) & np.isfinite(p[ix])]
            if len(m) > 30:
                rs.append(np.corrcoef(p[m], u[y].values[m])[0, 1])
        return float(np.mean(rs))

    rng = np.random.default_rng(0)
    boots = [rng.integers(0, len(u), len(u)) for _ in range(NB)]
    REF = names[0]
    base = ['aa', 'ext', 'velo', 'ivb', 'hb']
    kinds = {'res': lambda n: [f'oi_{n}', f'oh_{n}'], 'raw': lambda n: ['ivb', 'hb', f'oi_{n}', f'oh_{n}'],
             'guard': lambda n: base + [f'oi_{n}', f'oh_{n}']}
    P = {(n, y, k): preds(f(n), y) for n in names for y in ('whiff_rate', 'rv') for k, f in kinds.items()}
    out = {}
    for y, lab in (('whiff_rate', 'WHIFF RATE'), ('rv', 'RUN VALUE')):
        b0 = tmr(preds(base, y), y)
        print(f'{lab}: out-of-season r, mean over pitch types (delta against the shipped form, bootstrap se). '
              f'Guard base (slot, extension, velocity, raw movement, no arrow): {b0:.3f}')
        print(f'{"form":<22s}{"arrow SD ride/run":>19s}{"r arrow, shipped":>18s} | {"arrow only":>11s}{"vs S (se)":>16s} | {"+ raw move":>11s}{"vs S (se)":>16s} | '
              f'{"guard: adds":>12s}{"vs S (se)":>16s}')
        for n in names:
            rec = out.setdefault(n, {})
            line = (f'{n:<22s}{f"""{u[f"oi_{n}"].std():.2f} / {u[f"oh_{n}"].std():.2f}""":>19s}'
                    f'{f"""{np.corrcoef(u[f"oi_{n}"], u[f"oi_{REF}"])[0, 1]:.2f} / {np.corrcoef(u[f"oh_{n}"], u[f"oh_{REF}"])[0, 1]:.2f}""":>18s} | ')
            for k in kinds:
                r = tmr(P[(n, y, k)], y)
                d0 = r - tmr(P[(REF, y, k)], y)
                se = float(np.std([tmr(P[(n, y, k)], y, ix) - tmr(P[(REF, y, k)], y, ix) for ix in boots]))
                rec[f'{y}_{k}'] = (r, d0, se)
                line += f'{(f"{r - b0:+.3f}" if k == "guard" else f"{r:.3f}"):>{12 if k == "guard" else 11}s}{f"{d0:+.3f} ({se:.3f})":>16s} | '
            print(line, flush=True)
        print('   per season, arrow-only r minus shipped: ' + '   '.join(
            f'{n.split()[0]} ' + ' '.join(f'{tmr(np.where(u.season.values == yr, P[(n, y, "res")], np.nan), y) - tmr(np.where(u.season.values == yr, P[(REF, y, "res")], np.nan), y):+.3f}'
                                          for yr in SEASONS) for n in names[1:]))
        print('   per pitch type, arrow-only r (' + ' '.join(PTS) + '):')
        for n in names:
            rs = [np.corrcoef(P[(n, y, 'res')][(ptv == pt) & np.isfinite(P[(n, y, 'res')])], u[y].values[(ptv == pt) & np.isfinite(P[(n, y, 'res')])])[0, 1] for pt in PTS]
            print(f'      {n:<22s}' + ' '.join(f'{x:>6.2f}' for x in rs))
        print()
    json.dump(out, open(OUT + '.tmp', 'w'), indent=1)
    os.replace(OUT + '.tmp', OUT)
    print(f'wrote {OUT}')


def kstab():
    _, A = arrays()
    grid = (4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 16)
    T = {yr: traits(A, np.where(A['season'] == yr)[0], MIN_GROUP) for yr in SEASONS}
    print('BIC by season (full-season groups, 30+ pitches), best of three seeds; * = the minimum')
    print(f'{"K":>4s}' + ''.join(f'{yr:>10d}' for yr in SEASONS))
    bic = {}
    for K in grid:
        for yr in SEASONS:
            X = T[yr][list(TRAITS)].values
            best = np.inf
            for seed in (0, 1, 2):
                gm, mu, sd = mixture(T[yr], K, seed)
                best = min(best, gm.bic((X - mu) / sd))
            bic[(K, yr)] = best
    for K in grid:
        print(f'{K:>4d}' + ''.join(f'{bic[(K, yr)]:>9.0f}{"*" if bic[(K, yr)] == min(bic[(k, yr)] for k in grid) else " "}' for yr in SEASONS), flush=True)
    print('groups: ' + ', '.join(f'{yr} {len(T[yr])}' for yr in SEASONS))
    print('\nheld out: mixture fit on one season, mean log-likelihood per group on each OTHER season (mean of 20 pairs, and the worst pair)')
    for K in grid:
        ll = []
        for a in SEASONS:
            gm, mu, sd = mixture(T[a], K, 0)
            ll += [gm.score((T[b][list(TRAITS)].values - mu) / sd) for b in SEASONS if b != a]
        print(f'{K:>4d}  mean {np.mean(ll):.4f}   worst {np.min(ll):.4f}', flush=True)


def regroup(K=9, yr=2025):
    _, A = arrays()
    idx = np.where(A['season'] == yr)[0]
    T = traits(A, idx, MIN_GROUP)
    M = mixture(T, K)
    R = shares_of(M, T)
    co = type_fits(A, idx, R)
    xi0, xh0 = score(A, idx, R, co)
    # shipped per-type coefficients of the season, for the same relabel
    ship = {}
    for pt in ('SL', 'ST'):
        for hand in ('L', 'R'):
            m = idx[(A['pt'][idx] == pt) & (A['thr'][idx] == hand)]
            X = LAD.design(A, LAD.B0, m)
            ship[(pt, hand)] = (np.linalg.lstsq(X, A['ivb'][m], rcond=None)[0], np.linalg.lstsq(X, A['hb_s'][m], rcond=None)[0])
    gkey = pd.Series(A['pitcher'][idx]).astype(str) + '|' + pd.Series(A['thr'][idx])
    is_sl, is_st = A['pt'][idx] == 'SL', A['pt'][idx] == 'ST'
    rng = np.random.default_rng(0)
    print(f'{yr}, K = {K}: half of a pitcher\'s sliders are called sweepers (pitchers with 100+ sliders). Shift of the mean expectation, inches (ride, run combined)')
    for mode in ('random half', 'the half with the most sweep'):
        grp = A['grp'].copy()
        nxt = grp.max() + 1
        moved = np.zeros(len(idx), bool)
        rows = []
        for pk, pos in pd.Series(np.arange(len(idx))).groupby(gkey.values):
            pos = pos.values
            sl = pos[is_sl[pos]]
            if len(sl) < 100:
                continue
            pick = rng.permutation(sl)[:len(sl) // 2] if mode.startswith('random') else sl[np.argsort(A['hb_s'][idx[sl]])[:len(sl) // 2]]
            st = pos[is_st[pos]]
            tgt = grp[idx[st[0]]] if len(st) else nxt
            nxt += 0 if len(st) else 1
            grp[idx[pick]] = tgt
            moved[pick] = True
            rows.append((pk, sl, pick, st))
        T2 = traits(A, idx, MIN_GROUP, grp)
        xi1, xh1 = score(A, idx, shares_of(M, T2), co, grp)
        rec = {'moved': [], 'stay': [], 'old ST': [], 'ship moved': []}
        for pk, sl, pick, st in rows:
            stay = np.setdiff1d(sl, pick)
            for lab, ii in (('moved', pick), ('stay', stay), ('old ST', st)):
                if len(ii) >= 30 and np.isfinite(xi0[ii]).all() and np.isfinite(xi1[ii]).all():
                    rec[lab].append(np.hypot(xi1[ii].mean() - xi0[ii].mean(), xh1[ii].mean() - xh0[ii].mean()))
            hand = A['thr'][idx[pick[0]]]
            X = LAD.design(A, LAD.B0, idx[pick])
            rec['ship moved'].append(np.hypot((X @ ship[('ST', hand)][0]).mean() - (X @ ship[('SL', hand)][0]).mean(),
                                              (X @ ship[('ST', hand)][1]).mean() - (X @ ship[('SL', hand)][1]).mean()))
        print(f'  {mode} ({len(rows)} pitchers):')
        for lab, nm in (('moved', 'SHAPE: the sliders now called sweepers'), ('stay', 'SHAPE: the sliders still called sliders'),
                        ('old ST', 'SHAPE: the sweepers he had before'), ('ship moved', 'SHIPPED: the sliders now called sweepers')):
            v = np.array(rec[lab])
            if len(v):
                print(f'     {nm:<42s} n {len(v):>4d}   median {np.median(v):.2f}   90th pct {np.quantile(v, .9):.2f}   max {v.max():.2f}')


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'value'
    {'value': value, 'k': kstab, 'regroup': regroup}[mode]()
