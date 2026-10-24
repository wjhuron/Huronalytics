#!/usr/bin/env python3
"""twins_monthly_tracker.py — month-by-month rows for every 2026 Twins hitter.

Each (hitter, month) is a date window scored the window_pool way: the VALUES
come from the month's pitches, every league anchor and cell table is the
SEASON's. All months are scored in ONE compute_sd_plus / compute_ct_plus call
through extra_groups (the pipeline/splits.py pattern), so they sit outside the
anchor pool and on the season ruler.

BB+ / SD+ / CT+ are RAW: the unshrunk, prior-free atoms Process+ is built from
(_procBb / _procSd / _procCt), carried through the same post-chain as the
displayed values (slope match, plusReanchor, plusWrcScale). A month is not
pulled toward 100 by its sample size, so months compare to each other and to
the raw season value.

Official line (PA, AVG/OBP/SLG, wOBA, BABIP, K%, BB%, HR, wRC+) comes from
FanGraphs' date-range endpoint, as on the window cards. A month in which the
hitter also batted for another club keeps the pitch-derived line, because the
FanGraphs range row is the player's combined line.

wOBAcon is wOBA on non-bunt balls in play (home runs included), the
xwOBAcon denominator, priced with the season wOBA weights.

SELF-CHECK. A SEASON group per hitter runs through the same path and is
compared with the shipped leaderboard row. Process+ is the composite of the
three raw atoms, so agreement there validates the raw BB+/SD+/CT+ inputs.

Output: data/_twins_monthly.json (scratch). The workbook is written by
scripts/tools/twins_monthly_xlsx.py.

Usage: python3 scripts/tools/twins_monthly_tracker.py
"""
import json
import os
import pickle
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from pipeline.utils import (safe_float, spray_angle, spray_direction,          # noqa: E402
                            BUNT_BB_TYPES, ALL_TEAMS, is_combined_team,
                            XWOBA_PULLAIR_C, XWOBA_PULLAIR_LA, XWOBA_PULLAIR_LGSHARE)
from pipeline.window_pool import (build_window_hitter_row, bb_plus_chain,      # noqa: E402
                                  plus_post_chain, process_plus_from_atoms,
                                  wrc_plus_formula)
from pipeline.splits import hitter_split_rows                                  # noqa: E402
from pipeline.sdplus import compute_sd_plus                                    # noqa: E402
from pipeline.contact import compute_ct_plus                                   # noqa: E402
from pipeline.fg_overrides import fetch_mlb_hitters_range                      # noqa: E402

TEAM = 'MIN'
SEASON = 'Season'
# Late-March games (Opening Day 2026-03-26) are folded into April.
MONTHS = [('Mar/Apr', '2026-03-26', '2026-04-30'),
          ('May', '2026-05-01', '2026-05-31'),
          ('Jun', '2026-06-01', '2026-06-30'),
          ('Jul', '2026-07-01', '2026-07-31'),
          ('Aug', '2026-08-01', '2026-08-31'),
          ('Sep', '2026-09-01', '2026-09-30')]
EVENT_WEIGHT_KEY = {'Single': '1B', 'Double': '2B', 'Triple': '3B', 'Home Run': 'HR'}
OUT = os.path.join(REPO, 'data', '_twins_monthly.json')


def add_xwoba_hb(all_pitches):
    """The pulled-air hitter xwOBA (xwOBA_hb), copied from process_data: the
    pickle stores raw xwOBA only, and compute_expected_stats falls back to raw
    when the key is absent, which would put window xwOBA on a different basis
    from the season row."""
    n_air = n_pull = 0
    for p in all_pitches:
        if (p.get('_source', 'MLB') == 'MLB' and p.get('Description') == 'In Play'
                and (p.get('BBType') or '') not in BUNT_BB_TYPES):
            la = safe_float(p.get('LaunchAngle'))
            if la is None or la < XWOBA_PULLAIR_LA:
                continue
            sd = spray_direction(spray_angle(safe_float(p.get('HC_X')),
                                             safe_float(p.get('HC_Y'))), p.get('Bats'))
            if sd is None:
                continue
            n_air += 1
            n_pull += sd in ('pull', 'pull_side')
    if n_air >= 5000:
        share = n_pull / n_air
    else:
        share = XWOBA_PULLAIR_LGSHARE
        print(f"  xwOBA_hb WARNING: only {n_air} MLB air BIPs, frozen share {share} used")
    for p in all_pitches:
        xw = safe_float(p.get('xwOBA'))
        if xw is None:
            continue
        p['xwOBA_hb'] = xw
        if p.get('Description') == 'In Play' and (p.get('BBType') or '') not in BUNT_BB_TYPES:
            la = safe_float(p.get('LaunchAngle'))
            if la is None or la < XWOBA_PULLAIR_LA:
                continue
            sd = spray_direction(spray_angle(safe_float(p.get('HC_X')),
                                             safe_float(p.get('HC_Y'))), p.get('Bats'))
            if sd is None:
                continue
            p['xwOBA_hb'] = xw + XWOBA_PULLAIR_C * ((sd in ('pull', 'pull_side')) - share)
    print(f"  xwOBA_hb: league pull share {share:.3f} on {n_air} MLB air BIPs")


