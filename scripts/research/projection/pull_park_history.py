"""pull_park_history.py: Savant runs park factors 2015-2026 into data/_proj/park_factors_hist.json.

Reuses pull() from scripts/builders/park_factors_pull.py (same endpoint, same 3 -> 2 -> 1
rolling-window cascade, because the rolling-3 board omits a club whose venue lacks three
seasons) but never writes data/park_factors.json, which the pipeline reads.

Usage: python3 scripts/research/projection/pull_park_history.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'builders'))
from park_factors_pull import pull, WINDOWS  # noqa: E402

OUT = os.path.join(ROOT, 'data', '_proj', 'park_factors_hist.json')

if __name__ == '__main__':
    result, windows = {}, {}
    for y in range(2015, 2027):
        season, used = {}, {}
        for w in WINDOWS:
            try:
                got = pull(y, w)
            except RuntimeError as e:
                print(f'  {y} rolling {w}: {e}')
                continue
            for tid, pf in got.items():
                if tid not in season:
                    season[tid], used[tid] = pf, w
        if len(season) < 30:
            raise RuntimeError(f'{y}: {len(season)} clubs resolved')
        result[str(y)], windows[str(y)] = season, used
        print(y, len(season), 'clubs', 'min', min(season.values()), 'max', max(season.values()))
    result['_window'] = windows
    tmp = OUT + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(result, f)
    os.replace(tmp, OUT)
