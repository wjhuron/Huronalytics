"""Transactions bot prototype: find NEW MLB/MiLB transactions and print tweets.

No X/Twitter calls. This only decides WHAT would be posted.

New = a transaction `id` from the MLB Stats API that is not in the posted-ID
state file. The script re-reads a lookback window on every run, so a move
that the league logs today but dates 11/12 still gets picked up, and the tweet
carries its own date, not the posting date.

Usage (from the repo root):
    python3 scripts/tools/transactions_bot.py seed      # mark everything in the window as posted, print nothing
    python3 scripts/tools/transactions_bot.py preview   # print would-be tweets, write nothing
    python3 scripts/tools/transactions_bot.py run       # print would-be tweets AND record them as posted

`run` is where the X post call goes later: record an id only after its post succeeds.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
from datetime import date, datetime

import requests

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
# Every run re-reads all transactions dated from this day through today
# (per Wally 2026-11-17). Back-dated entries inside that range are picked up.
LOOKBACK_START = date(2026, 9, 28)

# The affiliated levels mlb.com/milb.com list: MLB, AAA, AA, A+, A, Rookie (DSL/ACL/FCL).
SPORT_IDS = [1, 11, 12, 13, 14, 16]
LEVEL_LABEL = {1: 'MLB', 11: 'AAA', 12: 'AA', 13: 'A+', 14: 'A', 16: 'Rookie'}
LEVEL_RANK = {1: 6, 11: 5, 12: 4, 13: 3, 14: 2, 16: 1}

# Which API date goes on the tweet: 'date', 'effectiveDate' or 'resolutionDate'.
DATE_FIELD = 'date'

# Pitcher role: SP when games started / games pitched >= this share. A labeling
# CONVENTION, not a measured value.
SP_SHARE_CUTOFF = 0.5

# A player with no games in the stats season:
#   'omit'        -> no "(X)" level tag
#   'last_season' -> his most recent season with games, as "(YYYY: X)" so it
#                    does not read as the current season
NO_STATS_MODE = 'omit'

# Official 2026 club hashtags, keyed by MLB club id (list from Wally, 2026-11-17).
# A blank entry adds no hashtag.
HASHTAGS = {
    108: '#RepTheHalo',  # LAA
    109: '#Dbacks',  # ARI
    110: '#Birdland',  # BAL
    111: '#DirtyWater',  # BOS
    112: '#Cubs',  # CHC
    113: '#ATOBTTR',  # CIN
    114: '#GuardsBall',  # CLE
    115: '#Rockies',  # COL
    116: '#DNMW',  # DET
    117: '#ChaseTheFight',  # HOU
    118: '#FountainsUp',  # KC
    119: '#Dodgers',  # LAD
    120: '#Natitude',  # WSH
    121: '#LGM',  # NYM
    133: '#Athletics',  # ATH
    134: '#LetsGoBucs',  # PIT
    135: '#ForTheFaithful',  # SD
    136: '#TridentsUp',  # SEA
    137: '#SFGiants',  # SF
    138: '#STLCards',  # STL
    139: '#RaysUp',  # TB
    140: '#AllForTX',  # TEX
    141: '#BlueJays50',  # TOR
    142: '#NoPlaceLikeHERE',  # MIN
    143: '#RingTheBell',  # PHI
    144: '#BravesCountry',  # ATL
    145: '#WhiteSox',  # CWS
    146: '#FightinFish',  # MIA
    147: '#RepBX',  # NYY
    158: '#ThisIsMyCrew',  # MIL
}

TWEET_LIMIT = 280
# ---------------------------------------------------------------------------

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_PATH = os.path.join(REPO, 'data', '_txbot', 'posted_ids.json')
API = 'https://statsapi.mlb.com/api/v1'

_session = requests.Session()


def get_json(path, params=None):
    """GET with retries. Raises on a persistent failure: never guess around a bad response."""
    url = f'{API}/{path}'
    last = None
    for attempt in range(3):
        try:
            r = _session.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f'Stats API request failed after 3 tries: {url} {params} ({last})')


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
def load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH) as f:
        return json.load(f)  # {id: {"date": tx date, "first_seen": iso date}}


def save_state(state):
    """Write to a temp file and move, so a crash never leaves a partial state file."""
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(STATE_PATH), suffix='.tmp')
    with os.fdopen(fd, 'w') as f:
        json.dump(state, f, indent=1, sort_keys=True)
    os.replace(tmp, STATE_PATH)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def load_org_map(season):
    """team id -> MLB parent org id, for every affiliated club (MLB clubs map to themselves)."""
    teams = get_json('teams', {'sportIds': ','.join(map(str, SPORT_IDS)), 'season': season})['teams']
    org = {}
    for t in teams:
        org[t['id']] = t['id'] if t['sport']['id'] == 1 else t.get('parentOrgId')
    missing = [t['name'] for t in teams if org[t['id']] is None]
    if missing:
        print(f'WARNING: no parentOrgId for {len(missing)} clubs: {missing[:5]}', file=sys.stderr)
    return org


_person_cache = {}


def person_info(pid):
    """Hand, primary position, and per-season games by level (MLB + MiLB)."""
    if pid in _person_cache:
        return _person_cache[pid]
    p = get_json(f'people/{pid}')['people'][0]
    stats = get_json(f'people/{pid}/stats',
                     {'stats': 'yearByYear', 'group': 'pitching,hitting', 'leagueListId': 'mlb_milb'})
    seasons = {}  # season -> {'levels': set(sport ids), 'g': pitching G, 'gs': pitching GS}
    for block in stats.get('stats', []):
        grp = block['group']['displayName']
        for sp in block['splits']:
            sid = sp.get('sport', {}).get('id')
            if sid not in LEVEL_RANK:
                continue
            # The API sometimes writes a season as '2018.1'; the part before the dot is the year.
            s = seasons.setdefault(int(str(sp['season']).split('.')[0]), {'levels': set(), 'g': 0, 'gs': 0})
            g = sp['stat'].get('gamesPlayed') or 0
            if g > 0:
                s['levels'].add(sid)
            if grp == 'pitching':
                s['g'] += sp['stat'].get('gamesPitched') or g
                s['gs'] += sp['stat'].get('gamesStarted') or 0
    info = {
        'hand': (p.get('pitchHand') or {}).get('code'),
        'pos': (p.get('primaryPosition') or {}).get('abbreviation'),
        'seasons': seasons,
    }
    _person_cache[pid] = info
    return info


def stats_season(tx_date):
    """Season the parenthetical describes. Jan-Feb moves describe the season just ended."""
    return tx_date.year if tx_date.month >= 3 else tx_date.year - 1


def level_note(info, tx_date):
    season = stats_season(tx_date)
    s = info['seasons'].get(season)
    if not (s and s['levels']):
        if NO_STATS_MODE != 'last_season':
            return None, None
        played = [y for y, v in info['seasons'].items() if v['levels'] and y <= season]
        if not played:
            return None, None
        season = max(played)
        s = info['seasons'][season]
    top = max(s['levels'], key=LEVEL_RANK.get)
    # Bare "(AAA)" = highest level played in the stats season (explained in the bot's bio).
    if season == stats_season(tx_date):
        return f'({LEVEL_LABEL[top]})', s
    return f'({season}: {LEVEL_LABEL[top]})', s


def pitcher_label(info, season_stats):
    """RHP -> RHSP/RHRP from the stats season's start share. None when unknown."""
    if not season_stats or season_stats['g'] == 0 or info['hand'] not in ('R', 'L'):
        return None
    role = 'SP' if season_stats['gs'] / season_stats['g'] >= SP_SHARE_CUTOFF else 'RP'
    return f"{info['hand']}H{role}"


