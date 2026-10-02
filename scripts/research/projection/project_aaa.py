"""project_aaa.py: 2027 / 2029 / 2031 MLB projections for 2026 Triple-A players (prospects: AAA only,
per Wally 2026-10-02). Research output.

Hitters (>= 100 PA at Triple-A in 2026): the box bridge (aaa_hitter_bridge.py, pooled OLS, N0 1000;
held-out r .06-.48, typically ~.25, beats the naive translation 7/10) gives the 2027 MLB wOBA delta,
then the MLB aging rule (+.002 / -.0045 per year, peak 30 / 30 / 29). Per 600 PA: batting runs;
baserunning from his MLB sprint speed when Savant has one (the MLB projection's relation), else 0;
fielding 0 (no FRV at Triple-A: unknown, not average, and flagged); positional = the shipped 2026
table at his listed position x 600/700 (a regular's season is about 700 PA per 1458 innings, a
labeled conversion); replacement and RPW as the MLB table.
Pitchers (>= 20 IP at Triple-A in 2026): the box bridge (aaa_pitcher_bridge.py; held-out r .03-.30,
weak) for the 2027 level, then the MLB chain (R 1 / .70 / .40, young-arm term). Rochester rows also
carry the shipped hpERA (+.08 measured AAA->MLB shift, reference-aaa-level-correction), the better
founded run-prevention read for that club.
Output: data/_proj/projections_aaa_hitters.csv, data/_proj/projections_aaa_pitchers.csv (scratch)
"""
import csv
import json
import os
import sys
from datetime import date

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aaa_hitter_bridge as hb
import aaa_pitcher_bridge as pb

ROOT = hb.ROOT
P = hb.P
BASE = 2026
ROC = 534
HORIZONS = (1, 3, 5)


