"""war_honest_followup.py: what the honest forecast tests left open (2026-11-04). Research only.

1. BLEND SE: hd + w (xfip - hd) at the swept optimum against w = 0, paired bootstrap, honest next and ros; and the same
   blend on the club description (club RA above league on summed runs, FRV, park). xFIP carries no HR outcome, so a move
   toward it cannot win that fit by copying results; a move toward FIP can, so FIP is shown as a labeled diagnostic only.
2. VELOCITY, the retest held on 2026-09-05 until 2026 was a complete replicate. xw + k x (LOSO band delta per BIP), LOSO over
   2021-2026. Honest next and ros by k. r rises with k because velocity is a stable trait, so r is a diagnostic. The
   strength is pinned by k* = coef(adjustment) / coef(hd) in target ~ hd + adjustment, honest pools, per season.
3. ROSTER: club runs in T from last season's rates at the club's actual T playing time. Everybody with no qualifying base
   gets the same held-out mean; each rate is put on the runs scale by a held-out player-level slope. Pitchers against club RA,
   hitters against club RS, with club park partialled out of BOTH sides per season (a projection carries the target park, a rate does not), T 2022-2026.
4. CLUB WINS, same season, hdWAR and real fWAR, diagnostic.
5. OVERLAP: shipped hdWAR rate against shipped hpWAR rate, and the largest gaps.
Usage: PYTHONHASHSEED=0 python3 scripts/research/era/war_honest_followup.py
Output: console + data/_war_honest/followup.json
"""
import contextlib, io, json, math, os, pickle, sys
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'projection')); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'hitter'))
from pipeline.eraplus import N0_XW, WAR_PARK_PASS
from pipeline.utils import TEAM_ABBREV_TO_ID
import war_forecast_honest as H
import war_rate_validation as W

SEASONS = H.SEASONS; D = H.D; OUT = H.OUT; TAB = H.TAB; LG = H.LG; PZ = H.PZ; FULL = H.FULL; wr = H.wr; paired = H.paired; show = H.show
IN = {y: pickle.load(open(os.path.join(OUT, f'in_{y}.pkl'), 'rb')) for y in SEASONS}
PF_MULT = 1.67
res = {}


def blend_block():
    print('== 1. BLEND SE: hd + w (xfip - hd), honest; A = blend, B = hd')
    npool = H.next_pool(30); rpool, rtab = H.ros_pool(); ny, nw = H.ys(npool); ry, rw = H.ys(rpool)
    h_n, x_n = H.col(npool, FULL, 'hd'), H.col(npool, FULL, 'xfip'); h_r, x_r = H.col(rpool, rtab, 'hd'), H.col(rpool, rtab, 'xfip')
    for w in (.3, .5, .7):
        a = {y: list(np.array(h_n[y], float) + w * (np.array(x_n[y], float) - np.array(h_n[y], float))) for y in npool}
        p = paired(a, h_n, ny, nw); show(f'next, w {w}', p, 4, ('blend', 'hd')); res[f'blend_next_{w}'] = p
        a = {y: list(np.array(h_r[y], float) + w * (np.array(x_r[y], float) - np.array(h_r[y], float))) for y in rpool}
        p = paired(a, h_r, ry, rw); show(f'ros, w {w}', p, 5, ('blend', 'hd')); res[f'blend_ros_{w}'] = p
    print('  club description by w (mean rmse in runs, 2021-2025; lower = better), RA9 would read 0')
    for other in ('xfip', 'fip'):
        line = []
        for w in [i / 10 for i in range(11)]:
            rm = []
            for y in SEASONS[:-1]:
                st = json.load(open(os.path.join(D, '_hwar_team', f'standings_{y}.json'))); teams = {t['team']['id']: t for rec in st['records'] for t in rec['teamRecords']}
                frv = json.load(open(os.path.join(D, '_hwar_team', f'frv_{y}.json'))); fld = defaultdict(float)
                for v in frv.values():
                    if v.get('total') is not None and v.get('team_id') is not None:
                        fld[int(v['team_id'])] += v['total']
                share = defaultdict(dict)
                for (p, c), n in IN[y]['pclub'].items():
                    share[p][int(c)] = n
                g = FULL[y]; xx = {p: g[p]['hd'] + w * ((g[p][other] if g[p][other] is not None else g[p]['hd']) - g[p]['hd']) for p in g if g[p]['hd'] is not None}
                ipw = sum(g[p]['ip'] for p in xx); mean = sum(xx[p] * g[p]['ip'] for p in xx) / ipw; runs = defaultdict(float)
                for p, v in xx.items():
                    s = share.get(p)
                    if s:
                        tot = sum(s.values())
                        for c, n in s.items():
                            runs[c] += (mean - v) * g[p]['ip'] / 9 * n / tot
                tg = sum(t['wins'] + t['losses'] for t in teams.values()); lgrg = sum(t['runsAllowed'] for t in teams.values()) / tg; pf = W.PF.get(str(y), {})
                X, Y = [], []
                for c, t in teams.items():
                    gm = t['wins'] + t['losses']; X.append((runs[c], fld[c], ((pf.get(str(c), 100) / 100 + 1) / 2 - 1) * lgrg * gm)); Y.append(t['runsAllowed'] - lgrg * gm)
                X, Y = np.array(X), np.array(Y); A = np.column_stack([np.ones(len(Y)), X]); b = np.linalg.lstsq(A, Y, rcond=None)[0]; e = Y - A @ b; rm.append(float(e.std(ddof=4)))
            line.append(rm)
        arr = np.array(line); print(f'    {other:4s} w 0..1: ' + ' '.join(f'{v:.1f}' for v in arr.mean(axis=1)) + f"   best w {int(arr.mean(axis=1).argmin()) / 10}; per-season best w " + ' '.join(str(int(arr[:, j].argmin()) / 10) for j in range(arr.shape[1])))
        res[f'club_blend_{other}'] = arr.tolist()


