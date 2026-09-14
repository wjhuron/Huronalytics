"""hwar_team_harness.py — are the hWAR components on the right scale? A team-level check,
2021-2025 rebuilt self-contained, plus the shipped 2026 (2026-09-14).

A component that varies across clubs is identifiable from club runs: its slope on team runs
scored or allowed should be 1.0. Per club-season:

    RS_ab = a + b_bat x batting runs + b_park x park runs                 (+ b_bsr x baserunning, 2026 only)
    RA_ab = a - c_p x pitcher deserved RAA + c_fld x fielding runs + c_park x park runs
    W_ab  = a + d_h x hitter WAR + d_p x pitcher WAR

  RS_ab, RA_ab   runs scored / allowed above the league rate x games (standings feed)
  park runs      ((PF/100 + 1)/2 - 1) x league runs per game x games, the published Savant runs
                 factor at half the games at home (data/park_factors.json). Batting runs already
                 have .35 of it removed and pitcher RAA .67, so the park slopes are not expected
                 at 1 (actual runs move about 1.67x the published factor, 2026-09-05).
  W_ab           wins above .294 x games

Components, rebuilt with the SHIPPED conventions:
  batting runs   per PA xhb (hwar_hitter_rate_validation.finish: Savant xwOBA + the pulled-air
                 term, K 0, BB/HBP at their weights), per-batter rate shrunk at HWAR_N0_BAT toward
                 the league, park at HWAR_PARK_PASS_BAT of the mean venue factor, recentered so the
                 league sums to zero, then every PA carries its batting CLUB, so a traded hitter
                 splits by PA (2026: the shipped club rows). Bunts: the Savant cache prices an
                 unpriced ball in play at 0 (the shipped rate excludes bunt ABs and 2026 prices
                 them at actual); a few runs per club at most.
  pitcher RAA    war_rate_validation.season_table -> hdR9 per pitcher (shrunk xwOBA against at
                 N0_XW, DH_B), park at WAR_PARK_PASS of the stint-club exposure, shift so the
                 innings-weighted league mean is lgRA9; RAA = (lgRA9 - rate) x IP/9, split across
                 clubs by the pitcher's PA share per club.
  fielding runs  Savant FRV total by season (data/_hwar_team/frv_Y.json, the leaderboard embed),
                 a multi-club fielder split by his batting-PA share per club.
  positional     innings by position per player-club (MLB API, data/_hwar_team/innings_Y.json)
                 x HWAR_POS_ADJ / 1458; DH games x 9.
  replacement    both sides pinned to their share of WAR_POOL (hitters per PA, pitchers per inning
                 with the fixed role gap), the shipped rule since 2026-09-14.
  baserunning    Savant serves the current season only, so 2021-2025 carry none (team sd about 7
                 runs against a 35-run residual); 2026 carries the shipped hBsrRuns.
Club resolution for a PA (2021-2025): the schedule gives home and away per gamePk; a player whose
games all share one club is resolved outright; a traded player's PA takes the club that is not the
resolved opponent's, and a PA where both sides are unresolved takes the nearest resolved game of the
same player by date. Counts are reported.

Decision rule: a component is mis-scaled when its pooled slope (season intercepts, n 150) sits more
than 2 SE from 1 AND the same side of 1 in at least 4 of the 5 rebuilt seasons. The remedy would be
a measured multiplier, labeled like the 1.67 park finding, never a refit of the component.

Usage: python3 scripts/research/hitter/hwar_team_harness.py
Output: console + data/_hwar_team_harness.json
"""
import gc, json, os, sys
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'era'))
from pipeline.utils import NON_PA_EVENTS, TEAM_ABBREV_TO_ID
from pipeline.eraplus import WAR_PARK_PASS, WAR_ROLE_GAP, WAR_POOL, WAR_POOL_GAMES, WAR_POOL_SHARE_HITTERS
from pipeline.hwar import HWAR_N0_BAT, HWAR_PARK_PASS_BAT, HWAR_POS_ADJ, HWAR_POS_INNINGS
import war_rate_validation as W
import hwar_hitter_rate_validation as HR
import war_improve_battery2 as B2
import era_battery_build as EB
import war_pullair_fixed as PX

