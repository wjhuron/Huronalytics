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

Names are matched to mlbId through the shipped leaderboard rows. A name that
matches several MLB players is resolved by role (pitcher vs hitter) and then
by the listed team; anything still ambiguous is printed and left out, never
guessed. Each player also carries his baseball age (June 30) in the season after BASE_SEASON, from
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


def resolve(name, pos, team, idx, by_name):
    """Return (mlbId, None) or (None, reason)."""
    cands = by_name.get(norm_name(name), [])
    if not cands:
        return None, 'no 2026 MLB row'
    if len(cands) > 1 and pos:
        side = 'pitcher' if is_pitcher_pos(pos) else 'hitter'
        narrowed = [c for c in cands if idx[c][side]]
        cands = narrowed or cands
    if len(cands) > 1 and team:
        narrowed = [c for c in cands if team in idx[c]['teams']]
        cands = narrowed or cands
    if len(cands) > 1:
        return None, 'ambiguous: ' + ', '.join(str(c) for c in cands)
    return cands[0], None


def read_fangraphs(path):
    import openpyxl
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).active
    rows = ws.iter_rows(values_only=True)
    hdr = list(next(rows))
    need = ('Name', 'FA Likelihood', 'Pos', 'Prev Team')
    missing = [h for h in need if h not in hdr]
    if missing:
        sys.exit(f'{path}: missing column(s) {missing}. Re-export the FanGraphs tracker.')
    col = {h: hdr.index(h) for h in need}
    out = []
    for r in rows:
        if not r[col['Name']]:
            continue
        out.append({'name': r[col['Name']], 'status': r[col['FA Likelihood']],
                    'pos': r[col['Pos']], 'team': r[col['Prev Team']]})
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

    idx, by_name = mlb_index()
    players = {}   # mlbId -> entry
    dropped = []   # (source, name, reason)

    def add(mid, source, status=None):
        e = players.setdefault(mid, {'mlbId': mid, 'name': idx[mid]['name'], 'sources': []})
        if source not in e['sources']:
            e['sources'].append(source)
        if status:
            e['fgStatus'] = status

    fg = read_fangraphs(args.fangraphs)
    n_fg_excl = 0
    for r in fg:
        if r['status'] in FG_EXCLUDE:
            n_fg_excl += 1
            continue
        mid, why = resolve(r['name'], r['pos'], r['team'], idx, by_name)
        if mid is None:
            dropped.append(('fangraphs', r['name'], why))
        else:
            add(mid, 'fangraphs', r['status'])

    with tempfile.TemporaryDirectory() as tmp:
        lists = (('released', read_numbers(args.released, tmp)),
                 ('elected', read_numbers(args.elected, tmp)))
    for source, rows in lists:
        for r in rows:
            mid, why = resolve(r['name'], r['pos'], r['team'], idx, by_name)
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
    nomlb = [d for d in dropped if not d[2].startswith('ambiguous')]
    print(f'Left out: {len(nomlb)} with no 2026 MLB row, {len(amb)} ambiguous')
    for s, n, why in amb:
        print(f'  AMBIGUOUS  {s:9s} {n}  ({why})')
    if os.environ.get('FA_VERBOSE'):
        for s, n, why in nomlb:
            print(f'  no MLB row {s:9s} {n}')


if __name__ == '__main__':
    main()
