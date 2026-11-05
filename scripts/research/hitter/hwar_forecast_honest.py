"""hwar_forecast_honest.py: the hitter side of war_forecast_honest.py, no gate on the TARGET period (2026-11-04).

hwar_hitter_rate_validation.py gated next season at >= 150 or >= 300 PA in BOTH seasons and rest of season at
>= 150 PA in both halves. Here the gate is on the base period only, every target PA counts, target PA weight.

Rates: xhb  shrunk at HWAR_N0_BAT, park at HWAR_PARK_PASS_BAT     the hdWAR batting input
       woba unshrunk, park at 1.0 of the published factor         the fWAR batting input
       xw   plain Savant xwOBA, treated as xhb
Target: actual wOBA in the target period above league. Park-adjusted target as a check.

Decision rule, written before the run: A beats B when the mean weighted r gap exceeds 2 paired-bootstrap SE AND
A wins at least 4 of 5 pairs (5 of 6 for rest of season). Otherwise a TIE.

Tests: replicate (against data/_hwar_hitter_rate_validation.json), next (base 150+ and 300+ PA), ros (h1 150+),
regulars (base 500+), disagree (top 50 by |xw - woba|, base 300+), n0 sweep, gap flag, the WAR level against real
FanGraphs WAR (total WAR with absent seasons scored 0, reconstruction checked against shipped 2026), the held-out
hpWAR batting projection against one season (bat_experience_test via h2h_batting), the nested add, and the
calibration of the hWAR_se batting noise (var(h1 - h2) against the prediction from WAR_XW_PA_SD).
Usage: PYTHONHASHSEED=0 python3 scripts/research/hitter/hwar_forecast_honest.py
Output: console + data/_war_honest/hitters.json
"""
import contextlib, io, json, math, os, pickle, sys
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'era')); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'projection'))
from pipeline.hwar import HWAR_N0_BAT, HWAR_PARK_PASS_BAT, HWAR_POS_ADJ, HWAR_POS_SPREAD, HWAR_POS_INNINGS
from pipeline.eraplus import WAR_XW_PA_SD, WAR_POOL, WAR_POOL_GAMES, WAR_POOL_SHARE_HITTERS
import war_rate_validation as W

SEASONS = W.SEASONS; D = os.path.join(ROOT, 'data'); OUT = os.path.join(D, '_war_honest'); NB = 2000
SCALE = {2021: 1.209, 2022: 1.259, 2023: 1.204, 2024: 1.242, 2025: 1.2317, 2026: 1.2385}
IN = {y: pickle.load(open(os.path.join(OUT, f'in_{y}.pkl'), 'rb')) for y in SEASONS}
RPA = {y: sum(v['r'] for v in W.T[str(y)]['pitchers'].values()) / sum(v['bf'] for v in W.T[str(y)]['pitchers'].values()) for y in SEASONS}
LG = {y: {sc: {c: float(np.average(IN[y]['bat'][sc][c], weights=IN[y]['bat'][sc]['n'])) for c in ('woba', 'xw', 'xhb')} for sc in ('full', 'h1', 'h2')} for y in SEASONS}


def wr(x, y, w):
    x, y, w = (np.asarray(a, float) for a in (x, y, w))
    m = np.isfinite(x) & np.isfinite(y) & (w > 0); x, y, w = x[m], y[m], w[m]
    mx, my = np.average(x, weights=w), np.average(y, weights=w); dx, dy = x - mx, y - my
    return float(np.sum(w * dx * dy) / math.sqrt(np.sum(w * dx * dx) * np.sum(w * dy * dy)))


def paired(a_by, b_by, y_by, w_by):
    rng = np.random.default_rng(0); keys = sorted(a_by)
    ra = [wr(a_by[k], y_by[k], w_by[k]) for k in keys]; rb = [wr(b_by[k], y_by[k], w_by[k]) for k in keys]
    draws = np.zeros((NB, len(keys)))
    for j, k in enumerate(keys):
        a, b, y, w = (np.asarray(v[k], float) for v in (a_by, b_by, y_by, w_by))
        m = np.isfinite(a) & np.isfinite(b) & np.isfinite(y) & (w > 0); a, b, y, w = a[m], b[m], y[m], w[m]; n = len(a)
        for i in range(NB):
            ix = rng.integers(0, n, n); draws[i, j] = wr(a[ix], y[ix], w[ix]) - wr(b[ix], y[ix], w[ix])
    gap = np.array(ra) - np.array(rb)
    return dict(a=float(np.mean(ra)), b=float(np.mean(rb)), gap=float(gap.mean()), se=float(draws.mean(axis=1).std()), wins=int((gap > 0).sum()), n=len(keys), per_a=ra, per_b=rb, size=[len(a_by[k]) for k in keys])


