"""predict_contracts.py: baseline contract predictions for the 2027 free-agent class.

Fits the three contract_model.py parts on every offseason (deal type: 2021-2026; AAV and years:
2020-2026) with the settings the LOYO sweeps chose (PARAMS / FEATS_USED below), then prices each
player in data/free_agents.json.

  * AAV is in the 2026 market level carried forward (the forward test: carrying the last level beat
    a linear trend in 3 of 4 offseasons). Floor: the 2026 MLB minimum, $780,000.
  * The AAV range is the 10th to 90th percentile of the LOYO residuals in log AAV, by role.
  * Deal type: 'MLB' when P(MLB deal | signed) >= .5, else 'MiLB'. The .5 cut is a convention: it
    trades two errors with no stated exchange rate. P is printed beside it.
  * Comps: the three past MLB deals nearest in standardized (age, WAR by season, Steamer WAR and
    rate[, versatility]) within the same role, with AAV restated in the 2027 market.
  * QO is 0 for every 2027 player: the offers are not made until after the World Series.

Output: ~/Downloads/fa_contract_predictions_2027.csv
Usage: python3 scripts/research/contracts/predict_contracts.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contract_model as cm

OUT = os.path.expanduser('~/Downloads/fa_contract_predictions_2027.csv')
MIN_SAL = 780_000
BAND_CUTS = [np.log(2e6), np.log(8e6)]   # price bands in the 2020 market (conventions)
PARAMS = json.load(open(os.path.join(cm.D, 'model_params.json')))
FEATS_USED = {k: cm.FEATS[v] for k, v in PARAMS['feats'].items()}
COMP_F = {'H': ['age', 'war0', 'war1', 'war2', 'stm_war', 'stm_rate', 'eff_pos'],
          'SP': ['age', 'war0', 'war1', 'war2', 'stm_war', 'stm_rate', 'ptn0'],
          'RP': ['age', 'war0', 'war1', 'war2', 'stm_war', 'stm_rate', 'lhp']}


def main():
    df = cm.load()
    lev = cm.market_level(df, cm.FEATS['history'])
    df['rel'] = df.laav - df.Y.map(lev)
    hist, live = df[df.Y < 2027], df[df.Y == 2027].copy()
    live['qo'] = 0
    L = lev[2026]

    mlb = hist[hist.outcome == 'mlb']
    sig = hist[hist.outcome.isin(['mlb', 'milb']) & (hist.Y != 2020)]
    fa, fy, fd = FEATS_USED['aav'], FEATS_USED['years'], FEATS_USED['deal']
    m_aav = cm.gbr(PARAMS['aav']).fit(mlb[fa], mlb.rel)
    m_yrs = cm.gbr(PARAMS['years'], 'poisson').fit(mlb[fy], mlb.years - 1)
    m_deal = cm.gbc(PARAMS['deal']).fit(sig[fd], (sig.outcome == 'mlb').astype(int))

    # LOYO residuals for the ranges
    res = []
    for Y in cm.HELD:
        tr, te = mlb[mlb.Y != Y], mlb[mlb.Y == Y]
        m = cm.gbr(PARAMS['aav']).fit(tr[fa], tr.rel)
        pt = m.predict(te[fa])
        res.append(pd.DataFrame({'role': te.role, 'band': np.digitize(pt, BAND_CUTS), 'r': te.rel - pt}))
        if Y == 2026:
            p26 = m.predict(te[fa])
            band26 = pd.DataFrame({'band': np.digitize(p26, BAND_CUTS), 'r': te.rel.values - p26})
    res = pd.concat(res)
    q = res.groupby('role').r.quantile([0.1, 0.9]).unstack()
    # Band levels: the 2026 market moved the top and the bottom apart (held out, $8M+ deals ran 30
    # log points above the single level and sub-$2M deals 30 below). The level for 2027 adds the
    # 2026 held-out mean residual of the player's band. Forward test 2023-2026: beats the single
    # level 4/4 on log error and 3/4 on dollar error; last 1 offseason beat last 2 and 3.
    band_off = band26.groupby('band').r.mean()
    # Expected (mean) AAV: the typical AAV is a median-type value (exp of a log prediction); the mean
    # is it times E[exp(residual)], per price band (smearing). Held out by offseason, band factors put
    # predicted dollars at 1.02x the dollars paid (one factor 1.08, by role 1.06).
    smear = res.groupby('band').r.apply(lambda x: np.exp(x).mean())
    print('expected/typical factor by band:', smear.round(3).to_dict())
    print('2026 band offsets (log):', band_off.round(3).to_dict())

    live['p_mlb'] = m_deal.predict_proba(live[fd])[:, 1]
    prel = m_aav.predict(live[fa])
    off = np.array([band_off.get(b, 0.0) for b in np.digitize(prel, BAND_CUTS)])
    live['aav_pred'] = np.maximum(np.exp(prel + L + off), MIN_SAL)
    live['aav_exp'] = np.maximum(np.exp(prel + L + off) * np.array([smear.get(b, 1.0) for b in np.digitize(prel, BAND_CUTS)]), MIN_SAL)
    live['aav_lo'] = np.maximum(live.aav_pred * np.exp(live.role.map(q[0.1])), MIN_SAL)
    live['aav_hi'] = live.aav_pred * np.exp(live.role.map(q[0.9]))
    live['yrs_mean'] = m_yrs.predict(live[fy]) + 1
    live['years_pred'] = live.yrs_mean.round().clip(lower=1).astype(int)
    live['deal'] = np.where(live.p_mlb >= 0.5, 'MLB', 'MiLB')

    comps = []
    for i, r in live.iterrows():
        f = COMP_F[r.role]
        pool = mlb[mlb.role == r.role].dropna(subset=['stm_war'])
        mu, sd = pool[f].mean(), pool[f].std()
        x = ((r[f] - mu) / sd).fillna(0)
        Z = ((pool[f] - mu) / sd).fillna(0)
        d = np.sqrt(((Z - x) ** 2).sum(axis=1))
        near = pool.loc[d.nsmallest(3).index]
        comps.append('; '.join(f"{c['name']} ({int(c.Y) - 1}-{str(int(c.Y))[2:]}, age {int(c.age)}): "
                               f"{int(c.years)}y/${c.aav * np.exp(L - lev[int(c.Y)]) / 1e6:.1f}M"
                               for _, c in near.iterrows()))
    live['comps'] = comps

    out = pd.DataFrame({
        'Name': live.name.map(lambda n: ' '.join(reversed([x.strip() for x in n.split(',', 1)])) if ',' in n else n), 'mlbId': live.mlbam.astype('Int64'), 'Role': live.role.map({'H': 'Position', 'SP': 'SP', 'RP': 'RP'}),
        'Pos': live.pos_lbl.fillna(live.top_pos), 'Throws': live.thr, 'Age 2027': live.age,
        'FA source': live.fa_status,
        'fWAR 2026': live.war0.round(1), 'fWAR 2025': live.war1.round(1), 'fWAR 2024': live.war2.round(1),
        'Steamer 2027 WAR': live.stm_war.round(1),
        'Eff. positions': live.eff_pos.round(1),
        'P(MLB deal)': live.p_mlb.round(2), 'Deal': live.deal,
        'Years': live.years_pred, 'Years (model)': live.yrs_mean.round(2),
        'AAV $M': (live.aav_pred / 1e6).round(1),
        'Expected AAV $M': (live.aav_exp / 1e6).round(1),
        'AAV low $M': (live.aav_lo / 1e6).round(1), 'AAV high $M': (live.aav_hi / 1e6).round(1),
        'Total $M': (live.aav_pred * live.years_pred / 1e6).round(1),
        'Comps (2027 $)': live.comps,
    })
    mask = out.Deal == 'MiLB'
    for c in ('Years', 'Years (model)', 'AAV $M', 'Expected AAV $M', 'AAV low $M', 'AAV high $M', 'Total $M'):
        out[c] = out[c].astype(object).where(~mask, '')
    out = out.sort_values(['Deal', 'Total $M'], ascending=[True, False], key=lambda s: pd.to_numeric(s, errors='coerce') if s.name == 'Total $M' else s)
    out.to_csv(OUT + '.tmp', index=False)
    os.replace(OUT + '.tmp', OUT)
    print(f'wrote {len(out)} rows to {OUT}; MLB {int((~mask).sum())}, MiLB {int(mask.sum())}')
    print('AAV LOYO residual 10-90% (log) by role:', q.round(2).to_dict('index'))
    return out


if __name__ == '__main__':
    main()
