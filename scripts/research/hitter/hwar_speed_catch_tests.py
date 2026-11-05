"""hwar_speed_catch_tests.py: the two flags from hwar_component_scale.py, tested directly (2026-11-04). Research only.

FLAG 1, catcher fielding: club RA on pitcher RAA + non-catcher + catcher reads catcher about 0. Hypothesis: framed strikes already sit
in the pitcher's K and BB, so xwOBA against carries them and hdWAR credits them to pitcher and catcher both.
  Test: drop pitcher RAA. A double count predicts catcher near -1 without it and near 0 with it. FanGraphs Fielding as the reference.
FLAG 2, speed: with xhb batting, baserunning reads 2.29 per run against 1.21 with wOBA batting. Hypothesis: xhb misses what speed does on
contact, and baserunning takes that credit.
  Measure: (actual - xhb) per BIP on same-season sprint speed, ground balls and air balls, LOSO. Term: rate + k x (LOSO slope) x (sprint - league) x BIP share.
  Objectives, written before the run: club RS slopes and rmse (description); same-season calibration of wOBA on the rate, and bias by sprint
  tercile (description); honest next and rest of season (forward check). k = 0, .5, 1, 1.5, 2, 3.
Usage: python3 ... build YEAR (one season per process), then python3 ... run
Output: data/_war_honest/speed_YEAR.pkl, console + data/_war_honest/speed_catch.json
"""
import csv, gc, json, os, pickle, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'era')); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'projection'))
D = os.path.join(ROOT, 'data'); OUT = os.path.join(D, '_war_honest')


def build(y):
    import hwar_hitter_rate_validation as HR
    import war_improve_battery2 as B2, era_battery_build as EB, war_pullair_fixed as PX
    from pipeline.utils import NON_PA_EVENTS, AAA_TEAMS
    if y < 2026:
        df = B2.df_year(y); df = df[df['game_type'] == 'R']
        d = df[df['events'].notna()][['batter', 'game_date', 'events', 'bb_type', 'launch_angle', 'hc_x', 'hc_y', 'stand', 'game_pk', 'estimated_woba_using_speedangle']].copy(); del df; gc.collect()
        d['ev'] = d['events'].map(EB.EVENT_MAP); d = d[d['ev'].notna() & ~d['ev'].isin(NON_PA_EVENTS) & ~d['ev'].isin(PX.EXCL)]
        P, _ = HR.pa_savant(y); bbt = d['bb_type'].astype(object).values
        assert len(P) == len(d)
    else:
        ids = {}
        for r in json.load(open(os.path.join(D, 'hitter_leaderboard_rs.json'))):
            if r.get('team') not in AAA_TEAMS and r.get('mlbId'):
                ids.setdefault(r['hitter'], set()).add(int(r['mlbId']))
        nm = {n for n, s in ids.items() if len(s) == 1}
        R = pickle.load(open(os.path.join(D, 'all_pitches_rs_cache.pkl'), 'rb'))
        rows = [p.get('BBType') for p in R if p.get('_source', 'MLB') == 'MLB' and p.get('BTeam') not in AAA_TEAMS and p.get('Event') and p.get('Event') not in NON_PA_EVENTS and p.get('Event') not in PX.EXCL and p.get('Batter') in nm]
        del R; gc.collect()
        P, _ = HR.pa_sheet(y); bbt = np.array(rows, dtype=object)
        assert len(P) == len(bbt)
    t = pd.Series(bbt).astype(str).str.lower()
    P['gb'] = t.str.contains('ground').values; P['air'] = (t.str.contains('fly') | t.str.contains('line') | t.str.contains('pop')).values
    P['r'] = P['woba'] - P['xhb']
    out = {}
    for sc, m in (('full', np.ones(len(P), bool)), ('h1', P['h1'].values)):
        g = P[m]; a = pd.DataFrame({'n': g.groupby('bid').size()})
        for c in ('gb', 'air'):
            s = g[g[c]]; a[f'{c}_n'] = s.groupby('bid').size(); a[f'{c}_r'] = s.groupby('bid')['r'].sum()
        out[sc] = a.fillna(0.0)
    with open(os.path.join(OUT, f'speed_{y}.pkl.tmp'), 'wb') as f:
        pickle.dump(out, f)
    os.replace(os.path.join(OUT, f'speed_{y}.pkl.tmp'), os.path.join(OUT, f'speed_{y}.pkl'))
    print(y, 'batters', len(out['full']), 'gb', int(out['full']['gb_n'].sum()), 'air', int(out['full']['air_n'].sum()), flush=True)


