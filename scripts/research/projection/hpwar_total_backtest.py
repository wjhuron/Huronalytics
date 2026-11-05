"""hpwar_total_backtest.py: the ASSEMBLED hpWAR against actual WAR and Steamer WAR (2026-11-04). Research only.

Each part of hpWAR was backtested alone. This scores the sum, one season out, held out by target season.
Hitters: rate per 600 PA = batting (bat_experience_test exper+aaa, setting chosen leaving T out; the 2026-11-03 catcher term is NOT in it) + baserunning (sprint x OBP
history, slope fit leaving T out on FanGraphs BaseRunning per PA) + fielding (FRV history form from h2h_fld_bsr) + positional (base season's innings at the compressed table) + replacement.
Pitchers: pit_class_calibration.heldout_records (no EV channel, added 2026-11-02), role from the BASE-season start share as production does, WAR formula from project_players.
Playing time: pt_backtest full arm, refit leaving T out. Total = rate x projected PT.
Truth: T WAR, and a player absent in T scores 0 in the total test. Rate test: T WAR per 600 PA or per 180 IP, target PT weighted, >= 1 PA or out in T.
Pools: a player with MLB history in T-1..T-3 whom BOTH systems project. T 2018, 2019, 2021-2025 where Steamer exists (T 2020 is not a target). T 2026 has no Steamer here.
Candidates: hp, steamer, fw1 (last season's fWAR), marcel (5/4/3 weighted fWAR), hd1 (last season's hdWAR, T 2022+), blend (hp + steamer, even).
Rule, written before the run: A beats B on r at gap over 2 paired-bootstrap SE and most replicates (4/5, 5/7). RMSE and calibration slope are reported, not decisive. Each system is centered on
the pool's mean actual WAR per season for the slope; RMSE is uncentered for the total, because a total is meant to be read at face value.
Usage: PYTHONHASHSEED=0 python3 scripts/research/projection/hpwar_total_backtest.py
Output: console + data/_war_honest/hpwar_total.json
"""
import contextlib, io, json, math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'era')); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'hitter'))
from pipeline.hwar import HWAR_POS_ADJ, HWAR_POS_SPREAD, HWAR_POS_INNINGS
import bat_experience_test as bx
import pt_backtest as PT
import h2h_fld_bsr as HF
import war_rate_validation as W

P = bx.v1.P; D = os.path.join(ROOT, 'data'); OUT = os.path.join(D, '_war_honest'); NB = 2000
T_ALL = [2018, 2019, 2021, 2022, 2023, 2024, 2025, 2026]
META = json.load(open(os.path.join(D, 'metadata_rs.json')))
HC = META['hwarConstants']; EW = META['eraPlusConstants']['war']; RPW, REPL_PA, SCALE = HC['rpw'], HC['replPerPa'], HC['wobaScale']; REPL_SP, REPL_RP, LGRA9 = EW['replSp'], EW['replRp'], EW['lgRA9']


def wr(x, y, w=None):
    x, y = np.asarray(x, float), np.asarray(y, float); w = np.ones(len(x)) if w is None else np.asarray(w, float)
    m = np.isfinite(x) & np.isfinite(y) & (w > 0); x, y, w = x[m], y[m], w[m]; mx, my = np.average(x, weights=w), np.average(y, weights=w); dx, dy = x - mx, y - my
    return float(np.sum(w * dx * dy) / math.sqrt(np.sum(w * dx * dx) * np.sum(w * dy * dy)))


def paired(rows, a, b, tgt, w=None):
    rng = np.random.default_rng(0); Ts = sorted(rows); gaps, ra, rb = [], [], []; draws = np.zeros((NB, len(Ts)))
    for j, T in enumerate(Ts):
        R = [r for r in rows[T] if r.get(a) is not None and r.get(b) is not None and r.get(tgt) is not None and np.isfinite(r[a]) and np.isfinite(r[b])]
        A, B, Y = (np.array([r[k] for r in R], float) for k in (a, b, tgt)); Wt = np.array([r[w] for r in R], float) if w else np.ones(len(R))
        ra.append(wr(A, Y, Wt)); rb.append(wr(B, Y, Wt)); n = len(R)
        for i in range(NB):
            ix = rng.integers(0, n, n); draws[i, j] = wr(A[ix], Y[ix], Wt[ix]) - wr(B[ix], Y[ix], Wt[ix])
    gap = np.array(ra) - np.array(rb)
    return dict(a=float(np.mean(ra)), b=float(np.mean(rb)), gap=float(gap.mean()), se=float(draws.mean(axis=1).std()), wins=int((gap > 0).sum()), n=len(Ts), per_a=ra, per_b=rb, T=Ts)


