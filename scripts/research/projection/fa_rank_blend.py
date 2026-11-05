"""fa_rank_blend.py: what should a free-agent ranking read, at 1, 3 and 5 seasons? (2026-11-05, per Wally's position rankings). Research only.

Truth: cumulative WAR over T..T+h-1, a player absent from a season scores 0 for it, 2020 restated to 162 games. Hitters: fWAR. Pitchers: fWAR is FIP-based, so a FIP-based forecast wins it by construction;
the primary pitcher truth is the even mean of fWAR and a runs-allowed WAR (same replacement constants), and each side is also reported.
Steamer's pitcher rate is its ERA, centered on our projected level in each T (the rundown's form), not its FIP-based WAR, because the 2027 file holds a 1 IP placeholder WAR for 101 of 237 free agents.
Replicates: every target season held out in turn. T 2020 is not a start. Hitters T 2018-2019, 2021-2025. Pitchers: our rate exists from T 2022; before that the rate is Steamer + ZiPS only.
Pools: base-period gate only (MLB history in T-1..T-3, Steamer exists for T). No gate on T playing time. Scored on all, and on the real free-agent class of T (data/_fa_contracts/dataset.csv).

Part 1, the rate blend at one season: rate = wh ours + ws Steamer + wz ZiPS, total = rate x our playing time. Simplex grid at .1, best chosen leaving T out.
Part 2, other inputs at one season: does last season's fWAR or the Marcel fWAR add to the blend?
Part 3, the multi-year form. Candidates, fit leaving T out, by group:
  M0  h x B                                        B = one-season total, R = blended rate at a full season (600 PA / 180 IP / 60 IP), a = age - 30
  M1  c + B (b0 + b1 a)
  M2  c + B (b0 + b1 a) + R (r0 + r1 a) + d a
  M3  M2 + Marcel fWAR
Caveat: the Steamer and ZiPS history is preseason, so it knows rosters that a November file does not.
Rule, written before the run: A beats B at a gap over 2 paired-bootstrap SE and most replicates, else TIE.

Usage: PYTHONHASHSEED=0 python3 scripts/research/projection/fa_rank_blend.py
Output: console + data/_proj/_fa_rank_blend.json
"""
import contextlib
import csv
import io
import itertools
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hpwar_total_backtest as HB

ROOT, P = HB.ROOT, HB.P
SP = os.path.join(ROOT, 'data', 'steamer_preseason')
NB = 1000
MIN_AGE = 25


def ipf(v):
    v = float(v or 0.0)
    return int(v) + (v - int(v)) * 10 / 3