def sprint(y):
    fn = os.path.join(D, '_proj', f'sprint_{y}.csv'); out = {}
    if os.path.exists(fn):
        with open(fn, encoding='utf-8-sig') as f:
            rd = csv.DictReader(f); key = 'player_id' if 'player_id' in rd.fieldnames else rd.fieldnames[1]
            for r in rd:
                if r.get('sprint_speed') not in (None, ''):
                    out[str(int(r[key]))] = float(r['sprint_speed'])
    return out


def run():
    import hwar_component_scale as C
    import hwar_forecast_honest as HH
    SEASONS = C.SEASONS; res = {}
    print('== FLAG 1: CATCHER FIELDING, club RA, season intercepts')
    res['with_p'] = C.fit('ra', ['praa', 'nonc', 'catch', 'park'], label='with pitcher RAA')
    res['no_p'] = C.fit('ra', ['nonc', 'catch', 'park'], label='without pitcher RAA')
    res['catch_only_praa'] = None
    rows = C.ROWS; x = np.array([r['catch'] for r in rows]); y = np.array([r['praa'] for r in rows]); ys = np.array([r['y'] for r in rows])
    for u in set(ys):
        x[ys == u] -= x[ys == u].mean(); y[ys == u] -= y[ys == u].mean()
    b = (x * y).sum() / (x * x).sum(); se = np.sqrt(((y - b * x) ** 2).sum() / (len(x) - 7) / (x * x).sum())
    print(f'  club pitcher RAA on club catcher fielding runs: slope {b:+.2f} +/- {se:.2f} (a full double count reads about +1)'); res['catch_only_praa'] = dict(b=float(b), se=float(se))
    print('  reference: FanGraphs Fielding split at catchers, same model')
    for r in rows:
        r['fg_c'] = 0.0; r['fg_n'] = 0.0
    idx = {(r['y'], r['club']): r for r in rows}
    for y_ in SEASONS:
        b_, _ = C.shares(y_)
        for pid, f in C.FG[y_].items():
            v = float(f.get('Fielding') or 0.0); k = 'fg_c' if (C.FRV[y_].get(pid) or {}).get('catching') is not None else 'fg_n'
            for c, x_ in C.spread(pid, v, b_).items():
                if (y_, c) in idx:
                    idx[(y_, c)][k] += x_
    res['fg_with_p'] = C.fit('ra', ['praa', 'fg_n', 'fg_c', 'park'], label='FanGraphs Fielding, with pitcher RAA')
    print('  outfield without Coors')
    res['of_nocol'] = C.fit('ra', ['praa', 'inf', 'of', 'catch', 'park'], rows=[r for r in rows if r['club'] != 115], label='no COL')

    print('\n== WHY batting reads 1.15: club RS slope on xhb batting by shrink, with baserunning in')
    res['n0'] = {}
    for n0 in (0, 25, 77, 150, 300):
        for r in rows:
            r['bat_n'] = 0.0
        for y_ in SEASONS:
            a = HH.rates(y_, n0=n0); L = float(np.average(a['xhb'], weights=a['n'])); b_, _ = C.shares(y_)
            for pid, q in a.iterrows():
                for c, v in C.spread(str(pid), (q['xhb'] - L) * q['n'] / HH.SCALE[y_], b_).items():
                    if (y_, c) in idx:
                        idx[(y_, c)]['bat_n'] += v
        res['n0'][n0] = C.fit('rs', ['bat_n', 'bsr', 'park'], label=f'N0 {n0}')

    print('\n== FLAG 2: SPEED. actual - xhb per BIP on sprint speed, per ft/s')
    S = {y: pickle.load(open(os.path.join(OUT, f'speed_{y}.pkl'), 'rb')) for y in SEASONS}; SP = {y: sprint(y) for y in SEASONS}
    print('  sprint coverage: ' + ' '.join(f'{y}:{len(SP[y])}' for y in SEASONS))
    if not SP[2026]:
        for r in json.load(open(os.path.join(D, 'hitter_leaderboard_rs.json'))):
            v = r.get('sprintSpeed') or r.get('sprint_speed')
            if r.get('mlbId') and v:
                SP[2026][str(r['mlbId'])] = float(v)
        print(f'  2026 sprint from the leaderboard: {len(SP[2026])}')
    slopes = {}
    for y_ in SEASONS:
        f = S[y_]['full']; s = pd.Series(SP[y_]).reindex(f.index); m = s.notna() & (f['n'] >= 50)
        lg = float(np.average(s[m], weights=f.loc[m, 'n'])); slopes[y_] = {'lg': lg}
        for c in ('gb', 'air'):
            n = f.loc[m, f'{c}_n']; rr = f.loc[m, f'{c}_r'] - n * (f.loc[m, f'{c}_r'].sum() / n.sum()); x_ = s[m] - lg
            slopes[y_][c] = float((x_ * rr).sum() / (n * x_ * x_).sum())
    for c in ('gb', 'air'):
        print(f'  {c:3s} per season ' + ' '.join(f'{slopes[y_][c]:+.4f}' for y_ in SEASONS) + f'  mean {np.mean([slopes[y_][c] for y_ in SEASONS]):+.4f}')
    res['slopes'] = slopes
    loso = {y_: {c: float(np.mean([slopes[o][c] for o in SEASONS if o != y_])) for c in ('gb', 'air')} for y_ in SEASONS}

    def term(y_, sc, k):
        f = S[y_][sc]; s = pd.Series(SP[y_]).reindex(f.index); x_ = (s - slopes[y_]['lg']).fillna(0.0)
        return k * x_ * (loso[y_]['gb'] * f['gb_n'] + loso[y_]['air'] * f['air_n']) / f['n']

    KS = [0, .5, 1, 1.5, 2, 3]; res['k'] = {}
    npool = HH.next_pool(150); rpool = HH.ros_pool(); ny, nw = HH.yw(npool); ry, rw = HH.yw(rpool)
    for k in KS:
        for r in rows:
            r['bat_k'] = 0.0
        cal, bias = [], []
        tabs = {}
        for y_ in SEASONS:
            a = HH.FULL[y_].copy(); a['xhb'] = a['xhb'] + term(y_, 'full', k).reindex(a.index).fillna(0.0); tabs[y_] = a; L = float(np.average(a['xhb'], weights=a['n'])); b_, _ = C.shares(y_)
            for pid, q in a.iterrows():
                for c, v in C.spread(str(pid), (q['xhb'] - L) * q['n'] / HH.SCALE[y_], b_).items():
                    if (y_, c) in idx:
                        idx[(y_, c)]['bat_k'] += v
            g = a[a['n'] >= 300]; cal.append(float(np.polyfit(g['xhb'].values, g['raw_woba'].values, 1)[0]))
            s = pd.Series(SP[y_]).reindex(g.index); e = (g['raw_woba'] - g['raw_woba'].mean()) - (g['xhb'] - g['xhb'].mean()); hi = s >= s.quantile(2 / 3); lo = s <= s.quantile(1 / 3); bias.append(float(e[hi].mean() - e[lo].mean()))
        th = {y_: HH.H1[y_].assign(xhb=HH.H1[y_]['xhb'] + term(y_, 'h1', k).reindex(HH.H1[y_].index).fillna(0.0)) for y_ in SEASONS}
        n_ = [HH.wr(tabs[y_].loc[npool[y_]['ids'], 'xhb'].values, ny[y_], nw[y_]) for y_ in npool]; r_ = [HH.wr(th[y_].loc[rpool[y_]['ids'], 'xhb'].values, ry[y_], rw[y_]) for y_ in rpool]
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            f_ = C.fit('rs', ['bat_k', 'bsr', 'park'])
        print(f"  k {k:3}: club bat {f_['slopes']['bat_k']['b']:.2f} bsr {f_['slopes']['bsr']['b']:.2f} +/- {f_['slopes']['bsr']['se']:.2f} rmse {f_['rmse']:.1f} | calib {np.mean(cal):.3f} | fast minus slow bias {np.mean(bias):+.4f} (" + ' '.join(f'{v:+.3f}' for v in bias) + f") | next {np.mean(n_):.4f} ros {np.mean(r_):.4f}", flush=True)
        res['k'][k] = dict(club=f_, cal=cal, bias=bias, next=n_, ros=r_)
    # who moves at k=1, 2026
    t = term(2026, 'full', 1); a = HH.FULL[2026]; g = a[a['n'] >= 400].index; runs = (t.reindex(g) * a.loc[g, 'n'] / HH.SCALE[2026]); print(f'  size at k=1, 2026, 400+ PA: sd {runs.std():.2f} runs, range {runs.min():.1f} to {runs.max():.1f}')
    res['size'] = dict(sd=float(runs.std()), lo=float(runs.min()), hi=float(runs.max()))
    with open(os.path.join(OUT, 'speed_catch.json.tmp'), 'w') as f:
        json.dump(res, f, indent=1, default=float)
    os.replace(os.path.join(OUT, 'speed_catch.json.tmp'), os.path.join(OUT, 'speed_catch.json'))
    print('\nwrote data/_war_honest/speed_catch.json')


if __name__ == '__main__':
    if sys.argv[1] == 'build':
        build(int(sys.argv[2]))
    else:
        run()
