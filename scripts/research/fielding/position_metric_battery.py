"""Which public fielding metric is best at each position?

Sources, cached in data/_fielding_battery/: Savant Fielding Run Value by position (range, arm,
double play, first-base receiving, framing, blocking, throwing), FanGraphs DRS and UZR, MLB API
innings by player x club x position. Rate = runs per 1,000 innings at that position.

Test A, repeatability: rate in Y against rate in Y+1, 200+ innings both years, weighted by the
harmonic mean of the innings, for everyone and for club-changers only (a club's positioning
and park stay behind). A diagnostic: it does not say a metric measures the right thing.

Test B, the objective: a player's rate in Y, times his innings for his club at that position in
Y+1, summed per club, against that club's runs saved against xwOBA in Y+1 on balls hit to that
position's zone. Different plays from the rating, so a metric cannot score by reading its own
inputs. No Y rating counts as league average. Fielding club comes from the pitcher's clubs
that season and the game's two clubs; a pitcher on both drops. Zones are conventions: ground
balls 3B under -25 deg, SS -25 to 0, 2B 0 to 25, 1B over 25; air balls LF under -15, CF, RF over
15. Popups out. An error counts as a single. Club-season means removed per season.
Catchers run Test A only: no ball-in-play target measures framing.

Limit: the MLB API serves one row per player x position with his FINAL club, so a traded
player's innings all land on that club in Test B, and club-changers in Test A miss a move
inside a season.

    python3 scripts/research/fielding/position_metric_battery.py
Writes data/_fielding_battery/results.json.
"""
import csv
import gc
import io
import json
import os
import subprocess
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT = os.path.join(ROOT, 'data', '_fielding_battery')
os.makedirs(OUT, exist_ok=True)
YEARS = [2021, 2022, 2023, 2024, 2025]
POS = {'C': 2, '1B': 3, '2B': 4, '3B': 5, 'SS': 6, 'LF': 7, 'CF': 8, 'RF': 9}
FGPOS = {'C': 'c', '1B': '1b', '2B': '2b', '3B': '3b', 'SS': 'ss', 'LF': 'lf', 'CF': 'cf', 'RF': 'rf'}
HX, HY, SCALE = 125.42, 198.27, 1.24
W = {'single': .89, 'double': 1.261, 'triple': 1.596, 'home_run': 2.049, 'field_error': .89}
UA = 'Mozilla/5.0 (Macintosh)'


def get(url, path):
    path = os.path.join(OUT, path)
    if os.path.exists(path):
        return open(path, encoding='utf-8-sig').read()
    for wait in (0, 5, 20, 60):
        time.sleep(wait)
        r = subprocess.run(['curl', '-sfL', '--retry', '3', '-A', UA, url], capture_output=True, text=True)
        t = r.stdout
        if r.returncode == 0 and t.strip() and not t.lstrip('﻿ ').startswith('<'):
            open(path + '.tmp', 'w').write(t)
            os.replace(path + '.tmp', path)
            return t
    raise SystemExit(f'ABORT: no data from {url}. Re-run: finished pulls are cached.')


def f(v):
    return float(v) if v not in (None, '') else np.nan


