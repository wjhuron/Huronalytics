"""Backtest the MiLB FA screen: does the season-Y score rank season-Y+1 performance?

Five independent replicate pairs, 2021->22 ... 2025->26, each rebuilt from its own
FanGraphs lines (bt_pull.py). Coefficients for the fitted candidates come from the
OTHER four pairs (leave-one-pair-out), so every number below is out of sample.

Target (Y+1): the player's PA- (TBF-) weighted mean over every level he played,
MLB included, of the stat TRANSLATED to the AAA scale. Translations are additive
level offsets measured each season with player fixed effects (stat = player +
level), on players with 30+ PA / TBF at two or more levels; AAA = 0.
Hitters: wRC+. Pitchers: K-BB% and RA9 (sign flipped so higher is better).

Base (Y): gated on the BASE period only, as production is: the primary level is
the highest with 100+ PA / 75+ TBF. Every Y+1 outcome counts, weighted by Y+1
PA / TBF (a target-period gate selects on the outcome). A player with no Y+1
line cannot be scored and drops out; the count is printed.

Objective: weighted Pearson r of the score with the target, per held-out pair.

    python3 scripts/research/milb_fa/bt_run.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
D = os.path.join(ROOT, 'data', '_milb_fa', 'backtest')
LV = {0: 'MLB', 1: 'AAA', 2: 'AA', 3: 'A+', 4: 'A'}
RANK = {'AAA': 0, 'AA': 1, 'A+': 2, 'A': 3}
YEARS = range(2021, 2027)
MIN = {'bat': 100, 'pit': 75}
POOL_MIN = 50
SP_GS_SHARE = 0.5
KS = [0, 25, 50, 100, 200, 400, 800, 1600, 3200]
# horizon: 1 = next season, 2 = two seasons ahead (tests development, where age should matter)
H = int(os.environ.get('BT_H', '1'))


def load(yr, side):
    fr = []
    for l, name in LV.items():
        df = pd.DataFrame(json.load(open(os.path.join(D, f'{yr}_{side}_L{l}.json'))))
        df = df[df.xMLBAMID.notna()].copy()
        df['mlbId'] = df.xMLBAMID.astype(int)
        df['lvl'] = name
        fr.append(df)
    df = pd.concat(fr, ignore_index=True)
    w = 'PA' if side == 'bat' else 'TBF'
    df['w'] = pd.to_numeric(df[w], errors='coerce')
    df['Age'] = pd.to_numeric(df['Age'], errors='coerce')
    for c in ('wRC+', 'K%', 'BB%', 'ISO', 'K-BB%', 'SwStr%', 'xFIP', 'GB%', 'G', 'GS', 'R', 'IP', 'Spd', 'wBsR',
              'FB%', 'IFFB%', 'Pull%', 'HR/FB', 'BABIP', 'AVG', 'OBP', 'SLG', 'LOB%', 'HR/9', 'ERA', 'FIP', 'LD%'):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    if side == 'pit':
        ip = df['IP'].fillna(0)
        outs = np.floor(ip) * 3 + np.round((ip - np.floor(ip)) * 10)
        df['RA9'] = np.where(outs > 0, df['R'] * 27 / outs, np.nan)
        df['nRA9'] = -df['RA9']
        df['role'] = np.where(df.GS / df.G >= SP_GS_SHARE, 'SP', 'RP')
    return df[df.w > 0]


def offsets(df, stat, min_w=30):
    """Additive level offsets by alternating fixed effects; AAA = 0."""
    d = df[(df.w >= min_w) & df[stat].notna()]
    multi = d.groupby('mlbId').lvl.transform('nunique') >= 2
    d = d[multi]
    b = {l: 0.0 for l in LV.values()}
    for _ in range(200):
        a = (d.assign(r=d[stat] - d.lvl.map(b), x=lambda t: t.r * t.w)
             .groupby('mlbId')[['x', 'w']].sum().pipe(lambda t: t.x / t.w))
        r = d[stat] - d.mlbId.map(a)
        nb = (d.assign(x=r * d.w).groupby('lvl')[['x', 'w']].sum().pipe(lambda t: t.x / t.w)).to_dict()
        nb = {l: nb.get(l, 0.0) - nb.get('AAA', 0.0) for l in LV.values()}
        if max(abs(nb[l] - b[l]) for l in b) < 1e-9:
            break
        b = nb
    return b, int(multi.sum())


def wcorr(x, y, w):
    m = np.isfinite(x) & np.isfinite(y) & np.isfinite(w)
    x, y, w = x[m], y[m], w[m]
    mx, my = np.average(x, weights=w), np.average(y, weights=w)
    return np.sum(w * (x - mx) * (y - my)) / np.sqrt(np.sum(w * (x - mx) ** 2) * np.sum(w * (y - my) ** 2))


def peer_z(pool, stat, by):
    out = {}
    for _, g in pool[pool.lvl != 'MLB'].groupby(by):
        g = g[g[stat].notna() & g.Age.notna()]
        f = g[g.w >= POOL_MIN]
        if len(f) < 10:
            continue
        X = np.column_stack([np.ones(len(f)), f.Age, f.Age ** 2])
        sw = np.sqrt(f.w.values)
        beta = np.linalg.lstsq(X * sw[:, None], f[stat].values * sw, rcond=None)[0]
        sd = np.sqrt(np.sum(f.w * (f[stat] - X @ beta) ** 2) / f.w.sum())
        pred = np.column_stack([np.ones(len(g)), g.Age, g.Age ** 2]) @ beta
        out.update({(l, m): v for l, m, v in zip(g.lvl, g.mlbId, (g[stat].values - pred) / sd)})
    return out


def build(side, extra=()):
    stats = (['wRC+', 'K%', 'BB%', 'ISO'] if side == 'bat' else ['K-BB%', 'SwStr%', 'xFIP', 'GB%', 'nRA9']) + list(extra)
    tgts = ['wRC+'] if side == 'bat' else ['K-BB%', 'nRA9']
    data = {y: load(y, side) for y in YEARS}
    offs = {}
    for y in YEARS:
        offs[y] = {}
        for s in set(stats + tgts):
            offs[y][s], n = offsets(data[y], s)
        print(side, y, 'offsets from', n, 'multi-level lines:',
              {s: {l: round(v, 3) for l, v in offs[y][s].items()} for s in tgts})
    rows = []
    for y in list(YEARS)[:-H]:
        base, nxt = data[y], data[y + H]
        mi = base[base.lvl != 'MLB'].copy()
        mi['_r'] = mi.lvl.map(RANK)
        # skip anyone whose base season is mostly MLB: the screen is for minor leaguers
        mlb_w = base[base.lvl == 'MLB'].set_index('mlbId').w
        zs = {}
        if side == 'bat':
            zs['shipped'] = peer_z(base, 'wRC+', ['lvl'])
        else:
            a, b = peer_z(base, 'K-BB%', ['lvl', 'role']), peer_z(base, 'SwStr%', ['lvl', 'role'])
            zs['shipped'] = {k: (a[k] + b[k]) / 2 for k in a if k in b}
        for s in stats:
            zs['age_' + s] = peer_z(base, s, ['lvl'] + ([] if side == 'bat' else ['role']))
        tr = {}
        for t in tgts:
            n2 = nxt[nxt[t].notna()].copy()
            n2['x'] = (n2[t] - n2.lvl.map(offs[y + H][t])) * n2.w
            tr[t] = n2.groupby('mlbId')[['x', 'w']].sum().pipe(lambda q: q.x / q.w)
        tw = nxt.groupby('mlbId').w.sum()
        for mid, g in mi.groupby('mlbId'):
            if mlb_w.get(mid, 0) > g.w.sum():
                continue
            ok = g[g.w >= MIN[side]]
            if ok.empty:
                continue
            p = ok.sort_values('_r').iloc[0]
            rec = {'pair': y, 'mlbId': mid, 'lvl': p.lvl, 'age': p.Age, 'n': p.w,
                   'nAll': g.w.sum(), 'shipped': zs['shipped'].get((p.lvl, mid), np.nan),
                   'tw': tw.get(mid, 0)}
            if side == 'pit':
                tot = g[['G', 'GS']].sum()
                rec['role'] = 'SP' if tot.G and tot.GS / tot.G >= SP_GS_SHARE else 'RP'
            for s in stats:
                rec['raw_' + s] = p[s]
                rec['x_' + s] = p[s] - offs[y][s][p.lvl]
                gg = g[g[s].notna()]
                rec['xall_' + s] = (np.average(gg[s] - gg.lvl.map(offs[y][s]), weights=gg.w)
                                    if len(gg) else np.nan)
                rec['z_' + s] = zs['age_' + s].get((p.lvl, mid), np.nan)
            for t in tgts:
                rec['T_' + t] = tr[t].get(mid, np.nan)
            rows.append(rec)
    return pd.DataFrame(rows), tgts, stats


def fit_predict(train, test, cols, t, k=0, nkey='n'):
    """Weighted least squares on the shrunk inputs. x_ / xall_ inputs shrink on df[nkey];
    xallm_ inputs (the average WITH the MLB rows) shrink on df[nkey] + mlbN, because nAll
    counts minor league batters only. Until 2026-11-09 xallm_ inputs were never shrunk."""
    def shrink(df):
        out = df[cols].copy()
        if k:
            f = df[nkey] / (df[nkey] + k)
            if any(c.startswith('xallm_') for c in cols):
                if 'mlbN' not in df:
                    raise KeyError('xallm_ inputs need an mlbN column (bt_features.add_xallm adds it)')
                nm = df[nkey] + df['mlbN']
                fm = nm / (nm + k)
            for c in cols:
                if c.startswith(('x_', 'xall_', 'xallm_')):
                    mu = np.average(train[c], weights=train['tw'])
                    out[c] = mu + (df[c] - mu) * (fm if c.startswith('xallm_') else f)
        return out
    tr = train.dropna(subset=cols + ['T_' + t])
    tr = tr[tr.tw > 0]
    X = np.column_stack([np.ones(len(tr))] + [shrink(tr)[c] for c in cols])
    sw = np.sqrt(tr.tw.values)
    beta = np.linalg.lstsq(X * sw[:, None], tr['T_' + t].values * sw, rcond=None)[0]
    Xt = np.column_stack([np.ones(len(test))] + [shrink(test)[c] for c in cols])
    return Xt @ beta, beta


def evaluate(df, side, tgts, stats):
    df = df.copy()
    df['age2'] = df.age ** 2
    if side == 'bat':
        cands = {'C1 shipped (age-peer z wRC+)': ('score', 'shipped'),
                 'C0 raw wRC+ at level': ('score', 'raw_wRC+'),
                 'C2 translated wRC+': ('fit', ['x_wRC+']),
                 'C3 translated wRC+ + age': ('fit', ['x_wRC+', 'age']),
                 'C3q translated wRC+ + age + age^2': ('fit', ['x_wRC+', 'age', 'age2']),
                 'C4 all-level translated wRC+ + age': ('fit', ['xall_wRC+', 'age']),
                 'C5 C4 + K% BB% ISO': ('fit', ['xall_wRC+', 'xall_K%', 'xall_BB%', 'xall_ISO', 'age'])}
    else:
        df['isSP'] = (df.role == 'SP').astype(float)
        cands = {'C1 shipped (mean z K-BB%, SwStr%)': ('score', 'shipped'),
                 'C0 raw K-BB% at level': ('score', 'raw_K-BB%'),
                 'C2 translated K-BB% + SwStr%': ('fit', ['x_K-BB%', 'x_SwStr%', 'isSP']),
                 'C3 C2 + age': ('fit', ['x_K-BB%', 'x_SwStr%', 'isSP', 'age']),
                 'C4 all-level C3': ('fit', ['xall_K-BB%', 'xall_SwStr%', 'isSP', 'age']),
                 'C5 C4 + xFIP + GB%': ('fit', ['xall_K-BB%', 'xall_SwStr%', 'xall_xFIP', 'xall_GB%', 'isSP', 'age']),
                 'C6 C5 + RA9': ('fit', ['xall_K-BB%', 'xall_SwStr%', 'xall_xFIP', 'xall_GB%', 'xall_nRA9', 'isSP', 'age'])}
    pairs = sorted(df.pair.unique())
    groups = {'all': lambda d: d.index == d.index}
    groups.update({'AAA': lambda d: d.lvl == 'AAA', 'AA': lambda d: d.lvl == 'AA',
                   'FA-like (AAA/AA, age 25+)': lambda d: d.lvl.isin(['AAA', 'AA']) & (d.age >= 25)})
    if side == 'pit':
        groups.update({'SP': lambda d: d.role == 'SP', 'RP': lambda d: d.role == 'RP'})
    results = {}
    for t in tgts:
        scored = df[df.tw > 0 & df['T_' + t].notna()] if False else df[(df.tw > 0) & df['T_' + t].notna()]
        print(f'\n=== {side} target {t}: {len(scored)} player-pairs scored, '
              f'{int((df.tw == 0).sum())} with no next-season line dropped ===')
        print('per pair:', scored.groupby('pair').size().to_dict())
        preds = {}
        for name, (kind, spec) in cands.items():
            col = pd.Series(np.nan, index=scored.index)
            for hp in pairs:
                te = scored[scored.pair == hp]
                if kind == 'score':
                    col[te.index] = te[spec]
                else:
                    p, _ = fit_predict(scored[scored.pair != hp], te, spec, t)
                    col[te.index] = p
            preds[name] = col
        # shrinkage sweep on the best-looking fitted spec family (C4 for hitters, C5 for pitchers)
        sweep_spec = cands['C4 all-level translated wRC+ + age'][1] if side == 'bat' else cands['C5 C4 + xFIP + GB%'][1]
        sweep = {}
        for k in KS:
            col = pd.Series(np.nan, index=scored.index)
            for hp in pairs:
                te = scored[scored.pair == hp]
                p, _ = fit_predict(scored[scored.pair != hp], te, sweep_spec, t, k=k, nkey='nAll')
                col[te.index] = p
            sweep[k] = col
        for gname, gf in groups.items():
            m = gf(scored)
            tab = {}
            for name, col in list(preds.items()) + [(f'k={k}', c) for k, c in sweep.items()]:
                tab[name] = [wcorr(col[m & (scored.pair == hp)].values,
                                   scored.loc[m & (scored.pair == hp), 'T_' + t].values,
                                   scored.loc[m & (scored.pair == hp), 'tw'].values) for hp in pairs]
            tdf = pd.DataFrame(tab, index=[f'{p}->{p+H}' for p in pairs]).T
            tdf['mean'] = tdf.mean(axis=1)
            base = tdf.loc[list(preds)[0]]
            tdf['wins_vs_C1'] = [(row[:-1] > base[:-1]).sum() for _, row in tdf.iterrows()]
            print(f'\n-- group {gname} (n={int(m.sum())}), weighted r by held-out pair --')
            print(tdf.round(3).to_string())
            results[(t, gname)] = tdf
        # coefficients on all five pairs, for reading the age exchange rate
        for name in ('C3 translated wRC+ + age', 'C4 all-level translated wRC+ + age', 'C3 C2 + age',
                     'C5 C4 + xFIP + GB%'):
            if name in cands:
                _, beta = fit_predict(scored, scored.head(1), cands[name][1], t)
                print(f'{name} full-fit coefficients:',
                      dict(zip(['const'] + cands[name][1], np.round(beta, 4))))
    return results


if __name__ == '__main__':
    out = {}
    for side in sys.argv[1:] or ['bat', 'pit']:
        df, tgts, stats = build(side)
        df.to_csv(os.path.join(D, f'_bt_{side}_h{H}.csv'), index=False)
        res = evaluate(df, side, tgts, stats)
        out[side] = {f'{t}|{g}': v.round(4).to_dict() for (t, g), v in res.items()}
    with open(os.path.join(D, f'results_h{H}_{"_".join(sys.argv[1:]) or "all"}.json'), 'w') as f:
        json.dump(out, f, indent=1, default=str)
