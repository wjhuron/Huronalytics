"""hwar_replacement_pool.py — where does freely available talent actually perform, and what does
the hitter / pitcher split of the WAR pool measure as? (2026-09-14, candidate 4 part B)

hWAR pins both sides to fWAR's 57/43 split of 1000 WAR per 2430 games, a judgment ("the role we
believe each plays"). The measurable form: the replacement level is the performance of players any
club can have for nothing. Two definitions bracket it, and the SPLIT is reported under each.

  A. transactions  a player with a waiver claim (CLW), a minor-league free-agent signing (SFA with
                   "minor league" in the description), an outright (OUT) or a release (REL) dated
                   between Nov 1 of Y-1 and the end of season Y (MLB Stats API transactions feed,
                   data/_hwar_team/transactions_Y.json); his MLB plate appearances in season Y AFTER
                   the earliest such date count (an offseason date: the whole season). No age gate,
                   no salary gate. Trades, major-league free agents and contracts selected without
                   a prior free-pool transaction are OUT: they cost something or are prospects.
  B. roster rank   within each club-season, hitters ranked 14th and below by PA with that club and
                   pitchers ranked 14th and below by batters faced (a 26-man roster carries 13 and
                   13); every PA of theirs counts. No transactions needed.

Levels (runs below league average per unit of playing time, PA-weighted = what a club gets):
  hitters   batting (per-PA xhb, the shipped basis, against the league mean, no shrink for a pool
            aggregate) + fielding (season Savant FRV prorated to the pool PAs) + positional
            (innings-by-position runs prorated the same way), each relative to the league mean per PA
  pitchers  pool xwOBA against (raw per-PA Savant xwOBA) minus the league, converted at hdERA's own
            slope DH_B / sd(pool) runs per 9 per xwOBA point, reported by role (starter = GS/G >= .5)
Split = hitter share of replacement runs at league playing time:
  hit_total = level_h x league PA,  pit_total = level_p x league IP/9,  share_h = hit / (hit + pit)
Also: the implied pool, (hit + pit) / RPW, against 1000 x games / 2430.
Caveat named up front: the pool's performance is measured after selection (the ones who stuck are
the ones who played), which biases both levels up in the same direction; the split is the more
trustworthy read, and an equal-weight-by-player version is printed beside the PA-weighted one.

Usage: python3 scripts/research/hitter/hwar_replacement_pool.py
Output: console + data/_hwar_replacement_pool.json
"""
import gc, json, os, sys
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'era'))
from pipeline.eraplus import DH_B, WAR_POOL, WAR_POOL_GAMES, WAR_POOL_SHARE_HITTERS
import hwar_team_harness as H
import war_rate_validation as W
import hwar_hitter_rate_validation as HR

D = H.D; SEASONS = H.SEASONS; T = W.T
ROSTER_N = 13
FREE_TYPES = {'CLW', 'OUT', 'REL'}


def free_dates(y):
    """{player id -> earliest date he became freely available in the window}."""
    tx = json.load(open(os.path.join(D, f'transactions_{y}.json')))['transactions']
    out = {}
    for t in tx:
        code = t.get('typeCode'); desc = (t.get('description') or '').lower(); pid = str((t.get('person') or {}).get('id') or '')
        if not pid:
            continue
        ok = code in FREE_TYPES or (code == 'SFA' and 'minor league' in desc)
        if not ok:
            continue
        d = (t.get('date') or t.get('effectiveDate') or '')[:10]
        if not d:
            continue
        if pid not in out or d < out[pid]:
            out[pid] = d
    return out