def velocity_block():
    print('\n== 2. VELOCITY, 2026 now a complete replicate. LOSO band deltas (actual - xwOBA per BIP, recentered)')
    bands = {}
    for y in SEASONS:
        ot = [s for s in SEASONS if s != y]; t = sum(IN[s]['velo_band'] for s in ot); base = t['sum'].sum() / t['size'].sum(); bands[y] = (t['sum'] / t['size'] - base).to_dict()
    print('  season deltas: ' + ' | '.join(f"{y} " + ' '.join(f"{b} {v:+.4f}" for b, v in ((IN[y]['velo_band']['sum'] / IN[y]['velo_band']['size'] - IN[y]['velo_band']['sum'].sum() / IN[y]['velo_band']['size'].sum()).items())) for y in (2025, 2026)))
    res['velo_bands_2026'] = (IN[2026]['velo_band']['sum'] / IN[2026]['velo_band']['size'] - IN[2026]['velo_band']['sum'].sum() / IN[2026]['velo_band']['size'].sum()).to_dict()

    def adj_table(y, h1_only=False):
        s = IN[y]['velo_pitcher']; out = defaultdict(float)
        for (pid, h1, band), n in s.items():
            if h1_only and not h1:
                continue
            out[pid] += bands[y].get(band, 0.0) * n
        return out

    A_F = {y: adj_table(y) for y in SEASONS}; A_H = {y: adj_table(y, True) for y in SEASONS}

    def rates_k(y, k, half=False):
        lg = LG[y]; pz = PZ[y]; gap = lg['ra9'] - lg['era']; out = {}
        for pid, r in TAB[y].items():
            xw, den = (r['xw_h1'], r['xw_den_h1']) if half else (r['xw'], r['xw_den'])
            if xw is None or den <= 0:
                continue
            ad = (A_H[y] if half else A_F[y]).get(pid, 0.0) / den; x = xw + k * ad
            s = (x * den + N0_XW * lg['xw']) / (den + N0_XW); park = 0.0 if half else WAR_PARK_PASS * (r['exp'] - 1) * lg['ra9']
            out[pid] = dict(hd=pz[2] + W.DH_B * (s - pz[0]) / pz[1] + gap - park, adj=W.DH_B * (ad * den / (den + N0_XW)) / pz[1])
        return out

    npool = H.next_pool(30); rpool, _ = H.ros_pool(); ny, nw = H.ys(npool); ry, rw = H.ys(rpool); res['velo'] = {}
    K = [0, .5, 1, 1.5, 2, 3, 4]
    for k in K:
        f = {y: rates_k(y, k) for y in SEASONS}; h = {y: rates_k(y, k, True) for y in SEASONS}
        n_ = [wr([f[y].get(p, {}).get('hd', np.nan) for p in npool[y]['ids']], ny[y], nw[y]) for y in npool]; r_ = [wr([h[y].get(p, {}).get('hd', np.nan) for p in rpool[y]['ids']], ry[y], rw[y]) for y in rpool]
        print(f'  k {k:3}: next {np.mean(n_):.4f}  ros {np.mean(r_):.4f}'); res['velo'][k] = dict(next=n_, ros=r_)
    f0 = {y: rates_k(y, 0) for y in SEASONS}; h0 = {y: rates_k(y, 0, True) for y in SEASONS}

    def kstar(pool, tab, y_, w_):
        o = []
        for y in pool:
            ids = [p for p in pool[y]['ids'] if p in tab[y]]; ix = [pool[y]['ids'].index(p) for p in ids]
            X = np.array([[1, tab[y][p]['hd'], tab[y][p]['adj']] for p in ids]); Y = np.array(y_[y])[ix]; W_ = np.sqrt(np.array(w_[y])[ix]); b = np.linalg.lstsq(X * W_[:, None], Y * W_, rcond=None)[0]; o.append(float(b[2] / b[1]))
        return o
    a = kstar(npool, f0, ny, nw); b = kstar(rpool, h0, ry, rw)
    print('  k* (coef adj / coef hd), next: ' + ' '.join(f'{v:+.2f}' for v in a) + f'  mean {np.mean(a):+.2f}, SE {np.std(a, ddof=1) / math.sqrt(len(a)):.2f}')
    print('  k* (coef adj / coef hd), ros:  ' + ' '.join(f'{v:+.2f}' for v in b) + f'  mean {np.mean(b):+.2f}, SE {np.std(b, ddof=1) / math.sqrt(len(b)):.2f}')
    res['kstar'] = dict(next=a, ros=b)
    ad = [v['adj'] for p, v in f0[2026].items() if TAB[2026][p]['outs'] >= 90]
    print(f'  size: sd of the 2026 k=1 adjustment over 30+ IP arms {np.std(ad):.3f} runs/9')


