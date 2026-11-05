"""Build data/free_agents.json, the player set behind the site's Free Agents filter.

Three hand-kept sources, all in ~/Downloads by default:

  * the FanGraphs free-agent tracker for BASE_SEASON + 1 ({year}-free-agent-tracker*.xlsx). Every row counts EXCEPT the
    FA Likelihood values NOT_HAPPENING and PROBABLY_NOT_FA.
  * released.numbers and "elected fa.numbers", the transaction lists kept
    from scrapers/transactions.py output. Every row counts; a player on more
    than one list is kept once.

Only players with a 2026 MLB leaderboard row are kept (pitcher or hitter,
any MLB club or a 2TM..10TM combined row). A ROC-only player is dropped even
though he has AAA data: the filter is for players who played in MLB.

Players are matched by ID, never by name against the leaderboard (a name
match put a released Double-A Jacob Webb and a Triple-A shortstop Edwin Díaz
on the list as the MLB pitchers of the same names, 2026-10-09):

  * FanGraphs rows carry the FanGraphs `playerid`; the season's MLB leaders
    endpoint pairs it with the MLB id (xMLBAMID).
  * the transaction lists carry no id, so each row is looked up in the MLB
    transactions API on its own date, where the move names the person id.
    The name only picks the move out of that one day's list.

A row that gets no id is printed and left out, never guessed. Each player also carries his baseball age (June 30) in the season after BASE_SEASON, from
the MLB season lines in data/_proj/ (lines_*_{year}.json, the projection inputs), for the hidden Free
Agents page. Run it again after either Numbers file changes, then commit the JSON:

    python3 scripts/builders/build_free_agents.py

Hand decisions live by id in SIGNED, RETIRED, REMOVED, MLBPA_XXB and HAND_ADDED. To apply them with no source list on hand, and so without any
other list changes reaching the JSON:

    python3 scripts/builders/build_free_agents.py --overrides-only
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from pipeline.fetch import TEAM_NAME_TO_ABBREV  # noqa: E402
from pipeline.utils import AAA_TEAMS  # noqa: E402

DATA = os.path.join(ROOT, 'data')
OUT = os.path.join(DATA, 'free_agents.json')
DOWNLOADS = os.path.expanduser('~/Downloads')

FG_EXCLUDE = {'NOT_HAPPENING', 'PROBABLY_NOT_FA'}
# Players who are signed, by MLB id: before reaching the market, or with a new team on the 2026/27 MLB Offseason
# sheet (per Wally 2026-11-03). A source list can still carry them (the FanGraphs tracker lags), so they are dropped by id.
SIGNED = {
    641835: 'Tim Mayza, extension with PHI (2026-10)',
    621097: 'Jacob Waguespack, re-signed with DET, MLB deal',
    605244: 'Aramis Garcia, re-signed with ARI, MiLB deal',
    660644: 'Vidal Bruján, ATL, MiLB deal',
    676369: 'Nelson Velázquez, Asia',
    675919: 'Nick Raquet, DET, MiLB deal',
    687957: 'Dustin Harris, SDP 40-man (selected 2026-08-24)',
}
# Retired, per Wally 2026-11-02. A source list can still carry them (the MLBPA XX(B) release did), so they are dropped by id.
RETIRED = {
    434378: 'Justin Verlander',
    489446: 'Kirby Yates',
    500743: 'Miguel Rojas',
}
# On the MLBPA XX(B) release of 2026-10-29 with a 2026 MLB row, added per Wally 2026-11-02. No source list above had them.
MLBPA_XXB = {
    621139: 'Brooks Kriske',
    605335: 'Brandon Leibrandt',
}
# Added by hand per Wally 2026-11-02: id -> (name, source). The first 14 have a 2026 MLB row and show no later deal in
# milb_transactions_master.csv, and the source is their last move there. The last two are his direct picks.
HAND_ADDED = {
    544150: ('Albert Suárez', 'elected'),
    676480: ('José Barrero', 'elected'),
    623437: ('Justin Topa', 'elected'),
    642851: ('Austin Wynns', 'elected'),
    666201: ('Alek Manoah', 'released'),
    664068: ('Scott Kingery', 'released'),
    669145: ('Bruce Zimmermann', 'elected'),
    666185: ('Dylan Carlson', 'released'),
    666619: ('Gregory Santos', 'elected'),
    664192: ('Joey Lucchesi', 'released'),
    663609: ('Luken Baker', 'released'),
    605441: ('Yacksel Ríos', 'released'),
    669288: ('Daniel Johnson', 'released'),
    674370: ('Osvaldo Bido', 'released'),
    665750: ('Leody Taveras', 'hand'),
    596117: ('Garrett Stubbs', 'hand'),
    # On the Elected MLB FA, Elected MiLB FA or MLB-level Released columns of Wally's 2026/27 MLB Offseason sheet, 2026-11-03.
    656976: ('Pavin Smith', 'elected'),
    683155: ('Joey Estes', 'elected'),
    664129: ('Geoff Hartlieb', 'elected'),
    671286: ('Johnathan Rodríguez', 'elected'),
    661531: ('Brian Serven', 'elected'),
    683021: ('Michael Stefanic', 'elected'),
    680577: ('DaShawn Keirsey Jr.', 'elected'),
    677008: ('Heston Kjerstad', 'released'),
    650968: ('Yohel Pozo', 'elected'),
    682769: ('Eiberson Castellano', 'elected'),
    669298: ('TJ Shook', 'elected'),
    677060: ('Chad Stevens', 'elected'),
    667452: ('Corey Julks', 'elected'),
    676694: ('Jake Meyers', 'elected'),
    656638: ('Alex Lange', 'elected'),
    665861: ('Sebastián Rivero', 'elected'),
    640459: ('Brian Navarreto', 'elected'),
    676604: ('Tyler Zuber', 'elected'),
    687287: ('Patrick Monteverde', 'elected'),
    657649: ('Jared Koenig', 'elected'),
    669060: ('Bryse Wilson', 'elected'),
    656484: ('Tristan Gray', 'elected'),
    693306: ('Aaron Sabato', 'elected'),
    665506: ('Cristian Pache', 'elected'),
    676572: ('Eric Wagaman', 'elected'),
    681006: ('Josh Simpson', 'elected'),
    642215: ('Weston Wilson', 'elected'),
    669717: ('Will Wilson', 'elected'),
    621550: ('Patrick Wisdom', 'elected'),
    671345: ('Jason Foley', 'elected'),
    663941: ('Tristan Beck', 'released'),
    657424: ('Matt Gage', 'elected'),
    678545: ('Osleivis Basabe', 'elected'),
    668800: ('Andrew Knizner', 'elected'),
    669270: ('Joel Kuhnel', 'elected'),
    663611: ('Nick Madrigal', 'elected'),
    669169: ('Jonathan Heasley', 'elected'),
    663992: ('Richard Lovelady', 'elected'),
    676571: ('PJ Poulin', 'elected'),
    # On released.numbers or elected fa.numbers with a 2026 MLB row, per Wally 2026-11-05. The full build also reaches them; here for --overrides-only.
    687849: ('Zak Kent', 'released'),
    693459: ('Kyler Fedko', 'released'),
    667463: ('John King', 'elected'),
    676596: ('Josh Fleming', 'elected'),
    606992: ('Eric Haase', 'elected'),
    628451: ('Andy Ibáñez', 'elected'),
    642020: ('Chuckie Robinson', 'released'),
    686894: ('Joey Wiemer', 'elected'),
    689520: ('Cody Laweryson', 'elected'),
    641598: ('Mitch Garver', 'released'),
    672279: ('Michael Siani', 'elected'),
    672284: ('Jarred Kelenic', 'elected'),
    678760: ('Eddys Leonard', 'elected'),
    680716: ('Jonathan Ornelas', 'elected'),
    666931: ('Jared Oliva', 'elected'),
    650559: ('Bryan De La Cruz', 'released'),
    628708: ('Yunior Marte', 'released'),
    666624: ('Christopher Morel', 'released'),
    663465: ('Kolby Allard', 'elected'),
    668974: ('Maverick Handley', 'released'),
    642546: ('Jonathan Hernández', 'elected'),
    506702: ('Sandy León', 'elected'),
    624512: ('Reese McGuire', 'elected'),
    641312: ('Shaun Anderson', 'elected'),
    592826: ('Vince Velasquez', 'elected'),
    605218: ('Carl Edwards Jr.', 'elected'),
    672335: ('Cionel Pérez', 'elected'),
    640492: ('José Azócar', 'elected'),
    666464: ('Jerar Encarnacion', 'elected'),
    681806: ('Andrew Wantz', 'elected'),
    682515: ('Logan Porter', 'elected'),
    644433: ('Chadwick Tromp', 'elected'),
    647315: ('Zach Pop', 'elected'),
    641820: ('Trey Mancini', 'elected'),
    669256: ('Nick Solak', 'elected'),
    685005: ('Christian Roa', 'elected'),
    656413: ('Stuart Fairchild', 'elected'),
    640454: ('Matt Krook', 'elected'),
    656212: ('Charlie Barnes', 'elected'),
    675659: ('Greg Jones', 'elected'),
    669699: ('Braden Shewmake', 'elected'),
    606965: ('Chris Devenski', 'elected'),
    669212: ('Eli Morgan', 'elected'),
    676760: ('Ron Marinaccio', 'elected'),
    671083: ('Buddy Kennedy', 'elected'),
    680573: ('Simeon Woods Richardson', 'elected'),
    641386: ('Ben Bowden', 'elected'),
    688497: ('Taylor Rashi', 'elected'),
    665856: ('Jair Camargo', 'elected'),
    664744: ('Jose Espada', 'elected'),
    676051: ('Codi Heuer', 'elected'),
    656457: ('Tyler Gilbert', 'elected'),
    678577: ('Junior Perez', 'elected'),
    671155: ('Ivan Johnson', 'elected'),
    671655: ('George Valera', 'elected'),
    678368: ('Valente Bellozo', 'elected'),
    666397: ('Edouard Julien', 'elected'),
    605353: ('Vimael Machín', 'elected'),
    624522: ('Keegan Thompson', 'elected'),
    669360: ('Trei Cruz', 'elected'),
    681546: ('James Outman', 'elected'),
    675989: ('Cody Bolton', 'elected'),
    681432: ('Luke Little', 'elected'),
    683079: ('Omar Martinez', 'elected'),
    608344: ('Cole Irvin', 'elected'),
    678225: ('Jihwan Bae', 'elected'),
    682641: ('Luis Matos', 'elected'),
    656577: ('Alex Jackson', 'elected'),
    675540: ('Xzavion Curry', 'elected'),
    676910: ('Matt Seelinger', 'elected'),
    670871: ('Guillo Zuñiga', 'elected'),
    529017: ('Alexander Cornielle', 'elected'),
    672642: ('Steward Berroa', 'elected'),
    662144: ('Brian Keller', 'elected'),
    669369: ('Bryce Johnson', 'elected'),
    686823: ('Will Brennan', 'elected'),
    678576: ('Wilkin Ramos', 'elected'),
    646242: ('Jhonathan Díaz', 'elected'),
    682445: ('Domingo Gonzalez', 'elected'),
    656582: ('Connor Joe', 'elected'),
    663884: ('Nolan Kingham', 'elected'),
    681168: ('Luis Curvelo', 'elected'),
    680737: ('Michael Helman', 'elected'),
    681084: ('Tanner Andrews', 'elected'),
    663662: ('Daz Cameron', 'elected'),
    669310: ('CJ Van Eyk', 'elected'),
    676680: ('Tom Cosgrove', 'elected'),
    686610: ('Ken Waldichuk', 'elected'),
}
# Removed by hand per Wally. A source list can still carry them, so they are dropped by id.
REMOVED = {
    623454: 'Drew Anderson',
    657675: 'Rudy Martin Jr., per Wally 2026-11-05',
    687134: 'Bradley Blalock, per Wally 2026-11-05',
}
BASE_SEASON = 2026          # the season just played; ages are for BASE_SEASON + 1
PITCHER_POS = {'P', 'SP', 'RP', 'RHP', 'LHP'}
SUFFIX = re.compile(r'\b(jr|sr|ii|iii|iv)\b')


def norm_name(name):
    """'García Jr., Luis' and 'Luis Garcia' both become 'luis garcia'."""
    name = (name or '').strip()
    if ',' in name:
        last, first = name.split(',', 1)
        name = first.strip() + ' ' + last.strip()
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    name = name.lower().replace('.', '').replace('-', ' ').replace("'", '')
    name = SUFFIX.sub('', name)
    return ' '.join(name.split())


def is_pitcher_pos(pos):
    return any(p.strip().upper() in PITCHER_POS for p in (pos or '').split('/'))


def mlb_index():
    """mlbId -> {name, teams, pitcher, hitter} for every 2026 MLB row."""
    idx = {}
    for fname, side in (('pitcher_leaderboard_rs.json', 'pitcher'),
                        ('hitter_leaderboard_rs.json', 'hitter')):
        with open(os.path.join(DATA, fname)) as f:
            rows = json.load(f)
        for r in rows:
            if r['team'] in AAA_TEAMS:
                continue
            p = idx.setdefault(r['mlbId'], {'name': r[side], 'teams': set(),
                                            'pitcher': False, 'hitter': False})
            p[side] = True
            p['teams'].add(r['team'])
    by_name = {}
    for mid, p in idx.items():
        by_name.setdefault(norm_name(p['name']), []).append(mid)
    return idx, by_name


def birth_dates():
    """mlbId -> 'yyyy-mm-dd' from the season lines, most recent season first."""
    out = {}
    for y in range(BASE_SEASON, BASE_SEASON - 3, -1):
        for kind in ('pitching', 'hitting'):
            path = os.path.join(DATA, '_proj', f'lines_{kind}_{y}.json')
            if not os.path.exists(path):
                continue
            with open(path) as f:
                for r in json.load(f):
                    if r.get('birth') and r['id'] not in out:
                        out[r['id']] = r['birth']
    if not out:
        sys.exit('No season lines in data/_proj/; run scripts/research/projection/pull_season_lines.py first.')
    return out


def baseball_age(birth, season):
    y, m, d = (int(x) for x in birth.split('-'))
    return season - y - (1 if (m, d) > (6, 30) else 0)


def fangraphs_ids(season):
    """FanGraphs playerid (str) -> MLB id, from the season's MLB leaders rows."""
    from pipeline import fg_overrides as F
    out = {}
    for stats in ('bat', 'pit'):
        url = (f'{F.FG_API}?pos=all&stats={stats}&lg=all&qual=0&type=1'
               f'&season={season}&seasonEnd={season}&ind=0&pageitems=5000&pagenum=1')
        try:
            rows = F._http_get_json(url).get('data', [])
        except (OSError, ValueError) as e:
            sys.exit(f'FanGraphs {stats} leaders fetch failed ({e}); nothing written. '
                     f'The tracker rows cannot be matched by id without it.')
        if len(rows) < 300:
            sys.exit(f'FanGraphs {stats} leaders returned only {len(rows)} rows; nothing written.')
        for r in rows:
            if r.get('playerid') is not None and r.get('xMLBAMID') is not None:
                out[str(r['playerid'])] = int(r['xMLBAMID'])
    return out