def main():
    meta = json.load(open(os.path.join(ROOT, 'data', 'metadata_rs.json')))
    hc = meta['hwarConstants']; wc = meta['eraPlusConstants']['war']
    scale, rpw, repl_pa, fill, posadj = hc['wobaScale'], hc['rpw'], hc['replPerPa'], hc['bsrFill'], hc['posAdj']
    lg_ra9 = wc['lgRA9']
    A, M = hb.season_tables()
    bh = json.load(open(os.path.join(P, '_aaa_hitter_bridge.json')))['box']
    beta = np.array(bh['beta'])
    lg_mlb_woba = M[BASE][1]['woba']
    # Triple-A lines list some players only as OF or IF: the plain mean of the spots it stands for (a
    # labeled convention; the line does not say which)
    GROUP = {'OF': (posadj['LF'] + posadj['CF'] + posadj['RF']) / 3, 'IF': (posadj['2B'] + posadj['3B'] + posadj['SS']) / 3}
    sprint = {}
    with open(os.path.join(P, f'sprint_{BASE}.csv'), encoding='utf-8-sig') as f:
        rows = [r for r in csv.DictReader(f) if r.get('sprint_speed')]
    lg_sp = sum(float(r['sprint_speed']) * int(r['competitive_runs'] or 0) for r in rows) / sum(int(r['competitive_runs'] or 0) for r in rows)
    for r in rows:
        sprint[int(r['player_id'])] = float(r['sprint_speed'])
    _ln = json.load(open(os.path.join(P, f'lines_hitting_{BASE}.json')))
    _g = lambda r, k: int(r.get(k) or 0)
    lg_obp = (sum(_g(r, 'hits') + _g(r, 'baseOnBalls') + _g(r, 'hitByPitch') for r in _ln)
              / sum(_g(r, 'atBats') + _g(r, 'baseOnBalls') + _g(r, 'hitByPitch') + _g(r, 'sacFlies') for r in _ln))
    out_h = []
    for pid, a in A[BASE][0].items():
        if a['pa'] < 100 or a['age'] is None:
            continue
        x = np.array([1.0] + hb.features(a, M[BASE][0].get(pid), bh['n0']))
        d27 = float(x @ beta)
        row = {'mlbId': pid, 'name': a['name'], 'rochester': a['team'] == ROC, 'aaa_team': a['team'], 'pos': a['pos'],
               'aaa_pa_2026': a['pa'], 'aaa_wOBA_2026': round(a['woba'], 3), 'mlb_pa_2026': (M[BASE][0].get(pid) or {}).get('pa', 0)}
        flags = ['fielding unknown (0)']
        for h in HORIZONS:
            T = BASE + h
            age = a['age'] + h          # lines carry the June-30 age of 2026
            peak = 29 if h == 5 else 30
            a1 = a['age'] + 1
            lo = min(age, peak) - min(a1, peak); hi = max(age, peak) - max(a1, peak)
            delta = d27 + 0.002 * lo - 0.0045 * hi
            bat = delta / scale * 600
            spd = sprint.get(pid)
            bsr = fill['k'] * (fill['a'] + fill['b'] * (spd - 0.2 * h)) * lg_obp * 600 if spd else 0.0
            pos = posadj.get(a['pos'] or '', GROUP.get(a['pos'], 0.0)) * 600 / 700
            war = (bat + bsr + pos + repl_pa * 600) / rpw
            row.update({f'age_{T}': age, f'wOBA_{T}': round(lg_mlb_woba + delta, 3), f'bat600_{T}': round(bat, 1),
                        f'bsr600_{T}': round(bsr, 1), f'pos600_{T}': round(pos, 1), f'WAR600_{T}': round(war, 2)})
        if not sprint.get(pid):
            flags.append('no MLB sprint (baserunning 0)')
        if a['pos'] in GROUP:
            flags.append(f'listed {a["pos"]}: positional = mean of its spots')
        elif a['pos'] not in posadj:
            flags.append(f'position {a["pos"]} not in the table (0)')
        row['flags'] = '; '.join(flags)
        out_h.append(row)

    Ap, Mp = pb.tables()
    pbb = json.load(open(os.path.join(P, '_aaa_pitcher_bridge.json')))['box']
    pbeta = np.array(pbb['beta'])
    L = json.load(open(os.path.join(ROOT, 'data', 'pitcher_leaderboard_rs.json')))
    hp = {int(r['mlbId']): r.get('hpERA') for r in L if r.get('team') == 'ROC' and r.get('mlbId')}
    R = {1: 1.0, 3: 0.70, 5: 0.40}
    out_p = []
    for pid, a in Ap[BASE].items():
        if a['ip'] < 20 or a['age'] is None:
            continue
        row = {'mlbId': pid, 'name': a['name'], 'rochester': a['team'] == ROC, 'aaa_team': a['team'],
               'aaa_ip_2026': round(a['ip'], 1), 'aaa_RA9_2026': round(a['ra9'], 2), 'aaa_gs_share_2026': round(a['gs'], 2),
               'mlb_ip_2026': round((Mp[BASE].get(pid) or {}).get('ip', 0), 1),
               'hpERA_ROC_2026': hp.get(pid)}
        for role, gs in (('SP', 1.0), ('RP', 0.0)):
            x = np.array([1.0] + pb.features(a, Mp[BASE].get(pid), gs, a['age'] + 1, pbb['n0']))
            l1 = float(x @ pbeta)
            for h in HORIZONS:
                T = BASE + h
                a1, aT = a['age'] + 1, a['age'] + h
                young = 0.09 * (min(aT, 26) - min(a1, 26))
                ra9 = lg_ra9 + R[h] * l1 - young
                ip = 180 if role == 'SP' else 60
                repl = wc['replSp'] if role == 'SP' else wc['replRp']
                row.update({f'age_{T}': aT, f'RA9_{role}_{T}': round(ra9, 2),
                            f'WAR{ip}_{role}_{T}': round((lg_ra9 - ra9) * ip / 9 / rpw + repl * ip / 9, 2)})
        out_p.append(row)

    for name, rows in (('projections_aaa_hitters.csv', out_h), ('projections_aaa_pitchers.csv', out_p)):
        cols = []
        for r in rows:
            for k in r:
                if k not in cols:
                    cols.append(k)
        path = os.path.join(P, name)
        with open(path + '.tmp', 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
        os.replace(path + '.tmp', path)
        print(f'wrote {name}: {len(rows)} rows ({sum(1 for r in rows if r["rochester"])} Rochester)')


if __name__ == '__main__':
    main()
