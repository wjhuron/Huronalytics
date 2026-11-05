"""hwar_component_scale.py: do hitting, baserunning and fielding each carry their weight in club results? (2026-11-04)

Extends hwar_team_harness.py, which had no baserunning before 2026 and one fielding slope. Six seasons, 180 club-seasons.
History baserunning is FanGraphs BaseRunning (UBR + wSB + wGDP, the closest match to hBsrRuns; Savant history is not cached).
2026 also runs on the shipped hBsrRuns as a check.

    RS_ab = bat + bsr + park                   batting on xhb, and on wOBA as the reference
    RA_ab = pRAA + fld + park                  fld split: non-catcher / catcher; infield / outfield / catcher; framing / other catching
    W_ab  = (bat + bsr + fld + pRAA) / RPW     wins above .294 x games on each part, one slope per part
Season intercepts; a slope of 1 means one run in the metric is one run on the scoreboard. A framing slope under the other
fielding slopes would show framing counted twice, because framed strikes already sit in the pitcher's K and BB.
Then, position players at 300+ PA in the base season: spread per 600 PA, share of hdWAR variance on shipped 2026, and year-to-year
r with no target gate (target PA weighted).
Usage: PYTHONHASHSEED=0 python3 scripts/research/hitter/hwar_component_scale.py
Output: console + data/_war_honest/components.json
"""
import json, os, pickle, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'era')); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'projection'))
from pipeline.eraplus import WAR_RAA_SCALE
from pipeline.utils import TEAM_ABBREV_TO_ID
import war_rate_validation as W
import war_forecast_honest as PH
import hwar_forecast_honest as HH

SEASONS = W.SEASONS; D = os.path.join(ROOT, 'data'); OUT = os.path.join(D, '_war_honest'); IN = HH.IN
HL = json.load(open(os.path.join(D, 'hitter_leaderboard_rs.json'))); PL = json.load(open(os.path.join(D, 'pitcher_leaderboard_rs.json')))
FG = {y: {str(int(r['xMLBAMID'])): r for r in json.load(open(os.path.join(D, '_proj', 'fg', f'actual_{y}_bat.json'))) if r.get('xMLBAMID')} for y in SEASONS}
FRV = {y: json.load(open(os.path.join(D, '_proj', f'frv_{y}.json'))) for y in SEASONS}


def standings(y):
    if y == 2026:
        return {int(k): v for k, v in json.load(open(os.path.join(D, '_hwar_team', 'standings_2026_by_id.json'))).items()}
    st = json.load(open(os.path.join(D, '_hwar_team', f'standings_{y}.json')))
    return {t['team']['id']: dict(w=t['wins'], l=t['losses'], rs=t['runsScored'], ra=t['runsAllowed'], g=t['wins'] + t['losses']) for rec in st['records'] for t in rec['teamRecords']}


def shares(y):
    b, p = defaultdict(dict), defaultdict(dict)
    if y < 2026:
        for (k, c), n in IN[y]['bclub'].items():
            b[str(k)][int(c)] = int(n)
        for (k, c), n in IN[y]['pclub'].items():
            p[str(k)][int(c)] = int(n)
        return b, p
    for r in HL:
        c = TEAM_ABBREV_TO_ID.get(r.get('team')); t = str(r.get('team'))
        if c and r.get('mlbId') and t not in ('ROC', 'AAA') and not t.endswith('TM') and r.get('pa'):
            b[str(r['mlbId'])][int(c)] = int(r['pa'])
    for r in PL:
        c = TEAM_ABBREV_TO_ID.get(r.get('team')); t = str(r.get('team'))
        if c and r.get('mlbId') and t not in ('ROC', 'AAA') and not t.endswith('TM') and r.get('tbf'):
            p[str(r['mlbId'])][int(c)] = int(r['tbf'])
    return b, p


def spread(tab, val, shr, fallback=None):
    tot = shr.get(tab)
    if tot:
        s = sum(tot.values())
        return {c: val * n / s for c, n in tot.items()}
    return {int(fallback): val} if fallback else {}


