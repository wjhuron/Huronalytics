"""wed_rpw.py - WAR/ERA deep dive, test 17b: runs per win. hdWAR divides runs by RPW = 4r / (2r)^WAR_PYTH_EXP
(.287, a published convention). Test 17 read 10.70 on 2021-2026 club records against the formula's 9.5.

A  club-seasons 2000-2026 (standings feed): slope of W% - .5 on run differential per game, per season and per era;
   the exponent e that the code's own form needs; leave-one-season-out error of each choice.
B  sweep of e (the code's linear form and the team-level PythagenPat form), by era.
C  games 2021-2026 (line scores): regulation and extra-inning run differential apart, a margin cap curve, and
   the marginal value of one more run in a random game (half a win when it breaks a regulation tie or makes one).
Data: data/_wed/rpw/st_Y.json, sc_Y.json (MLB Stats API). .venv/bin/python scripts/research/war_era_deep_dive/wed_rpw.py"""
import os, json
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
D = os.path.join(ROOT, 'data', '_wed', 'rpw'); SHIP = 0.287
RES = {}


def standings(y):
    j = json.load(open(os.path.join(D, f'st_{y}.json'))); rows = []
    for rec in j['records']:
        for t in rec['teamRecords']:
            rows.append(dict(y=y, club=t['team']['id'], w=t['wins'], l=t['losses'], rs=t['runsScored'], ra=t['runsAllowed']))
    return rows


S = pd.DataFrame([r for y in range(2000, 2027) for r in standings(y)])
S['g'] = S.w + S.l; S['wp'] = S.w / S.g - 0.5; S['rd'] = (S.rs - S.ra) / S.g
S['r'] = S.groupby('y').rs.transform('sum') / S.groupby('y').g.transform('sum')      # league runs per team game
assert S.groupby('y').size().eq(30).all()


def slope(x, y):
    b = float((x * y).sum() / (x * x).sum()); res = y - b * x
    return b, float(np.sqrt((res ** 2).sum() / (len(x) - 1) / (x * x).sum()))


def rpw_form(r, e):
    return 4 * r / (2 * r) ** e


print("A. per season: league R/G | direct runs per win (SE) | formula at .287 | exponent the linear form needs | best team-level PythagenPat exponent")
EG = np.round(np.arange(0.18, 0.341, 0.005), 3); per = {}
for y, g in S.groupby('y'):
    b, se = slope(g.rd.values, g.wp.values); r = float(g.r.iloc[0]); rpw = 1 / b
    e_lin = np.log(4 * r / rpw) / np.log(2 * r)
    def pyth(e):
        x = ((g.rs + g.ra) / g.g) ** e; return float((((g.rs ** x / (g.rs ** x + g.ra ** x)) - g.w / g.g) ** 2).mean())
    e_py = EG[int(np.argmin([pyth(e) for e in EG]))]
    per[y] = dict(r=r, rpw=rpw, se=se / b ** 2, e_lin=float(e_lin), e_py=float(e_py))
    print(f"   {y}: {r:.2f} | {rpw:5.2f} ({se / b ** 2:.2f}) | {rpw_form(r, SHIP):.2f} | {e_lin:.3f} | {e_py:.3f}")
ERAS = {'2000-2009': range(2000, 2010), '2010-2019': range(2010, 2020), '2021-2026': range(2021, 2027), '2000-2019': range(2000, 2020), '2000-2026 no 2020': [y for y in range(2000, 2027) if y != 2020]}
print("\nera: club-seasons | pooled direct runs per win (SE) | mean formula value at .287 | ratio | mean needed exponent (SE of the mean over seasons) | seasons with direct > formula")
for nm, ys in ERAS.items():
    g = S[S.y.isin(list(ys))]; b, se = slope(g.rd.values, g.wp.values); f = float(np.mean([rpw_form(per[y]['r'], SHIP) for y in ys])); el = np.array([per[y]['e_lin'] for y in ys])
    print(f"   {nm}: {len(g)} | {1 / b:.2f} ({se / b ** 2:.2f}) | {f:.2f} | {1 / b / f:.3f} | {el.mean():.3f} ({el.std(ddof=1) / np.sqrt(len(el)):.3f}) | {sum(per[y]['rpw'] > rpw_form(per[y]['r'], SHIP) for y in ys)}/{len(list(ys))}")
    RES[nm] = dict(rpw=1 / b, se=se / b ** 2, formula=f, e=float(el.mean()))

