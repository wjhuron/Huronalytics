"""milb_corpus.py — one player's rows from the 2026 MiLB corpus, for the cards.

scripts/builders/milb2026_pull.py writes the corpus and its three sidecars to
data/_milb2026/. This module is the only reader, and it answers the three
questions a card cannot answer from the rows alone:

    WHO   A row carries a name, and 19 corpus names are two players (Jacob Webb,
          Max Muncy). Rows are selected by mlbId through players.csv.gz. A name
          that resolves to two IDs stops the run and prints both; pass the ID.
    WHICH CURRENCY  RunExp is league-denominated. The factors come from
          runexp_scale.json, per level. The worksheet path infers level from bat
          tracking, which fails here: AFL and part of the AAA tab carry BatSpeed.
    HOW MANY PA  A no-pitch IBB leaves no row. ibb.csv.gz carries them.

A card reads tracked games only, so a Florida State League line is that club's
tracked games, not the player's year. The MLB regular season is not in the corpus; it
joins from data/all_pitches_rs_cache.pkl when the levels option names MLB.
"""
import json
import math
import os
import pickle
import sys

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT = os.path.join(_ROOT, 'data', '_milb2026')
CORPUS_PATH = os.path.join(_OUT, 'milb2026_pitches.csv.gz')
MANIFEST_PATH = os.path.join(_OUT, 'manifest.csv')
PLAYERS_PATH = os.path.join(_OUT, 'players.csv.gz')
IBB_PATH = os.path.join(_OUT, 'ibb.csv.gz')
SCALE_PATH = os.path.join(_OUT, 'runexp_scale.json')

# Card header text for each manifest level.
LEVEL_LABELS = {'MLB': 'MLB', 'AAA': 'AAA', 'Single-A': 'A', 'MLB-spring': 'Spring', 'Rookie': 'Rookie',
                'AFL': 'AFL', 'Prospect-event': 'Prospect'}
# 'regular' is the regular season and the playoffs, by game type. AFL games are type R,
# so the level leaves too. A date rule (03-25 to 09-27) keeps the same games but one:
# the Futures Game, type A on 07-12.
SCOPES = ('all', 'regular')
_REGULAR_TYPES = {'R', 'F', 'D', 'L', 'W', 'C'}
_PLAYOFF_TYPES = _REGULAR_TYPES - {'R'}
# wRC+ is relative to the player's own league, so it comes from FanGraphs per level.
# Spring, the AFL and prospect events have no FanGraphs line.
_FG_LEVELS = {'AAA': (1,), 'Single-A': (4,), 'Rookie': (7, 8)}
_ROLE_COLS = {'pitcher': ('PTeam', 'Pitcher', 'pitcherId'),
              'batter': ('BTeam', 'Batter', 'batterId')}


def parse_levels(levels):
    """'AAA,AFL' -> {'AAA', 'AFL'}; None or '' -> None, every level. A typo stops the run."""
    if not levels:
        return None
    want = {x.strip() for x in str(levels).split(',') if x.strip()}
    bad = want - set(LEVEL_LABELS)
    if bad:
        sys.exit(f'Unknown MiLB level(s) {sorted(bad)}. Use: {", ".join(LEVEL_LABELS)}')
    return want


def _read_keys(team_col, name_col):
    """(game, club, name) with its mlbId, for every player in the role. The corpus is 1.09M
    rows of 50 string columns, more than this 8 GB machine should hold for one card."""
    for path in (CORPUS_PATH, MANIFEST_PATH, PLAYERS_PATH, IBB_PATH, SCALE_PATH):
        if not os.path.exists(path):
            sys.exit(f'Missing {path}. Build it: python3 scripts/builders/milb2026_pull.py --index')
    keys = pd.read_csv(CORPUS_PATH, dtype=str, keep_default_na=False,
                       usecols=['PitchID', team_col, name_col])
    keys['_pk'] = keys.PitchID.str.split('_').str[0].astype(int)
    keys = keys[['_pk', team_col, name_col]].drop_duplicates()
    players = pd.read_csv(PLAYERS_PATH, keep_default_na=False)
    return keys.merge(players, left_on=['_pk', team_col, name_col],
                      right_on=['game_pk', 'team', 'name'], validate='m:1')


