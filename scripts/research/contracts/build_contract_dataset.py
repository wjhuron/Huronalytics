"""build_contract_dataset.py: one row per free agent, offseasons 2020-2027, for the contract model.

Sources (all keyed by id, never by name):
  * ~/Downloads/{Y}-free-agent-tracker.xlsx.xlsx, Y = 2020..2027 (FanGraphs trackers; Y is the
    season AFTER the offseason, so the platform season is Y-1). Signing Team / Years / Total Salary /
    AAV are the outcome; Pos / Thr / Age / QO describe the player.
  * data/_fa_contracts/actual_{y}_{bat|pit}.json (pull_fg_war_history.py): FanGraphs WAR and playing
    time for the three seasons before the signing, with playerid AND xMLBAMID.
  * data/steamer_preseason/steamer_{Y}_{bat|pit}.csv (2017-2026 preseason finals) and
    data/_proj/fg/steamer_2027_{bat|pit}.json (the live 2027 projection): the projection the market saw.
  * MLB Stats API bulk fielding (innings by position, cached to data/_fa_contracts/fielding_{y}.json):
    versatility measured the same way for every season, not from a hand label.
  * data/free_agents.json: the 2027 class (adds released / elected players the tracker does not list).

The 2020 season is scaled to 162 games (WAR, PA, IP, GS x 162/60). A season with no MLB row is 0 WAR
and 0 playing time: no MLB time is a real observation, not a missing value.

Outcome classes: MLB deal (Total Salary > 0), MiLB deal (signing team, Total 0 or blank), unsigned
(no signing team: retired, abroad, or still unsigned when the tracker was saved).
Output: data/_fa_contracts/dataset.csv (scratch).
Usage: python3 scripts/research/contracts/build_contract_dataset.py
"""
import json
import math
import os
import subprocess
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
D = os.path.join(ROOT, 'data', '_fa_contracts')
DL = os.path.expanduser('~/Downloads')
YEARS = range(2020, 2028)
LIVE = 2027
SCALE = {2020: 162 / 60}
FIELD_URL = ('https://statsapi.mlb.com/api/v1/stats?stats=season&group=fielding&season={y}&sportId=1'
             '&playerPool=ALL&limit=5000&offset={o}')
POS_CODES = {'2': 'C', '3': '1B', '4': '2B', '5': '3B', '6': 'SS', '7': 'LF', '8': 'CF', '9': 'RF'}


def load_actual(y):
    s = SCALE.get(y, 1.0)
    out = {}
    for side in ('bat', 'pit'):
        for r in json.load(open(os.path.join(D, f'actual_{y}_{side}.json'))):
            fg = str(r.get('playerid') or '').strip()
            if not fg:
                continue
            e = out.setdefault(fg, {'mlbam': r.get('xMLBAMID'), 'bwar': 0.0, 'pwar': 0.0, 'pa': 0.0, 'ip': 0.0, 'gs': 0.0, 'g_p': 0.0, 'pos': None})
            if side == 'bat':
                e['bwar'] += (r.get('WAR') or 0) * s
                e['pa'] += (r.get('PA') or 0) * s
                e['pos'] = r.get('Pos')
            else:
                e['pwar'] += (r.get('WAR') or 0) * s
                ip = r.get('IP') or 0
                ip = int(ip) + round((ip - int(ip)) * 10) / 3      # FanGraphs .1 / .2 innings
                e['ip'] += ip * s
                e['gs'] += (r.get('GS') or 0) * s
                e['g_p'] += (r.get('G') or 0) * s
    return out