def prior_org(pid, tx, org_map):
    """The org of the player's last affiliated club BEFORE this transaction's date."""
    hist = get_json('transactions', {'playerId': pid}).get('transactions', [])
    best = None
    for h in hist:
        if h['id'] == tx['id'] or h.get('date', '') >= tx[DATE_FIELD]:
            continue
        for side in ('toTeam', 'fromTeam'):
            tid = (h.get(side) or {}).get('id')
            if tid in org_map:
                if best is None or h['date'] >= best[0]:
                    best = (h['date'], org_map[tid])
                break
    return best[1] if best else None


# ---------------------------------------------------------------------------
# Tweet text
# ---------------------------------------------------------------------------
def build_tweet(records, org_map):
    """One tweet per transaction id. `records` = every API row that shares the id (trades have one per player)."""
    tx = records[0]
    tx_date = datetime.strptime(tx[DATE_FIELD], '%Y-%m-%d').date()
    text = tx['description'].strip()
    notes = []

    people = {}
    for r in records:
        if r.get('person'):
            people[r['person']['id']] = r['person']['fullName']

    for pid, name in people.items():
        info = person_info(pid)
        paren, season_stats = level_note(info, tx_date)
        # Find "<POS> <Name>" in the text.
        m = re.search(r'\b([A-Z0-9]{1,4})\s+' + re.escape(name) + r'(?!\w)', text)
        if not m:
            notes.append(f'name not found in text: {name}')
            continue
        pos_tok = m.group(1)
        new_pos = pos_tok
        if pos_tok in ('RHP', 'LHP', 'P'):
            new_pos = pitcher_label(info, season_stats) or pos_tok
        replacement = f'{new_pos} {name}' + (f' {paren}' if paren else '')
        text = text[:m.start()] + replacement + text[m.end():]

    # "signed free agent" -> "re-signed" when he comes back to his last org.
    to_id = (tx.get('toTeam') or {}).get('id')
    if tx.get('typeCode') == 'SFA' and to_id in org_map and len(people) == 1:
        pid = next(iter(people))
        if prior_org(pid, tx, org_map) == org_map[to_id]:
            text = re.sub(r'\bsigned free agent\b', 're-signed', text, count=1)

    orgs = []
    for r in records:
        for side in ('toTeam', 'fromTeam'):
            o = org_map.get((r.get(side) or {}).get('id'))
            if o and o not in orgs:
                orgs.append(o)
    tags = ' '.join(HASHTAGS[o] for o in orgs if HASHTAGS.get(o))

    tweet = f'{tx_date.month}/{tx_date.day}: {text}' + (f' {tags}' if tags else '')
    return tweet, notes


