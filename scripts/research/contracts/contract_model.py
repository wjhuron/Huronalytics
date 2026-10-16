"""contract_model.py: free-agent contract model, fitted on the 2020-2026 offseasons, scored one offseason out.

Three parts, each a gradient-boosted tree model on the same player features:
  deal   P(MLB deal | signed)               classifier, log loss
  aav    log AAV for MLB deals, in that offseason's market (log AAV minus the offseason's level)
  years  guaranteed years for MLB deals     Poisson loss on years - 1

Market level: the offseason's level is the year effect of a linear model of log AAV on the same
features plus offseason dummies (MLB deals). The model prices players RELATIVE to their market; the
level for 2027 is a separate forward test (carry the last level forward against a linear trend).

Validation: leave one offseason out (LOYO), 2021-2026 held out in turn (2020 trains only: its tracker
lacks most minor-league deals). Every feature set and every tree setting is chosen on LOYO, and a
choice must win most held-out offseasons, not only the mean.

Usage: python3 scripts/research/contracts/contract_model.py [sweep|features|level]
Output: data/_fa_contracts/model_*.json (scratch)
"""
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LinearRegression

warnings.filterwarnings('ignore')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
D = os.path.join(ROOT, 'data', '_fa_contracts')
HELD = range(2021, 2027)
UNIT = {'H': 600.0, 'SP': 180.0, 'RP': 65.0}


def load():
    df = pd.read_csv(os.path.join(D, 'dataset.csv'), dtype={'fg': str})
    u = df.role.map(UNIT)
    # the archived 2020 Steamer is the 60-game projection (Cole 2.2 WAR in 75 IP): restate to 162
    s20 = np.where(df.Y == 2020, 162 / 60, 1.0)
    df['stm_war'] = df.stm_war * s20
    df['stm_pt'] = df.stm_pt * s20
    for k in range(3):
        df[f'ptn{k}'] = df[f'pt{k}'] / u
    df['stm_ptn'] = df.stm_pt / u
    # Missing Steamer (the 2026 archive lacks 98 of that class, e.g. King, Díaz; a few 2020 rows)
    # is IMPUTED from the WAR record, per role, by a linear fit on rows that have it. Left as NaN,
    # the trees learned 'no projection' as a low-value sign and priced King's 3/75 at 3.9M.
    df['stm_imputed'] = df.stm_war.isna().astype(int)
    xs = ['age', 'war0', 'war1', 'war2', 'ptn0', 'ptn1', 'ptn2']
    for role, g in df.groupby('role'):
        have = g[g.stm_war.notna() & (g.ptn0 + g.ptn1 + g.ptn2 > 0)]
        miss = g.index[g.stm_war.isna()]
        if len(miss):
            for col in ('stm_war', 'stm_ptn'):
                lr_ = LinearRegression().fit(have[xs], have[col])
                df.loc[miss, col] = lr_.predict(df.loc[miss, xs])
            df.loc[miss, 'stm_pt'] = df.loc[miss, 'stm_ptn'] * UNIT[role]
    df['stm_rate'] = np.where(df.stm_pt > 0.15 * u, df.stm_war / df.stm_pt * u, np.nan)
    df['war3'] = df.war0 + df.war1 + df.war2
    df['is_sp'] = (df.role == 'SP').astype(int)
    df['is_rp'] = (df.role == 'RP').astype(int)
    df['lhp'] = (df.thr == 'L').astype(int)
    df['prem'] = df[['sh_C', 'sh_SS', 'sh_CF', 'sh_2B']].sum(axis=1).where(df.role == 'H')
    df['sh_C'] = df.sh_C.where(df.role == 'H')
    df['sh_1bdh'] = (df['sh_1B']).where(df.role == 'H')
    df['laav'] = np.log(df.aav)
    return df


FEATS = {
    'platform':  ['age', 'is_sp', 'is_rp', 'war0', 'ptn0'],
    'history':   ['age', 'is_sp', 'is_rp', 'war0', 'war1', 'war2', 'ptn0', 'ptn1', 'ptn2'],
    'steamer':   ['age', 'is_sp', 'is_rp', 'war0', 'war1', 'war2', 'ptn0', 'ptn1', 'ptn2', 'stm_war', 'stm_rate'],
    'full':      ['age', 'is_sp', 'is_rp', 'war0', 'war1', 'war2', 'ptn0', 'ptn1', 'ptn2', 'stm_war', 'stm_rate',
                  'lhp', 'qo', 'eff_pos', 'prem', 'sh_C', 'sh_1bdh'],
}
# ablations of the full set (2027 has no QO decisions yet; versatility is the utility-player question)
FEATS['full_noqo'] = [f for f in FEATS['full'] if f != 'qo']
FEATS['full_novers'] = [f for f in FEATS['full'] if f not in ('eff_pos', 'prem', 'sh_C', 'sh_1bdh')]
FEATS['full_nolhp'] = [f for f in FEATS['full'] if f != 'lhp']
# AAV set: QO out (unknown for 2027 until after the World Series), hand out (3/6 LOYO, mean worse)
FEATS['aav_final'] = [f for f in FEATS['full'] if f not in ('qo', 'lhp')]