def _read_rows(mine, team_col, name_col):
    """Only the rows of these (game, club, name) keys, read in chunks, with mlbId and level."""
    man = pd.read_csv(MANIFEST_PATH, usecols=['game_pk', 'level', 'gameType'])
    level, game_type = dict(zip(man.game_pk, man.level)), dict(zip(man.game_pk, man.gameType))
    want = mine[['_pk', team_col, name_col, 'mlbId']].drop_duplicates()
    parts = []
    for chunk in pd.read_csv(CORPUS_PATH, dtype=str, keep_default_na=False, chunksize=100_000):
        chunk = chunk[chunk[name_col].isin(want[name_col])]
        if len(chunk):
            chunk['_pk'] = chunk.PitchID.str.split('_').str[0].astype(int)
            parts.append(chunk.merge(want, on=['_pk', team_col, name_col]))
    df = pd.concat(parts, ignore_index=True)
    df['_level'] = df._pk.map(level)
    df['_gameType'] = df._pk.map(game_type)
    return df


def _to_mlb_currency(rows):
    """RunExp -> MLB runs by the row's own level. Spring measures 1.000, so it stays."""
    from pipeline.utils import runexp_factor, runexp_scale_from_json
    with open(SCALE_PATH) as f:
        scale = runexp_scale_from_json(json.load(f))
    n = 0
    for r in rows:
        if r['_level'] == 'MLB-spring' or r['RunExp'] == '':
            continue
        f = runexp_factor(scale.get(r['_level']), r['Description'], r['Count'])
        if f:
            r['RunExp'] = float(r['RunExp']) / f
            n += 1
    if n:
        print(f'  RunExp -> MLB currency: {n} MiLB pitches rescaled')


def _mlb_stints(role, mid=None, name=None):
    """A player's single-club MLB leaderboard rows, by ID or by name. Rows carry the mlbId,
    so they are the bridge from an ID to the pickle, which holds names only."""
    from pipeline.utils import AAA_TEAMS, is_combined_team
    path = os.path.join(_ROOT, 'data', f"{role.replace('batter', 'hitter')}_leaderboard_rs.json")
    with open(path) as f:
        rows = json.load(f)
    key = 'pitcher' if role == 'pitcher' else 'hitter'
    hit = [r for r in rows if (r.get('mlbId') == mid if mid is not None else r.get(key) == name)]
    stints = [r for r in hit if r.get('team') not in AAA_TEAMS and not is_combined_team(r.get('team'))]
    combined = [r for r in hit if is_combined_team(r.get('team'))]
    return stints, (combined[0] if combined else (stints[0] if len(stints) == 1 else None))


def _mlb_rows(role, mid, mlb_pitches):
    """(rows, no-pitch IBB count, the official row) of one player's MLB regular season.
    The pickle ends where the Sheets end, and it holds no MLB postseason."""
    team_col, name_col, _ = _ROLE_COLS[role]
    stints, official = _mlb_stints(role, mid=mid)
    if not stints:
        return [], 0, None
    want = {(r['pitcher' if role == 'pitcher' else 'hitter'], r['team']) for r in stints}
    if mlb_pitches is None:
        with open(os.path.join(_ROOT, 'data', 'all_pitches_rs_cache.pkl'), 'rb') as f:
            mlb_pitches = pickle.load(f)
    rows = [{k: ('' if v is None else v) for k, v in p.items()}
            for p in mlb_pitches
            if p.get('_source') == 'MLB' and (p.get(name_col), p.get(team_col)) in want]
    for r in rows:
        r['_level'], r['_gameType'] = 'MLB', 'R'
    # The sheets' no-pitch IBB markers do not reach the pickle. The official count less
    # the pitch-derived count is the same number, and the leaderboard carries the first.
    from pipeline.utils import NON_PA_EVENTS
    official_pa = sum(r.get('tbf' if role == 'pitcher' else 'pa') or 0 for r in stints)
    pitch_pa = sum(1 for r in rows if r.get('Event') and r['Event'] not in NON_PA_EVENTS)
    if official_pa < pitch_pa:
        print(f'  WARNING: {mid}: official MLB PA {official_pa} is below the pitch count of '
              f'{pitch_pa}. No MLB IBB added. Refresh: python3 -m pipeline.refresh_pickle')
    return rows, max(official_pa - pitch_pa, 0), official