def show(lab, p, an, bn):
    need = math.ceil(p['n'] * .7); tag = 'TIE'
    if abs(p['gap']) > 2 * p['se']:
        tag = an if p['gap'] > 0 and p['wins'] >= need else bn if p['gap'] < 0 and p['n'] - p['wins'] >= need else 'TIE'
    print(f"  {lab:40s} {an} {p['a']:.3f}  {bn} {p['b']:.3f}  gap {p['gap']:+.3f} (SE {p['se']:.3f})  wins {p['wins']}/{p['n']}  -> {tag}", flush=True)


def fg(system, T, side):
    fn = os.path.join(P, 'fg', f'{system}_{T}_{side}.json')
    if not os.path.exists(fn):
        return {}
    return {int(r['xMLBAMID']): r for r in json.load(open(fn)) if r.get('xMLBAMID')}


def pt_heldout(side):
    S = {y: (PT.pitch_season if side == 'pit' else PT.hit_season)(y) for y in range(PT.TARGETS[0] - 3, 2027)}; A = {y: PT.aaa_pt(y, 'outs' if side == 'pit' else 'plateAppearances') for y in S}
    R = {T: PT.rows(side, S, A, T - 1) for T in PT.TARGETS}; cols = PT.ARMS[side]['full']; out = {}
    for T in PT.TARGETS:
        tr = [t for t in PT.TARGETS if t != T]; X = np.vstack([PT.design(R[t], cols) for t in tr]); Y = np.concatenate([np.array([y for _, _, y in R[t]]) for t in tr]); b = np.linalg.lstsq(X, Y, rcond=None)[0]
        p = np.clip(PT.design(R[T], cols) @ b, 0, Y.max()); out[T] = {pid: float(v) for (pid, _, _), v in zip(R[T], p)}
    return out


def bat_projection():
    """exper+aaa with the setting chosen leaving T out, on every player with history, played in T or not."""
    v1, hb = bx.v1, bx.hb
    X = {y: v1.load_xstats(y) for y in range(2015, 2027)}; LG = {y: v1.league(X[y]) for y in X}; AG = {y: v1.load_ages(y) for y in range(2015, 2027)}; Aaa, Mlb = hb.season_tables()
    chosen = {h['T']: h['chosen'] for h in json.load(open(os.path.join(P, '_bat_experience_test.json')))['exper+aaa']['held']}; out = {}
    for T in bx.TARGETS:
        ids = set().union(*[set(X[T - 1 - k]) for k in range(3)]); rows = []
        for pid in ids:
            ag = AG[T].get(pid) or None
            if ag is None:
                for k in range(1, 4):
                    g = AG[T - k].get(pid)
                    if g:
                        ag = (g[0] + k, g[1]); break
            if ag is None or ag[1] == 'P':
                continue
            hist = []
            for k in range(3):
                v = X[T - 1 - k].get(pid); hist.append((v[0], v[1] - LG[T - 1 - k][0], v[2] - LG[T - 1 - k][1]) if v else (0, 0.0, 0.0))
            E = sum(h[0] for h in hist)
            if E == 0:
                continue
            aaa = None
            for y in (T - 1, T - 2):
                if y in Aaa and pid in Aaa[y][0]:
                    aaa = (y, Aaa[y][0][pid], Mlb[y][0].get(pid)); break
            t = X[T].get(pid); rows.append({'id': pid, 'age': ag[0], 'pa': t[0] if t else 0, 'y': (t[1] - LG[T][0]) if t else 0.0, 'hist': hist, 'E': E, 'aaa': aaa})
        Z = bx.arrays(rows, bx.bridge_beta(Aaa, Mlb, T)); p = bx.project(Z, *chosen[T]); out[T] = {r['id']: float(v) for r, v in zip(rows, p)}
    return out


