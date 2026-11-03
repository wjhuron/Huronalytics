"""Dense catch-probability table, identical to scripts/tools/catch_prob.py.

`catch_prob.lookup` scans every surface cell per call, which is too slow for
an alignment search (millions of lookups). This builds the same
expanding-ring weighted lookup once on the full (time tenth, foot) grid with
box sums, then serves it by array indexing. `verify()` checks it against
the tool on random points; it must match exactly.

Outside the surface: a distance past the last tracked cell (138 ft) has no
catch in 95k plays and reads 0; a time outside 2.1-7.9 s is clamped to the
edge tenth. Both are printed by `coverage()`.
"""
import numpy as np

import catch_prob as cp

T0, T1 = 2.1, 7.9
D_MAX = 200


def build():
    cells, _ = cp.load_surface()
    nt = int(round((T1 - T0) * 10)) + 1
    grid = np.full((2, 2, nt, D_MAX + 1), np.nan)
    for b in (0, 1):
        for w in (0, 1):
            pn = np.zeros((nt, D_MAX + 1))
            nn = np.zeros((nt, D_MAX + 1))
            for (t, d, cb, cw), (p, n, *_r) in cells.items():
                if cb == b and cw == w and d <= D_MAX:
                    i = int(round((t - T0) * 10))
                    pn[i, d] += p * n
                    nn[i, d] += n
            cpn = np.pad(pn, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
            cnn = np.pad(nn, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
            out = np.full((nt, D_MAX + 1), np.nan)
            last = np.full((nt, D_MAX + 1), np.nan)
            ii, dd = np.meshgrid(np.arange(nt), np.arange(D_MAX + 1), indexing='ij')
            for ring in range(1, cp.MAX_RING + 1):
                # The tool's window is |ct - t| <= 0.05 * ring (+1e-9); on
                # the tenth grid that is floor(ring / 2) tenths each way.
                ht = ring // 2
                hd = cp.DIST_STEP * ring
                i0, i1 = np.clip(ii - ht, 0, nt), np.clip(ii + ht + 1, 0, nt)
                d0, d1 = np.clip(dd - hd, 0, D_MAX + 1), np.clip(dd + hd + 1, 0, D_MAX + 1)
                sp = cpn[i1, d1] - cpn[i0, d1] - cpn[i1, d0] + cpn[i0, d0]
                sn = cnn[i1, d1] - cnn[i0, d1] - cnn[i1, d0] + cnn[i0, d0]
                val = np.where(sn > 0, sp / np.where(sn > 0, sn, 1), np.nan)
                take = np.isnan(out) & (sn >= cp.K_MIN)
                out[take] = val[take]
                last = np.where(sn > 0, val, last)
            out = np.where(np.isnan(out), last, out)   # tool: last ring with any data
            grid[b, w] = out
    return grid


def fill(grid):
    """Fill empty cells from the table's own monotonicity.

    Catch probability does not rise with distance or fall with time, so an
    empty (t, d) cell is at least the best tracked cell with less time and
    more distance. That lower bound fills it; a cell with no such cell (no
    play that long or that short in 95k) reads 0. A flat 0 fill was wrong:
    it scored a 10 ft play with 7.5 s of hang as a sure hit.
    """
    g = grid.copy()
    n_filled = int(np.isnan(g).sum())
    for b in (0, 1):
        for w in (0, 1):
            a = np.where(np.isnan(grid[b, w]), -np.inf, grid[b, w])
            lb = np.maximum.accumulate(a, axis=0)                  # t' <= t
            lb = np.maximum.accumulate(lb[:, ::-1], axis=1)[:, ::-1]  # d' >= d
            m = np.isnan(grid[b, w])
            g[b, w][m] = np.where(np.isfinite(lb[m]), lb[m], 0.0)
    return g, n_filled


def verify(grid, n=400, seed=0):
    cells, _ = cp.load_surface()
    rng = np.random.default_rng(seed)
    bad = 0
    for _ in range(n):
        t = round(rng.uniform(T0, T1), 1)
        d = int(rng.integers(0, 139))
        b, w = int(rng.integers(0, 2)), int(rng.integers(0, 2))
        ref, _n, _r = cp.lookup(cells, t, d, b, w)
        mine = grid[b, w, int(round((t - T0) * 10)), d]
        if (ref is None) != np.isnan(mine) or (ref is not None and abs(ref - mine) > 1e-9):
            bad += 1
    return bad


def lookup(grid, t, d, back, wall):
    """Vectorised: t seconds, d feet (arrays); back/wall 0/1 arrays."""
    i = np.clip(np.rint((np.asarray(t) - T0) * 10).astype(int), 0, grid.shape[2] - 1)
    j = np.clip(np.rint(np.asarray(d)).astype(int), 0, D_MAX)
    p = grid[np.asarray(back, int), np.asarray(wall, int), i, j]
    return np.where(np.asarray(d) > D_MAX, 0.0, p)
