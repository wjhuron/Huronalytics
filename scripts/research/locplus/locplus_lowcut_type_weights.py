#!/usr/bin/env python3
"""locplus_lowcut_type_weights.py — two open Loc+ questions on the RELEASED module.

  A  LOW FAR-MISS CUTOFF. The rule shipped 2026-11-19 at 24 in / 1.0 low / 0.6 high.
     At the pitch level the low cutoff has an interior optimum at 1.0; at the pitcher
     level it read slightly negative on the group-surface harness. This runs the
     production module itself (shape classes on) with the low cutoff swept, the
     horizontal and high cutoffs held at their shipped values, and reads the released
     pitcher decider against the arm with NO low cutoff.
  B  SECONDARY PITCHES IN THE PITCHER GRADE. Loc+ prices single pitches right for
     every type, but between pitchers only the fastball grades forecast
     (locplus_within_between.py). Test: the pitcher grade with the secondary pitches'
     location values multiplied by w (w = 1 is the shipped grade, w = 0 counts the
     fastballs only and keeps every pitch in the denominator), w swept.

  build    one pass per season: per-pitch location value under every arm
           -> data/_loc_lowcut/pp_{y}.pkl
  low      question A
  weights  question B

Decider (both): pitcher grade of season Y against season Y+1 run value (mean of the
luck-neutral and the actual target), partial on out-of-sample Stuff+, within pitcher
hand and role, pool gated on Y only (300 pitches) and weighted by Y+1 pitches, five
pairs, paired pitcher bootstrap (locplus_two_number_build.pair_frame / wpartial).

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/locplus_lowcut_type_weights.py build
"""
import gc
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'stuff'))

CACHE = os.path.join(ROOT, 'data', '_loc_lowcut')
YEARS = list(range(2021, 2027))
PAIRS = YEARS[:-1]
B = 2000
INF = float('inf')
X_IN, Z_HI = 24.0, 0.6                      # shipped, held fixed
LOWS = (0.6, 0.8, 1.0, 1.25, 1.5, 2.0, INF)  # 1.0 is shipped; INF = no low cutoff
ARM = lambda lo: 'lo_none' if lo == INF else f'lo_{lo:g}'
FASTBALL_GROUPS = ('FF', 'SI', 'FC')
W_GRID = (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5)


def build():
    import pipeline.locplus as BR
    import locplus_fullseason_replicate as FR
    import locplus_shape_loader as SL
    from pipeline.utils import safe_float
    os.makedirs(CACHE, exist_ok=True)
    ship = (BR.FAR_MISS_X_IN, BR.FAR_MISS_Z_LO, BR.FAR_MISS_Z_HI)
    assert ship == (X_IN, 1.0, Z_HI), f'shipped cutoffs moved: {ship}'
    for y in YEARS:
        fn = os.path.join(CACHE, f'pp_{y}.pkl')
        if os.path.exists(fn):
            continue
        ps = [p for p in SL.load_season(y) if BR.is_eligible_baseline(p)]
        d = {'pitcher': [p.get('Pitcher') for p in ps], 'throws': [p.get('Throws') for p in ps],
             'pt': [p.get('Pitch Type') for p in ps], 'grp': [BR.group_of(p) for p in ps],
             'date': [p.get('Game Date') for p in ps],
             'px': np.array([(lambda v: np.nan if v is None else v)(safe_float(p.get('PlateX'))) for p in ps], 'f4'),
             'zn': np.array([(lambda v: np.nan if v is None else v)(BR._znorm(p)) for p in ps], 'f4')}
        for lo in LOWS:
            BR.FAR_MISS_X_IN, BR.FAR_MISS_Z_LO, BR.FAR_MISS_Z_HI = X_IN, lo, Z_HI
            S = BR.build_surfaces(ps, FR.LG, FR.SCALE)
            d[ARM(lo)] = np.array([(lambda v: np.nan if v is None else v)(BR.location_value(p, S)) for p in ps], 'f8')
            del S
            gc.collect()
        BR.FAR_MISS_X_IN, BR.FAR_MISS_Z_LO, BR.FAR_MISS_Z_HI = ship
        df = pd.DataFrame(d)
        del ps, d
        gc.collect()
        df.to_pickle(fn + '.tmp')
        os.replace(fn + '.tmp', fn)
        far = (df['zn'] < -1.0).mean()
        print(f'{y}: {len(df):,} pitches; scored {df["lo_1"].notna().mean():.3f}; more than 1.0 zone heights low {far:.4f}', flush=True)