def hitters():
    print('== HITTERS: building'); res = {}
    bat = bat_projection()
    with contextlib.redirect_stdout(io.StringIO()):
        pt = pt_heldout('hit')
    SP = {y: HF.sprint(y) for y in range(2015, 2027)}; FRV = {y: json.load(open(os.path.join(P, f'frv_{y}.json'))) for y in range(2015, 2027) if os.path.exists(os.path.join(P, f'frv_{y}.json'))}
    LN = {y: {r['id']: r for r in json.load(open(os.path.join(P, f'lines_hitting_{y}.json')))} for y in range(2014, 2027)}

    def posr(y):
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
            tot[pos] += ii; rec.append((int(sp['player']['id']), pos, ii))
        c = sum(tot[p] * HWAR_POS_ADJ[p] for p in tot) / sum(tot.values()); tab = {p: c + HWAR_POS_SPREAD * (HWAR_POS_ADJ[p] - c) for p in HWAR_POS_ADJ}; o = defaultdict(float)
        for pid, p, ii in rec:
            o[pid] += ii * tab[p] / HWAR_POS_INNINGS
        return o
    POS = {y: posr(y) for y in range(2017, 2026)}
    ACT = {y: fg('actual', y, 'bat') for y in range(2015, 2027)}
    rows = {}; raw = []
    for T in T_ALL:
        st = fg('steamer', T, 'bat'); out = []
        for pid, b in bat[T].items():
            sn = sd = 0.0; ob = obd = 0.0; fn = fdn = on = od = 0.0
            for k in range(3):
                y = T - 1 - k; v = SP[y][0].get(pid)
                if v and v[1] > 0:
                    sn += .3 ** k * v[1] * (v[0] - SP[y][1]); sd += .3 ** k * v[1]
                l = LN[y].get(pid)
                if l:
                    g = lambda c: int(l.get(c) or 0)
                    ob += g('hits') + g('baseOnBalls') + g('hitByPitch'); obd += g('atBats') + g('baseOnBalls') + g('hitByPitch') + g('sacFlies')
                f = FRV.get(y, {}).get(str(pid)); pa = int((l or {}).get('plateAppearances') or 0)
                if f and f.get('total') is not None and sum(f['outs_by_pos'].values()) > 0:
                    o = sum(f['outs_by_pos'].values()); fn += .55 ** k * 1000 * f['total']; fdn += .55 ** k * o
                    if pa:
                        on += .55 ** k * o; od += .55 ** k * pa
                elif pa:
                    od += .55 ** k * pa
            age = (LN[T - 1].get(pid) or LN[T - 2].get(pid) or {}).get('age') or 28; age += 1
            f1000 = (fn + 2000 * -1.0) / (fdn + 2000) + (.05 * (34 - age) if age < 34 else -.2 * (age - 34)); opa = min(on / od, 6.47) if od else 0.0
            spd = (sn / (sd + 1) - .2) if sd > 0 else None; obp = ob / obd if obd else None
            l1 = LN[T - 1].get(pid); pa1 = int((l1 or {}).get('plateAppearances') or 0); a = ACT[T].get(pid) or {}; a1 = ACT[T - 1].get(pid) or {}; a2 = ACT[T - 2].get(pid) or {}; a3 = ACT[T - 3].get(pid) or {}
            s = st.get(pid); n1 = float(a1.get('PA') or 0.0)
            r = dict(pid=pid, T=T, bat600=b / SCALE * 600, bsr_x=(spd * obp) if (spd is not None and obp) else 0.0, fld600=f1000 / 1000 * opa * 600, pos600=(POS[T - 1].get(pid, 0.0) * 600 / pa1) if pa1 and T - 1 in POS else 0.0,
                     pt=pt.get(T, {}).get(pid), s_war=float(s['WAR']) if s and s.get('WAR') is not None else None, s_pa=float(s['PA']) if s and s.get('PA') else None, wT=float(a.get('WAR') or 0.0), paT=float(a.get('PA') or 0.0),
                     bsrT=float(a.get('BaseRunning') or 0.0), fw1=float(a1.get('WAR') or 0.0), marcel=(5 * float(a1.get('WAR') or 0.0) + 4 * float(a2.get('WAR') or 0.0) + 3 * float(a3.get('WAR') or 0.0)) / 12, pa1=n1)
            out.append(r); raw.append(r)
        rows[T] = out
    # baserunning slope leaving T out
    for T in T_ALL:
        tr = [r for r in raw if r['T'] != T and r['paT'] >= 100]; x = np.array([r['bsr_x'] for r in tr]); y = np.array([r['bsrT'] / r['paT'] for r in tr]); w = np.array([r['paT'] for r in tr]); b = np.sum(w * x * y) / np.sum(w * x * x)
        for r in rows[T]:
            r['bsr600'] = b * r['bsr_x'] * 600
    for T in rows:
        for r in rows[T]:
            r['hp600'] = (r['bat600'] + r['bsr600'] + r['fld600'] + r['pos600'] + REPL_PA * 600) / RPW
            r['hp'] = r['hp600'] * r['pt'] / 600 if r['pt'] is not None else None; r['s600'] = r['s_war'] * 600 / r['s_pa'] if r['s_war'] is not None and r['s_pa'] else None
            r['fw1_600'] = r['fw1'] * 600 / r['pa1'] if r['pa1'] >= 50 else None; r['wT600'] = r['wT'] * 600 / r['paT'] if r['paT'] >= 1 else None
            r['blend'] = (r['hp'] + r['s_war']) / 2 if r['hp'] is not None and r['s_war'] is not None else None; r['blend600'] = (r['hp600'] + r['s600']) / 2 if r['s600'] is not None else None
    for T in rows:
        for r in rows[T]:
            r['hp_spt'] = r['hp600'] * r['s_pa'] / 600 if r['s_pa'] else None
            r['s_opt'] = r['s600'] * r['pt'] / 600 if r['s600'] is not None and r['pt'] is not None else None
    m = {T: [r for r in rows[T] if r['s_war'] is not None and r['hp'] is not None] for T in T_ALL if T != 2026}; print('  matched pool: ' + ' '.join(f'{T}:{len(m[T])}' for T in m))
    for T in m:
        k = sum(r['pt'] for r in m[T]) / sum(r['s_pa'] for r in m[T])
        for r in m[T]:
            r['pt_c'] = r['s_pa'] * k; r['hp_c'] = r['hp600'] * r['pt_c'] / 600; r['hp_mix'] = r['hp600'] * (r['pt'] + r['pt_c']) / 2 / 600
    print('  CALIBRATED Steamer PT (Steamer ranks, our sum sets the level): k per T ' + ' '.join(f"{T}:{sum(r['pt'] for r in m[T]) / sum(r['s_pa'] for r in m[T]):.3f}" for T in m))
    print('  sum of WAR, actual | ours | raw Steamer PT | calibrated | mix: ' + ' ; '.join(f"{T}: {sum(r['wT'] for r in m[T]):.0f} | {sum(r['hp'] for r in m[T]):.0f} | {sum(r['hp_spt'] for r in m[T]):.0f} | {sum(r['hp_c'] for r in m[T]):.0f} | {sum(r['hp_mix'] for r in m[T]):.0f}" for T in m))
    print('  RMSE / slope, all T: ' + ' | '.join(f"{k_} {np.mean([math.sqrt(np.mean([(r[k_] - r['wT']) ** 2 for r in m[T]])) for T in m]):.3f} / {np.mean([np.polyfit([r[k_] for r in m[T]], [r['wT'] for r in m[T]], 1)[0] for T in m]):.2f}" for k_ in ('hp', 'hp_spt', 'hp_c', 'hp_mix', 's_war')))
    print('  PLAYING TIME: mean r with T PA, ours ' + f"{np.mean([wr([r['pt'] for r in m[T]], [r['paT'] for r in m[T]]) for T in m]):.3f}, Steamer {np.mean([wr([r['s_pa'] or 0.0 for r in m[T]], [r['paT'] for r in m[T]]) for T in m]):.3f}")
    print('  league check, sum of hp total v sum of actual fWAR: ' + ' '.join(f'{T}: {sum(r["hp"] for r in m[T]):.0f} v {sum(r["wT"] for r in m[T]):.0f}' for T in m))
    mb = {T: m[T] for T in m if T >= 2021}
    print('\n  TOTAL WAR, absent = 0'); res['total'] = {}
    for a, b in (('hp', 's_war'), ('hp', 'fw1'), ('hp', 'marcel'), ('s_war', 'marcel'), ('blend', 'hp'), ('blend', 's_war'), ('hp_spt', 's_war'), ('hp_spt', 'hp'), ('s_opt', 's_war'), ('hp_c', 'hp'), ('hp_mix', 'hp'), ('hp_c', 'hp_mix'), ('hp_c', 's_war')):
        p = paired(mb if b in ('fw1', 'marcel') else m, a, b, 'wT'); show(f'{a} v {b}' + (' (T 2021+, FanGraphs history starts 2018)' if b in ('fw1', 'marcel') else ''), p, a, b); res['total'][f'{a}_{b}'] = p
    print('  RMSE and slope, total, T 2021+: ' + ' | '.join(f"{k} {np.mean([math.sqrt(np.mean([(r[k] - r['wT']) ** 2 for r in mb[T]])) for T in mb]):.3f} / {np.mean([np.polyfit([r[k] for r in mb[T]], [r['wT'] for r in mb[T]], 1)[0] for T in mb]):.2f}" for k in ('hp', 's_war', 'blend', 'marcel', 'fw1')))
    print('\n  RATE, WAR per 600 PA, target PA weighted, 1+ PA'); mr = {T: [r for r in m[T] if r['wT600'] is not None and r['s600'] is not None] for T in m}; res['rate'] = {}
    for a, b in (('hp600', 's600'), ('blend600', 'hp600')):
        p = paired(mr, a, b, 'wT600', 'paT'); show(f'{a} v {b}', p, a, b); res['rate'][f'{a}_{b}'] = p
    mf = {T: [r for r in mr[T] if r['fw1_600'] is not None] for T in mr if T >= 2021}; p = paired(mf, 'hp600', 'fw1_600', 'wT600', 'paT'); show('hp600 v fw1_600 (50+ PA base)', p, 'hp', 'f1'); res['rate']['hp_fw1'] = p
    print('\n  REGULARS by history: 400+ PA in T-1, total WAR'); mg = {T: [r for r in m[T] if r['pa1'] >= 400] for T in mb if T >= 2022}; res['reg'] = {}   # no hitter reached 400 PA in the 60-game 2020
    for a, b in (('hp', 's_war'), ('hp', 'fw1')):
        p = paired(mg, a, b, 'wT'); show(f'{a} v {b}', p, a, b); res['reg'][f'{a}_{b}'] = p
    # parts: variance and calibration in the rate test
    print('  parts, r with T WAR per 600 (mean): ' + ' '.join(f"{k} {np.mean([wr([r[k] for r in mr[T]], [r['wT600'] for r in mr[T]], [r['paT'] for r in mr[T]]) for T in mr]):.3f}" for k in ('bat600', 'bsr600', 'fld600', 'pos600', 'hp600', 's600')))
    s26 = rows[2026]; s26 = [r for r in s26 if r['hp'] is not None]; print(f"  T 2026, no Steamer: hp total r {wr([r['hp'] for r in s26], [r['wT'] for r in s26]):.3f}, marcel {wr([r['marcel'] for r in s26], [r['wT'] for r in s26]):.3f}, fw1 {wr([r['fw1'] for r in s26], [r['wT'] for r in s26]):.3f}, sum {sum(r['hp'] for r in s26):.0f} v {sum(r['wT'] for r in s26):.0f}")
    return res