def load_players(role, names, levels=None, player_id=None, scope='all', mlb_pitches=None):
    """{requested name: {'mlbId', 'club', 'levels', 'label', 'rows', ...}} for the named players.

    scope 'all' is every tracked corpus game; 'regular' is the regular season and playoffs.
    MLB regular season rows join only when levels names MLB. Spring games are the
    MLB-spring level, so naming MLB does not bring them in.

    rows are strings with '' for blank, plus _level and _gameType, and the role's name
    column set to the requested spelling. Stops on a name that resolves to two players;
    a name with no rows is left out and printed.
    """
    team_col, name_col, ibb_col = _ROLE_COLS[role]
    if scope not in SCOPES:
        sys.exit(f'Unknown MiLB scope {scope!r}. Use: {", ".join(SCOPES)}')
    if player_id and len(names) != 1:
        sys.exit('The MiLB player ID option takes exactly one name.')
    print(f'  Reading the MiLB corpus ({CORPUS_PATH})...')
    keys = _read_keys(team_col, name_col)
    ibb = pd.read_csv(IBB_PATH)
    want_mlb = bool(levels) and 'MLB' in levels

    mids = {}
    for name in names:
        ids = set() if levels == {'MLB'} else set(keys.loc[keys[name_col] == name, 'mlbId'].tolist())
        if want_mlb:
            ids |= {r['mlbId'] for r in _mlb_stints(role, name=name)[0] if r.get('mlbId') is not None}
        ids = sorted(int(i) for i in ids)
        if player_id:
            ids = [i for i in ids if i == int(player_id)]
        if len(ids) > 1:
            lines = [f"    {i}: {', '.join(sorted(keys.loc[(keys[name_col] == name) & (keys.mlbId == i), team_col].unique()))}"
                     for i in ids]
            sys.exit(f'{name} is {len(ids)} players in the corpus. Pick one with the MiLB player '
                     'ID option:\n' + '\n'.join(lines))
        if not ids:
            print(f'  No rows for {name} as a {role}.')
            continue
        mids[name] = ids[0]
    # Selected by ID, so a spelling change between games stays one player.
    mine = keys[keys.mlbId.isin(mids.values())]
    df = _read_rows(mine, team_col, name_col) if len(mine) else pd.DataFrame(
        columns=['mlbId', '_pk', '_level', '_gameType'])

    out = {}
    for name, mid in mids.items():
        sel = df[df.mlbId == mid]
        if levels:
            sel = sel[sel._level.isin(levels)]
        if scope == 'regular':
            sel = sel[sel._gameType.isin(_REGULAR_TYPES) & (sel._level != 'AFL')]
        rows = sel.drop(columns=['_pk', 'mlbId']).to_dict('records')
        _to_mlb_currency(rows)
        mlb_ibb, official = 0, None
        if want_mlb:
            mlb, mlb_ibb, official = _mlb_rows(role, mid, mlb_pitches)
            rows += mlb
        if not rows:
            print(f'  {name}: no rows for scope {scope}' + (f' at {sorted(levels)}.' if levels else '.'))
            continue
        rows.sort(key=lambda r: (r['Game Date'], r['PitchID']))
        for r in rows:
            r[name_col] = name
        seen = list(dict.fromkeys(r['_level'] for r in rows))
        lv = ' + '.join(LEVEL_LABELS[x] for x in seen)
        if scope == 'regular':
            lv += (' Regular + Playoffs' if any(r['_gameType'] in _PLAYOFF_TYPES for r in rows)
                   else ' Regular Season')
        out[name] = {'mlbId': mid, 'club': rows[-1][team_col], 'levels': seen, 'label': f'2026 {lv}',
                     'rows': rows, 'ibb_pks': ibb.loc[ibb[ibb_col] == mid, 'game_pk'].tolist(),
                     'mlb_ibb': mlb_ibb, 'mlb_rows': sum(r['_level'] == 'MLB' for r in rows),
                     'mlb_only': seen == ['MLB'], 'official': official}
        print(f"  {name} ({mid}): {len(rows)} pitches, "
              f"{len({r['PitchID'].split('_')[0] for r in rows})} tracked games, {out[name]['label']}, "
              f"{ibb_count(out[name], rows)} no-pitch IBB")
    return out


def ibb_count(player, rows):
    """No-pitch IBBs inside these rows. A date window keeps only the IBBs of its games. The
    MLB count is a season total, so a window that cuts the MLB rows leaves it out and says so."""
    pks = {str(r['PitchID']).split('_')[0] for r in rows}
    n = sum(str(pk) in pks for pk in player['ibb_pks'])
    n_mlb = sum(r.get('_level') == 'MLB' for r in rows)
    if player['mlb_ibb'] and n_mlb == player['mlb_rows']:
        n += player['mlb_ibb']
    elif player['mlb_ibb'] and n_mlb:
        print(f"  Date window: {player['mlb_ibb']} MLB no-pitch IBB left out, PA can run short.")
    return n


