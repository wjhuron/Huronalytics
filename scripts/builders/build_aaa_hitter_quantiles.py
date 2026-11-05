"""The AAA percentile table the site ranks ROC hitters against: data/aaa_hitter_quantiles_rs.json.

101 quantiles per stat over every 2026 AAA hitter, so the pipeline and js/aggregator.js rank a
ROC row inside AAA, the rule the AAA cards follow (2026-11-05, per Wally). Official-line stats
come from FanGraphs' AAA line, everything else from the corpus pool
(scripts/research/cards/aaa_relative_grades.py). CI has no corpus, so this file is committed;
rebuild it when the pool is rebuilt.

    .venv/bin/python scripts/builders/build_aaa_hitter_quantiles.py
"""
import json
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POOL = os.path.join(ROOT, 'data', '_milb2026', 'hitter_pool_AAA.json')
FG = os.path.join(ROOT, 'data', '_milb2026', 'fg_hitters_level1.json')
OUT = os.path.join(ROOT, 'data', 'aaa_hitter_quantiles_rs.json')
# Leaderboard key -> FanGraphs column for the official line.
OFFICIAL = {'avg': 'AVG', 'obp': 'OBP', 'slg': 'SLG', 'ops': 'OPS', 'iso': 'ISO', 'babip': 'BABIP',
            'wOBA': 'wOBA', 'hr': 'HR', 'sb': 'SB', 'bbPct': 'BB%', 'kPct': 'K%', 'bbToK': 'BB/K',
            'wRCplus': 'wRC+'}


def main():
    with open(POOL) as f:
        pool = json.load(f)
    with open(FG) as f:
        fg = [v['line'] for v in json.load(f).values() if v.get('line')]
    cols = {k for v in pool.values() for k, x in v.items() if isinstance(x, (int, float))
            and not isinstance(x, bool) and k not in ('name', 'club', 'bbPlusNoBat')}
    out = {}
    for key in sorted(cols | set(OFFICIAL)):
        vals = ([l[OFFICIAL[key]] for l in fg if l.get(OFFICIAL[key]) is not None] if key in OFFICIAL
                else [v[key] for v in pool.values() if v.get(key) is not None])
        if len(vals) >= 50:
            out[key] = [round(float(x), 6) for x in np.percentile(vals, np.arange(101))]
    with open(OUT + '.tmp', 'w') as f:
        json.dump({'season': 2026, 'hitters': len(pool), 'quantiles': out}, f, separators=(',', ':'))
    os.replace(OUT + '.tmp', OUT)
    print(f'{len(out)} stats over {len(pool)} AAA hitters -> {OUT} ({os.path.getsize(OUT) // 1024} KB)')


if __name__ == '__main__':
    main()
