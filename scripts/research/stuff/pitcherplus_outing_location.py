#!/usr/bin/env python3
"""pitcherplus_outing_location.py — outing Pitching+ on the LOCATION grade.

The outing grade (cards/pitcher.py PP_OUTING_W / PP_OUTING_K) takes the outing
mean of per-pitch Loc+ as one of four components. Location+ (2026-11-18 design)
changes that per-pitch value: count-currency pricing, kernel 2 in / 0.12, minus
the league mean for (group, batter hand, pitcher hand, count). This rebuilds the
loc column of the outing tables on that definition, with the same rows, the same
odd/even plate-appearance halves and the same season surfaces rule as
pitcherplus_outing_tables.py, so pitcherplus_outing_refit.py `fit` can run on it.

  build   data/_pplus_outing_tables_location.pkl = the shipped tables with
          locRaw / locRaw_o / locRaw_e (and locN*) replaced
  fit     runs the refit's `fit` stage twice, on the shipped tables and on the
          location tables, into separate output files, and prints both

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/stuff/pitcherplus_outing_location.py build
  PYTHONHASHSEED=0 .venv/bin/python scripts/research/stuff/pitcherplus_outing_location.py fit
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'misc'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'locplus'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT = os.path.join(ROOT, 'data', '_pplus_outing_tables_location.pkl')
KERNEL = {'PHYS_X_IN': 2.0, 'PHYS_Z_FRAC': 0.12}
OUT_SHAPE = os.path.join(ROOT, 'data', '_pplus_outing_tables_shape.pkl')   # branch locplus-shape (2026-11-19)
OUT_FAR = os.path.join(ROOT, 'data', '_pplus_outing_tables_far.pkl')       # branch locplus-farmiss (2026-11-19)
BRANCH = None          # set by build_shape: the branch Loc+ module; add_location then grades with its location_value


def add_location(df, year):
    import pipeline.locplus as lp
    import locplus_fullseason_replicate as FR
    import locplus_count_calibration as CC
    import leaderboard_metric_battery as bat
    import pitcherplus_search as ps
    import pitcherplus_outing_tables as OT
    lg, scale = ps.GUTS[year]
    ev = df['events'].fillna('')
    desc = df['description'].fillna('').map(lambda d: OT.DESC_MAP.get(d, d))
    bbtype = np.where(ev.isin(bat.SH_EV), 'bunt', df['bb_type'].fillna(''))
    count = (df['balls'].fillna(-1).astype(int).astype(str) + '-' + df['strikes'].fillna(-1).astype(int).astype(str))
    recs = pd.DataFrame({
        'Description': desc, 'Count': count, 'PlateX': df['plate_x'], 'PlateZ': df['plate_z'],
        'SzTop': df['sz_top'], 'SzBot': df['sz_bot'], 'Bats': df['stand'], 'Throws': df['p_throws'],
        'Pitch Type': df['pitch_type'], 'BBType': bbtype,
        'Event': np.where(ev == 'intent_walk', 'Intent Walk', ''), 'RunExp': df['rv'],
        'xwOBA': df['estimated_woba_using_speedangle'],
    }, index=df.index)
    recs['_source'] = 'MLB'
    if BRANCH is not None:
        # sheet convention for the class variable: IVB in inches, HorzBrk = -pfx_x
        recs['IndVertBrk'], recs['HorzBrk'] = df['pfx_z'] * 12.0, -df['pfx_x'] * 12.0
    dicts = recs.to_dict('records')
    if BRANCH is not None:
        scorable = [(i, p) for i, p in zip(recs.index, dicts) if BRANCH._is_scorable(p)]
        S = BRANCH.build_surfaces([p for _, p in scorable], lg, scale)
        loc = pd.Series(np.nan, index=df.index)
        for i, p in scorable:
            v = BRANCH.location_value(p, S)
            if v is not None:
                loc[i] = -v                  # pitcher perspective, higher = better
        df['loc_pitch'] = loc
        return df
    scorable = [(i, p) for i, p in zip(recs.index, dicts) if lp._is_scorable(p)]
    base = [p for _, p in scorable]
    off = lp.build_bip_count_offsets(base, lg, scale)
    FR.apply(KERNEL)
    try:
        S = lp.build_surfaces(base, lg, scale)
    finally:
        FR.restore()
    vals, cells = {}, {}
    acc = {}
    for i, p in scorable:
        v = CC.score(p, S, off, None)
        if v is None:
            continue
        ck = (lp.group_of(p), p['Bats'], p['Throws'], lp.get_count(p))
        vals[i], cells[i] = v, ck
        a = acc.setdefault(ck, [0.0, 0])
        a[0] += v
        a[1] += 1
    loc = pd.Series(np.nan, index=df.index)
    for i, v in vals.items():
        s, n = acc[cells[i]]
        loc[i] = -(v - s / n)            # pitcher perspective, higher = better
    df['loc_pitch'] = loc
    return df


def build(out=None):
    out_path = out or OUT
    import leaderboard_metric_battery as bat
    import pitcherplus_search as ps
    import pitcherplus_outing_tables as OT
    rows = []
    for year in OT.SEASONS:
        df = bat.load_season(year)
        df = ps.add_extra_flags(df)
        df = ps.add_xrv(df, year)
        df = add_location(df, year)
        df = OT.add_pa_index(df)
        for (pid, gpk), g in df.groupby(['pitcher', 'game_pk'], sort=False):
            r = {'pid': pid, 'season': year, 'game_pk': gpk}
            for suf, gg in (('', g), ('_o', g[g['pa_idx'] % 2 == 1]), ('_e', g[g['pa_idx'] % 2 == 0])):
                lv = gg['loc_pitch'].dropna()
                r['locRaw' + suf] = lv.mean() if len(lv) else np.nan
                r['locN' + suf] = len(lv)
            rows.append(r)
        print(f'{year}: {len(rows)} outings so far, location scored on {df["loc_pitch"].notna().mean():.3f} of pitches', flush=True)
        del df
    new = pd.DataFrame(rows)
    old = pickle.load(open(OT.OUT_PKL, 'rb'))
    keep = [c for c in old.columns if not c.startswith('locRaw') and not c.startswith('locN')]
    out = old[keep].merge(new, on=['pid', 'season', 'game_pk'], how='left')
    if len(out) != len(old):
        sys.exit('row count changed in the merge. Not written.')
    m = old[['pid', 'season', 'game_pk', 'locRaw']].merge(new[['pid', 'season', 'game_pk', 'locRaw']],
                                                           on=['pid', 'season', 'game_pk'], suffixes=('_old', '_new'))
    ok = m.dropna()
    print(f'outings {len(out)}; location present on {out["locRaw"].notna().mean():.3f}; '
          f'r(outing shipped Loc+ value, outing location part) {np.corrcoef(ok.locRaw_old, ok.locRaw_new)[0, 1]:.3f}')
    tmp = out_path + '.tmp'
    pickle.dump(out, open(tmp, 'wb'))
    os.replace(tmp, out_path)
    print(f'wrote {out_path}')


def fit():
    import pitcherplus_outing_refit as R
    base = os.path.join(R.DATA, '_pplus_outing_refit')
    for tag, tables in (('shipped', R.TABLES), ('location', OUT)):
        R.TABLES = tables
        R.OUT_JSON, R.OUT_MD = f'{base}_{tag}_1118.json', f'{base}_{tag}_1118.md'
        R.SEARCH_CSV = f'{base}_search_{tag}_1118.csv'
        print(f'\n################ {tag} tables ################', flush=True)
        sys.argv = ['pitcherplus_outing_refit.py', 'fit']
        R.main()


def build_shape(branch_path, out=None):
    global BRANCH
    sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'locplus'))
    import locplus_shape_loader as SL
    BRANCH = SL.branch(branch_path)
    build(out or OUT_SHAPE)


def lock(pairs=None):
    """Loc-k sweep on the outing composite (the stabilization crossing is a diagnostic;
    the composite's own curve decides). Frozen shipped weights, and weights refit out of
    fold by season, on the shipped tables and on the location tables."""
    import json
    import pitcherplus_outing_refit as R
    four = ['stuffAtom', 'locRaw', 'cswPct', 'xrv100']
    grid = (30, 60, 100, 150, 185, 236, 300, 450, 700, 1000, 2000, 5000)
    out = {}
    for tag, tables in (pairs or (('shipped', R.TABLES), ('location', OUT))):
        R.TABLES = tables
        t = R.load_tables()[0]
        params = R.pool_params(t, four)
        cols = list(range(4))
        rows = []
        for k in grid:
            km = dict(R.SHIPPED_K)
            km['locRaw'] = float(k)
            X, y, g, _ = R.build_split_panel(t, km, params, four)
            fr, ff = R.fixed_r(X, y, g, cols, [R.SHIPPED_W[f] for f in four])
            orr, of = R.oof_r(X, y, g, cols)
            rows.append({'k': k, 'frozen_r': fr, 'frozen_folds': ff, 'oof_r': orr, 'oof_folds': of})
        out[tag] = rows
        print(f'\n{tag} tables: outing composite r by loc k (other k at shipped)')
        print(f'{"k":>6s}{"frozen w":>10s}{"refit w":>9s}   frozen r per season')
        for r in rows:
            ff = r['frozen_folds']
            ff = ff.values() if isinstance(ff, dict) else ff
            print(f'{r["k"]:>6d}{r["frozen_r"]:>10.4f}{r["oof_r"]:>9.4f}   ' + ' '.join(f'{x:.4f}' for x in ff))
    fn = os.path.join(R.DATA, '_pplus_outing_loc_k_sweep_1118.json' if not pairs else '_pplus_outing_loc_k_sweep_shape_1119.json')
    json.dump(out, open(fn + '.tmp', 'w'), indent=1, default=float)
    os.replace(fn + '.tmp', fn)
    print(f'wrote {fn}')


if __name__ == '__main__':
    if sys.argv[1] == 'build_shape':
        build_shape(sys.argv[2])
    elif sys.argv[1] == 'lock_shape':
        lock((('location', OUT), ('shape', OUT_SHAPE)))
    elif sys.argv[1] == 'build_far':
        build_shape(sys.argv[2], OUT_FAR)
    elif sys.argv[1] == 'lock_far':
        lock((('shape', OUT_SHAPE), ('far', OUT_FAR)))
    else:
        {'build': build, 'fit': fit, 'lock': lock}[sys.argv[1]]()