def _fg_level(code):
    """One FanGraphs level, cached on disk. Delete the file to refresh it."""
    path = os.path.join(_OUT, f'fg_hitters_level{code}.json')
    cached = None
    if os.path.exists(path):
        with open(path) as f:
            cached = json.load(f)
        # A file from before the full line was kept is refreshed once; it still serves wRC+
        # if FanGraphs does not answer.
        if all('line' in line for line in cached.values()):
            return cached
    from pipeline.fg_overrides import fetch_milb_hitters
    try:
        got = fetch_milb_hitters(code)
    except (OSError, ValueError, RuntimeError) as e:
        if cached is None:
            raise
        print(f'  FanGraphs level {code} refresh failed ({e}); the official line stays blank.')
        return cached
    with open(path + '.tmp', 'w') as f:
        json.dump(got, f)
    os.replace(path + '.tmp', path)
    return got


def _xwoba_pool(level):
    """{mlbId: xwOBA} for every hitter's regular season at one corpus level, through the card's
    own compute_expected_stats, cached on disk. FanGraphs has no xwOBA, so this pool comes from
    the corpus. Delete the file after a corpus rebuild."""
    path = os.path.join(_OUT, f'xwoba_pool_{level}.json')
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    from pipeline.compute import compute_expected_stats
    man = pd.read_csv(MANIFEST_PATH, usecols=['game_pk', 'level', 'gameType'])
    pks = set(man[(man.level == level) & (man.gameType == 'R')].game_pk)
    players = pd.read_csv(PLAYERS_PATH, keep_default_na=False)
    ids = {(r.game_pk, r.team, r.name): str(r.mlbId) for r in players.itertuples()}
    rows = {}
    for chunk in pd.read_csv(CORPUS_PATH, dtype=str, keep_default_na=False, chunksize=100_000,
                             usecols=['PitchID', 'BTeam', 'Batter', 'Event', 'BBType', 'xBA', 'xSLG', 'xwOBA']):
        chunk = chunk[chunk.Event != '']
        for p in chunk.to_dict('records'):
            pk = int(p['PitchID'].split('_')[0])
            if pk in pks:
                mid = ids.get((pk, p['BTeam'], p['Batter']))
                if mid:
                    rows.setdefault(mid, []).append(p)
    got = {mid: v for mid, v in ((m, compute_expected_stats(pl, None).get('xwOBA')) for m, pl in rows.items())
           if v is not None}
    if not got:
        sys.exit(f'xwOBA pool for {level} came back empty. Check {CORPUS_PATH}.')
    with open(path + '.tmp', 'w') as f:
        json.dump(got, f)
    os.replace(path + '.tmp', path)
    print(f'  xwOBA pool {level}: {len(got)} hitters, built from {sum(map(len, rows.values()))} plate appearances.')
    return got


# Official-line stats a MiLB card takes from FanGraphs, per Wally 2026-11-05: a stat with no model
# of ours must match the public number. Statcast and our grades keep their own values.
_FG_COUNTS = {'pa': 'PA', 'ab': 'AB', 'h': 'H', 'doubles': '2B', 'triples': '3B', 'hr': 'HR', 'sb': 'SB',
              'cs': 'CS'}