def build(y):
    b, p = shares(y); C = defaultdict(lambda: defaultdict(float)); a = HH.FULL[y]; sc = HH.SCALE[y]
    Lx = float(np.average(a['xhb'], weights=a['n'])); Lw = float(np.average(a['woba'], weights=a['n']))
    for pid, r in a.iterrows():
        for c, v in spread(str(pid), (r['xhb'] - Lx) * r['n'] / sc, b).items():
            C[c]['bat'] += v
        for c, v in spread(str(pid), (r['woba'] - Lw) * r['n'] / sc, b).items():
            C[c]['bat_w'] += v
    for pid, r in FG[y].items():
        for c, v in spread(pid, float(r.get('BaseRunning') or 0.0), b).items():
            C[c]['bsr'] += v
    for pid, v in FRV[y].items():
        tot = float(v.get('total') or 0.0); rng = float(v.get('range') or 0.0) + float(v.get('arm') or 0.0) + float(v.get('dp') or 0.0)
        o = v.get('outs_by_pos') or {}; io = sum(o.get(k, 0) for k in '3456'); oo = sum(o.get(k, 0) for k in '789')
        catch = float(v.get('catching') or 0.0); rest = tot - catch; fr = float(v.get('framing') or 0.0)
        for name, val in (('fld', tot), ('catch', catch), ('frame', fr), ('catch_o', catch - fr), ('nonc', rest), ('inf', rest * io / (io + oo) if io + oo else 0.0), ('of', rest * oo / (io + oo) if io + oo else 0.0)):
            for c, x in spread(pid, val, b, v.get('team_id')).items():
                C[c][name] += x
    lg = PH.LG[y]; f = PH.FULL[y]; ids = [k for k, r in f.items() if r['hd'] is not None and r['ip'] > 0]; ipw = sum(f[k]['ip'] for k in ids); shift = lg['ra9'] - sum(f[k]['hd'] * f[k]['ip'] for k in ids) / ipw
    for k in ids:
        for c, v in spread(k, WAR_RAA_SCALE * (lg['ra9'] - (f[k]['hd'] + shift)) * f[k]['ip'] / 9, p).items():
            C[c]['praa'] += v
    st = standings(y); rows = []; rsg = sum(v['rs'] for v in st.values()) / sum(v['g'] for v in st.values()); pf = W.PF.get(str(y), {})
    for c, v in st.items():
        x = dict(C[c]); x.update(y=y, club=c, rs=v['rs'] - rsg * v['g'], ra=v['ra'] - rsg * v['g'], wab=v['w'] - .294 * v['g'], park=((pf.get(str(c), 100) / 100 + 1) / 2 - 1) * rsg * v['g'], rpw=lg['rpw'])
        rows.append(x)
    return rows


ROWS = [r for y in SEASONS for r in build(y)]


def fit(ycol, xcols, rows=None, scale=None, label=None):
    rows = rows or ROWS; ys = sorted({r['y'] for r in rows}); X, Y = [], []
    for y in ys:
        g = [r for r in rows if r['y'] == y]; xx = np.array([[r.get(k, 0.0) / (r['rpw'] if scale and k in scale else 1.0) for k in xcols] for r in g]); yy = np.array([r[ycol] for r in g], float)
        X.append(xx - xx.mean(axis=0)); Y.append(yy - yy.mean())
    X, Y = np.vstack(X), np.concatenate(Y); b = np.linalg.lstsq(X, Y, rcond=None)[0]; e = Y - X @ b; dof = len(Y) - X.shape[1] - len(ys); s2 = (e ** 2).sum() / dof; se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))
    per = {}
    for y in ys:
        g = [r for r in rows if r['y'] == y]; xx = np.array([[r.get(k, 0.0) / (r['rpw'] if scale and k in scale else 1.0) for k in xcols] for r in g]); yy = np.array([r[ycol] for r in g], float)
        A = np.column_stack([np.ones(len(yy)), xx]); per[y] = np.linalg.lstsq(A, yy, rcond=None)[0][1:].tolist()
    out = {k: dict(b=float(v), se=float(s), per=[per[y][i] for y in ys]) for i, (k, v, s) in enumerate(zip(xcols, b, se))}; rmse = float(np.sqrt(s2))
    print(f'  {label or ycol}: rmse {rmse:.1f}')
    for k, v in out.items():
        print(f"     {k:8s} {v['b']:+.2f} +/- {v['se']:.2f}   per season " + ' '.join(f'{x:+.2f}' for x in v['per']))
    return dict(rmse=rmse, slopes=out)


def wr(x, y, w):
    return PH.wr(x, y, w)


