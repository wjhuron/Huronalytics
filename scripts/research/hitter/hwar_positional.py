"""hwar_positional.py — the positional adjustment, two designs, and the version-three rule (2026-09-14).

fWAR's values (HWAR_POS_ADJ: C 12.5, SS 7.5, 2B/3B/CF 2.5, LF/RF -7.5, 1B -12.5, DH -17.5 runs per
1458 innings) came from Tango's position-switcher design on 2000s UZR plus "some creative licence"
(2014). No out-of-sample objective exists for them. Two designs measure the spectrum from different
evidence; their agreement on DIRECTION is the only check this question allows.

DESIGN 1, the same fielder at two positions (fWAR's own design on Statcast data):
    delta_AB(player-season) = FRP_A / inn_A x 1458 - FRP_B / inn_B x 1458
    FRP = Savant range runs AT that position (outs_above_average CSV with the numeric pos code,
    data/_hwar_team/oaa_Y_posP.csv, integers), innings from the MLB API fielding splits summed over
    clubs (innings_Y.json); pairs with >= MIN_INN at both positions; weight 1/(1/inn_A + 1/inn_B).
    Levels solved by weighted least squares with a sum-to-zero constraint; a level is how many
    more runs the same fielder posts at that position, so pos_adj = -level + K. Bootstrap SE over
    player-seasons. Candidate = 2023-2026 (post shift ban); 2016-2022 reported as the pre-ban read.
    Known floor: players are placed where they can play, so the spread is compressed by selection.
    Catcher and DH are not measurable here.
DESIGN 2, the offensive gap at the margin (Tango's 2026 primer):
    bench_X = PA-weighted batting runs per 600 PA (per-PA xhb, the shipped basis, against the league
    mean, no shrink) of the NON-REGULARS whose primary position is X (primary = most innings that
    season, DH by games x 9; regular = top BENCH_TOP by PA at that position, one per club).
    pos_adj_X = -bench_X + K2. If clubs price positions efficiently, the worst bench bats sit where
    defense is worth most. Covers all nine positions. 2021-2025 from the Savant caches, 2026 from the
    sheet. SE by bootstrap over players; BENCH_TOP 45 as a sensitivity.
ANCHOR K, K2: the innings-weighted (design 1, 7 field positions) / PA-weighted (design 2, 9 positions)
    mean of the measured spectrum equals fWAR's over the same positions. A convention; the hitter
    replacement pin absorbs the center anyway, so only the spread between positions carries value.
THE RULE (version three, agreed 2026-09-14 before any number was seen):
    1. design 1 on 2023-2026 is the candidate spectrum for the seven field positions, whole.
    2. one test: the innings-weighted regression slope of a design on fWAR across the seven
       positions says compressed (< 1) or widened (> 1). The candidate ships only if design 2's
       slope sits on the same side of 1. Otherwise fWAR stays and both tables publish beside it.
    3. catcher and DH from design 2 alone, only if SE < 3 runs and the sign of the deviation from
       fWAR holds in 4 of 6 seasons; otherwise they keep their fWAR distance from the field.
    4. the shipped values are a labeled convention: measured on position switchers, a floor on the
       spread, with design 2 as the direction check.
Also printed: bWAR's set (C 9, SS 7, 2B 3, CF 2.5, 3B 2, LF/RF -7, 1B -9.5, DH -15 per 1350 innings)
and what the candidate does to the shipped 2026 positional runs of the top hitters.

Usage: python3 scripts/research/hitter/hwar_positional.py
Output: console + data/_hwar_positional.json
"""
import csv, gc, json, os, sys
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'era'))
from pipeline.hwar import HWAR_POS_ADJ, HWAR_POS_INNINGS
import hwar_team_harness as H
import hwar_hitter_rate_validation as HR
import war_rate_validation as W

D = H.D
FIELD = ['1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF']; ALL9 = FIELD + ['C', 'DH']
POSCODE = {'1B': 3, '2B': 4, '3B': 5, 'SS': 6, 'LF': 7, 'CF': 8, 'RF': 9}
BWAR = {'C': 9.0, 'SS': 7.0, '2B': 3.0, 'CF': 2.5, '3B': 2.0, 'RF': -7.0, 'LF': -7.0, '1B': -9.5, 'DH': -15.0}   # per 1350 innings, B-Ref
MIN_INN = 100.0
BENCH_TOP = 30; BENCH_TOP_ALT = 45
ERA_CAND = [2023, 2024, 2025, 2026]; ERA_PRE = [2016, 2017, 2018, 2019, 2020, 2021, 2022]
SEASONS_D2 = [2021, 2022, 2023, 2024, 2025, 2026]
rng = np.random.default_rng(0)


