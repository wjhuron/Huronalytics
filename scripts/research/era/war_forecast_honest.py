"""war_forecast_honest.py: the hdERA / FIP / RA9 forecast tests again, with no gate on the TARGET period (2026-11-04).

war_rate_validation.py (2026-09-05) gated the next-season test at >= 60 or >= 30 IP in BOTH seasons and the
rest-of-season test at >= 30 IP in both halves. Playing time follows performance, so that gate selects on the
outcome (root CLAUDE.md failure log, 2026-10-07). Here the gate is on the base period only, every target out
counts, and target innings weight the score.

Rates, each on the runs-per-9 scale, each with its parent's park removal:
  hd    hdERA runs (W.hd_rate, shrunk at N0_XW), WAR_PARK_PASS .67         the hdWAR input
  fip   FIP runs, published factor x 1                                     the fWAR input
  ra9   actual runs, published factor x 1                                  the bWAR idea
  xfip  FIP with the HR term at the league HR/FB, published factor x 1
Target: RA9 in the target period minus the league rate. Park-adjusted target reported as a check.

Decision rule, written before the run: A beats B when the mean weighted r gap exceeds 2 paired-bootstrap SE
AND A wins at least 4 of 5 pairs (5 of 6 for rest of season). Otherwise the two are a TIE on that objective.

Tests:
  replicate   the gated numbers, against data/_war_rate_validation.json, before anything is trusted
  next        base >= 30 and >= 60 IP, target >= 1 out, IP_T weighted, five pairs
  ros         first half >= 30 IP, second half >= 1 out, h2 IP weighted, six seasons
  classes     history-defined: starters 120+ IP and start share .5+; relievers 40+ IP and start share under .2
  disagree    per season the 50 pitchers (base >= 60 IP) where hd and fip differ most, target ungated
  blend       hd + w (fip - hd) and hd + w (xfip - hd), w 0..1, plus the LOSO-chosen w
  n0          the N0_XW sweep on the honest objectives (hdERA's own shrink)
  gap         does a season's gap forecast the change in RA9? (RA9_T - RA9_Y) on (rate - RA9_Y)
  war         real FanGraphs WAR against a reconstructed hdWAR and RA9-WAR: total WAR Y -> total WAR T with
              absent seasons scored 0, pool >= 30 IP in Y; the reconstruction is checked against shipped 2026
  hp          the held-out hpWAR run model (pit_class_calibration, without the EV channel added 2026-11-02)
              against hd on one pool, plus the leak-free nested add of hd to the projection
  club        same-season description: club RA above league on summed deserved runs, FRV and park, per rate
Usage: PYTHONHASHSEED=0 python3 scripts/research/era/war_forecast_honest.py [--no-hp]
Output: console + data/_war_honest/pitchers.json
"""
import contextlib, io, json, math, os, pickle, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'projection'))
from pipeline.eraplus import N0_XW, WAR_PARK_PASS, WAR_RAA_SCALE, WAR_ROLE_GAP, WAR_POOL, WAR_POOL_GAMES, WAR_POOL_SHARE_HITTERS
from pipeline.utils import TEAM_ABBREV_TO_ID
import war_rate_validation as W

SEASONS = W.SEASONS; B = W.B; D = os.path.join(ROOT, 'data'); OUT = os.path.join(D, '_war_honest')
NB = 2000; RATES = ('hd', 'fip', 'ra9', 'xfip')


def wr(x, y, w):
    x, y, w = (np.asarray(a, float) for a in (x, y, w))
    m = np.isfinite(x) & np.isfinite(y) & (w > 0); x, y, w = x[m], y[m], w[m]
    if len(x) < 10:
        return float('nan')
    mx, my = np.average(x, weights=w), np.average(y, weights=w); dx, dy = x - mx, y - my
    return float(np.sum(w * dx * dy) / math.sqrt(np.sum(w * dx * dx) * np.sum(w * dy * dy)))


