"""pt_backtest.py: next-season playing time (pitcher IP, hitter PA) for a TOTAL hpWAR.

hpWAR ships as a rate (per 180 IP / 60 IP / 600 PA). A total needs projected playing time. The pool is
the projection pool (project_players.py): every player with MLB history in B-2..B (pitchers >= 1 BF,
position players excluded; hitters >= 1 PA, pitchers excluded). Truth: MLB IP or PA in T = B + 1, and a
player who does not reach the majors in T counts as 0. A total projection has to carry that risk, so the
zeros stay in the score.

Arms (each scored per player, unweighted MSE of IP_T or PA_T, OLS refit leaving the target season out):
  marcel   Tango's published playing-time rule. Hitters .5 PA1 + .1 PA2 + 200. Pitchers .5 IP1 + .1 IP2
           + 60 if a starter in B (GS/G > .5) else + 25.
  hist     OLS on PT_B, PT_B-1, PT_B-2 (and GS share in B for pitchers)
  full     hist + age, age^2 + shrunk quality history + Triple-A PT in B (+ catcher flag for hitters)
Predictions are clipped to [0, max PT_T in the training seasons].

Quality (history d^k by PT, shrunk to league at N0 PT):
  pitchers  RA9 and FIP deltas from the season league;  hitters OPS delta.
Swept 2026-10-07 on the full arm (LOSO RMSE, nested choice validated per season):
  pitchers  FLAT: d .5-.8 x N0 500-2000 spans .03 IP; the nested choice beat the rate model's (.65, 500)
            in 3/10, so (.65, 500) stays. "Flat, so anything here works."
  hitters   d .3 interior (.2 131.46, .3 131.41, .4 131.46); N0 improves monotonically toward the LIMIT
            form, flat beyond 4000 (<.03 PA), so N0 = None: the PA-weighted total of the OPS delta per
            1000 PA (quality times playing time, which is what decides a job). Nested choice beat the
            borrowed (.7, 450) in 9/10, RMSE 131.46 vs 132.22.

2020 (60 games): history counting stats are scaled by 162/60 and T = 2020 is not a target. A convention.
Targets 2016-2026 minus 2020 (usage drifts: starter innings fell over the period; a recent window).

Usage: python3 scripts/research/projection/pt_backtest.py
Output: console + data/_proj/_pt_backtest.json
"""
import json
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
P = os.path.join(ROOT, 'data', '_proj')
TARGETS = [T for T in range(2016, 2027) if T != 2020]
SCALE = {2020: 162 / 60}
PIT_Q = (0.65, 500)
HIT_Q = (0.3, None)     # None: the limit form, see the docstring


def load(kind, y):
    path = os.path.join(P, f'{kind}_{y}.json')
    return json.load(open(path)) if os.path.exists(path) else []


def pitch_season(y):
    out = {}
    for r in load('lines_pitching', y):
        if r.get('pos') not in ('P', 'TWP'):
            continue
        outs, bf = int(r.get('outs') or 0), int(r.get('battersFaced') or 0)
        if bf <= 0:
            continue
        g, gs = int(r.get('gamesPlayed') or 0), int(r.get('gamesStarted') or 0)
        k, bb, hbp, hr = (int(r.get(c) or 0) for c in ('strikeOuts', 'baseOnBalls', 'hitByPitch', 'homeRuns'))
        ip = outs / 3
        out[r['id']] = {'ip': ip * SCALE.get(y, 1), 'bf': bf * SCALE.get(y, 1), 'age': r.get('age'),
                        'gs': gs / g if g else 0.0,
                        'ra9': 9 * int(r.get('runs') or 0) / ip if ip else None,
                        'fip': (13 * hr + 3 * (bb + hbp) - 2 * k) / ip if ip else None, 'raw_ip': ip}
    for c in ('ra9', 'fip'):
        v = [(s[c], s['raw_ip']) for s in out.values() if s[c] is not None and s['raw_ip'] > 0]
        lg = sum(a * b for a, b in v) / sum(b for _, b in v)
        for s in out.values():
            if s[c] is not None:
                s[c] -= lg
    return out


