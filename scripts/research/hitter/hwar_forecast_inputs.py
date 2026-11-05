"""hwar_forecast_inputs.py YEAR: compact per-season tables for the honest hdWAR tests (2026-11-04).

One season per process, so an 8 GB machine holds one pitch table at a time. Reuses the shipped research
readers, nothing new is computed here:
  bat    per batter, scope full/h1/h2: n, woba, xw, xhb, pf, within-batter variance of xhb
         (hwar_hitter_rate_validation.pa_savant / pa_sheet -> finish)
  bclub  (batter, club) -> PA, pclub (pitcher, club) -> PA, 2021-2025 only (hwar_team_harness.resolve_clubs);
         2026 reads the shipped club rows downstream
  velo   (pitcher, h1, band) -> BIP count, and (band) -> [n, sum of actual minus xwOBA] for LOSO tables
         (war_velo_bias_followup.pa_savant / pa_sheet)
Usage: PYTHONHASHSEED=0 python3 scripts/research/hitter/hwar_forecast_inputs.py 2024
Output: data/_war_honest/in_YEAR.pkl, built to a temp path and moved
"""
import gc, os, pickle, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'era'))
import hwar_hitter_rate_validation as HR
import hwar_team_harness as TH
import war_velo_bias_followup as VF

OUT = os.path.join(ROOT, 'data', '_war_honest')


def batter_table(P):
    g = P.groupby('bid').agg(n=('xhb', 'size'), woba=('woba', 'mean'), xw=('xw', 'mean'), xhb=('xhb', 'mean'), pf=('pf', 'mean'), xhb_var=('xhb', 'var'))
    return g


def main(y):
    os.makedirs(OUT, exist_ok=True)
    res = {'year': y}
    if y < 2026:
        games = TH.load_games(y)
        P = TH.pa_table(y, games)
        res['club_stats'] = TH.resolve_clubs(P, games)
        res['bclub'] = P[P['bclub'] >= 0].groupby(['bid', 'bclub']).size()
        res['pclub'] = P[P['pclub'] >= 0].groupby(['pid', 'pclub']).size()
    else:
        P, _ = HR.pa_sheet(y)
    res['bat'] = {'full': batter_table(P), 'h1': batter_table(P[P['h1'].values]), 'h2': batter_table(P[~P['h1'].values])}
    print(f'{y}: {len(P)} PA, {P["bid"].nunique()} batters', flush=True)
    del P; gc.collect()

    V = VF.pa_savant(y) if y < 2026 else VF.pa_sheet(y)
    d = V[V['bip'] & V['velo'].notna()].copy()
    d['r'] = d['w'] - d['x']
    res['velo_pitcher'] = d.groupby(['pid', 'h1', 'velo']).size()
    res['velo_band'] = d.groupby('velo')['r'].agg(['size', 'sum'])
    print(f'{y}: {len(d)} BIP with a velocity band, of {int(V["bip"].sum())} BIP', flush=True)
    print(res['velo_band'].assign(mean=lambda t: t['sum'] / t['size']).round(4).to_string(), flush=True)
    del V, d; gc.collect()

    tmp = os.path.join(OUT, f'in_{y}.pkl.tmp'); final = os.path.join(OUT, f'in_{y}.pkl')
    with open(tmp, 'wb') as f:
        pickle.dump(res, f)
    os.replace(tmp, final)
    print(f'wrote {final}', flush=True)


if __name__ == '__main__':
    main(int(sys.argv[1]))