def roster_block():
    print('\n== 3. ROSTER TEST: T club runs from Y rates at actual T playing time (held-out player slope; no-base players share a held-out mean)')
    # playing time per club in T, 2026 from the shipped club rows
    H_ = json.load(open(os.path.join(D, 'hitter_leaderboard_rs.json'))); P_ = json.load(open(os.path.join(D, 'pitcher_leaderboard_rs.json')))
    bc, pc = {}, {}
    for y in SEASONS[1:]:
        if y < 2026:
            bc[y] = {(str(b), int(c)): int(n) for (b, c), n in IN[y]['bclub'].items()}; pc[y] = {(str(p), int(c)): int(n) for (p, c), n in IN[y]['pclub'].items()}
    bc[2026], pc[2026] = {}, {}
    for r in H_:
        c = TEAM_ABBREV_TO_ID.get(r.get('team')); t = str(r.get('team'))
        if c and r.get('mlbId') and t not in ('ROC', 'AAA') and not t.endswith('TM'):
            bc[2026][(str(r['mlbId']), int(c))] = int(r.get('pa') or 0)
    for r in P_:
        c = TEAM_ABBREV_TO_ID.get(r.get('team')); t = str(r.get('team'))
        if c and r.get('mlbId') and t not in ('ROC', 'AAA') and not t.endswith('TM'):
            pc[2026][(str(r['mlbId']), int(c))] = int(r.get('tbf') or r.get('pa') or 0)

    def standings(y):
        if y == 2026:
            s = json.load(open(os.path.join(D, '_hwar_team', 'standings_2026_by_id.json'))); return {int(k): v for k, v in s.items()}
        st = json.load(open(os.path.join(D, '_hwar_team', f'standings_{y}.json'))); return {t['team']['id']: dict(rs=t['runsScored'], ra=t['runsAllowed'], g=t['wins'] + t['losses']) for rec in st['records'] for t in rec['teamRecords']}

    def score(side, cands, level_T, club_pt, tgt_key, gate_label):
        """level_T[(T, player)] = T outcome in runs per PA above league; cands[name][(T, player)] = base value."""
        out = {n: {} for n in cands}; ys = {}
        Ts = SEASONS[1:]
        for T in Ts:
            st = standings(T); lg = sum(v[tgt_key] for v in st.values()) / sum(v['g'] for v in st.values()); pf = W.PF.get(str(T), {})
            y_ = {c: v[tgt_key] - lg * v['g'] for c, v in st.items()}
            pk = np.array([((pf.get(str(c), 100) / 100 + 1) / 2 - 1) * lg * st[c]['g'] for c in sorted(y_)])
            A_pk = np.column_stack([np.ones(len(pk)), pk])
            part = lambda z: z - A_pk @ np.linalg.lstsq(A_pk, z, rcond=None)[0]      # the projection carries the target park, the rates do not: partial it from both sides
            ys[T] = part(np.array([y_[c] for c in sorted(y_)], float)).tolist()
            for n, tab in cands.items():
                tr = [(k, v) for k, v in tab.items() if k[0] != T and k in level_T and np.isfinite(v)]
                x = np.array([v for _, v in tr]); yy = np.array([level_T[k][0] for k, _ in tr]); ww = np.array([level_T[k][1] for k, _ in tr], float)
                A = np.column_stack([np.ones(len(x)), x]) * np.sqrt(ww)[:, None]; b = np.linalg.lstsq(A, yy * np.sqrt(ww), rcond=None)[0]
                unk = [(k, v) for k, v in level_T.items() if k[0] != T and k not in tab]; mu_unk = np.average([v[0] for _, v in unk], weights=[v[1] for _, v in unk]) if unk else 0.0
                pred = defaultdict(float)
                for (p, c), pa in club_pt[T].items():
                    v = tab.get((T, p)); pred[c] += pa * ((b[0] + b[1] * v) if (v is not None and np.isfinite(v)) else mu_unk)
                out[n][T] = part(np.array([pred[c] for c in sorted(y_)], float)).tolist()
        return out, ys

    # pitchers: base 30+ IP
    lev = {}
    for T in SEASONS[1:]:
        for p, t in TAB[T].items():
            if t['outs'] > 0 and t.get('xw_den', 0) > 0:
                lev[(T, p)] = ((t['r'] - LG[T]['ra9'] * t['outs'] / 27) / max(t['xw_den'], 1), t['xw_den'])
    cands = {k: {} for k in ('hd', 'fip', 'xfip', 'ra9')}
    for y in SEASONS[:-1]:
        for p, r in FULL[y].items():
            if r['ip'] >= 30:
                for k in cands:
                    if r[k] is not None:
                        cands[k][(y + 1, p)] = r[k] - LG[y]['ra9']
    with contextlib.redirect_stdout(io.StringIO()):
        import pit_class_calibration as pcc
        recs = pcc.heldout_records(min_ip_t=0)
    cands['hp'] = {(r['T'], str(r['pid'])): r['pred'] for r in recs}
    o, ys = score('p', cands, lev, pc, 'ra', '30')
    wt = {T: np.ones(len(ys[T])) for T in ys}; res['roster_p'] = {}
    for a, b in (('hd', 'fip'), ('hd', 'xfip'), ('hd', 'ra9'), ('hp', 'hd')):
        p = paired(o[a], o[b], ys, wt); show(f'club RA: {a} v {b}', p, 4, (a, b)); res['roster_p'][f'{a}_{b}'] = p

    # hitters: base 150+ PA
    lev = {}
    for T in SEASONS[1:]:
        g = IN[T]['bat']['full']; lgw = float(np.average(g['woba'], weights=g['n']))
        for b, r in g.iterrows():
            lev[(T, str(b))] = ((r['woba'] - lgw) / 1.24, r['n'])
    import hwar_forecast_honest as HH
    cands = {k: {} for k in ('xhb', 'woba')}
    for y in SEASONS[:-1]:
        a = HH.FULL[y]; lgw = HH.LG[y]['full']
        for b, r in a[a['n'] >= 150].iterrows():
            cands['xhb'][(y + 1, str(b))] = r['xhb'] - lgw['xhb']; cands['woba'][(y + 1, str(b))] = r['woba'] - lgw['woba']
    import h2h_batting as HB
    with contextlib.redirect_stdout(io.StringIO()):
        ours = HB.ours_by_season()
    cands['hp'] = {(T, str(b)): v[0] for T in ours for b, v in ours[T].items() if T in SEASONS[1:]}
    o, ys = score('h', cands, lev, bc, 'rs', '150')
    wt = {T: np.ones(len(ys[T])) for T in ys}; res['roster_h'] = {}
    for a, b in (('xhb', 'woba'), ('hp', 'xhb')):
        p = paired(o[a], o[b], ys, wt); show(f'club RS: {a} v {b}', p, 4, (a, b)); res['roster_h'][f'{a}_{b}'] = p


