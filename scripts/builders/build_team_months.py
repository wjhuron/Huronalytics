#!/usr/bin/env python3
"""Build data/team_months/, the hitter-month rows behind the hidden Team by
Month section (?roc=1 only).

One row per (hitter, MLB club, month) for every 2026 MLB hitter stint, plus a
Season row per stint. The scoring is the Twins tracker's
(scripts/tools/twins_monthly_tracker.py), run for every club:

  * VALUES come from the month's pitches; every league anchor and cell table
    is the SEASON's (the window_pool rule). All months go through ONE
    compute_sd_plus / compute_ct_plus call via extra_groups, outside the
    anchor pool.
  * BB+ / SD+ / CT+ are RAW (unshrunk, prior-free, through the post-chain),
    keyed bbPlusU / sdPlusU / ctPlusU. The Season row carries the raw values
    too, so a month and its season compare on one construction.
  * The official line (PA, AVG/OBP/SLG, wOBA, BABIP, K%, BB%, HR, wRC+) is
    FanGraphs' date-range line. A month in which the hitter batted for two
    clubs keeps the pitch-derived line for each stint (lineSource 'pitch'),
    because the FanGraphs range row is the combined line. The Season row is
    the shipped leaderboard row for every shipped column.
  * Percentiles: VALUES from the month, PERCENTILES from the SEASON pool of
    all MLB players (no qualification), the window_pool rule. Shipped columns
    rank inside the shipped season values; the raw + stats and wOBAcon rank
    inside the same quantities computed here for every MLB player's season,
    so a raw month is never ranked against regressed season values.

Output (rebuilt whole, written to a temp dir and swapped in):
  data/team_months/index.json   teams, months, column notes, generatedAt
  data/team_months/<TEAM>.json  that club's rows

The 2026 season is over, so one run covers it. Re-run after the pickle or the
leaderboard moves, then commit data/team_months/:

    PYTHONHASHSEED=0 python3 scripts/builders/build_team_months.py
"""
import bisect
import json
import os
import pickle
import shutil
import sys
import tempfile
from collections import defaultdict
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from pipeline.utils import ALL_TEAMS, AAA_TEAMS, is_combined_team, safe_float, BUNT_BB_TYPES  # noqa: E402
from pipeline.compute import HITTER_INVERT_PCTL  # noqa: E402
from pipeline.window_pool import (bb_plus_chain, plus_post_chain,  # noqa: E402
                                  process_plus_from_atoms, wrc_plus_formula,
                                  _season_pool_rows)
from pipeline.splits import hitter_split_rows  # noqa: E402
from pipeline.sdplus import compute_sd_plus  # noqa: E402
from pipeline.contact import compute_ct_plus  # noqa: E402
from pipeline.fg_overrides import fetch_mlb_hitters_range  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'tools'))
from twins_monthly_tracker import MONTHS, add_xwoba_hb, woba_con, raw_plus  # noqa: E402

DATA = os.path.join(ROOT, 'data')
OUT_DIR = os.path.join(DATA, 'team_months')
SEASON = 'Season'
ALL = '_ALL'            # every MLB pitch of one batter: the raw-pool season group

# Every key a row ships. The site picks its columns from these.
KEYS = ['pa', 'count', 'nSwings', 'nBip', 'nCompSwings',
        'avg', 'obp', 'slg', 'hr', 'babip', 'wOBA', 'xwOBA', 'wRCplus', 'xWRCplus',
        'wOBAcon', 'xwOBAcon', 'processPlus', 'bbPlusU', 'ctPlusU', 'sdPlusU',
        'kPct', 'bbPct', 'izSwingPct', 'chasePct', 'izContactPct', 'whiffPct',
        'twoStrikeWhiffPct', 'firstPitchSwingPct',
        'avgEVAll', 'ev95', 'hardHitPct', 'barrelPct', 'medLA', 'gbPct', 'fbPct',
        'pullPct', 'airPullPct',
        'batSpeed', 'swingLength', 'attackAngle', 'squaredUpPct', 'blastPct']
