"""war_xrv_wp_size.py: size the two channels that passed the war_battery_honest.py description rule (2026-11-04). Research only.

xRV: RAA_b = (1 - w) RAA + w x (-xRV runs, recentered), xRV runs = xRV/100 x pitches / 100. Sweep w 0..1. Objective: club RA rmse (with fielding and park) must bracket an interior minimum and
win most seasons against w = 0. Forward: rate blend on honest next and rest of season, must not lose by the war_forecast_honest rule. Reads actual results on takes and whiffs, so moving toward it is partly a move toward results on non-contact pitches; contact stays priced by xwOBA.
WP + BK: RAA_w = RAA - k x (runs above league), k 0..2. Club slope objective already measured (+2.12 +/- .93); size only, plus catcher-blocking overlap.
Usage: PYTHONHASHSEED=0 python3 scripts/research/era/war_xrv_wp_size.py
Output: console + data/_war_honest/xrv_wp.json
"""
import contextlib, io, json, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'hitter')); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'projection'))
from pipeline.eraplus import WAR_RAA_SCALE
import war_forecast_honest as PH
import hwar_component_scale as C
SE = PH.SEASONS; TAB = PH.TAB; FULL = PH.FULL; LG = PH.LG; res = {}; X = json.load(open(os.path.join(ROOT, 'data', '_era_xrv100.json'))); OUT = os.path.join(ROOT, 'data', '_war_honest')
idx = {(r['y'], r['club']): r for r in C.ROWS}
XR = {}
for y in SE:
    t = {}
    for p, r in FULL[y].items():
        v = X.get(str(y), {}).get(p)
        if v and v.get('full') is not None and r['ip'] > 0:
            t[p] = -v['full'] * v['n_full'] / 100      # pitcher-positive runs
    m = sum(t.values()) / sum(FULL[y][p]['ip'] for p in t); XR[y] = {p: t[p] - m * FULL[y][p]['ip'] for p in t}
    print(f'{y}: {len(t)} arms, sd xRV runs {np.std(list(XR[y].values())):.1f}, r with hd RAA {np.corrcoef([XR[y][p] for p in t if FULL[y][p]["hd"] is not None], [WAR_RAA_SCALE * (LG[y]["ra9"] - FULL[y][p]["hd"]) * FULL[y][p]["ip"] / 9 for p in t if FULL[y][p]["hd"] is not None])[0, 1]:.3f}')
    _, sh = C.shares(y)
    for r in C.ROWS:
        if r['y'] == y:
            r['xr'] = 0.0
    for p, v in XR[y].items():
        s = sh.get(p)
        if s:
            tot = sum(s.values())
            for c, n in s.items():
                if (y, c) in idx:
                    idx[(y, c)]['xr'] += v * n / tot
print('\n== xRV BLEND, club RA rmse by w, per season and mean')
GRID = [i / 10 for i in range(11)]; A = []
for w in GRID:
    for r in C.ROWS:
        r['pb'] = (1 - w) * r['praa'] + w * r['xr']
    per = []
    for y in SE:
        with contextlib.redirect_stdout(io.StringIO()):
            f = C.fit('ra', ['pb', 'nonc', 'catch', 'park'], rows=[r for r in C.ROWS if r['y'] == y])
        per.append(f['rmse'])
    with contextlib.redirect_stdout(io.StringIO()):
        f = C.fit('ra', ['pb', 'nonc', 'catch', 'park'])
    A.append(per); print(f"  w {w:.1f}: pooled rmse {f['rmse']:.1f}, pitcher slope {f['slopes']['pb']['b']:+.2f}, catcher {f['slopes']['catch']['b']:+.2f}  per season " + ' '.join(f'{v:.1f}' for v in per))
A = np.array(A); print('  best w per season: ' + ' '.join(str(GRID[int(A[:, j].argmin())]) for j in range(A.shape[1])) + f'; w .5 beats w 0 in {int((A[5] < A[0]).sum())}/6')
res['rmse'] = A.tolist()
print('\n== xRV BLEND, honest forward; rate blended on the runs-per-9 scale, A = blend, B = hd')
def rate_b(y, p, w, hd):
    v = XR[y].get(p)
    if v is None or hd is None:
        return hd if hd is not None else np.nan
    return (1 - w) * hd + w * (LG[y]['ra9'] - v * 9 / FULL[y][p]['ip'] / WAR_RAA_SCALE)
npool = PH.next_pool(30); ny, nw = PH.ys(npool); h = PH.col(npool, FULL, 'hd')
for w in (.2, .4, .6):
    a = {y: [rate_b(y, p, w, FULL[y][p]['hd']) for p in npool[y]['ids']] for y in npool}; q = PH.paired(a, h, ny, nw); PH.show(f'next 30+, w {w}', q, 4, ('blend', 'hd')); res[f'next_{w}'] = q
print('\n== WP + BK size, 2026, pitchers 100+ IP')
t = PH.W.T['2026']['pitchers']; o = sum(v['outs'] for v in t.values()); lg = sum(.25 * (v.get('wp', 0) + v.get('bk', 0)) for v in t.values()) / o; rpw = LG[2026]['rpw']
d = {p: (.25 * (v.get('wp', 0) + v.get('bk', 0)) - lg * v['outs']) / rpw for p, v in t.items() if v['outs'] >= 300}; a = np.array(list(d.values())); print(f'  at k = 1: sd {a.std():.2f} WAR, range {a.min():.2f} to {a.max():.2f}, n {len(a)}; at the measured k = 2.1: sd {2.12 * a.std():.2f}, range {2.12 * a.min():.2f} to {2.12 * a.max():.2f}')
res['wp'] = dict(sd=float(a.std()), lo=float(a.min()), hi=float(a.max()))
print('\n== SHIPPED hpWAR totals for 2027 against the pool')
h = json.load(open(os.path.join(ROOT, 'data', 'hpwar_projections.json')))
for s, share in (('hitters', 570), ('pitchers', 430)):
    v = [r['tot'] for r in h[s].values() if r.get('tot') is not None]; print(f'  {s}: sum of hpWAR total {sum(v):.0f} over {len(v)} players, against a pool share of {share}, before the players not yet in MLB')
json.dump(res, open(os.path.join(OUT, 'xrv_wp.json'), 'w'), indent=1, default=float)