def paired(a_by, b_by, y_by, w_by, rng_seed=0):
    """Mean r of a, of b, the gap, its bootstrap SE (pitchers resampled within season, same draw for both), wins."""
    rng = np.random.default_rng(rng_seed); keys = sorted(a_by)
    ra = [wr(a_by[k], y_by[k], w_by[k]) for k in keys]; rb = [wr(b_by[k], y_by[k], w_by[k]) for k in keys]
    draws = np.zeros((NB, len(keys)))
    for j, k in enumerate(keys):
        a, b, y, w = (np.asarray(v[k], float) for v in (a_by, b_by, y_by, w_by))
        m = np.isfinite(a) & np.isfinite(b) & np.isfinite(y) & (w > 0); a, b, y, w = a[m], b[m], y[m], w[m]; n = len(a)
        for i in range(NB):
            ix = rng.integers(0, n, n); draws[i, j] = wr(a[ix], y[ix], w[ix]) - wr(b[ix], y[ix], w[ix])
    gap = np.array(ra) - np.array(rb)
    return dict(a=float(np.mean(ra)), b=float(np.mean(rb)), gap=float(gap.mean()), se=float(draws.mean(axis=1).std()), wins=int((gap > 0).sum()), n=len(keys),
                per_a=ra, per_b=rb, size=[int(len(a_by[k])) for k in keys])


def verdict(p, need):
    if abs(p['gap']) > 2 * p['se'] and (p['wins'] >= need if p['gap'] > 0 else p['n'] - p['wins'] >= need):
        return 'A' if p['gap'] > 0 else 'B'
    return 'TIE'


def show(label, p, need, names=('A', 'B')):
    v = verdict(p, need); tag = names[0] if v == 'A' else names[1] if v == 'B' else 'TIE'
    print(f"  {label:34s} {names[0]} {p['a']:.3f}  {names[1]} {p['b']:.3f}  gap {p['gap']:+.3f} (SE {p['se']:.3f})  wins {p['wins']}/{p['n']}  -> {tag}   n {p['size']}", flush=True)


TAB = {y: W.season_table(y) for y in SEASONS}
LG = {y: W.league(TAB[y]) for y in SEASONS}
PZ = {y: W.pool_stats(TAB[y], LG[y]) for y in SEASONS}


def hrfb(y):
    hrs = fbs = 0.0
    for p, r in W.T[str(y)]['pitchers'].items():
        m = B[str(y)].get(p, {}).get('full')
        if m and m.get('fb_pct') is not None and m.get('bip'):
            hrs += r['hr']; fbs += m['fb_pct'] * m['bip']
    return hrs / fbs


HRFB = {y: hrfb(y) for y in SEASONS}


def xfip_num(y, pid, scope='full'):
    t = W.T[str(y)]['pitchers'][pid]; b = B[str(y)].get(pid, {}); m = b.get('full' if scope == 'full' else 'h1')
    if not m or m.get('fb_pct') is None or not m.get('bip'):
        return None
    kc = m.get('k_counts')
    return 13 * HRFB[y] * m['fb_pct'] * m['bip'] + 3 * (kc['bb'] + kc['hbp']) - 2 * kc['k']


def rates_full(y, n0=N0_XW, pass_hd=WAR_PARK_PASS):
    lg = LG[y]; out = {}; pz = PZ[y]
    for pid, r in TAB[y].items():
        o = r['outs']; k = (r['exp'] - 1) * lg['ra9']; gap = lg['ra9'] - lg['era']
        sh = None
        if r['xw'] is not None and r['xw_den'] > 0:
            s = (r['xw'] * r['xw_den'] + n0 * lg['xw']) / (r['xw_den'] + n0)
            sh = pz[2] + W.DH_B * (s - pz[0]) / pz[1] + gap - pass_hd * k
        xn = xfip_num(y, pid)
        out[pid] = dict(hd=sh, fip=r['fip_num'] * 3 / o + lg['cfip'] + gap - k, ra9=r['r'] * 27 / o - k,
                        xfip=(xn * 3 / o + lg['cfip'] + gap - k) if xn is not None else None,
                        ip=o / 3, g=r['g'], gs=r['gs'], s=(r['gs'] / r['g'] if r['g'] else 0.0), exp=r['exp'], raw=r['r'] * 27 / o)
    return out