def load(y):
    return pd.read_pickle(os.path.join(CACHE, f'pp_{y}.pkl'))


def pitcher_table(df, cols):
    """Mean per (pitcher, hand) of each column; the pitcher's larger hand row is kept."""
    g = df.groupby(['pitcher', 'throws'])
    t = g[cols].mean()
    t['n'] = g.size()
    t = t[t['n'] >= 300].reset_index().sort_values('n').drop_duplicates('pitcher', keep='last').set_index('pitcher')
    return t


def decide(tabs, arms, base):
    """Each arm minus `base` on the released decider. tabs[y] = pitcher table with the arm columns."""
    import locplus_two_number_build as T2
    rng = np.random.default_rng(0)
    per = {a: [] for a in arms}
    lvl = []
    for y in PAIRS:
        f0 = T2.pair_frame(y)
        f0 = f0[f0['role'] != 'NA']
        t = tabs[y]
        d = f0.assign(**{a: -t[a].reindex(f0.index) for a in set(arms) | {base}}).dropna(subset=list(set(arms) | {base}))
        k = len(d)
        idx = np.vstack([np.arange(k)[None, :], rng.integers(0, k, size=(B, k))])
        V = {c: d[c].values.astype(float)[idx] for c in list(set(arms) | {base}) + ['stuff', 'x', 'rv', 'w']}
        grp = pd.factorize(d['hand'] + d['role'])[0][idx]
        r = {a: sum(T2.wpartial(V[a], V[tg], V['stuff'], V['w'], grp) for tg in ('x', 'rv')) / 2 for a in set(arms) | {base}}
        lvl.append(float(r[base][0]))
        for a in arms:
            dd = r[a] - r[base]
            per[a].append((float(dd[0]), float(dd[1:].std())))
    out = {}
    for a in arms:
        m = np.mean([v[0] for v in per[a]])
        se = np.sqrt(sum(v[1] ** 2 for v in per[a])) / len(per[a])
        out[a] = (m, se, sum(v[0] > 0 for v in per[a]), [v[0] for v in per[a]])
    return float(np.mean(lvl)), out


def low():
    arms = [ARM(lo) for lo in LOWS]
    tabs, share = {}, {lo: [] for lo in LOWS}
    for y in YEARS:
        df = load(y).dropna(subset=arms)
        for lo in LOWS:
            share[lo].append(float((df['zn'] < -lo).mean()))
        tabs[y] = pitcher_table(df, arms)
    base = ARM(INF)
    lvl, res = decide(tabs, [a for a in arms if a != base], base)
    print(f'A. LOW CUTOFF, horizontal {X_IN:g} in and high {Z_HI:g} held. Base = no low cutoff, decider level {lvl:.4f}')
    print(f'{"low cutoff":>11s}{"pitches below":>15s}{"arm - no low":>14s}{"se":>8s}{"z":>7s}{"pairs>0":>9s}   per pair')
    for lo in LOWS[:-1]:
        m, se, w, pp = res[ARM(lo)]
        print(f'{lo:>11g}{np.mean(share[lo]):>15.4f}{m:>+14.4f}{se:>8.4f}{m / se:>+7.1f}{w:>7d}/5   ' + ' '.join(f'{v:+.4f}' for v in pp))
    # who throws the far-low pitch, and does the grade of those pitches alone carry signal
    print('\nPitches more than 1.0 zone heights below the zone (six seasons): share by pitch type, and of them the two-strike share is not read here')
    allp = pd.concat([load(y)[['pt', 'grp', 'zn']] for y in YEARS])
    far = allp[allp['zn'] < -1.0]
    by = (far['pt'].value_counts() / len(far)).head(8)
    rate = (allp.assign(f=allp['zn'] < -1.0).groupby('pt')['f'].mean()).reindex(by.index)
    print('   ' + '  '.join(f'{k} {v:.0%} of them (rate {rate[k]:.2%})' for k, v in by.items()))
    # split-half reliability of the pitcher grade under each arm
    print('\nsplit-half r of the pitcher grade (150+ pitches per half, mean of six seasons):')
    for lo in (1.0, INF):
        rs = []
        for y in YEARS:
            df = load(y).dropna(subset=[ARM(lo)])
            dates = sorted(df['date'].dropna().unique())
            par = {dt: i % 2 for i, dt in enumerate(dates)}
            df = df.assign(h=df['date'].map(par))
            g = df.groupby(['pitcher', 'throws', 'h'])[ARM(lo)].agg(['mean', 'size']).unstack('h')
            ok = (g[('size', 0)] >= 150) & (g[('size', 1)] >= 150)
            rs.append(np.corrcoef(g[('mean', 0)][ok], g[('mean', 1)][ok])[0, 1])
        print(f'   low {lo:g}: {np.mean(rs):.3f}')


