"""The AAA ruler for pitcher cards: every 2026 AAA pitcher scored the way a scratch-tab card scores one.

Each AAA regular-season pitcher in the MiLB corpus goes through the card's own scratch context
(cards/pitcher.py: _build_scratch_league_context and _compute_scratch_pitcher_context), so his
Stuff+, Loc+, xRV and rates are exactly what his own card would compute. The pool then sets the
AAA grade shift: per pitch type for Stuff+ and per location group for Loc+, the AAA mean of the
unrounded MLB-anchored grade less 100. Every pitcher's grades are re-rounded on that shift, so the
pool sits on the same atoms a AAA card draws. Pitcher+ is rebuilt on the pool's own (mu, sigma)
with the shipped build_baseline rule (300 pitches).

Writes data/_milb2026/pitcher_pool_AAA.json, which cards/pitcher.py reads with --aaa-ruler. The
league ERA anchor comes from the MLB Stats API AAA team totals; FIP and xFIP take the same value,
as FanGraphs sets both constants to make the league mean equal league ERA.

Batches keep one pitcher group in memory at a time: this machine has 8 GB, so run it alone, with
no card build beside it. About 30 minutes.

    PYTHONHASHSEED=0 .venv/bin/python scripts/research/cards/aaa_pitcher_pool.py
    PYTHONHASHSEED=0 .venv/bin/python scripts/research/cards/aaa_pitcher_pool.py --limit 150   # smoke test, writes _smoke
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import date

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from cards import milb_corpus as mc  # noqa: E402
from cards import pitcher as P  # noqa: E402
from pipeline.compute import compute_expected_stats, compute_stats  # noqa: E402
from pipeline.eraplus import DH_B_AAA, N0_XW, POOL_MIN_OUTS  # noqa: E402
from pipeline.pitcherplus import build_baseline, score_row  # noqa: E402
from pipeline.utils import WHIFF_DESCRIPTIONS, is_no_pitch, safe_float  # noqa: E402

OUT = os.path.join(ROOT, 'data', '_milb2026')
N_BATCH = 4
SEASON = 2026
AAA_SPORT_ID = 11
PT_RATE_KEYS = ('cswPct', 'izPct', 'swStrPct', 'chasePct', 'gbPct', 'strikePct', 'izWhiffPct')
PITCHER_KEEP = tuple(P._SCRATCH_POOL_STATS) + ('pa', 'count', 'nBip', 'runValue', 'rv100', 'kbbPct')


def split_batches(limit=None):
    """AAA regular-season pitches into N_BATCH files by pitcher mlbId, plus team games per club."""
    tag = '_smoke' if limit else ''
    paths = [os.path.join(OUT, f'_aaa_pbatch{tag}{i}.csv') for i in range(N_BATCH)]
    tg_path = os.path.join(OUT, f'_aaa_pbatch{tag}_teamgames.json')
    if all(os.path.exists(p) for p in paths) and os.path.exists(tg_path):
        with open(tg_path) as f:
            return paths, json.load(f)
    man = pd.read_csv(mc.MANIFEST_PATH, usecols=['game_pk', 'level', 'gameType'])
    pks = set(man[(man.level == 'AAA') & (man.gameType == 'R')].game_pk)
    players = pd.read_csv(mc.PLAYERS_PATH, keep_default_na=False)[['game_pk', 'team', 'name', 'mlbId']]
    club_games = defaultdict(set)
    keep_ids = None
    started = set()
    for chunk in pd.read_csv(mc.CORPUS_PATH, dtype=str, keep_default_na=False, chunksize=100_000):
        chunk['_pk'] = chunk.PitchID.str.split('_').str[0].astype(int)
        chunk = chunk[chunk._pk.isin(pks)]
        if not len(chunk):
            continue
        for club, pk in set(zip(chunk.PTeam, chunk._pk)):
            club_games[club].add(int(pk))
        n0 = len(chunk)
        chunk = chunk.merge(players, left_on=['_pk', 'PTeam', 'Pitcher'],
                            right_on=['game_pk', 'team', 'name'], validate='m:1')
        if len(chunk) != n0:
            print(f'  {n0 - len(chunk)} pitches had no pitcher mlbId and were dropped', flush=True)
        chunk = chunk.drop(columns=['game_pk', 'team', 'name', '_pk'])
        if limit:
            if keep_ids is None:
                keep_ids = set(sorted(chunk.mlbId.unique())[:limit])
            chunk = chunk[chunk.mlbId.isin(keep_ids)]
        for i, g in chunk.groupby(chunk.mlbId.astype(int) % N_BATCH):
            g.to_csv(paths[i], mode='a' if i in started else 'w', header=i not in started, index=False)
            started.add(i)
    for i, p in enumerate(paths):
        if i not in started:
            pd.DataFrame(columns=['mlbId']).to_csv(p, index=False)
    tg = {c: len(v) for c, v in club_games.items()}
    with open(tg_path, 'w') as f:
        json.dump(tg, f)
    return paths, tg


def league_era():
    """AAA league ERA from the MLB Stats API team totals. Stops on a failed fetch."""
    url = (f'https://statsapi.mlb.com/api/v1/teams/stats?season={SEASON}&sportIds={AAA_SPORT_ID}'
           '&group=pitching&stats=season&gameType=R')
    with urllib.request.urlopen(url, timeout=60) as r:
        sp = json.load(r)['stats'][0]['splits']
    er = sum(x['stat']['earnedRuns'] for x in sp)
    outs = sum(x['stat']['outs'] for x in sp)
    if len(sp) < 28 or not outs:
        sys.exit(f'AAA team totals look wrong ({len(sp)} teams, {outs} outs). Not writing the pool.')
    return er * 27 / outs, len(sp)


def pitcher_era():
    """Per-pitcher AAA earned runs and outs, one combined row per pitcher, from the MLB Stats API.
    Stops on a failed or short fetch."""
    url = ('https://statsapi.mlb.com/api/v1/stats?stats=season&group=pitching'
           f'&sportId={AAA_SPORT_ID}&season={SEASON}&playerPool=All&limit=10000&gameType=R')
    with urllib.request.urlopen(url, timeout=60) as r:
        sp = json.load(r)['stats'][0]['splits']
    if len(sp) < 1000:
        sys.exit(f'AAA pitcher lines look wrong ({len(sp)} rows). Not writing the pool.')
    return {str(x['player']['id']): (int(x['stat'].get('earnedRuns', 0)), int(x['stat'].get('outs', 0)))
            for x in sp}


def hdera_scale(pitchers, era):
    """hdERA's AAA scale, the apply_era_plus rules on the AAA pool: 30+ IP, anchor = mean ERA,
    xwOBA shrunk at N0_XW toward the PA-weighted pool mean, z over the pool. The slope is
    DH_B_AAA (scripts/research/era/aaa_hdera_slope.py)."""
    pool = [(r['xwOBA'], r['pa'], era[mid]) for mid, r in pitchers.items()
            if mid in era and era[mid][1] >= POOL_MIN_OUTS and r.get('xwOBA') is not None and r.get('pa')]
    if len(pool) < 300:
        sys.exit(f'Only {len(pool)} AAA pitchers at 30+ IP with an xwOBA. Not writing the pool.')
    lg_xw = sum(x * pa for x, pa, _ in pool) / sum(pa for _, pa, _ in pool)
    shr = [(x * pa + N0_XW * lg_xw) / (pa + N0_XW) for x, pa, _ in pool]
    m = sum(shr) / len(shr)
    sd = (sum((s - m) ** 2 for s in shr) / len(shr)) ** 0.5
    anchor = sum(er * 27.0 / outs for _, _, (er, outs) in pool) / len(pool)
    return {'anchor': anchor, 'lgXw': lg_xw, 'm': m, 'sd': sd, 'dhB': DH_B_AAA, 'n': len(pool)}


def ibb_by_pitcher(pks):
    ibb = pd.read_csv(mc.IBB_PATH)
    ibb = ibb[ibb.game_pk.isin(pks)]
    return ibb.groupby(ibb.pitcherId.astype(str)).size().to_dict()


def wmean(pairs, nd):
    pairs = [(v, w) for v, w in pairs if v is not None and w]
    tw = sum(w for _v, w in pairs)
    return round(sum(v * w for v, w in pairs) / tw, nd) if tw else None


def score_batch(path, ibb):
    """Every pitcher in one batch file: his card row, per-type rows, split cells, HR/FB counts
    and per-pitch unrounded grades."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if not len(df):
        return {}
    df['_level'], df['_gameType'] = 'AAA', 'R'
    rows_all = df.to_dict('records')
    del df
    mc._to_mlb_currency(rows_all)
    by = defaultdict(list)
    for r in rows_all:
        by[r.pop('mlbId')].append(r)
    del rows_all
    norm = {}
    for mid, rows in by.items():
        rows.sort(key=lambda r: (r['Game Date'], r['PitchID']))
        norm[mid] = [P._normalize_scratch_pitch(r) for r in mc.as_sheet_rows(rows) if not is_no_pitch(r)]
    del by
    ctx = P._build_scratch_league_context(norm, stuff_k_shrink=P.K_SHRINK_DAILY, keep_cont=True)
    ctx['ibb_by_pitcher'] = {m: ibb.get(m, 0) for m in norm}
    ctx['xrv_estimate'] = False
    s_cont = ctx['stuff_cont_by_pid']
    out = {}
    for mid, pitches in norm.items():
        row, plb, _locp = P._compute_scratch_pitcher_context(mid, ctx)
        if row is None:
            continue
        rec = {k: row.get(k) for k in PITCHER_KEEP}
        rec.update(name=pitches[-1].get('Pitcher'), club=pitches[-1].get('PTeam'),
                   throws=pitches[-1].get('Throws'), tbf=row.get('pa'))
        grades, by_pt, cells = [], defaultdict(list), defaultdict(list)
        acc = [0, 0, 0, 0]   # fb, hr, pu, bip: _hrfb_pu_pools' rule
        for p in pitches:
            pt = p.get('Pitch Type')
            lc = ctx['loc_cont_fn'](p)
            grades.append([pt, s_cont.get(str(p.get('PitchID') or '')),
                           ctx['loc_group_fn'](p) if lc is not None else None, lc])
            if pt:
                by_pt[pt].append(p)
                if p.get('Bats') in ('L', 'R'):
                    cells[(p.get('Bats'), pt)].append(p)
            if p.get('Description') == 'In Play':
                bb = str(p.get('BBType') or '')
                if bb and not bb.startswith('bunt'):
                    acc[3] += 1
                    if bb == 'fly_ball':
                        acc[0] += 1
                        acc[1] += p.get('Event') == 'Home Run'
                    elif bb == 'popup':
                        acc[2] += 1
        rec['hrfb'] = acc
        pts = {}
        for pt, pp in by_pt.items():
            cs = compute_stats(pp)
            xs = compute_expected_stats(pp, None)
            ext = [v for v in (safe_float(x.get('Extension')) for x in pp) if v is not None]
            d = {'count': len(pp), 'velocity': (plb.get(pt) or {}).get('velocity'),
                 'nVAA': (plb.get(pt) or {}).get('nVAA'), 'nBip': cs.get('nBip'), 'pa': cs.get('pa'),
                 'xwOBAcon': xs.get('xwOBAcon'),
                 'extension': sum(ext) / len(ext) if ext else None}
            d.update({k: cs.get(k) for k in PT_RATE_KEYS})
            pts[pt] = d
        soc = []
        for (bh, pt), pp in cells.items():
            n = len(pp)
            st = sum(p.get('Description') in P.STRIKE_DESC for p in pp)
            sw = sum(p.get('Description') in P.SWING_DESC for p in pp)
            wh = sum(p.get('Description') in WHIFF_DESCRIPTIONS for p in pp)
            bip = [p for p in pp if p.get('Description') == 'In Play']
            xw = compute_expected_stats(bip, None).get('xwOBAcon') if bip else None
            soc.append([rec['throws'], bh, pt, n, st, sw, wh, len(bip), xw])
        out[mid] = {'rec': rec, 'pts': pts, 'soc': soc, 'grades': grades}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=None, help='Smoke test on the first N pitcher IDs')
    args = ap.parse_args()
    t0 = time.time()
    lg_era, n_teams = league_era()
    print(f'AAA league ERA {lg_era:.3f} over {n_teams} clubs', flush=True)
    paths, team_games = split_batches(args.limit)
    print(f'{len(team_games)} AAA clubs, median {sorted(team_games.values())[len(team_games) // 2]} games '
          f'({time.time() - t0:.0f}s)', flush=True)
    man = pd.read_csv(mc.MANIFEST_PATH, usecols=['game_pk', 'level', 'gameType'])
    ibb = ibb_by_pitcher(set(man[(man.level == 'AAA') & (man.gameType == 'R')].game_pk))

    got = {}
    for i, path in enumerate(paths):
        got.update(score_batch(path, ibb))
        print(f'batch {i + 1}/{N_BATCH}: {len(got)} pitchers ({time.time() - t0:.0f}s)', flush=True)
    if len(got) < (30 if args.limit else 500):
        sys.exit(f'Only {len(got)} AAA pitchers scored. Not writing the pool.')

    # The shift: the AAA mean of the unrounded MLB-anchored grade, less 100.
    s_sum, l_sum = defaultdict(lambda: [0.0, 0]), defaultdict(lambda: [0.0, 0])
    for g in got.values():
        for pt, s, grp, lc in g['grades']:
            if pt and s is not None:
                s_sum[pt][0] += s
                s_sum[pt][1] += 1
            if grp is not None:
                l_sum[grp][0] += lc
                l_sum[grp][1] += 1
    stuff_shift = {pt: a / n - 100 for pt, (a, n) in s_sum.items() if n}
    loc_shift = {grp: a / n - 100 for grp, (a, n) in l_sum.items() if n}
    print('Stuff+ shift by type (AAA mean - 100):',
          {pt: f'{v:+.2f} ({s_sum[pt][1]})' for pt, v in sorted(stuff_shift.items())})
    print('Loc+ shift by group:', {g: f'{v:+.2f} ({l_sum[g][1]})' for g, v in sorted(loc_shift.items())})

    # Re-round every grade on the shift, as the card does.
    pitchers, pitch_types = {}, {}
    for mid, g in got.items():
        rec = g['rec']
        s_all, l_all, s_mlb, l_mlb = [], [], [], []
        s_pt, l_pt = defaultdict(list), defaultdict(list)
        for pt, s, grp, lc in g['grades']:
            if pt and s is not None:
                a = int(round(s - stuff_shift.get(pt, 0.0)))
                s_all.append(a)
                s_pt[pt].append(a)
                s_mlb.append(int(round(s)))
            if grp is not None:
                a = int(round(lc - loc_shift.get(grp, 0.0)))
                l_all.append(a)
                if pt:
                    l_pt[pt].append(a)
                l_mlb.append(int(round(lc)))
        rec['stuffScore'] = sum(s_all) / len(s_all) if s_all else None
        rec['locPlus'] = round(sum(l_all) / len(l_all), 1) if l_all else None
        rec['stuffScoreMLB'] = sum(s_mlb) / len(s_mlb) if s_mlb else None
        rec['locPlusMLB'] = round(sum(l_mlb) / len(l_mlb), 1) if l_mlb else None
        for pt, d in g['pts'].items():
            d['stuffScore'] = sum(s_pt[pt]) / len(s_pt[pt]) if s_pt.get(pt) else None
            d['locPlus'] = round(sum(l_pt[pt]) / len(l_pt[pt]), 1) if l_pt.get(pt) else None
        pitchers[mid] = rec
        pitch_types[mid] = g['pts']

    # Pitcher+ on the AAA pool's own baseline (shipped rule: 300 pitches, count-weighted mu).
    rows = [dict(r, team=r['club']) for r in pitchers.values()]
    base = build_baseline(rows, aaa_teams=())
    if base is None:
        sys.exit('Pitcher+ baseline came back empty (fewer than 50 pitchers at 300 pitches).')
    for mid, r in pitchers.items():
        v = score_row(dict(r, team=r['club']), base)
        r['pitcherPlus'] = None if (r.get('stuffScore') is None or r.get('xRv100') is None) else v
    print('Pitcher+ AAA baseline:', {k: (round(m, 4), round(s, 4)) for k, (m, s) in base.items()})

    # League averages, the process_data rules: per type by pitches (xwOBAcon by BIP), overall by
    # pitches with K%/BB% by batters faced.
    by_pt = defaultdict(list)
    for pts in pitch_types.values():
        for pt, d in pts.items():
            by_pt[pt].append(d)
    lg = {}
    for pt, ds in by_pt.items():
        a = {k: wmean([(d.get(k), d['count']) for d in ds], 2) for k in ('velocity', 'extension')}
        a.update({k: wmean([(d.get(k), d['count']) for d in ds], 4) for k in PT_RATE_KEYS})
        a['xwOBAcon'] = wmean([(d.get('xwOBAcon'), d.get('nBip')) for d in ds], 4)
        a['count'] = len(ds)
        lg[pt] = a
    pr = list(pitchers.values())
    plg = {k: wmean([(r.get(k), r.get('count')) for r in pr], 4)
           for k in ('izPct', 'cswPct', 'swStrPct', 'chasePct', 'gbPct', 'fpsPct', 'izWhiffPct',
                     'extension', 'fbVelo', 'stuffScore', 'locPlus')}
    plg.update({k: wmean([(r.get(k), r.get('pa')) for r in pr], 4) for k in ('kPct', 'bbPct', 'kbbPct', 'xwOBA')})
    plg['xwOBAcon'] = wmean([(r.get('xwOBAcon'), r.get('nBip')) for r in pr], 4)
    plg.update(era=round(lg_era, 2), lgERA=round(lg_era, 4), fip=round(lg_era, 2), xFIP=round(lg_era, 2))
    plg['count'] = len(pr)
    era = pitcher_era()
    hd = hdera_scale(pitchers, era)
    plg['hdera'] = round(hd['anchor'], 2)
    # Every pitcher's ERA and AAA-scale hdERA, for the card's ERA and hdERA tile ranks.
    for mid, r in pitchers.items():
        er, outs = era.get(mid, (None, 0))
        r['era'] = er * 27.0 / outs if outs else None
        r['hdERA'] = None
        if r.get('xwOBA') is not None and r.get('pa'):
            shr = (r['xwOBA'] * r['pa'] + N0_XW * hd['lgXw']) / (r['pa'] + N0_XW)
            r['hdERA'] = hd['anchor'] + hd['dhB'] * (shr - hd['m']) / hd['sd']
    print('hdERA AAA scale:', {k: round(v, 4) for k, v in hd.items()})

    soc = [c for g in got.values() for c in g['soc']]
    pool = {
        'meta': {'built': date.today().isoformat(), 'season': SEASON, 'pitches': sum(len(g['grades']) for g in got.values()),
                 'teamGames': team_games, 'gate': 'PCTL_BF_PER_GAME_MLB x team games of the last club',
                 'source': 'data/_milb2026 AAA regular season', 'smoke': bool(args.limit)},
        'shift': {'stuff': stuff_shift, 'loc': loc_shift},
        'pitchers': pitchers,
        'pitchTypes': pitch_types,
        'pitcherPlusBase': {k: list(v) for k, v in base.items()},
        'socialCells': soc,
        'leagueAverages': lg,
        'pitcherLeagueAverages': plg,
        'hdera': hd,
    }
    name = 'pitcher_pool_AAA_smoke.json' if args.limit else 'pitcher_pool_AAA.json'
    tmp = os.path.join(OUT, name + '.tmp')
    with open(tmp, 'w') as f:
        json.dump(pool, f)
    os.replace(tmp, os.path.join(OUT, name))
    q = P.aaa_qualified(pool)
    print(f'Wrote {name}: {len(pitchers)} pitchers, {len(q)} in the percentile pool, '
          f'{len(soc)} split cells ({time.time() - t0:.0f}s)')
    for p in paths:
        os.remove(p)
    os.remove(os.path.join(OUT, f"_aaa_pbatch{'_smoke' if args.limit else ''}_teamgames.json"))


if __name__ == '__main__':
    main()