def transaction_ids(dates):
    """{(date, normalized name): {person ids}} from the MLB transactions API for
    the given yyyy-mm-dd dates (one request per month touched)."""
    import urllib.request
    out = {}
    months = sorted({d[:7] for d in dates})
    for m in months:
        ds = sorted(d for d in dates if d[:7] == m)
        url = ('https://statsapi.mlb.com/api/v1/transactions'
               f'?startDate={ds[0]}&endDate={ds[-1]}')
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                tx = json.load(r).get('transactions', [])
        except (OSError, ValueError) as e:
            sys.exit(f'MLB transactions fetch failed for {m} ({e}); nothing written.')
        for t in tx:
            person = t.get('person') or {}
            if person.get('id') is None:
                continue
            for d in {t.get('date'), t.get('effectiveDate')} - {None}:
                out.setdefault((d, norm_name(person.get('fullName'))), set()).add(person['id'])
    return out


def resolve_transaction(row, tx_ids, idx):
    """Return (mlbId, None) or (None, reason) for a released / elected row."""
    ids = tx_ids.get((row['date'], norm_name(row['name'])))
    if not ids:
        return None, 'no transaction on that date'
    if len(ids) > 1:
        return None, 'ambiguous: ' + ', '.join(str(i) for i in sorted(ids))
    mid = next(iter(ids))
    return (mid, None) if mid in idx else (None, 'no 2026 MLB row')


