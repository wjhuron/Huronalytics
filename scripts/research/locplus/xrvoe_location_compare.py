#!/usr/bin/env python3
"""xrvoe_location_compare.py — what the Loc+ release does to xRVOE.

xRVOE (stuff_plus/train_stuff.py compute_xrvoe) is the per-pitch residual of
target xRV on a stacked expectation of the Stuff+ prediction and the Loc+
EXPECTED value (locplus.score_pitch). The 2026-11-18 Loc+ branch changes that
expected value two ways: the kernel (2 in / 0.12) and the ball-in-play branch
in count currency. This script scores the same 2026 pitches and the same
Stuff+ predictions against both versions of pipeline/locplus.py.

  ship    pipeline/locplus.py of this checkout (main)
  branch  pipeline/locplus.py of the Loc+ release worktree (argv[1])

The Stuff+ side comes from the real score-only path of train_stuff.main(): the
driver runs it against a COPY of the bundle in a scratch folder, stops at the
compute_xrvoe call and takes its arguments. No shipped file moves.

Reads, per version:
  validation     ship units against xrvoe100 in data/pitcher_leaderboard_rs.json
  fit            R2 of the expectation on target xRV, in sample and CROSS-FIT
                 (surfaces built on the other half of the games). The in-sample
                 number is gameable by a narrow kernel, so the cross-fit decides.
  calibration    mean residual by count and by pitcher hand (runs per 100)
  reliability    split-half r of unit residuals (odd/even games): a diagnostic
  units          how far the shipped values move

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/locplus/xrvoe_location_compare.py \
      /Users/wallyhuron/Huronalytics-locplus
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'stuff_plus'))
OUT = os.path.join(ROOT, 'data', '_xrvoe_location_compare.json')


class _Captured(Exception):
    pass


def capture():
    """Run the real score-only path up to compute_xrvoe and return its inputs."""
    import train_stuff as T
    scratch = tempfile.mkdtemp(prefix='xrvoe_cmp_')
    for f in ('stuff_models.pkl', 'pitcher_stuff.csv'):
        shutil.copyfile(os.path.join(T.HERE, f), os.path.join(scratch, f))
    hist = os.path.join(T.DATA, 'stuff_metrics_history.csv')
    hist_bak = os.path.join(scratch, 'stuff_metrics_history.csv')
    shutil.copyfile(hist, hist_bak)
    T.HERE = scratch
    T.write_bundle_info = lambda b: None
    box = {}

    def grab(df, pitches, roc_df=None, roc_pitches=None, by_hand=False):
        box.update(df=df, pitches=pitches, lg=T.LG_WOBA, scale=T.WOBA_SCALE)
        raise _Captured()
    T.compute_xrvoe = grab
    argv = sys.argv
    sys.argv = ['train_stuff.py', '--score-only', '--inject']
    try:
        T.main()
    except _Captured:
        pass
    finally:
        sys.argv = argv
        shutil.copyfile(hist_bak, hist)
        shutil.rmtree(scratch, ignore_errors=True)
    if 'df' not in box:
        sys.exit('train_stuff.main() did not reach compute_xrvoe. Nothing measured.')
    return T, box


def load_branch(path, name='pipeline.locplus_branch'):
    fn = os.path.join(path, 'pipeline', 'locplus.py')
    spec = importlib.util.spec_from_file_location(name, fn)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def _sp(LOC, p, S):
    """The expected value as compute_xrvoe reads it: without the count anchor since 2026-11-18
    (a module that predates the option keeps its plain call)."""
    try:
        return LOC.score_pitch(p, S, count_anchor=False)
    except TypeError:
        return LOC.score_pitch(p, S)


def exprv_for(LOC, base, lg, scale, fold=None):
    """PitchID -> expected value. fold: PitchID -> 0/1, then each pitch is scored on
    surfaces built from the OTHER fold (cross-fit)."""
    out = {}
    if fold is None:
        S = LOC.build_surfaces(base, lg, scale)
        for p in base:
            v = _sp(LOC, p, S)
            if v is not None and p.get('PitchID'):
                out[p['PitchID']] = v
        return out
    for k in (0, 1):
        S = LOC.build_surfaces([p for p in base if fold.get(p.get('PitchID')) == 1 - k], lg, scale)
        for p in base:
            if fold.get(p.get('PitchID')) != k:
                continue
            v = _sp(LOC, p, S)
            if v is not None:
                out[p['PitchID']] = v
        del S
    return out


def residuals(T, df, exprv, group_of_code):
    """compute_xrvoe's _prep / _stack / _apply, kept line for line."""
    d = df[['pid', 'pitcher', 'team', 'pitch_type', 'target_xrv', 'stuff_raw', 'rv_raw']].copy()
    d['loc_exprv'] = d['pid'].map(exprv)
    d = d[d['loc_exprv'].notna() & d['stuff_raw'].notna() & d['target_xrv'].notna()]
    d['stuff_hit'] = -d['stuff_raw']
    d['grp'] = d['pitch_type'].map(group_of_code)

    def stack(sub):
        A = np.column_stack([np.ones(len(sub)), sub['stuff_hit'].values, sub['loc_exprv'].values])
        beta, *_ = np.linalg.lstsq(A, sub['target_xrv'].values, rcond=None)
        return beta
    beta_g = stack(d)
    betas = {g: (stack(s) if len(s) >= 5000 else beta_g) for g, s in d.groupby('grp')}
    d['expect'] = np.nan
    for g, s in d.groupby('grp'):
        A = np.column_stack([np.ones(len(s)), s['stuff_hit'].values, s['loc_exprv'].values])
        d.loc[s.index, 'expect'] = A @ betas.get(g, beta_g)
    d['resid'] = d['target_xrv'] - d['expect']
    return d, betas