def woba_con(pitches, weights):
    """wOBA on non-bunt balls in play, home runs included."""
    num = den = 0
    for p in pitches:
        if p.get('Description') != 'In Play' or (p.get('BBType') or '') in BUNT_BB_TYPES:
            continue
        den += 1
        k = EVENT_WEIGHT_KEY.get(p.get('Event'))
        if k:
            num += weights[k]
    return (num / den) if den else None


def post_chain(v, key, metadata):
    """plusReanchor then the plusWrcScale factor/shift: the stages applied after
    the raw computation in the season path (window_pool.plus_post_chain)."""
    v *= (metadata.get('plusReanchor') or {}).get(key) or 1.0
    wrc = (metadata.get('plusWrcScale') or {}).get(key) or {}
    if wrc.get('factor'):
        v = 100.0 + (v - 100.0) * wrc['factor'] + (wrc.get('shift') or 0.0)
    return v


def raw_plus(row, s, c, metadata):
    """Unshrunk BB+ / SD+ / CT+ on the displayed scale. Keyed *U, not *Raw:
    the leaderboard's sdPlusRaw / ctPlusRaw are the shrunk atoms in their own
    units, a different quantity."""
    out = {'bbPlusU': None, 'sdPlusU': None, 'ctPlusU': None}
    if row.get('_procBb') is not None:
        slope = metadata.get('bbPlusSlopeMatch') or 1.2352
        out['bbPlusU'] = post_chain(100.0 + (row['_procBb'] - 100.0) * slope, 'bbPlus', metadata)
    # sdPlus = 100 * raw_adj / lg_mean, so the raw value on the same ruler is
    # sdPlus * raw / raw_adj (lg_mean cancels). Same identity for CT+.
    if s and s.get('raw_sd_adj'):
        out['sdPlusU'] = post_chain(s['sdPlus'] * s['raw_sd'] / s['raw_sd_adj'], 'sdPlus', metadata)
    if c and c.get('raw_ct_adj'):
        out['ctPlusU'] = post_chain(c['ctPlus'] * c['raw_ct'] / c['raw_ct_adj'], 'ctPlus', metadata)
    return out


