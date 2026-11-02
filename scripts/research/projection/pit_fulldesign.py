"""pit_fulldesign.py: the shipped pitcher projection design, with the 2026 Stuff+ repair and the EV channel as arms.

Copies project_players.py's pitcher path (features, Stuff+ N0 250, experience k 20, history and target park, age offset). Steps:
 1. GATE: the shipped arm (fix_ev), fit on every base, must reproduce projections_pitchers.csv RA9_SP_2027 / RA9_RP_2027. Stops if not.
 2. LOSO backtest, T 2022-2026, IP_T weighted MSE on RA9 and FIP: base vs +EV (N0 100). Plus T 2020-2026 without Stuff+, because
    T 2020-2021 were not used to choose EV. (The park history needs lines from 2017, so 2020 is the first such target.)
 3. 2027 levels for every pitcher: ship, fix (adds 2026 Stuff+ from data/_proj/stuff_2026_loso.json), fix+EV.
The repair cannot be backtested as a separate arm: every backtest target already had its latest season of Stuff+. That is the point:
the repair restores what the backtests measured. Reads no file in data/ other than inputs.

Usage: python3 scripts/research/projection/pit_fulldesign.py
Output: console + data/_proj/_pit_fulldesign.json, data/_proj/_pit_fulldesign_2027.csv
"""
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pit_ev_addon as pe
import pit_horizon_backtest as ph
import pit_rate_backtest as pr
import pit_stuff_addon as pst

ROOT = pr.ROOT
P = pr.P
BASE = 2026
PIT_EXP_K = 20
N0_EV = 100


