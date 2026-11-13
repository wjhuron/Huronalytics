"""Is the next-season gain of a STRONGER Loc+ hand level location, or exposure?
(2026-11-13, per Wally: "is the platoon split too strong?")

The strength sweep (locplus_handneutral.py, h = lp.HANDNEU, tables from
locplus_target_audit.py run --flag hs_*) found next-season prediction rising
as h goes NEGATIVE, i.e. as the opposite-hand penalty grows. A pitcher's Loc+
moves with h in proportion to his opposite-hand share, so a larger penalty
also loads Loc+ with that share. If the share itself predicts next season's
run value (relievers deployed by platoon, pitch-mix by hand), the "gain" is the
matchup mix and not location.

This reads the audit tables unchanged and repeats the decider (next season,
rendered Loc+, partial on Stuff+, mean of the xRV and actual-RV columns) with
and without the pitcher's season-Y opposite-hand pitch share as a second
control. Paired bootstrap within each Y -> Y+1 pair, pooled as the audit does.
    python3 scripts/research/locplus/locplus_handstrength_exposure.py
Output: data/_loc_target_audit/handstrength_exposure.json
"""
import json
import math
import os
import pickle
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import locplus_target_audit as TA  # noqa: E402

CACHE = os.path.join(ROOT, 'data', '_loc_target_audit')
OUT = os.path.join(CACHE, 'handstrength_exposure.json')
CTL = 'ctl1113'
ARMS = ['hs_m300', 'hs_m200', 'hs_m150', 'hs_m100', 'hs_m075', 'hs_m050', 'hs_m025',
        'hs_p025', 'hs_p050', 'hs_p075', 'hs_p100']
H = {'hs_m300': -3, 'hs_m200': -2, 'hs_m150': -1.5, 'hs_m100': -1, 'hs_m075': -.75,
     'hs_m050': -.5, 'hs_m025': -.25, 'hs_p025': .25, 'hs_p050': .5, 'hs_p075': .75,
     'hs_p100': 1}
SRC = {2021: 'data/_statcast2021_cache.pkl', 2022: 'data/_statcast2022_cache.pkl',
       2023: 'data/_statcast2023_cache.pkl', 2024: 'data/_statcast2024_cache.pkl',
       2025: 'data/_statcast2025_full_cache.pkl'}
B = 1000


def opp_share(yr):
    """(pitcher, throws) -> share of his pitches thrown to opposite-hand batters."""
    if yr in SRC:
        df = pickle.load(open(os.path.join(ROOT, SRC[yr]), 'rb'))
        f = pd.DataFrame({'pitcher': df['player_name'].astype(str),
                          'throws': df['p_throws'].astype(str), 'bats': df['stand'].astype(str)})
    else:
        from pipeline.utils import AAA_TEAMS
        d = pd.DataFrame(pd.read_pickle(os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl')))
        d = d[~d.PTeam.isin(AAA_TEAMS)]
        f = pd.DataFrame({'pitcher': d.Pitcher, 'throws': d.Throws, 'bats': d.Bats})
    f = f[f.bats.isin(['L', 'R']) & f.throws.isin(['L', 'R'])]
    s = (f.bats != f.throws).groupby([f.pitcher, f.throws]).mean()
    s.index.names = ['pitcher', 'throws']
    return s


def resid(y, X):
    """y and X are (B+1, n): residual of y on [1, X] per bootstrap row."""
    out = np.empty_like(y)
    for b in range(y.shape[0]):
        A = np.column_stack([np.ones(y.shape[1])] + [x[b] for x in X])
        out[b] = y[b] - A @ np.linalg.lstsq(A, y[b], rcond=None)[0]
    return out


def pr(L, y, ctrls):
    return TA._r(resid(L, ctrls), resid(y, ctrls))


def main():
    rng = np.random.default_rng(0)
    share = {}
    res = {a: {'stuff': [], 'stuff_share': []} for a in ARMS}
    diag = []
    for y in range(2021, 2026):
        for yr in (y, y + 1):
            if yr not in share:
                share[yr] = opp_share(yr)
        ty, ty1 = TA.with_stuff(pd.read_pickle(TA.table_path(CTL, y)), y), pd.read_pickle(TA.table_path(CTL, y + 1))
        vc = TA.view(ty, ty1, 'next')
        vc['stuff'] = ty['stuff'].reindex(vc.index)
        vc['share'] = share[y].reindex(vc.index)
        vc = vc.dropna(subset=['L_ren', 'x', 'rv', 'stuff', 'share'])
        sh1 = share[y + 1].reindex(vc.index)
        k = sh1.notna()
        diag.append({'pair': f'{y}->{y + 1}', 'n': len(vc),
                     'r_share_share1': float(np.corrcoef(vc.share[k], sh1[k])[0, 1]),
                     'r_share_x1_pstuff': float(TA._partial(vc.share.corr(vc.x), vc.share.corr(vc.stuff), vc.stuff.corr(vc.x))),
                     'r_share_rv1_pstuff': float(TA._partial(vc.share.corr(vc.rv), vc.share.corr(vc.stuff), vc.stuff.corr(vc.rv))),
                     'r_locctl_share': float(vc.L_ren.corr(vc.share))})
        n = len(vc)
        idx = np.vstack([np.arange(n)[None, :], rng.integers(0, n, size=(B, n))])
        g = {c: vc[c].values.astype(float)[idx] for c in ('L_ren', 'x', 'rv', 'stuff', 'share')}
        base = {c: {tg: pr(g['L_ren'], g[tg], [g['stuff']] + ([g['share']] if c == 'stuff_share' else []))
                    for tg in ('x', 'rv')} for c in ('stuff', 'stuff_share')}
        for a in ARMS:
            La =(-pd.read_pickle(TA.table_path(a, y))['ren_full']).reindex(vc.index).values.astype(float)[idx]
            for c in ('stuff', 'stuff_share'):
                ctr = [g['stuff']] + ([g['share']] if c == 'stuff_share' else [])
                d = sum(pr(La, g[tg], ctr) - base[c][tg] for tg in ('x', 'rv')) / 2
                res[a][c].append({'d': float(d[0]), 'se': float(d[1:].std())})
        print(diag[-1], flush=True)
    out = {'diag': diag, 'curve': {}}
    print(f"\n{'h':>6} | {'| Stuff+ (decider)':>28} | {'| Stuff+ and opp share':>28}")
    for a in ARMS:
        row = {c: TA.pool(res[a][c]) for c in ('stuff', 'stuff_share')}
        out['curve'][a] = {'h': H[a], **row}
        f = lambda p: f"{p['mean_d'] * 1e4:+7.1f} se {p['se_boot'] * 1e4:5.1f} {p['wins']}/{p['k']}"
        print(f"{H[a]:>6} | {f(row['stuff']):>28} | {f(row['stuff_share']):>28}")
    tmp = OUT + '.tmp'
    json.dump(out, open(tmp, 'w'), indent=1)
    os.replace(tmp, OUT)
    print('wrote', OUT, '(deltas x 1e4 vs h = 0, rendered, mean of xRV and RV columns)')


if __name__ == '__main__':
    main()
