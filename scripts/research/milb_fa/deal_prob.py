"""P(MLB deal) for the free-agent pitcher tier list (2026-11-11, per Wally: "Add the P(MLB deal)
column to the tier list, and remove any guy you think is 100%").

An MLB deal is guaranteed money and a 40-man spot. The probability is the deal part of the
October contract model (scripts/research/contracts/contract_model.py, settings in
data/_fa_contracts/model_params.json): a gradient-boosted classifier on age, role, three seasons of
FanGraphs WAR and innings, and the Steamer 2027 projection, fit on every signed free agent
2021-2026 (outcome 'mlb' = a tracker deal with salary, 'milb' = signed with none). It is
P(MLB deal | signed). Held out by offseason it is well calibrated for pitchers (predicted .62 /
.77 / .91 against .55 / .72 / .96 signed to MLB deals).

Inputs for a pitcher outside the 2027 tracker class are built exactly as build_contract_dataset.py
builds them: FanGraphs WAR and IP 2024-2026 (0 for a season with no MLB line) and Steamer 2027,
matched by FanGraphs id or MLBAM id. A missing Steamer line is imputed from the WAR record per
role, as contract_model.load does (fit on rows with a real projection).

OUT OF RANGE: only 35 of the model's 815 signed pitchers had under MIN_MLB_IP MLB innings over
three seasons, and they were tracker players, not six-year minor-league free agents. Below that
line the probability is blanked rather than reported (a 23-year-old with no MLB inning read .90,
five pitchers with no MLB inning and no Steamer line all read .57). MIN_MLB_IP is a convention.
"""
import json
import os
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'contracts'))
import build_contract_dataset as B  # noqa: E402
import contract_model as cm  # noqa: E402

MIN_MLB_IP = 20


def p_mlb_deal(f):
    """f: DataFrame with mlbId, Role ('SP'/'RP') and age (2026 season age).
    Returns a DataFrame indexed like f with p_mlb (NaN when out of range), mlbIP3 and stm_imputed."""
    act = {y: B.load_actual(y) for y in (2024, 2025, 2026)}
    am2fg = {int(e['mlbam']): fg for y in act for fg, e in act[y].items() if e['mlbam']}
    st_fg, st_am = B.steamer(2027)
    rows = []
    for r in f.itertuples():
        fg = am2fg.get(int(r.mlbId))
        hist = [act[2026 - k].get(fg, {}) if fg else {} for k in range(3)]
        stm = (st_fg.get(fg) if fg else None) or st_am.get(int(r.mlbId)) or {}
        rows.append({'role': r.Role, 'age': r.age + 1,
                     **{f'war{k}': hist[k].get('pwar', 0.0) for k in range(3)},
                     **{f'pt{k}': hist[k].get('ip', 0.0) for k in range(3)},
                     'stm_war': stm.get('pwar'), 'stm_pt': stm.get('ip')})
    x = pd.DataFrame(rows, index=f.index)
    df = cm.load()
    u = x.role.map(cm.UNIT)
    for k in range(3):
        x[f'ptn{k}'] = x[f'pt{k}'] / u
    x['stm_ptn'] = x.stm_pt / u
    x['stm_imputed'] = x.stm_war.isna().astype(int)
    xs = ['age', 'war0', 'war1', 'war2', 'ptn0', 'ptn1', 'ptn2']
    for role, g in x.groupby('role'):
        miss = g.index[g.stm_war.isna()]
        if not len(miss):
            continue
        have = df[(df.role == role) & df.stm_war.notna() & (df.stm_imputed == 0) & (df.ptn0 + df.ptn1 + df.ptn2 > 0)]
        for col in ('stm_war', 'stm_ptn'):
            x.loc[miss, col] = LinearRegression().fit(have[xs], have[col]).predict(x.loc[miss, xs])
        x.loc[miss, 'stm_pt'] = x.loc[miss, 'stm_ptn'] * cm.UNIT[role]
    x['stm_rate'] = np.where(x.stm_pt > 0.15 * u, x.stm_war / x.stm_pt * u, np.nan)
    x['is_sp'] = (x.role == 'SP').astype(int)
    x['is_rp'] = 1 - x.is_sp
    params = json.load(open(os.path.join(cm.D, 'model_params.json')))
    fd = cm.FEATS[params['feats']['deal']]
    sig = df[df.outcome.isin(['mlb', 'milb']) & (df.Y != 2020) & (df.Y < 2027)]
    m = cm.gbc(params['deal']).fit(sig[fd], (sig.outcome == 'mlb').astype(int))
    x['mlbIP3'] = x.pt0 + x.pt1 + x.pt2
    x['p_mlb'] = m.predict_proba(x[fd])[:, 1]
    x.loc[x.mlbIP3 < MIN_MLB_IP, 'p_mlb'] = np.nan
    print(f'P(MLB deal): {x.p_mlb.notna().sum()} scored, {x.p_mlb.isna().sum()} out of range '
          f'(under {MIN_MLB_IP} MLB IP 2024-2026); {int(x.stm_imputed.sum())} Steamer lines imputed')
    return x[['p_mlb', 'mlbIP3', 'stm_imputed']]
