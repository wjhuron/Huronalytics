"""wed_rpw_marginal.py - test 17c: the marginal run, 2000-2026. One more run in a random game is half a win when it
breaks a regulation tie or makes one: wins per run = .5 P(tied after regulation) + .5 P(one run behind). This is the
slope of wins on runs for a club near .500, which is what a player's runs above average are. The club regression of
wed_rpw.py is a chord across clubs from -300 to +300 runs. Validation: in 2000-2009 the formula at .287 matched the
club records, so the marginal value must sit near it there.
.venv/bin/python scripts/research/war_era_deep_dive/wed_rpw_marginal.py"""
import os, json
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
D = os.path.join(ROOT, 'data', '_wed', 'rpw'); SHIP = 0.287
rows = []
for y in range(2000, 2027):
    j = json.load(open(os.path.join(D, f'sc_{y}.json'))); seen = set()
    for dt in j['dates']:
        for gm in dt['games']:
            ls = gm.get('linescore', {}); inn = ls.get('innings', []); si = ls.get('scheduledInnings', 9)
            if gm.get('status', {}).get('codedGameState') != 'F' or gm['gamePk'] in seen or len(inn) < min(si, 5):
                continue
            seen.add(gm['gamePk'])
            h9 = sum(i['home'].get('runs', 0) or 0 for i in inn if i['num'] <= si); a9 = sum(i['away'].get('runs', 0) or 0 for i in inn if i['num'] <= si)
            rows.append(dict(y=y, d9=h9 - a9, d=gm['teams']['home']['score'] - gm['teams']['away']['score'], rs=(gm['teams']['home']['score'] + gm['teams']['away']['score']) / 2, r9=(h9 + a9) / 2, extra=int(len(inn) > si)))
G = pd.DataFrame(rows)


def one(g):
    n = len(g); pt = (g.d9 == 0).mean(); p1 = (g.d9.abs() == 1).mean(); wpr = .5 * pt + .25 * p1      # mean of the home and away sides
    se = np.sqrt(((.5 * (g.d9 == 0) + .25 * (g.d9.abs() == 1)).var()) / n); r = g.rs.mean()
    return n, pt, p1, 1 / wpr, se / wpr ** 2, r, 4 * r / (2 * r) ** SHIP, np.log(4 * r * wpr) / np.log(2 * r), g.r9.mean()


print("season | games | tied after regulation | one-run regulation margin | marginal runs per win (SE) | formula at .287 | exponent the marginal value needs | R/G all, regulation only")
per = {}
for y, g in G.groupby('y'):
    n, pt, p1, rpw, se, r, f, e, r9 = one(g); per[y] = (rpw, f, e)
    print(f"   {y}: {n} | {pt:.3f} | {p1:.3f} | {rpw:5.2f} ({se:.2f}) | {f:.2f} | {e:.3f} | {r:.2f} {r9:.2f}")
print("\nera | marginal runs per win (SE) | mean formula | ratio | needed exponent: mean over seasons (SE) | seasons marginal > formula")
for nm, ys in (('2000-2009', range(2000, 2010)), ('2010-2019', range(2010, 2020)), ('2021-2026', range(2021, 2027)), ('2000-2019', range(2000, 2020))):
    g = G[G.y.isin(list(ys))]; n, pt, p1, rpw, se, r, f, e, r9 = one(g); es = np.array([per[y][2] for y in ys]); fm = np.mean([per[y][1] for y in ys])
    print(f"   {nm}: {rpw:.2f} ({se:.2f}) | {fm:.2f} | {rpw / fm:.3f} | {es.mean():.3f} ({es.std(ddof=1) / np.sqrt(len(es)):.3f}) | {sum(per[y][0] > per[y][1] for y in ys)}/{len(list(ys))}")
print("\nthe marginal value with the run environment held out: regression of ln(marginal RPW) on ln(R/G) over 26 seasons (the formula's own shape is RPW = 4r / (2r)^e)")
ys = [y for y in per if y != 2020]; lr = np.log([G[G.y == y].rs.mean() for y in ys]); lw = np.log([per[y][0] for y in ys]); t = np.array([y - 2013 for y in ys])
X = np.c_[np.ones(len(ys)), lr, t]; co, *_ = np.linalg.lstsq(X, lw, rcond=None); res = lw - X @ co; cov = (res ** 2).sum() / (len(ys) - 3) * np.linalg.inv(X.T @ X)
print(f"   ln RPW = {co[0]:.3f} + {co[1]:.3f} ln r + {co[2]:.4f} per year (SE {np.sqrt(cov[2, 2]):.4f}, z {co[2] / np.sqrt(cov[2, 2]):.1f}); the formula's slope on ln r is {1 - SHIP:.3f}")