def apply_fg_line(h_row, player, rows):
    """Put the FanGraphs line on a pure minor league regular-season card. Returns True if it
    applied; a card with playoffs, spring or MLB rows is a different sample, so it keeps its own
    numbers and says so. Two levels sum their counts and PA-weight wOBA."""
    if 'MLB' in player['levels'] or any(r.get('_gameType') != 'R' for r in rows):
        print('  FanGraphs line not applied: this card is not one minor league regular season.')
        return False
    lines = []
    for lv in player['levels']:
        if lv not in _FG_LEVELS:
            print(f'  FanGraphs line not applied: no level code for {lv}.')
            return False
        for code in _FG_LEVELS[lv]:
            try:
                got = _fg_level(code).get(str(player['mlbId']))
            except (OSError, ValueError, RuntimeError) as e:
                print(f'  FanGraphs line not applied: level {code} failed ({e}).')
                return False
            if got and got.get('line'):
                lines.append(got['line'])
    if not lines:
        print(f'  FanGraphs line not applied: no line for {player["mlbId"]}.')
        return False
    tot = {k: sum(int(l.get(k) or 0) for l in lines)
           for k in ('PA', 'AB', 'H', '2B', '3B', 'HR', 'SB', 'CS', 'BB', 'SO', 'HBP', 'SF')}
    before = {k: h_row.get(k) for k in ('pa', 'avg', 'obp', 'slg', 'wOBA', 'babip', 'bbPct', 'kPct')}
    for key, col in _FG_COUNTS.items():
        h_row[key] = tot[col]
    ab, pa = tot['AB'], tot['PA']
    tb = tot['H'] + tot['2B'] + 2 * tot['3B'] + 3 * tot['HR']
    obp_d = ab + tot['BB'] + tot['HBP'] + tot['SF']
    h_row['avg'] = tot['H'] / ab if ab else None
    h_row['obp'] = (tot['H'] + tot['BB'] + tot['HBP']) / obp_d if obp_d else None
    h_row['slg'] = tb / ab if ab else None
    if h_row['obp'] is not None and h_row['slg'] is not None:
        h_row['ops'] = h_row['obp'] + h_row['slg']
    h_row['wOBA'] = (sum(l['wOBA'] * l['PA'] for l in lines) / pa if pa else None)
    _bip = ab - tot['SO'] - tot['HR'] + tot['SF']
    h_row['babip'] = (tot['H'] - tot['HR']) / _bip if _bip else None
    h_row['bbPct'] = tot['BB'] / pa if pa else None   # fractions, as on the row
    h_row['kPct'] = tot['SO'] / pa if pa else None
    if player['levels'] == ['AAA']:
        apply_aaa_ruler(h_row, str(player['mlbId']))
    print('  FanGraphs line applied: ' + ', '.join(
        f'{k} {before[k]} -> {h_row[k]:.3f}' for k in before
        if before[k] is not None and h_row[k] is not None and abs(float(before[k]) - h_row[k]) >= .0005))
    return True


# Everything on a AAA card reads against AAA (2026-11-05, per Wally): every chip is a AAA
# percentile, every grade is 100 = AAA average, and the heat map is AAA wOBAcon. HITTER_POOL_AAA is built by
# scripts/research/cards/aaa_relative_grades.py, about 20 minutes, one season.
HITTER_POOL_AAA = os.path.join(_OUT, 'hitter_pool_AAA.json')
_AAA_RATE_KEYS = ('barrelPct', 'airPullPct', 'gbPct', 'izSwChase', 'izSwingPct', 'chasePct', 'izContactPct',
                  'contactPct', 'whiffPct', 'hardHitPct', 'ev95', 'xwOBAcon')
_AAA_GRADES = (('bbPlus', 'bbPlusNoBat'), ('ctPlus', 'ctPlus'), ('sdPlus', 'sdPlus'), ('processPlus', 'processPlus'))


