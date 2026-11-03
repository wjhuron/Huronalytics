"""milb2026_pull.py — every tracked 2026 minor league pitch, in Pitcher2026 format.

One row per pitch with the same 50 columns the scraper writes, spring training
through the Arizona Fall League, for every player. Nothing here pushes to Sheets.

SOURCES
    AAA, Florida State League     feed + gf + Savant minors search
    MLB spring and exhibitions    feed + gf + Savant MLB search
    AFL, Spring Breakout, Futures Game, partly tracked Rookie games
                                  feed + gf only; Savant search has no rows

NO SECOND PARSER. Rows come from BaseballSavantFocusedDownloader itself
(download_game_data, merge_bat_speed, merge_statcast_supplement), and the
backfill state comes from backfill_supplement.download_statcast and
backfill_milb_feed.feed_gamestate. Both are fed from disk through thin stand-ins
for their HTTP calls, so a change to those parsers reaches this corpus on the
next --assemble.

THREE DEPARTURES FROM A PLAYER-ID PULL, all per Wally 2026-11-03:
    1. Team labels are the club's feed abbreviation, per game. normalize_aaa_labels
       collapses every team in a frame to ROC/AAA once Rochester appears anywhere
       in it, which on this corpus would erase every club.
    2. Savant rows are renumbered within each at-bat before the merge, the
       backfill_supplement auto-ball fix. The scraper merges on the raw
       pitch_number, so a pitch after an automatic ball takes a neighbour's values.
    3. Backfill state is applied to every game, the state the ROC and AAA tabs
       are in after backfill_supplement, not only the state of a fresh scrape.
A whole-game pull also fills the rows a player lookup leaves blank: mid-PA
substitutions, and a hitter's innings on the mound.

ROCHESTER GAMES take fresh Savant and feed values like every other game. Measured
on 815506: Runners, xBA/xSLG/xwOBA, RunExp and Spin Rate on the tabs can lag the
current sources, and the fresh values agree with Savant. Only what the sources
cannot supply is read from the ROC and AAA tabs (read-only, rocaaa_sheet.csv.gz):
Pitch Type, which backfill_supplement deliberately never touches, and the blanked
pitch shape on Pitch Type 'EP' rows.

Extension stays the feed's 4 decimals wherever the feed has it, the sheet's depth.
The scraper's 60.5 - release_pos_y is only the fallback, for the reason given at
Extension in backfill_supplement.SUPPLEMENT_MAP.

Runners is never a false 0: a pitch with no Savant row takes the feed's
reconstruction (feed_gamestate), the same fill the ROC/AAA tabs get.

LAYOUT (data/_milb2026/, gitignored)
    savant/   raw search CSVs per window      feed/, gf/  per tracked game
    games/    one finished CSV per game       scan.json   pk -> tracked or not
    manifest.csv  one row per game, with level, type, venue, supplement match
    milb2026_pitches.csv.gz  the corpus       game_weather.json  density sidecar
    players.csv.gz, ibb.csv.gz, runexp_scale.json  what cards/milb_corpus.py reads

    python3 scripts/builders/milb2026_pull.py                # fetch, then assemble
    python3 scripts/builders/milb2026_pull.py --fetch        # resumable
    python3 scripts/builders/milb2026_pull.py --assemble     # no network
    python3 scripts/builders/milb2026_pull.py --pks 867664 815506
Re-run after new AFL games: finished games are skipped unless --refresh is given.
"""
import argparse
import concurrent.futures as cf
import contextlib
import datetime as dt
import glob
import gzip
import io
import json
import os
import pickle
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import pandas as pd
import requests

import scrapers.backfill_supplement as B
import scrapers.pitcher2026 as P
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'builders'))
import backfill_milb_feed as MF