def wins_block():
    print('\n== 4. CLUB WINS, same season, 2021-2025 + shipped 2026 (diagnostic: fWAR hitters are priced on actual results, so it should win this)')
    import hwar_forecast_honest as HH
    rows = []
    H_ = json.load(open(os.path.join(D, 'hitter_leaderboard_rs.json'))); P_ = json.load(open(os.path.join(D, 'pitcher_leaderboard_rs.json')))
    C = defaultdict(lambda: [0.0, 0.0])
    for r in H_ + P_:
        c = TEAM_ABBREV_TO_ID.get(r.get('team')); t = str(r.get('team'))
        if c and t not in ('ROC', 'AAA') and not t.endswith('TM') and r.get('hWAR') is not None and r.get('fWAR') is not None:
            C[int(c)][0] += r['hWAR']; C[int(c)][1] += r['fWAR']
    s = {int(k): v for k, v in json.load(open(os.path.join(D, '_hwar_team', 'standings_2026_by_id.json'))).items()}
    w = np.array([s[c]['w'] for c in s]); h = np.array([C[c][0] for c in s]); f = np.array([C[c][1] for c in s])
    rd = np.array([s[c]['rs'] - s[c]['ra'] for c in s])
    print(f'  2026, 30 clubs, shipped rows: r(hdWAR, wins) {np.corrcoef(h, w)[0, 1]:.3f}  r(fWAR, wins) {np.corrcoef(f, w)[0, 1]:.3f}  r(run diff, wins) {np.corrcoef(rd, w)[0, 1]:.3f}  r(hdWAR, fWAR) {np.corrcoef(h, f)[0, 1]:.3f}')
    res['wins_2026'] = dict(hd=float(np.corrcoef(h, w)[0, 1]), f=float(np.corrcoef(f, w)[0, 1]))


