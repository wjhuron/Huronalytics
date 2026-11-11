"""Rank Wally's free-agent pitcher targets plus my adds by the backtest winner (2026-11-09).

rank_backtest.py: the shipped projection (projections_pit.csv, proj1_RA9_MLB) beat every
alternative within role on next-season RA9, and nothing added to it (Stuff+, fastball velo,
own RA9, separate role fits) cleared its bar. So covered pitchers take the shipped number.
rank_small.py: for the pitchers it does not cover (base season mostly MLB, or under 75 TBF at
every level) the same spec on all-level inputs WITH the MLB rows (xallm_) ranks small AAA
samples better than raw K-BB% (4/5 pairs). Those pitchers take that spec, fit on every pair
of the rank_small frame and put on the MLB scale with the 2026 MLB offset, as shipped.
Role: SP if starts are 40%+ of 2026 AAA + MLB games (the cutoff used in the chat ranking).
    python3 scripts/research/milb_fa/rank_live.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_run as BT  # noqa: E402
import rank_small as RS  # noqa: E402

D = os.path.join(BT.ROOT, 'data', '_milb_fa')
ADDS = {'Bryse Wilson', 'Carl Edwards Jr.', 'Elieser Hernández', 'Seth Martinez'}


def disp(n):
    last, _, first = n.partition(', ')
    return f'{first} {last}'.strip() if first else n


def main():
    t = pd.read_csv(os.path.join(D, 'card_targets.csv'))
    p = t[t.side == 'pitcher'].drop_duplicates('mlbId')
    tg = set()
    for _, _, fs in os.walk(os.path.expanduser('~/Downloads/MiLB FA Cards 2026/Targets')):
        tg |= {f.split(' - ')[0] for f in fs if f.endswith('.png')}
    p = p.assign(disp=p.name.map(disp))
    p = p[p.disp.isin(tg | ADDS)]
    miss = (tg | ADDS) - set(p.disp)
    if miss:
        sys.exit(f'no id for {miss}')
    # --mlb-adds (2026-11-11, per Wally): also rank every free pitcher with 2026 MLB time whose
    # last list move came before 2026-10-28 (mlb_released_adds.py writes the list from Sheets)
    mlb_adds = '--mlb-adds' in sys.argv
    if mlb_adds:
        ma = pd.read_csv(os.path.join(D, 'mlb_adds.csv'))
        ma = ma[ma.signedSince.isna() & ~ma.mlbId.isin(p.mlbId)]
        p = pd.concat([p, pd.DataFrame({'mlbId': ma.mlbId.values, 'disp': ma.Player.map(disp).values})],
                      ignore_index=True)
    # 2026 all-level inputs, MLB included
    data = BT.load(2026, 'pit')
    offs = {s: BT.offsets(data, s)[0] for s in RS.STATS}
    rows = []
    for mid in p.mlbId:
        g = data[data.mlbId == mid]
        rec = {'mlbId': mid, 'pair': 2026, 'nAll': g.w.sum(), 'mlbN': g[g.lvl == 'MLB'].w.sum(),
               'age': g.Age.dropna().iloc[0] if g.Age.notna().any() else np.nan}
        gg = g[['G', 'GS']].sum()
        rec['gs_share'] = gg.GS / gg.G if gg.G else np.nan
        rec['isSP'] = float(bool(gg.G) and gg.GS / gg.G >= BT.SP_GS_SHARE)
        for s in RS.STATS:
            q = g[g[s].notna()]
            rec['xallm_' + s] = np.average(q[s] - q.lvl.map(offs[s]), weights=q.w) if len(q) else np.nan
        rows.append(rec)
    f = pd.DataFrame(rows)
    fr = RS.build()
    tr = fr[(fr.tw > 0) & fr.T_nRA9.notna()].dropna(subset=RS.SPEC)
    ok = f.dropna(subset=RS.SPEC)
    pred, beta = RS.fit_predict_m(tr, ok, RS.SPEC, 'nRA9', RS.K)
    f.loc[ok.index, 'xallmRA9'] = -(pred + offs['nRA9']['MLB'])
    # small samples (under 75 TBF at every minor level, mostly minor league) take the heavy
    # shrinkage their own sweep chose
    minor = data[data.lvl != 'MLB'].groupby('mlbId').w
    f['small'] = (f.mlbId.map(minor.max()).fillna(0) < BT.MIN['pit']) & (f.mlbN <= f.nAll - f.mlbN)
    sm = ok[f.loc[ok.index, 'small']]
    if len(sm):
        ps, _ = RS.fit_predict_m(tr, sm, RS.SPEC, 'nRA9', RS.K_SMALL)
        f.loc[sm.index, 'xallmRA9'] = -(ps + offs['nRA9']['MLB'])
    print('xallm spec beta', dict(zip(['const'] + RS.SPEC, np.round(beta, 4))))
    # level calibration: the held-out bias of each uncovered group (nRA9 units, + = the group
    # did better than predicted), so the groups sit on one scale in a mixed list
    b_small, per_s = RS.heldout_bias(fr, (fr.grp == 'small MiLB') & (fr.top == 'AAA'), RS.K_SMALL)
    b_mlb, per_m = RS.heldout_bias(fr, fr.grp == 'MLB-primary', RS.K)
    print(f'held-out bias: small AAA {b_small:+.3f} {np.round(per_s, 3)}; MLB-primary {b_mlb:+.3f} {np.round(per_m, 3)}')
    pr = pd.read_csv(os.path.join(D, 'projections_pit.csv')).drop_duplicates('mlbId').set_index('mlbId')
    f['shipRA9'] = f.mlbId.map(pr['proj1_RA9_MLB'])
    both = f.dropna(subset=['shipRA9', 'xallmRA9'])
    print(f'shipped vs xallm spec on the {len(both)} covered: r {both[["shipRA9", "xallmRA9"]].corr().iloc[0, 1]:.3f}, '
          f'mean gap {(both.xallmRA9 - both.shipRA9).mean():+.3f}')
    f['source'] = np.where(f.shipRA9.notna(), 'shipped projection', 'xallm spec (not covered)')
    # put the uncovered on the shipped scale: shift by the mean gap measured on the covered
    gap = (both.xallmRA9 - both.shipRA9).mean()
    # then the uncovered groups take their own held-out bias (RA9 falls when the group beat its prediction)
    unc = f.shipRA9.isna()
    f.loc[unc, 'xallmRA9'] -= np.where(f.loc[unc, 'small'], b_small, b_mlb)
    f['projRA9'] = f.shipRA9.fillna(f.xallmRA9 - gap)
    f['name'] = f.mlbId.map(p.set_index('mlbId').disp)
    f['add'] = f.name.isin(ADDS)
    if mlb_adds:
        f['mlbAdd'] = f.mlbId.isin(ma.mlbId)
        f['sheetMLB_TBF'] = f.mlbId.map(ma.set_index('mlbId').MLB_TBF)
        f['add'] |= f.mlbAdd
        nop = f[f.mlbAdd & f.projRA9.isna()]
        if len(nop):
            print(f'NO PROJECTION (no 2026 FanGraphs line or inputs): {", ".join(nop.name)}')
    # role from 2026 AAA + MLB games, starts share >= 40% = SP
    aaa_mlb = data[data.lvl.isin(['AAA', 'MLB'])].groupby('mlbId')[['G', 'GS']].sum()
    f['role'] = np.where(f.mlbId.map(aaa_mlb.GS / aaa_mlb.G) >= 0.4, 'SP', 'RP')
    f = f.sort_values(['role', 'projRA9'])
    f.to_csv(os.path.join(D, '_rank_live_mlbadds.csv' if mlb_adds else '_rank_live.csv'), index=False)
    for r, g in f.groupby('role', sort=False):
        print(f'\n{r} ({len(g)})')
        for i, (_, x) in enumerate(g.iterrows(), 1):
            print(f'{i:3d} {x["name"]:22s} RA9 {x.projRA9:5.2f}  {("* small" if x.small else "* MLB") if x.source != "shipped projection" else "       "}'
                  f'{" (add)" if x["add"] else ""}')


if __name__ == '__main__':
    main()