def innings(y):
    """{player: {pos: innings}} summed over clubs; DH carries games x 9 under 'DH'."""
    out = defaultdict(lambda: defaultdict(float))
    for sp in json.load(open(os.path.join(D, f'innings_{y}.json')))['stats'][0]['splits']:
        pos = sp.get('position', {}).get('abbreviation'); pid = str(sp['player']['id']); st = sp['stat']
        if pos == 'DH':
            out[pid]['DH'] += 9.0 * int(st.get('games') or 0)
        elif pos in POSCODE or pos in ('C', 'P'):
            w, _, f = str(st.get('innings') or '0').partition('.'); out[pid][pos] += int(w) + int(f or 0) / 3.0
    return out


def frp(y):
    out = defaultdict(dict)
    for pos, code in POSCODE.items():
        for r in csv.DictReader(open(os.path.join(D, f'oaa_{y}_pos{code}.csv'), encoding='utf-8-sig')):
            out[r['player_id']][pos] = float(r['fielding_runs_prevented'] or 0)
    return out


def pairs_for(years):
    """List of (a, b, delta, w, key) over player-seasons with >= MIN_INN at two positions."""
    P = []
    for y in years:
        I = innings(y); F = frp(y)
        for pid, ip in I.items():
            ok = [p for p in FIELD if ip.get(p, 0) >= MIN_INN and p in F.get(pid, {})]
            for i in range(len(ok)):
                for j in range(i + 1, len(ok)):
                    a, b = ok[i], ok[j]
                    ra = F[pid][a] / ip[a] * HWAR_POS_INNINGS; rb = F[pid][b] / ip[b] * HWAR_POS_INNINGS
                    P.append((a, b, ra - rb, 1.0 / (1.0 / ip[a] + 1.0 / ip[b]), f'{y}:{pid}'))
    return P


def solve_levels(P):
    idx = {p: i for i, p in enumerate(FIELD)}
    A = np.zeros((len(P) + 1, len(FIELD))); b = np.zeros(len(P) + 1)
    for k, (a, bb, d, w, _) in enumerate(P):
        s = np.sqrt(w); A[k, idx[a]] = s; A[k, idx[bb]] = -s; b[k] = d * s
    A[-1, :] = 1e3
    lv, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
    return {p: float(lv[idx[p]]) for p in FIELD}


def league_innings(years):
    tot = defaultdict(float)
    for y in years:
        for pid, ip in innings(y).items():
            for p in FIELD:
                tot[p] += ip.get(p, 0.0)
    return dict(tot)


def anchor(adj, weights, ref):
    """Shift adj so its weighted mean over its keys equals ref's weighted mean over the same keys."""
    ks = list(adj); w = np.array([weights[k] for k in ks]); m_adj = np.average([adj[k] for k in ks], weights=w); m_ref = np.average([ref[k] for k in ks], weights=w)
    return {k: adj[k] - m_adj + m_ref for k in ks}


def slope_on_fwar(adj, weights, keys):
    x = np.array([HWAR_POS_ADJ[k] for k in keys]); y = np.array([adj[k] for k in keys]); w = np.array([weights[k] for k in keys], float)
    mx, my = np.average(x, weights=w), np.average(y, weights=w)
    return float(np.sum(w * (x - mx) * (y - my)) / np.sum(w * (x - mx) ** 2))


def design1(years, label, n_boot=300):
    P = pairs_for(years); keys = sorted({k for *_, k in P})
    lv = solve_levels(P); wts = league_innings(years)
    adj = anchor({p: -lv[p] for p in FIELD}, wts, HWAR_POS_ADJ); sl = slope_on_fwar(adj, wts, FIELD)
    by_key = defaultdict(list)
    for t in P:
        by_key[t[-1]].append(t)
    boots_adj, boots_sl = [], []
    for _ in range(n_boot):
        samp = rng.choice(keys, len(keys), replace=True); Pb = [t for k in samp for t in by_key[k]]
        lb = solve_levels(Pb); ab = anchor({p: -lb[p] for p in FIELD}, wts, HWAR_POS_ADJ); boots_adj.append([ab[p] for p in FIELD]); boots_sl.append(slope_on_fwar(ab, wts, FIELD))
    se = dict(zip(FIELD, np.std(boots_adj, axis=0))); se_sl = float(np.std(boots_sl))
    n_pairs = len(P); n_ps = len(keys)
    print(f"DESIGN 1 {label}: {n_ps} player-seasons, {n_pairs} position pairs; slope on fWAR {sl:+.2f} ± {se_sl:.2f}")
    for p in FIELD:
        print(f"   {p}: {adj[p]:+6.1f} ± {se[p]:.1f}   (fWAR {HWAR_POS_ADJ[p]:+.1f}, level {-(adj[p] - HWAR_POS_ADJ[p]):+.1f} vs fWAR)")
    return dict(adj=adj, se=se, slope=sl, slope_se=se_sl, n_pairs=n_pairs, n_player_seasons=n_ps, weights=wts)


