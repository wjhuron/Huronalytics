"""Build data/free_agents.json, the player set behind the site's Free Agents filter.

Three hand-kept sources, all in ~/Downloads by default:

  * the FanGraphs free-agent tracker (.xlsx). Every row counts EXCEPT the
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


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--fangraphs', default=newest('*free-agent-tracker*.xlsx'))
    ap.add_argument('--released', default=os.path.join(DOWNLOADS, 'released.numbers'))
    ap.add_argument('--elected', default=os.path.join(DOWNLOADS, 'elected fa.numbers'))
    args = ap.parse_args()
    for label, p in (('FanGraphs tracker', args.fangraphs), ('released', args.released),
                     ('elected FA', args.elected)):
        if not p or not os.path.exists(p):
            sys.exit(f'{label} file not found: {p}')

    idx, _by_name = mlb_index()
    players = {}   # mlbId -> entry
    dropped = []   # (source, name, reason)

    def add(mid, source, status=None):
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

    print(f'FanGraphs: {len(fg)} rows, {n_fg_excl} excluded as NOT_HAPPENING / PROBABLY_NOT_FA')
    for source, rows in lists:
        print(f'{source}: {len(rows)} rows')
    by_src = {}
    for e in players.values():
        by_src[' + '.join(e['sources'])] = by_src.get(' + '.join(e['sources']), 0) + 1
    for k, v in sorted(by_src.items()):
        print(f'  {v:4d}  {k}')
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