def rates_half(y, n0=N0_XW):
    """First-half rates; park cancels within a season for the same pitcher, as in the source test."""
    lg = LG[y]; out = {}; pz = PZ[y]; gap = lg['ra9'] - lg['era']
    for pid, r in TAB[y].items():
        h = r['h1']; o = h.get('outs') or 0
        if o <= 0:
            continue
        sh = None
        if r['xw_h1'] is not None and r['xw_den_h1'] > 0:
            s = (r['xw_h1'] * r['xw_den_h1'] + n0 * lg['xw']) / (r['xw_den_h1'] + n0)
            sh = pz[2] + W.DH_B * (s - pz[0]) / pz[1] + gap
        fn = r['fip_num_h1']; b1 = B[str(y)].get(pid, {}).get('h1'); xf = None
        if b1 and b1.get('fb_pct') is not None and b1.get('bip'):
            kc = b1['k_counts']; xf = (13 * HRFB[y] * b1['fb_pct'] * b1['bip'] + 3 * (kc['bb'] + kc['hbp']) - 2 * kc['k']) * 3 / o + lg['cfip'] + gap
        out[pid] = dict(hd=sh, fip=(fn * 3 / o + lg['cfip'] + gap) if fn is not None else None, ra9=h['r'] * 27 / o, xfip=xf, ip=o / 3)
    return out


FULL = {y: rates_full(y) for y in SEASONS}
H1 = {y: rates_half(y) for y in SEASONS}


def next_pool(gate, sel=None, rate_tab=None, park_target=False):
    """{y: dict(ids, y, w)} for base gate only; every pitcher with >= 1 out in T."""
    tab = rate_tab or FULL; out = {}
    for y in SEASONS[:-1]:
        a, b = tab[y], FULL[y + 1]; T1 = TAB[y + 1]
        ids = [p for p, r in a.items() if r['ip'] >= gate and p in T1 and T1[p]['outs'] > 0 and (sel is None or sel(r))]
        k = {p: (T1[p]['exp'] - 1) * LG[y + 1]['ra9'] for p in ids}
        out[y] = dict(ids=ids, y=[T1[p]['r'] * 27 / T1[p]['outs'] - LG[y + 1]['ra9'] - (k[p] if park_target else 0.0) for p in ids], w=[T1[p]['outs'] / 3 for p in ids])
    return out


def col(pool, tab, key):
    return {y: [(tab[y][p].get(key) if tab[y][p].get(key) is not None else np.nan) for p in pool[y]['ids']] for y in pool}


def ys(pool):
    return {y: pool[y]['y'] for y in pool}, {y: pool[y]['w'] for y in pool}


def ros_pool(gate=30, n0=None):
    tab = H1 if n0 is None else {y: rates_half(y, n0) for y in SEASONS}; out = {}
    for y in SEASONS:
        ids = [p for p, r in tab[y].items() if r['ip'] >= gate and (TAB[y][p]['h2'].get('outs') or 0) > 0]
        out[y] = dict(ids=ids, y=[TAB[y][p]['h2']['r'] * 27 / TAB[y][p]['h2']['outs'] - LG[y]['ra9'] for p in ids], w=[TAB[y][p]['h2']['outs'] / 3 for p in ids])
    return out, tab