print("\nB. exponent sweep, the code's form (W% - .5 = RD per game / (4r / (2r)^e)). RMSE in wins per 162, by era")
print("   e     | " + " | ".join(ERAS))
cur = {nm: [] for nm in ERAS}
for e in EG:
    row = []
    for nm, ys in ERAS.items():
        g = S[S.y.isin(list(ys))]; v = 162 * float(np.sqrt(((g.wp - g.rd / rpw_form(g.r, e)) ** 2).mean())); cur[nm].append(v); row.append(f"{v:.3f}")
    print(f"   {e:.3f} | " + " | ".join(row))
for nm in ERAS:
    i = int(np.argmin(cur[nm])); flat = [float(EG[k]) for k in range(len(EG)) if cur[nm][k] <= cur[nm][i] * 1.002]
    print(f"   {nm}: best e {EG[i]:.3f} ({'interior' if 0 < i < len(EG) - 1 else 'GRID EDGE'}), within 0.2% of the best: {min(flat):.3f}-{max(flat):.3f}; .287 costs {100 * (cur[nm][list(EG).index(0.285)] / cur[nm][i] - 1):.1f}% RMSE (at .285)")
    RES[nm]['best_e'] = float(EG[i])

print("\nleave-one-season-out, 2021-2026 and 2000-2026: e fitted on the other seasons of the pool, error on the held-out season (wins per 162)")
for nm in ('2021-2026', '2000-2026 no 2020'):
    ys = list(ERAS[nm]); win = 0; out = []
    for h in ys:
        tr = S[S.y.isin([y for y in ys if y != h])]; e_fit = EG[int(np.argmin([((tr.wp - tr.rd / rpw_form(tr.r, e)) ** 2).mean() for e in EG]))]
        ho = S[S.y == h]; a = 162 * float(np.sqrt(((ho.wp - ho.rd / rpw_form(ho.r, e_fit)) ** 2).mean())); s = 162 * float(np.sqrt(((ho.wp - ho.rd / rpw_form(ho.r, SHIP)) ** 2).mean()))
        win += a < s; out.append(f"{h}:{e_fit:.3f} {a:.2f}/{s:.2f}")
    print(f"   {nm}: fitted beats .287 in {win}/{len(ys)} held-out seasons | " + (" ".join(out) if len(ys) <= 6 else " ".join(out[-8:])))
    RES[nm]['loso_wins'] = f"{win}/{len(ys)}"

print("\nC. games 2021-2026")
G = []
for y in range(2021, 2027):
    j = json.load(open(os.path.join(D, f'sc_{y}.json'))); seen = set()
    for dt in j['dates']:
        for gm in dt['games']:
            if gm.get('status', {}).get('codedGameState') != 'F' or gm['gamePk'] in seen:
                continue
            ls = gm.get('linescore', {}); inn = ls.get('innings', []); si = ls.get('scheduledInnings', 9)
            if not inn:
                continue
            seen.add(gm['gamePk'])
            h9 = sum(i['home'].get('runs', 0) or 0 for i in inn if i['num'] <= si); a9 = sum(i['away'].get('runs', 0) or 0 for i in inn if i['num'] <= si)
            hs, as_ = gm['teams']['home']['score'], gm['teams']['away']['score']
            assert hs == sum(i['home'].get('runs', 0) or 0 for i in inn) and as_ == sum(i['away'].get('runs', 0) or 0 for i in inn)
            for side, opp, me9, op9, me, op in (('home', 'away', h9, a9, hs, as_), ('away', 'home', a9, h9, as_, hs)):
                G.append(dict(y=y, club=gm['teams'][side]['team']['id'], win=int(me > op), rd=me - op, rd9=me9 - op9, rdx=(me - op) - (me9 - op9), extra=int(len(inn) > si), rs=me))