COUNT_KEYS = {'pa', 'count', 'nSwings', 'nBip', 'nCompSwings', 'hr'}
RAW_POOL_KEYS = {'bbPlusU': 'bbPlusU', 'ctPlusU': 'ctPlusU', 'sdPlusU': 'sdPlusU', 'wOBAcon': 'wOBAcon'}
STORE_DP = 5            # storage precision; display rounds further


def is_mlb_team(t):
    return t in ALL_TEAMS and t not in AAA_TEAMS and not is_combined_team(t)


class Pools:
    """Sorted season pools, ranked with window_pool.add_season_percentiles'
    formula (below + half the ties, over the pool) by bisection."""

    def __init__(self, shipped_rows, raw_rows):
        self.pools = {}
        pool_rows = _season_pool_rows(shipped_rows)
        for k in KEYS:
            if k in COUNT_KEYS:
                continue
            src = raw_rows if k in RAW_POOL_KEYS else pool_rows
            vals = sorted(r[k] for r in src if r.get(k) is not None)
            if len(vals) >= 10:
                self.pools[k] = vals

    def pctl(self, k, v):
        pool = self.pools.get(k)
        if pool is None or v is None:
            return None
        lo = bisect.bisect_left(pool, v)
        hi = bisect.bisect_right(pool, v)
        p = (lo + 0.5 * (hi - lo)) / len(pool) * 100.0
        if k in HITTER_INVERT_PCTL:
            p = 100.0 - p
        return max(0, min(100, round(p)))


def store(v):
    if isinstance(v, float):
        return round(v, STORE_DP)
    return v