def hit_season(y):
    out = {}
    for r in load('lines_hitting', y):
        if r.get('pos') == 'P':
            continue
        pa = int(r.get('plateAppearances') or 0)
        if pa <= 0:
            continue
        ops = float(r['ops']) if r.get('ops') not in (None, '', '-.--', '.---') else None
        out[r['id']] = {'pa': pa * SCALE.get(y, 1), 'raw_pa': pa, 'age': r.get('age'), 'pos': r.get('pos'), 'ops': ops}
    v = [(s['ops'], s['raw_pa']) for s in out.values() if s['ops'] is not None]
    lg = sum(a * b for a, b in v) / sum(b for _, b in v)
    for s in out.values():
        if s['ops'] is not None:
            s['ops'] -= lg
    return out


def aaa_pt(y, key):
    return {r['id']: int(r.get(key) or 0) / (3 if key == 'outs' else 1) for r in load('aaa_lines_' + ('pitching' if key == 'outs' else 'hitting'), y)}


def shrunk(hist, ch, wkey, d, n0):
    num = den = 0.0
    for k, h in enumerate(hist):
        if h and h.get(ch) is not None:
            num += d ** k * h[wkey] * h[ch]; den += d ** k * h[wkey]
    if n0 is None:
        return num / 1000.0
    return num / (den + n0) if den + n0 > 0 else 0.0


def rows(side, S, A, B):
    T = B + 1
    pt = 'ip' if side == 'pit' else 'pa'
    ids = set().union(*[set(S[B - k]) for k in range(3)])
    out = []
    for pid in ids:
        hist = [S[B - k].get(pid) for k in range(3)]
        h0 = next(h for h in hist if h)
        k0 = hist.index(h0)
        age = (h0['age'] or 28) + k0 + 1
        t = S[T].get(pid)
        y = (t['raw_ip'] if side == 'pit' else t['raw_pa']) if t else 0.0
        f = {'pt0': hist[0][pt] if hist[0] else 0.0, 'pt1': hist[1][pt] if hist[1] else 0.0,
             'pt2': hist[2][pt] if hist[2] else 0.0, 'age': age, 'aaa': A[B].get(pid, 0.0)}
        if side == 'pit':
            f['gs'] = hist[0]['gs'] if hist[0] else (h0['gs'])
            f['q_ra9'] = shrunk(hist, 'ra9', 'bf', *PIT_Q)
            f['q_fip'] = shrunk(hist, 'fip', 'bf', *PIT_Q)
        else:
            f['q_ops'] = shrunk(hist, 'ops', 'pa', *HIT_Q)
            f['c'] = 1.0 if h0.get('pos') == 'C' else 0.0
        out.append((pid, f, y))
    return out


def marcel(side, R):
    if side == 'pit':
        return np.array([0.5 * f['pt0'] + 0.1 * f['pt1'] + (60 if f['gs'] > 0.5 else 25) for _, f, _ in R])
    return np.array([0.5 * f['pt0'] + 0.1 * f['pt1'] + 200 for _, f, _ in R])


ARMS = {
    'pit': {'hist': ['pt0', 'pt1', 'pt2', 'gs'],
            'full': ['pt0', 'pt1', 'pt2', 'gs', 'age', 'age2', 'q_ra9', 'q_fip', 'aaa', 'gs_pt0']},
    'hit': {'hist': ['pt0', 'pt1', 'pt2'],
            'full': ['pt0', 'pt1', 'pt2', 'age', 'age2', 'q_ops', 'aaa', 'c', 'q_pt0']},
}


def design(R, cols):
    X = []
    for _, f, _ in R:
        g = dict(f)
        g['age2'] = (f['age'] - 28) ** 2
        g['gs_pt0'] = f.get('gs', 0) * f['pt0']
        g['q_pt0'] = f.get('q_ops', 0) * f['pt0']
        X.append([1.0] + [g[c] for c in cols])
    return np.array(X)