def overlap_block():
    print('\n== 5. OVERLAP on shipped 2026: hdWAR per unit against hpWAR Full (the projected 2027 rate)')
    H_ = json.load(open(os.path.join(D, 'hitter_leaderboard_rs.json'))); P_ = json.load(open(os.path.join(D, 'pitcher_leaderboard_rs.json')))

    def ip(s):
        w, _, f = str(s or '0').partition('.'); return int(w) + int(f or 0) / 3

    def one(rows, gate):
        seen = {}
        for r in rows:
            t = str(r.get('team'))
            if t in ('ROC', 'AAA') or not r.get('mlbId') or r.get('hWAR') is None:
                continue
            if t.endswith('TM') or r['mlbId'] not in seen:
                seen[r['mlbId']] = r
        return [r for r in seen.values() if gate(r)]
    hit = [r for r in one(H_, lambda r: (r.get('pa') or 0) >= 300) if r.get('hpWAR') is not None]
    a = np.array([r['hWAR'] * 600 / r['pa'] for r in hit]); b = np.array([r['hpWAR'] for r in hit])
    print(f'  hitters 300+ PA, n {len(hit)}: r {np.corrcoef(a, b)[0, 1]:.3f}, sd of hdWAR/600 {a.std():.2f}, sd of hpWAR {b.std():.2f}, r with fWAR/600 {np.corrcoef(np.array([r["fWAR"] * 600 / r["pa"] for r in hit]), b)[0, 1]:.3f}')
    res['overlap_h'] = dict(n=len(hit), r=float(np.corrcoef(a, b)[0, 1]), sd_hd=float(a.std()), sd_hp=float(b.std()))
    d = a - b; o = np.argsort(d)
    for lab, ix in (('hpWAR above this season', o[:6]), ('this season above hpWAR', o[::-1][:6])):
        print(f'    {lab}: ' + '; '.join(f"{hit[i]['hitter']} {a[i]:.1f} v {b[i]:.1f}" for i in ix))
    pit = [r for r in one(P_, lambda r: ip(r.get('ip')) >= 100 and (r.get('gs') or 0) / max(r.get('g') or 1, 1) >= .5) if r.get('hpWAR') is not None]
    a = np.array([r['hWAR'] * 180 / ip(r['ip']) for r in pit]); b = np.array([r['hpWAR'] for r in pit])
    print(f'  starters 100+ IP, n {len(pit)}: r {np.corrcoef(a, b)[0, 1]:.3f}, sd of hdWAR/180 {a.std():.2f}, sd of hpWAR {b.std():.2f}')
    res['overlap_p'] = dict(n=len(pit), r=float(np.corrcoef(a, b)[0, 1]), sd_hd=float(a.std()), sd_hp=float(b.std()))
    d = a - b; o = np.argsort(d)
    for lab, ix in (('hpWAR above this season', o[:6]), ('this season above hpWAR', o[::-1][:6])):
        print(f'    {lab}: ' + '; '.join(f"{pit[i]['pitcher']} {a[i]:.1f} v {b[i]:.1f}" for i in ix))


def main():
    if '--roster-only' in sys.argv:
        roster_block(); return
    blend_block(); velocity_block(); roster_block(); wins_block(); overlap_block()
    with open(os.path.join(OUT, 'followup.json.tmp'), 'w') as f:
        json.dump(res, f, indent=1, default=float)
    os.replace(os.path.join(OUT, 'followup.json.tmp'), os.path.join(OUT, 'followup.json'))
    print('\nwrote data/_war_honest/followup.json')


if __name__ == '__main__':
    main()
