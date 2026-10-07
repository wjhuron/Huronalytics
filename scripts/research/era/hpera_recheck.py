"""hpera_recheck.py: does hpERA beat SIERA at forecasting, on pools that do not select on the outcome?

The hpERA tooltip says it "beats SIERA at predicting both rest-of-season and next-season ERA in every
tested season". Those tests (era_weights_final.py) kept pitchers with >= 60 IP in BOTH the base and the
target period, unweighted. A target-period innings gate selects on the outcome (an arm who pitches
well keeps pitching). next_season_metric_screen.py (2026-10-07) found a reconstruction of hpERA
at r .22 against next-season RA9 on an honest pool, under SIERA and xFIP at .30.

Steps:
  1. VALIDATE the reconstruction: hpERA from the research channels (era_weights_final shrunk z,
     shipped W_PH, plus the W_LHP hand term) against the SHIPPED 2026 hpERA on the leaderboard.
  2. REPRODUCE the original setting: >= 60 IP in base and target, unweighted r with ERA.
  3. HONEST pools: base >= 30 IP (full season) or >= 15 IP (first half; the h1 z pool), target >= 1
     out, r weighted by target innings; ERA and RA9 targets.
Objectives: NEXT (season B -> B + 1, B 2021-2025) and ROS (first half -> second half, 2021-2026).
Arms: hpERA, SIERA (the pipeline's formula), xFIP, FIP, K-BB%, ERA. Sign set so positive = predicts
the better result. Paired bootstrap of r(hpERA) - r(SIERA) within each replicate, averaged.
hpERA's weights were fit on 2021-2026 ROS, so it is in-sample here: any edge is an upper bound.

Usage: python3 scripts/research/era/hpera_recheck.py
Output: console + data/_hpera_recheck.json
"""
import contextlib
import io
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import era_weights_final as ewf  # noqa: E402

ROOT = ewf.ROOT
TG = ewf.TARGETS
BAT = json.load(open(os.path.join(ROOT, 'data', '_era_battery.json')))
W_PH = {'stuff': 0.315, 'loc': 0.105, 'k': 0.053, 'izwh': 0.101, 'xrv': 0.16, 'gb': 0.151, 'gs_share': 0.298, 'park': 0.152}
W_LHP = -0.211
ARMS = ['hpERA', 'SIERA', 'xFIP', 'FIP', 'K-BB%', 'ERA']
LOWER_BETTER = {'hpERA', 'SIERA', 'xFIP', 'FIP', 'ERA'}


def line(season, pid, scope):
    rec = TG[str(season)]['pitchers'].get(pid)
    if rec is None:
        return None
    return rec if scope == 'full' else rec.get(scope)


def base_features(season, scope):
    """{pid: {arm: value, 'outs': base outs}} for every pitcher in the hpERA z pool of (season, scope)."""
    with contextlib.redirect_stdout(io.StringIO()):
        Z = ewf.shrunk_features(season, scope)
    pit = TG[str(season)]['pitchers']
    lg = [line(season, p, scope) for p in pit]
    lg = [v for v in lg if v and v['outs'] > 0]
    fipc = sum(v['er'] for v in lg) * 27 / sum(v['outs'] for v in lg) - \
        sum(13 * v['hr'] + 3 * (v['bb'] + v['hbp']) - 2 * v['so'] for v in lg) * 3 / sum(v['outs'] for v in lg)
    hr = fb = 0.0
    for p in pit:
        m = BAT[str(season)].get(p, {}).get(scope); v = line(season, p, scope)
        if m and v and m.get('fb_pct') is not None and m.get('bip'):
            hr += v['hr']; fb += m['fb_pct'] * m['bip']
    lg_hrfb = hr / fb
    out = {}
    for p, z in Z.items():
        v = line(season, p, scope); m = BAT[str(season)].get(p, {}).get(scope) or {}
        if not v or v['outs'] <= 0 or v['bf'] <= 0:
            continue
        ip, pa = v['outs'] / 3, v['bf']
        f = {'outs': v['outs']}
        if all(k in z for k in W_PH):
            hand = pit[p].get('hand')
            # the research harness stores xRV with the OPPOSITE sign to production (CLAUDE.md failure log:
            # era_xrv100_pass.py is batter-positive and raw_features negates it), so the shipped xrv weight
            # applies to -z['xrv'] here; the first run of this script missed it and understated hpERA
            f['hpERA'] = sum(W_PH[k] * (-z[k] if k == 'xrv' else z[k]) for k in W_PH) + (W_LHP if hand == 'L' else 0.0)
        f['ERA'] = 9 * v['er'] / ip
        f['FIP'] = (13 * v['hr'] + 3 * (v['bb'] + v['hbp']) - 2 * v['so']) / ip + fipc
        f['K-BB%'] = (v['so'] - v['bb']) / pa
        if m.get('fb_pct') is not None and m.get('bip'):
            f['xFIP'] = (13 * lg_hrfb * m['fb_pct'] * m['bip'] + 3 * (v['bb'] + v['hbp']) - 2 * v['so']) / ip + fipc
        if all(m.get(k) is not None for k in ('gb_pct', 'fb_pct', 'pu_pct')) and m.get('bip'):
            so, bb = v['so'] / pa, v['bb'] / pa
            gbn, fbn = m['gb_pct'] * m['bip'], (m['fb_pct'] + m['pu_pct']) * m['bip']
            ng = (gbn - fbn) / pa
            sp = min(v['gs'] / v['g'], 1.0) if v.get('g') else 0.0
            f['SIERA'] = (-15.518 * so + 9.146 * so ** 2 + 8.648 * bb + 27.252 * bb ** 2 - 2.298 * ng
                          + (-1.0 if gbn >= fbn else 1.0) * 4.920 * ng ** 2 - 4.036 * so * bb
                          + 5.155 * so * ng + 4.546 * bb * ng + 0.367 * sp)
        out[p] = f
    return out