OUT = os.path.join(ROOT, 'data', '_milb2026')
SAVANT_DIR, FEED_DIR, GF_DIR, GAME_DIR = (os.path.join(OUT, d) for d in ('savant', 'feed', 'gf', 'games'))
SCAN_PATH = os.path.join(OUT, 'scan.json')
SCHEDULE_PATH = os.path.join(OUT, 'schedule.json')
MANIFEST_PATH = os.path.join(OUT, 'manifest.csv')
CORPUS_PATH = os.path.join(OUT, 'milb2026_pitches.csv.gz')
WEATHER_PATH = os.path.join(OUT, 'game_weather.json')
SHEET_PATH = os.path.join(OUT, 'rocaaa_sheet.csv.gz')
PLAYERS_PATH = os.path.join(OUT, 'players.csv.gz')
IBB_PATH = os.path.join(OUT, 'ibb.csv.gz')
SCALE_PATH = os.path.join(OUT, 'runexp_scale.json')
# Blank on the tabs for a position player's pitches; see EP_SKIP_COLS in the backfill.
EP_BLANK_COLS = ['Velocity', 'Spin Rate', 'RTilt', 'OTilt', 'IndVertBrk', 'HorzBrk', 'xIndVrtBrk',
                 'xHorzBrk', 'RelPosZ', 'RelPosX', 'Extension']
# Fill-only from the tabs. The AAA tab's bat speed came from a hand export (2026-08-21);
# the minors search CSV serves none, so no re-pull can recover these 2,115 cells.
SHEET_FILL_COLS = ['BatSpeed', 'SwingLength']

SEASON_START, SPRING_END = '2026-02-01', '2026-03-31'
WINDOW_DAYS = 3         # a busy day runs ~5,800 minors rows against the 25k cap
ROW_CAP = B.MILB_ROW_CAP
WORKERS = 6             # feed and gf; Savant search runs SAVANT_WORKERS
SAVANT_WORKERS = 3
AFL_LEAGUE_ID = 119

# (sportId, allowed game types or None for all, extra schedule params)
SCOPE = [
    (1, {'S', 'E'}, {}),   # spring; the regular season is already in Sheets
    (11, None, {}), (12, None, {}), (13, None, {}), (14, None, {}), (16, None, {}),
    (21, None, {}),        # Spring Breakout, Futures Game
    (17, None, {'leagueId': AFL_LEAGUE_ID}),   # AFL only, not the winter leagues
]
LEVEL = {1: 'MLB-spring', 11: 'AAA', 12: 'AA', 13: 'High-A', 14: 'Single-A',
         16: 'Rookie', 17: 'AFL', 21: 'Prospect-event'}

# The scraper's final_columns, which it holds inline in each download method.
# parity is asserted against a real player-ID CSV in the build test.
FINAL_COLUMNS = [
    'Game Date', 'PTeam', 'Pitcher', 'Throws', 'Pitch Type',
    'Velocity', 'Spin Rate', 'RTilt', 'OTilt', 'IndVertBrk', 'HorzBrk',
    'xIndVrtBrk', 'xHorzBrk',
    'RelPosZ', 'RelPosX', 'Extension', 'ArmAngle',
    'PlateZ', 'PlateX', 'SzTop', 'SzBot',
    'VAA', 'HAA',
    'Stuff+', 'Loc+',
    'BTeam', 'Batter', 'Bats', 'Count', 'Runners', 'Outs',
    'Description', 'Event',
    'ExitVelo', 'LaunchAngle', 'Distance', 'BBType',
    'HC_X', 'HC_Y', 'xBA', 'xSLG', 'xwOBA', 'RunExp',
    'BatSpeed', 'SwingLength',
    'AttackAngle', 'AttackDirection', 'SwingPathTilt',
    'PitchID', 'Barrel',
]
# What download_statcast_supplement keeps, plus the auto-ball inputs.
SCRAPER_SUPPLEMENT = ['game_pk', 'at_bat_number', 'pitch_number', 'arm_angle', 'release_pos_y',
                      'bat_speed', 'swing_length', 'attack_angle', 'attack_direction',
                      'swing_path_tilt', 'delta_pitcher_run_exp',
                      'estimated_ba_using_speedangle', 'estimated_slg_using_speedangle',
                      'estimated_woba_using_speedangle', 'on_1b', 'on_2b', 'on_3b',
                      'outs_when_up', 'launch_speed_angle']
GF_KEEP = ('ab_number', 'pitch_number', 'batSpeed', 'plate_x', 'plate_z')
UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      'Referer': 'https://baseballsavant.mlb.com/gamefeed'}
_tls = threading.local()


def _session():
    if not hasattr(_tls, 's'):
        _tls.s = requests.Session()
        _tls.s.headers.update(UA)
    return _tls.s


def _get(url, params=None, timeout=170, tries=4):
    """Response on 200, None on 404, raises after retries on anything else."""
    for attempt in range(tries):
        try:
            r = _session().get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                return None
            err = f'HTTP {r.status_code}'
        except requests.RequestException as e:
            err = str(e)
        if attempt < tries - 1:
            time.sleep(5 * 2 ** attempt)
    raise RuntimeError(f'{url} {params or ""}: {err}')