def apply_aaa_ruler(h_row, mid):
    """Rank the row against AAA and center its grades at the AAA mean. A corpus card and a ROC
    team card both land here. A row that is one stint of a traded hitter (its PA differ from his
    AAA total) scores on the row's own grades and xwOBA; otherwise grades read the pool's
    prior-free values, because AAA bat speed covers 3.7% of swings. No pool or no row for this
    hitter leaves the MLB values and footer in place, and says so."""
    from cards.pitcher import _rank_in_mlb_pool
    from pipeline.compute import HITTER_INVERT_PCTL
    if not os.path.exists(HITTER_POOL_AAA):
        print(f'  AAA ruler NOT applied: {HITTER_POOL_AAA} is missing. '
              'Build it: scripts/research/cards/aaa_relative_grades.py')
        return
    with open(HITTER_POOL_AAA) as f:
        pool = json.load(f)
    me = pool.get(mid)
    if me is None:
        print(f'  AAA ruler NOT applied: {mid} is not in the AAA pool.')
        return
    stint = abs((me.get('pa') or 0) - (h_row.get('pa') or 0)) > 3
    if stint:
        print(f"  AAA ruler: {h_row.get('pa')} PA on this row of {me.get('pa')} at AAA, scoring the row's own values.")
    # Official stats against FanGraphs' AAA line.
    lines = [got['line'] for code in _FG_LEVELS['AAA'] for got in _fg_level(code).values() if got.get('line')]
    for key, col, inv in (('avg', 'AVG', False), ('obp', 'OBP', False), ('slg', 'SLG', False),
                          ('wOBA', 'wOBA', False), ('wRCplus', 'wRC+', False), ('babip', 'BABIP', False),
                          ('bbPct', 'BB%', False), ('kPct', 'K%', True)):
        vals = sorted(l[col] for l in lines if l.get(col) is not None)
        h_row[key + '_pctl'] = _rank_in_mlb_pool(h_row.get(key), vals, invert=inv)
    # xwOBA against the corpus. The pool is raw and the card prints the hitter basis, so a whole
    # AAA season ranks on its raw value: one definition on both sides, about .002 apart.
    xw = _xwoba_pool('AAA')
    raw = h_row.get('xwOBA') if stint else xw.get(mid)
    h_row['xwOBA_pctl'] = _rank_in_mlb_pool(raw, sorted(xw.values())) if raw is not None else None
    if raw is not None:
        # xwRC+ on the AAA scale. FanGraphs' own wRC+-per-wOBA slope at the level (100+ PA, PA
        # weighted; Furman moves 1.5 points from 1 to 400 PA) times his xwOBA against the level's
        # mean xwOBA, so AAA averages 100. The same method on MLB reproduces shipped xwRC+ at
        # r .9998, mean gap .23. It ranks exactly as xwOBA does.
        import numpy as np
        fit = [l for l in lines if l.get('PA', 0) >= 100 and l.get('wOBA') is not None and l.get('wRC+') is not None]
        slope = np.polyfit([l['wOBA'] for l in fit], [l['wRC+'] for l in fit], 1,
                           w=np.sqrt([l['PA'] for l in fit]))[0]
        pa_of = {str(int(l['xMLBAMID'])): l['PA'] for l in lines if l.get('xMLBAMID') and l.get('PA')}
        both = [(v, pa_of[m]) for m, v in xw.items() if m in pa_of]
        lg = sum(v * n for v, n in both) / sum(n for _v, n in both)
        was = h_row.get('xWRCplus')
        h_row['xWRCplus'] = round(100 + slope * (raw - lg))
        h_row['xWRCplus_pctl'] = h_row['xwOBA_pctl']
        print(f"  xwRC+: {was} on the MLB formula -> {h_row['xWRCplus']} on the AAA scale "
              f"(slope {slope:.0f}, AAA xwOBA {lg:.3f})")
    # Statcast rates against the pool.
    for key in _AAA_RATE_KEYS:
        vals = sorted(v[key] for v in pool.values() if v.get(key) is not None)
        if h_row.get(key) is not None and vals:
            h_row[key + '_pctl'] = _rank_in_mlb_pool(h_row[key], vals, invert=key in HITTER_INVERT_PCTL)
    # Grades: 100 = AAA average.
    for key, src in _AAA_GRADES:
        both = [(v[src], v.get('pa') or 0) for v in pool.values() if v.get(src) is not None]
        total = sum(n for _v, n in both)
        val = h_row.get(key) if stint else me.get(src)
        if val is None or not total:
            h_row[key] = h_row[key + '_pctl'] = None
            continue
        mean = sum(v * n for v, n in both) / total
        h_row[key + '_pctl'] = _rank_in_mlb_pool(val, sorted(v for v, _n in both))
        h_row[key] = val / mean * 100
        print(f'  {key}: {val:.1f} on the MLB scale / AAA mean {mean:.1f} -> {h_row[key]:.1f}')
    h_row['_aaaRuler'] = True


def aaa_sacq_zones():
    """The heat map's zone table on AAA balls in play, in metadata['sacqZones'] form, cached on
    disk. Same bins, weights and 20-BIP rule as process_data. Delete the file after a corpus
    rebuild."""
    path = os.path.join(_OUT, 'sacq_zones_AAA.json')
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    from pipeline.process_data import _bip_woba_value
    from pipeline.utils import BUNT_BB_TYPES, safe_float, spray_angle, spray_direction
    edges = [(-999, -10), (-10, 0), (0, 5), (5, 10), (10, 15), (15, 20), (20, 25), (25, 30), (30, 35),
             (35, 40), (40, 50), (50, 999)]
    man = pd.read_csv(MANIFEST_PATH, usecols=['game_pk', 'level', 'gameType'])
    pks = set(man[(man.level == 'AAA') & (man.gameType == 'R')].game_pk)
    cells = {}
    for chunk in pd.read_csv(CORPUS_PATH, dtype=str, keep_default_na=False, chunksize=100_000,
                             usecols=['PitchID', 'Bats', 'BBType', 'HC_X', 'HC_Y', 'LaunchAngle', 'Event', 'xwOBA']):
        chunk = chunk[(chunk.BBType != '') & (chunk.Bats != '')]
        for p in chunk.to_dict('records'):
            if int(p['PitchID'].split('_')[0]) not in pks or p['BBType'] in BUNT_BB_TYPES:
                continue
            la, hx, hy = safe_float(p['LaunchAngle']), safe_float(p['HC_X']), safe_float(p['HC_Y'])
            if la is None or hx is None or hy is None:
                continue
            spray = spray_direction(spray_angle(hx, hy), p['Bats'])
            lb = next((i for i, (lo, hi) in enumerate(edges) if lo <= la < hi), None)
            if not spray or lb is None:
                continue
            v, x = _bip_woba_value(p['Event']), safe_float(p['xwOBA'])
            for key in ((spray, lb, p['Bats']), (spray, lb, None)):
                c = cells.setdefault(key, [0, 0.0, 0, 0.0, 0])
                c[0] += 1
                if v is not None:
                    c[1] += v
                    c[2] += 1
                if x is not None:
                    c[3] += x
                    c[4] += 1
    got = [{'spray': s, 'laBin': lb, 'bats': b, 'count': c[0],
            'woba': round(c[1] / c[2], 3) if c[2] else None, 'wobacon': round(c[1] / c[2], 3) if c[2] else None,
            'xwobacon': round(c[3] / c[4], 3) if c[4] else None}
           for (s, lb, b), c in cells.items()]
    if not got:
        sys.exit(f'AAA heat map zones came back empty. Check {CORPUS_PATH}.')
    with open(path + '.tmp', 'w') as f:
        json.dump(got, f)
    os.replace(path + '.tmp', path)
    print(f'  AAA heat map: {len(got)} zones from {sum(c[0] for k, c in cells.items() if k[2] is None)} balls in play.')
    return got