def project(side, base):
    """Fit the full arm on every target season and project T = base + 1 for the base pool.
    Returns {mlbId: projected IP or PA}."""
    S = {y: (pitch_season if side == 'pit' else hit_season)(y) for y in range(TARGETS[0] - 3, base + 1)}
    A = {y: aaa_pt(y, 'outs' if side == 'pit' else 'plateAppearances') for y in S}
    S[base + 1] = {}
    R = {T: rows(side, S, A, T - 1) for T in TARGETS}
    cols = ARMS[side]['full']
    X = np.vstack([design(R[T], cols) for T in TARGETS])
    Y = np.concatenate([np.array([y for _, _, y in R[T]]) for T in TARGETS])
    beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
    Rb = rows(side, S, A, base)
    p = np.clip(design(Rb, cols) @ beta, 0, Y.max())
    return {pid: float(v) for (pid, _, _), v in zip(Rb, p)}


def main():
    out = {}
    for side in ('pit', 'hit'):
        S = {y: (pitch_season if side == 'pit' else hit_season)(y) for y in range(TARGETS[0] - 3, TARGETS[-1] + 1)}
        A = {y: aaa_pt(y, 'outs' if side == 'pit' else 'plateAppearances') for y in S}
        R = {T: rows(side, S, A, T - 1) for T in TARGETS}
        Y = {T: np.array([y for _, _, y in R[T]]) for T in TARGETS}
        cap = {T: max(Y[t].max() for t in TARGETS if t != T) for T in TARGETS}
        res = {'marcel': {T: float(((np.clip(marcel(side, R[T]), 0, cap[T]) - Y[T]) ** 2).mean()) for T in TARGETS}}
        preds = {}
        for arm, cols in ARMS[side].items():
            Xd = {T: design(R[T], cols) for T in TARGETS}
            res[arm] = {}
            preds[arm] = {}
            for T in TARGETS:
                tr = [t for t in TARGETS if t != T]
                beta, *_ = np.linalg.lstsq(np.vstack([Xd[t] for t in tr]), np.concatenate([Y[t] for t in tr]), rcond=None)
                p = np.clip(Xd[T] @ beta, 0, cap[T])
                preds[arm][T] = p
                res[arm][T] = float(((p - Y[T]) ** 2).mean())
        unit = 'IP' if side == 'pit' else 'PA'
        print(f'\n== {side}  (RMSE in {unit}; pool per season {[len(R[T]) for T in TARGETS]})')
        for arm in res:
            r = res[arm]
            wins = sum(r[T] < res['marcel'][T] for T in TARGETS)
            print(f'  {arm:7s} RMSE {np.sqrt(np.mean(list(r.values()))):6.1f}   ' +
                  ' '.join(f'{T % 100}:{np.sqrt(r[T]):5.1f}' for T in TARGETS) + (f'   beats marcel {wins}/{len(TARGETS)}' if arm != 'marcel' else ''))
        # calibration of the best arm by history playing time, pooled
        allp = np.concatenate([preds['full'][T] for T in TARGETS]); ally = np.concatenate([Y[T] for T in TARGETS])
        allm = np.concatenate([np.clip(marcel(side, R[T]), 0, cap[T]) for T in TARGETS])
        pt0 = np.array([f['pt0'] for T in TARGETS for _, f, _ in R[T]])
        bins = (0, 1, 30, 80, 150, 1e9) if side == 'pit' else (0, 1, 100, 300, 500, 1e9)
        print('  calibration by PT in B, actual - projected (full | marcel):')
        for lo, hi in zip(bins[:-1], bins[1:]):
            m = (pt0 >= lo) & (pt0 < hi)
            print(f'    {unit}_B [{lo}, {hi if hi < 1e9 else "+"}) n {m.sum():5d}  actual {ally[m].mean():6.1f}  '
                  f'full {(ally[m] - allp[m]).mean():+6.1f}  marcel {(ally[m] - allm[m]).mean():+6.1f}')
        out[side] = {arm: {str(T): v for T, v in r.items()} for arm, r in res.items()}
    with open(os.path.join(P, '_pt_backtest.json'), 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
