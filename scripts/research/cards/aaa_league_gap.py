"""International League against Pacific Coast League, 2026: does one AAA pool misrank hitters?
Every hitter joins his last AAA club's league. Read the mean gap and how far ranks move inside a
league. Run from the repo root."""
import json, os, sys
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.chdir(ROOT)
PCL = {'ABQ', 'ELP', 'LV', 'OKC', 'RNO', 'RR', 'SAC', 'SL', 'SUG', 'TAC'}
pool = json.load(open('data/_milb2026/hitter_pool_AAA.json'))
fg = json.load(open('data/_milb2026/fg_hitters_level1.json'))
clubs = sorted({v['club'] for v in pool.values()})
print(len(clubs), clubs)
unknown = [c for c in clubs if c not in PCL]
print('PCL found', sorted(PCL & set(clubs)), 'missing', sorted(PCL - set(clubs)), 'IL count', len(unknown))
rows = []
for mid, v in pool.items():
    l = (fg.get(mid) or {}).get('line') or {}
    rows.append({**v, 'lg': 'PCL' if v['club'] in PCL else 'IL', 'fgw': l.get('wOBA'), 'wrc': l.get('wRC+'),
                 'babip': l.get('BABIP'), 'iso': l.get('ISO'), 'fgpa': l.get('PA') or 0, 'mid': mid})
KEYS = [('fgw', 0), ('wrc', 0), ('babip', 0), ('iso', 0), ('xwOBA', 0), ('barrelPct', 0), ('hardHitPct', 0), ('ev95', 0),
        ('airPullPct', 0), ('gbPct', 1), ('kPct', 1), ('bbPct', 0), ('izSwChase', 0), ('izContactPct', 0), ('bbPlusNoBat', 0),
        ('ctPlus', 0), ('sdPlus', 0), ('processPlus', 0)]
def wm(xs):
    v = np.array([x[0] for x in xs], float); w = np.array([x[1] for x in xs], float)
    return (v * w).sum() / w.sum()
print(f"{'stat':<14}{'IL':>9}{'PCL':>9}{'gap':>9}{'gap/SD':>8}{'mean |rank move|':>18}{'max':>6}")
for k, inv in KEYS:
    a = [r for r in rows if r.get(k) is not None and (r.get('pa') or 0) > 0]
    il = [(r[k], r['pa']) for r in a if r['lg'] == 'IL']; pc = [(r[k], r['pa']) for r in a if r['lg'] == 'PCL']
    q = [r for r in a if r['pa'] >= 100]
    sd = np.std([r[k] for r in q])
    allv = np.array([r[k] for r in a], float)
    moves = []
    for r in q:
        same = np.array([x[k] for x in a if x['lg'] == r['lg']], float)
        moves.append(abs((allv < r[k]).mean() - (same < r[k]).mean()) * 100)
    g = wm(pc) - wm(il)
    print(f"{k:<14}{wm(il):9.3f}{wm(pc):9.3f}{g:9.3f}{g / sd:8.2f}{np.mean(moves):18.1f}{max(moves):6.0f}")
print('PA', {lg: sum(r['pa'] or 0 for r in rows if r['lg'] == lg) for lg in ('IL', 'PCL')}, 'hitters',
      {lg: sum(r['lg'] == lg for r in rows) for lg in ('IL', 'PCL')})
fu = pool['801501']; print('Furman club', fu['club'])
for k, _ in KEYS:
    rs = [r for r in rows if r.get(k) is not None]
    me = [r for r in rs if r['mid'] == '801501']
    if me:
        v = me[0][k]; a = np.mean([x[k] < v for x in rs]) * 100; b = np.mean([x[k] < v for x in rs if x['lg'] == 'PCL']) * 100
        print(f'  {k:<14}{v:8.3f}  all AAA {a:4.0f}  PCL {b:4.0f}')