def units(T, d, keys, min_n):
    g = d.groupby(keys).agg(resid=('resid', 'mean'), n=('resid', 'size'))
    g = g[g['n'] >= min_n]
    g['v'] = -(g['n'] / (g['n'] + T.XRVOE_N0)) * g['resid'] * 100.0
    return g


def r2(y, f):
    return 1.0 - float(((y - f) ** 2).sum()) / float(((y - y.mean()) ** 2).sum())


def main():
    branch_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(ROOT), 'Huronalytics-locplus')
    T, box = capture()
    df, pitches, lg, scale = box['df'], box['pitches'], box['lg'], box['scale']
    import pipeline.locplus as SHIP
    BR = load_branch(branch_path)
    # third arm: the branch kernel with the ball in play left count-neutral, the
    # currency of the xRVOE target (train_stuff does not count-anchor a BIP target)
    print(f'\nship   kernel {SHIP.PHYS_X_IN:g} in / {SHIP.PHYS_Z_FRAC:g}, BIP count anchor {getattr(SHIP, "BIP_COUNT_ANCHOR", None)}')
    print(f'branch kernel {BR.PHYS_X_IN:g} in / {BR.PHYS_Z_FRAC:g}, BIP count anchor {getattr(BR, "BIP_COUNT_ANCHOR", None)}')
    base = [p for p in pitches if SHIP.is_eligible_baseline(p)]
    meta = {p['PitchID']: (SHIP.get_count(p), p.get('Throws'), p.get('Bats')) for p in base if p.get('PitchID')}
    fold = {pid: (int(str(pid).split('_')[0]) % 2 if str(pid).split('_')[0].isdigit() else 0) for pid in meta}
    res, out = {}, {}
    for name, LOC in (('ship', SHIP), ('branch', BR)):
        d, betas = residuals(T, df, exprv_for(LOC, base, lg, scale), SHIP.group_of_code)
        dx, _ = residuals(T, df, exprv_for(LOC, base, lg, scale, fold), SHIP.group_of_code)
        d['count'] = d['pid'].map(lambda k: '%d-%d' % meta[k][0])
        d['throws'] = d['pid'].map(lambda k: meta[k][1])
        d['fold'] = d['pid'].map(fold)
        res[name] = d
        loc_only = np.polyfit(d['loc_exprv'], d['target_xrv'], 1)
        locx_only = np.polyfit(dx['loc_exprv'], dx['target_xrv'], 1)
        o = {'n': len(d),
             'betas': {g: [float(x) for x in b] for g, b in betas.items()},
             'r2_in': r2(d['target_xrv'], d['expect']),
             'r2_cross': r2(dx['target_xrv'], dx['expect']),
             'r2_loc_in': r2(d['target_xrv'], np.polyval(loc_only, d['loc_exprv'])),
             'r2_loc_cross': r2(dx['target_xrv'], np.polyval(locx_only, dx['loc_exprv'])),
             'by_count': (d.groupby('count')['resid'].mean() * 100).round(3).to_dict(),
             'by_throws': (d.groupby('throws')['resid'].mean() * 100).round(3).to_dict()}
        gq = units(T, d, ['pitcher', 'team', 'pitch_type'], 100)
        st = d.groupby(['pitcher', 'team', 'pitch_type']).agg(stuff=('stuff_hit', 'mean'), loc=('loc_exprv', 'mean'))
        j = gq.join(st)
        o['cal_stuff'] = float(np.corrcoef(j['resid'], j['stuff'])[0, 1])
        o['cal_loc'] = float(np.corrcoef(j['resid'], j['loc'])[0, 1])
        for tag, keys, mn in (('pt', ['pitcher', 'team', 'pitch_type'], T.XRVOE_MIN_PT), ('ov', ['pitcher', 'team'], T.XRVOE_MIN_OV)):
            h = d.groupby(keys + ['fold'])['resid'].agg(['mean', 'size']).unstack('fold')
            h = h[(h[('size', 0)] >= mn / 2) & (h[('size', 1)] >= mn / 2)]
            o[f'half_r_{tag}'] = float(np.corrcoef(h[('mean', 0)], h[('mean', 1)])[0, 1])
            o[f'half_n_{tag}'] = len(h)
            o[f'sd_v_{tag}'] = float(units(T, d, keys, mn)['v'].std())
        out[name] = o
        print(f'\n== {name}: {o["n"]} pitches')
        for g, b in betas.items():
            print(f'   {g:>9s}  intercept {b[0]:+.5f}  stuff {b[1]:.3f}  loc {b[2]:.3f}')
        print(f'   R2 expectation on target xRV: in sample {o["r2_in"]:.5f}, cross-fit {o["r2_cross"]:.5f}')
        print(f'   R2 location term alone:       in sample {o["r2_loc_in"]:.5f}, cross-fit {o["r2_loc_cross"]:.5f}')
        print(f'   calibration (units 100+): corr(resid, stuff) {o["cal_stuff"]:+.3f}, corr(resid, loc) {o["cal_loc"]:+.3f}')
        print('   mean residual by count, runs/100: ' + '  '.join(f'{k} {v:+.2f}' for k, v in sorted(o['by_count'].items())))
        print('   mean residual by pitcher hand, runs/100: ' + '  '.join(f'{k} {v:+.3f}' for k, v in o['by_throws'].items()))
        print(f'   split-half r (odd/even games): pitch type {o["half_r_pt"]:.3f} ({o["half_n_pt"]} units), '
              f'pitcher {o["half_r_ov"]:.3f} ({o["half_n_ov"]} units)')
        print(f'   SD of shipped-scale xRVOE/100: pitch type {o["sd_v_pt"]:.3f}, pitcher {o["sd_v_ov"]:.3f}')

    # validation of the replica against the shipped column
    lb = json.load(open(os.path.join(ROOT, 'data', 'pitcher_leaderboard_rs.json')))
    ov = units(T, res['ship'], ['pitcher', 'team'], T.XRVOE_MIN_OV)
    pairs = [(ov.loc[(r['pitcher'], r['team']), 'v'], r['xrvoe100']) for r in lb
             if r.get('xrvoe100') is not None and (r['pitcher'], r['team']) in ov.index]
    a = np.array(pairs)
    print(f'\nVALIDATION: ship replica against leaderboard xrvoe100, {len(a)} rows: r {np.corrcoef(a[:, 0], a[:, 1])[0, 1]:.4f}, '
          f'median |diff| {np.median(np.abs(a[:, 0] - a[:, 1])):.3f}, max {np.abs(a[:, 0] - a[:, 1]).max():.3f}')
    out['validation'] = {'n': len(a), 'r': float(np.corrcoef(a[:, 0], a[:, 1])[0, 1]),
                         'max_abs': float(np.abs(a[:, 0] - a[:, 1]).max())}

    for tag, keys, mn in (('pitch type', ['pitcher', 'team', 'pitch_type'], T.XRVOE_MIN_PT), ('pitcher', ['pitcher', 'team'], T.XRVOE_MIN_OV)):
        for other in ('branch',):
            a, b = units(T, res['ship'], keys, mn), units(T, res[other], keys, mn)
            m = a.join(b, lsuffix='_s', rsuffix='_b', how='inner')
            dv = m['v_b'] - m['v_s']
            print(f'\n{tag} units, ship against {other} ({len(m)}): r {np.corrcoef(m.v_s, m.v_b)[0, 1]:.4f}, '
                  f'mean |move| {dv.abs().mean():.3f}, 90th pct {dv.abs().quantile(.9):.3f}, max {dv.abs().max():.3f} '
                  f'runs/100 (SD of the stat {m.v_s.std():.3f})')
            out[f'move_{tag}_{other}'] = {'n': len(m), 'r': float(np.corrcoef(m.v_s, m.v_b)[0, 1]),
                                          'mean_abs': float(dv.abs().mean()), 'p90': float(dv.abs().quantile(.9)),
                                          'max': float(dv.abs().max())}
            m = m.assign(move=dv).sort_values('move')
            show = m[['n_s', 'v_s', 'v_b', 'move']].round(2)
            print('  largest falls:'); print(show.head(6).to_string())
            print('  largest rises:'); print(show.tail(6).to_string())
    tmp = OUT + '.tmp'
    json.dump(out, open(tmp, 'w'), indent=1)
    os.replace(tmp, OUT)
    print(f'\nwrote {OUT}')


if __name__ == '__main__':
    main()