D = os.path.join(ROOT, 'data', '_hwar_team')
SEASONS = [2021, 2022, 2023, 2024, 2025]
PF = W.PF; T = W.T
REPL_PCT = 0.294


def load_games(y):
    s = json.load(open(os.path.join(D, f'schedule_{y}.json')))
    out = {}
    for d in s['dates']:
        for g in d['games']:
            if g.get('status', {}).get('codedGameState') == 'F':
                out[int(g['gamePk'])] = (int(g['teams']['home']['team']['id']), int(g['teams']['away']['team']['id']))
    return out


def load_standings(y):
    if y == 2026:
        return {int(k): v for k, v in json.load(open(os.path.join(D, 'standings_2026_by_id.json'))).items()}
    st = json.load(open(os.path.join(D, f'standings_{y}.json'))); out = {}
    for rec in st['records']:
        for t in rec['teamRecords']:
            out[int(t['team']['id'])] = dict(w=t['wins'], l=t['losses'], rs=t['runsScored'], ra=t['runsAllowed'], g=t['wins'] + t['losses'])
    return out


def pa_table(y, games):
    """Per PA: bid, pid, gamePk, date, and the finish() columns (woba, xw, xhb, pf)."""
    df = B2.df_year(y); df = df[df['game_type'] == 'R']
    d = df[df['events'].notna()][['batter', 'pitcher', 'game_date', 'events', 'bb_type', 'launch_angle', 'hc_x', 'hc_y', 'stand',
                                  'game_pk', 'estimated_woba_using_speedangle']].copy()
    del df; gc.collect()
    d['ev'] = d['events'].map(EB.EVENT_MAP)
    d = d[d['ev'].notna() & ~d['ev'].isin(NON_PA_EVENTS) & ~d['ev'].isin(PX.EXCL)]
    d['game_pk'] = d['game_pk'].astype(int); d = d[d['game_pk'].isin(games.keys())]
    f = lambda c: pd.to_numeric(d[c], errors='coerce').values.astype(float)
    venue = np.array([str(B2.GPK[g]) if g in B2.GPK else None for g in d['game_pk'].values], dtype=object)
    P, _ = HR.finish(y, d['batter'].astype(int).astype(str).values, d['game_date'].astype(str).str[:10].values, d['ev'].values,
                     f('estimated_woba_using_speedangle'), f('launch_angle'), d['bb_type'].values, f('hc_x'), f('hc_y'), d['stand'].values, venue)
    P['pid'] = d['pitcher'].astype(int).astype(str).values; P['gpk'] = d['game_pk'].values; P['date'] = d['game_date'].astype(str).str[:10].values
    return P.reset_index(drop=True)


def resolve_clubs(P, games):
    """Adds bclub / pclub per PA. Returns counts (single-club batters, resolved by opponent, by nearest game, unresolved)."""
    home = np.array([games[g][0] for g in P['gpk'].values]); away = np.array([games[g][1] for g in P['gpk'].values])
    stats = {}
    for side, col in (('bid', 'bclub'), ('pid', 'pclub')):
        club = np.full(len(P), -1, int)
        ids = P[side].values
        for k, idx in P.groupby(side).indices.items():
            cand = set(zip(home[idx], away[idx]))
            common = set.intersection(*[set(c) for c in cand]) if cand else set()
            if len(common) == 1:
                club[idx] = next(iter(common))
        stats[col] = {'single': int((club >= 0).sum())}
        P[col] = club
    # pass 2: a traded player's PA takes the club that is not the resolved opponent's
    for col, other in (('bclub', 'pclub'), ('pclub', 'bclub')):
        m = (P[col].values < 0) & (P[other].values >= 0)
        oth = P[other].values[m]; h = home[m]; a = away[m]
        P.loc[m, col] = np.where(oth == h, a, np.where(oth == a, h, -1))
        stats[col]['by_opponent'] = int(m.sum())
    # pass 3: nearest resolved game of the same player by date
    for side, col in (('bid', 'bclub'), ('pid', 'pclub')):
        n3 = 0
        for k, idx in P.groupby(side).indices.items():
            c = P[col].values[idx]
            if (c >= 0).all() or (c < 0).all():
                continue
            dates = P['date'].values[idx]; order = np.argsort(dates)
            c_sorted = c[order]; known = np.where(c_sorted >= 0)[0]
            for j in np.where(c_sorted < 0)[0]:
                near = known[np.argmin(np.abs(known - j))]; c_sorted[j] = c_sorted[near]; n3 += 1
            P.loc[P.index[idx[order]], col] = c_sorted
        stats[col]['by_nearest'] = n3; stats[col]['unresolved'] = int((P[col].values < 0).sum())
    return stats


