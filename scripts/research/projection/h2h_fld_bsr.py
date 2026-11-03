"""h2h_fld_bsr.py: our fielding and baserunning projections against Steamer's, scored on what happened.

Pool: hitters with >= 100 PA in the target season T (Steamer 2018-2025) and a projection in both systems.
Predictors (each projected from seasons before T only):
  baserunning  ours: projected sprint speed (sprint_backtest pooled: d .3, N0 1 run, -.2 ft/s per year)
               times history OBP (the shipped fill relation is linear in sprint x times on base);
               Steamer: projected BaseRunning per PA
  fielding     ours: projected FRV per 1000 outs (prior -1.0, N0 2000, d .55, age term) times outs per PA
               (own history, capped at the regulars' 90th percentile); Steamer: projected Fielding per PA
Truth per PA in T: FanGraphs BaseRunning; for fielding both FanGraphs Fielding and Savant FRV.
Each predictor gets a linear calibration fitted on the OTHER seasons (so units do not matter); scored
by PA_T-weighted MSE and r, plus the two-predictor blend (OLS on both, also leaving the season out).

Usage: python3 scripts/research/projection/h2h_fld_bsr.py
"""
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fld_rate_backtest as fr

P = fr.P
YEARS = range(2018, 2026)


def jl(p):
    return json.load(open(os.path.join(P, p)))


def sprint(y):
    out = {}
    with open(os.path.join(P, f'sprint_{y}.csv'), encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            try:
                out[int(r['player_id'])] = (float(r['sprint_speed']), int(r['competitive_runs'] or 0))
            except (ValueError, KeyError):
                pass
    lg = sum(s * n for s, n in out.values() if n) / sum(n for _, n in out.values() if n)
    return out, lg


def main():
    SP = {y: sprint(y) for y in range(2015, 2026)}
    FRV = {y: jl(f'frv_{y}.json') for y in range(2015, 2026) if os.path.exists(os.path.join(P, f'frv_{y}.json'))}
    LN = {y: {r['id']: r for r in jl(f'lines_hitting_{y}.json')} for y in range(2015, 2026)}
    rows = {}
    for T in YEARS:
        act = {int(r['xMLBAMID']): r for r in jl(f'fg/actual_{T}_bat.json') if r.get('xMLBAMID') and (r.get('PA') or 0) >= 100}
        st = {int(r['xMLBAMID']): r for r in jl(f'fg/steamer_{T}_bat.json') if r.get('xMLBAMID') and (r.get('PA') or 0) > 0}
        out = []
        for pid, a in act.items():
            s = st.get(pid); L = LN[T].get(pid)
            if not s or not L:
                continue
            # ours: sprint x OBP
            sn = sd = 0.0
            for k in range(3):
                v = SP[T - 1 - k][0].get(pid)
                if v and v[1] > 0:
                    sn += 0.3 ** k * v[1] * (v[0] - SP[T - 1 - k][1]); sd += 0.3 ** k * v[1]
            ob = obd = 0.0
            for k in range(3):
                l = LN[T - 1 - k].get(pid)
                if l:
                    g = lambda c: int(l.get(c) or 0)
                    ob += g('hits') + g('baseOnBalls') + g('hitByPitch'); obd += g('atBats') + g('baseOnBalls') + g('hitByPitch') + g('sacFlies')
            spd = (sn / (sd + 1) - 0.2) if sd > 0 else None
            obp = ob / obd if obd else None
            # ours: fielding
            fn = fd = 0.0; on = od = 0.0
            for k in range(3):
                y = T - 1 - k
                f = FRV.get(y, {}).get(str(pid)); l = LN[y].get(pid)
                pa = int((l or {}).get('plateAppearances') or 0)
                if f and f.get('total') is not None:
                    o = sum(f['outs_by_pos'].values())
                    if o > 0:
                        fn += 0.55 ** k * o * 1000 * f['total'] / o; fd += 0.55 ** k * o
                        if pa:
                            on += 0.55 ** k * o; od += 0.55 ** k * pa
                elif pa:
                    od += 0.55 ** k * pa
            if fd == 0 and od == 0:
                continue
            age = L.get('age') or 28
            f1000 = (fn + 2000 * -1.0) / (fd + 2000) + (0.05 * (34 - age) if age < 34 else -0.2 * (age - 34))
            opa = min(on / od, 6.47) if od else 0.0
            f_tr = FRV.get(T, {}) if T in FRV else None
            frv_t = (FRV[T].get(str(pid)) or {}).get('total') if T in FRV else None
            out.append({'pa': a['PA'], 'bsr_t': (a.get('BaseRunning') or 0) / a['PA'], 'fld_t': (a.get('Fielding') or 0) / a['PA'],
                        'frv_t': (frv_t or 0.0) / a['PA'],
                        'bsr_o': (spd * obp) if (spd is not None and obp) else 0.0, 'bsr_s': (s.get('BaseRunning') or 0) / s['PA'],
                        'fld_o': f1000 / 1000 * opa, 'fld_s': (s.get('Fielding') or 0) / s['PA']})
        rows[T] = out
    def run(tkey, okey, skey):
        res = {'ours': [], 'steamer': [], 'blend': []}
        for T in YEARS:
            tr = [S for S in YEARS if S != T]
            for name, cols in (('ours', [okey]), ('steamer', [skey]), ('blend', [okey, skey])):
                Xtr = np.array([[r[c] for c in cols] for S in tr for r in rows[S]]); ytr = np.array([r[tkey] for S in tr for r in rows[S]])
                wtr = np.array([r['pa'] for S in tr for r in rows[S]], float)
                A = np.column_stack([np.ones(len(Xtr)), Xtr]); sw = np.sqrt(wtr)
                b, *_ = np.linalg.lstsq(A * sw[:, None], ytr * sw, rcond=None)
                Xt = np.array([[r[c] for c in cols] for r in rows[T]]); yt = np.array([r[tkey] for r in rows[T]]); wt = np.array([r['pa'] for r in rows[T]], float)
                p = np.column_stack([np.ones(len(Xt)), Xt]) @ b
                res[name].append((float(np.average((p - yt) ** 2, weights=wt)), float(np.corrcoef(p, yt)[0, 1])))
        return res
    for label, args in (('baserunning (truth FanGraphs BaseRunning)', ('bsr_t', 'bsr_o', 'bsr_s')),
                        ('fielding (truth FanGraphs Fielding)', ('fld_t', 'fld_o', 'fld_s')),
                        ('fielding (truth Savant FRV)', ('frv_t', 'fld_o', 'fld_s'))):
        r = run(*args)
        mo = np.array([x[0] for x in r['ours']]); ms = np.array([x[0] for x in r['steamer']]); mb = np.array([x[0] for x in r['blend']])
        print(f'\n== {label}: n per season {[len(rows[T]) for T in YEARS]}')
        print(f'   mean r: ours {np.mean([x[1] for x in r["ours"]]):.3f}  steamer {np.mean([x[1] for x in r["steamer"]]):.3f}  blend {np.mean([x[1] for x in r["blend"]]):.3f}')
        print(f'   ours beats steamer {int((mo < ms).sum())}/{len(mo)}; blend beats both {int(((mb < mo) & (mb < ms)).sum())}/{len(mo)}; '
              f'MSE ratio ours/steamer {mo.mean()/ms.mean():.3f}, blend/steamer {mb.mean()/ms.mean():.3f}')


if __name__ == '__main__':
    main()