def main():
    S = {y: pr.season(y) for y in range(2015, BASE + 1)}
    stuff = json.load(open(os.path.join(ROOT, 'data', '_era_internal_stuff.json')))
    stuff_fix = dict(stuff); stuff_fix['2026'] = json.load(open(os.path.join(P, 'stuff_2026_loso.json')))
    phb = json.load(open(os.path.join(P, '_pit_horizon_backtest.json')))
    H1 = phb['1']['pooled']
    par = (H1['d'], H1['n0'], H1['peak'], H1['yi'], H1['od'])
    meta = json.load(open(os.path.join(ROOT, 'data', 'metadata_rs.json')))
    lg_ra9 = meta['eraPlusConstants']['war']['lgRA9']
    pl = {y: json.load(open(os.path.join(P, f'lines_pitching_{y}.json'))) for y in range(2017, BASE + 1)}
    club = {y: {r['id']: r.get('team') for r in pl[y]} for y in pl}
    lgr = {y: 27 * sum(int(r.get('runs') or 0) for r in pl[y]) / sum(int(r.get('outs') or 0) for r in pl[y]) for y in pl}
    PF = json.load(open(os.path.join(P, 'park_factors_hist.json')))
    tab, lg = pe.ev_table()

    def peff(y, team):
        pf = PF.get(str(y), {}).get(str(team))
        return 0.0 if pf is None else ((pf / 100 + 1) / 2 - 1) * lgr[y]

    def rows_all(B):
        T = B + 1
        return [(pid, t, [S[B - k].get(pid) for k in range(3)]) for pid, t in S[T].items() if any(S[B - k].get(pid) for k in range(3))]

    def x_exp(rows):
        return np.array([1 / (1 + sum(h['bf'] for h in hist if h) / PIT_EXP_K) for _, _, hist in rows])

    def x_park(rows, B, target_park):
        out = []
        for pid, _, hist in rows:
            num = den = 0.0
            for k, h in enumerate(hist):
                if h:
                    num += par[0] ** k * h['bf'] * peff(B - k, club[B - k].get(pid)); den += par[0] ** k * h['bf']
            out.append((num / den if den else 0.0, peff(B + 1, club[B + 1].get(pid)) if target_park else 0.0))
        return np.array(out)

    def x_ev(rows, B):
        out = []
        for pid, _, _ in rows:
            num = den = 0.0
            for k in range(3):
                r = tab[B - k].get(int(pid))
                if r:
                    num += par[0] ** k * r[1] * (r[0] - lg[B - k]); den += par[0] ** k * r[1]
            out.append(num / (den + N0_EV) if den + N0_EV > 0 else 0.0)
        return np.array(out)

    def design(rows, B, st, use_stuff, use_ev, target_park=True):
        X = ph.feats(rows, 1, *par)[0]
        cols = [X[:, :-1]]
        if use_stuff:
            cols.append(pst.stuff_channel(rows, B + 1, st, H1['d'], 250)[0])
        cols.append(x_exp(rows)); cols.append(x_park(rows, B, target_park))
        if use_ev:
            cols.append(x_ev(rows, B))
        cols.append(X[:, -1])
        return np.column_stack(cols)

    # ---- fit on every shipped base
    bases = [B for B in ph.HORIZONS[1] if B + 1 >= 2022]
    R1 = {B: rows_all(B) for B in bases}
    FT = {B: ph.feats(R1[B], 1, *par) for B in bases}
    ytr = np.concatenate([FT[B][1] for B in bases]); wtr = np.concatenate([FT[B][2] for B in bases])
    Xtr = {ev: np.vstack([design(R1[B], B, stuff, True, ev) for B in bases]) for ev in (False, True)}

    pids = set().union(*[set(S[y]) for y in range(BASE - 2, BASE + 1)])
    pids = sorted(pids)
    levels = {}
    for role, gs in (('SP', 1.0), ('RP', 0.0)):
        fake = []
        for pid in pids:
            hist = [S[BASE - k].get(pid) for k in range(3)]
            k0 = next(k for k, x in enumerate(hist) if x)
            fake.append((pid, {'age': hist[k0]['age'] + k0 + 1, 'gs': gs, 'ra9': 0.0, 'fip': 0.0, 'ip': 1.0}, hist))
        for name, st, ev in (('ship', stuff, False), ('fix', stuff_fix, False), ('fix_ev', stuff_fix, True)):
            d = design(fake, BASE, st, True, ev, target_park=False)
            lvl, beta = pr.fit_predict(Xtr[ev], ytr, wtr, d)
            levels[(role, name)] = lg_ra9 + lvl
            if role == 'SP':
                print(f'  {name} betas', np.round(beta, 3).tolist())

    # ---- 1. reproduce shipped. Since 2026-11-02 the repair and EV ARE shipped, so the arm to match is fix_ev.
    # (Before that ship this gate passed on arm 'ship', max diff .000 on 1,180 rows in both roles.)
    ship = {}
    with open(os.path.join(P, 'projections_pitchers.csv')) as f:
        for r in csv.DictReader(f):
            ship[int(r['mlbId'])] = r
    for role in ('SP', 'RP'):
        d = [abs(round(float(levels[(role, 'fix_ev')][i]), 2) - float(ship[p][f'RA9_{role}_2027'])) for i, p in enumerate(pids) if p in ship]
        print(f'GATE {role}: n {len(d)} max |diff| {max(d):.3f}, rows off by > .01: {sum(x > .0101 for x in d)}')
        if max(d) > 0.0101:
            raise SystemExit('does not reproduce projections_pitchers.csv: stop')

    # ---- 2. backtest
    res = {}

    def loso(Ts, use_stuff, use_ev, ykey):
        L = []
        B_of = lambda T: T - 1
        Rr = {T: rows_all(B_of(T)) for T in Ts}
        Xs = {T: design(Rr[T], B_of(T), stuff, use_stuff, use_ev) for T in Ts}
        Ys = {T: np.array([r[1][ykey] for r in Rr[T]]) for T in Ts}; Ws = {T: np.array([r[1]['ip'] for r in Rr[T]]) for T in Ts}
        for T in Ts:
            tr = [s for s in Ts if s != T]
            p, _ = pr.fit_predict(np.vstack([Xs[s] for s in tr]), np.concatenate([Ys[s] for s in tr]), np.concatenate([Ws[s] for s in tr]), Xs[T])
            L.append(pr.wmse(p, Ys[T], Ws[T]))
        return np.array(L)

    for lab, Ts, us in (('with Stuff+, T 2022-2026', list(range(2022, 2027)), True), ('no Stuff+, T 2020-2026', list(range(2020, 2027)), False)):
        for ykey in ('ra9', 'fip'):
            b = loso(Ts, us, False, ykey); e = loso(Ts, us, True, ykey); g = 100 * (1 - e / b)
            print(f'{lab} {ykey}: base {np.round(b,3).tolist()} +EV gain {g.mean():+.3f}% se {g.std(ddof=1)/np.sqrt(len(g)):.3f} wins {(g>0).sum()}/{len(g)} {np.round(g,2).tolist()}')
            res[f'{lab}|{ykey}'] = g.tolist()

    # ---- 3. 2027 levels
    path = os.path.join(P, '_pit_fulldesign_2027.csv')
    with open(path + '.tmp', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['mlbId', 'RA9_SP_ship', 'RA9_SP_fix', 'RA9_SP_fix_ev', 'RA9_RP_ship', 'RA9_RP_fix', 'RA9_RP_fix_ev'])
        for i, p in enumerate(pids):
            w.writerow([p] + [round(float(levels[(r, n)][i]), 4) for r in ('SP', 'RP') for n in ('ship', 'fix', 'fix_ev')])
    os.replace(path + '.tmp', path)
    for a, b in (('ship', 'fix'), ('fix', 'fix_ev')):
        d = levels[('SP', b)] - levels[('SP', a)]
        ip26 = np.array([(S[BASE][p]['ip'] if p in S[BASE] else 0) for p in pids])
        m = ip26 >= 50
        print(f'{a} -> {b}: 50+ IP n {int(m.sum())} SD {d[m].std():.3f} mean {d[m].mean():+.3f} max |d| {np.abs(d[m]).max():.3f}')
        o = np.argsort(-np.abs(d * m))[:6]
        print('   largest:', [(pids[i], round(float(d[i]), 3)) for i in o])
    with open(os.path.join(P, '_pit_fulldesign.json'), 'w') as f:
        json.dump(res, f, indent=1)


if __name__ == '__main__':
    main()