def read_fangraphs(path):
    import openpyxl
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).active
    rows = ws.iter_rows(values_only=True)
    hdr = list(next(rows))
    need = ('Name', 'FA Likelihood', 'Pos', 'Prev Team', 'playerid')
    missing = [h for h in need if h not in hdr]
    if missing:
        sys.exit(f'{path}: missing column(s) {missing}. Re-export the FanGraphs tracker.')
    col = {h: hdr.index(h) for h in need}
    out = []
    for r in rows:
        if not r[col['Name']]:
            continue
        out.append({'name': r[col['Name']], 'status': r[col['FA Likelihood']],
                    'pos': r[col['Pos']], 'team': r[col['Prev Team']],
                    'fgId': str(r[col['playerid']]).strip() if r[col['playerid']] is not None else ''})
    return out


def read_numbers(path, tmpdir):
    """Export a .numbers file to CSV through Numbers.app, then read it."""
    import csv
    dest = os.path.join(tmpdir, os.path.basename(path) + '.csv')
    script = (f'tell application "Numbers"\n'
              f'set d to open POSIX file "{path}"\n'
              f'export d to POSIX file "{dest}" as CSV\n'
              f'close d saving no\n'
              f'end tell')
    res = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
    if res.returncode != 0 or not os.path.exists(dest):
        sys.exit(f'{path}: Numbers export failed: {res.stderr.strip()}')
    with open(dest, newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    if rows and not {'Player', 'Position', 'Team'} <= set(rows[0]):
        sys.exit(f'{path}: expected Player, Position and Team columns, got {list(rows[0])}')
    return [{'name': r['Player'], 'pos': r['Position'],
             'team': TEAM_NAME_TO_ABBREV.get(r['Team'], r['Team']),
             'date': r.get('Date', '')} for r in rows if r.get('Player')]


def newest(pattern):
    hits = sorted(glob.glob(os.path.join(DOWNLOADS, pattern)), key=os.path.getmtime)
    return hits[-1] if hits else None


def write_out(players):
    """Stamp ages and write the JSON atomically. Returns the count with no birth date."""
    births = birth_dates()
    no_birth = 0
    for mid, e in players.items():
        b = births.get(mid)
        e['age'] = baseball_age(b, BASE_SEASON + 1) if b else None
        no_birth += b is None
    out = {'generatedAt': date.today().isoformat(), 'ageSeason': BASE_SEASON + 1,
           'players': sorted(players.values(), key=lambda e: e['mlbId'])}
    fd, tmp_path = tempfile.mkstemp(dir=DATA, suffix='.json')
    with os.fdopen(fd, 'w') as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp_path, OUT)
    return no_birth


