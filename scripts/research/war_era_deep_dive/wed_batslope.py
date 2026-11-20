"""wed_batslope.py - WAR/ERA deep dive, test 6: why hitter hdWAR batting runs read 1.15 at club level.

Known (2026-11-04): club runs scored on club batting runs has slope .96 with no shrink, 1.03 at N0 25 and 1.15 at
the shipped N0 77; in wins the slope is 1.00 +/- .10. Hypothesis: the shrink target is the LEAGUE mean, but hitters
with few PA are worse than league (playing time follows talent), so shrinking them up over-credits thin hitters and
compresses club totals. Candidate: shrink toward the mean for the hitter's own PA level, mu(PA), a same-season
(descriptive) quantity. Reports the club-level slope and the player-level calibration slope for each form.
PYTHONHASHSEED=0 .venv/bin/python scripts/research/war_era_deep_dive/wed_batslope.py"""
import sys, os, json
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'hitter')); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'era')); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'projection'))
import hwar_component_scale as CS
HH = CS.HH; SEASONS = CS.SEASONS
RAW = {y: HH.rates(y, 'full', 0) for y in SEASONS}       # park-adjusted, unshrunk: n, xhb, woba


def mu_of_pa(a, form):
    lg = float(np.average(a['xhb'], weights=a['n']))
    if form == 'league':
        return pd.Series(lg, index=a.index)
    # PA-weighted mean of xhb in PA bands, linear interpolation on log PA between band centres
    edges = [1, 20, 50, 100, 200, 350, 500, 800]; cx, cy = [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (a['n'] >= lo) & (a['n'] < hi)
        if m.sum() >= 5:
            cx.append(np.log(np.average(a['n'][m], weights=a['n'][m]))); cy.append(float(np.average(a['xhb'][m], weights=a['n'][m])))
    return pd.Series(np.interp(np.log(a['n'].clip(lower=1)), cx, cy), index=a.index)


def variant(form, n0):
    out = {}
    for y in SEASONS:
        a = RAW[y]; mu = mu_of_pa(a, form); sh = (a['n'] * a['xhb'] + n0 * mu) / (a['n'] + n0)
        out[y] = pd.DataFrame(dict(n=a['n'], sh=sh, woba=a['woba'], mu=mu))
    return out


def club_slope(V):
    rows = []
    for y in SEASONS:
        b, _p = CS.shares(y); a = V[y]; sc = HH.SCALE[y]; L = float(np.average(a['sh'], weights=a['n'])); C = defaultdict(float)
        for pid, r in a.iterrows():
            for c, v in CS.spread(str(pid), (r['sh'] - L) * r['n'] / sc, b).items():
                C[c] += v
        for r in CS.ROWS:
            if r['y'] == y:
                x = dict(r); x['bat'] = C.get(r['club'], 0.0); rows.append(x)
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        f = CS.fit('rs', ['bat', 'bsr', 'park'], rows=rows); w = CS.fit('wab', ['bat', 'bsr', 'fld', 'praa'], rows=rows, scale={'bat', 'bsr', 'fld', 'praa'})
    return f['slopes']['bat'], f['rmse'], w['slopes']['bat']


def player_slope(V, lo=1, hi=10 ** 6):
    """PA-weighted slope of actual wOBA on the shrunk rate, both above league, fitted leaving each season out.
    lo / hi restrict the hitters by season PA (the league means stay those of all hitters)."""
    out = []
    for hold in SEASONS:
        x, yv, w = [], [], []
        for y in SEASONS:
            if y == hold:
                continue
            a = V[y]; m = (a['n'] >= lo) & (a['n'] < hi)
            x += list((a['sh'] - np.average(a['sh'], weights=a['n']))[m]); yv += list((a['woba'] - np.average(a['woba'], weights=a['n']))[m]); w += list(a['n'][m])
        x, yv, w = np.array(x), np.array(yv), np.array(w, float); out.append(float((w * x * yv).sum() / (w * x * x).sum()))
    return float(np.mean(out))


def main():
    print("mean xhb above league by PA band (PA weighted, six seasons): " + " ".join(
        f"{lo}-{hi}:{1000*np.mean([float(np.average(RAW[y]['xhb'][(RAW[y]['n']>=lo)&(RAW[y]['n']<hi)], weights=RAW[y]['n'][(RAW[y]['n']>=lo)&(RAW[y]['n']<hi)]) - np.average(RAW[y]['xhb'], weights=RAW[y]['n'])) for y in SEASONS]):+.1f}"
        for lo, hi in ((1, 50), (50, 150), (150, 300), (300, 500), (500, 800))) + "  (wOBA points x1000)")
    print("\nform | N0 | club runs slope on batting (SE; per season) | club rmse | club WINS slope (SE) | player calibration slope (1.0 = calibrated)")
    res = {}
    for form in ('league', 'pa'):
        for n0 in (0, 10, 15, 25, 40, 50, 77, 100, 150):
            V = variant(form, n0); s, rm, ws = club_slope(V); ps_ = player_slope(V)
            print(f" {form:6s} | {n0:3d} | {s['b']:+.3f} (SE {s['se']:.3f}; " + " ".join(f"{v:+.2f}" for v in s['per']) + f") | {rm:.1f} | {ws['b']:+.3f} (SE {ws['se']:.3f}) | {ps_:.3f} | 300+ PA {player_slope(V, 300):.3f} | 100-300 PA {player_slope(V, 100, 300):.3f} | under 100 {player_slope(V, 1, 100):.3f}", flush=True)
            res[f'{form} {n0}'] = dict(club=s['b'], se=s['se'], rmse=rm, wins=ws['b'], wins_se=ws['se'], player=ps_)
    json.dump(res, open(os.path.join(ROOT, 'data', '_wed', 'res_batslope.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