def pull():
    rows, teams = [], {}
    for y in YEARS:
        for p, code in POS.items():
            t = get('https://baseballsavant.mlb.com/leaderboard/fielding-run-value?gameType=Regular&seasonStart='
                    f'{y}&seasonEnd={y}&type=fielder&position={code}&minInnings=1&csv=true', f'sv_{y}_{p}.csv')
            for r in csv.DictReader(io.StringIO(t)):
                rows.append({'id': int(r['id']), 'y': y, 'p': p, 'sv_total': f(r['total_runs']), 'sv_range': f(r['range_runs']),
                             'sv_arm': f(r['arm_runs']), 'sv_dp': f(r['dp_runs']), 'sv_rec': f(r.get('fielding_runs_prevented_on_rec1b')),
                             'sv_frame': f(r['framing_runs']), 'sv_throw': f(r['throwing_runs']), 'sv_block': f(r['blocking_runs'])})
    sv = pd.DataFrame(rows)
    rows = []
    for y in YEARS:
        for p, code in FGPOS.items():
            t = get(f'https://www.fangraphs.com/api/leaders/major-league/data?pos={code}&stats=fld&lg=all&qual=0&type=1&season={y}'
                    f'&seasonEnd={y}&month=0&ind=0&team=0&pageitems=2000&pagenum=1', f'fg_{y}_{p}.json')
            for r in json.loads(t)['data']:
                if r.get('xMLBAMID'):
                    rows.append({'id': int(r['xMLBAMID']), 'y': y, 'p': p, 'DRS': r.get('DRS'), 'UZR': r.get('UZR'), 'rSZ': r.get('rSZ'), 'rSB': r.get('rSB')})
            time.sleep(6)
    fg = pd.DataFrame(rows).astype({'DRS': float, 'UZR': float, 'rSZ': float, 'rSB': float})
    rows = []
    for y in YEARS:
        t = get(f'https://statsapi.mlb.com/api/v1/stats?stats=season&group=fielding&season={y}&sportId=1&limit=10000&playerPool=all',
                f'inn_{y}.json')
        for s in json.loads(t)['stats'][0]['splits']:
            inn = s['stat'].get('innings')
            if inn is None or 'team' not in s:
                continue
            w, _, o = str(inn).partition('.')
            rows.append({'id': s['player']['id'], 'y': y, 'p': s['position']['abbreviation'], 'team': s['team']['id'],
                         'inn': int(w) + int(o or 0) / 3})
    inn = pd.DataFrame(rows)
    return sv, fg, inn


def wr(a, b, w):
    a, b, w = np.asarray(a, float), np.asarray(b, float), np.asarray(w, float)
    ok = np.isfinite(a) & np.isfinite(b) & (w > 0)
    if ok.sum() < 20:
        return np.nan
    C = np.cov(a[ok], b[ok], aweights=w[ok])
    return float(C[0, 1] / np.sqrt(C[0, 0] * C[1, 1]))


def club_targets(inn):
    out = []
    for y in YEARS:
        games = {}
        t = get(f'https://statsapi.mlb.com/api/v1/schedule?sportId=1&season={y}&gameType=R', f'sched_{y}.json')
        for d in json.loads(t)['dates']:
            for g in d['games']:
                games[g['gamePk']] = (g['teams']['home']['team']['id'], g['teams']['away']['team']['id'])
        stints = inn[(inn.y == y) & (inn.p == 'P')].groupby('id').team.apply(set).to_dict()
        d = pd.read_pickle(os.path.join(ROOT, 'data', f'_statcast{y}_cache.pkl'))
        d = d[(d['type'] == 'X') & d.bb_type.notna()]
        x = pd.DataFrame({'pk': pd.to_numeric(d.game_pk), 'pit': pd.to_numeric(d.pitcher), 'bb': d.bb_type.astype('object').to_numpy(),
                          'hx': pd.to_numeric(d.hc_x, errors='coerce').to_numpy('float64', na_value=np.nan),
                          'hy': pd.to_numeric(d.hc_y, errors='coerce').to_numpy('float64', na_value=np.nan),
                          'xw': pd.to_numeric(d.estimated_woba_using_speedangle, errors='coerce').to_numpy('float64', na_value=np.nan),
                          'w': d.events.astype('object').map(W).fillna(0.0).to_numpy()})
        del d
        gc.collect()
        x = x.dropna(subset=['hx', 'hy', 'xw'])
        def club(pk, pit):
            c = set(games.get(pk, ())) & stints.get(pit, set())
            return next(iter(c)) if len(c) == 1 else None
        x['team'] = [club(a, b) for a, b in zip(x.pk, x.pit)]
        print(y, 'BIP', len(x), 'dropped with no single club', int(x.team.isna().sum()), flush=True)
        x = x.dropna(subset=['team'])
        a = np.degrees(np.arctan2(x.hx - HX, HY - x.hy))
        gb, air = x.bb == 'ground_ball', x.bb.isin(['fly_ball', 'line_drive'])
        zone = np.select([gb & (a < -25), gb & (a < 0), gb & (a < 25), gb, air & (a < -15), air & (a <= 15), air],
                         ['3B', 'SS', '2B', '1B', 'LF', 'CF', 'RF'], default='')
        x['p'] = zone
        s = x[x.p != ''].assign(saved=lambda q: (q.xw - q.w) / SCALE).groupby(['team', 'p']).saved.sum().reset_index()
        s['y'] = y
        out.append(s)
    return pd.concat(out, ignore_index=True)


