"""Where should the social card fade a small-sample xwOBAcon?

The cell is the rendered one: season x batter hand x pitch type for one pitcher.
Split-half r of xwOBAcon at m balls in play per half, 2021-2025, repeated random
splits. n is the first m where r reaches .50, the point at which a value is half
signal; the repo already uses the same anchor (MIN_HITTER_SWINGS). The fade is a
trade between hiding numbers and warning about noise with no stated exchange rate,
so n is a convention anchored on this curve, not an optimum.

    python3 scripts/research/cards/social_xwobacon_fade.py
"""
import gc
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
GRID = [5, 10, 15, 20, 25, 30, 40, 50, 60, 75]


def num(s):
    return pd.to_numeric(s, errors='coerce').to_numpy('float64', na_value=np.nan)


def main():
    rng = np.random.default_rng(0)
    print('m   ' + ' '.join(f'{y:>10d}' for y in range(2021, 2026)) + '     mean')
    table = {m: [] for m in GRID}
    cells = []
    for y in range(2021, 2026):
        d = pd.read_pickle(os.path.join(ROOT, 'data', f'_statcast{y}_cache.pkl'))
        d = d[(d['type'] == 'X') & d.bb_type.notna() & d.bb_type.astype('object').ne('bunt')]
        o = pd.DataFrame({'p': num(d.pitcher), 's': d.stand.astype('object').to_numpy(),
                          't': d.pitch_type.astype('object').to_numpy(),
                          'x': num(d.estimated_woba_using_speedangle)}).dropna()
        del d
        gc.collect()
        groups = [g.x.to_numpy() for _, g in o.groupby(['p', 's', 't'], sort=False)]
        cells.append(np.array([len(g) for g in groups]))
        for m in GRID:
            use = [g for g in groups if len(g) >= 2 * m]
            rs = []
            for _ in range(50):
                a, b = [], []
                for g in use:
                    i = rng.permutation(len(g))
                    a.append(g[i[:m]].mean())
                    b.append(g[i[m:2 * m]].mean())
                rs.append(np.corrcoef(a, b)[0, 1])
            table[m].append((float(np.mean(rs)), len(use)))
    for m in GRID:
        print(f'{m:<3d} ' + ' '.join(f'{r:.3f}({n:>3d})' for r, n in table[m])
              + f'  {np.mean([r for r, _ in table[m]]):.3f}')
    allc = np.concatenate(cells)
    print('share of cells with n BIP below:', {k: round(float((allc < k).mean()), 3) for k in (5, 10, 15, 20, 25, 30, 40)})


if __name__ == '__main__':
    main()
