"""h2h_pitching_v2.py: ours with Stuff+ and with the EV channel against Steamer and ZiPS, next-season RA9, T 2022-2025.

h2h_threeway ran ours WITHOUT Stuff+. Same conventions as h2h_pitching: matched set = pitchers in our wide pool (>= 1 out in T) the
systems all projected, IP_T weight, each projection centered on the matched set's actual IP-weighted mean (ranking and spread, not
run environment). Ours is LOSO over T 2022-2026 (shipped design less the park term). Steamer has no complete 2026, so scoring ends at T 2025.
Blend weights are set by the grid in steps of .1 leaving the target season out, and fixed 50/50 is printed too.

Steamer and ZiPS project ERA (h2h_pitching's convention); centering removes the level gap to RA9.

Usage: python3 scripts/research/projection/h2h_pitching_v2.py
Output: console + data/_proj/_h2h_pitching_v2.json
"""
import itertools
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fa_class_calibration as fc
import h2h_pitching as hp
import pit_ev_addon as pe
import pit_experience_test as px
import pit_rate_backtest as pr
import pit_stuff_addon as pst

ROOT = pr.ROOT
T_ = fc.PIT_T
N0_EV = 100


def main():
    D = fc.pit_build()
    stuff = json.load(open(os.path.join(ROOT, 'data', '_era_internal_stuff.json')))
    tab, lg = pe.ev_table()
    for T in T_:
        z = D[T]
        ch, _ = pst.stuff_channel(z['rows'], T, stuff, px.PAR[0], 250)
        ev = []
        for pid, _, _ in z['rows']:
            num = den = 0.0
            for k in range(3):
                y = T - 1 - k
                r = tab[y].get(int(pid))
                if r:
                    num += px.PAR[0] ** k * r[1] * (r[0] - lg[y]); den += px.PAR[0] ** k * r[1]
            ev.append(num / (den + N0_EV) if den + N0_EV > 0 else 0.0)
        x = z['X']; exp = (1 / (1 + z['E'] / 20))[:, None]
        z['nostuff'] = np.column_stack([x[:, :-1], exp, x[:, -1]])
        z['stuff'] = np.column_stack([x[:, :-1], exp, ch, x[:, -1]])
        z['stuff_ev'] = np.column_stack([x[:, :-1], exp, ch, np.array(ev), x[:, -1]])
    preds = {a: {} for a in ('nostuff', 'stuff', 'stuff_ev')}
    for a in preds:
        for T in T_:
            tr = [s for s in T_ if s != T]
            preds[a][T], _ = pr.fit_predict(np.vstack([D[s][a] for s in tr]), np.concatenate([D[s]['y'] for s in tr]), np.concatenate([D[s]['w'] for s in tr]), D[T][a])
    rows = {}
    for T in (2022, 2023, 2024, 2025):
        st, zi = hp.fg('steamer', T), hp.fg('zips', T)
        ids = [int(r[0]) for r in D[T]['rows']]
        keep = [i for i, p in enumerate(ids) if p in st and p in zi]
        y, w = D[T]['y'][keep], D[T]['w'][keep]
        ctr = lambda v: v - np.average(v, weights=w) + np.average(y, weights=w)
        rows[T] = dict(y=y, w=w, nostuff=ctr(preds['nostuff'][T][keep]), stuff=ctr(preds['stuff'][T][keep]), stuff_ev=ctr(preds['stuff_ev'][T][keep]),
                       steamer=ctr(np.array([st[ids[i]][0] for i in keep])), zips=ctr(np.array([zi[ids[i]][0] for i in keep])))
    mse = lambda p, r: float(np.average((r['y'] - p) ** 2, weights=r['w']))
    print('matched n', {T: len(rows[T]['y']) for T in rows})
    out = {}
    for a in ('nostuff', 'stuff', 'stuff_ev', 'steamer', 'zips'):
        out[a] = [mse(rows[T][a], rows[T]) for T in rows]
        print(f'  {a:10s} mean MSE {np.mean(out[a]):.4f}  ' + ' '.join(f'{x:.3f}' for x in out[a]))
    for a, b, c in (('stuff_ev', 'steamer', None), ('stuff_ev', 'zips', None), ('stuff_ev', 'steamer', 'zips')):
        if c:
            p = {T: (rows[T][a] + rows[T][b] + rows[T][c]) / 3 for T in rows}; name = 'thirds ours/steamer/zips'
        else:
            p = {T: (rows[T][a] + rows[T][b]) / 2 for T in rows}; name = f'50/50 {a}+{b}'
        m = [mse(p[T], rows[T]) for T in rows]; out[name] = m
        print(f'  {name:30s} mean MSE {np.mean(m):.4f}  beats ours {sum(x < y for x, y in zip(m, out["stuff_ev"]))}/4, beats steamer {sum(x < y for x, y in zip(m, out["steamer"]))}/4')
    grid = [(a / 10, b / 10, (10 - a - b) / 10) for a in range(11) for b in range(11 - a)]
    held = []
    for T in rows:
        tr = [s for s in rows if s != T]
        best = min(grid, key=lambda g: np.mean([mse(g[0] * rows[s]['stuff_ev'] + g[1] * rows[s]['steamer'] + g[2] * rows[s]['zips'], rows[s]) for s in tr]))
        held.append((best, mse(best[0] * rows[T]['stuff_ev'] + best[1] * rows[T]['steamer'] + best[2] * rows[T]['zips'], rows[T])))
    print('  held-out 3-way weights (ours, steamer, zips)', [h[0] for h in held], 'mean MSE', round(np.mean([h[1] for h in held]), 4))
    with open(os.path.join(pr.P, '_h2h_pitching_v2.json'), 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