def primary_position(y):
    out = {}
    for pid, ip in innings(y).items():
        cand = {p: v for p, v in ip.items() if p in ALL9}
        if not cand:
            continue
        p = max(cand, key=cand.get)
        if ip.get('P', 0) > cand[p]:
            continue   # a pitcher
        out[pid] = p
    return out


def design2(top=BENCH_TOP, n_boot=300):
    per_season = {}; pool = defaultdict(list)   # pos -> [(bat_per_pa, n, player-season)]
    for y in SEASONS_D2:
        if y < 2026:
            games = H.load_games(y); P = H.pa_table(y, games)
        else:
            P, _ = HR.pa_sheet(2026)
        ph = W.T[str(y)]['pitchers']; scale = HR.SCALE[y]
        L = float(P['xhb'].mean()); P['bat_pa'] = (P['xhb'] - L) / scale
        g = P.groupby('bid').agg(bat=('bat_pa', 'mean'), n=('bat_pa', 'size')); prim = primary_position(y)
        g['pos'] = g.index.map(lambda b: prim.get(str(b))); g = g[g['pos'].notna()]
        g['rk'] = g.groupby('pos')['n'].rank(ascending=False, method='first')
        bench = g[g['rk'] > top]
        row = {}
        for p in ALL9:
            s = bench[bench['pos'] == p]
            if len(s):
                row[p] = dict(bench600=float(np.average(s['bat'], weights=s['n'])) * 600, n_pa=int(s['n'].sum()), n_players=int(len(s)))
                for _, r in s.iterrows():
                    pool[p].append((r['bat'], r['n'], f"{y}:{_}"))
        per_season[y] = row
        del P; gc.collect()
    lg_pa = {p: sum(n for _, n, _ in pool[p]) for p in ALL9}
    bench = {p: float(np.average([b for b, _, _ in pool[p]], weights=[n for _, n, _ in pool[p]])) * 600 for p in ALL9}
    adj = anchor({p: -bench[p] for p in ALL9}, lg_pa, HWAR_POS_ADJ)
    boots = []
    for _ in range(n_boot):
        bb = {}
        for p in ALL9:
            k = rng.integers(0, len(pool[p]), len(pool[p])); b = np.array([pool[p][i][0] for i in k]); n = np.array([pool[p][i][1] for i in k])
            bb[p] = -float(np.average(b, weights=n)) * 600
        boots.append([anchor(bb, lg_pa, HWAR_POS_ADJ)[p] for p in ALL9])
    se = dict(zip(ALL9, np.std(boots, axis=0)))
    wts7 = league_innings(SEASONS_D2)
    sl = slope_on_fwar(adj, wts7, FIELD); sl_se = float(np.std([slope_on_fwar(dict(zip(ALL9, bvec)), wts7, FIELD) for bvec in boots]))
    # per-season sign of the deviation from fWAR for every position (anchored within season over the 9)
    signs = defaultdict(list)
    for y, row in per_season.items():
        a = anchor({p: -row[p]['bench600'] for p in ALL9 if p in row}, {p: row[p]['n_pa'] for p in row}, HWAR_POS_ADJ)
        for p in a:
            signs[p].append(int(np.sign(a[p] - HWAR_POS_ADJ[p])))
    print(f"DESIGN 2 (bench = outside the top {top} by PA at the position), 2021-2026 pooled; slope on fWAR over the 7 field positions {sl:+.2f} ± {sl_se:.2f}")
    for p in ALL9:
        sg = signs[p]; same = max(sg.count(1), sg.count(-1))
        print(f"   {p:2}: {adj[p]:+6.1f} ± {se[p]:.1f}   (fWAR {HWAR_POS_ADJ[p]:+.1f}; bench bat {bench[p]:+.1f} runs/600 on {lg_pa[p]} PA; deviation sign holds {same}/{len(sg)} seasons)")
    return dict(adj=adj, se=se, slope=sl, slope_se=sl_se, bench=bench, n_pa=lg_pa, signs={p: signs[p] for p in ALL9}, per_season=per_season)


