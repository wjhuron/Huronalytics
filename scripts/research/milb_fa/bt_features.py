"""Shared feature builders for the measured additions to C5 (bt_history.py):
prior-season translated stat with a has-prior flag (hitters, k = 100) and age vs
level (pitchers). Used by project_2027.py for both the training frames and 2026.
"""
import numpy as np
import pandas as pd

import bt_run as BT

PRIOR_K = 100   # flat 50-200 on both horizons (bt_history.py, 2026-11-06)


def add_prev(df, prev_by_pair, stat='wRC+', mu=None):
    """prev_by_pair: {pair year: that pair's Y-1 FanGraphs frame (BT.load)}."""
    df = df.copy()
    for y, prev in prev_by_pair.items():
        off = BT.offsets(prev, stat)[0]
        q = prev[prev[stat].notna()].assign(x=lambda t: (t[stat] - t.lvl.map(off)) * t.w)
        agg = q.groupby('mlbId')[['x', 'w']].sum()
        m = df.pair == y
        df.loc[m, 'prev_' + stat] = df.loc[m, 'mlbId'].map(agg.x / agg.w)
        df.loc[m, 'prevN_' + stat] = df.loc[m, 'mlbId'].map(agg.w).fillna(0)
    has = df['prev_' + stat].notna()
    if mu is None:
        mu = np.average(df.loc[has, 'prev_' + stat], weights=df.loc[has, 'prevN_' + stat])
    f = df['prevN_' + stat] / (df['prevN_' + stat] + PRIOR_K)
    df['ps_' + stat] = mu + (df['prev_' + stat].fillna(mu) - mu) * f
    df['has_' + stat] = has.astype(float)
    return df, mu


def add_agerel(df, cur_by_pair):
    df = df.copy()
    for y, cur in cur_by_pair.items():
        cur = cur[cur.lvl != 'MLB']
        ok = cur.Age.notna() & (cur.w > 0)
        mean_age = cur[ok].assign(x=cur.Age * cur.w).groupby('lvl')[['x', 'w']].sum().pipe(lambda t: t.x / t.w)
        m = df.pair == y
        df.loc[m, 'agerel'] = df.loc[m, 'age'] - df.loc[m, 'lvl'].map(mean_age)
    return df


def add_xallm(df, stats, data_by_pair):
    """xallm_<stat>: the all-level translated average WITH the season's MLB rows, plus mlbN
    (MLB PA / TBF). bt_mlbline.py: it beats the minor-league-only average for players with
    MLB time (pitchers 5/5 and 4/5 pairs next season) and slightly loses for those without,
    so it is used for players with MLB time only."""
    df = df.copy()
    for y, d in data_by_pair.items():
        m = df.pair == y
        for s in stats:
            off = BT.offsets(d, s)[0]
            q = d[d[s].notna()].assign(x=lambda t: (t[s] - t.lvl.map(off)) * t.w)
            agg = q.groupby('mlbId')[['x', 'w']].sum()
            df.loc[m, 'xallm_' + s] = df.loc[m, 'mlbId'].map(agg.x / agg.w)
        mw = d[d.lvl == 'MLB'].set_index('mlbId').w
        df.loc[m, 'mlbN'] = df.loc[m, 'mlbId'].map(mw).fillna(0)
    return df