def market_level(df, feats):
    """Offseason year effects in log AAV, from a linear model on MLB deals (features filled for the
    linear fit only: NaN -> column median, a level estimate, never a model input)."""
    m = df[df.outcome == 'mlb'].copy()
    X = m[feats].fillna(m[feats].median())
    yd = pd.get_dummies(m.Y, prefix='y', drop_first=True).astype(float)
    lr = LinearRegression().fit(pd.concat([X, yd], axis=1), m.laav)
    lev = {int(m.Y.min()): 0.0}
    for c, b in zip(list(X.columns) + list(yd.columns), lr.coef_):
        if c.startswith('y_'):
            lev[int(c[2:])] = float(b)
    return lev


def gbr(params, loss='squared_error'):
    return HistGradientBoostingRegressor(loss=loss, max_iter=params['it'], learning_rate=params['lr'],
                                         max_leaf_nodes=params['leaves'], min_samples_leaf=params['msl'],
                                         l2_regularization=params.get('l2', 0.0), random_state=0)


def gbc(params):
    return HistGradientBoostingClassifier(max_iter=params['it'], learning_rate=params['lr'],
                                          max_leaf_nodes=params['leaves'], min_samples_leaf=params['msl'],
                                          l2_regularization=params.get('l2', 0.0), random_state=0)


def loyo(df, feats, params, part):
    """Per held-out offseason score for one part. aav: RMSE of log AAV relative to the level;
    years: MAE of years; deal: log loss."""
    lev = market_level(df, FEATS['history'])
    df = df.assign(rel=df.laav - df.Y.map(lev))
    out = {}
    for Y in HELD:
        tr, te = df[df.Y != Y], df[df.Y == Y]
        if part == 'deal':
            tr = tr[tr.outcome.isin(['mlb', 'milb']) & (tr.Y != 2020)]   # 2020 tracker lacks most MiLB deals
            te = te[te.outcome.isin(['mlb', 'milb'])]
            m = gbc(params).fit(tr[feats], (tr.outcome == 'mlb').astype(int))
            p = np.clip(m.predict_proba(te[feats])[:, 1], 1e-4, 1 - 1e-4)
            y = (te.outcome == 'mlb').astype(int).values
            out[Y] = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
        elif part == 'aav':
            tr, te = tr[tr.outcome == 'mlb'], te[te.outcome == 'mlb']
            m = gbr(params).fit(tr[feats], tr.rel)
            out[Y] = float(np.sqrt(np.mean((m.predict(te[feats]) - te.rel) ** 2)))
        else:
            tr, te = tr[tr.outcome == 'mlb'], te[te.outcome == 'mlb']
            m = gbr(params, 'poisson').fit(tr[feats], tr.years - 1)
            out[Y] = float(np.mean(np.abs(m.predict(te[feats]) + 1 - te.years)))
    return out


def aav_loyo(df, feats, params, mode):
    """AAV variants, held out by offseason. mode 'level': log AAV minus the offseason level (shipped v1);
    'yfeat': log AAV with the offseason as a feature (a held-out or future offseason is priced like
    its nearest offseason, segment by segment); 'gamma': AAV in dollars with the offseason as a
    feature, gamma loss (log link, predicts the MEAN). Returns per-year log RMSE, dollar ratio
    sum(pred)/sum(actual), and the predictions."""
    lev = market_level(df, FEATS['history'])
    m = df[df.outcome == 'mlb'].assign(rel=lambda x: x.laav - x.Y.map(lev))
    f = feats + (['Y'] if mode != 'level' else [])
    out, preds = {}, []
    for Y in HELD:
        tr, te = m[m.Y != Y], m[m.Y == Y]
        if mode == 'level':
            p = np.exp(gbr(params).fit(tr[f], tr.rel).predict(te[f]) + lev[Y])
        elif mode == 'yfeat':
            p = np.exp(gbr(params).fit(tr[f], tr.laav).predict(te[f]))
        else:
            p = gbr(params, 'gamma').fit(tr[f], tr.aav / 1e6).predict(te[f]) * 1e6
        out[Y] = {'rmse_log': float(np.sqrt(np.mean((np.log(p) - te.laav) ** 2))),
                  'dollar_ratio': float(p.sum() / te.aav.sum()),
                  'mae_m': float(np.mean(np.abs(p - te.aav)) / 1e6)}
        preds.append(te.assign(pred=p))
    return out, pd.concat(preds)