def wr(x, y, w):
    mx, my = np.average(x, weights=w), np.average(y, weights=w)
    c = np.average((x - mx) * (y - my), weights=w)
    return c / math.sqrt(np.average((x - mx) ** 2, weights=w) * np.average((y - my) ** 2, weights=w))


def validate():
    feats = base_features(2026, 'full')
    rows = json.load(open(os.path.join(ROOT, 'data', 'pitcher_leaderboard_rs.json')))
    n_rows = {}
    for r in rows:
        n_rows[r['mlbId']] = n_rows.get(r['mlbId'], 0) + 1
    xs, ys = [], []
    for r in rows:
        f = feats.get(str(r['mlbId']))
        if not f or 'hpERA' not in f or r.get('hpERA') is None or n_rows[r['mlbId']] != 1 or r['team'] in ('ROC', 'AAA'):
            continue
        xs.append(f['hpERA']); ys.append(r['hpERA'])
    xs, ys = np.array(xs), np.array(ys)
    r = np.corrcoef(xs, ys)[0, 1]
    slope = np.polyfit(xs, ys, 1)[0]
    print(f'1. VALIDATION vs shipped 2026 hpERA (single-team MLB rows, 30+ IP in the research pool): '
          f'n {len(xs)}, r {r:.3f}, slope {slope:.2f} (1.00 = same scale)')
    return {'n': int(len(xs)), 'r': float(r), 'slope': float(slope)}


def replicates(objective):
    """[(label, base feats, target dict pid -> (era, ra9, outs))]"""
    reps = []
    if objective == 'next':
        for B in range(2021, 2026):
            tgt = {}
            for p, v in TG[str(B + 1)]['pitchers'].items():
                if v['outs'] > 0:
                    tgt[p] = (27 * v['er'] / v['outs'], 27 * v['r'] / v['outs'], v['outs'])
            reps.append((f'{B % 100}->{(B + 1) % 100}', base_features(B, 'full'), tgt))
    else:
        for S in range(2021, 2027):
            tgt = {}
            for p, v in TG[str(S)]['pitchers'].items():
                h = v.get('h2')
                if h and h['outs'] > 0:
                    tgt[p] = (27 * h['er'] / h['outs'], 27 * h['r'] / h['outs'], h['outs'])
            reps.append((f'{S % 100}h', base_features(S, 'h1'), tgt))
    return reps


def score(reps, base_min, tgt_min, weighted, ti, rng):
    """per-arm per-replicate r, and the paired bootstrap of hpERA - SIERA"""
    per = {a: [] for a in ARMS}
    diffs = []
    for label, F, tgt in reps:
        P = [p for p, f in F.items() if f['outs'] >= base_min and p in tgt and tgt[p][2] >= tgt_min
             and all(a in f for a in ARMS)]
        y = np.array([tgt[p][ti] for p in P]); w = np.array([tgt[p][2] for p in P], float) if weighted else np.ones(len(P))
        X = {a: np.array([F[p][a] for p in P]) * (-1 if a in LOWER_BETTER else 1) for a in ARMS}
        for a in ARMS:
            per[a].append(-wr(X[a], y, w))      # target lower = better, flip
        d = []
        for _ in range(1000):
            i = rng.integers(0, len(P), len(P))
            d.append(-wr(X['hpERA'][i], y[i], w[i]) + wr(X['SIERA'][i], y[i], w[i]))
        diffs.append(np.array(d))
        per.setdefault('_n', []).append(len(P))
    D = np.mean(np.vstack(diffs), axis=0)
    return per, float(np.mean([a - b for a, b in zip(per['hpERA'], per['SIERA'])])), float(D.std())


def main():
    rng = np.random.default_rng(0)
    out = {'validation': validate()}
    settings = [('NEXT', 'next', 'orig: >= 60 IP base AND target, unweighted, ERA', 180, 180, False, 0),
                ('NEXT', 'next', 'honest: >= 30 IP base, target >= 1 out, IP-weighted, ERA', 90, 1, True, 0),
                ('NEXT', 'next', 'honest: same, RA9', 90, 1, True, 1),
                ('ROS', 'ros', 'orig: >= 30 IP h1 AND h2, unweighted, ERA', 90, 90, False, 0),
                ('ROS', 'ros', 'honest: >= 15 IP h1, h2 >= 1 out, IP-weighted, ERA', 45, 1, True, 0),
                ('ROS', 'ros', 'honest: same, RA9', 45, 1, True, 1)]
    cache = {}
    for obj, key, desc, bmin, tmin, wt, ti in settings:
        if key not in cache:
            cache[key] = replicates(key)
        reps = cache[key]
        per, dmean, dse = score(reps, bmin, tmin, wt, ti, rng)
        print(f'\n{obj} | {desc}   (n per replicate {per["_n"]})')
        for a in ARMS:
            v = per[a]
            print(f'   {a:7s} mean r {np.mean(v):+.3f}   ' + ' '.join(f'{x:+.3f}' for x in v))
        wins = sum(h > s for h, s in zip(per['hpERA'], per['SIERA']))
        print(f'   hpERA - SIERA: {dmean:+.3f} (bootstrap SE {dse:.3f}, z {dmean / dse:+.2f}), hpERA ahead in {wins}/{len(reps)}')
        out[f'{obj}|{desc}'] = {a: per[a] for a in ARMS} | {'diff': dmean, 'se': dse, 'wins': wins}
    with open(os.path.join(ROOT, 'data', '_hpera_recheck.json'), 'w') as f:
        json.dump(out, f, indent=1, default=float)


if __name__ == '__main__':
    main()
