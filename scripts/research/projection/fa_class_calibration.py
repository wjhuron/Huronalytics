"""fa_class_calibration.py: are the rate projections biased on players who reached free agency?

Free agents are not a random draw: they are older and their old club chose to let them go. A projection
that is calibrated on all players can still be biased on the group a free-agent rundown reads. This reads
that gap directly, on held-out projections of the wide (honest) pools:

    hitters   bat_experience_test exper+aaa held-out projection of wOBA vs league, T 2021-2026, PA_T weight
    pitchers  pit_rate_backtest features + experience term (k 20) + Stuff+ history channel (N0_S 250), no park
              term (project_players adds one; movers are not systematic here), LOSO over T
              2022-2026 (Stuff+ history starts 2021), IP_T weight, target RA9

FA class = the row in data/_fa_contracts/dataset.csv with Y == T, matched by MLBAM id. Residual = actual minus
projected. Positive = the player beat the projection (for pitchers, positive = allowed MORE runs).

Read: weighted mean residual FA minus non-FA, raw and with age-bin + experience-bin controls (WLS within T),
per season, plus a bootstrap of players within season. Split by deal type (MLB deal / other) and age.

Usage: python3 scripts/research/projection/fa_class_calibration.py
Output: console + data/_proj/_fa_class_calibration.json
"""
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bat_experience_test as bx
import pit_experience_test as px
import pit_rate_backtest as pr
import pit_stuff_addon as pst
import aaa_pitcher_bridge as apb

ROOT = pr.ROOT
BAT_T = list(range(2021, 2027))
PIT_T = list(range(2022, 2027))
N_BOOT = 2000


def fa_rows():
    out = {}
    with open(os.path.join(ROOT, 'data', '_fa_contracts', 'dataset.csv')) as f:
        for r in csv.DictReader(f):
            if not r.get('mlbam'):
                continue
            out[(int(r['Y']), int(float(r['mlbam'])))] = r
    return out


def controlled(resid, fa, age, E, w, T):
    """WLS coefficient on the FA flag with T x age-bin and experience-bin dummies."""
    agebin = np.digitize(age, [25, 28, 31, 34])
    ebin = np.digitize(E, np.percentile(E, [25, 50, 75]))
    cols = [fa.astype(float)]
    for t in np.unique(T):
        cols.append((T == t).astype(float))
    for a in np.unique(agebin)[1:]:
        cols.append((agebin == a).astype(float))
    for e in np.unique(ebin)[1:]:
        cols.append((ebin == e).astype(float))
    X = np.column_stack(cols)
    sw = np.sqrt(w)
    return float(np.linalg.lstsq(X * sw[:, None], resid * sw, rcond=None)[0][0])


def report(name, resid, fa, age, E, w, T, unit, sub=None):
    m = np.ones(len(resid), bool) if sub is None else sub
    resid, fa2, age, E, w, T = resid[m], fa[m], age[m], E[m], w[m], T[m]
    rng = np.random.default_rng(0)
    raw = float(np.average(resid[fa2], weights=w[fa2]) - np.average(resid[~fa2], weights=w[~fa2]))
    ctl = controlled(resid, fa2, age, E, w, T)
    boots_raw, boots_ctl = [], []
    idx_by_t = {t: np.where(T == t)[0] for t in np.unique(T)}
    for _ in range(N_BOOT):
        ix = np.concatenate([rng.choice(v, len(v)) for v in idx_by_t.values()])
        f, r_, w_ = fa2[ix], resid[ix], w[ix]
        boots_raw.append(np.average(r_[f], weights=w_[f]) - np.average(r_[~f], weights=w_[~f]))
    for _ in range(300):
        ix = np.concatenate([rng.choice(v, len(v)) for v in idx_by_t.values()])
        boots_ctl.append(controlled(resid[ix], fa2[ix], age[ix], E[ix], w[ix], T[ix]))
    per = []
    for t in np.unique(T):
        s = T == t
        if fa2[s].sum():
            per.append(float(np.average(resid[s & fa2], weights=w[s & fa2]) - np.average(resid[s & ~fa2], weights=w[s & ~fa2])))
    print(f'  {name:34s} n FA {int(fa2.sum()):4d}  raw {raw:+.4f} (se {np.std(boots_raw):.4f})  '
          f'controlled {ctl:+.4f} (se {np.std(boots_ctl):.4f})  per T {" ".join(f"{p:+.3f}" for p in per)}  [{unit}]')
    return dict(n_fa=int(fa2.sum()), raw=raw, raw_se=float(np.std(boots_raw)), controlled=ctl,
                controlled_se=float(np.std(boots_ctl)), per_T=per)


def hitters(FA):
    D, Aaa, Mlb = bx.build()
    held = {h['T']: h['chosen'] for h in json.load(open(os.path.join(bx.v1.P, '_bat_experience_test.json')))['exper+aaa']['held']}
    A = dict(resid=[], fa=[], age=[], E=[], w=[], T=[], mlb=[], id=[])
    for T in BAT_T:
        Z = bx.arrays(D[T], bx.bridge_beta(Aaa, Mlb, T))
        p = bx.project(Z, *held[T])
        for i, r in enumerate(D[T]):
            f = FA.get((T, int(r['id'])))
            A['resid'].append(Z['y'][i] - p[i]); A['fa'].append(f is not None); A['age'].append(r['age']); A['E'].append(r['E'])
            A['w'].append(Z['w'][i]); A['T'].append(T); A['mlb'].append(bool(f and f.get('outcome') == 'mlb')); A['id'].append(int(r['id']))
    return {k: np.array(v) for k, v in A.items()}