def weights():
    col = ARM(1.0)
    tabs = {}
    for y in YEARS:
        df = load(y).dropna(subset=[col])
        sec = ~df['grp'].isin(FASTBALL_GROUPS)
        cols = []
        for w in W_GRID:
            df[f'w_{w:g}'] = np.where(sec, w, 1.0) * df[col]
            cols.append(f'w_{w:g}')
        # per-group contributions: only that group's values, every pitch in the denominator
        for gname in ('FF', 'SI', 'FC', 'SL', 'CU', 'CH'):
            df[f'only_{gname}'] = np.where(df['grp'] == gname, df[col], 0.0)
            cols.append(f'only_{gname}')
        tabs[y] = pitcher_table(df, cols)
        tabs[y]['sec_share'] = df.assign(s=sec).groupby(['pitcher', 'throws'])['s'].mean().reset_index().drop_duplicates('pitcher', keep='last').set_index('pitcher')['s'].reindex(tabs[y].index)
    arms = [f'w_{w:g}' for w in W_GRID if w != 1.0]
    lvl, res = decide(tabs, arms, 'w_1')
    print(f'B. SECONDARY-PITCH WEIGHT in the pitcher grade (fastballs = {", ".join(FASTBALL_GROUPS)}). Base w = 1 (shipped), decider level {lvl:.4f}')
    print(f'{"w":>6s}{"arm - shipped":>15s}{"se":>8s}{"z":>7s}{"pairs>0":>9s}   per pair')
    for w in W_GRID:
        if w == 1.0:
            print(f'{w:>6g}{"0 (base)":>15s}')
            continue
        m, se, k, pp = res[f'w_{w:g}']
        print(f'{w:>6g}{m:>+15.4f}{se:>8.4f}{m / se:>+7.1f}{k:>7d}/5   ' + ' '.join(f'{v:+.4f}' for v in pp))
    # level of each group's own contribution, as its own grade
    import locplus_two_number_build as T2
    rng = np.random.default_rng(1)
    print('\nDecider level of ONE group\'s contribution alone (its values, zero for every other pitch):')
    for gname in ('FF', 'SI', 'FC', 'SL', 'CU', 'CH'):
        rs = []
        for y in PAIRS:
            f0 = T2.pair_frame(y)
            f0 = f0[f0['role'] != 'NA']
            d = f0.assign(a=-tabs[y][f'only_{gname}'].reindex(f0.index)).dropna(subset=['a'])
            k = len(d)
            idx = np.vstack([np.arange(k)[None, :], rng.integers(0, k, size=(500, k))])
            V = {c: d[c].values.astype(float)[idx] for c in ('a', 'stuff', 'x', 'rv', 'w')}
            grp = pd.factorize(d['hand'] + d['role'])[0][idx]
            r = sum(T2.wpartial(V['a'], V[tg], V['stuff'], V['w'], grp) for tg in ('x', 'rv')) / 2
            rs.append((float(r[0]), float(r[1:].std())))
        m = np.mean([v[0] for v in rs])
        se = np.sqrt(sum(v[1] ** 2 for v in rs)) / len(rs)
        print(f'   {gname}: {m:+.4f} (se {se:.4f}), pairs > 0: {sum(v[0] > 0 for v in rs)}/5')


if __name__ == '__main__':
    {'build': build, 'low': low, 'weights': weights}[sys.argv[1]]()