def main():
    res = {}
    print('== REPLICATE the gated test against data/_war_rate_validation.json (pass .899 as there)')
    old = json.load(open(os.path.join(D, '_war_rate_validation.json')))
    F0 = {y: rates_full(y, pass_hd=float(np.mean(old['park_pass']['hdR9']))) for y in SEASONS}
    for gate in (60, 30):
        rr = {k: [] for k in ('hd', 'fip', 'ra9')}
        for y in SEASONS[:-1]:
            ks = [p for p in F0[y] if p in F0[y + 1] and F0[y][p]['ip'] >= gate and F0[y + 1][p]['ip'] >= gate]
            tgt = [TAB[y + 1][p]['r'] * 27 / TAB[y + 1][p]['outs'] for p in ks]
            for k in rr:
                rr[k].append(W.pear([F0[y][p][k] for p in ks], tgt))
        ref = old[f'next_{gate}']['raw']
        print(f"  gate {gate}: hd {np.mean(rr['hd']):.3f} (file {np.mean(ref['hdR9']):.3f})  fip {np.mean(rr['fip']):.3f} (file {np.mean(ref['FIPR9']):.3f})  ra9 {np.mean(rr['ra9']):.3f} (file {np.mean(ref['RA9']):.3f})")
        ok = all(abs(np.mean(rr[a]) - np.mean(ref[b])) < .002 for a, b in (('hd', 'hdR9'), ('fip', 'FIPR9'), ('ra9', 'RA9')))
        if not ok:
            raise SystemExit('the replication misses the shipped file; stop and find out why')
    res['replicated'] = True

    print('\n== NEXT SEASON, honest: base gate only, every target out counts, IP_T weighted, RA9_T above league')
    res['next'] = {}
    for gate in (30, 60):
        for park in (False, True):
            pool = next_pool(gate, park_target=park); y_, w_ = ys(pool)
            for a, b in (('hd', 'fip'), ('hd', 'ra9'), ('fip', 'ra9'), ('hd', 'xfip')):
                p = paired(col(pool, FULL, a), col(pool, FULL, b), y_, w_)
                show(f'{gate}+ IP, {"park target" if park else "raw target"}, {a} v {b}', p, 4, (a, b)); res['next'][f'{gate}_{"park" if park else "raw"}_{a}_{b}'] = p

    print('\n== GATE EFFECT: the old gate applied to the same shipped park, on the same weights (target IP gate on)')
    res['gate_effect'] = {}
    for g in (60, 30):
        pool = next_pool(g); pg = {}
        for y in pool:
            keep = [i for i, p in enumerate(pool[y]['ids']) if TAB[y + 1][p]['outs'] / 3 >= g]
            pg[y] = dict(ids=[pool[y]['ids'][i] for i in keep], y=[pool[y]['y'][i] for i in keep], w=[1.0 for _ in keep])
        y_, w_ = ys(pg); p = paired(col(pg, FULL, 'hd'), col(pg, FULL, 'fip'), y_, w_); show(f'gated both, unweighted, {g}', p, 4, ('hd', 'fip')); res['gate_effect'][f'gated_{g}'] = p
        y_, w_ = ys(pool); w1 = {y: [1.0] * len(pool[y]['ids']) for y in pool}; p = paired(col(pool, FULL, 'hd'), col(pool, FULL, 'fip'), y_, w1); show(f'base gate only, unweighted, {g}', p, 4, ('hd', 'fip')); res['gate_effect'][f'base_unw_{g}'] = p

    print('\n== REST OF SEASON, honest: first half >= 30 IP, second half any, h2 IP weighted')
    pool, tab = ros_pool(); y_, w_ = ys(pool); res['ros'] = {}
    for a, b in (('hd', 'fip'), ('hd', 'ra9'), ('fip', 'ra9'), ('hd', 'xfip')):
        p = paired(col(pool, tab, a), col(pool, tab, b), y_, w_); show(f'{a} v {b}', p, 5, (a, b)); res['ros'][f'{a}_{b}'] = p

    print('\n== HISTORY-DEFINED CLASSES, honest next season')
    res['classes'] = {}
    for name, gate, sel in (('starters 120+ IP, share .5+', 120, lambda r: r['s'] >= .5), ('relievers 40+ IP, share under .2', 40, lambda r: r['s'] < .2)):
        pool = next_pool(gate, sel); y_, w_ = ys(pool)
        p = paired(col(pool, FULL, 'hd'), col(pool, FULL, 'fip'), y_, w_); show(name, p, 4, ('hd', 'fip')); res['classes'][name] = p

    print('\n== DISAGREEMENT SET: the 50 pitchers per season (base 60+ IP) where hd and fip differ most, honest target')
    pool = next_pool(60); dis = {}
    for y in pool:
        idx = [i for i, p in enumerate(pool[y]['ids']) if FULL[y][p]['hd'] is not None]
        top = sorted(idx, key=lambda i: -abs(FULL[y][pool[y]['ids'][i]]['hd'] - FULL[y][pool[y]['ids'][i]]['fip']))[:50]
        dis[y] = dict(ids=[pool[y]['ids'][i] for i in top], y=[pool[y]['y'][i] for i in top], w=[pool[y]['w'][i] for i in top])
    y_, w_ = ys(dis); p = paired(col(dis, FULL, 'hd'), col(dis, FULL, 'fip'), y_, w_); show('hd v fip on the disagreement set', p, 4, ('hd', 'fip')); res['disagree'] = p

    print('\n== BLEND SWEEP (hdERA + w (other - hdERA)), honest; r by w. Forward objectives only: a forecast win is not a description win')
    GRID = [i / 10 for i in range(11)]; res['blend'] = {}
    npool = next_pool(30); rpool, rtab = ros_pool(); ny, nw = ys(npool); ry, rw = ys(rpool)
    for other in ('fip', 'xfip'):
        cur = {'next': [], 'ros': []}
        for w in GRID:
            nx = {y: list(np.array(col(npool, FULL, 'hd')[y], float) + w * (np.array(col(npool, FULL, other)[y], float) - np.array(col(npool, FULL, 'hd')[y], float))) for y in npool}
            rx = {y: list(np.array(col(rpool, rtab, 'hd')[y], float) + w * (np.array(col(rpool, rtab, other)[y], float) - np.array(col(rpool, rtab, 'hd')[y], float))) for y in rpool}
            cur['next'].append([wr(nx[y], ny[y], nw[y]) for y in npool]); cur['ros'].append([wr(rx[y], ry[y], rw[y]) for y in rpool])
        nm = np.array(cur['next']); rm = np.array(cur['ros'])
        print(f'  {other}: w      ' + ' '.join(f'{w:5.1f}' for w in GRID)); print('    next       ' + ' '.join(f'{v:.3f}' for v in nm.mean(axis=1))); print('    ros        ' + ' '.join(f'{v:.3f}' for v in rm.mean(axis=1)))
        print(f'    best next w {GRID[int(nm.mean(axis=1).argmax())]}, best ros w {GRID[int(rm.mean(axis=1).argmax())]}')
        lo = {}
        for j, y in enumerate(sorted(npool)):
            tr = [i for i in range(nm.shape[1]) if i != j]; k = int(nm[:, tr].mean(axis=1).argmax()); lo[y] = (GRID[k], float(nm[k, j] - nm[0, j]))
        print('    LOSO next: chosen w and gain over w=0: ' + ' '.join(f'{y} {a}:{b:+.3f}' for y, (a, b) in lo.items()) + f"  mean {np.mean([b for _, b in lo.values()]):+.3f}, wins {sum(b > 0 for _, b in lo.values())}/5")
        lo2 = {}
        for j, y in enumerate(sorted(rpool)):
            tr = [i for i in range(rm.shape[1]) if i != j]; k = int(rm[:, tr].mean(axis=1).argmax()); lo2[y] = (GRID[k], float(rm[k, j] - rm[0, j]))
        print('    LOSO ros:  chosen w and gain over w=0: ' + ' '.join(f'{y} {a}:{b:+.3f}' for y, (a, b) in lo2.items()) + f"  mean {np.mean([b for _, b in lo2.values()]):+.3f}, wins {sum(b > 0 for _, b in lo2.values())}/6")
        res['blend'][other] = dict(grid=GRID, next=nm.tolist(), ros=rm.tolist(), loso_next=lo, loso_ros=lo2)

    print('\n== N0_XW SWEEP, honest (shipped 250)')
    res['n0'] = {}
    for n0 in (0, 50, 100, 150, 250, 400, 600, 1000, 1500, 2500):
        tabn = {y: rates_full(y, n0=n0) for y in SEASONS}; rp, rt = ros_pool(n0=n0)
        n_ = [wr(col(npool, tabn, 'hd')[y], ny[y], nw[y]) for y in npool]; r_ = [wr(col(rp, rt, 'hd')[y], ys(rp)[0][y], ys(rp)[1][y]) for y in rp]
        print(f'  N0 {n0:5d}: next {np.mean(n_):.4f}  ros {np.mean(r_):.4f}', flush=True); res['n0'][n0] = dict(next=n_, ros=r_)

    print('\n== GAP FLAG: slope and r of (RA9_T - RA9_Y) on (rate_Y - RA9_Y), base 60+ IP, honest target, IP_T weighted')
    res['gap'] = {}
    pool = next_pool(60)
    for k in ('hd', 'fip', 'xfip'):
        sl, rr = [], []
        for y in pool:
            ids = pool[y]['ids']; g = np.array([(FULL[y][p][k] if FULL[y][p][k] is not None else np.nan) - FULL[y][p]['ra9'] for p in ids], float)
            ch = np.array([TAB[y + 1][p]['r'] * 27 / TAB[y + 1][p]['outs'] - (FULL[y][p]['ra9'] - LG[y]['ra9'] + LG[y + 1]['ra9']) for p in ids]); w = np.array(pool[y]['w'])
            m = np.isfinite(g); sl.append(W.wls_slope(g[m], ch[m], w[m])); rr.append(wr(g[m], ch[m], w[m]))
        print(f"  {k:5s} slope {np.mean(sl):.3f} (" + ' '.join(f'{v:.2f}' for v in sl) + f")  r {np.mean(rr):.3f} (" + ' '.join(f'{v:.2f}' for v in rr) + ')'); res['gap'][k] = dict(slope=sl, r=rr)

    # ---------------- WAR level, real FanGraphs
    print('\n== WAR LEVEL: reconstructed hdWAR and RA9-WAR against real FanGraphs WAR')
    FG = {y: {str(int(r['xMLBAMID'])): r for r in json.load(open(os.path.join(D, '_proj', 'fg', f'actual_{y}_pit.json'))) if r.get('xMLBAMID')} for y in SEASONS}

    GAMES = {}
    for y in SEASONS:
        if y == 2026:
            s = json.load(open(os.path.join(D, '_hwar_team', 'standings_2026_by_id.json'))); GAMES[y] = sum(v['g'] for v in s.values()) / 2
        else:
            st = json.load(open(os.path.join(D, '_hwar_team', f'standings_{y}.json'))); GAMES[y] = sum(t['wins'] + t['losses'] for rec in st['records'] for t in rec['teamRecords']) / 2

    def war_table(y, key):
        """Shipped hdWAR formula on any rate: shift to the league mean, RAA scale only on the deserved rate, role bars pinned."""
        lg = LG[y]; f = FULL[y]; rpw = lg['rpw']; ids = [p for p, r in f.items() if r[key] is not None and r['ip'] > 0]
        ipw = sum(f[p]['ip'] for p in ids); shift = lg['ra9'] - sum(f[p][key] * f[p]['ip'] for p in ids) / ipw
        sc = WAR_RAA_SCALE if key == 'hd' else 1.0
        target = (1 - WAR_POOL_SHARE_HITTERS) * WAR_POOL * GAMES[y] / WAR_POOL_GAMES
        ip9 = sum(f[p]['ip'] / 9 for p in ids); rp = sum((1 - f[p]['s']) * f[p]['ip'] / 9 for p in ids)
        rs = (target + (WAR_ROLE_GAP / rpw) * rp) / ip9; rr = rs - WAR_ROLE_GAP / rpw
        return {p: sc * (lg['ra9'] - (f[p][key] + shift)) * f[p]['ip'] / 9 / rpw + (rr + (rs - rr) * f[p]['s']) * f[p]['ip'] / 9 for p in ids}

    HD = {y: war_table(y, 'hd') for y in SEASONS}; RAW = {y: war_table(y, 'ra9') for y in SEASONS}; FW = {y: {p: float(r['WAR']) for p, r in FG[y].items() if r.get('WAR') is not None} for y in SEASONS}
    ship = json.load(open(os.path.join(D, 'pitcher_leaderboard_rs.json'))); sh = {}
    for r in ship:
        t = str(r.get('team'))
        if t in ('ROC', 'AAA') or r.get('hWAR') is None or not r.get('mlbId'):
            continue
        if t.endswith('TM') or str(r['mlbId']) not in sh:
            sh[str(r['mlbId'])] = r['hWAR']
    ks = [p for p in sh if p in HD[2026]]; a = np.array([sh[p] for p in ks]); b = np.array([HD[2026][p] for p in ks])
    print(f'  check: reconstructed 2026 hdWAR vs shipped: n {len(ks)}, r {np.corrcoef(a, b)[0, 1]:.4f}, mean abs diff {np.abs(a - b).mean():.3f}, max {np.abs(a - b).max():.2f}, sums {a.sum():.1f} / {b.sum():.1f}')
    res['war_check'] = dict(n=len(ks), r=float(np.corrcoef(a, b)[0, 1]), mad=float(np.abs(a - b).mean()), max=float(np.abs(a - b).max()))
    if res['war_check']['r'] < .97:
        raise SystemExit('the hdWAR reconstruction misses shipped 2026; stop and find out why')
    res['war'] = {}
    pool_ids = {y: [p for p, r in FULL[y].items() if r['ip'] >= 30 and p in FW[y] and p in HD[y] and p in RAW[y]] for y in SEASONS[:-1]}
    for tname, TT in (('RA9-WAR', RAW), ('fWAR', FW), ('hdWAR', HD)):
        tgt = {y: [TT[y + 1].get(p, 0.0) for p in pool_ids[y]] for y in pool_ids}; w1 = {y: [1.0] * len(pool_ids[y]) for y in pool_ids}
        hdc = {y: [HD[y][p] for p in pool_ids[y]] for y in pool_ids}; fc = {y: [FW[y][p] for p in pool_ids[y]] for y in pool_ids}; rc = {y: [RAW[y][p] for p in pool_ids[y]] for y in pool_ids}
        p = paired(hdc, fc, tgt, w1); show(f'total T {tname}: hdWAR_Y v fWAR_Y', p, 4, ('hd', 'f')); res['war'][f'{tname}_hd_f'] = p
        p = paired(hdc, rc, tgt, w1); show(f'total T {tname}: hdWAR_Y v RA9WAR_Y', p, 4, ('hd', 'ra')); res['war'][f'{tname}_hd_ra'] = p

    # ---------------- club description
    print('\n== CLUB DESCRIPTION: club RA above league on the summed rate runs, FRV and park (same season). Diagnostic: RA9 itself would read 1 and r 1 by construction')
    res['club'] = {}
    in_y = {}
    for y in SEASONS[:-1]:
        fn = os.path.join(OUT, f'in_{y}.pkl')
        if os.path.exists(fn):
            in_y[y] = pickle.load(open(fn, 'rb'))['pclub']
    if len(in_y) == 5:
        fits = {k: [] for k in ('hd', 'fip', 'xfip')}
        for y in in_y:
            st = json.load(open(os.path.join(D, '_hwar_team', f'standings_{y}.json'))); teams = {t['team']['id']: t for rec in st['records'] for t in rec['teamRecords']}
            frv = json.load(open(os.path.join(D, '_hwar_team', f'frv_{y}.json'))); fld = defaultdict(float)
            for v in frv.values():
                if v.get('total') is not None and v.get('team_id') is not None:
                    fld[int(v['team_id'])] += v['total']
            pf = W.PF.get(str(y), {}); g = FULL[y]; share = defaultdict(dict)
            for (p, c), n in in_y[y].items():
                share[p][int(c)] = n
            lgrg = LG[y]['ra9'] * sum(r['outs'] for r in TAB[y].values()) / 27 / sum(t['wins'] + t['losses'] for t in teams.values())
            for k in fits:
                runs = defaultdict(float); xx = {p: g[p][k] for p in g if g[p][k] is not None}; ipw = sum(g[p]['ip'] for p in xx); mean = sum(xx[p] * g[p]['ip'] for p in xx) / ipw
                for p, v in xx.items():
                    s = share.get(p)
                    if not s:
                        continue
                    tot = sum(s.values())
                    for c, n in s.items():
                        runs[c] += (mean - v) * g[p]['ip'] / 9 * n / tot
                X, Y = [], []
                for c, t in teams.items():
                    gm = t['wins'] + t['losses']; X.append((runs[c], fld[c], ((pf.get(str(c), 100) / 100 + 1) / 2 - 1) * lgrg * gm)); Y.append(t['runsAllowed'] - lgrg * gm)
                X, Y = np.array(X), np.array(Y); A = np.column_stack([np.ones(len(Y)), X]); bb = np.linalg.lstsq(A, Y, rcond=None)[0]; res_ = Y - A @ bb
                fits[k].append(dict(y=y, slope=float(bb[1]), rmse=float(res_.std(ddof=4)), r2=float(1 - (res_ ** 2).sum() / ((Y - Y.mean()) ** 2).sum())))
        for k in fits:
            print(f"  {k:5s} slope " + ' '.join(f"{f['slope']:+.2f}" for f in fits[k]) + '  rmse ' + ' '.join(f"{f['rmse']:.1f}" for f in fits[k]) + f"   mean rmse {np.mean([f['rmse'] for f in fits[k]]):.1f}, mean R2 {np.mean([f['r2'] for f in fits[k]]):.3f}")
        res['club'] = fits
    else:
        print('  skipped: inputs not built yet')

    # ---------------- hpWAR
    if '--no-hp' not in sys.argv:
        print('\n== hpWAR RUN MODEL (held out, no EV channel) against one season of hd, same pool: base 30+ IP, target any, IP_T weighted, T 2022-2026')
        import pit_class_calibration as pcc
        with contextlib.redirect_stdout(io.StringIO()):
            recs = pcc.heldout_records(min_ip_t=0)
        pr = {(r['T'], str(r['pid'])): r for r in recs}
        pool = {};
        for y in SEASONS[:-1]:
            base = next_pool(30)[y]; keep = [i for i, p in enumerate(base['ids']) if (y + 1, p) in pr and FULL[y][p]['hd'] is not None]
            pool[y] = dict(ids=[base['ids'][i] for i in keep], y=[base['y'][i] for i in keep], w=[base['w'][i] for i in keep])
        y_, w_ = ys(pool); projc = {y: [pr[(y + 1, p)]['pred'] for p in pool[y]['ids']] for y in pool}
        for other in ('hd', 'fip', 'ra9'):
            p = paired(projc, col(pool, FULL, other), y_, w_); show(f'hp v {other}', p, 4, ('hp', other)); res[f'hp_{other}'] = p
        # nested: fit RA9_T on proj + hd on the other seasons, score the held-out season
        out = []
        for y in pool:
            tr = [s for s in pool if s != y]
            X = np.vstack([np.column_stack([projc[s], col(pool, FULL, 'hd')[s]]) for s in tr]); Y = np.concatenate([np.array(pool[s]['y']) for s in tr]); W_ = np.concatenate([np.array(pool[s]['w']) for s in tr])
            A = np.column_stack([np.ones(len(Y)), X]) * np.sqrt(W_)[:, None]; bb = np.linalg.lstsq(A, Y * np.sqrt(W_), rcond=None)[0]
            Xh = np.column_stack([projc[y], col(pool, FULL, 'hd')[y]]); pred = bb[0] + Xh @ bb[1:]
            Ah = np.column_stack([np.ones(len(Y)), X[:, 0]]) * np.sqrt(W_)[:, None]; b0 = np.linalg.lstsq(Ah, Y * np.sqrt(W_), rcond=None)[0]; pred0 = b0[0] + b0[1] * np.array(projc[y])
            yy = np.array(pool[y]['y']); ww = np.array(pool[y]['w'])
            out.append(dict(y=y, beta_proj=float(bb[1]), beta_hd=float(bb[2]), mse=float(np.average((yy - pred) ** 2, weights=ww)), mse0=float(np.average((yy - pred0) ** 2, weights=ww))))
        d = np.array([1 - o['mse'] / o['mse0'] for o in out])
        print('  nested, projection + hd, held out: ' + ' '.join(f"{o['y'] + 1}: b_hd {o['beta_hd']:+.2f}, MSE gain {100 * (1 - o['mse'] / o['mse0']):+.2f}%" for o in out) + f'  mean {100 * d.mean():+.2f}%, wins {(d > 0).sum()}/5'); res['hp_nested'] = out

    with open(os.path.join(OUT, 'pitchers.json.tmp'), 'w') as f:
        json.dump(res, f, indent=1, default=float)
    os.replace(os.path.join(OUT, 'pitchers.json.tmp'), os.path.join(OUT, 'pitchers.json'))
    print('\nwrote data/_war_honest/pitchers.json')


if __name__ == '__main__':
    main()
