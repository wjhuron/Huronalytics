"""Social card table: Zone% or Strike%, and which columns can carry percentile color?

Cell: season x pitcher hand x batter hand x pitch type for one pitcher, at least
100 pitches, 2021-2025. A percentile color ranks a pitcher inside his own pitch type
and hands, so every r here is WITHIN that group (group means removed).

  reliability  split-half r, Spearman-Brown up to the full cell, 10 random splits
  year to year same cell in Y+1, gated on Y only
  value        within-group r with the cell's run value per 100 (pitcher-positive)
  pitcher      whole-pitcher Zone% and Strike% against BB%, Y and Y+1, 500+ pitches in Y,
               Y+1 weighted by its pitches

    python3 scripts/research/cards/social_table_columns.py
"""
import gc
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
YEARS = [2021, 2022, 2023, 2024, 2025]
KEY = ['p', 'th', 's', 't']
STRIKE = {'called_strike', 'swinging_strike', 'swinging_strike_blocked', 'foul', 'foul_tip', 'foul_bunt',
          'missed_bunt', 'hit_into_play', 'automatic_strike', 'bunt_foul_tip'}
SWING = {'swinging_strike', 'swinging_strike_blocked', 'foul', 'foul_tip', 'hit_into_play'}
WHIFF = {'swinging_strike', 'swinging_strike_blocked'}
HALF_PLATE, BALL_R = 8.5 / 12, 1.45 / 12
STATS = {'zone': ('zone', None), 'strike': ('strike', None), 'whiff': ('whiff', 'swing'), 'xwobacon': ('xw', 'bip')}


def num(s):
    return pd.to_numeric(s, errors='coerce').to_numpy('float64', na_value=np.nan)


def season(y):
    d = pd.read_pickle(os.path.join(ROOT, 'data', f'_statcast{y}_cache.pkl'))
    desc = d.description.astype('object')
    o = pd.DataFrame({'p': num(d.pitcher), 'th': d.p_throws.astype('object').to_numpy(),
                      's': d.stand.astype('object').to_numpy(), 't': d.pitch_type.astype('object').to_numpy()})
    px, pz, top, bot = num(d.plate_x), num(d.plate_z), num(d.sz_top), num(d.sz_bot)
    dx = np.maximum(0, np.abs(px) - HALF_PLATE)
    dz = np.maximum(np.maximum(0, bot - pz), pz - top)
    o['zone'] = np.where(np.isnan(dx + dz), np.nan, (np.hypot(dx, dz) <= BALL_R).astype(float))
    o['strike'] = desc.isin(STRIKE).to_numpy(float)
    o['swing'] = desc.isin(SWING).to_numpy(float)
    o['whiff'] = np.where(o.swing == 1, desc.isin(WHIFF).to_numpy(float), np.nan)
    isbip = (d['type'].astype('object') == 'X') & d.bb_type.notna() & d.bb_type.astype('object').ne('bunt')
    o['bip'] = isbip.to_numpy(float)
    o['xw'] = np.where(o.bip == 1, num(d.estimated_woba_using_speedangle), np.nan)
    o['rv'] = -num(d.delta_run_exp)
    ev = d.events.astype('object')
    o['pa'] = ev.notna().to_numpy(float)
    o['bb'] = ev.eq('walk').to_numpy(float)
    del d
    gc.collect()
    return o.dropna(subset=['p', 'th', 's', 't'])


def within(df, cols):
    g = df.groupby(['th', 's', 't'])
    return df[cols] - g[cols].transform('mean')


def r(a, b, w=None):
    ok = ~(np.isnan(a) | np.isnan(b))
    a, b = a[ok], b[ok]
    return float(np.corrcoef(a, b)[0, 1]) if w is None else float(
        np.cov(a, b, aweights=w[ok])[0, 1] / np.sqrt(np.cov(a, aweights=w[ok]) * np.cov(b, aweights=w[ok])))


def cells(o):
    f = o.groupby(KEY).agg(n=('strike', 'size'), zone=('zone', 'mean'), strike=('strike', 'mean'), whiff=('whiff', 'mean'),
                           xw=('xw', 'mean'), rv=('rv', 'mean'), swing=('swing', 'sum'), bip=('bip', 'sum'))
    return f[f.n >= 100].reset_index()