def pitchers():
    print('\n== PITCHERS: building'); res = {}
    import pit_class_calibration as pcc
    with contextlib.redirect_stdout(io.StringIO()):
        recs = pcc.heldout_records(min_ip_t=0); pt = pt_heldout('pit')
    pr = defaultdict(dict)
    for r in recs:
        pr[r['T']][int(r['pid'])] = r['pred']
    ACT = {y: fg('actual', y, 'pit') for y in range(2018, 2027)}; rows = {}
    S = {y: {r['id']: r for r in json.load(open(os.path.join(P, f'lines_pitching_{y}.json')))} for y in range(2017, 2027)}
    for T in (2022, 2023, 2024, 2025, 2026):
        st = fg('steamer', T, 'pit'); out = []
        for pid, pred in pr[T].items():
            L = S[T - 1].get(pid) or S[T - 2].get(pid) or S[T - 3].get(pid) or {}; g = int(L.get('gamesPitched') or 0); gs = int(L.get('gamesStarted') or 0); sh = gs / g if g else 0.0; rep = REPL_RP + (REPL_SP - REPL_RP) * sh
            hp9 = -pred / RPW + rep; a = ACT[T].get(pid) or {}; a1 = ACT[T - 1].get(pid) or {}; a2 = ACT[T - 2].get(pid) or {}; a3 = ACT.get(T - 3, {}).get(pid) or {}; s = st.get(pid); p_ = pt.get(T, {}).get(pid)
            ipT = float(a.get('IP') or 0.0); ip1 = float(a1.get('IP') or 0.0); ipT = int(ipT) + (ipT - int(ipT)) * 10 / 3; ip1 = int(ip1) + (ip1 - int(ip1)) * 10 / 3
            r = dict(pid=pid, hp=hp9 * p_ / 9 if p_ is not None else None, hp180=hp9 * 20, s_war=float(s['WAR']) if s and s.get('WAR') is not None else None, s180=(float(s['WAR']) * 180 / float(s['IP'])) if s and s.get('WAR') is not None and s.get('IP') else None, wT=float(a.get('WAR') or 0.0), ipT=ipT, wT180=(float(a.get('WAR') or 0.0) * 180 / ipT) if ipT > 0 else None, fw1=float(a1.get('WAR') or 0.0), marcel=(5 * float(a1.get('WAR') or 0.0) + 4 * float(a2.get('WAR') or 0.0) + 3 * float(a3.get('WAR') or 0.0)) / 12, ip1=ip1, fw1_180=(float(a1.get('WAR') or 0.0) * 180 / ip1) if ip1 >= 30 else None)
            r['blend'] = (r['hp'] + r['s_war']) / 2 if r['hp'] is not None and r['s_war'] is not None else None; r['blend180'] = (r['hp180'] + r['s180']) / 2 if r['s180'] is not None else None
            r['s_ip'] = float(s['IP']) if s and s.get('IP') else None; r['pt'] = p_; r['hp_spt'] = hp9 * r['s_ip'] / 9 if r['s_ip'] else None; r['s_opt'] = r['s_war'] / r['s_ip'] * p_ if r['s_war'] is not None and r['s_ip'] and p_ is not None else None; r['pred'] = pred; r['rep'] = rep
            out.append(r)
        rows[T] = out
    # Target fWAR is FIP-based; also score the runs-allowed target from official lines.
    for T in rows:
        L = S[T]; lg = 27 * sum(int(r.get('runs') or 0) for r in L.values()) / sum(int(r.get('outs') or 0) for r in L.values())
        for r in rows[T]:
            l = L.get(r['pid']); o = int((l or {}).get('outs') or 0)
            r['raT'] = (lg - 27 * int(l.get('runs') or 0) / o) * o / 27 / RPW if o else 0.0   # runs-allowed value above AVERAGE, no replacement; absent 0
    m = {T: [r for r in rows[T] if r['s_war'] is not None and r['hp'] is not None] for T in rows if T != 2026}; print('  matched pool: ' + ' '.join(f'{T}:{len(m[T])}' for T in m))
    for T in m:
        k = sum(r['pt'] for r in m[T]) / sum(r['s_ip'] for r in m[T])
        for r in m[T]:
            hp9 = r['hp'] / r['pt'] * 9 if r['pt'] else -r['pred'] / RPW + r['rep']
            r['pt_c'] = r['s_ip'] * k; r['hp_c'] = hp9 * r['pt_c'] / 9; r['hp_mix'] = hp9 * (r['pt'] + r['pt_c']) / 2 / 9
    print('  CALIBRATED Steamer PT: k per T ' + ' '.join(f"{T}:{sum(r['pt'] for r in m[T]) / sum(r['s_ip'] for r in m[T]):.3f}" for T in m))
    print('  sum of WAR, actual | ours | raw Steamer PT | calibrated | mix: ' + ' ; '.join(f"{T}: {sum(r['wT'] for r in m[T]):.0f} | {sum(r['hp'] for r in m[T]):.0f} | {sum(r['hp_spt'] for r in m[T]):.0f} | {sum(r['hp_c'] for r in m[T]):.0f} | {sum(r['hp_mix'] for r in m[T]):.0f}" for T in m))
    print('  RMSE / slope, T fWAR: ' + ' | '.join(f"{k_} {np.mean([math.sqrt(np.mean([(r[k_] - r['wT']) ** 2 for r in m[T]])) for T in m]):.3f} / {np.mean([np.polyfit([r[k_] for r in m[T]], [r['wT'] for r in m[T]], 1)[0] for T in m]):.2f}" for k_ in ('hp', 'hp_spt', 'hp_c', 'hp_mix', 's_war')))
    print('  PLAYING TIME: mean r with T IP, ours ' + f"{np.mean([wr([r['pt'] for r in m[T]], [r['ipT'] for r in m[T]]) for T in m]):.3f}, Steamer {np.mean([wr([r['s_ip'] or 0.0 for r in m[T]], [r['ipT'] for r in m[T]]) for T in m]):.3f}")
    print('  why the total reads low, per T: IP projected v actual; IP-weighted projected RA9 above league; mean replacement wins per 9: ' + ' | '.join(f"{T}: {sum(r['pt'] for r in m[T]):.0f} v {sum(r['ipT'] for r in m[T]):.0f}; {np.average([r['pred'] for r in m[T]], weights=[r['pt'] + 1e-6 for r in m[T]]):+.2f}; {np.average([r['rep'] for r in m[T]], weights=[r['pt'] + 1e-6 for r in m[T]]):.3f}" for T in m))
    print('  league check, hp v fWAR: ' + ' '.join(f'{T}: {sum(r["hp"] for r in m[T]):.0f} v {sum(r["wT"] for r in m[T]):.0f}' for T in m))
    print('\n  TOTAL, T fWAR, absent = 0'); res['total_f'] = {}
    for a, b in (('hp', 's_war'), ('hp', 'fw1'), ('hp', 'marcel'), ('s_war', 'marcel'), ('blend', 'hp'), ('blend', 's_war'), ('hp_spt', 's_war'), ('hp_spt', 'hp'), ('s_opt', 's_war'), ('hp_c', 'hp'), ('hp_mix', 'hp'), ('hp_c', 'hp_mix'), ('hp_c', 's_war')):
        p = paired(m, a, b, 'wT'); show(f'{a} v {b}', p, a, b); res['total_f'][f'{a}_{b}'] = p
    print('  RMSE and slope, total fWAR: ' + ' | '.join(f"{k} {np.mean([math.sqrt(np.mean([(r[k] - r['wT']) ** 2 for r in m[T]])) for T in m]):.3f} / {np.mean([np.polyfit([r[k] for r in m[T]], [r['wT'] for r in m[T]], 1)[0] for T in m]):.2f}" for k in ('hp', 's_war', 'blend', 'marcel', 'fw1')))
    print('\n  TOTAL, T runs-allowed value above average (the target hpWAR is built to project), absent = 0'); res['total_ra'] = {}
    for a, b in (('hp', 's_war'), ('hp', 'fw1'), ('blend', 'hp'), ('blend', 's_war'), ('hp_spt', 's_war'), ('hp_spt', 'hp'), ('hp_c', 'hp'), ('hp_mix', 'hp'), ('hp_c', 'hp_mix')):
        p = paired(m, a, b, 'raT'); show(f'{a} v {b}', p, a, b); res['total_ra'][f'{a}_{b}'] = p
    print('\n  RATE, WAR per 180 IP, target IP weighted'); mr = {T: [r for r in m[T] if r['wT180'] is not None and r['s180'] is not None] for T in m}; res['rate'] = {}
    for a, b in (('hp180', 's180'), ('blend180', 'hp180')):
        p = paired(mr, a, b, 'wT180', 'ipT'); show(f'{a} v {b}', p, a, b); res['rate'][f'{a}_{b}'] = p
    mf = {T: [r for r in mr[T] if r['fw1_180'] is not None] for T in mr}; p = paired(mf, 'hp180', 'fw1_180', 'wT180', 'ipT'); show('hp180 v fw1_180 (30+ IP base)', p, 'hp', 'f1'); res['rate']['hp_fw1'] = p
    s26 = [r for r in rows[2026] if r['hp'] is not None]; print(f"  T 2026, no Steamer: hp total r {wr([r['hp'] for r in s26], [r['wT'] for r in s26]):.3f}, marcel {wr([r['marcel'] for r in s26], [r['wT'] for r in s26]):.3f}, fw1 {wr([r['fw1'] for r in s26], [r['wT'] for r in s26]):.3f}, sum {sum(r['hp'] for r in s26):.0f} v {sum(r['wT'] for r in s26):.0f}")
    return res


def main():
    res = {'hitters': hitters(), 'pitchers': pitchers()}
    with open(os.path.join(OUT, 'hpwar_total.json.tmp'), 'w') as f:
        json.dump(res, f, indent=1, default=float)
    os.replace(os.path.join(OUT, 'hpwar_total.json.tmp'), os.path.join(OUT, 'hpwar_total.json')); print('\nwrote data/_war_honest/hpwar_total.json')


if __name__ == '__main__':
    main()
