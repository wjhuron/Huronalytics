"""replacement_level_check.py: does the WAR replacement convention (1000 wins per 2430 games, 57/43) match the talent teams get for nothing? (2026-11-05). Research only.
Pool: free agents who signed MINOR-LEAGUE deals for season Y (data/_fa_contracts/dataset.csv, outcome 'milb', Y 2021-2026; 2020 lacks most MiLB deals).
If the convention is right, that pool should sit near 0 WAR per unit of playing time in season Y.
Measures: fWAR per 600 PA (hitters) and per 180 IP / 60 IP (pitchers by role), playing-time weighted, for the signees who reached MLB; 2026 also on hdWAR from the site leaderboard.
Comparison: the same rate for every MLB player. SE: bootstrap over players.
Usage: python3 scripts/research/hitter/replacement_level_check.py
"""
import csv, json, os
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
P = os.path.join(ROOT, 'data', '_proj', 'fg')
rows = [r for r in csv.DictReader(open(os.path.join(ROOT, 'data', '_fa_contracts', 'dataset.csv'))) if r['mlbam'] and r['Y'] >= '2021']
def ip(v):
    v = float(v or 0); return int(v) + (v - int(v)) * 10 / 3
def act(y, side):
    k = 162 / 60 if y == 2020 else 1
    return {int(r['xMLBAMID']): r for r in json.load(open(os.path.join(P, f'actual_{y}_{side}.json'))) if r.get('xMLBAMID')}
rng = np.random.default_rng(0)
def rate(pairs, unit):
    w = np.array([p for _, p in pairs]); v = np.array([x for x, _ in pairs])
    r = v.sum() / w.sum() * unit
    bs = [v[ix].sum() / w[ix].sum() * unit for ix in (rng.integers(0, len(v), len(v)) for _ in range(2000))]
    return r, float(np.std(bs)), len(v), float(w.sum())
out = {}
for role, side, unit, key in (('H', 'bat', 600, 'PA'), ('SP', 'pit', 180, 'IP'), ('RP', 'pit', 60, 'IP')):
    print(f'\n== {role}: fWAR per {unit} {key}')
    allp = []
    for oc in ('milb', 'mlb'):
        pairs = []; per = {}; n_sig = 0
        for y in range(2021, 2027):
            A = act(y, side); sig = [r for r in rows if r['Y'] == str(y) and r['outcome'] == oc and r['role'] == role]; n_sig += len(sig); py = []
            for r in sig:
                a = A.get(int(float(r['mlbam'])))
                if a:
                    pt = float(a['PA'] or 0) if side == 'bat' else ip(a['IP'])
                    if pt > 0:
                        py.append((float(a['WAR'] or 0), pt))
            pairs += py
            if py:
                per[y] = (sum(x for x, _ in py) / sum(p for _, p in py) * unit, len(py))
        r, se, n, pt = rate(pairs, unit)
        print(f'  {oc} signees: {r:+.2f} (SE {se:.2f}), {n} of {n_sig} reached MLB, {pt:.0f} {key}; by season ' + ' '.join(f'{y}:{v[0]:+.2f}/{v[1]}' for y, v in per.items()))
        out[f'{role}_{oc}'] = dict(rate=r, se=se, n=n, pt=pt, per=per)
    pairs = []
    for y in range(2021, 2027):
        for a in act(y, side).values():
            pt = float(a['PA'] or 0) if side == 'bat' else ip(a['IP'])
            if pt > 0 and (side == 'bat' or ((float(a.get('GS') or 0) / float(a.get('G') or 1) >= .5) == (role == 'SP'))):
                pairs.append((float(a['WAR'] or 0), pt))
    r, se, n, pt = rate(pairs, unit); print(f'  every MLB player: {r:+.2f}')
# 2026 on hdWAR
d = json.load(open(os.path.join(ROOT, 'data', 'hitter_leaderboard_rs.json'))); H = d if isinstance(d, list) else next(iter(d.values()))
best = {}
for r in H:
    if r.get('team') not in ('ROC', 'AAA') and r.get('mlbId') is not None and (r['mlbId'] not in best or (r.get('pa') or 0) > (best[r['mlbId']].get('pa') or 0)):
        best[r['mlbId']] = r
sig = {int(float(r['mlbam'])) for r in rows if r['Y'] == '2026' and r['outcome'] == 'milb' and r['role'] == 'H'}
pairs = [(best[i]['hWAR'], best[i]['pa']) for i in sig if i in best and best[i].get('hWAR') is not None and (best[i].get('pa') or 0) > 0]
r, se, n, pt = rate(pairs, 600); print(f'\n2026 hitters on hdWAR: minor-league signees {r:+.2f} per 600 PA (SE {se:.2f}, n {n}, {pt:.0f} PA)')
json.dump(out, open(os.path.join(ROOT, 'data', '_replacement_check.json'), 'w'), indent=1, default=float)
