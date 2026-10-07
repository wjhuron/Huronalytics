"""project_players.py: assemble the 2027 / 2029 / 2031 projections (1, 3 and 5 seasons out) from the
measured backtest settings. Research output, not a site metric.

HITTERS, WAR per 600 PA (rate, per Wally 2026-10-02):
  batting   wOBA delta, ONE level setting for every horizon (a .75, d .70, N0 450) with the measured
            aging (+.002 / -.0045 per year, peak 30 at 1 and 3 seasons out, 29 at 5): per-horizon
            optima made the chains incoherent (Judge rose from 2029 to 2031); the shared setting costs
            0 / .19 / .46 percent of held-out MSE against each horizon's own optimum. History park removed at m .375 x the blend pass (bat_park_test.py, 8/9).
            Two versions: NEUTRAL park, and WSH (the Nationals Park effect added back at m .375).
            runs/600 = delta / wOBAscale x 600 (2026 Guts)
  baserun.  projected sprint (sprint_backtest pooled: d .3, N0 1 run, -.2 ft/s per year relative to
            league) through the shipped hWAR fill relation: k x (a + b x sprint) x times on base per
            600 PA (metadata hwarConstants.bsrFill). Times on base from OBP history weighted like the
            batting and shrunk at the batting N0 (BORROWED constant, labeled). No sprint -> 0.
  fielding  FRV per 1000 outs (fld_rate_backtest pooled) x outs per PA (his own, weighted) x 600.
            Measured at 1 season out only; the 3/5-year rows reuse it with the target age.
  position  his 2026 shipped hPosRuns per PA x 600 (the shipped positional table on his 2026 innings
            mix); a hitter without a 2026 MLB row gets 0 and is flagged. Position drift with age: none.
  replace.  metadata hwarConstants.replPerPa x 600.     WAR = sum / RPW (2026).
PITCHERS, runs per 9 for a STARTER role (gs share 1) and a RELIEVER role (0):
  model     CHAIN (pit_chain_test.py): the 1-season-out level (pit_horizon_backtest h=1 settings, OLS on
            every h=1 replicate with targets 2022-2026, plus the Stuff+ history channel at N0_S 250),
            then delta_T = R_h x level + the h=1 young-arm term to the target age; R = 1 / .70 / .40 at
            1 / 3 / 5 seasons out, no extra decline after the peak (fitted at its floor of 0 among arms
            who still pitch). Per-horizon direct fits scored the same (+.05 / -.08 percent) but were
            incoherent (468 of 602 arms 31+ projected better at 5 years than at 3).
  WAR/180   (lgRA9 - RA9) x 20 / RPW + replSp x 20     WAR/60 likewise with replRp x 60/9.
  Projections are of ACTUAL runs (the target the backtests scored), so hWAR's .90 deserved-runs scale
  does not apply here. Park: not neutralized on the pitcher side (untested).
thin_age_support lists the target years past the age the data supports (a 20-season convention).
Pools: anyone with MLB history in 2024-2026 (hitters >= 1 PA, pitchers >= 1 BF), position players
and pitchers separately. Ages are baseball ages (June 30) in the target season.

Usage: python3 scripts/research/projection/project_players.py
Output: data/_proj/projections_hitters.csv, data/_proj/projections_pitchers.csv (scratch)
"""
import csv
import json
import os
import sys
from datetime import date

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bat_rate_backtest as v1
import pit_rate_backtest as pr
import pit_horizon_backtest as ph
import pit_stuff_addon as pst
import aaa_hitter_bridge as hbr
import bat_experience_test as bxt

ROOT = v1.ROOT
P = v1.P
BASE = 2026
HORIZONS = (1, 3, 5)
PARK_M = 0.375
WSH = '120'


def baseball_age(birth, season):
    b = date.fromisoformat(birth)
    return season - b.year - ((6, 30) < (b.month, b.day))


def load_json(path):
    return json.load(open(os.path.join(ROOT, path)))


