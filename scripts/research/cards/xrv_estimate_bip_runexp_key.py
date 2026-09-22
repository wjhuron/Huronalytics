"""Which key should the daily card's same-day RunExp estimate use on a ball
in play?

Background: a social card built before the Savant backfill fills RunExp from
league tables (cards/pitcher.py, _xrv_fill_estimates). Until 2026-09-21 the
fill covered takes, whiffs and fouls only, so RV on such a card omitted every
hit and out on contact (Herz 2026-09-21: 4 ER at RV +0.4, changeup RV 0.0
against xRV -1.4). This script picks the key for the ball-in-play table.

Runners is a supplement column (absent before the backfill), so only fields
the scrape writes are eligible: Count, Event, Outs.

Candidates
    E    (event)
    CE   (count, event)
    EO   (event, outs)
    CEO  (count, event, outs)
    CEOB (count, event, outs, batted-ball type), to close the grid: every
         scrape-time field that could enter the value
Fallback for a key the fit set never saw: (event) mean, then the global BIP
mean, the same chain the code uses.

Replicates (2026 MLB balls in play with a sheet RunExp, fit on one side and
scored on the other, tables never see the scored rows)
    H1   fit the first half of the season by date, score the second
    H2   the reverse
    M-*  leave one calendar month out, fit the rest, score that month

Objectives on the scored rows
    per BIP:    r and mean |err| of the estimate against the sheet RunExp
    per cell:   the card's unit, one outing x pitch type: r and mean |err|
                of the summed BIP RunExp
    per outing: the TOTAL row: r and mean |err|
The per-cell mean |err| decides. Wins are counted per replicate.

Run from the repo root:
    PYTHONHASHSEED=0 python3 scripts/research/cards/xrv_estimate_bip_runexp_key.py
"""
import os
import sys
from collections import defaultdict

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, ROOT)
from cards.pitcher import _load_mlb_pickle, sf  # noqa: E402

CANDS = {
    'E':   lambda p: (p['ev'],),
    'CE':  lambda p: (p['cnt'], p['ev']),
    'EO':  lambda p: (p['ev'], p['outs']),
    'CEO': lambda p: (p['cnt'], p['ev'], p['outs']),
    'CEOB': lambda p: (p['cnt'], p['ev'], p['outs'], p['bbt']),
}


def load_bip():
    rows = []
    for p in _load_mlb_pickle():
        if p.get('Description') != 'In Play':
            continue
        rv = sf(p.get('RunExp'))
        ev = p.get('Event')
        if rv is None or not ev:
            continue
        rows.append({
            'rv': rv, 'ev': str(ev), 'cnt': str(p.get('Count') or ''),
            'outs': str(p.get('Outs') if p.get('Outs') not in (None, '') else ''),
            'bbt': str(p.get('BBType') or ''),
            'date': str(p.get('Game Date') or ''),
            'cell': (p.get('Pitcher'), str(p.get('Game Date')), p.get('Pitch Type')),
            'outing': (p.get('Pitcher'), str(p.get('Game Date'))),
        })
    return rows


def fit(rows, keyf):
    acc = defaultdict(lambda: [0.0, 0])
    ev_acc = defaultdict(lambda: [0.0, 0])
    g = [0.0, 0]
    for r in rows:
        a = acc[keyf(r)]; a[0] += r['rv']; a[1] += 1
        b = ev_acc[r['ev']]; b[0] += r['rv']; b[1] += 1
        g[0] += r['rv']; g[1] += 1
    return ({k: s / n for k, (s, n) in acc.items()},
            {k: s / n for k, (s, n) in ev_acc.items()},
            g[0] / g[1])


