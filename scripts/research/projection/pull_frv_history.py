"""pull_frv_history.py: Savant Fielding Run Value 2016-2026 for the fielding projection.

Parses the JSON table embedded in the fielding-run-value page, the same way
pipeline.fetch.fetch_fielding_runs does, but writes data/_proj/frv_{Y}.json and never the
live cache (that function overwrites data/fielding_runs_cache.json for whatever year it is
given). Existing past seasons are reused; the live season is always re-pulled.

Usage: python3 scripts/research/projection/pull_frv_history.py
"""
import json
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT = os.path.join(ROOT, 'data', '_proj')
LIVE = 2026
URL = 'https://baseballsavant.mlb.com/leaderboard/fielding-run-value?type=player&year={y}&min=1'


def parse(html):
    i = html.find('"range_runs"')
    if i < 0:
        raise ValueError('no range_runs key in the page')
    j = html.rfind('[', 0, i)
    depth, k = 0, j
    while k < len(html):
        if html[k] == '[':
            depth += 1
        elif html[k] == ']':
            depth -= 1
            if depth == 0:
                break
        k += 1
    out = {}
    for r in json.loads(html[j:k + 1]):
        if r.get('id') is None:
            continue
        f = lambda key: (float(r[key]) if r.get(key) is not None else None)
        out[str(int(r['id']))] = {
            'name': r.get('name'), 'team_id': r.get('team_id'),
            'range': f('range_runs'), 'arm': f('arm_runs'), 'dp': f('dp_runs'), 'catching': f('catching_runs'),
            'framing': f('framing_runs'), 'throwing': f('throwing_runs'), 'blocking': f('blocking_runs'),
            'total': f('total_runs'),
            'outs_by_pos': {str(p): int(r[f'outs_{p}'] or 0) for p in range(2, 10) if r.get(f'outs_{p}') is not None},
        }
    return out


if __name__ == '__main__':
    for y in range(2016, LIVE + 1):
        path = os.path.join(OUT, f'frv_{y}.json')
        if os.path.exists(path) and y != LIVE:
            print(y, 'cached'); continue
        html = subprocess.run(['curl', '-sfL', '--retry', '3', URL.format(y=y)], capture_output=True, check=True).stdout.decode('utf-8', 'ignore')
        out = parse(html)
        if len(out) < 100:
            raise RuntimeError(f'{y}: {len(out)} fielders; page shape changed')
        tmp = path + '.tmp'
        with open(tmp, 'w') as fh:
            json.dump(out, fh)
        os.replace(tmp, path)
        print(y, len(out), 'fielders, total', round(sum(v['total'] or 0 for v in out.values()), 1))