def _write_gz(path, text):
    tmp = path + '.tmp'
    with gzip.open(tmp, 'wt', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, path)


def _read_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def _write_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(obj, f)
    os.replace(tmp, path)


# ── Fetch ────────────────────────────────────────────────────────────────────

def pull_schedule():
    """{pk: {date, sportId, gameType, venue, home, away}} for every Final game."""
    end = dt.date.today().isoformat()
    games = {}
    for sport, types, extra in SCOPE:
        r = _get('https://statsapi.mlb.com/api/v1/schedule',
                 {'sportId': sport, 'startDate': SEASON_START, 'endDate': end, **extra}, timeout=90)
        for day in r.json().get('dates', []):
            for g in day['games']:
                # codedGameState, never abstractGameState: a postponed game is
                # Final/D on its original date and its makeup reuses the gamePk.
                if g['status'].get('codedGameState') != 'F':
                    continue
                if types and g['gameType'] not in types:
                    continue
                pk = str(g['gamePk'])
                # A suspended game appears on two dates; the first level seen wins
                # and the Savant index is by pk, so neither date loses its rows.
                games.setdefault(pk, {
                    'date': day['date'], 'sportId': sport, 'gameType': g['gameType'],
                    'venue': g.get('venue', {}).get('name', ''),
                    'home': g['teams']['home']['team'].get('name', ''),
                    'away': g['teams']['away']['team'].get('name', '')})
    return games


def _windows(a, b, days):
    out, cur = [], dt.date.fromisoformat(a)
    last = dt.date.fromisoformat(b)
    while cur <= last:
        nxt = min(cur + dt.timedelta(days=days - 1), last)
        out.append((cur, nxt))
        cur = nxt + dt.timedelta(days=1)
    return out