def season(y):
    games = H.load_games(y); st = H.load_standings(y)
    P = H.pa_table(y, games); H.resolve_clubs(P, games)
    ph = T[str(y)]['pitchers']
    rows = W.season_table(y); lg = W.league(rows); pz = W.pool_stats(rows, lg)
    lg_ra9, rpw, lg_xw, sd_pool = lg['ra9'], lg['rpw'], lg['xw'], pz[1]
    scale = HR.SCALE[y]; rpa = sum(v['r'] for v in ph.values()) / sum(v['bf'] for v in ph.values())
    lg_outs = sum(v['outs'] for v in ph.values()); lg_pa = len(P); pa9 = lg_pa / (lg_outs / 27.0)
    lg_games = sum(v['g'] for v in st.values()) / 2.0
    # per-player season quantities for proration
    pa_season = P.groupby('bid').size().to_dict()
    frv = {k: (v.get('total') or 0.0) for k, v in json.load(open(os.path.join(D, f'frv_{y}.json'))).items()}
    _, _, _, player_pos = H.fielding_and_positional(y, P)
    L_xhb = float(P['xhb'].mean())
    lg_fld_pa = sum(frv.values()) / lg_pa; lg_pos_pa = sum(player_pos.values()) / lg_pa
    role = {p: ((v['gs'] / v['g']) if v['g'] else 0.0) for p, v in ph.items()}
    P['starter'] = P['pid'].map(lambda p: role.get(p, 0.0) >= 0.5).values
    P['bat_pa'] = (P['xhb'] - L_xhb) / scale
    P['fld_pa'] = P['bid'].map(lambda b: frv.get(b, 0.0) / pa_season[b] - lg_fld_pa).values
    P['pos_pa'] = P['bid'].map(lambda b: player_pos.get(b, 0.0) / pa_season[b] - lg_pos_pa).values
    P['xw_dev'] = P['xw'] - lg_xw
    ctx = dict(lg_ra9=lg_ra9, rpw=rpw, sd_pool=sd_pool, pa9=pa9, lg_pa=lg_pa, lg_ip9=lg_outs / 27.0, lg_games=lg_games)
    return P, ctx


def levels(P, mask_h, mask_p, ctx):
    """Replacement levels from the masked PAs. Returns dict with per-PA hitter runs below league,
    per-9 pitcher runs below league (all, starters, relievers), sizes, and equal-weight variants."""
    h = P[mask_h]; p = P[mask_p]
    out = {}
    if len(h):
        comp = {k: float(h[k].mean()) for k in ('bat_pa', 'fld_pa', 'pos_pa')}
        out['h_level_pa'] = -(comp['bat_pa'] + comp['fld_pa'] + comp['pos_pa']); out['h_comp_600'] = {k: v * 600 for k, v in comp.items()}
        g = h.groupby('bid').agg(bat=('bat_pa', 'mean'), fld=('fld_pa', 'mean'), pos=('pos_pa', 'mean'), n=('bat_pa', 'size'))
        out['h_level_pa_eq'] = -float((g['bat'] + g['fld'] + g['pos']).mean()); out['h_players'] = int(len(g)); out['h_pa'] = int(len(h))
        out['h_share_of_pa'] = len(h) / ctx['lg_pa']
    if len(p):
        k = DH_B / ctx['sd_pool']
        out['p_level_9'] = float(p['xw_dev'].mean()) * k
        for nm, m in (('sp', p['starter'].values), ('rp', ~p['starter'].values)):
            out[f'p_level_9_{nm}'] = float(p.loc[m, 'xw_dev'].mean()) * k if m.any() else None; out[f'p_pa_{nm}'] = int(m.sum())
        g = p.groupby('pid').agg(xw=('xw_dev', 'mean'), n=('xw_dev', 'size'))
        out['p_level_9_eq'] = float(g['xw'].mean()) * k; out['p_players'] = int(len(g)); out['p_pa'] = int(len(p)); out['p_share_of_pa'] = len(p) / ctx['lg_pa']
    if 'h_level_pa' in out and 'p_level_9' in out:
        hit = out['h_level_pa'] * ctx['lg_pa']; pit = out['p_level_9'] * ctx['lg_ip9']
        out['hit_total'] = hit; out['pit_total'] = pit; out['share_h'] = hit / (hit + pit) if (hit + pit) else None
        out['pool_war'] = (hit + pit) / ctx['rpw']; out['pool_war_convention'] = WAR_POOL * ctx['lg_games'] / WAR_POOL_GAMES
        hit_e = out['h_level_pa_eq'] * ctx['lg_pa']; pit_e = out['p_level_9_eq'] * ctx['lg_ip9']
        out['share_h_eq'] = hit_e / (hit_e + pit_e) if (hit_e + pit_e) else None
    return out