def main():
    meta = load_json('data/metadata_rs.json')
    hc = meta['hwarConstants']; wc = meta['eraPlusConstants']['war']
    scale, rpw, repl_pa = hc['wobaScale'], hc['rpw'], hc['replPerPa']
    fill = hc['bsrFill']
    PF = json.load(open(os.path.join(P, 'park_factors_hist.json')))

    def park_eff(y, team):
        pf = PF.get(str(y), {}).get(str(team))
        return 0.0 if pf is None else ((pf / 100 + 1) / 2 - 1) * hc['lgRPA'] * scale

    # ---------------- hitters ----------------
    # Prior (bat_experience_test.py, 2026-10-03): thin MLB history no longer regresses to the league
    # mean. mu(E) = EXP_C / (1 + E / EXP_K) with E the raw MLB PA of the history, and a hitter with a
    # Triple-A season in BASE or BASE-1 takes the box bridge at weight AAA_W. Held-out 13.74 vs 14.15
    # (8/9), better in every prior-PA bin; the league prior over-projected 1-50 PA by 20 wOBA points.
    EXP_C, EXP_K, AAA_W = -0.04, 200, 0.75
    AAA_T, MLB_T = hbr.season_tables()
    bbeta = bxt.bridge_beta(AAA_T, MLB_T, leave_T=None)
    X = {y: v1.load_xstats(y) for y in range(BASE - 3, BASE + 1)}   # four seasons of batting history (2026-10-03: 6/8, ~.3%)
    LG = {y: v1.league(X[y]) for y in X}
    lines = {y: {r['id']: r for r in json.load(open(os.path.join(P, f'lines_hitting_{y}.json')))} for y in X}
    sprint = {}
    for y in X:
        with open(os.path.join(P, f'sprint_{y}.csv'), encoding='utf-8-sig') as f:
            rows = [r for r in csv.DictReader(f) if r.get('sprint_speed')]
        n = {int(r['player_id']): (float(r['sprint_speed']), int(r['competitive_runs'] or 0)) for r in rows}
        lg = sum(s * c for s, c in n.values()) / sum(c for _, c in n.values())
        sprint[y] = (n, lg)
    frv = {y: json.load(open(os.path.join(P, f'frv_{y}.json'))) for y in X}
    # Fielding prior (fld_experience_test.py, 2026-10-03): a CONSTANT -1.0 runs per 1000 outs, not 0
    # (fielders with a history sit slightly below the all-fielder zero; 8/8 seasons, c interior, the
    # experience shape k ran to infinity). Outs per PA capped at the regulars' 90th percentile (a
    # convention, measured live): a 600-PA rate describes a full-timer, and a defensive replacement's
    # innings without plate appearances inflated the ratio (Pinckney 7.6 against a regular's 5.8).
    FLD_PRIOR = -1.0
    _r = []
    for _pid, _f in frv[BASE].items():
        _l = lines[BASE].get(int(_pid))
        _pa = int((_l or {}).get('plateAppearances') or 0); _o = sum(_f['outs_by_pos'].values())
        if _pa >= 500 and _o > 0:
            _r.append(_o / _pa)
    OUTS_PA_CAP = sorted(_r)[int(0.9 * len(_r))]
    print(f'  outs per PA cap (regulars 500+ PA, 90th percentile): {OUTS_PA_CAP:.2f} from {len(_r)} players')
    # Position (pos_assignment_test.py, 2026-10-03): innings SHARES by position, weighted .3 per season
    # back over three seasons, times a full-timer's innings per 600 PA (median of the top 150 hitters
    # by PA in BASE), on the shipped table. Beat the base season's runs per PA 8/8 (MSE 2.85 vs 3.34)
    # and stops crediting a defensive replacement's innings without PA.
    sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'projection'))
    import pos_assignment_test as pat
    posadj = hc['posAdj']
    INN = {y: pat.innings(y) for y in range(BASE - 2, BASE + 1)}
    _top = sorted((q for q in INN[BASE] if int((lines[BASE].get(q) or {}).get('plateAppearances') or 0) > 0),
                  key=lambda q: -int(lines[BASE][q].get('plateAppearances') or 0))[:150]
    FULL_INN = float(np.median([sum(INN[BASE][q].values()) / int(lines[BASE][q]['plateAppearances']) * 600 for q in _top]))
    print(f'  full-time innings per 600 PA (top 150 by PA, {BASE}): {FULL_INN:.0f}')
    pos600 = {}
    for q in set().union(*[set(INN[y]) for y in INN]):
        sh = {}; tot = 0.0
        for k in range(3):
            for pp, v in (INN[BASE - k].get(q) or {}).items():
                sh[pp] = sh.get(pp, 0.0) + 0.3 ** k * v; tot += 0.3 ** k * v
        if tot > 0:
            pos600[q] = sum(v / tot * posadj[pp] for pp, v in sh.items()) * FULL_INN / 1458.0
    bh = json.load(open(os.path.join(P, '_bat_horizon_backtest.json')))
    fld = json.load(open(os.path.join(P, '_fld_rate_backtest.json')))['pooled']
    lg_obp = {y: sum(int(r.get('hits') or 0) + int(r.get('baseOnBalls') or 0) + int(r.get('hitByPitch') or 0)
                     for r in lines[y].values()) / max(1, sum(int(r.get('atBats') or 0) + int(r.get('baseOnBalls') or 0)
                     + int(r.get('hitByPitch') or 0) + int(r.get('sacFlies') or 0) for r in lines[y].values())) for y in X}

    out_h = []
    ids = set().union(*[set(k for k, r in lines[y].items() if r.get('pos') != 'P' and int(r.get('plateAppearances') or 0) > 0) for y in range(BASE - 2, BASE + 1)])
    for pid in sorted(ids):
        rec = lines[BASE].get(pid) or lines[BASE - 1].get(pid) or lines[BASE - 2].get(pid)
        if not rec.get('birth'):
            continue
        row = {'mlbId': pid, 'name': rec['name'], 'pos': rec.get('pos'),
               'pa_2026': int((lines[BASE].get(pid) or {}).get('plateAppearances') or 0),
               'pa_2024_26': sum(int((lines[y].get(pid) or {}).get('plateAppearances') or 0) for y in X)}
        flags = []
        for h in HORIZONS:
            T = BASE + h
            age = baseball_age(rec['birth'], T)
            a, d, n0, ys, os_ = 0.75, 0.7, 450, 0.002, 0.0045
            E_raw = 0
            peak = 29 if h == 5 else 30
            num = den = agew = obn = obd = 0.0
            for k in range(4):
                y = BASE - k
                v = X[y].get(pid)
                if not v:
                    continue
                pe = park_eff(y, (lines[y].get(pid) or {}).get('team'))
                w_dev = v[1] - LG[y][0] - PARK_M * 1.0 * pe
                x_dev = v[2] - LG[y][1] - PARK_M * 0.37 * pe
                wt = d ** k * v[0]
                num += wt * (a * x_dev + (1 - a) * w_dev); den += wt; agew += wt * (age - h - k)
                if k < 3:
                    E_raw += v[0]     # the experience prior was fitted on three seasons
                L = lines[y].get(pid) or {}
                ob = int(L.get('hits') or 0) + int(L.get('baseOnBalls') or 0) + int(L.get('hitByPitch') or 0)
                obd_k = int(L.get('atBats') or 0) + int(L.get('baseOnBalls') or 0) + int(L.get('hitByPitch') or 0) + int(L.get('sacFlies') or 0)
                if obd_k:
                    obn += d ** k * obd_k * (ob / obd_k - lg_obp[y]); obd += d ** k * obd_k
            if den == 0:
                continue
            a0 = agew / den
            lo = min(age, peak) - min(a0, peak); hi = max(age, peak) - max(a0, peak)
            mu = EXP_C / (1 + E_raw / EXP_K)
            for ya in (BASE, BASE - 1):
                aa = AAA_T.get(ya, ({}, None))[0].get(pid)
                if aa and aa['age'] is not None:
                    mu = AAA_W * float(np.array([1.0] + hbr.features(aa, MLB_T[ya][0].get(pid), 1000)) @ bbeta) + (1 - AAA_W) * mu
                    break
            delta = (num + n0 * mu) / (den + n0) + ys * lo - os_ * hi
            bat = delta / scale * 600
            bat_wsh = (delta + PARK_M * 1.0 * park_eff(BASE, WSH)) / scale * 600
            # baserunning
            sn = sd_ = 0.0
            for k in range(3):
                y = BASE - k
                v = sprint[y][0].get(pid)
                if v and v[1] > 0:
                    sn += 0.3 ** k * v[1] * (v[0] - sprint[y][1]); sd_ += 0.3 ** k * v[1]
            if sd_ > 0:
                spd = sprint[BASE][1] + sn / (sd_ + 1) - 0.2 * h
                obp = lg_obp[BASE] + obn / (obd + n0)
                bsr = fill['k'] * (fill['a'] + fill['b'] * spd) * obp * 600
            else:
                spd, bsr = None, 0.0
                if h == 1:
                    flags.append('no sprint')
            # fielding
            fn = fd = 0.0; outs_pa_n = outs_pa_d = 0.0
            for k in range(3):
                y = BASE - k
                f = frv[y].get(str(pid))
                pa_y = int((lines[y].get(pid) or {}).get('plateAppearances') or 0)
                if f and f.get('total') is not None:
                    o = sum(f['outs_by_pos'].values())
                    if o > 0:
                        fn += fld['d'] ** k * o * 1000 * f['total'] / o; fd += fld['d'] ** k * o
                        if pa_y > 0:
                            outs_pa_n += fld['d'] ** k * o; outs_pa_d += fld['d'] ** k * pa_y
                elif pa_y > 0:
                    outs_pa_d += fld['d'] ** k * pa_y        # a DH season: PA with no fielding outs
            f_age = (fld['yi'] * (fld['peak'] - age) if age < fld['peak'] else -fld['od'] * (age - fld['peak']))
            frv1000 = (fn + fld['n0'] * FLD_PRIOR) / (fd + fld['n0']) + f_age
            outs_per_pa = min(outs_pa_n / outs_pa_d, OUTS_PA_CAP) if outs_pa_d else 0.0
            fldr = frv1000 / 1000 * outs_per_pa * 600
            posr = pos600.get(pid)
            if posr is None:
                posr = 0.0
                if h == 1:
                    flags.append('no 2026 position row')
            repl = repl_pa * 600
            war = (bat + bsr + fldr + posr + repl) / rpw
            war_wsh = (bat_wsh + bsr + fldr + posr + repl) / rpw
            row.update({f'age_{T}': age, f'wOBA_{T}': round(LG[BASE][0] + delta, 4),
                        f'bat600_{T}': round(bat, 1), f'bsr600_{T}': round(bsr, 1), f'fld600_{T}': round(fldr, 1),
                        f'pos600_{T}': round(posr, 1), f'repl600_{T}': round(repl, 1),
                        f'WAR600_{T}': round(war, 2), f'WAR600_WSH_{T}': round(war_wsh, 2),
                        f'sprint_{T}': round(spd, 1) if spd is not None else None})
        row['flags'] = '; '.join(flags)
        out_h.append(row)

    # ---------------- pitchers ----------------
    S = {y: pr.season(y) for y in range(2015, BASE + 1)}
    stuff = json.load(open(os.path.join(ROOT, 'data', '_era_internal_stuff.json')))
    phb = json.load(open(os.path.join(P, '_pit_horizon_backtest.json')))
    plines = {y: {r['id']: r for r in json.load(open(os.path.join(P, f'lines_pitching_{y}.json')))} for y in range(BASE - 2, BASE + 1)}
    lg_ra9 = wc['lgRA9']
    pids = set().union(*[set(k for k in S[y]) for y in range(BASE - 2, BASE + 1)])
    rows_p = {pid: {} for pid in pids}
    H1 = phb['1']['pooled']
    par = (H1['d'], H1['n0'], H1['peak'], H1['yi'], H1['od'])
    R = {1: 1.0, 3: 0.70, 5: 0.40}
    # Fit pool and experience term (pit_experience_test.py, 2026-10-03): the OLS is fitted on EVERY
    # pitcher with >= 1 out in the target season (the >= 30 IP pool under-projected thin-history arms
    # by .55 runs/9), plus x_E = 1 / (1 + E / PIT_EXP_K), E = raw history BF (k flat 10-35 once position players left the pool; 9/9 seasons).
    # Triple-A terms were tested and NOT adopted (6/9, swings both ways).
    PIT_EXP_K = 20

    def rows_all(B):
        T = B + 1
        return [(pid, t, [S[B - k].get(pid) for k in range(3)]) for pid, t in S[T].items()
                if any(S[B - k].get(pid) for k in range(3))]

    def x_exp(rows):
        return np.array([1 / (1 + sum(h['bf'] for h in hist if h) / PIT_EXP_K) for _, _, hist in rows])

    # Park (pit_park_test.py, 2026-10-03): the history's home-park effect and the target season's, in
    # runs per 9, enter the fit (9/9 seasons, 1.8 percent; history -.22, target +1.35 against the shrunk
    # published factor). hpWAR is neutral-park, so the target park is set to 0 at projection time.
    _pl = {y: json.load(open(os.path.join(P, f'lines_pitching_{y}.json'))) for y in range(2017, BASE + 1)}
    _club = {y: {r['id']: r.get('team') for r in _pl[y]} for y in _pl}
    _lgra9 = {y: 27 * sum(int(r.get('runs') or 0) for r in _pl[y]) / sum(int(r.get('outs') or 0) for r in _pl[y]) for y in _pl}
    _PF = json.load(open(os.path.join(P, 'park_factors_hist.json')))

    def _peff(y, team):
        pf = _PF.get(str(y), {}).get(str(team))
        return 0.0 if pf is None else ((pf / 100 + 1) / 2 - 1) * _lgra9[y]

    def x_park(rows, B, target_park):
        out = []
        for pid, _, hist in rows:
            num = den = 0.0
            for k, h in enumerate(hist):
                if h:
                    num += par[0] ** k * h['bf'] * _peff(B - k, _club[B - k].get(pid)); den += par[0] ** k * h['bf']
            out.append((num / den if den else 0.0, _peff(B + 1, _club[B + 1].get(pid)) if target_park else 0.0))
        return np.array(out)

    bases = [B for B in ph.HORIZONS[1] if B + 1 >= 2022]          # Stuff+ history exists from 2021
    R1 = {B: rows_all(B) for B in bases}
    tr = [ph.feats(R1[B], 1, *par) for B in bases]
    ch = [pst.stuff_channel(R1[B], B + 1, stuff, H1['d'], 250)[0] for B in bases]
    Xtr = np.column_stack([np.vstack([t[0][:, :-1] for t in tr]), np.concatenate(ch),
                           np.concatenate([x_exp(R1[B]) for B in bases]), np.vstack([x_park(R1[B], B, True) for B in bases]),
                           np.concatenate([t[0][:, -1] for t in tr])])
    ytr = np.concatenate([t[1] for t in tr]); wtr = np.concatenate([t[2] for t in tr])
    for role, gs in (('SP', 1.0), ('RP', 0.0)):
        fake = []
        for pid in pids:
            hist = [S[BASE - k].get(pid) for k in range(3)]
            k0 = next(k for k, x in enumerate(hist) if x)          # most recent season he pitched
            fake.append((pid, {'age': hist[k0]['age'] + k0 + 1, 'gs': gs, 'ra9': 0.0, 'fip': 0.0, 'ip': 1.0}, hist))
        Xp, _, _ = ph.feats(fake, 1, *par)
        c, _ = pst.stuff_channel(fake, BASE + 1, stuff, H1['d'], 250)
        lvl, _ = pr.fit_predict(Xtr, ytr, wtr, np.column_stack([Xp[:, :-1], c, x_exp(fake), x_park(fake, BASE, False), Xp[:, -1]]))
        for (pid, t, _), l1 in zip(fake, lvl):
            for h in HORIZONS:
                T = BASE + h
                a1, aT = t['age'], t['age'] + h - 1
                young = H1['yi'] * (min(aT, H1['peak']) - min(a1, H1['peak']))
                ra9 = lg_ra9 + R[h] * l1 - young
                ip = 180 if role == 'SP' else 60
                repl = wc['replSp'] if role == 'SP' else wc['replRp']
                war = (lg_ra9 - ra9) * ip / 9 / rpw + repl * ip / 9
                rows_p[pid].update({f'age_{T}': aT, f'RA9_{role}_{T}': round(ra9, 2), f'WAR{ip}_{role}_{T}': round(war, 2)})
    out_p = []
    for pid, r in rows_p.items():
        rec = (plines[BASE].get(pid) or plines[BASE - 1].get(pid) or plines[BASE - 2].get(pid))
        if not rec:
            continue
        r.update({'mlbId': pid, 'name': rec['name'], 'ip_2026': round(int((plines[BASE].get(pid) or {}).get('outs') or 0) / 3, 1),
                  'gs_share_2026': round(S[BASE][pid]['gs'], 2) if pid in S[BASE] else None,
                  'ip_2024_26': round(sum(int((plines[y].get(pid) or {}).get('outs') or 0) for y in plines) / 3, 1)})
        out_p.append(r)

    # thin age support (a convention): fewer than 20 player-seasons of that age in the 2018-2026 backtest
    # pools (hitters >= 200 PA: 13 at 38; pitchers >= 30 IP: 11 at 39). Beyond it the multi-year value
    # describes the few who kept a job, not this player.
    for rows, lim in ((out_h, 38), (out_p, 39)):
        for r in rows:
            thin = [str(BASE + h) for h in HORIZONS if (r.get(f'age_{BASE + h}') or 0) >= lim]
            r['thin_age_support'] = ' '.join(thin)
    for name, rows in (('projections_hitters.csv', out_h), ('projections_pitchers.csv', out_p)):
        cols = []
        for r in rows:
            for k in r:
                if k not in cols:
                    cols.append(k)
        path = os.path.join(P, name)
        with open(path + '.tmp', 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader(); w.writerows(rows)
        os.replace(path + '.tmp', path)
        print(f'wrote {name}: {len(rows)} rows')


if __name__ == '__main__':
    main()