def _pull_savant_window(kind, w0, w1, holes):
    """One search window to disk. A capped window subdivides; a capped day is a hole."""
    path = os.path.join(SAVANT_DIR, f'{kind}_{w0}_{w1}.csv.gz')
    if os.path.exists(path):
        return 0
    url = ('https://baseballsavant.mlb.com/statcast-search-minors/csv' if kind == 'minors'
           else 'https://baseballsavant.mlb.com/statcast_search/csv')
    params = {'all': 'true', 'type': 'details', 'game_date_gt': str(w0), 'game_date_lt': str(w1),
              'player_type': 'pitcher', 'min_pitches': '0', 'min_results': '0',
              'sort_col': 'pitches', 'sort_order': 'desc'}
    if kind == 'minors':
        params['minors'] = 'true'
    try:
        r = _get(url, params)
    except RuntimeError as e:
        holes.append(f'savant {kind} {w0}..{w1}: {e}')
        return 0
    text = r.text if r is not None else ''
    if text.lstrip('﻿ \n')[:1] == '<':
        holes.append(f'savant {kind} {w0}..{w1}: HTML body, not CSV')
        return 0
    n = max(0, text.count('\n') - 1)
    # The search quotes multi-line text rarely; a count near the cap is enough to act on.
    if n >= ROW_CAP:
        span = (w1 - w0).days + 1
        if span <= 1:
            holes.append(f'savant {kind} {w0}: capped at {n} rows on one day')
            return 0
        mid = w0 + dt.timedelta(days=span // 2 - 1)
        print(f'  {kind} {w0}..{w1}: {n} rows hit the cap, subdividing', flush=True)
        return (_pull_savant_window(kind, w0, mid, holes)
                + _pull_savant_window(kind, mid + dt.timedelta(days=1), w1, holes))
    _write_gz(path, text)
    return n


def pull_savant(holes):
    today = dt.date.today().isoformat()
    jobs = [('minors', a, b) for a, b in _windows(SEASON_START, today, WINDOW_DAYS)]
    jobs += [('mlb', a, b) for a, b in _windows(SEASON_START, SPRING_END, WINDOW_DAYS)]
    t0, done, rows = time.time(), 0, 0
    with cf.ThreadPoolExecutor(SAVANT_WORKERS) as ex:
        futs = [ex.submit(_pull_savant_window, k, a, b, holes) for k, a, b in jobs]
        for fu in cf.as_completed(futs):
            rows += fu.result()
            done += 1
            if done % 10 == 0 or done == len(jobs):
                print(f'  savant {done}/{len(jobs)} windows, +{rows} rows, {time.time()-t0:.0f}s', flush=True)


def _pull_game(pk, holes):
    """Feed for any game, gf only if the feed holds a tracked pitch. Returns tracked."""
    feed_path = os.path.join(FEED_DIR, f'{pk}.json.gz')
    if not os.path.exists(feed_path):
        r = _get(f'https://statsapi.mlb.com/api/v1.1/game/{pk}/feed/live', timeout=60)
        if r is None:
            raise RuntimeError(f'feed {pk}: 404')
        data = r.json()
        tracked = any((e.get('pitchData') or {}).get('startSpeed') is not None
                      for pl in data['liveData']['plays'].get('allPlays', [])
                      for e in pl.get('playEvents', []) if e.get('isPitch'))
        if not tracked:
            return False    # no pitch to keep, so no feed to keep
        _write_gz(feed_path, json.dumps(data))
    gf_path = os.path.join(GF_DIR, f'{pk}.json.gz')
    if not os.path.exists(gf_path):
        try:
            r = _get('https://baseballsavant.mlb.com/gf', {'game_pk': pk}, timeout=60)
            j = r.json() if r is not None else {}
        except (RuntimeError, ValueError) as e:
            holes.append(f'gf {pk}: {e}')
            return True
        slim = {side: [{k: p.get(k) for k in GF_KEEP} for p in j.get(side, []) or []]
                for side in ('team_away', 'team_home')}
        _write_gz(gf_path, json.dumps(slim))
    return True


def pull_sheet_tabs():
    """The ROC and AAA tabs, read-only, for Pitch Type and the EP blanks."""
    import gspread
    book = gspread.service_account().open_by_key(B.SPREADSHEET_IDS[MF.MILB_BOOK])
    frames = []
    for tab in MF.MILB_TABS:
        vals = book.worksheet(tab).get_all_values()
        frames.append(pd.DataFrame(vals[1:], columns=vals[0]))
    df = pd.concat(frames, ignore_index=True)[['PitchID', 'Pitch Type'] + EP_BLANK_COLS + SHEET_FILL_COLS]
    df = df[df.PitchID != ''].drop_duplicates('PitchID')
    tmp = SHEET_PATH + '.tmp'
    df.to_csv(tmp, index=False, compression='gzip')
    os.replace(tmp, SHEET_PATH)
    print(f'sheet tabs: {len(df)} ROC and AAA rows', flush=True)


def fetch(pks_only=None, refresh=False):
    for d in (OUT, SAVANT_DIR, FEED_DIR, GF_DIR, GAME_DIR):
        os.makedirs(d, exist_ok=True)
    holes = []
    pull_sheet_tabs()
    sched = pull_schedule()
    _write_json(SCHEDULE_PATH, sched)
    print(f'schedule: {len(sched)} final games in scope', flush=True)
    pull_savant(holes)
    scan = _read_json(SCAN_PATH, {})
    todo = [pk for pk in sched if (refresh or pk not in scan) and (not pks_only or pk in pks_only)]
    print(f'feeds: {len(todo)} games to read, {len(scan)} already read', flush=True)
    lock = threading.Lock()
    t0 = time.time()

    def work(pk):
        try:
            tracked = _pull_game(pk, holes)
        except (RuntimeError, ValueError, KeyError) as e:
            holes.append(f'feed {pk}: {e}')
            return
        with lock:
            scan[pk] = tracked

    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for i, _ in enumerate(ex.map(work, todo), 1):
            if i % 250 == 0:
                _write_json(SCAN_PATH, scan)
                print(f'  {i}/{len(todo)} feeds, {sum(scan.values())} tracked, '
                      f'{time.time()-t0:.0f}s', flush=True)
    _write_json(SCAN_PATH, scan)
    print(f'scan: {len(scan)} read, {sum(scan.values())} tracked', flush=True)
    return holes


# ── Assemble (no network) ────────────────────────────────────────────────────

class _Resp:
    status_code = 200
    text = ''

    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


class _DiskHTTP:
    """Answers the scrapers' gf and feed requests from disk. Anything else fails."""

    def get(self, url, params=None, timeout=None):
        if '/gf' in url:
            pk = url.split('game_pk=')[1]
            path = os.path.join(GF_DIR, f'{pk}.json.gz')
            if not os.path.exists(path):
                return _Resp({})
            with gzip.open(path, 'rt') as f:
                return _Resp(json.load(f))
        if '/feed/live' in url:
            pk = url.split('/game/')[1].split('/')[0]
            with gzip.open(os.path.join(FEED_DIR, f'{pk}.json.gz'), 'rt') as f:
                return _Resp(json.load(f))
        raise RuntimeError(f'assemble must not touch the network: {url}')


class CorpusDownloader(P.BaseballSavantFocusedDownloader):
    """The scraper, reading disk, with its density sidecar sent to the corpus."""

    def __init__(self, weather):
        self._weather = weather
        super().__init__(download_dir=OUT)
        self.session = _DiskHTTP()

    def _record_game_weather(self, game_pk, info):
        # NEVER data/game_weather_rs.json: ~3,500 minor league games do not
        # belong in a shipped artifact.
        self._weather[str(game_pk)] = info


def load_savant():
    """{pk: frame} from every search window. Minors wins a pk that both serve."""
    frames = []
    # sorted: 'minors' files before 'mlb', so the drop below keeps the minors row.
    for path in sorted(glob.glob(os.path.join(SAVANT_DIR, '*.csv.gz'))):
        with gzip.open(path, 'rt', encoding='utf-8-sig') as f:
            text = f.read()
        if text.count('\n') < 2:
            continue
        frames.append(pd.read_csv(io.StringIO(text), low_memory=False))
    if not frames:
        sys.exit('ABORT: no Savant windows on disk. Run --fetch first.')
    df = pd.concat(frames, ignore_index=True).drop_duplicates(
        subset=['game_pk', 'at_bat_number', 'pitch_number'])
    return {str(k): v for k, v in df.groupby('game_pk', sort=False)}


def align_auto_balls(sav):
    """backfill_supplement's fix: drop automatic rows, renumber each at-bat 1..N."""
    is_auto = sav['description'].astype(str).str.lower().str.contains('automatic', na=False)
    if not is_auto.any():
        return sav
    kept = sav[~is_auto].sort_values(['at_bat_number', 'pitch_number']).copy()
    kept['pitch_number'] = kept.groupby('at_bat_number').cumcount() + 1
    return kept


def _text(df):
    """Every column as the string the CSV will hold, blanks as ''."""
    out = df.astype(object).where(df.notna(), '')
    return out.apply(lambda s: s.map(str))


def apply_backfill(df, pk, sav, is_minors, declined):
    """Bring a game to its post-backfill_supplement state. Mirrors the write
    loop in backfill_supplement.main(), whose rules sit inside the gspread path.
    Returns the number of cells changed."""
    B._download_statcast_minors = lambda *_a, **_k: sav
    B._fetch_savant_csv = lambda *_a, **_k: sav
    # 'ROC' selects the MiLB column set; any MLB tab selects the full map.
    got = B.download_statcast('ROC' if is_minors else 'NYY', '', '', None)
    if got is None:
        return 0
    lookup = got[0]
    changed = 0
    cols = df.columns
    for i, pid, ptype in zip(df.index, df['PitchID'], df['Pitch Type']):
        p = pid.split('_')
        data = lookup.get((p[0], str(int(p[1])), str(int(p[2]))))
        if not data:
            continue
        for col, val in data.items():
            if col not in cols or (ptype == 'EP' and col in B.EP_SKIP_COLS):
                continue
            cur = df.at[i, col]
            overwrite = col in B.ALWAYS_OVERWRITE_COLS or col in B.OVERWRITE_ONLY_COLS
            if not cur and col in B.OVERWRITE_ONLY_COLS:
                continue
            if cur and not overwrite:
                continue
            if not val and overwrite:
                continue
            if cur and str(val) == cur:
                continue
            if col == 'BBType' and cur == 'bunt':
                continue
            if cur and col in B.OVERWRITE_EPSILON:
                try:
                    if abs(float(val) - float(cur)) <= B.OVERWRITE_EPSILON[col]:
                        continue
                except (TypeError, ValueError):
                    pass
            if B.is_declined(declined, pid, col, val):
                continue
            df.at[i, col] = str(val)
            changed += 1
    return changed


def overlay_sheet(df, sheet):
    """Pitch Type, and the EP blanks, from the tabs. Returns retagged pitch count."""
    hit = df['PitchID'].isin(sheet.index)
    if not hit.any():
        return 0
    rows = sheet.loc[df.loc[hit, 'PitchID']]
    tags = pd.Series(rows['Pitch Type'].values, index=df.index[hit])
    retagged = int((tags != df.loc[hit, 'Pitch Type']).sum())
    df.loc[hit, 'Pitch Type'] = tags
    for col in EP_BLANK_COLS:
        ep = tags.index[tags == 'EP']
        df.loc[ep, col] = sheet.loc[df.loc[ep, 'PitchID'], col].values
    for col in SHEET_FILL_COLS:
        blank = df.index[hit & (df[col] == '')]
        df.loc[blank, col] = sheet.loc[df.loc[blank, 'PitchID'], col].values
    return retagged


def build_game(dl, pk, info, sav, declined, sheet):
    """One game in the scraper's format, or (None, reason)."""
    with gzip.open(os.path.join(FEED_DIR, f'{pk}.json.gz'), 'rt') as f:
        feed = json.load(f)
    df = dl.download_game_data(int(pk), game_json=feed)
    if df is None or df.empty:
        return None, 'parser returned nothing'
    df = dl.merge_bat_speed(df, int(pk))
    feed_ext = dict(zip(df['PitchID'], df['Extension']))

    aligned = align_auto_balls(sav) if sav is not None else None
    savant_keys = set()
    if aligned is not None:
        keep = [c for c in SCRAPER_SUPPLEMENT if c in aligned.columns]
        savant_keys = set(zip(aligned['at_bat_number'].astype(int), aligned['pitch_number'].astype(int)))
        df = dl.merge_statcast_supplement(df, aligned[keep].copy())
    else:
        df = dl.merge_statcast_supplement(df, None)
    for c in FINAL_COLUMNS:
        if c not in df.columns:
            df[c] = ''
    df = _text(df[FINAL_COLUMNS].copy())
    df['Extension'] = [feed_ext.get(p) or e for p, e in zip(df['PitchID'], df['Extension'])]

    # Per-game team labels, never normalize_aaa_labels (see the module docstring).
    teams = feed.get('gameData', {}).get('teams', {})
    names = {teams[s]['name']: teams[s]['abbreviation'] for s in ('home', 'away')
             if teams.get(s, {}).get('name') and teams[s].get('abbreviation')}
    df['PTeam'] = df['PTeam'].map(lambda t: names.get(t, t))
    df['BTeam'] = df['BTeam'].map(lambda t: names.get(t, t))

    backfilled = 0
    if sav is not None:
        backfilled = apply_backfill(df, pk, sav, info['sportId'] != 1, declined)

    # A pitch with no Savant row got Runners '0' from the merge's left join.
    def has_savant(pid):
        _, ab, pn = pid.split('_')
        return (int(ab), int(pn)) in savant_keys
    unmatched = ~df['PitchID'].map(has_savant)
    df.loc[unmatched, 'Runners'] = ''
    # Feed reconstruction, fill-only, the backfill_milb_feed pass.
    state = MF.feed_gamestate(int(pk)) or {}
    filled = 0
    for i, pid in zip(df.index, df['PitchID']):
        gs = state.get(pid)
        if gs is None:
            continue
        if not df.at[i, 'Outs'] and gs[0] is not None:
            df.at[i, 'Outs'] = str(gs[0])
            filled += 1
        if not df.at[i, 'Runners'] and gs[1] is not None:
            df.at[i, 'Runners'] = str(gs[1])
            filled += 1
    retagged = overlay_sheet(df, sheet)
    return df, {'pitches': len(df), 'savant_rows': 0 if aligned is None else len(aligned),
                'savant_matched': int((~unmatched).sum()), 'backfill_cells': backfilled,
                'feed_fill_cells': filled, 'sheet_retagged': retagged}


def assemble(pks_only=None, refresh=False):
    sched = _read_json(SCHEDULE_PATH, None)
    scan = _read_json(SCAN_PATH, None)
    if sched is None or scan is None:
        sys.exit('ABORT: schedule or scan missing. Run --fetch first.')
    savant = load_savant()
    tracked = sorted((pk for pk, t in scan.items() if t and (not pks_only or pk in pks_only)),
                     key=lambda pk: (sched[pk]['date'], int(pk)))
    print(f'assemble: {len(tracked)} tracked games, Savant rows for {len(savant)} games', flush=True)
    weather = _read_json(WEATHER_PATH, {})
    dl = CorpusDownloader(weather)
    MF.requests = _DiskHTTP()
    declined = B.load_declined()
    if not os.path.exists(SHEET_PATH):
        sys.exit('ABORT: rocaaa_sheet.csv.gz missing. Run --fetch first.')
    sheet = pd.read_csv(SHEET_PATH, dtype=str, keep_default_na=False).set_index('PitchID')
    stats_path = os.path.join(OUT, 'game_stats.json')
    stats = _read_json(stats_path, {})
    failed = []
    t0 = time.time()
    for i, pk in enumerate(tracked, 1):
        path = os.path.join(GAME_DIR, f'{pk}.csv.gz')
        if not refresh and os.path.exists(path) and pk in stats:
            continue
        sink = io.StringIO()
        try:
            with contextlib.redirect_stdout(sink):
                df, st = build_game(dl, pk, sched[pk], savant.get(pk), declined, sheet)
        except (KeyError, ValueError, TypeError, IndexError, OSError) as e:
            failed.append(f'{pk}: {type(e).__name__}: {e}')
            continue
        if df is None:
            failed.append(f'{pk}: {st}')
            continue
        _write_gz(path, df.to_csv(index=False))
        stats[pk] = st
        if i % 200 == 0:
            _write_json(stats_path, stats)
            print(f'  {i}/{len(tracked)} games, {time.time()-t0:.0f}s', flush=True)
    _write_json(stats_path, stats)
    _write_json(WEATHER_PATH, weather)
    return tracked, failed, stats, sched


def combine(tracked, stats, sched):
    """The corpus and manifest, written only after every part has been read."""
    frames, rows = [], []
    for pk in tracked:
        path = os.path.join(GAME_DIR, f'{pk}.csv.gz')
        if not os.path.exists(path):
            continue
        frames.append(pd.read_csv(path, dtype=str, keep_default_na=False))
        info = sched[pk]
        rows.append({'game_pk': pk, 'date': info['date'], 'level': LEVEL[info['sportId']],
                     'sportId': info['sportId'], 'gameType': info['gameType'], 'venue': info['venue'],
                     'home': info['home'], 'away': info['away'], **stats.get(pk, {})})
    df = pd.concat(frames, ignore_index=True)
    if list(df.columns) != FINAL_COLUMNS:
        sys.exit(f'ABORT: corpus columns differ from the scraper: {list(df.columns)}')
    dup = int(df.PitchID.duplicated().sum())
    if dup:
        sys.exit(f'ABORT: {dup} duplicate PitchIDs. The corpus was not written.')
    tmp = CORPUS_PATH + '.tmp'
    df.to_csv(tmp, index=False, compression='gzip')
    os.replace(tmp, CORPUS_PATH)
    man = pd.DataFrame(rows)
    man.to_csv(MANIFEST_PATH + '.tmp', index=False)
    os.replace(MANIFEST_PATH + '.tmp', MANIFEST_PATH)
    print(f'corpus: {len(df)} pitches, {len(man)} games -> {CORPUS_PATH}', flush=True)
    print(man.groupby(['level', 'gameType'])[['pitches', 'savant_matched']].agg(['count', 'sum']).to_string())


def _index_dl():
    if not hasattr(_tls, 'dl'):
        _tls.dl = P.BaseballSavantFocusedDownloader(download_dir=OUT)
    return _tls.dl


def _index_game(pk):
    """(team, name -> mlbId) and the no-pitch intentional walks of one cached feed."""
    with gzip.open(os.path.join(FEED_DIR, f'{pk}.json.gz'), 'rt') as f:
        feed = json.load(f)
    names, ibb = [], []
    people = feed['gameData']['players']
    teams = feed['gameData']['teams']
    feed_abbrev = {teams[s]['name']: teams[s]['abbreviation'] for s in ('home', 'away')}
    for side in ('home', 'away'):
        # The labels build_game writes: the scraper's map, then the feed abbreviation.
        team = _index_dl().get_team_abbreviation(teams[side]['name'])
        team = feed_abbrev.get(team, team)
        for key, entry in feed['liveData']['boxscore']['teams'][side]['players'].items():
            # lastFirstName can carry a trailing space; the scraper strips it too.
            person = people.get(key) or {}
            if person.get('lastFirstName'):
                names.append({'game_pk': pk, 'team': team, 'name': person['lastFirstName'].strip(),
                              'mlbId': entry['person']['id']})
    for play in feed['liveData']['plays']['allPlays']:
        if (play['result'].get('eventType') == 'intent_walk'
                and not any(e.get('isPitch') for e in play.get('playEvents', []))):
            ibb.append({'game_pk': pk, 'pitcherId': play['matchup']['pitcher']['id'],
                        'batterId': play['matchup']['batter']['id']})
    return names, ibb


def build_index():
    """The sidecars the cards read: a corpus row carries a name, and a name is not a player.

    players.csv.gz   (game_pk, team, name) -> mlbId, so a card selects by ID. Team is in
                     the key because two Max Muncys can share a spring game.
    ibb.csv.gz       no-pitch intentional walks. They leave no pitch row, so a
                     pitch-derived PA runs short without them.
    runexp_scale.json  RunExp -> MLB currency per level, by compute_runexp_scale.
                     The metadata factors cover ROC and AAA only, and the Single-A
                     matrix is its own. Reference: MLB rows of the local pickle.
    """
    from pipeline.utils import compute_runexp_scale, runexp_scale_to_json
    man = pd.read_csv(MANIFEST_PATH, dtype={'game_pk': int})
    pks = man.game_pk.tolist()
    names, ibb = [], []
    with cf.ProcessPoolExecutor() as ex:
        for got_names, got_ibb in ex.map(_index_game, pks, chunksize=20):
            names += got_names
            ibb += got_ibb
    players = pd.DataFrame(names).drop_duplicates()
    same = players[players.duplicated(['game_pk', 'team', 'name'], keep=False)]
    if len(same):
        sys.exit(f'ABORT: one club lists one name twice, the key cannot separate them:\n{same.to_string()}')

    df = pd.read_csv(CORPUS_PATH, dtype=str, keep_default_na=False,
                     usecols=['PitchID', 'PTeam', 'Pitcher', 'BTeam', 'Batter', 'Description', 'Count', 'RunExp'])
    df['game_pk'] = df.PitchID.str.split('_').str[0].astype(int)
    known = set(zip(players.game_pk, players.team, players.name))
    orphans = {key for t, n in (('PTeam', 'Pitcher'), ('BTeam', 'Batter'))
               for key in set(zip(df.game_pk, df[t], df[n])) if key not in known}
    if orphans:
        sys.exit(f'ABORT: {len(orphans)} corpus names are not in their feed, '
                 f'for example {sorted(orphans)[:5]}. The index was not written.')

    level = dict(zip(man.game_pk, man.level))
    df['_source'] = df.game_pk.map(level)
    rows = df[df.RunExp != ''][['_source', 'Description', 'Count', 'RunExp']].to_dict('records')
    with open(os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl'), 'rb') as f:
        rows += [{k: p.get(k) for k in ('_source', 'Description', 'Count', 'RunExp')}
                 for p in pickle.load(f) if p.get('_source') == 'MLB']
    scale = compute_runexp_scale(rows)

    players.to_csv(PLAYERS_PATH, index=False, compression='gzip')
    pd.DataFrame(ibb, columns=['game_pk', 'pitcherId', 'batterId']).to_csv(
        IBB_PATH, index=False, compression='gzip')
    _write_json(SCALE_PATH, runexp_scale_to_json(scale))
    print(f'index: {players.mlbId.nunique()} players, {len(ibb)} no-pitch IBB, RunExp factors '
          + ', '.join(f'{k} {v["global"]:.3f}' for k, v in sorted(scale.items())), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fetch', action='store_true', help='download only')
    ap.add_argument('--assemble', action='store_true', help='build from disk only')
    ap.add_argument('--index', action='store_true', help='rebuild only the card sidecars')
    ap.add_argument('--pks', nargs='*', default=None, help='limit to these gamePks')
    ap.add_argument('--refresh', action='store_true', help='redo games already finished')
    a = ap.parse_args()
    if a.index:
        build_index()
        return
    both = not a.fetch and not a.assemble
    holes = []
    if a.fetch or both:
        holes = fetch(a.pks, a.refresh)
    if a.assemble or both:
        tracked, failed, stats, sched = assemble(a.pks, a.refresh or bool(a.pks))
        combine(tracked, stats, sched)
        build_index()
        holes += [f'assemble {f}' for f in failed]
    if holes:
        print(f'\nHOLES ({len(holes)}), re-run to retry:')
        for h in holes[:60]:
            print('  ', h)
        sys.exit(1)


if __name__ == '__main__':
    main()
