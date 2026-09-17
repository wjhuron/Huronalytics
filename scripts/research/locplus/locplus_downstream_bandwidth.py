#!/usr/bin/env python3
"""locplus_downstream_bandwidth.py — do the constants fit ON Loc+ survive a
Loc+ bandwidth change? (2026-09-17)

Three shipped things were fitted with Loc+ as an input:
  pplus   season Pitcher+: weight .06, k 215  (pipeline/pitcherplus.py)
  era     hpERA W_PH loc channel               (pipeline/eraplus.py)
  outing  outing Pitching+ PP_OUTING_W / _K    (cards/pitcher.py)
Each has its own research harness that reads a cached Loc+ series. This
driver rebuilds ONLY that series at a given bandwidth, with today's code,
into data/_loc_target_audit/prep/<tag>/, then runs the harness on it with
its input path re-pointed. Nothing under data/_pplus_* or data/_era_* is
written: the harness functions are called, never their file-writing mains.

  build <tag> <bx> <bz> [--parts hist,era,outing]
  eval  <tag>           [--parts pplus,era,outing]

Validation is a build at the bandwidth the stored series was made under:
the rebuilt series must equal the stored one (printed by `build`).
  _pplus_locplus_hist.csv   regenerated 2026-09-05 under 6.0 / 0.30
  _era_internal_cmdloc.json rebuilt     2026-09-05 under 6.0 / 0.30
  _pplus_outing_tables.pkl  built       2026-08-28 under 4.5 / 0.22
The ERA harness takes 2026 Loc+ from the battery (site-scale sheet value);
that is left alone in every arm, so 2026 units carry the shipped Loc+.
"""
import argparse
import gc
import importlib.util
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
for p in (ROOT, os.path.join(ROOT, 'scripts'), HERE,
          os.path.join(ROOT, 'scripts', 'research', 'misc'),
          os.path.join(ROOT, 'scripts', 'research', 'stuff'),
          os.path.join(ROOT, 'scripts', 'research', 'era')):
    if p not in sys.path:
        sys.path.insert(0, p)

import pipeline.locplus as lp                           # noqa: E402

PREP = os.path.join(ROOT, 'data', '_loc_target_audit', 'prep')
LOC_COLS = ['locRaw', 'locN', 'locRaw_o', 'locN_o', 'locRaw_e', 'locN_e']


def set_bandwidth(bx, bz):
    lp.PHYS_X_IN, lp.PHYS_Z_FRAC = float(bx), float(bz)
    lp._KX = lp._k1d(lp.PHYS_X_IN / lp.BIN_X_IN)
    lp._KZ = lp._k1d(lp.PHYS_Z_FRAC / lp.BIN_Z)
    print(f'[bandwidth] pipeline.locplus -> {lp.PHYS_X_IN} in / {lp.PHYS_Z_FRAC}', flush=True)


def load_by_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── build ────────────────────────────────────────────────────────────────
def build_hist(out_dir):
    mod = load_by_path('pitcherplus_locplus_hist',
                       os.path.join(ROOT, 'scripts', 'archive', 'pitcherplus_locplus_hist.py'))
    mod.OUT_CSV = os.path.join(out_dir, 'locplus_hist.csv')
    mod.main()
    new = pd.read_csv(mod.OUT_CSV)
    old = pd.read_csv(os.path.join(ROOT, 'data', '_pplus_locplus_hist.csv'))
    j = new.merge(old, on=['pid', 'season', 'half'], suffixes=('', '_stored'))
    d = (j['locRaw'] - j['locRaw_stored']).abs()
    print(f'  hist vs stored _pplus_locplus_hist.csv: {len(j)}/{len(old)} rows joined, '
          f'max |d locRaw| {d.max():.2e}, r {np.corrcoef(j["locRaw"], j["locRaw_stored"])[0, 1]:.5f}, '
          f'locN equal on {(j["locN"] == j["locN_stored"]).mean():.4f}', flush=True)


def build_era(out_dir):
    import era_cmd_loc_scores as E
    import locplus_constants_multiseason as base
    stored = json.load(open(E.OUT))
    result = {}
    for season, path in E.SEASONS:
        pitches = base.adapt(os.path.join(ROOT, path))
        asg = E.TARGETS[str(season)]['asg']
        h1 = [p for p in pitches if p.get('Game Date') and p['Game Date'] <= asg]
        b = [p for p in pitches if lp.is_eligible_baseline(p)]
        S = lp.build_surfaces(b, base.LG, base.SCALE)
        rec = E.emit(season, E.loc_scores(pitches, S), E.loc_scores(h1, S), {}, {})
        for pid, r in rec.items():          # Command+ does not depend on the bandwidth
            for k, v in stored.get(str(season), {}).get(pid, {}).items():
                if k.startswith('cmd_'):
                    r[k] = v
        result[str(season)] = rec
        del pitches, h1, b, S
        gc.collect()
    result['2026'] = stored.get('2026', {})
    with open(os.path.join(out_dir, 'era_cmdloc.json'), 'w') as f:
        json.dump(result, f)
    dif, n = [], 0
    for sk, recs in result.items():
        for pid, r in recs.items():
            o = stored.get(sk, {}).get(pid, {})
            for k in ('loc_full', 'loc_h1'):
                if k in r and k in o:
                    dif.append(abs(r[k] - o[k])); n += 1
    print(f'  era vs stored _era_internal_cmdloc.json: {n} loc values compared, '
          f'max |d| {max(dif):.2e}', flush=True)