def main():
    out = {}
    for y in SEASONS:
        P, ctx = season(y)
        # A: transactions
        fd = free_dates(y)
        after_b = P['bid'].map(fd).values; after_p = P['pid'].map(fd).values
        mask_h = pd.notna(after_b) & (P['date'].values > np.where(pd.notna(after_b), after_b, '')); mask_p = pd.notna(after_p) & (P['date'].values > np.where(pd.notna(after_p), after_p, ''))
        A = levels(P, mask_h, mask_p, ctx)
        # B: roster rank within club-season
        hb = P[P['bclub'] >= 0].groupby(['bclub', 'bid']).size().reset_index(name='n'); hb['rk'] = hb.groupby('bclub')['n'].rank(ascending=False, method='first')
        pb = P[P['pclub'] >= 0].groupby(['pclub', 'pid']).size().reset_index(name='n'); pb['rk'] = pb.groupby('pclub')['n'].rank(ascending=False, method='first')
        deep_h = set(zip(hb.loc[hb['rk'] > ROSTER_N, 'bclub'], hb.loc[hb['rk'] > ROSTER_N, 'bid'])); deep_p = set(zip(pb.loc[pb['rk'] > ROSTER_N, 'pclub'], pb.loc[pb['rk'] > ROSTER_N, 'pid']))
        mask_hB = np.array([(c, b) in deep_h for c, b in zip(P['bclub'].values, P['bid'].values)]); mask_pB = np.array([(c, p) in deep_p for c, p in zip(P['pclub'].values, P['pid'].values)])
        B = levels(P, mask_hB, mask_pB, ctx)
        out[y] = dict(ctx=ctx, A=A, B=B, n_free_players=len(fd))
        for nm, R in (('A transactions', A), ('B roster rank', B)):
            print(f"{y} {nm:16} hitters {R['h_players']:4d} players {R['h_pa']:6d} PA ({R['h_share_of_pa']:.1%} of league): level {R['h_level_pa'] * 600:5.1f} runs per 600 PA below average "
                  f"[bat {R['h_comp_600']['bat_pa']:+.1f} fld {R['h_comp_600']['fld_pa']:+.1f} pos {R['h_comp_600']['pos_pa']:+.1f}] (equal-weight {R['h_level_pa_eq'] * 600:.1f}); "
                  f"pitchers {R['p_players']:4d} players {R['p_pa']:6d} PA ({R['p_share_of_pa']:.1%}): level {R['p_level_9']:.2f} runs per 9 below average "
                  f"(SP {R['p_level_9_sp'] if R['p_level_9_sp'] is None else round(R['p_level_9_sp'], 2)} on {R['p_pa_sp']} PA, RP {round(R['p_level_9_rp'], 2)} on {R['p_pa_rp']} PA; equal-weight {R['p_level_9_eq']:.2f}); "
                  f"SPLIT hitters {R['share_h']:.3f} (equal-weight {R['share_h_eq']:.3f}); implied pool {R['pool_war']:.0f} WAR vs convention {R['pool_war_convention']:.0f}", flush=True)
        del P; gc.collect()
    print("\nSUMMARY: hitter share of the replacement pool (convention 0.570)")
    for nm in ('A', 'B'):
        s = [out[y][nm]['share_h'] for y in SEASONS]; se = [out[y][nm]['share_h_eq'] for y in SEASONS]
        print(f"  {nm}: " + " ".join(f"{y} {v:.3f}" for y, v in zip(SEASONS, s)) + f"  mean {np.mean(s):.3f} sd {np.std(s, ddof=1):.3f}  | equal-weight mean {np.mean(se):.3f}")
    print("  implied pool (WAR per 2430 games): " + " ".join(f"{nm} {np.mean([out[y][nm]['pool_war'] / (out[y]['ctx']['lg_games'] / WAR_POOL_GAMES) for y in SEASONS]):.0f}" for nm in ('A', 'B')) + "  (convention 1000)")
    print("  hitter level, runs per 600 PA: " + " ".join(f"{nm} {np.mean([out[y][nm]['h_level_pa'] * 600 for y in SEASONS]):.1f}" for nm in ('A', 'B')) + f"  (shipped pin: about 19.5 x RPW/9.7 = the 57% share)")
    print("  pitcher level, runs per 9:     " + " ".join(f"{nm} {np.mean([out[y][nm]['p_level_9'] for y in SEASONS]):.2f}" for nm in ('A', 'B')) + f"  (shipped pinned bars: SP 0.128 wins/9 = {0.128 * 9.6:.2f} runs/9, RP 0.040 = {0.040 * 9.6:.2f})")
    json.dump(out, open(os.path.join(ROOT, 'data', '_hwar_replacement_pool.json'), 'w'), indent=1, default=float)
    print("wrote data/_hwar_replacement_pool.json")


if __name__ == '__main__':
    main()