def main():
    print('Loading pickle, metadata, leaderboard...')
    with open(os.path.join(DATA, 'all_pitches_rs_cache.pkl'), 'rb') as f:
        all_pitches = pickle.load(f)
    with open(os.path.join(DATA, 'metadata_rs.json')) as f:
        metadata = json.load(f)
    with open(os.path.join(DATA, 'hitter_leaderboard_rs.json')) as f:
        season_rows = json.load(f)
    dates = [p['Game Date'] for p in all_pitches if p.get('Game Date')]
    print(f'  {len(all_pitches)} pitches, {min(dates)} to {max(dates)}')
    add_xwoba_hb(all_pitches)
    G = metadata.get('gutsConstants') or {}
    weights = metadata['wobaWeights']

    ep = {(p.get('Pitcher'), p.get('PTeam')) for p in all_pitches if p.get('Pitch Type') == 'EP'}
    skill_league = [p for p in all_pitches if (p.get('Pitcher'), p.get('PTeam')) not in ep]
    by = defaultdict(list)
    for p in skill_league:
        if p.get('_roc_pitcher_pitch'):
            continue
        b, bt = p.get('Batter'), p.get('BTeam')
        if b and bt and bt in ALL_TEAMS:
            by[(b, bt)].append(p)

    stints = defaultdict(list)      # (batter, club) -> every pitch, MLB clubs only
    batter_all = defaultdict(list)  # batter -> every MLB pitch (raw season pool)
    for p in all_pitches:
        b, bt = p.get('Batter'), p.get('BTeam')
        if b and is_mlb_team(bt) and p.get('_source', 'MLB') == 'MLB':
            stints[(b, bt)].append(p)
            batter_all[b].append(p)
    month_clubs = defaultdict(set)  # (batter, month) -> clubs he batted for
    for (b, t), ps in stints.items():
        for label, lo, hi in MONTHS:
            if any(lo <= (p.get('Game Date') or '') <= hi for p in ps):
                month_clubs[(b, label)].add(t)

    groups = {}
    for (b, t), ps in stints.items():
        groups[(b, t, SEASON)] = ps
        for label, lo, hi in MONTHS:
            sub = [p for p in ps if lo <= (p.get('Game Date') or '') <= hi]
            if sub:
                groups[(b, t, label)] = sub
    for b, ps in batter_all.items():
        groups[(b, ALL, SEASON)] = ps
    skill_groups = {k: [p for p in ps if (p.get('Pitcher'), p.get('PTeam')) not in ep]
                    for k, ps in groups.items()}
    print(f'  {len(stints)} hitter stints on {len({t for _, t in stints})} clubs, '
          f'{len(groups)} groups')

    print('Building rows...')
    rows = hitter_split_rows(groups, skill_groups, weights)
    print('Scoring SD+ against season cell tables...')
    _, _, sd_extra = compute_sd_plus(skill_league, dict(by), lg_woba=G.get('lgWOBA'),
                                     woba_scale=G.get('wOBAScale'), extra_groups=skill_groups)
    print('Scoring CT+ against season cell tables...')
    ctp = metadata.get('ctPlusBtPrior') or {}
    cta = ctp.get('anchors') or {}
    bt_z = {}
    for k, r in rows.items():
        if cta.get('bsSd') and r.get('batSpeed') is not None and (r.get('nCompSwings') or 0) > 0:
            bt_z[k] = ((r['batSpeed'] - cta['bsMean']) / cta['bsSd'], r['nCompSwings'])
    _, _, ct_extra = compute_ct_plus(skill_league, dict(by), lg_woba=G.get('lgWOBA'),
                                     woba_scale=G.get('wOBAScale'), bt_z=bt_z,
                                     bt_beta=ctp.get('betaBs') or 0.0, bt_k=ctp.get('k') or 0,
                                     bt_s0=ctp.get('s0') or 0, extra_groups=skill_groups)

    scored = {}
    for key, base in rows.items():
        row = dict(base)
        s, c = sd_extra.get(key), ct_extra.get(key)
        row['sdPlus'] = s['sdPlus'] if s else None
        row['_procSd'] = s['raw_sd'] if s else None
        row['ctPlus'] = c['ctPlus'] if c else None
        row['_procCt'] = c['raw_ct'] if c else None
        bb_plus_chain(row, metadata)
        plus_post_chain(row, metadata)
        process_plus_from_atoms(row, metadata)
        wrc_plus_formula(row, key[1] if key[1] != ALL else None, metadata)
        row.update(raw_plus(row, s, c, metadata))
        row['wOBAcon'] = woba_con(groups[key], weights)
        scored[key] = row

    raw_rows = [r for (b, t, m), r in scored.items() if t == ALL]
    pools = Pools(season_rows, raw_rows)

    shipped = {(r['hitter'], r['team']): r for r in season_rows}
    fg = {}
    for label, lo, hi in MONTHS:
        print(f'FanGraphs official line {lo} to {hi}...')
        fg[label] = fetch_mlb_hitters_range(lo, hi)
        if not fg[label]:
            raise SystemExit(f'FanGraphs range {lo}..{hi} returned nothing. Nothing was '
                             f'written; re-run when the endpoint answers.')

    # Self-check: each stint's Season group against its shipped row.
    checks = {'xwOBA': 0.0005, 'xwOBAcon': 0.0005, 'chasePct': 0.0005, 'whiffPct': 0.0005,
              'ev95': 0.05, 'batSpeed': 0.05, 'processPlus': 0.5}
    print('\nSelf-check, stint Season group vs shipped row:')
    bad = False
    for k, tol in checks.items():
        n = good = 0
        for (b, t, m), r in scored.items():
            if m != SEASON or t == ALL or (b, t) not in shipped:
                continue
            a, sv = r.get(k), shipped[(b, t)].get(k)
            if a is None or sv is None:
                continue
            n += 1
            good += abs(a - sv) <= tol
        share = good / n if n else 0
        print(f'  {k:12s} {good}/{n} within {tol} ({share:.1%})')
        bad |= share < 0.98
    if bad:
        raise SystemExit('Season groups do not reproduce the shipped rows. Nothing was written.')

    by_team = defaultdict(list)
    n_fg = n_pitch = n_missing_id = 0
    for (b, t, m), r in sorted(scored.items()):
        if t == ALL:
            continue
        ship = shipped.get((b, t))
        mid = ship.get('mlbId') if ship else None
        out = {'hitter': b, 'team': t, 'month': m, 'mlbId': mid,
               'stands': ship.get('stands') if ship else None,
               'position': ship.get('position') if ship else None}
        if m == SEASON:
            if ship is None:
                n_missing_id += 1
                print(f'  {b} {t}: no shipped season row, Season row kept pitch-derived')
            vals = {k: (r.get(k) if (ship is None or k in RAW_POOL_KEYS) else ship.get(k))
                    for k in KEYS}
            out['lineSource'] = 'leaderboard' if ship else 'pitch'
        else:
            vals = {k: r.get(k) for k in KEYS}
            hit = fg[m].get(str(int(mid))) if mid else None
            two_clubs = len(month_clubs[(b, m)]) > 1
            if hit and hit.get('pa') and not two_clubs:
                for src, nd in (('pa', 0), ('hr', 0), ('avg', 3), ('obp', 3), ('slg', 3),
                                ('wOBA', 3), ('babip', 3), ('bbPct', 4), ('kPct', 4)):
                    if hit.get(src) is not None:
                        vals[src] = int(hit[src]) if nd == 0 else round(hit[src], nd)
                if hit.get('wRCplus') is not None:
                    vals['wRCplus'] = hit['wRCplus']
                out['lineSource'] = 'FanGraphs'
                n_fg += 1
            else:
                out['lineSource'] = 'pitch'
                n_pitch += 1
        for k in KEYS:
            out[k] = store(vals.get(k))
            if k not in COUNT_KEYS:
                out[k + '_pctl'] = pools.pctl(k, vals.get(k))
        by_team[t].append(out)
    print(f'\nMonth lines: {n_fg} FanGraphs, {n_pitch} pitch-derived (two clubs in the '
          f'month or no FanGraphs row); {n_missing_id} Season rows without a shipped row')

    lg = dict(metadata.get('hitterLeagueAverages') or {})
    lg_stints = [r for r in season_rows if is_mlb_team(r.get('team')) and r.get('pa')
                 and r.get('kPct') is not None]
    lg['kPct'] = sum(r['kPct'] * r['pa'] for r in lg_stints) / sum(r['pa'] for r in lg_stints)
    mlb_pitches = [p for ps in batter_all.values() for p in ps]
    lg['wOBAcon'] = woba_con(mlb_pitches, weights)
    las = sorted(v for v in (safe_float(p.get('LaunchAngle')) for p in mlb_pitches
                             if p.get('Description') == 'In Play'
                             and (p.get('BBType') or '') not in BUNT_BB_TYPES) if v is not None)
    lg['medLA'] = las[len(las) // 2]
    for k in ('processPlus', 'bbPlusU', 'ctPlusU', 'sdPlusU', 'wRCplus', 'xWRCplus'):
        lg[k] = 100
    index = {
        'generatedAt': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'dataThrough': max(dates),
        'months': [m for m, _, _ in MONTHS] + [SEASON],
        'monthRanges': {m: [lo, hi] for m, lo, hi in MONTHS},
        'teams': sorted(by_team),
        'leagueAverages': {k: store(lg.get(k)) for k in KEYS if lg.get(k) is not None},
    }

    tmp = tempfile.mkdtemp(prefix='team_months_', dir=DATA)
    os.chmod(tmp, 0o755)    # mkdtemp makes it 0700
    try:
        for t, rs in by_team.items():
            with open(os.path.join(tmp, f'{t}.json'), 'w') as f:
                json.dump({'team': t, 'rows': rs}, f, separators=(',', ':'))
        with open(os.path.join(tmp, 'index.json'), 'w') as f:
            json.dump(index, f, separators=(',', ':'))
        if os.path.isdir(OUT_DIR):
            shutil.rmtree(OUT_DIR)
        os.replace(tmp, OUT_DIR)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    size = sum(os.path.getsize(os.path.join(OUT_DIR, f)) for f in os.listdir(OUT_DIR))
    print(f'Wrote {OUT_DIR}: {len(by_team)} clubs, '
          f'{sum(len(v) for v in by_team.values())} rows, {size / 1e6:.1f} MB')


if __name__ == '__main__':
    main()