def batting_runs(P, y, rpa, scale):
    """Per PA batting runs above average on the shipped rule; returns {club: runs} and the per-batter table."""
    g = P.groupby('bid').agg(xhb=('xhb', 'mean'), n=('xhb', 'size'), pf=('pf', 'mean')); g['pf'] = g['pf'].fillna(1.0)
    lg = float(np.average(g['xhb'], weights=g['n']))
    sh = (g['xhb'] * g['n'] + HWAR_N0_BAT * lg) / (g['n'] + HWAR_N0_BAT)
    adj = sh - HWAR_PARK_PASS_BAT * (g['pf'] - 1.0) * rpa * scale      # mean venue factor: home share is 50% at club level
    L = float(np.average(adj, weights=g['n']))
    per_pa = ((adj - L) / scale).to_dict()
    P['bat_pa'] = P['bid'].map(per_pa).values
    club = P.groupby('bclub')['bat_pa'].sum().to_dict()
    return {int(k): float(v) for k, v in club.items() if k >= 0}, g.assign(adj=adj, runs=(adj - L) * g['n'] / scale)


def pitcher_runs(y, P):
    """Per club: deserved RAA and pitcher WAR (pinned bars); per-pitcher table."""
    rows = W.season_table(y); lg = W.league(rows); pz = W.pool_stats(rows, lg); R = W.rates_full(rows, lg, pz)
    lg_ra9 = lg['ra9']; rpw = lg['rpw']
    ids = [p for p, r in R.items() if r['hdR9'] is not None and r['ip'] > 0]
    dp = {p: R[p]['hdR9'] - WAR_PARK_PASS * (R[p]['exp'] - 1.0) * lg_ra9 for p in ids}
    ipw = sum(R[p]['ip'] for p in ids); shift = lg_ra9 - sum(dp[p] * R[p]['ip'] for p in ids) / ipw
    raa = {p: (lg_ra9 - (dp[p] + shift)) * R[p]['ip'] / 9.0 for p in ids}
    # pinned bars: target = pitcher share of the pool; role gap fixed in runs
    games = load_standings(y); lg_games = sum(v['g'] for v in games.values()) / 2.0
    target = (1.0 - WAR_POOL_SHARE_HITTERS) * WAR_POOL * (lg_games / WAR_POOL_GAMES)
    s = {p: (R[p]['gs'] / R[p]['g'] if R[p]['g'] else 0.0) for p in ids}
    sum_ip9 = sum(R[p]['ip'] / 9.0 for p in ids); sum_rp = sum((1 - s[p]) * R[p]['ip'] / 9.0 for p in ids)
    repl_sp = (target + (WAR_ROLE_GAP / rpw) * sum_rp) / sum_ip9; repl_rp = repl_sp - WAR_ROLE_GAP / rpw
    war = {p: raa[p] / rpw + (repl_rp + (repl_sp - repl_rp) * s[p]) * R[p]['ip'] / 9.0 for p in ids}
    # club shares from the PA table
    cnt = P[P['pclub'] >= 0].groupby(['pid', 'pclub']).size()
    share = defaultdict(dict)
    for (p, c), n in cnt.items():
        share[p][int(c)] = n
    club_raa, club_war = defaultdict(float), defaultdict(float); n_noshare = 0
    for p in ids:
        sh = share.get(p)
        if not sh:
            teams = T[str(y)]['pitchers'][p].get('teams') or []
            if not teams:
                n_noshare += 1; continue
            sh = {int(teams[-1]): 1}
        tot = sum(sh.values())
        for c, n in sh.items():
            club_raa[c] += raa[p] * n / tot; club_war[c] += war[p] * n / tot
    return dict(club_raa=dict(club_raa), club_war=dict(club_war), lg_ra9=lg_ra9, rpw=rpw, repl_sp=repl_sp, repl_rp=repl_rp,
                target=target, lg_games=lg_games, sum_war=sum(war.values()), n=len(ids), n_noshare=n_noshare)


