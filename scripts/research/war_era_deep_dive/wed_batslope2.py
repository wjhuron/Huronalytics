"""wed_batslope2.py - the shrink target for hitter hdWAR batting runs: which form of mu(PA), and which N0.

wed_batslope.py showed that shrinking every hitter toward the league mean over-credits low-PA hitters. Production
needs a form it can fit live each run, also early in a season. Forms, each fitted on the season's own hitters,
PA weighted:  league (shipped), bands (PA-band means, interpolated on log PA), log (a + b log PA),
log2 (quadratic in log PA). Scopes: the full season, and the first half alone (what a mid-season run sees).
Read-outs per form and N0: the club-runs slope on batting runs (full season only), the calibration slope of
actual wOBA on the shrunk rate for all hitters and by PA group, and the same-season r with actual wOBA.
PYTHONHASHSEED=0 .venv/bin/python scripts/research/war_era_deep_dive/wed_batslope2.py"""
import sys, os, json, io, contextlib
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'hitter')); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'era')); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'projection'))
import hwar_component_scale as CS
HH = CS.HH; SEASONS = CS.SEASONS
RAW = {sc: {y: HH.rates(y, sc, 0) for y in SEASONS} for sc in ('full', 'h1')}


def mu_of(a, form):
    n = a['n'].clip(lower=1); lg = float(np.average(a['xhb'], weights=a['n'])); ln = np.log(n)
    if form == 'league':
        return pd.Series(lg, index=a.index)
    if form == 'bands':
        qs = np.unique(np.quantile(a['n'], [0, .35, .55, .7, .8, .9, 1.0])); cx, cy = [], []
        for lo, hi in zip(qs[:-1], qs[1:]):
            m = (a['n'] >= lo) & (a['n'] <= hi)
            if m.sum() >= 5:
                cx.append(np.log(np.average(a['n'][m], weights=a['n'][m]))); cy.append(float(np.average(a['xhb'][m], weights=a['n'][m])))
        return pd.Series(np.interp(ln, cx, cy), index=a.index)
    X = np.column_stack([np.ones(len(a)), ln] + ([ln ** 2] if form == 'log2' else [])); sw = np.sqrt(a['n'].values)
    b = np.linalg.lstsq(X * sw[:, None], a['xhb'].values * sw, rcond=None)[0]
    return pd.Series(X @ b, index=a.index)


def variant(sc, form, n0):
    out = {}
    for y in SEASONS:
        a = RAW[sc][y]; mu = mu_of(a, form); out[y] = pd.DataFrame(dict(n=a['n'], sh=(a['n'] * a['xhb'] + n0 * mu) / (a['n'] + n0), woba=a['woba']))
    return out


def club(V):
    rows = []
    for y in SEASONS:
        b, _p = CS.shares(y); a = V[y]; sc = HH.SCALE[y]; L = float(np.average(a['sh'], weights=a['n'])); C = defaultdict(float)
        for pid, r in a.iterrows():
            for c, v in CS.spread(str(pid), (r['sh'] - L) * r['n'] / sc, b).items():
                C[c] += v
        rows += [dict(r, bat=C.get(r['club'], 0.0)) for r in CS.ROWS if r['y'] == y]
    with contextlib.redirect_stdout(io.StringIO()):
        f = CS.fit('rs', ['bat', 'bsr', 'park'], rows=rows)
    return f['slopes']['bat']['b'], f['slopes']['bat']['se'], f['rmse']


def cal(V, lo=1, hi=10 ** 6):
    out = []
    for hold in SEASONS:
        x, yv, w = [], [], []
        for y in SEASONS:
            if y != hold:
                a = V[y]; m = (a['n'] >= lo) & (a['n'] < hi)
                x += list((a['sh'] - np.average(a['sh'], weights=a['n']))[m]); yv += list((a['woba'] - np.average(a['woba'], weights=a['n']))[m]); w += list(a['n'][m])
        x, yv, w = np.array(x), np.array(yv), np.array(w, float); out.append(float((w * x * yv).sum() / (w * x * x).sum()))
    return float(np.mean(out))


def rr(V, lo):
    return float(np.mean([np.corrcoef(V[y]['sh'][V[y]['n'] >= lo], V[y]['woba'][V[y]['n'] >= lo])[0, 1] for y in SEASONS]))


res = {}
for sc, groups in (('full', ((300, 10 ** 6), (100, 300), (1, 100))), ('h1', ((150, 10 ** 6), (50, 150), (1, 50)))):
    print(f"\n== scope {sc}: form | N0 |" + (" club slope (SE) rmse |" if sc == 'full' else "") + " calibration all | " + " | ".join(f"{lo}-{hi if hi < 10**6 else '+'} PA" for lo, hi in groups) + " | r with actual wOBA (PA >= %d)" % groups[0][0])
    for form in ('league', 'bands', 'log', 'log2'):
        for n0 in ((77,) if form == 'league' else (30, 40, 50, 60, 70, 77, 90, 110)):
            V = variant(sc, form, n0); line = f" {form:6s} | {n0:3d} |"
            if sc == 'full':
                b, se, rm = club(V); line += f" {b:.3f} ({se:.3f}) {rm:.2f} |"; res[f'{form} {n0} club'] = (b, se, rm)
            line += f" {cal(V):.3f} | " + " | ".join(f"{cal(V, lo, hi):.3f}" for lo, hi in groups) + f" | {rr(V, groups[0][0]):.4f}"
            print(line, flush=True)
json.dump(res, open(os.path.join(ROOT, 'data', '_wed', 'res_batslope2.json'), 'w'), indent=1)