def effect_2026(cand):
    """Positional runs for the shipped 2026 hitters under the candidate vs fWAR."""
    inn = json.load(open(os.path.join(ROOT, 'data', 'fielding_innings_cache.json')))
    Hj = json.load(open(os.path.join(ROOT, 'data', 'hitter_leaderboard_rs.json'))); hr = Hj['hitters'] if isinstance(Hj, dict) and 'hitters' in Hj else Hj
    md = json.load(open(os.path.join(ROOT, 'data', 'metadata_rs.json'))); rpw = md['hwarConstants']['rpw']
    out = []
    for r in hr:
        if r.get('hWAR') is None or str(r.get('team', '')).endswith('TM'):
            continue
        ip = inn.get(str(r.get('mlbId'))) or {}
        def pos_runs(tab):
            return sum((ip.get(p, 0.0) if p != 'DH' else 9.0 * ip.get('DH_games', 0)) * tab[p] / HWAR_POS_INNINGS for p in tab)
        out.append((r['hitter'], r['team'], r['pa'], pos_runs(HWAR_POS_ADJ), pos_runs(cand), r['hWAR']))
    out.sort(key=lambda t: t[4] - t[3])
    print("EFFECT on the shipped 2026 positional runs (candidate minus fWAR; hWAR moves by that over RPW, before the replacement pin re-solves):")
    for t in out[:5] + out[-5:]:
        print(f"   {t[0]:24} {t[1]:4} PA {t[2]:4} pos fWAR {t[3]:+6.1f} -> {t[4]:+6.1f}  ({(t[4] - t[3]) / rpw:+.2f} WAR)   hWAR now {t[5]:.1f}")
    return [dict(hitter=t[0], team=t[1], pa=t[2], pos_fwar=t[3], pos_cand=t[4], d_war=(t[4] - t[3]) / rpw) for t in out]


def main():
    out = {}
    d1c = design1(ERA_CAND, '2023-2026 (candidate)'); d1p = design1(ERA_PRE, '2016-2022 (pre-ban read)'); d1a = design1(ERA_PRE + ERA_CAND, '2016-2026 (all)')
    d2 = design2(BENCH_TOP); d2alt = design2(BENCH_TOP_ALT, n_boot=100)
    out.update(design1_candidate=d1c, design1_preban=d1p, design1_all=d1a, design2=d2, design2_top45=d2alt)
    print("\nTABLE (runs per 1458 innings; bWAR per 1350):")
    print(f"   {'pos':3} {'fWAR':>6} {'bWAR':>6} {'D1 23-26':>10} {'D1 16-22':>10} {'D2 21-26':>10} {'D2 top45':>9}")
    for p in ALL9:
        c1 = f"{d1c['adj'][p]:+.1f}±{d1c['se'][p]:.1f}" if p in FIELD else '  n/a'; p1 = f"{d1p['adj'][p]:+.1f}" if p in FIELD else '  n/a'
        print(f"   {p:3} {HWAR_POS_ADJ[p]:+6.1f} {BWAR[p]:+6.1f} {c1:>10} {p1:>10} {d2['adj'][p]:+6.1f}±{d2['se'][p]:.1f} {d2alt['adj'][p]:+8.1f}")
    same_side = np.sign(d1c['slope'] - 1) == np.sign(d2['slope'] - 1)
    print(f"\nRULE 2, the spread: design 1 slope {d1c['slope']:+.2f} ± {d1c['slope_se']:.2f} (pre-ban {d1p['slope']:+.2f}), design 2 slope {d2['slope']:+.2f} ± {d2['slope_se']:.2f} (top45 {d2alt['slope']:+.2f}) "
          f"-> {'SAME side of 1: the candidate spectrum ships for the field positions' if same_side else 'OPPOSITE sides of 1: fWAR stays, both tables publish beside it'}")
    cand = dict(HWAR_POS_ADJ)
    if same_side:
        cand.update({p: d1c['adj'][p] for p in FIELD})
    cd = {}
    for p in ('C', 'DH'):
        sg = d2['signs'][p]; same = max(sg.count(1), sg.count(-1)); ok = d2['se'][p] < 3.0 and same >= 4
        cd[p] = dict(value=d2['adj'][p], se=d2['se'][p], same=same, adopt=bool(ok))
        print(f"RULE 3, {p}: design 2 {d2['adj'][p]:+.1f} ± {d2['se'][p]:.1f}, sign holds {same}/6 -> {'ADOPT' if ok else 'keep the fWAR distance from the field'}")
        if ok and same_side:
            cand[p] = d2['adj'][p]
        elif same_side:
            # keep the fWAR distance from the (re-anchored) field: the anchor already equalizes the field mean, so the fWAR value stands
            cand[p] = HWAR_POS_ADJ[p]
    print("\nCANDIDATE TABLE to ship (if the rule passed):", {p: round(v, 1) for p, v in cand.items()})
    out['rule'] = dict(same_side=bool(same_side), c_dh=cd, candidate=cand)
    out['effect_2026'] = effect_2026(cand)
    json.dump(out, open(os.path.join(ROOT, 'data', '_hwar_positional.json'), 'w'), indent=1, default=float)
    print("wrote data/_hwar_positional.json")


if __name__ == '__main__':
    main()