G = pd.DataFrame(G)
print(f"   games {len(G) // 2}; extra-inning share {G.extra.mean():.3f}; runs per team game {G.rs.mean():.3f}; of those, runs after regulation {(G.rs.sum() - (G.rs - 0).sum() + G[G.extra == 1].rdx.abs().sum()) / len(G):.3f} (abs margin made in extras per team game)")
T = G.groupby(['y', 'club']).agg(g=('win', 'size'), w=('win', 'sum'), rd=('rd', 'sum'), rd9=('rd9', 'sum'), rdx=('rdx', 'sum')).reset_index()
T['wp'] = T.w / T.g - .5
chk = T.merge(S[['y', 'club', 'w', 'g']], on=['y', 'club'], suffixes=('', '_st')); print(f"   check against standings: wins equal in {(chk.w == chk.w_st).sum()}/{len(chk)} club-seasons")
b, se = slope((T.rd / T.g).values, T.wp.values); print(f"   all runs: runs per win {1 / b:.2f} ({se / b ** 2:.2f})")
X = np.c_[T.rd9 / T.g, T.rdx / T.g]; co, *_ = np.linalg.lstsq(X, T.wp.values, rcond=None); res = T.wp.values - X @ co; cov = (res ** 2).sum() / (len(T) - 2) * np.linalg.inv(X.T @ X)
print(f"   two terms: regulation differential {1 / co[0]:.2f} runs per win (SE {np.sqrt(cov[0, 0]) / co[0] ** 2:.2f}); extra-inning differential {1 / co[1]:.2f} runs per win (SE {np.sqrt(cov[1, 1]) / co[1] ** 2:.2f})")
print("   margin cap (each game's run differential clipped at +/- c): runs per win, RMSE in wins per 162")
for c in (1, 2, 3, 4, 5, 6, 8, 10, 15, 99):
    t = G.assign(rc=G.rd.clip(-c, c)).groupby(['y', 'club']).agg(g=('win', 'size'), w=('win', 'sum'), rc=('rc', 'sum')); x = (t.rc / t.g).values; yv = (t.w / t.g - .5).values; b, se = slope(x, yv)
    print(f"      cap {c:2d}: {1 / b:5.2f} | {162 * np.sqrt(((yv - b * x) ** 2).mean()):.2f}")
print("   marginal run in a random game, regulation scores: a run is half a win when it breaks a tie or makes one")
h = G  # both sides
for y, g in list(h.groupby('y')) + [('all', h)]:
    p_tie = (g.rd9 == 0).mean(); p_m1 = (g.rd9 == -1).mean(); p_p1 = (g.rd9 == 1).mean()
    add = .5 * p_tie + .5 * p_m1; sub = .5 * p_tie + .5 * p_p1; n = len(g) / 2; se_add = np.sqrt((p_tie + p_m1) * (1 - p_tie - p_m1) / n) * .5
    r = g.rs.mean(); print(f"      {y}: tied after regulation {p_tie:.3f}, one-run regulation margin {p_m1 + p_p1:.3f} | wins per added run {add:.4f} -> {1 / add:.2f} runs per win (SE {se_add / add ** 2:.2f}) | formula at .287: {rpw_form(r, SHIP):.2f}")
    RES[f'marg_{y}'] = 1 / add
json.dump(RES, open(os.path.join(ROOT, 'data', '_wed', 'res_rpw.json'), 'w'), indent=1)
