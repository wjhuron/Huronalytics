"""fa_upside_rankings.py: the second free-agent ranking, direct weight on full-time value and upside (per Wally 2026-11-05). Research only.
Score = .4 E/sdE + .3 F/sdF + .3 U/sdU, parts and SDs from fa_upside_blend.py. The weights are a CONVENTION: no optimum exists (see the log; r falls steadily as E's share falls and top-decile capture is flat).
U for relievers at 2027 and 3 years adds Stuff+ history (fa_upside_stuff_test.py wins 4/4 and 3/3); starters and hitters do not, and the 5-year fit has no replicate for it.
List end (a convention): the score a floor player typically has, the group-wide line of score on E read at E = floor x term; over 30 listed, the largest drop between ranks 15 and 30.
Usage: python3 scripts/research/projection/fa_upside_rankings.py
Output: data/_proj/_fa_upside_rankings.json
"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fa_upside_blend as U
B = U.B; P = B.P
W = (.4, .3, .3); FLOOR = {'H': .2, 'SP': .2, 'RP': .1}; KEY = {1: 'B', 3: 'v3', 5: 'v5'}; HZ = {1: '2027', 3: '2027-2029', 5: '2027-2031'}
d = json.load(open(os.path.join(P, '_fa_position_rankings.json'))); J = json.load(open(os.path.join(P, '_fa_upside_blend.json'))); JS = json.load(open(os.path.join(P, '_fa_upside_stuff.json')))
stuff = json.load(open(os.path.join(B.ROOT, 'data', '_era_internal_stuff.json'))); stuff['2026'] = json.load(open(os.path.join(P, 'stuff_2026_loso.json')))
print('stuff 2026 sample', list(stuff['2026'].items())[:1], len(stuff['2026']))


def ch(pid):
    n = q = 0.0
    for k in range(3):
        v = stuff.get(str(2026 - k), {}).get(str(pid))
        if v and v.get('stuff_full') is not None:
            n += .7 ** k * v['n_full'] * v['stuff_full']; q += .7 ** k * v['n_full']
    return n / (q + 250) * 100


rows = d['all_h'] + d['all_p']
for r in rows:
    g = r['group']; a = r['age'] - 30.0
    for h in (1, 3, 5):
        E = r[KEY[h]]; F = U.aged_sum(r['rate'], r['age'], g, h)
        x = [1.0, r['B'], r['B'] * a, r['rate'], r['rate'] * a, a]
        if g == 'RP' and h in (1, 3):
            x.append(ch(r['mlbId'])); c = JS[f'RP_{h}']['qcoef']
        else:
            c = J[f'{g}_{h}']['qcoef']
        Up = float(np.dot(x, c)); sd = J[f'{g}_{h}']['sd']
        r[f'E{h}'], r[f'F{h}'], r[f'U{h}'] = E, F, Up
        r[f'S{h}'] = W[0] * E / sd[0] + W[1] * F / sd[1] + W[2] * Up / sd[2]
    r['stuffch'] = ch(r['mlbId']) if g != 'H' else None

cut = {}
for g in ('H', 'SP', 'RP'):
    G = [r for r in rows if r['group'] == g]
    for h in (1, 3, 5):
        b = np.polyfit([r[f'E{h}'] for r in G], [r[f'S{h}'] for r in G], 1); cut[f'{g}_{h}'] = float(np.polyval(b, FLOOR[g] * h))


def end(src, g, h):
    k = f'S{h}'; R = sorted(src, key=lambda r: -r[k]); keep = [r for r in R if r[k] >= cut[f'{g}_{h}']]
    if len(keep) <= 30:
        return keep
    v = [r[k] for r in keep]; gaps = [(v[i - 1] - v[i], i) for i in range(15, 30)]
    return keep[:max(gaps)[1]]


INF = {'1B', '2B', '3B', 'SS'}; OF = {'LF', 'CF', 'RF'}
defs = [('Starting pitchers', 'SP', lambda r: r['group'] == 'SP'), ('Relief pitchers', 'RP', lambda r: r['group'] == 'RP'), ('Catchers', 'H', lambda r: 'C' in r['pos']), ('First base', 'H', lambda r: '1B' in r['pos']), ('Second base', 'H', lambda r: '2B' in r['pos']), ('Third base', 'H', lambda r: '3B' in r['pos']), ('Shortstop', 'H', lambda r: 'SS' in r['pos']), ('All infielders', 'H', lambda r: set(r['pos']) & INF), ('Left field', 'H', lambda r: 'LF' in r['pos']), ('Center field', 'H', lambda r: 'CF' in r['pos']), ('Right field', 'H', lambda r: 'RF' in r['pos']), ('All outfielders', 'H', lambda r: set(r['pos']) & OF)]
L = {}
for nm, g, t in defs:
    src = [r for r in rows if r['group'] == g and t(r)]; L[nm] = {HZ[h]: end(src, g, h) for h in (1, 3, 5)}
json.dump(dict(lists=L, cut=cut, weights=W, all=rows), open(os.path.join(P, '_fa_upside_rankings.json'), 'w'), default=float)
print('cuts', {k: round(v, 2) for k, v in cut.items()})
for nm, hs in L.items():
    print(f'\n== {nm}')
    wl = d['lists'][nm]
    for hz, R in hs.items():
        k = {'2027': 1, '2027-2029': 3, '2027-2031': 5}[hz]; wr = {x['mlbId']: i + 1 for i, x in enumerate(sorted(wl[hz], key=lambda q: -q[KEY[k]]))}
        print(f'  {hz} ({len(R)}): ' + ', '.join(f"{r['name'].split(',')[0]}{'^' if r.get('rate_note') else ''}[{wr.get(r['mlbId'], '-')}] {r[f'S{k}']:.2f}" for r in R))
