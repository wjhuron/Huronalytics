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