def build_outing(out_dir, seasons=None):
    import leaderboard_metric_battery as bat
    import pitcherplus_search as ps
    import pitcherplus_outing_tables as OT
    parts = []
    for year in (seasons or OT.SEASONS):
        # EXACTLY OT.main's order. bat.load_season returns a NON-unique index
        # and OT.add_loc assigns by index label; ps.add_xrv is what resets it.
        # Skipping add_xrv scrambles every loc value (r .016 vs the stored table).
        df = bat.load_season(year)
        df = ps.add_extra_flags(df)
        df = ps.add_xrv(df, year)
        if not df.index.is_unique:
            raise SystemExit(f'{year}: non-unique index before add_loc; loc values would be scrambled')
        df = OT.add_loc(df, year)
        df = OT.add_pa_index(df)
        df['_odd'] = df['pa_idx'] % 2 == 1
        g = df.groupby(['pitcher', 'game_pk'], sort=False)['loc_pitch']
        out = pd.DataFrame({'locRaw': g.mean(), 'locN': g.count()})
        for suf, m in (('_o', df['_odd']), ('_e', ~df['_odd'])):
            gg = df[m].groupby(['pitcher', 'game_pk'], sort=False)['loc_pitch']
            out['locRaw' + suf] = gg.mean()
            out['locN' + suf] = gg.count()
        out = out.reset_index().rename(columns={'pitcher': 'pid'})
        out['season'] = year
        parts.append(out)
        print(f'  outing loc {year}: {len(out)} outings', flush=True)
        del df
        gc.collect()
    new = pd.concat(parts, ignore_index=True)
    for c in ('locN', 'locN_o', 'locN_e'):
        new[c] = new[c].fillna(0).astype(int)
    t = pickle.load(open(OT.OUT_PKL, 'rb'))
    if seasons:
        t = t[t['season'].isin(seasons)].reset_index(drop=True)
    j = t[['pid', 'season', 'game_pk'] + LOC_COLS].merge(
        new, on=['pid', 'season', 'game_pk'], suffixes=('_stored', ''), how='left')
    both = j['locRaw'].notna() & j['locRaw_stored'].notna()
    d = (j.loc[both, 'locRaw'] - j.loc[both, 'locRaw_stored']).abs()
    print(f'  outing vs stored _pplus_outing_tables.pkl: {len(t)} outings, {int(both.sum())} with both, '
          f'max |d locRaw| {d.max():.2e}, r {np.corrcoef(j.loc[both, "locRaw"], j.loc[both, "locRaw_stored"])[0, 1]:.5f}, '
          f'locN equal on {(j["locN"] == j["locN_stored"]).mean():.4f}', flush=True)
    t2 = t.drop(columns=LOC_COLS).merge(new, on=['pid', 'season', 'game_pk'], how='left')
    t2 = t2[list(t.columns)]
    with open(os.path.join(out_dir, 'outing_tables.pkl'), 'wb') as f:
        pickle.dump(t2, f)