def main():
    res = {}
    print('== CLUB RUNS SCORED')
    res['rs_bat'] = fit('rs', ['bat', 'park'], label='xhb batting, no baserunning')
    res['rs_bat_bsr'] = fit('rs', ['bat', 'bsr', 'park'], label='xhb batting + baserunning')
    res['rs_woba_bsr'] = fit('rs', ['bat_w', 'bsr', 'park'], label='wOBA batting + baserunning (reference; results on results)')
    print('\n== CLUB RUNS ALLOWED')
    res['ra_fld'] = fit('ra', ['praa', 'fld', 'park'], label='pitcher RAA + all fielding')
    res['ra_c'] = fit('ra', ['praa', 'nonc', 'catch', 'park'], label='non-catcher / catcher')
    res['ra_pos'] = fit('ra', ['praa', 'inf', 'of', 'catch', 'park'], label='infield / outfield / catcher')
    res['ra_frame'] = fit('ra', ['praa', 'nonc', 'frame', 'catch_o', 'park'], label='framing separate')
    print('\n== WINS ABOVE .294, one slope per part, in wins')
    res['w'] = fit('wab', ['bat', 'bsr', 'fld', 'praa', 'park'], scale={'bat', 'bsr', 'fld', 'praa', 'park'}, label='all parts')

    print('\n== SHIPPED 2026 hdWAR, position players 300+ PA: spread and share of variance (cov(part, total) / var(total))')
    seen = {}
    for r in HL:
        t = str(r.get('team'))
        if t in ('ROC', 'AAA') or not r.get('mlbId') or r.get('hWAR') is None:
            continue
        if t.endswith('TM') or r['mlbId'] not in seen:
            seen[r['mlbId']] = r
    S = [r for r in seen.values() if (r.get('pa') or 0) >= 300]; rp = 9.6534
    tot = np.array([sum(r[k] for k in ('hBatRuns', 'hBsrRuns', 'hFldRuns', 'hPosRuns', 'hReplRuns')) for r in S]); res['share'] = {}
    for k in ('hBatRuns', 'hBsrRuns', 'hFldRuns', 'hPosRuns', 'hReplRuns'):
        v = np.array([r[k] for r in S]); per = v * 600 / np.array([r['pa'] for r in S]); sh = float(np.cov(v, tot)[0, 1] / tot.var(ddof=1))
        print(f'  {k:10s} sd {v.std():5.1f} runs ({v.std() / rp:.2f} WAR), sd per 600 {per.std():5.1f}, share of variance {100 * sh:5.1f}%'); res['share'][k] = dict(sd=float(v.std()), share=sh)

    print('\n== YEAR TO YEAR, base 300+ PA, target any PA, target PA weighted, per 600 PA')
    res['yoy'] = {}
    for name, get in (('batting xhb', lambda y, b: (HH.FULL[y].loc[b, 'xhb'] - HH.LG[y]['full']['xhb']) * 600 / HH.SCALE[y] if b in HH.FULL[y].index else None),
                      ('batting wOBA', lambda y, b: (HH.FULL[y].loc[b, 'woba'] - HH.LG[y]['full']['woba']) * 600 / HH.SCALE[y] if b in HH.FULL[y].index else None),
                      ('baserunning FG', lambda y, b: float(FG[y][b]['BaseRunning'] or 0.0) * 600 / FG[y][b]['PA'] if b in FG[y] and FG[y][b].get('PA') else None),
                      ('fielding FRV', lambda y, b: float((FRV[y].get(b) or {}).get('total') or 0.0) * 600 / HH.FULL[y].loc[b, 'n'] if b in HH.FULL[y].index else None)):
        rr = []
        for y in SEASONS[:-1]:
            a = HH.FULL[y]; ids = [b for b in a.index[a['n'] >= 300] if b in HH.FULL[y + 1].index]; x = [get(y, b) for b in ids]; t = [get(y + 1, b) for b in ids]; w = [float(HH.FULL[y + 1].loc[b, 'n']) for b in ids]
            rr.append(wr([np.nan if v is None else v for v in x], [np.nan if v is None else v for v in t], w))
        print(f"  {name:16s} r {np.mean(rr):.3f}  (" + ' '.join(f'{v:.2f}' for v in rr) + ')'); res['yoy'][name] = rr

    print('\n== 2026 CHECK: shipped hBsrRuns against FanGraphs BaseRunning, and shipped hFldRuns against FanGraphs Fielding, 300+ PA')
    a = np.array([r['hBsrRuns'] for r in S]); b = np.array([float((FG[2026].get(str(r['mlbId'])) or {}).get('BaseRunning') or 0.0) for r in S]); c = np.array([r['hFldRuns'] for r in S]); d = np.array([float((FG[2026].get(str(r['mlbId'])) or {}).get('Fielding') or 0.0) for r in S])
    print(f'  baserunning r {np.corrcoef(a, b)[0, 1]:.3f}, sd {a.std():.1f} v {b.std():.1f}; fielding r {np.corrcoef(c, d)[0, 1]:.3f}, sd {c.std():.1f} v {d.std():.1f}')
    with open(os.path.join(OUT, 'components.json.tmp'), 'w') as f:
        json.dump(res, f, indent=1, default=float)
    os.replace(os.path.join(OUT, 'components.json.tmp'), os.path.join(OUT, 'components.json'))
    print('\nwrote data/_war_honest/components.json')


if __name__ == '__main__':
    main()
