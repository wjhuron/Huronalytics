"""war_battery_honest.py: the 09-05 hdERA channel battery again, with no gate on the TARGET period (2026-11-04). Research only.

war_improve_battery.py and _battery2.py scored candidates on >= 60 / >= 30 IP in BOTH seasons and >= 30 IP in both halves. War_forecast_honest.py and
war_framing_fix.py re-ran the shrink, velocity, xFIP blend and framing. This covers what is left:
  k       K% in the base period                     bb    BB% in the base period            kbb   both
  xrv     per-pitch luck-neutral xRV/100            pull  pulled-air excess per PA (2021-2025; the source has no 2026)
  rg      running game (.45 CS - .20 SB) per 9      wp    (WP + BK) x .25 per 9

Forward test: target ~ hd + z(channel), OLS fit on the OTHER seasons, target-innings weighted, scored on the held-out season, paired bootstrap on fixed
fitted weights. Pools: next season base 30+ IP, rest of season h1 30+ IP. Target above league, raw.
Description test: club RA ~ pitcher RAA + fielding + park + club channel runs. Only rg and wp are in run units, so only they can read a slope of -1. K, BB, xRV
and pull are converted to runs by their LOSO forward weight, so a slope near 0 means no descriptive content beyond hd.

Rules written before the run:
  A channel that only adds forecast is a candidate for hpERA / hpWAR, never for hdWAR: hdWAR is descriptive. It is reported as forecast only.
  hdWAR candidate: same-season description slope more than 2 SE from 0 with the right sign in 4 of 6 seasons, AND no forward loss by the
  war_forecast_honest rule (gap over 2 SE and 4/5, 5/6).
  rg overlaps catcher throwing in FRV; wp overlaps catcher blocking. Those slopes are read next to the catcher term in the same fit.
Usage: python3 scripts/research/era/war_battery_honest.py pull YEAR (2021-2025, one per process), then python3 scripts/research/era/war_battery_honest.py run
Output: data/_war_honest/pull_YEAR.pkl, console + data/_war_honest/battery.json
"""
import contextlib, gc, io, json, os, pickle, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'hitter')); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'projection'))
D = os.path.join(ROOT, 'data'); OUT = os.path.join(D, '_war_honest')
CS_RV, SB_RV, WP_RV = .45, .20, .25


def pull(y):
    import war_improve_battery2 as B2
    df = B2.df_year(y); df = df[df['game_type'] == 'R']; o, s = B2.pull_excess(y, df)
    with open(os.path.join(OUT, f'pull_{y}.pkl.tmp'), 'wb') as f:
        pickle.dump(o, f)
    os.replace(os.path.join(OUT, f'pull_{y}.pkl.tmp'), os.path.join(OUT, f'pull_{y}.pkl')); print(y, len(o), round(s, 3), flush=True)


