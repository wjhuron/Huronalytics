"""ss_to_2b_conversion.py: how many fielding runs a shortstop gains when he plays second base.

Within-player, same-season design: every infielder with innings at BOTH shortstop and second base
in one season. Savant's per-position Outs Above Average leaderboard (fielding_runs_prevented at that
position, measured against the average fielder AT that position) divided by his MLB innings there
(MLB Stats API fielding splits), scaled to a full season (1458 innings). The difference, 2B rate
minus SS rate, is how much easier second base reads for the same glove. The positional adjustment
exists to cancel that gap, so the comparison is with the shipped hWAR table (SS 3.32, 2B 0.47 runs per
1458 innings, a 2.85-run gap) and fWAR's (7.5 and 2.5, a 5-run gap).

Pairs weight by the harmonic mean of the two inning totals (the noise of a difference of two rates).
Seasons 2021-2026, each reported on its own, plus a minimum-innings sweep (the floor trades pairs for
noise and has no optimum; every floor is shown).

Usage: python3 scripts/research/fielding/ss_to_2b_conversion.py
Output: console + data/_fielding_battery/ss_to_2b_conversion.json (scratch)
"""
import csv
import io
import json
import math
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT = os.path.join(ROOT, 'data', '_fielding_battery')
SEASONS = range(2021, 2027)
OAA = ('https://baseballsavant.mlb.com/leaderboard/outs_above_average?type=Fielder&startYear={y}&endYear={y}'
       '&split=no&team=&range=year&min=1&pos={p}&roles=&viz=hide&csv=true')
FLD = ('https://statsapi.mlb.com/api/v1/stats?stats=season&group=fielding&season={y}&sportId=1'
       '&playerPool=All&limit=10000&gameType=R')
FULL = 1458.0
FLOORS = (50, 100, 150, 200, 300)


def fetch(url, path):
    if os.path.exists(path):
        return open(path, encoding='utf-8-sig').read()
    r = subprocess.run(['curl', '-sfL', '--retry', '3', '-A', 'huronalytics-research/1.0', url], capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f'fetch failed ({r.returncode}): {url}')
    txt = r.stdout.decode('utf-8-sig')
    tmp = path + '.tmp'
    open(tmp, 'w', encoding='utf-8').write(txt)
    os.replace(tmp, path)
    return txt


def oaa_runs(y, pos):
    txt = fetch(OAA.format(y=y, p=pos), os.path.join(OUT, f'oaa_{y}_pos{pos}.csv'))
    out = {}
    for r in csv.DictReader(io.StringIO(txt)):
        v = r.get('fielding_runs_prevented')
        if v not in (None, ''):
            out[r['player_id']] = float(v)
    if len(out) < 30:
        raise SystemExit(f'OAA {y} pos {pos}: only {len(out)} rows')
    return out


def innings(y):
    js = json.loads(fetch(FLD.format(y=y), os.path.join(OUT, f'fielding_innings_{y}.json')))
    out = {}
    for s in js['stats'][0]['splits']:
        p = s['position']['abbreviation']
        if p in ('SS', '2B'):
            inn = float(s['stat'].get('innings') or 0)
            k = (str(s['player']['id']), p)
            out[k] = out.get(k, 0.0) + inn
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    pairs = []
    for y in SEASONS:
        ss, b2, inn = oaa_runs(y, 6), oaa_runs(y, 4), innings(y)
        for pid in set(ss) & set(b2):
            i_ss, i_2b = inn.get((pid, 'SS'), 0.0), inn.get((pid, '2B'), 0.0)
            if i_ss > 0 and i_2b > 0:
                pairs.append({'y': y, 'pid': pid, 'i_ss': i_ss, 'i_2b': i_2b,
                              'gain': FULL * (b2[pid] / i_2b - ss[pid] / i_ss),
                              'w': 2 * i_ss * i_2b / (i_ss + i_2b)})

    def summary(ps):
        sw = sum(p['w'] for p in ps)
        m = sum(p['w'] * p['gain'] for p in ps) / sw
        # weighted SE through the effective sample size
        var = sum(p['w'] * (p['gain'] - m) ** 2 for p in ps) / sw
        neff = sw ** 2 / sum(p['w'] ** 2 for p in ps)
        return m, math.sqrt(var / neff), len(ps)

    res = {'floors': {}, 'seasons': {}}
    print('Floor sweep (innings at EACH position), all seasons pooled:')
    for f in FLOORS:
        ps = [p for p in pairs if p['i_ss'] >= f and p['i_2b'] >= f]
        m, se, n = summary(ps)
        res['floors'][f] = {'gain': m, 'se': se, 'n': n}
        print(f'  >= {f:3d} inn: {n:3d} pairs  gain {m:+.2f} runs / 1458 inn  (SE {se:.2f})')
    f = 100
    print(f'By season at >= {f} innings:')
    for y in SEASONS:
        ps = [p for p in pairs if p['y'] == y and p['i_ss'] >= f and p['i_2b'] >= f]
        if len(ps) >= 5:
            m, se, n = summary(ps)
            res['seasons'][y] = {'gain': m, 'se': se, 'n': n}
            print(f'  {y}: {n:3d} pairs  gain {m:+.2f}  (SE {se:.2f})')
    print('Positional gap SS - 2B: hWAR table 2.85, fWAR 5.0 runs / 1458 inn')
    tmp = os.path.join(OUT, 'ss_to_2b_conversion.json.tmp')
    json.dump(res, open(tmp, 'w'), indent=1)
    os.replace(tmp, os.path.join(OUT, 'ss_to_2b_conversion.json'))


if __name__ == '__main__':
    main()
