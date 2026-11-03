"""h2h_batting.py: our batting projection against Steamer and ZiPS, scored on what actually happened.

For each target season T, the matched set is every hitter in bat_experience_test's wide pool (>= 1 PA
in T, >= 1 MLB PA in T-3..T-1) that the FanGraphs system also projected (data/_proj/fg/, joined on
MLBAM id). Truth: actual Savant wOBA in T. Ours: the exper+aaa projection with the settings chosen
LEAVING T OUT (bat_experience_test held-out choice). Steamer 2018-2025, ZiPS 2020-2025.

Each system's projection is centered on the matched set's PA_T-weighted actual mean before scoring,
so the comparison is of ranking and spread, not of run environment (each system projects in its own
environment). Scores, PA_T-weighted: centered MSE, Pearson r, calibration slope (actual on projected),
and the per-bin bias by prior MLB PA. Then the blend w x ours + (1 - w) x theirs, w chosen leaving the
season out, tells whether the other system carries information ours lacks.

Usage: python3 scripts/research/projection/h2h_batting.py
Output: console + data/_proj/_h2h_batting.json
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bat_experience_test as bx

P = bx.v1.P
SYSTEMS = {'steamer': range(2018, 2026), 'zips': range(2020, 2026)}
W_GRID = [i / 10 for i in range(11)]


def fg(system, T):
    rows = json.load(open(os.path.join(P, 'fg', f'{system}_{T}_bat.json')))
    out = {}
    for r in rows:
        m = r.get('xMLBAMID')
        if m and r.get('wOBA') is not None and (r.get('PA') or 0) > 0:
            out[int(m)] = float(r['wOBA'])
    return out


def ours_by_season():
    D, Aaa, Mlb = bx.build()
    res = json.load(open(os.path.join(P, '_bat_experience_test.json')))['exper+aaa']['held']
    chosen = {h['T']: h['chosen'] for h in res}
    out = {}
    for T in bx.TARGETS:
        Z = bx.arrays(D[T], bx.bridge_beta(Aaa, Mlb, T))
        p = bx.project(Z, *chosen[T])
        ids = [r['id'] for r in D[T]]
        out[T] = {pid: (pp, y, w, E) for pid, pp, y, w, E in zip(ids, p, Z['y'], Z['w'], Z['E'])}
    return out


def wstats(p, y, w):
    p = p - np.average(p, weights=w) + np.average(y, weights=w)
    mse = float(np.average((p - y) ** 2, weights=w))
    pc, yc = p - np.average(p, weights=w), y - np.average(y, weights=w)
    r = float(np.sum(w * pc * yc) / np.sqrt(np.sum(w * pc ** 2) * np.sum(w * yc ** 2)))
    slope = float(np.sum(w * pc * yc) / np.sum(w * pc ** 2))
    return mse, r, slope, p


def main():
    ours = ours_by_season()
    out = {}
    for system, years in SYSTEMS.items():
        print(f'\n===== ours vs {system} =====')
        print(f'{"T":>5} {"n":>4} | {"MSE ours":>9} {"theirs":>9} | {"r ours":>7} {"theirs":>7} | {"slope ours":>10} {"theirs":>7}')
        per, blend_inputs = [], {}
        for T in years:
            F = fg(system, T)
            ids = [pid for pid in ours[T] if pid in F]
            o = np.array([ours[T][i][0] for i in ids]); y = np.array([ours[T][i][1] for i in ids])
            w = np.array([ours[T][i][2] for i in ids]); E = np.array([ours[T][i][3] for i in ids])
            t = np.array([F[i] for i in ids])
            mo, ro, so, oc = wstats(o, y, w); mt, rt, st, tc = wstats(t, y, w)
            per.append({'T': T, 'n': len(ids), 'mse_ours': mo, 'mse_theirs': mt, 'r_ours': ro, 'r_theirs': rt, 'slope_ours': so, 'slope_theirs': st})
            blend_inputs[T] = (oc, tc, y, w, E)
            print(f'{T:>5} {len(ids):>4} | {mo*1e4:9.3f} {mt*1e4:9.3f} | {ro:7.3f} {rt:7.3f} | {so:10.3f} {st:7.3f}')
        wins = sum(p['mse_ours'] < p['mse_theirs'] for p in per)
        print(f'ours beats {system} in {wins}/{len(per)} seasons; mean MSE ours {np.mean([p["mse_ours"] for p in per])*1e4:.3f} '
              f'{system} {np.mean([p["mse_theirs"] for p in per])*1e4:.3f}; mean r ours {np.mean([p["r_ours"] for p in per]):.3f} '
              f'{system} {np.mean([p["r_theirs"] for p in per]):.3f}')
        # bias by prior MLB PA (centered projections), pooled over seasons
        print('  bias (actual - projected, wOBA points x1000) by prior MLB PA:')
        for lo, hi in bx.BINS:
            bo, bt, ww = [], [], []
            for T, (oc, tc, y, w, E) in blend_inputs.items():
                m = (E >= lo) & (E < hi)
                bo.append(np.sum(w[m] * (y[m] - oc[m]))); bt.append(np.sum(w[m] * (y[m] - tc[m]))); ww.append(np.sum(w[m]))
            print(f'    {lo}-{hi if hi < 10**6 else "+"}: ours {1000*sum(bo)/sum(ww):+5.1f}   {system} {1000*sum(bt)/sum(ww):+5.1f}')
        # blend, w chosen leaving the season out
        L = {T: [float(np.average(((wb * oc + (1 - wb) * tc) - y) ** 2, weights=w)) for wb in W_GRID]
             for T, (oc, tc, y, w, E) in blend_inputs.items()}
        held = []
        for T in L:
            others = np.mean([L[S] for S in L if S != T], axis=0)
            b = int(np.argmin(others)); held.append((T, W_GRID[b], L[T][b]))
        pooled = np.mean(list(L.values()), axis=0)
        print('  blend curve (weight on OURS: mean MSE x1e4): ' + '  '.join(f'{wb}:{v*1e4:.3f}' for wb, v in zip(W_GRID, pooled)))
        bw = sum(l < min(p['mse_ours'], p['mse_theirs']) for (T, wb, l), p in zip(held, per))
        print(f'  held-out blend beats BOTH systems in {bw}/{len(held)} seasons; chosen weights {[h[1] for h in held]}')
        out[system] = {'per': per, 'blend_curve': dict(zip(map(str, W_GRID), pooled.tolist())), 'blend_held': held}
    tmp = os.path.join(P, '_h2h_batting.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(out, f, indent=1, default=float)
    os.replace(tmp, os.path.join(P, '_h2h_batting.json'))


if __name__ == '__main__':
    main()