# ---------------------------------------------------------------------------
def fetch_window(today):
    start = LOOKBACK_START
    data = get_json('transactions', {
        'startDate': start.isoformat(), 'endDate': today.isoformat(),
        'sportId': ','.join(map(str, SPORT_IDS)),
    })
    by_id = {}
    for t in data.get('transactions', []):
        by_id.setdefault(str(t['id']), []).append(t)
    return start, by_id


def dup_key(records):
    """Two API ids with the same date and the same text are one move (seen: Angel
    Vicioso, 10/5, listed under two ids). Key on the raw API text, before enrichment."""
    desc = next((r['description'] for r in records if r.get('description')), '')
    return f"{records[0][DATE_FIELD]}|{' '.join(desc.split()).casefold()}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode', choices=['seed', 'preview', 'run'])
    ap.add_argument('--today', help='yyyy-mm-dd, for testing a past window (default: today)')
    args = ap.parse_args()

    today = date.fromisoformat(args.today) if args.today else date.today()
    state = load_state()
    start, by_id = fetch_window(today)
    new_ids = sorted((i for i in by_id if i not in state),
                     key=lambda i: (by_id[i][0][DATE_FIELD], int(i)))
    print(f'Window {start} to {today}: {len(by_id)} transactions, '
          f'{len(by_id) - len(new_ids)} already posted, {len(new_ids)} new.')

    if args.mode == 'seed':
        for i in new_ids:
            state[i] = {'date': by_id[i][0][DATE_FIELD], 'first_seen': today.isoformat(),
                        'key': dup_key(by_id[i]), 'seeded': True}
        save_state(state)
        print(f'Seeded {len(new_ids)} ids into {STATE_PATH}. Nothing printed, nothing posted.')
        return

    org_map = load_org_map(today.year)
    too_long = 0
    held = 0
    dups = 0
    lags = []
    # key -> id already posted (earlier runs) or printed (this run)
    seen_keys = {v['key']: k for k, v in state.items() if v.get('key')}
    seen_tweets = {v['tweet']: k for k, v in state.items() if v.get('tweet')}
    for i in new_ids:
        # The API can list a record with no text and no player (seen: 944537, a bare
        # "Recalled"). Hold it, unrecorded, so it posts on a later run if text appears.
        if not any(r.get('description') for r in by_id[i]):
            held += 1
            print(f"\n[{i}] HELD: no description ({by_id[i][0].get('typeDesc')}, "
                  f"{(by_id[i][0].get('toTeam') or {}).get('name')}). Not posted, not recorded.")
            continue
        by_id[i].sort(key=lambda r: not r.get('description'))
        key = dup_key(by_id[i])
        if key in seen_keys:
            dups += 1
            print(f'\n[{i}] SKIPPED: duplicate of [{seen_keys[key]}].')
            if args.mode == 'run':
                state[i] = {'date': by_id[i][0][DATE_FIELD], 'first_seen': today.isoformat(),
                            'key': key, 'duplicate_of': seen_keys[key]}
            continue
        tweet, notes = build_tweet(by_id[i], org_map)
        # Second guard: identical final text from different API text.
        if tweet in seen_tweets:
            dups += 1
            print(f'\n[{i}] SKIPPED: same tweet as [{seen_tweets[tweet]}].')
            if args.mode == 'run':
                state[i] = {'date': by_id[i][0][DATE_FIELD], 'first_seen': today.isoformat(),
                            'key': key, 'duplicate_of': seen_tweets[tweet]}
            continue
        seen_keys[key] = i
        seen_tweets[tweet] = i
        tx_date = date.fromisoformat(by_id[i][0][DATE_FIELD])
        age = (today - tx_date).days  # days since the transaction date, not since it first appeared
        lags.append(age)
        flag = ''
        if len(tweet) > TWEET_LIMIT:
            flag = f'  [TOO LONG: {len(tweet)}]'
            too_long += 1
        print(f'\n[{i}] dated {age}d ago, {len(tweet)} chars{flag}')
        print(tweet)
        for n in notes:
            print(f'  note: {n}')
        if args.mode == 'run':
            # TODO: post to X here; record the id only after the post succeeds.
            state[i] = {'date': by_id[i][0][DATE_FIELD], 'first_seen': today.isoformat(),
                        'key': key, 'tweet': tweet}

    if args.mode == 'run':
        save_state(state)
    print(f'\n{len(new_ids)} new, {dups} duplicates skipped, {held} held, {too_long} over {TWEET_LIMIT} chars.'
          + (f' Oldest new entry: {max(lags)}d.' if lags else '')
          + (' State updated.' if args.mode == 'run' else ' Preview only, state not written.'))


if __name__ == '__main__':
    main()