def fielding(y):
    path = os.path.join(D, f'fielding_{y}.json')
    if not os.path.exists(path):
        rows, o = [], 0
        while True:
            body = subprocess.run(['curl', '-sfL', '--retry', '3', FIELD_URL.format(y=y, o=o)], capture_output=True)
            if body.returncode != 0:
                raise SystemExit(f'fielding {y}: curl failed ({body.returncode})')
            st = json.loads(body.stdout)['stats'][0]
            sp = st['splits']
            rows += [{'id': s['player']['id'], 'pos': s['position']['code'], 'inn': s['stat'].get('innings', '0')} for s in sp]
            o += len(sp)
            if not sp or o >= st.get('totalSplits', 0):
                break
            time.sleep(1)
        with open(path + '.tmp', 'w') as f:
            json.dump(rows, f)
        os.replace(path + '.tmp', path)
    inn = {}
    for r in json.load(open(path)):
        p = POS_CODES.get(r['pos'])
        if not p:
            continue
        x = float(r['inn'] or 0)
        x = int(x) + round((x - int(x)) * 10) / 3
        inn.setdefault(r['id'], {}).setdefault(p, 0.0)
        inn[r['id']][p] += x
    return inn


def steamer(Y):
    """fgid -> (war, pa, ip, gs), plus mlbam -> same, for the projection of season Y."""
    by_fg, by_am = {}, {}
    if Y == LIVE:
        for side in ('bat', 'pit'):
            for r in json.load(open(os.path.join(ROOT, 'data', '_proj', 'fg', f'steamer_{Y}_{side}.json'))):
                key = 'b' if side == 'bat' else 'p'
                rec = {f'{key}war': r.get('WAR'), 'pa' if side == 'bat' else 'ip': r.get('PA' if side == 'bat' else 'IP'),
                       **({'gs': r.get('GS'), 'g': r.get('G')} if side == 'pit' else {})}
                by_fg.setdefault(str(r.get('playerid')), {}).update(rec)
                if r.get('xMLBAMID'):
                    by_am.setdefault(int(r['xMLBAMID']), {}).update(rec)
        return by_fg, by_am
    for side in ('bat', 'pit'):
        df = pd.read_csv(os.path.join(ROOT, 'data', 'steamer_preseason', f'steamer_{Y}_{side}.csv'))
        for r in df.to_dict('records'):
            key = 'b' if side == 'bat' else 'p'
            rec = {f'{key}war': r['war'], **({'pa': r['pa']} if side == 'bat' else {'ip': r['ip'], 'gs': r['gs'], 'g': r['g']})}
            by_fg.setdefault(str(r['fgid']), {}).update(rec)
            if not pd.isna(r['mlbam']):
                by_am.setdefault(int(r['mlbam']), {}).update(rec)
    return by_fg, by_am


def versatility(inn_seasons):
    """Innings by position over the given seasons -> (effective positions, top position, shares)."""
    tot = {}
    for s in inn_seasons:
        for p, x in (s or {}).items():
            tot[p] = tot.get(p, 0) + x
    T = sum(tot.values())
    if T < 1:
        return np.nan, None, {}
    sh = {p: x / T for p, x in tot.items()}
    return 1 / sum(v * v for v in sh.values()), max(sh, key=sh.get), sh