def preseason(system, T, side):
    fn = os.path.join(SP, f'{system}_{T}_{side}.csv')
    if not os.path.exists(fn):
        return {}
    out = {}
    with open(fn, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            try:
                pt = float(r.get('pa') or r.get('ip') or 0)
                out[int(float(r['mlbam']))] = (float(r['war']), pt)
            except (KeyError, ValueError, TypeError):
                continue
    return out


def actuals(side):
    A = {}
    for y in range(2016, 2027):
        fn = os.path.join(P, 'fg', f'actual_{y}_{side}.json')
        if not os.path.exists(fn):
            fn = os.path.join(ROOT, 'data', '_fa_contracts', f'actual_{y}_{side}.json')
        k = 162 / 60 if y == 2020 else 1.0
        A[y] = {int(r['xMLBAMID']): float(r.get('WAR') or 0.0) * k for r in json.load(open(fn)) if r.get('xMLBAMID')}
    return A


def fa_class():
    out = defaultdict(set)
    with open(os.path.join(ROOT, 'data', '_fa_contracts', 'dataset.csv')) as f:
        for r in csv.DictReader(f):
            if r['mlbam'] and r['outcome'] in ('mlb', 'milb'):
                out[int(r['Y'])].add(int(float(r['mlbam'])))
    return out


def capture(fn):
    """The backtest's first paired() call receives the matched rows. Take them and skip its bootstrap."""
    got = []
    real_p, real_s = HB.paired, HB.show

    def stub(rows, a, b, tgt, w=None):
        if not got:
            got.append(rows)
        return dict(a=0.0, b=0.0, gap=0.0, se=1.0, wins=0, n=1, per_a=[], per_b=[], T=[])
    HB.paired, HB.show = stub, lambda *a, **k: None
    with contextlib.redirect_stdout(io.StringIO()):
        fn()
    HB.paired, HB.show = real_p, real_s
    return got[0]


def wr(x, y):
    return HB.wr(x, y)


def rmse(x, y):
    return float(math.sqrt(np.mean((np.asarray(x) - np.asarray(y)) ** 2)))


def paired_gap(pred_a, pred_b, truth):
    """dict T -> arrays. Mean per-T r gap, bootstrap SE, wins."""
    rng = np.random.default_rng(0); Ts = sorted(truth); g = []; draws = np.zeros((NB, len(Ts)))
    for j, T in enumerate(Ts):
        a, b, y = pred_a[T], pred_b[T], truth[T]; g.append(wr(a, y) - wr(b, y)); n = len(y)
        for i in range(NB):
            ix = rng.integers(0, n, n); draws[i, j] = wr(a[ix], y[ix]) - wr(b[ix], y[ix])
    g = np.array(g)
    return float(g.mean()), float(draws.mean(axis=1).std()), int((g > 0).sum()), len(Ts)


def verdict(gap, se, wins, n, an, bn):
    need = math.ceil(n * .7)
    if abs(gap) > 2 * se and gap > 0 and wins >= need:
        return an
    if abs(gap) > 2 * se and gap < 0 and n - wins >= need:
        return bn
    return 'TIE'


def build(side):
    A = actuals(side)
    if side == 'bat':
        m = capture(HB.hitters)
        rows = []
        for T, R in m.items():
            z = preseason('zips', T, 'bat')
            for r in R:
                zz = z.get(r['pid'])
                rows.append(dict(pid=r['pid'], T=T, hp_rate=r['hp600'] / 600, pt=r['pt'], s_rate=r['s600'] / 600 if r.get('s600') is not None and r['s_pa'] >= 20 else None,
                                 z_rate=zz[0] / zz[1] if zz and zz[1] >= 20 else None, fw1=r['fw1'], marcel=r['marcel'], unit=600.0, group='H'))
        LN = {y: {x['id']: x for x in json.load(open(os.path.join(P, f'lines_hitting_{y}.json')))} for y in range(2014, 2027)}
    else:
        m = capture(HB.pitchers)
        with contextlib.redirect_stdout(io.StringIO()):
            pt = HB.pt_heldout('pit')
        LN = {y: {x['id']: x for x in json.load(open(os.path.join(P, f'lines_pitching_{y}.json')))} for y in range(2014, 2027)}
        rows = []
        for T in (2018, 2019, 2021, 2022, 2023, 2024, 2025):
            s = preseason('steamer', T, 'pit'); z = preseason('zips', T, 'pit')
            hp = {r['pid']: r for r in m.get(T, [])}
            era = {k: float(v['ERA']) for k, v in HB.fg('steamer', T, 'pit').items() if v.get('ERA') is not None}
            common = [(pid, ptv) for pid, ptv in pt.get(T, {}).items() if pid in era and ptv > 0]
            wt = np.array([v for _, v in common]); e_mean = float(np.average([era[q] for q, _ in common], weights=wt))
            # our predicted level above league on the same pool; before T 2022 ours does not exist and Steamer is centered on league
            own = [(hp[q]['pred'], v) for q, v in common if q in hp]
            lvl = float(np.average([a for a, _ in own], weights=[b for _, b in own])) if own else 0.0
            for pid, ptv in pt.get(T, {}).items():
                ss = s.get(pid)
                if not ss:
                    continue
                L = LN[T - 1].get(pid) or LN[T - 2].get(pid) or LN[T - 3].get(pid) or {}
                g_, gs = int(L.get('gamesPitched') or 0), int(L.get('gamesStarted') or 0)
                role = 'SP' if g_ and gs / g_ >= .5 else 'RP'
                unit = 180.0 if role == 'SP' else 60.0
                h = hp.get(pid); zz = z.get(pid)
                rep_ = HB.REPL_SP if role == 'SP' else HB.REPL_RP
                # hp180 / 180 carries the blended start-share replacement rate; put ours on the same role replacement as Steamer
                s_ra = ((-(era[pid] - e_mean) - lvl) / HB.RPW + rep_) / 9 if pid in era else None
                hp_r = (-h['pred'] / HB.RPW + rep_) / 9 if h else None
                a1, a2, a3 = (A.get(T - k, {}).get(pid, 0.0) for k in (1, 2, 3))
                rows.append(dict(pid=pid, T=T, hp_rate=hp_r, pt=ptv, s_rate=s_ra, z_rate=zz[0] / zz[1] if zz and zz[1] >= 10 else None,
                                 fw1=a1, marcel=(5 * a1 + 4 * a2 + 3 * a3) / 12, unit=unit, group=role))
    RA_LG = {y: 27 * sum(int(x.get('runs') or 0) for x in LN[y].values()) / max(1, sum(int(x.get('outs') or 0) for x in LN[y].values())) for y in LN} if side == 'pit' else {}
    for r in rows:
        y0 = r['T']; L = None
        for k in range(1, 4):
            L = LN[y0 - k].get(r['pid'])
            if L:
                break
        r['age'] = (L.get('age') + k) if L and L.get('age') is not None else None
        for h in (1, 3, 5):
            ys = [y0 + k for k in range(h)]
            if ys[-1] > 2026:
                r[f'y{h}'] = r[f'f{h}'] = r[f'ra{h}'] = None
                continue
            f_ = sum(A[y].get(r['pid'], 0.0) for y in ys); r[f'f{h}'] = f_
            if side == 'bat':
                r[f'y{h}'] = f_
            else:
                ra_ = 0.0
                for y in ys:
                    l = LN[y].get(r['pid'])
                    o = int((l or {}).get('outs') or 0)
                    if o:
                        lg, k = RA_LG[y], (162 / 60 if y == 2020 else 1.0)
                        g_, gs = int(l.get('gamesPitched') or 0), int(l.get('gamesStarted') or 0)
                        rp_ = HB.REPL_RP + (HB.REPL_SP - HB.REPL_RP) * (gs / g_ if g_ else 0.0)
                        ra_ += k * ((lg - 27 * int(l.get('runs') or 0) / o) / HB.RPW + rp_) * o / 27
                r[f'ra{h}'] = ra_; r[f'y{h}'] = (f_ + ra_) / 2
    return [r for r in rows if r['age'] is not None and r['age'] >= MIN_AGE and r['pt'] is not None]


def blend_rate(r, w):
    """Weights over the rates a player has. A missing system's weight goes to the others, as in production when Steamer has a placeholder."""
    tot = num = 0.0
    for key, wt in zip(('hp_rate', 's_rate', 'z_rate'), w):
        v = r.get(key)
        if v is not None and wt > 0:
            num += wt * v; tot += wt
    return num / tot if tot else None


def part1(rows, Ts, lab, res):
    pool = {T: [r for r in rows if r['T'] == T and r['hp_rate'] is not None and r['s_rate'] is not None and r['z_rate'] is not None and r['y1'] is not None] for T in Ts}
    pool = {T: v for T, v in pool.items() if v}
    if not pool:
        return None
    grid = [(a / 10, b / 10, (10 - a - b) / 10) for a in range(11) for b in range(11 - a)]
    sc = {}
    for w in grid:
        sc[w] = {T: wr([blend_rate(r, w) * r['pt'] for r in R], [r['y1'] for r in R]) for T, R in pool.items()}
    mean = {w: float(np.mean(list(sc[w].values()))) for w in grid}
    best = max(mean, key=mean.get)
    print(f'\n[{lab}] PART 1: rate blend (ours, Steamer, ZiPS) x our PT, target one-season fWAR. T {sorted(pool)}, n {[len(v) for v in pool.values()]}')
    print('  top of the grid: ' + ' | '.join(f'{w} {mean[w]:.4f}' for w in sorted(mean, key=mean.get, reverse=True)[:6]))
    print('  corners and the old even blend: ' + ' | '.join(f'{w} {mean[w]:.4f}' for w in ((1, 0, 0), (0, 1, 0), (0, 0, 1), (.5, .5, 0), (.4, .3, .3), (.3, .4, .3), (.3, .3, .4))))
    for a in range(0, 11, 2):
        print('  ours ' + f'{a/10:.1f}: ' + ' '.join(f'{mean[(a/10, b/10, round((10-a-b)/10, 1))]:.4f}' for b in range(0, 11 - a, 2)))
    picks = []
    for T in pool:
        tr = {w: np.mean([v for t, v in sc[w].items() if t != T]) for w in grid}; b = max(tr, key=tr.get); picks.append((T, b, sc[b][T], sc[(.5, .5, 0)][T], sc[(1, 0, 0)][T]))
    print('  chosen leaving T out: ' + ' '.join(f'{T}:{b}' for T, b, *_ in picks))
    print(f'  held-out r: chosen {np.mean([p[2] for p in picks]):.4f}, ours+Steamer even {np.mean([p[3] for p in picks]):.4f}, ours {np.mean([p[4] for p in picks]):.4f}; chosen beats even {sum(p[2] > p[3] for p in picks)}/{len(picks)}, beats ours {sum(p[2] > p[4] for p in picks)}/{len(picks)}')
    if 'f1' in next(iter(pool.values()))[0] and pool[next(iter(pool))][0].get('ra1') is not None:
        for tk, tn in (('f1', 'fWAR only'), ('ra1', 'runs-allowed WAR only')):
            mt = {w: float(np.mean([wr([blend_rate(r, w) * r['pt'] for r in R], [r[tk] for r in R]) for R in pool.values()])) for w in grid}
            bt = max(mt, key=mt.get)
            print(f'  {tn}: best {bt} {mt[bt]:.4f} | ours {mt[(1, 0, 0)]:.4f} | Steamer {mt[(0, 1, 0)]:.4f} | ZiPS {mt[(0, 0, 1)]:.4f} | even {mt[(.5, .5, 0)]:.4f}')
    res[lab] = {'best': best, 'mean': {str(k): v for k, v in mean.items()}, 'picks': picks}
    return best, pool


def part2(pool, w, lab):
    """Residual test: adding last-season fWAR or Marcel to B, weight swept."""
    print(f'  PART 2 [{lab}]: add results history to the blend (B + c x input), mean r over {len(pool)} T')
    for key in ('fw1', 'marcel'):
        line = []
        for c in (0, .1, .2, .3, .5, .75, 1.0, 1.5, 2.0):
            line.append(f"{c}:{np.mean([wr([blend_rate(r, w) * r['pt'] + c * r[key] for r in R], [r['y1'] for r in R]) for R in pool.values()]):.4f}")
        print(f'    {key}: ' + ' '.join(line))


def design(R, form, w):
    B = np.array([blend_rate(r, w) * r['pt'] for r in R]); U = np.array([blend_rate(r, w) * r['unit'] for r in R]); a = np.array([r['age'] - 30.0 for r in R]); M = np.array([r['marcel'] for r in R])
    one = np.ones(len(R))
    if form == 'M1':
        return np.column_stack([one, B, B * a])
    if form == 'M2':
        return np.column_stack([one, B, B * a, U, U * a, a])
    if form == 'M3':
        return np.column_stack([one, B, B * a, U, U * a, a, M])
    raise ValueError(form)


def part3(rows, Ts, h, w, lab, FA, res):
    use = [r for r in rows if r['T'] in Ts and r[f'y{h}'] is not None and blend_rate(r, w) is not None]
    Tu = sorted({r['T'] for r in use})
    print(f'\n[{lab}] PART 3, {h} seasons: T {Tu}, n {[sum(r["T"] == T for r in use) for T in Tu]}')
    if len(Tu) < 2:
        print('  under 2 replicates: fit only, no held-out test')
    pred = {f: {} for f in ('M0', 'M1', 'M2', 'M3')}; truth = {}; idx = {}
    for T in Tu:
        te = [r for r in use if r['T'] == T]; tr = [r for r in use if r['T'] != T] or te
        truth[T] = np.array([r[f'y{h}'] for r in te]); idx[T] = te
        pred['M0'][T] = np.array([blend_rate(r, w) * r['pt'] * h for r in te])
        for f in ('M1', 'M2', 'M3'):
            b = np.linalg.lstsq(design(tr, f, w), np.array([r[f'y{h}'] for r in tr]), rcond=None)[0]
            pred[f][T] = design(te, f, w) @ b
    out = {}
    for f in pred:
        r_ = np.mean([wr(pred[f][T], truth[T]) for T in Tu]); e = np.mean([rmse(pred[f][T], truth[T]) for T in Tu])
        fa_r = []
        for T in Tu:
            ix = [i for i, r in enumerate(idx[T]) if r['pid'] in FA.get(T, ())]
            if len(ix) >= 15:
                fa_r.append(wr(pred[f][T][ix], truth[T][ix]))
        print(f'  {f}: r {r_:.3f}  rmse {e:.3f}  FA class r {np.mean(fa_r) if fa_r else float("nan"):.3f} ({len(fa_r)} T)')
        out[f] = dict(r=float(r_), rmse=float(e), fa_r=float(np.mean(fa_r)) if fa_r else None)
    if len(Tu) >= 2:
        for a_, b_ in (('M1', 'M0'), ('M2', 'M1'), ('M3', 'M2')):
            g, se, wi, n = paired_gap(pred[a_], pred[b_], truth)
            print(f'  {a_} v {b_}: gap {g:+.3f} (SE {se:.3f}) wins {wi}/{n} -> {verdict(g, se, wi, n, a_, b_)}')
    coef = {}
    for f in ('M1', 'M2', 'M3'):
        coef[f] = np.linalg.lstsq(design(use, f, w), np.array([r[f'y{h}'] for r in use]), rcond=None)[0].tolist()
    print('  all-sample coefficients M1 [c, B, B*a]: ' + ' '.join(f'{x:.3f}' for x in coef['M1']))
    print('  all-sample coefficients M2 [c, B, B*a, R, R*a, a]: ' + ' '.join(f'{x:.3f}' for x in coef['M2']))
    res[f'{lab}_{h}'] = dict(T=Tu, scores=out, coef=coef)


def main():
    FA = fa_class(); res = {'part1': {}, 'part3': {}}
    FIXED = {'H': (.5, .5, 0), 'SP': (.5, .5, 0), 'RP': (.5, 0, .5)}
    # Replication check: the captured matched rows must reproduce the shipped backtest's total-WAR r (hitters .698, pitchers .620).
    for fn, nm, want in ((HB.hitters, 'hitters', .698), (HB.pitchers, 'pitchers', .620)):
        m_ = capture(fn)
        got_ = float(np.mean([HB.wr([r['hp'] for r in R], [r['wT'] for r in R]) for R in m_.values()]))
        print(f'replication {nm}: hp total r {got_:.3f}, recorded {want:.3f}')
        if abs(got_ - want) > .002:
            raise SystemExit('capture does not reproduce the recorded backtest: stop')
    for side, groups in (('bat', ('H',)), ('pit', ('SP', 'RP'))):
        rows = build(side)
        for gp in groups:
            G = [r for r in rows if r['group'] == gp]
            Ts1 = [T for T in (2018, 2019, 2021, 2022, 2023, 2024, 2025)]
            got = part1(G, Ts1, gp, res['part1'])
            # Weights read off part 1 and fixed here. H: even ours + Steamer is the interior grid best. SP: even ours + Steamer, the grid is flat near the top and a pick left out loses to it.
            # RP: even ours + ZiPS is the grid best, and every pick left out has Steamer at 0.
            w = FIXED[gp]
            pool = got[1]
            rp_ref = (.5, .5, 0)
            if w != rp_ref:
                A_ = {T: np.array([blend_rate(r, w) * r['pt'] for r in R]) for T, R in pool.items()}
                B_ = {T: np.array([blend_rate(r, rp_ref) * r['pt'] for r in R]) for T, R in pool.items()}
                C_ = {T: np.array([blend_rate(r, (1, 0, 0)) * r['pt'] for r in R]) for T, R in pool.items()}
                Y_ = {T: np.array([r['y1'] for r in R]) for T, R in pool.items()}
                for nm, X_ in (('ours + Steamer', B_), ('ours alone', C_)):
                    g, se, wi, n = paired_gap(A_, X_, Y_)
                    print(f'  fixed {w} v {nm}: gap {g:+.3f} (SE {se:.3f}) wins {wi}/{n} -> {verdict(g, se, wi, n, "fixed", nm)}')
            part2(pool, w, gp)
            for h in (3, 5):
                part3(G, Ts1, h, w, gp, FA, res['part3'])
    tmp = os.path.join(P, '_fa_rank_blend.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(res, f, indent=1, default=float)
    os.replace(tmp, os.path.join(P, '_fa_rank_blend.json'))
    print('\nwrote data/_proj/_fa_rank_blend.json')


if __name__ == '__main__':
    main()