def show(label, p, need, names):
    tag = 'TIE'
    if abs(p['gap']) > 2 * p['se']:
        if p['gap'] > 0 and p['wins'] >= need:
            tag = names[0]
        elif p['gap'] < 0 and p['n'] - p['wins'] >= need:
            tag = names[1]
    print(f"  {label:36s} {names[0]} {p['a']:.3f}  {names[1]} {p['b']:.3f}  gap {p['gap']:+.3f} (SE {p['se']:.3f})  wins {p['wins']}/{p['n']}  -> {tag}   n {p['size']}", flush=True)


def park_runs(y, g):
    return (g['pf'].fillna(1.0) - 1.0) * RPA[y] * SCALE[y]


def rates(y, sc='full', n0=HWAR_N0_BAT, park=True):
    g = IN[y]['bat'][sc]; pk = park_runs(y, g) if park else 0.0; lg = LG[y][sc]
    sh = lambda c: (g[c] * g['n'] + n0 * lg[c]) / (g['n'] + n0)
    return pd.DataFrame(dict(n=g['n'], xhb=sh('xhb') - HWAR_PARK_PASS_BAT * pk, xw=sh('xw') - HWAR_PARK_PASS_BAT * pk, woba=g['woba'] - 1.0 * pk, raw_woba=g['woba']))


FULL = {y: rates(y) for y in SEASONS}
H1 = {y: rates(y, 'h1', park=False) for y in SEASONS}


def next_pool(gate, park_target=False):
    out = {}
    for y in SEASONS[:-1]:
        a = FULL[y]; b = IN[y + 1]['bat']['full']
        ids = a.index[a['n'] >= gate].intersection(b.index[b['n'] > 0])
        t = b.loc[ids, 'woba'] - LG[y + 1]['full']['woba']
        if park_target:
            t = t - park_runs(y + 1, b.loc[ids])
        out[y] = dict(ids=ids, y=t.values, w=b.loc[ids, 'n'].values.astype(float))
    return out


def ros_pool(gate=150, tab=None):
    tab = tab or H1; out = {}
    for y in SEASONS:
        a = tab[y]; b = IN[y]['bat']['h2']; ids = a.index[a['n'] >= gate].intersection(b.index[b['n'] > 0])
        out[y] = dict(ids=ids, y=(b.loc[ids, 'woba'] - LG[y]['h2']['woba']).values, w=b.loc[ids, 'n'].values.astype(float))
    return out


def c(pool, tab, k):
    return {y: tab[y].loc[pool[y]['ids'], k].values for y in pool}


def yw(pool):
    return {y: pool[y]['y'] for y in pool}, {y: pool[y]['w'] for y in pool}