def score(rows, keyf, tabs):
    tab, ev_tab, glob = tabs
    est, act, hit = [], [], 0
    cell_e, cell_a = defaultdict(float), defaultdict(float)
    out_e, out_a = defaultdict(float), defaultdict(float)
    for r in rows:
        k = keyf(r)
        v = tab.get(k)
        if v is not None:
            hit += 1
        else:
            v = ev_tab.get(r['ev'], glob)
        est.append(v); act.append(r['rv'])
        cell_e[r['cell']] += v; cell_a[r['cell']] += r['rv']
        out_e[r['outing']] += v; out_a[r['outing']] += r['rv']
    est, act = np.array(est), np.array(act)
    ce = np.array([cell_e[c] for c in cell_a]); ca = np.array([cell_a[c] for c in cell_a])
    oe = np.array([out_e[c] for c in out_a]); oa = np.array([out_a[c] for c in out_a])
    return {
        'n': len(rows), 'key_hit': hit / len(rows),
        'bip_r': float(np.corrcoef(est, act)[0, 1]), 'bip_mae': float(np.mean(np.abs(est - act))),
        'cell_r': float(np.corrcoef(ce, ca)[0, 1]), 'cell_mae': float(np.mean(np.abs(ce - ca))),
        'out_r': float(np.corrcoef(oe, oa)[0, 1]), 'out_mae': float(np.mean(np.abs(oe - oa))),
    }


def main():
    rows = load_bip()
    dates = sorted(set(r['date'] for r in rows))
    mid = dates[len(dates) // 2]
    months = sorted(set(r['date'][:7] for r in rows))
    print(f"{len(rows)} MLB balls in play with RunExp, {dates[0]}..{dates[-1]}, "
          f"half split at {mid}, months {months}")
    print(f"events: {len(set(r['ev'] for r in rows))}, outs values: "
          f"{sorted(set(r['outs'] for r in rows))}")
    splits = [('H1', lambda r: r['date'] < mid), ('H2', lambda r: r['date'] >= mid)]
    for m in months:
        splits.append((f'M-{m[5:]}', lambda r, m=m: r['date'][:7] != m))
    wins = defaultdict(int)
    res = {}
    hdr = f"{'split':<6}{'key':<5}{'n':>7}{'hit':>6}{'bipR':>7}{'bipMAE':>8}{'cellR':>7}{'cellMAE':>9}{'outR':>7}{'outMAE':>8}"
    print(hdr)
    for name, in_fit in splits:
        fit_rows = [r for r in rows if in_fit(r)]
        sc_rows = [r for r in rows if not in_fit(r)]
        best, best_v = None, None
        for c, kf in CANDS.items():
            s = score(sc_rows, kf, fit(fit_rows, kf))
            res[(name, c)] = s
            print(f"{name:<6}{c:<5}{s['n']:>7}{s['key_hit']:>6.3f}{s['bip_r']:>7.3f}{s['bip_mae']:>8.4f}"
                  f"{s['cell_r']:>7.3f}{s['cell_mae']:>9.4f}{s['out_r']:>7.3f}{s['out_mae']:>8.4f}")
            if best_v is None or s['cell_mae'] < best_v:
                best, best_v = c, s['cell_mae']
        wins[best] += 1
        print(f"{'':<6}-> {best} wins on cell MAE")
    print("\nwins by cell MAE over", len(splits), "replicates:", dict(wins))
    for obj in ('bip_mae', 'cell_mae', 'out_mae'):
        print(f"mean {obj}: " + ", ".join(
            f"{c} {np.mean([res[(n, c)][obj] for n, _ in splits]):.4f}" for c in CANDS))
    # paired deltas against E, per replicate
    for c in ('CE', 'EO', 'CEO', 'CEOB'):
        d = [res[(n, 'E')]['cell_mae'] - res[(n, c)]['cell_mae'] for n, _ in splits]
        print(f"cell MAE gain of {c} over E: mean {np.mean(d):+.4f}, "
              f"SE {np.std(d, ddof=1) / np.sqrt(len(d)):.4f}, wins {sum(x > 0 for x in d)}/{len(d)}")
    d = [res[(n, 'CEO')]['cell_mae'] - res[(n, 'CEOB')]['cell_mae'] for n, _ in splits]
    print(f"cell MAE gain of CEOB over CEO: mean {np.mean(d):+.4f}, "
          f"SE {np.std(d, ddof=1) / np.sqrt(len(d)):.4f}, wins {sum(x > 0 for x in d)}/{len(d)}")


if __name__ == '__main__':
    main()