def main():
    rng = np.random.default_rng(0)
    frames = {y: season(y) for y in YEARS}
    rel = {k: [] for k in STATS}
    zs_corr, val = [], {k: [] for k in STATS}
    for y, o in frames.items():
        c = cells(o)
        w = within(c, ['zone', 'strike', 'whiff', 'xw', 'rv'])
        zs_corr.append(r(w.zone.to_numpy(), w.strike.to_numpy()))
        for k, (col, _) in STATS.items():
            val[k].append(r(w[col].to_numpy(), w.rv.to_numpy()))
        keep = c[KEY]
        m = o.merge(keep, on=KEY)
        for k, (col, _) in STATS.items():
            rs = []
            for _r in range(10):
                bit = rng.integers(0, 2, len(m))
                h = m.assign(_b=bit).groupby(KEY + ['_b'])[col].mean().unstack('_b').dropna().reset_index()
                x = within(h, [0, 1])
                q = r(x[0].to_numpy(), x[1].to_numpy())
                rs.append(2 * q / (1 + q))
            rel[k].append(float(np.mean(rs)))
    yoy = {k: [] for k in STATS}
    nxt = {k: [] for k in STATS}
    for y0, y1 in zip(YEARS, YEARS[1:]):
        a, b = cells(frames[y0]), frames[y1].groupby(KEY).agg(
            n1=('strike', 'size'), zone1=('zone', 'mean'), strike1=('strike', 'mean'), whiff1=('whiff', 'mean'),
            xw1=('xw', 'mean'), rv1=('rv', 'mean')).reset_index()
        j = a.merge(b, on=KEY)
        w = within(j, ['zone', 'strike', 'whiff', 'xw', 'zone1', 'strike1', 'whiff1', 'xw1', 'rv1'])
        wt = j.n1.to_numpy(float)
        for k, (col, _) in STATS.items():
            yoy[k].append(r(w[col].to_numpy(), w[col + '1'].to_numpy(), wt))
            nxt[k].append(r(w[col].to_numpy(), w.rv1.to_numpy(), wt))
    print(f"cells per season about {np.mean([len(cells(o)) for o in frames.values()]):.0f}; within-group Zone% x Strike% r "
          f"{np.mean(zs_corr):.3f}")
    print('stat       reliability  year-to-year  same-season RV/100  next-season RV/100')
    for k in STATS:
        print(f'{k:10s} {np.mean(rel[k]):.3f}        {np.mean(yoy[k]):.3f}         {np.mean(val[k]):+.3f}              {np.mean(nxt[k]):+.3f}'
              f'   by pair yoy {[round(x, 3) for x in yoy[k]]}  next {[round(x, 3) for x in nxt[k]]}')
    res = {'zone': {'now': [], 'next': []}, 'strike': {'now': [], 'next': []}}
    for y0, y1 in zip(YEARS, YEARS[1:]):
        for y, tag in ((y0, 'a'),):
            pass
        ag = lambda o: o.groupby('p').agg(n=('strike', 'size'), zone=('zone', 'mean'), strike=('strike', 'mean'),
                                          pa=('pa', 'sum'), bb=('bb', 'sum'))
        a, b = ag(frames[y0]), ag(frames[y1])
        a = a[a.n >= 500]
        a['bbp'] = a.bb / a.pa
        b['bbp'] = b.bb / b.pa.where(b.pa > 0)
        j = a.join(b, rsuffix='1', how='inner')
        for k in ('zone', 'strike'):
            res[k]['now'].append(r(j[k].to_numpy(), j.bbp.to_numpy()))
            res[k]['next'].append(r(j[k].to_numpy(), j.bbp1.to_numpy(), j.pa1.to_numpy(float)))
    print('pitcher-level r with BB%:')
    for k, v in res.items():
        print(f"  {k:7s} same season {np.mean(v['now']):+.3f} {[round(x, 3) for x in v['now']]}  next season {np.mean(v['next']):+.3f} {[round(x, 3) for x in v['next']]}")


if __name__ == '__main__':
    main()