def main():
    res = {}
    print('== REPLICATE the gated test against data/_hwar_hitter_rate_validation.json (unshrunk, pass as there)')
    old = json.load(open(os.path.join(D, '_hwar_hitter_rate_validation.json')))
    for cand, key in (('xhb', 'xhb N0=0'), ('woba', 'woba N0=0')):
        ps = float(np.mean(old[f'pass_{cand}'])); got = {}
        for gate in (300, 150):
            rr = []
            for y in SEASONS[:-1]:
                g, g2 = IN[y]['bat']['full'], IN[y + 1]['bat']['full']; ks = g.index[g['n'] >= gate].intersection(g2.index[g2['n'] >= gate])
                rr.append(W.pear((g.loc[ks, cand] - ps * park_runs(y, g.loc[ks])).values, g2.loc[ks, 'woba'].values))
            got[gate] = float(np.mean(rr))
        ref = old[key]
        print(f"  {cand}: nxt300 {got[300]:.3f} (file {np.mean(ref['nxt300']):.3f})  nxt150 {got[150]:.3f} (file {np.mean(ref['nxt150']):.3f})")
        if abs(got[300] - np.mean(ref['nxt300'])) > .003 or abs(got[150] - np.mean(ref['nxt150'])) > .003:
            print('  WARNING: the replication misses the file by more than .003 (the 2026 inputs moved since 2026-10-02 are the first suspect)')
    print('\n== NEXT SEASON, honest: base gate only, every target PA counts, PA_T weighted, wOBA_T above league')
    res['next'] = {}
    for gate in (150, 300):
        for pk in (False, True):
            pool = next_pool(gate, pk); y_, w_ = yw(pool)
            for a, b in (('xhb', 'woba'), ('xw', 'woba'), ('xhb', 'xw')):
                p = paired(c(pool, FULL, a), c(pool, FULL, b), y_, w_); show(f'{gate}+ PA, {"park" if pk else "raw"} target, {a} v {b}', p, 4, (a, b)); res['next'][f'{gate}_{"park" if pk else "raw"}_{a}_{b}'] = p
    print('\n== GATE EFFECT: same rates, target gate on, unweighted, against base gate only, unweighted')
    res['gate_effect'] = {}
    for g_ in (300, 150):
        pool = next_pool(g_); pg = {}
        for y in pool:
            nT = IN[y + 1]['bat']['full'].loc[pool[y]['ids'], 'n'].values; keep = nT >= g_
            pg[y] = dict(ids=pool[y]['ids'][keep], y=pool[y]['y'][keep], w=np.ones(keep.sum()))
        y_, w_ = yw(pg); p = paired(c(pg, FULL, 'xhb'), c(pg, FULL, 'woba'), y_, w_); show(f'gated both, unweighted, {g_}', p, 4, ('xhb', 'woba')); res['gate_effect'][f'gated_{g_}'] = p
        y_, w1 = yw(pool); w1 = {y: np.ones(len(pool[y]['ids'])) for y in pool}; p = paired(c(pool, FULL, 'xhb'), c(pool, FULL, 'woba'), y_, w1); show(f'base gate only, unweighted, {g_}', p, 4, ('xhb', 'woba')); res['gate_effect'][f'base_unw_{g_}'] = p
    print('\n== REST OF SEASON, honest: first half 150+ PA, second half any, h2 PA weighted')
    pool = ros_pool(); y_, w_ = yw(pool); res['ros'] = {}
    for a, b in (('xhb', 'woba'), ('xw', 'woba'), ('xhb', 'xw')):
        p = paired(c(pool, H1, a), c(pool, H1, b), y_, w_); show(f'{a} v {b}', p, 5, (a, b)); res['ros'][f'{a}_{b}'] = p
    print('\n== REGULARS by history, base 500+ PA, honest target')
    pool = next_pool(500); y_, w_ = yw(pool); p = paired(c(pool, FULL, 'xhb'), c(pool, FULL, 'woba'), y_, w_); show('xhb v woba', p, 4, ('xhb', 'woba')); res['regulars'] = p
    print('\n== DISAGREEMENT SET: 50 hitters per season, base 300+ PA, largest |xw - woba| (park terms out), honest target')
    pool = next_pool(300); dis = {}
    for y in pool:
        g = IN[y]['bat']['full'].loc[pool[y]['ids']]; top = (g['xw'] - g['woba']).abs().values.argsort()[::-1][:50]
        dis[y] = dict(ids=pool[y]['ids'][top], y=pool[y]['y'][top], w=pool[y]['w'][top])
    y_, w_ = yw(dis); p = paired(c(dis, FULL, 'xhb'), c(dis, FULL, 'woba'), y_, w_); show('xhb v woba', p, 4, ('xhb', 'woba')); res['disagree'] = p

    print('\n== BLEND a xhb + (1 - a) woba, honest (the projection uses a = .75 on its own history form; a over 1 extends the grid past the edge)')
    pool = next_pool(150); rp = ros_pool(); ny, nw = yw(pool); ry, rw = yw(rp); GRID = [i / 10 for i in range(14)]; nm, rm = [], []
    for a in GRID:
        nm.append([wr(a * FULL[y].loc[pool[y]['ids'], 'xhb'].values + (1 - a) * FULL[y].loc[pool[y]['ids'], 'woba'].values, ny[y], nw[y]) for y in pool])
        rm.append([wr(a * H1[y].loc[rp[y]['ids'], 'xhb'].values + (1 - a) * H1[y].loc[rp[y]['ids'], 'woba'].values, ry[y], rw[y]) for y in rp])
    nm, rm = np.array(nm), np.array(rm); print('  a     ' + ' '.join(f'{a:5.1f}' for a in GRID)); print('  next  ' + ' '.join(f'{v:.3f}' for v in nm.mean(axis=1))); print('  ros   ' + ' '.join(f'{v:.3f}' for v in rm.mean(axis=1))); res['blend'] = dict(grid=GRID, next=nm.tolist(), ros=rm.tolist())

    print('\n== N0 SWEEP, honest xhb (shipped 77, chosen on same-season calibration, so this is a diagnostic)')
    res['n0'] = {}
    for n0 in (0, 25, 50, 77, 100, 150, 200, 300, 500, 800):
        tf = {y: rates(y, n0=n0) for y in SEASONS}; th = {y: rates(y, 'h1', n0=n0, park=False) for y in SEASONS}
        n_ = [wr(tf[y].loc[pool[y]['ids'], 'xhb'].values, ny[y], nw[y]) for y in pool]; r_ = [wr(th[y].loc[rp[y]['ids'], 'xhb'].values, ry[y], rw[y]) for y in rp]
        print(f'  N0 {n0:4d}: next {np.mean(n_):.4f}  ros {np.mean(r_):.4f}', flush=True); res['n0'][n0] = dict(next=n_, ros=r_)

    print('\n== GAP FLAG: (wOBA_T - wOBA_Y, both above league) on (xhb_Y - wOBA_Y, both above league), base 300+ PA, honest, PA_T weighted')
    pool = next_pool(300); sl, rr = [], []
    for y in pool:
        ids = pool[y]['ids']; a = FULL[y].loc[ids]; g = (a['xhb'] - LG[y]['full']['xhb']) - (a['raw_woba'] - LG[y]['full']['woba'])
        ch = pool[y]['y'] - (a['raw_woba'].values - LG[y]['full']['woba']); sl.append(W.wls_slope(g.values, ch, pool[y]['w'])); rr.append(wr(g.values, ch, pool[y]['w']))
    print(f"  slope {np.mean(sl):.3f} (" + ' '.join(f'{v:.2f}' for v in sl) + f")  r {np.mean(rr):.3f} (" + ' '.join(f'{v:.2f}' for v in rr) + ')'); res['gap'] = dict(slope=sl, r=rr)

    # ---------- WAR level
    print('\n== WAR LEVEL: reconstructed hdWAR (xhb, FG BaseRunning as the history stand-in, Savant FRV, compressed positional, pinned replacement) against real FanGraphs WAR')
    FG = {y: {str(int(r['xMLBAMID'])): r for r in json.load(open(os.path.join(D, '_proj', 'fg', f'actual_{y}_bat.json'))) if r.get('xMLBAMID')} for y in SEASONS}
    GAMES, RPW = {}, {}
    for y in SEASONS:
        if y == 2026:
            s = json.load(open(os.path.join(D, '_hwar_team', 'standings_2026_by_id.json'))); GAMES[y] = sum(v['g'] for v in s.values()) / 2
        else:
            st = json.load(open(os.path.join(D, '_hwar_team', f'standings_{y}.json'))); GAMES[y] = sum(t['wins'] + t['losses'] for rec in st['records'] for t in rec['teamRecords']) / 2
        rows = W.season_table(y); RPW[y] = W.league(rows)['rpw']

    def pos_runs(y):
        inn = json.load(open(os.path.join(D, '_hwar_team', f'innings_{y}.json')))['stats'][0]['splits']; tot = defaultdict(float); rec = []
        for sp in inn:
            pos = sp.get('position', {}).get('abbreviation')
            if pos not in HWAR_POS_ADJ:
                continue
            st = sp['stat']
            if pos == 'DH':
                ii = 9.0 * int(st.get('games') or 0)
            else:
                a, _, f = str(st.get('innings') or '0').partition('.'); ii = int(a) + int(f or 0) / 3.0
            tot[pos] += ii; rec.append((str(sp['player']['id']), pos, ii))
        center = sum(tot[p] * HWAR_POS_ADJ[p] for p in tot) / sum(tot.values())
        tab = {p: center + HWAR_POS_SPREAD * (HWAR_POS_ADJ[p] - center) for p in HWAR_POS_ADJ}; out = defaultdict(float)
        for pid, pos, ii in rec:
            out[pid] += ii * tab[pos] / HWAR_POS_INNINGS
        return out

    def load_frv(y):
        fn = os.path.join(D, '_hwar_team', f'frv_{y}.json')
        if os.path.exists(fn):
            return json.load(open(fn))
        rows = json.load(open(os.path.join(D, '_proj', f'frv_{y}.json')))
        if isinstance(rows, dict):
            return rows
        return {str(r.get('id') or r.get('player_id') or r.get('entity_id')): dict(total=r.get('total') if r.get('total') is not None else r.get('total_runs')) for r in rows}

    def hd_war(y):
        a = FULL[y]; L = float(np.average(a['xhb'], weights=a['n'])); bat = ((a['xhb'] - L) * a['n'] / SCALE[y]).to_dict(); n = a['n'].to_dict()
        frv = load_frv(y); pos = pos_runs(y); fg = FG[y]; ids = list(a.index)
        comp = {p: bat[p] + float(fg.get(p, {}).get('BaseRunning') or 0.0) + float((frv.get(p) or {}).get('total') or 0.0) + pos.get(p, 0.0) for p in ids}
        tgt = WAR_POOL_SHARE_HITTERS * WAR_POOL * GAMES[y] / WAR_POOL_GAMES * RPW[y]; rep = (tgt - sum(comp.values())) / sum(n.values())
        return {p: (comp[p] + rep * n[p]) / RPW[y] for p in ids}

    HD = {y: hd_war(y) for y in SEASONS}; FW = {y: {p: float(r['WAR']) for p, r in FG[y].items() if r.get('WAR') is not None} for y in SEASONS}
    ship = json.load(open(os.path.join(D, 'hitter_leaderboard_rs.json'))); sh = {}
    for r in ship:
        t = str(r.get('team'))
        if t in ('ROC', 'AAA') or r.get('hWAR') is None or not r.get('mlbId'):
            continue
        if t.endswith('TM') or str(r['mlbId']) not in sh:
            sh[str(r['mlbId'])] = r['hWAR']
    ks = [p for p in sh if p in HD[2026]]; a_ = np.array([sh[p] for p in ks]); b_ = np.array([HD[2026][p] for p in ks])
    print(f'  check: reconstructed 2026 hdWAR vs shipped: n {len(ks)}, r {np.corrcoef(a_, b_)[0, 1]:.4f}, mean abs diff {np.abs(a_ - b_).mean():.3f}, max {np.abs(a_ - b_).max():.2f}, sums {a_.sum():.1f} / {b_.sum():.1f}')
    res['war_check'] = dict(n=len(ks), r=float(np.corrcoef(a_, b_)[0, 1]), mad=float(np.abs(a_ - b_).mean()))
    if res['war_check']['r'] < .97:
        raise SystemExit('the hdWAR reconstruction misses shipped 2026; stop and find out why')
    ids = {y: [p for p in FULL[y].index[FULL[y]['n'] >= 200] if p in FW[y]] for y in SEASONS[:-1]}; w1 = {y: np.ones(len(ids[y])) for y in ids}; res['war'] = {}
    hdc = {y: [HD[y][p] for p in ids[y]] for y in ids}; fc = {y: [FW[y][p] for p in ids[y]] for y in ids}
    for tname, TT in (('fWAR', FW), ('hdWAR', HD)):
        tgt = {y: [TT[y + 1].get(p, 0.0) for p in ids[y]] for y in ids}; p = paired(hdc, fc, tgt, w1); show(f'total T {tname}: hdWAR_Y v fWAR_Y', p, 4, ('hd', 'f')); res['war'][f'{tname}_total'] = p
    # neutral target: actual-outcome batting runs per PA is FanGraphs Batting, already in fWAR; rate target over PA_T
    print('  rate form: T WAR per 600 PA, base 200+ PA, target PA >= 1, PA_T weighted')
    for tname, TT in (('fWAR', FW), ('hdWAR', HD)):
        a2, b2, y2, w2 = {}, {}, {}, {}
        for y in ids:
            nT = IN[y + 1]['bat']['full']['n']; kp = [p for p in ids[y] if p in nT.index and nT[p] > 0 and p in TT[y + 1]]
            nY = FULL[y]['n']; a2[y] = [HD[y][p] * 600 / nY[p] for p in kp]; b2[y] = [FW[y][p] * 600 / nY[p] for p in kp]; y2[y] = [TT[y + 1][p] * 600 / nT[p] for p in kp]; w2[y] = [float(nT[p]) for p in kp]
        p = paired(a2, b2, y2, w2); show(f'rate T {tname}: hdWAR_Y v fWAR_Y', p, 4, ('hd', 'f')); res['war'][f'{tname}_rate'] = p

    # ---------- projection
    print('\n== hpWAR BATTING PROJECTION (held out) against one season, same pool: base 150+ PA, target any, PA_T weighted, T 2022-2026')
    import h2h_batting as HB
    with contextlib.redirect_stdout(io.StringIO()):
        ours = HB.ours_by_season()
    pool = next_pool(150); pp = {}; pj = {}
    for y in pool:
        rec = ours.get(y + 1, {}); keep = [i for i, b in enumerate(pool[y]['ids']) if int(b) in rec]
        pp[y] = dict(ids=pool[y]['ids'][keep], y=pool[y]['y'][keep], w=pool[y]['w'][keep]); pj[y] = np.array([rec[int(b)][0] for b in pp[y]['ids']])
    y_, w_ = yw(pp)
    for o in ('xhb', 'woba'):
        p = paired(pj, c(pp, FULL, o), y_, w_); show(f'projection v {o}', p, 4, ('hp', o)); res[f'hp_{o}'] = p
    out = []
    for y in pp:
        tr = [s for s in pp if s != y]; X = np.vstack([np.column_stack([pj[s], FULL[s].loc[pp[s]['ids'], 'xhb'].values]) for s in tr]); Y = np.concatenate([pp[s]['y'] for s in tr]); Wg = np.concatenate([pp[s]['w'] for s in tr])
        A = np.column_stack([np.ones(len(Y)), X]) * np.sqrt(Wg)[:, None]; bb = np.linalg.lstsq(A, Y * np.sqrt(Wg), rcond=None)[0]; Ah = A[:, :2]; b0 = np.linalg.lstsq(Ah, Y * np.sqrt(Wg), rcond=None)[0]
        Xh = np.column_stack([pj[y], FULL[y].loc[pp[y]['ids'], 'xhb'].values]); pr = bb[0] + Xh @ bb[1:]; p0 = b0[0] + b0[1] * pj[y]; yy, ww = pp[y]['y'], pp[y]['w']
        out.append(dict(T=y + 1, b_x=float(bb[2]), mse=float(np.average((yy - pr) ** 2, weights=ww)), mse0=float(np.average((yy - p0) ** 2, weights=ww))))
    d = np.array([1 - o['mse'] / o['mse0'] for o in out]); print('  nested, projection + xhb, held out: ' + ' '.join(f"{o['T']}: b {o['b_x']:+.2f}, MSE gain {100 * (1 - o['mse'] / o['mse0']):+.2f}%" for o in out) + f'  mean {100 * d.mean():+.2f}%, wins {(d > 0).sum()}/5'); res['hp_nested'] = out

    # ---------- error bar
    print(f'\n== hWAR_se BATTING NOISE: var(h1 - h2 of xhb) against the sigma^2 (1/n1 + 1/n2) prediction, 150+ PA each half; sigma {WAR_XW_PA_SD} ships')
    res['se'] = {}
    for y in SEASONS:
        a, b = IN[y]['bat']['h1'], IN[y]['bat']['h2']; ks = a.index[a['n'] >= 150].intersection(b.index[b['n'] >= 150]); pred = WAR_XW_PA_SD ** 2 * (1 / a.loc[ks, 'n'] + 1 / b.loc[ks, 'n'])
        diff = (a.loc[ks, 'xhb'] - LG[y]['h1']['xhb']) - (b.loc[ks, 'xhb'] - LG[y]['h2']['xhb']); obs = float((diff ** 2).mean()); own = np.sqrt(float(np.average(IN[y]['bat']['full']['xhb_var'].dropna(), weights=IN[y]['bat']['full'].loc[IN[y]['bat']['full']['xhb_var'].notna(), 'n'])))
        print(f'  {y}: n {len(ks)}, observed / predicted {obs / float(pred.mean()):.3f}, mean within-batter per-PA sd {own:.3f}'); res['se'][y] = dict(n=int(len(ks)), ratio=obs / float(pred.mean()), sd=own)

    with open(os.path.join(OUT, 'hitters.json.tmp'), 'w') as f:
        json.dump(res, f, indent=1, default=float)
    os.replace(os.path.join(OUT, 'hitters.json.tmp'), os.path.join(OUT, 'hitters.json'))
    print('\nwrote data/_war_honest/hitters.json')


if __name__ == '__main__':
    main()