def main():
    act = {y: load_actual(y) for y in range(2016, 2027)}
    am2fg = {}
    for y in act:
        for fg, e in act[y].items():
            if e['mlbam']:
                am2fg[int(e['mlbam'])] = fg
    fld = {y: fielding(y) for y in range(2017, 2027)}
    rows = []
    for Y in YEARS:
        trk = pd.read_excel(os.path.join(DL, f'{Y}-free-agent-tracker.xlsx.xlsx'))
        trk['playerid'] = trk['playerid'].astype(str).str.strip()
        trk = trk.drop_duplicates('playerid')
        if Y == LIVE:
            fa = json.load(open(os.path.join(ROOT, 'data', 'free_agents.json')))['players']
            keep_fg = {am2fg.get(p['mlbId']) for p in fa}
            extra = [p for p in fa if am2fg.get(p['mlbId']) not in set(trk['playerid'])]
            trk = trk[trk['playerid'].isin(keep_fg)]
            add = pd.DataFrame([{'Name': p['name'], 'playerid': am2fg.get(p['mlbId']) or f"am{p['mlbId']}",
                                 'Age': p['age'], '_mlbam': p['mlbId'], 'FA Likelihood': ','.join(p['sources'])} for p in extra])
            trk = pd.concat([trk, add], ignore_index=True)
        st_fg, st_am = steamer(Y)
        P = Y - 1
        for r in trk.to_dict('records'):
            fg = r['playerid']
            hist = [act.get(P - k, {}).get(fg, {}) for k in range(3)]
            am = r.get('_mlbam') if not pd.isna(r.get('_mlbam', np.nan)) else None
            am = int(am) if am else next((int(h['mlbam']) for h in hist if h.get('mlbam')), None)
            pos_lbl = r.get('Pos') if isinstance(r.get('Pos'), str) else None
            ip3 = sum(h.get('ip', 0) for h in hist)
            pa3 = sum(h.get('pa', 0) for h in hist)
            if pos_lbl:
                is_p = pos_lbl in ('SP', 'RP', 'P')
            else:
                is_p = ip3 * 4.3 > pa3
            gs_sh = None
            if is_p:
                g = sum(h.get('g_p', 0) for h in hist[:2])
                gs_sh = sum(h.get('gs', 0) for h in hist[:2]) / g if g else 0.0
                role = 'SP' if (pos_lbl == 'SP' or (pos_lbl is None and gs_sh >= 0.5)) else 'RP'
            else:
                role = 'H'
            wkey = 'pwar' if is_p else 'bwar'
            war = [h.get(wkey, 0.0) for h in hist]
            pt = [h.get('ip' if is_p else 'pa', 0.0) for h in hist]
            stm = st_fg.get(fg) or (st_am.get(am) if am else None) or {}
            s_war = stm.get(wkey)
            s_pt = stm.get('ip' if is_p else 'pa')
            eff, top, sh = (np.nan, None, {})
            if not is_p and am:
                eff, top, sh = versatility([fld[P - k].get(am) for k in range(2) if P - k in fld])
            tot = r.get('Total Salary')
            if (pd.isna(tot) or tot <= 0) and not pd.isna(r.get('AAV', np.nan)) and r['AAV'] > 0 and not pd.isna(r.get('Years', np.nan)):
                tot = r['AAV'] * r['Years']      # the 2020 tracker carries AAV only
            team = r.get('Signing Team')
            if Y == LIVE:
                outcome = None
            elif not isinstance(team, str) or not team.strip():
                outcome = 'unsigned'
            elif pd.isna(tot) or tot <= 0:
                outcome = 'milb'
            else:
                outcome = 'mlb'
            rows.append({
                'Y': Y, 'fg': fg, 'mlbam': am, 'name': r['Name'], 'pos_lbl': pos_lbl, 'role': role,
                'thr': r.get('Thr') if isinstance(r.get('Thr'), str) else None, 'age': r.get('Age'),
                'qo': 0 if pd.isna(r.get('QO', np.nan)) else 1, 'fa_status': r.get('FA Likelihood'),
                'war0': war[0], 'war1': war[1], 'war2': war[2], 'pt0': pt[0], 'pt1': pt[1], 'pt2': pt[2],
                'gs_share': gs_sh, 'stm_war': s_war, 'stm_pt': s_pt,
                'eff_pos': eff, 'top_pos': top,
                **{f'sh_{p}': sh.get(p, 0.0) for p in POS_CODES.values()},
                'outcome': outcome, 'team': team if isinstance(team, str) else None,
                'years': r.get('Years'), 'total': tot, 'aav': (tot / r['Years']) if outcome == 'mlb' and r.get('Years') else None,
                'aav_trk': r.get('AAV'),
            })
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(D, 'dataset.csv'), index=False)
    print(df.groupby(['Y', 'outcome'], dropna=False).size().unstack())
    print('no steamer:', df.stm_war.isna().groupby(df.Y).sum().to_dict())
    print('no age:', df.age.isna().sum(), ' roles:', df.role.value_counts().to_dict())


if __name__ == '__main__':
    main()