def fielding_and_positional(y, P):
    frv = json.load(open(os.path.join(D, f'frv_{y}.json')))
    cnt = P[P['bclub'] >= 0].groupby(['bid', 'bclub']).size(); bshare = defaultdict(dict)
    for (b, c), n in cnt.items():
        bshare[b][int(c)] = n
    club_fld = defaultdict(float); n_split = 0
    for pid, v in frv.items():
        tot = v.get('total')
        if tot is None:
            continue
        if (v.get('n_teams') or 1) > 1 and bshare.get(pid):
            sh = bshare[pid]; s = sum(sh.values()); n_split += 1
            for c, n in sh.items():
                club_fld[c] += tot * n / s
        elif v.get('team_id') is not None:
            club_fld[int(v['team_id'])] += tot
    inn = json.load(open(os.path.join(D, f'innings_{y}.json')))['stats'][0]['splits']
    club_pos = defaultdict(float); player_pos = defaultdict(float)
    for sp in inn:
        pos = sp.get('position', {}).get('abbreviation'); tid = sp.get('team', {}).get('id')
        if pos not in HWAR_POS_ADJ or tid is None:
            continue
        st = sp['stat']
        if pos == 'DH':
            innings = 9.0 * int(st.get('games') or 0)
        else:
            w, _, f = str(st.get('innings') or '0').partition('.'); innings = int(w) + int(f or 0) / 3.0
        runs = innings * HWAR_POS_ADJ[pos] / HWAR_POS_INNINGS
        club_pos[int(tid)] += runs; player_pos[str(sp['player']['id'])] += runs
    return dict(club_fld), dict(club_pos), n_split, player_pos


def season_2026():
    """The shipped club rows: components straight from the leaderboards."""
    H = json.load(open(os.path.join(ROOT, 'data', 'hitter_leaderboard_rs.json'))); Pj = json.load(open(os.path.join(ROOT, 'data', 'pitcher_leaderboard_rs.json')))
    md = json.load(open(os.path.join(ROOT, 'data', 'metadata_rs.json')))
    hr = H['hitters'] if isinstance(H, dict) and 'hitters' in H else H; pr = Pj['pitchers'] if isinstance(Pj, dict) and 'pitchers' in Pj else Pj
    war = md['eraPlusConstants']['war']; rpw = war['rpw']; repl_sp, repl_rp = war['replSp'], war['replRp']
    def ip9(r):
        s = str(r.get('ip') or '0'); w, _, f = s.partition('.'); return (int(w) * 3 + int(f or 0)) / 27.0
    C = defaultdict(lambda: defaultdict(float))
    for r in hr:
        t = r.get('team')
        if r.get('hWAR') is None or str(t).endswith('TM'):
            continue
        c = TEAM_ABBREV_TO_ID.get(t)
        if c is None:
            continue
        for k, f in (('bat', 'hBatRuns'), ('bsr', 'hBsrRuns'), ('fld', 'hFldRuns'), ('pos', 'hPosRuns'), ('hwar', 'hWAR')):
            C[c][k] += r[f]
    for r in pr:
        t = r.get('team')
        if r.get('hWAR') is None or str(t).endswith('TM'):
            continue
        c = TEAM_ABBREV_TO_ID.get(t)
        if c is None:
            continue
        g = r.get('g') or 0; s = (r.get('gs') or 0) / g if g else 0.0
        repl = repl_rp + (repl_sp - repl_rp) * s
        C[c]['praa'] += (r['hWAR'] - repl * ip9(r)) * rpw; C[c]['pwar'] += r['hWAR']
    return C, rpw


def ols(X, y, names):
    X = np.column_stack([np.ones(len(y))] + X); b, _, _, _ = np.linalg.lstsq(X, y, rcond=None); res = y - X @ b; n, k = X.shape
    s2 = (res ** 2).sum() / (n - k); se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X))); r2 = 1 - (res ** 2).sum() / ((y - y.mean()) ** 2).sum()
    return {nm: (float(bb), float(ss)) for nm, bb, ss in zip(names, b[1:], se[1:])}, float(r2), float(res.std(ddof=k))