def run():
    import war_forecast_honest as PH
    import hwar_component_scale as C
    SEASONS = PH.SEASONS; TAB = PH.TAB; FULL = PH.FULL; res = {}
    XRV = json.load(open(os.path.join(D, '_era_xrv100.json')))
    PULL = {y: pickle.load(open(os.path.join(OUT, f'pull_{y}.pkl'), 'rb')) for y in SEASONS if y < 2026}

    def chan(y, pid, half=False):
        t = W_T[str(y)]['pitchers'][pid]; r = t['h1'] if half else t; o = r.get('outs') or 0; bf = r.get('bf') or 0
        if o <= 0 or bf <= 0:
            return None
        x = XRV.get(str(y), {}).get(pid) or {}; p = PULL.get(y, {}).get(pid) or {}; pa = bf
        return dict(k=r['so'] / bf, bb=r['bb'] / bf, xrv=x.get('h1' if half else 'full'), rg=(CS_RV * r.get('cs', 0) - SB_RV * r.get('sb', 0)) * 27 / o, wp=WP_RV * (r.get('wp', 0) + r.get('bk', 0)) * 27 / o,
                    pull=(p.get('h1' if half else 'full', 0.0) / pa) if y in PULL else None)
    W_T = PH.W.T

    def zs(pool, half):
        """{y: {name: array of within-season z}} for the pool's pitchers."""
        o = {}
        for y in pool:
            cols = defaultdict(list)
            for p in pool[y]['ids']:
                c = chan(y, p, half) or {}
                for n in ('k', 'bb', 'xrv', 'rg', 'wp', 'pull'):
                    cols[n].append(c.get(n) if c.get(n) is not None else np.nan)
            z = {}
            for n, v in cols.items():
                a = np.array(v, float); mu, sd = np.nanmean(a) if np.isfinite(a).any() else 0.0, np.nanstd(a) if np.isfinite(a).any() else 1.0
                z[n] = (a - mu) / sd if sd > 0 else a * 0
            o[y] = z
        return o

    def forward(pool, tab, need, label):
        print(f'\n== FORWARD: {label}; A = hd + channel, LOSO, B = hd alone'); y_, w_ = PH.ys(pool); h = PH.col(pool, tab, 'hd'); Z = zs(pool, label.startswith('rest')); out = {}
        for name, chs in (('k', ['k']), ('bb', ['bb']), ('kbb', ['k', 'bb']), ('xrv', ['xrv']), ('rg', ['rg']), ('wp', ['wp']), ('pull', ['pull']), ('all but pull', ['k', 'bb', 'xrv', 'rg', 'wp'])):
            yrs = [y for y in pool if all(np.isfinite(Z[y][c]).sum() > 30 for c in chs)]; a = {}; wt = {}; b = {y: h[y] for y in yrs}
            for y in yrs:
                X, Y, Wg = [], [], []
                for s in yrs:
                    if s == y:
                        continue
                    M = np.column_stack([np.array(h[s], float)] + [Z[s][c] for c in chs]); m = np.isfinite(M).all(axis=1); X.append(M[m]); Y.append(np.array(y_[s], float)[m]); Wg.append(np.array(w_[s], float)[m])
                X, Y, Wg = np.vstack(X), np.concatenate(Y), np.concatenate(Wg); A = np.column_stack([np.ones(len(Y)), X]) * np.sqrt(Wg)[:, None]; bb = np.linalg.lstsq(A, Y * np.sqrt(Wg), rcond=None)[0]
                M = np.column_stack([np.array(h[y], float)] + [np.nan_to_num(Z[y][c]) for c in chs]); a[y] = (bb[0] + M @ bb[1:]).tolist(); wt[y] = bb[1:].tolist()
            p = PH.paired(a, b, {y: y_[y] for y in yrs}, {y: w_[y] for y in yrs}); PH.show(name, p, need if len(yrs) >= 5 else max(need - 1, 1), ('fix', 'hd'))
            print('      mean weights (hd, channels): ' + ' '.join(f'{v:+.3f}' for v in np.mean(list(wt.values()), axis=0))); out[name] = dict(p, weights=np.mean(list(wt.values()), axis=0).tolist())
        return out
    npool = PH.next_pool(30); rpool, rtab = PH.ros_pool()
    res['next'] = forward(npool, FULL, 4, 'next season, 30+ IP'); res['ros'] = forward(rpool, rtab, 5, 'rest of season, 30+ IP')
    res['next60'] = forward(PH.next_pool(60), FULL, 4, 'next season, 60+ IP')

    print('\n== DESCRIPTION: club RA, season intercepts; slope on the club channel in runs. rg and wp: a real uncounted run reads -1 (rg) / +1 (wp, a cost)')
    idx = {(r['y'], r['club']): r for r in C.ROWS}
    wts = {n: res['next'][n]['weights'][1] for n in ('k', 'bb', 'xrv', 'pull')}
    for y in SEASONS:
        _, sh = C.shares(y)
        for r in C.ROWS:
            if r['y'] == y:
                for n in ('c_k', 'c_bb', 'c_xrv', 'c_pull', 'c_rg', 'c_wp'):
                    r[n] = 0.0
        vals = {}
        for p in sh:
            if p in W_T[str(y)]['pitchers']:
                c = chan(y, p)
                if c:
                    vals[p] = c
        for n in ('k', 'bb', 'xrv', 'pull'):
            a = np.array([vals[p][n] if vals[p][n] is not None else np.nan for p in vals], float)
            if not np.isfinite(a).any():
                continue
            mu, sd = np.nanmean(a), np.nanstd(a)
            for p in vals:
                v = vals[p][n]
                if v is None:
                    continue
                ip = TAB[y][p]['outs'] / 3 if p in TAB[y] else 0.0; run = wts[n] * (v - mu) / sd * ip / 9; tot = sum(sh[p].values())
                for c_, m in sh[p].items():
                    if (y, c_) in idx:
                        idx[(y, c_)]['c_' + n] += run * m / tot
        lgo = sum(t['outs'] for t in TAB[y].values()); lg_rg = sum((CS_RV * t.get('cs', 0) - SB_RV * t.get('sb', 0)) for t in W_T[str(y)]['pitchers'].values()) / lgo; lg_wp = sum(WP_RV * (t.get('wp', 0) + t.get('bk', 0)) for t in W_T[str(y)]['pitchers'].values()) / lgo
        for p in sh:
            t = W_T[str(y)]['pitchers'].get(p)
            if not t:
                continue
            tot = sum(sh[p].values()); a_rg = CS_RV * t.get('cs', 0) - SB_RV * t.get('sb', 0) - lg_rg * t['outs']; a_wp = WP_RV * (t.get('wp', 0) + t.get('bk', 0)) - lg_wp * t['outs']
            for c_, m in sh[p].items():
                if (y, c_) in idx:
                    idx[(y, c_)]['c_rg'] += a_rg * m / tot; idx[(y, c_)]['c_wp'] += a_wp * m / tot
    res['desc'] = {}
    for n in ('c_rg', 'c_wp', 'c_k', 'c_bb', 'c_xrv'):
        res['desc'][n] = C.fit('ra', ['praa', 'nonc', 'catch', n, 'park'], label=f'{n}')
    res['desc']['c_pull'] = C.fit('ra', ['praa', 'nonc', 'catch', 'c_pull', 'park'], rows=[r for r in C.ROWS if r['y'] < 2026], label='c_pull (2021-2025)')
    res['desc']['rg_wp'] = C.fit('ra', ['praa', 'nonc', 'catch', 'c_rg', 'c_wp', 'park'], label='rg and wp together')
    with open(os.path.join(OUT, 'battery.json.tmp'), 'w') as f:
        json.dump(res, f, indent=1, default=float)
    os.replace(os.path.join(OUT, 'battery.json.tmp'), os.path.join(OUT, 'battery.json')); print('\nwrote data/_war_honest/battery.json')


if __name__ == '__main__':
    if sys.argv[1] == 'pull':
        pull(int(sys.argv[2]))
    else:
        run()