BASE = {'it': 300, 'lr': 0.03, 'leaves': 8, 'msl': 20, 'l2': 0.0}


def features():
    df = load()
    res = {}
    for part in ('deal', 'aav', 'years'):
        res[part] = {}
        for name, f in FEATS.items():
            res[part][name] = loyo(df, f, BASE, part)
        ref = res[part]['history']
        print(f'\n{part}: per held-out offseason ({"log loss" if part == "deal" else "RMSE log AAV" if part == "aav" else "MAE years"})')
        print('  set        ' + ' '.join(f'{y:>7d}' for y in HELD) + '    mean  wins vs history')
        for name, s in res[part].items():
            w = sum(s[y] < ref[y] for y in HELD)
            print(f'  {name:10s} ' + ' '.join(f'{s[y]:7.3f}' for y in HELD) + f'  {np.mean(list(s.values())):6.3f}  {w}/6')
    json.dump(res, open(os.path.join(D, 'model_features.json'), 'w'), indent=1)


GRID = {'lr': (0.01, 0.02, 0.03, 0.05, 0.08, 0.12), 'leaves': (3, 5, 8, 12, 20), 'msl': (5, 10, 20, 40, 80)}


def sweep(part, feats_name, grid=None, tag=''):
    """Tree settings: learning rate x leaves x min leaf size at a fixed 300 rounds (lr and rounds trade
    off; the rounds are fixed and lr carries the strength)."""
    df = load()
    f = FEATS[feats_name]
    rows = []
    g = dict(GRID, **(grid or {}))
    for lr in g['lr']:
        for leaves in g['leaves']:
            for msl in g['msl']:
                p = dict(BASE, lr=lr, leaves=leaves, msl=msl)
                s = loyo(df, f, p, part)
                rows.append({'lr': lr, 'leaves': leaves, 'msl': msl, 'mean': float(np.mean(list(s.values()))), **{str(y): s[y] for y in HELD}})
    r = pd.DataFrame(rows).sort_values('mean')
    r.to_csv(os.path.join(D, f'model_sweep_{part}_{feats_name}{tag}.csv'), index=False)
    print(r.head(12).to_string(index=False))
    best = r.iloc[0]
    for k in ('lr', 'leaves', 'msl'):
        g = r.groupby(k)['mean'].min()
        print(f'  best mean by {k}: ' + '  '.join(f'{i}:{v:.4f}' for i, v in g.items()))
    return best


def level():
    """Forward test of the 2027 market level: for each offseason Y >= 2023, predict its level from the
    earlier offseasons only, by (a) carrying the last level and (b) a linear trend over the earlier levels."""
    df = load()
    lev = market_level(df, FEATS['history'])
    print('levels (log AAV, 2020 = 0):', {k: round(v, 3) for k, v in sorted(lev.items())})
    for Y in range(2023, 2027):
        past = {k: v for k, v in lev.items() if k < Y}
        carry = past[max(past)]
        ks = sorted(past)
        b = np.polyfit(ks, [past[k] for k in ks], 1)
        trend = np.polyval(b, Y)
        b3 = np.polyfit(ks[-3:], [past[k] for k in ks[-3:]], 1)
        print(f'  {Y}: actual {lev[Y]:+.3f}  carry {carry:+.3f} (err {carry - lev[Y]:+.3f})  '
              f'trend-all {trend:+.3f} (err {trend - lev[Y]:+.3f})  trend-last3 {np.polyval(b3, Y):+.3f} (err {np.polyval(b3, Y) - lev[Y]:+.3f})')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'features'
    if cmd == 'features':
        features()
    elif cmd == 'sweep':
        sweep(sys.argv[2], sys.argv[3], json.loads(sys.argv[4]) if len(sys.argv) > 4 else None,
              sys.argv[5] if len(sys.argv) > 5 else '')
    elif cmd == 'level':
        level()