def overrides_only():
    """Apply SIGNED, RETIRED, REMOVED, MLBPA_XXB and HAND_ADDED to the current JSON, reading no source list."""
    idx, _by_name = mlb_index()
    with open(OUT) as f:
        players = {e['mlbId']: e for e in json.load(f)['players']}
    n0 = len(players)
    for mid in list(players):
        if mid in SIGNED or mid in RETIRED or mid in REMOVED:
            print(f'removed {players.pop(mid)["name"]} ({mid})')
    for mid in MLBPA_XXB:
        if mid not in idx:
            sys.exit(f'MLBPA_XXB {MLBPA_XXB[mid]} ({mid}) has no 2026 MLB row; nothing written.')
        if mid not in players:
            players[mid] = {'mlbId': mid, 'name': idx[mid]['name'], 'sources': ['mlbpa']}
            print(f'added {idx[mid]["name"]} ({mid})')
    for mid, (name, source) in HAND_ADDED.items():
        if mid not in idx:
            sys.exit(f'HAND_ADDED {name} ({mid}) has no 2026 MLB row; nothing written.')
        if mid not in players:
            players[mid] = {'mlbId': mid, 'name': idx[mid]['name'], 'sources': [source]}
            print(f'added {idx[mid]["name"]} ({mid}, {source})')
    no_birth = write_out(players)
    print(f'Wrote {len(players)} players (was {n0}), {no_birth} without a birth date')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    # The tracker for the class being built, by year: Downloads also holds past trackers
    # (the contract model's history), and the newest file is not always this class.
    ap.add_argument('--fangraphs', default=newest(f'{BASE_SEASON + 1}-free-agent-tracker*.xlsx'))
    ap.add_argument('--released', default=os.path.join(DOWNLOADS, 'released.numbers'))
    ap.add_argument('--elected', default=os.path.join(DOWNLOADS, 'elected fa.numbers'))
    ap.add_argument('--overrides-only', action='store_true',
                    help='apply SIGNED, RETIRED, REMOVED, MLBPA_XXB and HAND_ADDED to the current JSON and stop; reads no source list')
    args = ap.parse_args()
    if args.overrides_only:
        overrides_only()
        return
    for label, p in (('FanGraphs tracker', args.fangraphs), ('released', args.released),
                     ('elected FA', args.elected)):
        if not p or not os.path.exists(p):
            sys.exit(f'{label} file not found: {p}')

    idx, _by_name = mlb_index()
    players = {}   # mlbId -> entry
    dropped = []   # (source, name, reason)

    def add(mid, source, status=None):
        if mid in SIGNED or mid in RETIRED or mid in REMOVED:
            return
        e = players.setdefault(mid, {'mlbId': mid, 'name': idx[mid]['name'], 'sources': []})
        if source not in e['sources']:
            e['sources'].append(source)
        if status:
            e['fgStatus'] = status

    fg = read_fangraphs(args.fangraphs)
    fg_ids = fangraphs_ids(BASE_SEASON)
    n_fg_excl = 0
    for r in fg:
        if r['status'] in FG_EXCLUDE:
            n_fg_excl += 1
            continue
        mid = fg_ids.get(r['fgId'])
        if mid is None or mid not in idx:
            dropped.append(('fangraphs', r['name'], 'no 2026 MLB row'))
        else:
            add(mid, 'fangraphs', r['status'])

    with tempfile.TemporaryDirectory() as tmp:
        lists = (('released', read_numbers(args.released, tmp)),
                 ('elected', read_numbers(args.elected, tmp)))
    bad_dates = [r for _s, rows in lists for r in rows
                 if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', r['date'] or '')]
    if bad_dates:
        sys.exit(f"{len(bad_dates)} transaction row(s) have no yyyy-mm-dd Date "
                 f"(first: {bad_dates[0]['name']!r} {bad_dates[0]['date']!r}); the id lookup needs it.")
    tx_ids = transaction_ids({r['date'] for _s, rows in lists for r in rows})
    for source, rows in lists:
        for r in rows:
            mid, why = resolve_transaction(r, tx_ids, idx)
            if mid is None:
                dropped.append((source, r['name'], why))
            else:
                add(mid, source)

    for mid in MLBPA_XXB:
        if mid not in idx:
            sys.exit(f'MLBPA_XXB {MLBPA_XXB[mid]} ({mid}) has no 2026 MLB row; nothing written.')
        add(mid, 'mlbpa')
    for mid, (name, source) in HAND_ADDED.items():
        if mid not in idx:
            sys.exit(f'HAND_ADDED {name} ({mid}) has no 2026 MLB row; nothing written.')
        add(mid, source)
    no_birth = write_out(players)

    print(f'FanGraphs: {len(fg)} rows, {n_fg_excl} excluded as NOT_HAPPENING / PROBABLY_NOT_FA')
    for source, rows in lists:
        print(f'{source}: {len(rows)} rows')
    by_src = {}
    for e in players.values():
        by_src[' + '.join(e['sources'])] = by_src.get(' + '.join(e['sources']), 0) + 1
    for k, v in sorted(by_src.items()):
        print(f'  {v:4d}  {k}')
    print(f'Left out as already signed (SIGNED): {len(SIGNED)}')
    print(f'Wrote {len(players)} players to {os.path.relpath(OUT, ROOT)} ({no_birth} without a birth date, age blank)')
    amb = [d for d in dropped if d[2].startswith('ambiguous')]
    notx = [d for d in dropped if d[2] == 'no transaction on that date']
    nomlb = [d for d in dropped if d[2] == 'no 2026 MLB row']
    print(f'Left out: {len(nomlb)} with no 2026 MLB row, {len(notx)} with no transaction '
          f'on their date, {len(amb)} ambiguous')
    for s, n, why in amb:
        print(f'  AMBIGUOUS  {s:9s} {n}  ({why})')
    for s, n, why in notx:
        print(f'  NO TRANSACTION FOUND  {s:9s} {n}')
    if os.environ.get('FA_VERBOSE'):
        for s, n, why in nomlb:
            print(f'  no MLB row {s:9s} {n}')


if __name__ == '__main__':
    main()