def fmt(fit):
    est, r2, sd = fit
    return '  '.join(f"{k} {v[0]:+.2f}±{v[1]:.2f}" for k, v in est.items()) + f"   R2 {r2:.3f} resid {sd:.1f}"


def main():
    out = {'seasons': {}}
    rows = []   # one dict per club-season
    for y in SEASONS:
        games = load_games(y); st = load_standings(y)
        P = pa_table(y, games); stats = resolve_clubs(P, games)
        ph = T[str(y)]['pitchers']; rpa = sum(v['r'] for v in ph.values()) / sum(v['bf'] for v in ph.values()); scale = HR.SCALE[y]
        bat, btab = batting_runs(P, y, rpa, scale)
        pr = pitcher_runs(y, P)
        fld, pos, n_split, _ = fielding_and_positional(y, P)
        rpw = pr['rpw']; lg_games = pr['lg_games']
        lg_rpg = sum(v['rs'] for v in st.values()) / sum(v['g'] for v in st.values())
        # hitter replacement pinned per PA over club PA
        club_pa = P[P['bclub'] >= 0].groupby('bclub').size().to_dict()
        clubs = sorted(st)
        above = sum(bat.get(c, 0) + fld.get(c, 0) + pos.get(c, 0) for c in clubs)
        target_h = WAR_POOL_SHARE_HITTERS * WAR_POOL * rpw * (lg_games / WAR_POOL_GAMES)
        repl_pa = (target_h - above) / sum(club_pa.get(c, 0) for c in clubs)
        print(f"\n{y}: {len(P)} PA; clubs resolved batters {stats['bclub']} pitchers {stats['pclub']}; batting runs sum {sum(bat.values()):+.1f} "
              f"(sd {np.std(list(bat.values())):.1f}); pitcher RAA sum {sum(pr['club_raa'].values()):+.1f} over {pr['n']} arms ({pr['n_noshare']} without a club share); "
              f"fielding sum {sum(fld.values()):+.1f} ({n_split} multi-club split); positional sum {sum(pos.values()):+.1f}; "
              f"RPW {rpw:.2f}; bars SP {pr['repl_sp']:.4f} RP {pr['repl_rp']:.4f}; pitcher WAR {pr['sum_war']:.1f} = target {pr['target']:.1f}; "
              f"hitter repl {repl_pa * 600:.1f} runs per 600 PA")
        for c in clubs:
            s = st[c]; g = s['g']; pf = PF[str(y)].get(str(c), 100.0)
            hw = (bat.get(c, 0) + fld.get(c, 0) + pos.get(c, 0) + repl_pa * club_pa.get(c, 0)) / rpw
            rows.append(dict(y=y, club=c, g=g, rs=s['rs'] - lg_rpg * g, ra=s['ra'] - lg_rpg * g, w=s['w'] - REPL_PCT * g,
                             bat=bat.get(c, 0), fld=fld.get(c, 0), pos=pos.get(c, 0), praa=pr['club_raa'].get(c, 0), bsr=np.nan,
                             hwar=hw, pwar=pr['club_war'].get(c, 0), park=((pf / 100 + 1) / 2 - 1) * lg_rpg * g))
        out['seasons'][y] = dict(resolve=stats, bat_sum=sum(bat.values()), praa_sum=sum(pr['club_raa'].values()), fld_sum=sum(fld.values()),
                                 pos_sum=sum(pos.values()), rpw=rpw, repl_sp=pr['repl_sp'], repl_pa=repl_pa, pitcher_war=pr['sum_war'], target_p=pr['target'])
        del P; gc.collect()
    # 2026 shipped
    C, rpw26 = season_2026(); st = load_standings(2026); lg_rpg = sum(v['rs'] for v in st.values()) / sum(v['g'] for v in st.values())
    for c in sorted(st):
        if c not in C:
            continue
        s = st[c]; g = s['g']; pf = PF['2026'].get(str(c), 100.0); d = C[c]
        rows.append(dict(y=2026, club=c, g=g, rs=s['rs'] - lg_rpg * g, ra=s['ra'] - lg_rpg * g, w=s['w'] - REPL_PCT * g, bat=d['bat'], fld=d['fld'],
                         pos=d['pos'], praa=d['praa'], bsr=d['bsr'], hwar=d['hwar'], pwar=d['pwar'], park=((pf / 100 + 1) / 2 - 1) * lg_rpg * g))
    df = pd.DataFrame(rows); out['rows'] = df.to_dict('records')
    print("\nPER SEASON (slope ± SE; 1.0 = on scale):")
    per = {}
    for y, g in df.groupby('y'):
        A = lambda k: g[k].values.astype(float)
        f_rs = ols([A('bat'), A('park')], A('rs'), ['bat', 'park'])
        f_ra = ols([A('praa'), A('fld'), A('park')], A('ra'), ['pRAA', 'fld', 'park'])
        f_w = ols([A('hwar'), A('pwar')], A('w'), ['hWAR_h', 'hWAR_p'])
        per[y] = dict(rs=f_rs, ra=f_ra, w=f_w)
        print(f"  {y} RS: {fmt(f_rs)}\n  {y} RA: {fmt(f_ra)}\n  {y} W : {fmt(f_w)}")
        if y == 2026:
            f_rs2 = ols([A('bat'), A('bsr'), A('park')], A('rs'), ['bat', 'bsr', 'park']); per[y]['rs_bsr'] = f_rs2; print(f"  2026 RS with baserunning: {fmt(f_rs2)}")
    out['per_season'] = {int(y): {k: v[0] for k, v in d.items()} for y, d in per.items()}
    print("\nPOOLED 2021-2025 with season intercepts (n 150):")
    g = df[df['y'] < 2026].copy()
    dummies = [(g['y'] == y).values.astype(float) for y in SEASONS[1:]]
    A = lambda k: g[k].values.astype(float)
    p_rs = ols([A('bat'), A('park')] + dummies, A('rs'), ['bat', 'park'] + [f's{y}' for y in SEASONS[1:]])
    p_ra = ols([A('praa'), A('fld'), A('park')] + dummies, A('ra'), ['pRAA', 'fld', 'park'] + [f's{y}' for y in SEASONS[1:]])
    p_w = ols([A('hwar'), A('pwar')] + dummies, A('w'), ['hWAR_h', 'hWAR_p'] + [f's{y}' for y in SEASONS[1:]])
    strip = lambda f: ({k: v for k, v in f[0].items() if not k.startswith('s20')}, f[1], f[2])
    print(f"  RS: {fmt(strip(p_rs))}\n  RA: {fmt(strip(p_ra))}\n  W : {fmt(strip(p_w))}")
    out['pooled'] = dict(rs=strip(p_rs)[0], ra=strip(p_ra)[0], w=strip(p_w)[0])
    print("\nDECISION RULE per component (pooled slope > 2 SE from 1 AND same side in >= 4 of 5 seasons):")
    # sign: a run-saving component (pitcher RAA, fielding runs) LOWERS runs allowed, so its RA slope is expected at -1
    checks = [('bat', 'rs', 'bat', 1.0), ('pRAA', 'ra', 'pRAA', -1.0), ('fld', 'ra', 'fld', -1.0), ('hWAR_h', 'w', 'hWAR_h', 1.0), ('hWAR_p', 'w', 'hWAR_p', 1.0)]
    out['verdict'] = {}
    for name, reg, key, sign in checks:
        b, se = strip({'rs': p_rs, 'ra': p_ra, 'w': p_w}[reg])[0][key]
        b_s = b * sign; z = (b_s - 1.0) / se
        sides = [np.sign(per[y][reg][0][key][0] * sign - 1.0) for y in SEASONS]
        n_same = max(sides.count(1.0), sides.count(-1.0))
        verdict = 'MIS-SCALED' if abs(z) > 2 and n_same >= 4 else ('flagged (one test)' if abs(z) > 2 or n_same >= 4 else 'on scale')
        out['verdict'][name] = dict(slope=b_s, se=se, z=z, same_side=n_same, verdict=verdict)
        print(f"  {name:7} slope {b_s:+.2f} ± {se:.2f}  z {z:+.1f}  same side {n_same}/5  -> {verdict}")
    json.dump(out, open(os.path.join(ROOT, 'data', '_hwar_team_harness.json'), 'w'), indent=1, default=float)
    print("\nwrote data/_hwar_team_harness.json")


if __name__ == '__main__':
    main()