def hitter_sb(player):
    """Stolen bases for the card's levels. A steal leaves no pitch row, so this reads the
    official lines: FanGraphs per minor league level, the shipped row for MLB. None, and a
    printed reason, when a level has no line, so the count leaves the card."""
    seen = set(player['levels'])
    total = 0
    if 'MLB' in seen:
        sb = (player.get('official') or {}).get('sb')
        if sb is None:
            print('  SB blank: no MLB line.')
            return None
        total += int(sb)
    for lv in seen - {'MLB'}:
        if lv not in _FG_LEVELS:
            print(f'  SB blank: FanGraphs has no line for {lv}.')
            return None
        found = False
        for code in _FG_LEVELS[lv]:
            try:
                line = _fg_level(code).get(str(player['mlbId']))
            except (OSError, ValueError, RuntimeError) as e:
                print(f'  SB blank: FanGraphs level {code} failed ({e}).')
                return None
            if line and line.get('sb') is not None:
                total += line['sb']
                found = True
        if not found:
            print(f'  SB blank: no FanGraphs {lv} line for {player["mlbId"]}.')
            return None
    return total


def hitter_wrc_plus(player, rows):
    """FanGraphs wRC+ for the card's levels, PA-weighted when there are two (FanGraphs builds
    its own combined minor league row the same way), with the shipped value for MLB. None,
    and a printed reason, when a level has no line or FanGraphs does not answer. The line
    is the level's whole regular season, so a gap against the card's tracked PA is printed."""
    from pipeline.utils import NON_PA_EVENTS
    seen = set(player['levels'])
    bad = seen - set(_FG_LEVELS) - {'MLB'}
    if bad:
        print(f'  wRC+ blank: FanGraphs has no line for {sorted(bad)}.')
        return None
    parts = []
    for lv in seen - {'MLB'}:
        card_pa = sum(1 for r in rows if r.get('_level') == lv and r.get('_gameType') == 'R'
                      and r.get('Event') and r['Event'] not in NON_PA_EVENTS)
        fg_pa = 0
        for code in _FG_LEVELS[lv]:
            try:
                line = _fg_level(code).get(str(player['mlbId']))
            except (OSError, ValueError, RuntimeError) as e:
                print(f'  wRC+ blank: FanGraphs level {code} failed ({e}).')
                return None
            if line:
                parts.append((line['wRCplus'], line['pa']))
                fg_pa += line['pa']
        if not fg_pa:
            print(f'  wRC+ blank: no FanGraphs {lv} line for {player["mlbId"]}.')
            return None
        print(f'  FanGraphs {lv}: {fg_pa} PA in the wRC+ line, {card_pa} regular-season PA on the card'
              + ('' if abs(fg_pa - card_pa) <= player_ibb_in(player, rows) else '  (samples differ)'))
    if 'MLB' in seen:
        official = player.get('official') or {}
        if official.get('wRCplus') is None or not official.get('pa'):
            print('  wRC+ blank: no shipped MLB wRC+.')
            return None
        parts.append((official['wRCplus'], official['pa']))
    total = sum(pa for _, pa in parts)
    return math.floor(sum(w * pa for w, pa in parts) / total + 0.5) if total else None


