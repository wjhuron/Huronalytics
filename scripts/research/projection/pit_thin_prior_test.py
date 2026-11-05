"""pit_thin_prior_test.py: does the pitcher level over-project arms with a thin or failing recent record?

Why (2026-11-03): Joey Estes (7.1 IP, 11.05 ERA; 6.50 in 274 Triple-A outs) projected 4.65 RA9 and 2.39 WAR per 180 IP, and Jason
Alexander (18.1 IP, 9.33 ERA; 5.26 in Triple-A) 4.89 and 1.90. Both are SP180 because they started half of a few games.

Pool, design and objective are project_players.py's (pit_fulldesign.py): every pitcher with >= 1 out in T and history in T-3..T-1,
IP_T-weighted MSE of RA9, leave one target season out, T 2022-2026. Two readings of the shipped model:
  actual role   gs_T is the target season's start share (what the backtests score). It knows who kept a rotation job.
  stated role   gs is set the way production sets it: 1 if his base-season share >= .5, else 0.
Candidate terms, added to the fit, kept only if they beat the shipped design held out:
  gsBase    train on the base season's start share in place of gs_T
  aaa       Triple-A FIP and K-BB deltas in T-1 or T-2, shrunk at n, plus a has-Triple-A flag (n swept)
  aaaRA     the same with Triple-A runs per 9
  recent    1 / (1 + BF_(T-1) / k), a thin latest MLB season (k swept)
  aaa+recent

Usage: python3 scripts/research/projection/pit_thin_prior_test.py
Output: console + data/_proj/_pit_thin_prior_test.json
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aaa_pitcher_bridge as apb
import pit_ev_addon as pe
import pit_horizon_backtest as ph
import pit_rate_backtest as pr
import pit_stuff_addon as pst

ROOT = pr.ROOT
P = pr.P
TS = list(range(2022, 2027))
PIT_EXP_K = 20
N0_EV = 100
GRID_N = [50, 100, 200, 400, 800, 1600, 3200]
GRID_K = [5, 10, 20, 40, 80, 160, 320, 640]
N_BOOT = 2000


class Base:
    def __init__(self):
        self.S = {y: pr.season(y) for y in range(2015, 2027)}
        self.stuff = json.load(open(os.path.join(ROOT, 'data', '_era_internal_stuff.json')))
        H1 = json.load(open(os.path.join(P, '_pit_horizon_backtest.json')))['1']['pooled']
        self.H1 = H1; self.par = (H1['d'], H1['n0'], H1['peak'], H1['yi'], H1['od'])
        pl = {y: json.load(open(os.path.join(P, f'lines_pitching_{y}.json'))) for y in range(2017, 2027)}
        self.club = {y: {r['id']: r.get('team') for r in pl[y]} for y in pl}
        self.lgr = {y: 27 * sum(int(r.get('runs') or 0) for r in pl[y]) / sum(int(r.get('outs') or 0) for r in pl[y]) for y in pl}
        self.PF = json.load(open(os.path.join(P, 'park_factors_hist.json')))
        self.tab, self.lg = pe.ev_table()
        self.A, _ = apb.tables()

    def peff(self, y, team):
        pf = self.PF.get(str(y), {}).get(str(team))
        return 0.0 if pf is None else ((pf / 100 + 1) / 2 - 1) * self.lgr[y]

    def rows(self, T):
        B = T - 1
        return [(pid, t, [self.S[B - k].get(pid) for k in range(3)]) for pid, t in self.S[T].items() if any(self.S[B - k].get(pid) for k in range(3))]

    def design(self, rows, T, gs_mode='actual', use_stuff=True, stuff=None):
        B = T - 1; d = self.par[0]
        X = ph.feats(rows, 1, *self.par)[0]
        if gs_mode != 'actual':
            base = np.array([h[0]['gs'] if h[0] else (next(x for x in h if x)['gs']) for _, _, h in rows])
            X[:, -2] = (base >= 0.5).astype(float) if gs_mode == 'stated' else base
        stuffc = pst.stuff_channel(rows, T, stuff or self.stuff, self.H1['d'], 250)[0] if use_stuff else np.zeros((len(rows), 0))
        xe = np.array([1 / (1 + sum(h['bf'] for h in hist if h) / PIT_EXP_K) for _, _, hist in rows])
        pk, ev = [], []
        for pid, _, hist in rows:
            num = den = 0.0
            for k, h in enumerate(hist):
                if h:
                    num += d ** k * h['bf'] * self.peff(B - k, self.club[B - k].get(pid)); den += d ** k * h['bf']
            pk.append((num / den if den else 0.0, self.peff(T, self.club.get(T, {}).get(pid))))
            n2 = d2 = 0.0
            for k in range(3):
                r = self.tab[B - k].get(int(pid))
                if r:
                    n2 += d ** k * r[1] * (r[0] - self.lg[B - k]); d2 += d ** k * r[1]
            ev.append(n2 / (d2 + N0_EV) if d2 + N0_EV > 0 else 0.0)
        return np.column_stack([X[:, :-1], stuffc, xe, np.array(pk), np.array(ev), X[:, -1]])

    def aaa(self, pid, T):
        for y in (T - 1, T - 2):
            a = self.A.get(y, {}).get(pid)
            if a:
                return a
        return None


def add(X, extra):
    return np.column_stack([X[:, :-1], extra, X[:, -1]]) if extra is not None and extra.size else X


def loso(D, extras=None, score=None):
    """score: optional per-T design to predict from (the stated-role reading)."""
    pred, betas = {}, {}
    for T in TS:
        tr = [s for s in TS if s != T]
        Xt = np.vstack([add(D[s]['X'], extras[s] if extras else None) for s in tr])
        Xp = add((score or {}).get(T, D[T]['X']), extras[T] if extras else None)
        pred[T], betas[T] = pr.fit_predict(Xt, np.concatenate([D[s]['y'] for s in tr]), np.concatenate([D[s]['w'] for s in tr]), Xp)
    return pred, betas


def mse(p, D, T, m=None):
    z = D[T]; m = np.ones(len(p), bool) if m is None else m
    return float((z['w'][m] * (p[m] - z['y'][m]) ** 2).sum() / z['w'][m].sum())


def report(name, pred, P0, D, res):
    d = [mse(pred[T], D, T) - mse(P0[T], D, T) for T in TS]
    rng = np.random.default_rng(0); B = []
    for _ in range(N_BOOT):
        b = []
        for T in TS:
            z = D[T]; i = rng.integers(0, len(z['y']), len(z['y']))
            b.append((z['w'][i] * ((pred[T][i] - z['y'][i]) ** 2 - (P0[T][i] - z['y'][i]) ** 2)).sum() / z['w'][i].sum())
        B.append(np.mean(b))
    base = np.mean([mse(P0[T], D, T) for T in TS])
    sl = {}
    for lab, key in (('thin base', 'thinB'), ('reg base', 'regB')):
        v = [mse(pred[T], D, T, D[T][key]) - mse(P0[T], D, T, D[T][key]) for T in TS]
        sl[lab] = (float(np.mean(v)), int(sum(x < 0 for x in v)))
    print(f'{name:22s} dMSE {np.mean(d):+.4f} (se {np.std(B):.4f}, {100*np.mean(d)/base:+.2f}%)  wins {sum(x < 0 for x in d)}/5  per T ' + ' '.join(f'{x:+.3f}' for x in d) +
          f'   thin base IP<30: {sl["thin base"][0]:+.3f} ({sl["thin base"][1]}/5)  base IP>=30: {sl["reg base"][0]:+.3f} ({sl["reg base"][1]}/5)')
    res[name] = dict(d=d, se=float(np.std(B)), base=float(base), slices=sl)


def calib(pred, D, lab):
    print(f'\n  calibration, actual - projected RA9, {lab}')
    c = {k: np.concatenate([D[T][k] for T in TS]) for k in ('y', 'w', 'ipB', 'gsB', 'bad', 'hasA', 'age', 'E')}
    p = np.concatenate([pred[T] for T in TS])
    for name, m in (('base IP<30, base gs>=.5', (c['ipB'] < 30) & (c['gsB'] >= .5)), ('base IP<30, base gs<.5', (c['ipB'] < 30) & (c['gsB'] < .5)),
                    ('base IP 30-80, gs>=.5', (c['ipB'] >= 30) & (c['ipB'] < 80) & (c['gsB'] >= .5)), ('base IP 30-80, gs<.5', (c['ipB'] >= 30) & (c['ipB'] < 80) & (c['gsB'] < .5)),
                    ('base IP>=80', c['ipB'] >= 80),
                    ('base IP<30, Triple-A FIP worse than lg', (c['ipB'] < 30) & (c['bad'] == 1)), ('base IP<30, Triple-A FIP better', (c['ipB'] < 30) & (c['hasA'] == 1) & (c['bad'] == 0)),
                    ('base IP<30, gs>=.5, Triple-A worse', (c['ipB'] < 30) & (c['gsB'] >= .5) & (c['bad'] == 1)),
                    ('base IP<30, age>=30', (c['ipB'] < 30) & (c['age'] >= 30)), ('base IP<30, E>=300', (c['ipB'] < 30) & (c['E'] >= 300))):
        if m.sum() < 3:
            continue
        r = c['y'][m] - p[m]; w = c['w'][m]
        rng = np.random.default_rng(0); n = len(r)
        se = np.std([np.average(r[i], weights=w[i]) for i in (rng.integers(0, n, n) for _ in range(1000))])
        print(f'    {name:40s} n {int(m.sum()):4d} IP {w.sum():7.0f}  {np.average(r, weights=w):+.2f} (se {se:.2f})  mean proj {np.average(p[m], weights=w):+.2f}')


def main():
    B = Base()
    D = {}
    for T in TS:
        R = B.rows(T)
        X = B.design(R, T)
        y = ph.feats(R, 1, *B.par)[1]; w = ph.feats(R, 1, *B.par)[2]
        ipB = np.array([h[0]['ip'] if h[0] else 0.0 for _, _, h in R]); bfB = np.array([h[0]['bf'] if h[0] else 0.0 for _, _, h in R])
        gsB = np.array([h[0]['gs'] if h[0] else (next(x for x in h if x)['gs']) for _, _, h in R])
        A_ = [B.aaa(pid, T) for pid, _, _ in R]
        D[T] = dict(R=R, X=X, y=y, w=w, ipB=ipB, bfB=bfB, gsB=gsB, A=A_, Xstated=B.design(R, T, 'stated'), Xbase=B.design(R, T, 'base'),
                    hasA=np.array([1.0 if a else 0.0 for a in A_]), bad=np.array([1.0 if a and a['d_fip'] > 0 else 0.0 for a in A_]),
                    age=np.array([t['age'] for _, t, _ in R], float), E=np.array([sum(h['bf'] for h in hist if h) for _, _, hist in R], float),
                    thinB=ipB < 30, regB=ipB >= 30)
    print('pool', {T: len(D[T]['y']) for T in TS})
    res = {}
    P0, _ = loso(D)
    print('shipped design, held-out mean MSE', round(np.mean([mse(P0[T], D, T) for T in TS]), 4))
    calib(P0, D, 'SHIPPED, actual role')
    Pst, _ = loso(D, score={T: D[T]['Xstated'] for T in TS})
    print('\nstated-role reading of the shipped fit: MSE', round(np.mean([mse(Pst[T], D, T) for T in TS]), 4))
    calib(Pst, D, 'SHIPPED, stated role (what production prints)')
    print()
    Db = {T: dict(D[T], X=D[T]['Xbase']) for T in TS}
    Pb, _ = loso(Db)
    report('gsBase vs actual role', Pb, P0, D, res)
    report('gsBase vs stated role', Pb, Pst, D, res)

    def ex_aaa(n, kind):
        out = {}
        for T in TS:
            rows = []
            for a in D[T]['A']:
                if not a:
                    rows.append((0.0, 0.0, 0.0)); continue
                sh = a['bf'] / (a['bf'] + n)
                rows.append((1.0, a[kind] * sh, a['d_kbb'] * sh))
            out[T] = np.array(rows)
        return out

    def ex_recent(k):
        return {T: (1 / (1 + D[T]['bfB'] / k))[:, None] for T in TS}

    print('\n  sweep, held-out MSE minus shipped')
    for kind in ('d_fip',):
        cur = {}
        for n in GRID_N:
            pr_, _ = loso(D, ex_aaa(n, kind)); cur[n] = np.mean([mse(pr_[T], D, T) - mse(P0[T], D, T) for T in TS])
        print(f'    aaa {kind} n: ' + '  '.join(f'{n}:{v:+.4f}' for n, v in cur.items()))
        best_n = min(cur, key=cur.get)
        pr_, bt = loso(D, ex_aaa(best_n, kind)); report(f'aaa n{best_n}', pr_, P0, D, res)
        print('      betas [has, fip, kbb] per T', [np.round(bt[T][-4:-1], 3).tolist() if False else None for T in []])
        res['aaa_curve'] = {str(k): float(v) for k, v in cur.items()}
    cur = {}
    for k in GRID_K:
        pr_, _ = loso(D, ex_recent(k)); cur[k] = np.mean([mse(pr_[T], D, T) - mse(P0[T], D, T) for T in TS])
    print('    recent k: ' + '  '.join(f'{k}:{v:+.4f}' for k, v in cur.items()))
    best_k = min(cur, key=cur.get)
    pr_, _ = loso(D, ex_recent(best_k)); report(f'recent k{best_k}', pr_, P0, D, res)
    res['recent_curve'] = {str(k): float(v) for k, v in cur.items()}
    a = ex_aaa(best_n, 'd_fip'); r = ex_recent(best_k)
    both = {T: np.column_stack([a[T], r[T]]) for T in TS}
    prb, _ = loso(D, both); report('aaa+recent', prb, P0, D, res)
    calib(prb, D, 'aaa+recent, actual role')
    # the two players at 2027 are read in a separate step, from the shipped path
    tmp = os.path.join(P, '_pit_thin_prior_test.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(res, f, indent=1, default=float)
    os.replace(tmp, os.path.join(P, '_pit_thin_prior_test.json'))


if __name__ == '__main__':
    main()