def main():
    print("Loading pickle, metadata, leaderboard...")
    with open(os.path.join(REPO, 'data', 'all_pitches_rs_cache.pkl'), 'rb') as f:
        all_pitches = pickle.load(f)
    with open(os.path.join(REPO, 'data', 'metadata_rs.json')) as f:
        metadata = json.load(f)
    with open(os.path.join(REPO, 'data', 'hitter_leaderboard_rs.json')) as f:
        season_rows = json.load(f)
    dates = [p['Game Date'] for p in all_pitches if p.get('Game Date')]
    print(f"  {len(all_pitches)} pitches, {min(dates)} to {max(dates)}")
    add_xwoba_hb(all_pitches)
    G = metadata.get('gutsConstants') or {}
    weights = metadata['wobaWeights']

    # League groups, as window_pool builds them: position-player pitching out.
    ep = {(p.get('Pitcher'), p.get('PTeam')) for p in all_pitches if p.get('Pitch Type') == 'EP'}
    skill_league = [p for p in all_pitches if (p.get('Pitcher'), p.get('PTeam')) not in ep]
    by = defaultdict(list)
    for p in skill_league:
        if p.get('_roc_pitcher_pitch'):
            continue
        b, bt = p.get('Batter'), p.get('BTeam')
        if b and bt and bt in ALL_TEAMS:
            by[(b, bt)].append(p)

    twins = defaultdict(list)
    for p in all_pitches:
        if p.get('BTeam') == TEAM and p.get('Batter'):
            twins[p['Batter']].append(p)
    other_team_dates = defaultdict(set)   # dates a Twins hitter batted for another MLB club
    for p in all_pitches:
        if p.get('Batter') in twins and p.get('BTeam') not in (TEAM, None, 'ROC', 'AAA'):
            other_team_dates[p['Batter']].add(p['Game Date'])

    groups, skill_groups = {}, {}
    for b, ps in twins.items():
        windows = [(SEASON, '0000', '9999')] + MONTHS
        for label, lo, hi in windows:
            sub = [p for p in ps if lo <= (p.get('Game Date') or '') <= hi]
            if not sub:
                continue
            groups[(b, TEAM, label)] = sub
            skill_groups[(b, TEAM, label)] = [
                p for p in sub if (p.get('Pitcher'), p.get('PTeam')) not in ep]
    print(f"  {len(twins)} Twins hitters, {len(groups)} hitter windows")

    rows = hitter_split_rows(groups, skill_groups, weights)

    print("Scoring SD+ against season cell tables...")
    _, _, sd_extra = compute_sd_plus(skill_league, dict(by), lg_woba=G.get('lgWOBA'),
                                     woba_scale=G.get('wOBAScale'), extra_groups=skill_groups)
    print("Scoring CT+ against season cell tables...")
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

    mlb_id = {}
    for r in season_rows:
        if r.get('team') == TEAM and r.get('mlbId'):
            mlb_id[r['hitter']] = r['mlbId']

    fg = {}
    for label, lo, hi in MONTHS:
        print(f"FanGraphs official line {lo} to {hi}...")
        fg[label] = fetch_mlb_hitters_range(lo, hi)
        if not fg[label]:
            raise SystemExit(f"FanGraphs range {lo}..{hi} returned nothing. "
                             f"Re-run when the endpoint answers; no workbook was written.")

    out = []
    n_official = n_pitch_line = 0
    for key, base in rows.items():
        b, _, label = key
        row = dict(base)
        s, c = sd_extra.get(key), ct_extra.get(key)
        row['sdPlus'] = s['sdPlus'] if s else None
        row['_procSd'] = s['raw_sd'] if s else None
        row['ctPlus'] = c['ctPlus'] if c else None
        row['_procCt'] = c['raw_ct'] if c else None
        bb_plus_chain(row, metadata)
        plus_post_chain(row, metadata)
        process_plus_from_atoms(row, metadata)
        wrc_plus_formula(row, TEAM, metadata)
        row.update(raw_plus(row, s, c, metadata))
        row['wOBAcon'] = woba_con(groups[key], weights)
        row['hitter'], row['month'], row['mlbId'] = b, label, mlb_id.get(b)
        row['lineSource'] = 'pitch'
        if label != SEASON:
            lo, hi = next((lo, hi) for m, lo, hi in MONTHS if m == label)
            shared = any(lo <= d <= hi for d in other_team_dates.get(b, ()))
            hit = fg[label].get(str(int(row['mlbId']))) if row['mlbId'] else None
            if hit and hit.get('pa') and not shared:
                for src, nd in (('pa', 0), ('hr', 0), ('avg', 3), ('obp', 3), ('slg', 3),
                                ('wOBA', 3), ('babip', 3), ('bbPct', 4), ('kPct', 4)):
                    if hit.get(src) is not None:
                        row[src] = int(hit[src]) if nd == 0 else round(hit[src], nd)
                if hit.get('wRCplus') is not None:
                    row['wRCplus'] = hit['wRCplus']
                row['lineSource'] = 'FanGraphs'
                n_official += 1
            else:
                n_pitch_line += 1
                print(f"  {b} {label}: pitch-derived line kept "
                      f"({'also batted for another club' if shared else 'no FanGraphs row'})")
        out.append({k: v for k, v in row.items() if not k.startswith('_')})
    print(f"  official line: {n_official} months FanGraphs, {n_pitch_line} pitch-derived")

    # Self-check: SEASON group against the shipped row.
    season = {r['hitter']: r for r in season_rows if r.get('team') == TEAM}
    checks = ('pa', 'xwOBA', 'xwOBAcon', 'xWRCplus', 'processPlus', 'bbPlus', 'sdPlus', 'ctPlus',
              'chasePct', 'izContactPct', 'whiffPct', 'ev95', 'barrelPct', 'hardHitPct',
              'batSpeed', 'squaredUpPct')
    print("\nSelf-check, Season group vs shipped leaderboard (max |diff| over hitters):")
    for k in checks:
        diffs = []
        for r in out:
            if r['month'] != SEASON or r['hitter'] not in season:
                continue
            a, sv = r.get(k), season[r['hitter']].get(k)
            if a is not None and sv is not None:
                diffs.append((abs(a - sv), r['hitter']))
        if diffs:
            d, who = max(diffs)
            print(f"  {k:13s} n={len(diffs):2d}  max {d:.4f} ({who})")

    # League reference row: the shipped league averages, plus the three this
    # sheet needs that hitterLeagueAverages does not carry.
    lg = dict(metadata.get('hitterLeagueAverages') or {})
    stints = [r for r in season_rows
              if r.get('team') not in ('ROC', 'AAA') and not is_combined_team(r.get('team'))
              and r.get('pa') and r.get('kPct') is not None]
    lg['kPct'] = sum(r['kPct'] * r['pa'] for r in stints) / sum(r['pa'] for r in stints)
    mlb = [p for p in all_pitches if p.get('_source', 'MLB') == 'MLB'
           and p.get('BTeam') not in ('ROC', 'AAA')]
    lg['wOBAcon'] = woba_con(mlb, weights)
    las = sorted(v for v in (safe_float(p.get('LaunchAngle')) for p in mlb
                             if p.get('Description') == 'In Play'
                             and (p.get('BBType') or '') not in BUNT_BB_TYPES) if v is not None)
    lg['medLA'] = las[len(las) // 2]
    print(f"  league K% {lg['kPct']:.4f}, wOBAcon {lg['wOBAcon']:.3f}, median LA {lg['medLA']}")

    tmp = OUT + '.tmp'
    with open(tmp, 'w') as f:
        json.dump({'months': [m for m, _, _ in MONTHS], 'rows': out,
                   'leagueAverages': lg,
                   'seasonRows': [season[b] for b in sorted(season)]}, f)
    os.replace(tmp, OUT)
    print(f"\nWrote {OUT} ({len(out)} rows)")


if __name__ == '__main__':
    main()