def player_ibb_in(player, rows):
    """The minor league no-pitch IBBs in these rows: real PA that leave no row."""
    pks = {str(r['PitchID']).split('_')[0] for r in rows}
    return sum(str(pk) in pks for pk in player['ibb_pks'])


def file_slug(scope, levels):
    """The output name part, so the AAA, MLB and combined cards do not overwrite each other."""
    parts = ['MiLB'] + (['Reg'] if scope == 'regular' else []) + sorted(levels or [])
    return '-'.join(parts)


def as_sheet_rows(rows):
    """Rows shaped like gspread get_all_records(): numbers parsed, blanks ''."""
    from gspread.utils import numericise
    out = []
    for r in rows:
        q = {k: (v if not isinstance(v, str) or k.startswith('_') else numericise(v))
             for k, v in r.items()}
        out.append(q)
    return out


def as_pickle_rows(rows, all_pitches):
    """Rows shaped like data/all_pitches_rs_cache.pkl: strings, blanks None, InZone, _source,
    xwOBA_hb. ROC rows are _source ROC; every other level is its own name, never MLB."""
    from pipeline.utils import (BUNT_BB_TYPES, XWOBA_PULLAIR_C, XWOBA_PULLAIR_LA, XWOBA_PULLAIR_LGSHARE,
                                compute_in_zone, safe_float, spray_angle, spray_direction)

    def _pull(p):
        if (p.get('Description') != 'In Play' or (p.get('BBType') or '') in BUNT_BB_TYPES):
            return None
        la = safe_float(p.get('LaunchAngle'))
        if la is None or la < XWOBA_PULLAIR_LA:
            return None
        sd = spray_direction(spray_angle(safe_float(p.get('HC_X')), safe_float(p.get('HC_Y'))),
                             p.get('Bats'))
        return None if sd is None else sd in ('pull', 'pull_side')

    # The pulled-air term of process_data's xwOBA_hb block, on the MLB share: a
    # MiLB hitter adjusts against the MLB league, the same as a ROC hitter.
    lg = [v for v in (_pull(p) for p in all_pitches if p.get('_source', 'MLB') == 'MLB')
          if v is not None]
    share = sum(lg) / len(lg) if len(lg) >= 5000 else XWOBA_PULLAIR_LGSHARE
    out = []
    for r in rows:
        p = {k: (None if v == '' else v) for k, v in r.items()}
        p['_source'] = 'ROC' if p.get('BTeam') == 'ROC' else r['_level']
        p['InZone'] = compute_in_zone(p)
        xw = safe_float(p.get('xwOBA'))
        if xw is not None:
            pull = _pull(p)
            p['xwOBA_hb'] = xw if pull is None else xw + XWOBA_PULLAIR_C * (float(pull) - share)
        out.append(p)
    return out


def add_ibb(row, rows, n):
    """Add no-pitch IBBs to a window row's official ledger: a PA and a hitter's walk.
    Every Statcast-derived key stays pitch-derived, the split the season card uses."""
    if not n or not row.get('pa'):
        return
    from pipeline.utils import BB_EVENTS, K_EVENTS, NON_PA_EVENTS, HIT_EVENTS, HBP_EVENTS, SF_EVENTS, SH_EVENTS, CI_EVENTS
    ev = [p['Event'] for p in rows if p.get('Event') and p['Event'] not in NON_PA_EVENTS]
    n_bb = sum(e in BB_EVENTS for e in ev) + n
    n_k = sum(e in K_EVENTS for e in ev)
    n_h = sum(e in HIT_EVENTS for e in ev)
    n_hbp = sum(e in HBP_EVENTS for e in ev)
    n_sf = sum(e in SF_EVENTS for e in ev)
    n_ab = (len(ev) + n - n_bb - n_hbp - n_sf - sum(e in SH_EVENTS for e in ev)
            - sum(e in CI_EVENTS for e in ev))
    pa = len(ev) + n
    row['pa'] = pa
    row['bbPct'] = round(n_bb / pa, 4)
    row['kPct'] = round(n_k / pa, 4)
    row['bbToK'] = n_bb / n_k if n_k else None
    d = n_ab + n_bb + n_hbp + n_sf
    if d:
        row['obp'] = round((n_h + n_bb + n_hbp) / d, 3)
        if row.get('slg') is not None:
            row['ops'] = round(row['obp'] + row['slg'], 3)