# ── eval ─────────────────────────────────────────────────────────────────
def eval_pplus(out_dir):
    import pitcherplus_search as ps
    ps.LOC_CSV = os.path.join(out_dir, 'locplus_hist.csv')
    import pitcherplus_v14_audit as V
    import pitcherplus_k_sweep as KS
    t = V.load_tables(ps.STUFF_CSV)
    r_s, r_y = V.frozen_eval(t)
    print(f'FROZEN shipped Pitcher+ formula: r_S {r_s:.4f}  r_Y {r_y:.4f}  combined {(r_s + r_y) / 2:.4f}')
    kmap = V.stab_constants()
    (S_X, S_y, S_grp), (Y_X, Y_y, Y_grp) = V.build_panels(t, kmap)
    cols = [V.SURVIVORS.index(c) for c in V.SHIPPED_SUBSET]
    rs, frs = V.oof_r(S_X, S_y, S_grp, cols)
    ry, fry = V.oof_r(Y_X, Y_y, Y_grp, cols)
    folds = frs + fry
    print(f'REFIT shipped six (OOF): r_S {rs:.4f}  r_Y {ry:.4f}  combined {(rs + ry) / 2:.4f}  '
          f'se {np.std(folds) / np.sqrt(len(folds)):.4f}')
    res = {'frozen': [r_s, r_y], 'refit_oof': [rs, ry], 'weights': {}}
    for label, X, y in (('S', S_X, S_y), ('Y', Y_X, Y_y)):
        A = np.column_stack([np.ones(len(y)), X[:, cols]])
        beta, *_ = np.linalg.lstsq(A, y, rcond=None)
        w = beta[1:] / np.abs(beta[1:]).sum()
        res['weights'][label] = dict(zip(V.SHIPPED_SUBSET, map(float, w)))
        print(f'refit weights (panel {label}, normalized): '
              + '  '.join(f'{f}:{v:+.3f}' for f, v in zip(V.SHIPPED_SUBSET, w)))
    r, nh, cross, n = KS.crossing(t, 'locRaw')
    print(f'locRaw reliability: half r {r:.3f}, mean half n {nh:.0f}, r=0.5 crossing {cross:.0f} (shipped k 215), n {n}')
    ship = {f: k for f, _w, k in V.SHIPPED}
    r_s0, r_y0 = KS.eval_k(t, ship)
    res['loc_k'] = {'crossing': cross, 'sweep': []}
    print(f'composite with shipped k set: r_S {r_s0:.4f}  r_Y {r_y0:.4f}; locRaw k sweep (others shipped):')
    for k in KS.GRID['locRaw']:
        km = dict(ship); km['locRaw'] = float(k)
        a, b = KS.eval_k(t, km)
        res['loc_k']['sweep'].append({'k': k, 'r_s': a, 'r_y': b})
        print(f'   k {k:5d}  r_S {a:.4f} ({a - r_s0:+.4f})  r_Y {b:.4f} ({b - r_y0:+.4f})'
              + ('  <- shipped' if k == ship['locRaw'] else ''))
    return res


def eval_era(out_dir):
    import era_weights_final as wf
    wf.CMDLOC = json.load(open(os.path.join(out_dir, 'era_cmdloc.json')))
    import era_hand_weight_refit as HR
    feats = HR.FEATS + ['lhp']
    res = {}
    for test, gate in (('ros', 60), ('next', 60), ('ros', 30), ('next', 30)):
        ev = HR.loso_with_betas(HR.reps_hand(test, gate), feats)
        per, mean, beta = ev
        w = dict(zip(feats, beta[1:]))
        res[f'{test}_{gate}'] = {'mean_r': mean, 'per': dict(per), 'weights': w}
        print(f'{test.upper()}-{gate}: held-out r {mean:.4f}  [' + ' '.join(f'{r:.3f}' for _, r in per) + ']')
        print('     weights: ' + ' '.join(f'{f} {v:+.3f}' for f, v in w.items()))
    return res


def eval_outing(out_dir):
    import pitcherplus_outing_refit as R
    R.TABLES = os.path.join(out_dir, 'outing_tables.pkl')
    R.OUT_JSON = os.path.join(out_dir, 'outing_refit.json')
    R.OUT_MD = os.path.join(out_dir, 'outing_refit.md')
    R.SEARCH_CSV = os.path.join(out_dir, 'outing_refit_search.csv')
    R.stage_fit()
    return {'json': R.OUT_JSON}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['build', 'eval'])
    ap.add_argument('tag')
    ap.add_argument('bw', nargs='*', type=float)
    ap.add_argument('--parts', default=None)
    ap.add_argument('--seasons', default=None, help='build outing: subset, for a quick validation')
    a = ap.parse_args()
    out_dir = os.path.join(PREP, a.tag)
    os.makedirs(out_dir, exist_ok=True)
    if a.cmd == 'build':
        if len(a.bw) != 2:
            raise SystemExit('build needs <bx> <bz>')
        set_bandwidth(*a.bw)
        json.dump({'bx': a.bw[0], 'bz': a.bw[1]}, open(os.path.join(out_dir, 'bandwidth.json'), 'w'))
        for part in (a.parts or 'hist,era,outing').split(','):
            print(f'\n===== build {part} @ {a.tag} =====', flush=True)
            if part == 'outing' and a.seasons:
                build_outing(out_dir, [int(x) for x in a.seasons.split(',')])
                continue
            {'hist': build_hist, 'era': build_era, 'outing': build_outing}[part](out_dir)
        return
    out = {}
    for part in (a.parts or 'pplus,era,outing').split(','):
        print(f'\n===== eval {part} @ {a.tag} =====', flush=True)
        out[part] = {'pplus': eval_pplus, 'era': eval_era, 'outing': eval_outing}[part](out_dir)
    dest = os.path.join(out_dir, f'eval_{"_".join(sorted(out))}.json')
    tmp = dest + '.tmp'
    json.dump(out, open(tmp, 'w'), indent=1, default=float)
    os.replace(tmp, dest)
    print(f'\nwrote {dest}')


if __name__ == '__main__':
    main()