def pit_build():
    S = {y: pr.season(y) for y in range(2015, 2027)}
    A, _ = apb.tables()
    D = {}
    for T in PIT_T:
        rows, extra = [], []
        for pid, t in S[T].items():
            hist = [S[T - 1 - k].get(pid) for k in range(3)]
            if not any(hist):
                continue
            E = sum(h['bf'] for h in hist if h)
            aa = next((A[y][pid] for y in (T - 1, T - 2) if y in A and pid in A[y]), None)
            rows.append((pid, t, hist))
            sh = aa['bf'] / (aa['bf'] + 400) if aa else 0.0
            extra.append((E, aa['d_fip'] * sh if aa else 0.0, aa['d_kbb'] * sh if aa else 0.0, 1.0 if aa else 0.0))
        X, yra, _, w = pr.features(rows, *px.PAR)
        D[T] = {'X': X, 'y': yra, 'w': w, 'E': np.array([e[0] for e in extra], float),
                'A': np.array([e[1:] for e in extra], float), 'rows': rows}
    return D


def pitchers(FA):
    D = pit_build()
    stuff = json.load(open(os.path.join(ROOT, 'data', '_era_internal_stuff.json')))
    k = 20   # PIT_EXP_K in project_players.py; the Triple-A terms were not adopted there
    for T in PIT_T:
        ch, _ = pst.stuff_channel(D[T]['rows'], T, stuff, px.PAR[0], 250)
        z = D[T]
        z['F'] = np.column_stack([z['X'][:, :-1], (1 / (1 + z['E'] / k))[:, None], ch, z['X'][:, -1]])
    A = dict(resid=[], fa=[], age=[], E=[], w=[], T=[], mlb=[], id=[])
    for T in PIT_T:
        tr = [S for S in PIT_T if S != T]
        p, _ = pr.fit_predict(np.vstack([D[S]['F'] for S in tr]), np.concatenate([D[S]['y'] for S in tr]),
                              np.concatenate([D[S]['w'] for S in tr]), D[T]['F'])
        z = D[T]
        for i, (pid, t, _) in enumerate(z['rows']):
            f = FA.get((T, int(pid)))
            A['resid'].append(z['y'][i] - p[i]); A['fa'].append(f is not None); A['age'].append(t['age']); A['E'].append(z['E'][i])
            A['w'].append(z['w'][i]); A['T'].append(T); A['mlb'].append(bool(f and f.get('outcome') == 'mlb')); A['id'].append(int(pid))
    return {k_: np.array(v) for k_, v in A.items()}


def block(name, A, unit):
    print(f'\n== {name}: rows {len(A["w"])}, FA rows {int(A["fa"].sum())}, FA share of weight {A["w"][A["fa"]].sum() / A["w"].sum():.3f}')
    print(f'  overall weighted mean residual {np.average(A["resid"], weights=A["w"]):+.4f}  mean age FA {np.average(A["age"][A["fa"]], weights=A["w"][A["fa"]]):.1f} non-FA {np.average(A["age"][~A["fa"]], weights=A["w"][~A["fa"]]):.1f}')
    out = {}
    out['all'] = report('all FA vs rest', A['resid'], A['fa'], A['age'], A['E'], A['w'], A['T'], unit)
    mlb = A['fa'] & A['mlb']
    out['mlb_deal'] = report('FA with MLB deal vs rest', A['resid'], mlb, A['age'], A['E'], A['w'], A['T'], unit, sub=(~A['fa']) | mlb)
    oth = A['fa'] & ~A['mlb']
    out['other_deal'] = report('FA with other deal vs rest', A['resid'], oth, A['age'], A['E'], A['w'], A['T'], unit, sub=(~A['fa']) | oth)
    for lab, lo, hi in (('age <= 30', 0, 30.5), ('age 31-33', 30.5, 33.5), ('age 34+', 33.5, 99)):
        out[lab] = report(lab, A['resid'], A['fa'], A['age'], A['E'], A['w'], A['T'], unit, sub=(A['age'] >= lo) & (A['age'] < hi))
    return out


def main():
    FA = fa_rows()
    print('FA rows by Y:', {y: sum(1 for k in FA if k[0] == y) for y in sorted({k[0] for k in FA})})
    res = {}
    res['hitters'] = block('HITTERS, wOBA vs league', hitters(FA), 'wOBA')
    res['pitchers'] = block('PITCHERS, RA9', pitchers(FA), 'runs/9')
    tmp = os.path.join(pr.P, '_fa_class_calibration.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(res, f, indent=1)
    os.replace(tmp, os.path.join(pr.P, '_fa_class_calibration.json'))


if __name__ == '__main__':
    main()
