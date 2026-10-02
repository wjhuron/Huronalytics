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
    X = {y: v1.load_xstats(y) for y in range(BASE - 2, BASE + 1)}
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
    H = load_json('data/hitter_leaderboard_rs.json')
    pos600 = {}
    for r in H:
        if r.get('mlbId') and r.get('pa') and r.get('hPosRuns') is not None and r.get('team') not in ('ROC', 'AAA'):
            k = int(r['mlbId'])
            if r['team'].endswith('TM') or k not in pos600:     # a combined row carries the season
                pos600[k] = 600 * r['hPosRuns'] / r['pa']
    bh = json.load(open(os.path.join(P, '_bat_horizon_backtest.json')))
    fld = json.load(open(os.path.join(P, '_fld_rate_backtest.json')))['pooled']
    lg_obp = {y: sum(int(r.get('hits') or 0) + int(r.get('baseOnBalls') or 0) + int(r.get('hitByPitch') or 0)
                     for r in lines[y].values()) / max(1, sum(int(r.get('atBats') or 0) + int(r.get('baseOnBalls') or 0)
                     + int(r.get('hitByPitch') or 0) + int(r.get('sacFlies') or 0) for r in lines[y].values())) for y in X}

    out_h = []
    ids = set().union(*[set(k for k, r in lines[y].items() if r.get('pos') != 'P' and int(r.get('plateAppearances') or 0) > 0) for y in X])
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
            peak = 29 if h == 5 else 30
            num = den = agew = obn = obd = 0.0
            for k in range(3):
                y = BASE - k
                v = X[y].get(pid)
                if not v:
                    continue
                pe = park_eff(y, (lines[y].get(pid) or {}).get('team'))
                w_dev = v[1] - LG[y][0] - PARK_M * 1.0 * pe
                x_dev = v[2] - LG[y][1] - PARK_M * 0.37 * pe
                wt = d ** k * v[0]
                num += wt * (a * x_dev + (1 - a) * w_dev); den += wt; agew += wt * (age - h - k)
                L = lines[y].get(pid) or {}
                ob = int(L.get('hits') or 0) + int(L.get('baseOnBalls') or 0) + int(L.get('hitByPitch') or 0)
                obd_k = int(L.get('atBats') or 0) + int(L.get('baseOnBalls') or 0) + int(L.get('hitByPitch') or 0) + int(L.get('sacFlies') or 0)
                if obd_k:
                    obn += d ** k * obd_k * (ob / obd_k - lg_obp[y]); obd += d ** k * obd_k
            if den == 0:
                continue
            a0 = agew / den
            lo = min(age, peak) - min(a0, peak); hi = max(age, peak) - max(a0, peak)
            delta = num / (den + n0) + ys * lo - os_ * hi
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
            frv1000 = fn / (fd + fld['n0']) + f_age
            outs_per_pa = outs_pa_n / outs_pa_d if outs_pa_d else 0.0
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
    bases = [B for B in ph.HORIZONS[1] if B + 1 >= 2022]          # Stuff+ history exists from 2021
    tr = [ph.feats(ph.rows_for(S, B, 1), 1, *par) for B in bases]
    ch = [pst.stuff_channel(ph.rows_for(S, B, 1), B + 1, stuff, H1['d'], 250)[0] for B in bases]
    Xtr = np.column_stack([np.vstack([t[0][:, :-1] for t in tr]), np.concatenate(ch), np.concatenate([t[0][:, -1] for t in tr])])
    ytr = np.concatenate([t[1] for t in tr]); wtr = np.concatenate([t[2] for t in tr])
    for role, gs in (('SP', 1.0), ('RP', 0.0)):
        fake = []
        for pid in pids:
            hist = [S[BASE - k].get(pid) for k in range(3)]
            k0 = next(k for k, x in enumerate(hist) if x)          # most recent season he pitched
            fake.append((pid, {'age': hist[k0]['age'] + k0 + 1, 'gs': gs, 'ra9': 0.0, 'fip': 0.0, 'ip': 1.0}, hist))
        Xp, _, _ = ph.feats(fake, 1, *par)
        c, _ = pst.stuff_channel(fake, BASE + 1, stuff, H1['d'], 250)
        lvl, _ = pr.fit_predict(Xtr, ytr, wtr, np.column_stack([Xp[:, :-1], c, Xp[:, -1]]))
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
