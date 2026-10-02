"""pull_savant_history.py: Savant season leaderboards 2015-2026 for the projection backtest.

expected_statistics (batter and pitcher: PA, BIP, wOBA, xwOBA, BA/xBA, SLG/xSLG) and
sprint_speed, one CSV per kind-season in data/_proj/. min=1 on every board, so the
caller applies its own sample gate. Existing files are reused except the live season.

Usage: python3 scripts/research/projection/pull_savant_history.py
"""
import csv
import io
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT = os.path.join(ROOT, 'data', '_proj')
LIVE = 2026
BOARDS = {
    'xstats_batter': 'https://baseballsavant.mlb.com/leaderboard/expected_statistics?type=batter&year={y}&position=&team=&filterType=pa&min=1&csv=true',
    'xstats_pitcher': 'https://baseballsavant.mlb.com/leaderboard/expected_statistics?type=pitcher&year={y}&position=&team=&filterType=pa&min=1&csv=true',
    'sprint': 'https://baseballsavant.mlb.com/leaderboard/sprint_speed?min_season={y}&max_season={y}&position=&team=&min=1&csv=true',
}


def pull(kind, y):
    path = os.path.join(OUT, f'{kind}_{y}.csv')
    if os.path.exists(path) and y != LIVE:
        return None
    body = subprocess.run(['curl', '-sfL', '--retry', '3', BOARDS[kind].format(y=y)],
                          capture_output=True, check=True).stdout.decode('utf-8-sig')
    rows = list(csv.DictReader(io.StringIO(body)))
    if len(rows) < 100:   # an HTML page or an empty board parses to almost nothing
        raise RuntimeError(f'{kind} {y}: {len(rows)} rows; Savant served something else')
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        f.write(body)
    os.replace(tmp, path)
    return len(rows)


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    for y in range(2015, LIVE + 1):
        print(y, {k: pull(k, y) for k in BOARDS})