def main():
    sv, fg, inn = pull()
    print('MLB API rows per club?', inn[(inn.y == 2025) & (inn.p == 'SS')].groupby('id').team.nunique().max())
    tot = inn.groupby(['id', 'y', 'p']).inn.sum().rename('inn').reset_index()
    main_team = inn.sort_values('inn').groupby(['id', 'y', 'p']).team.last().rename('team').reset_index()
    m = tot.merge(main_team, on=['id', 'y', 'p']).merge(sv, on=['id', 'y', 'p'], how='left').merge(fg, on=['id', 'y', 'p'], how='left')
    # The even blend of the two systems that both repeat. Even is a convention, not fitted.
    m['blend'] = (m.sv_total + m.DRS) / 2
    M = {'IF': ['sv_range', 'sv_total', 'DRS', 'UZR', 'blend'], 'OF': ['sv_range', 'sv_total', 'DRS', 'UZR', 'blend'], 'C': ['sv_total', 'sv_frame', 'sv_block', 'sv_throw', 'DRS', 'rSZ', 'rSB', 'blend']}
    res = {'A': {}, 'B': {}}
    print('\nTest A: year-to-year r on runs per 1,000 innings (4 pairs), all / club-changers (n pairs)')
    for p in POS:
        ms = M['C'] if p == 'C' else (M['OF'] if p in ('LF', 'CF', 'RF') else M['IF']) + (['sv_rec'] if p == '1B' else [])
        q = m[m.p == p]
        for k in ms:
            a = q[(q.inn >= 200) & q[k].notna()]
            j = a.assign(y=a.y + 1).merge(a, on=['id', 'y', 'p'], suffixes=('', '_n'))
            w = 2 / (1 / j.inn + 1 / j.inn_n)
            ra, rb = j[k] / j.inn * 1000, j[k + '_n'] / j.inn_n * 1000
            sw = j.team != j.team_n
            res['A'][f'{p}|{k}'] = {'all': wr(ra, rb, w), 'n': len(j), 'sw': wr(ra[sw], rb[sw], w[sw]), 'n_sw': int(sw.sum())}
            print(f"  {p:3s} {k:9s} {res['A'][f'{p}|{k}']['all']:+.2f} ({len(j):3d})   {res['A'][f'{p}|{k}']['sw']:+.2f} ({int(sw.sum()):3d})", flush=True)
    t = club_targets(inn)
    print('\nTest B: Y rating x Y+1 innings against the club zone runs saved in Y+1 (club-seasons), r by pair, mean')
    for p in ('1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF'):
        for k in ('sv_range', 'sv_total', 'DRS', 'UZR', 'blend'):
            rs = []
            for y0, y1 in zip(YEARS, YEARS[1:]):
                rate = m[(m.p == p) & (m.y == y0) & (m.inn >= 50) & m[k].notna()].copy()
                if len(rate) < 20:
                    rs.append(np.nan)
                    continue
                rate['rate'] = rate[k] / rate.inn
                e = inn[(inn.y == y1) & (inn.p == p)].merge(rate[['id', 'rate']], on='id', how='left').fillna({'rate': 0.0})
                x = (e.rate * e.inn).groupby(e.team).sum().rename('x')
                yy = t[(t.y == y1) & (t.p == p)].set_index('team').saved
                c = pd.concat([x, yy], axis=1).dropna()
                rs.append(float(np.corrcoef(c.x, c.saved)[0, 1]))
            res['B'][f'{p}|{k}'] = rs
            print(f"  {p:3s} {k:9s} {[None if np.isnan(v) else round(v, 2) for v in rs]}  {np.nanmean(rs):+.3f}", flush=True)
    with open(os.path.join(OUT, 'results.json.tmp'), 'w') as fo:
        json.dump(res, fo, indent=1)
    os.replace(os.path.join(OUT, 'results.json.tmp'), os.path.join(OUT, 'results.json'))


if __name__ == '__main__':
    main()
