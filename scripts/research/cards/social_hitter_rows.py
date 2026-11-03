"""Which rows belong on the social hitter card?

Part 1, 2026 shipped leaderboard, single-club MLB rows with 300+ PA: for every candidate,
the held-out R2 from the six other rows of the proposed left and right columns. High means
the row repeats the card. Part 2, 2021-2025 Statcast caches, hitter-sides with 250+ BIP in Y:
year-to-year r and r with next-season wOBA on contact and full wOBA (gated on Y only, Y+1
weighted by PA). The + family and bat tracking are not in the caches, so Part 2 skips them.

    python3 scripts/research/cards/social_hitter_rows.py
"""
import gc
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from la_chart_added_value import cv_r2
from social_stabilize import ROOT, num

CURRENT = ['bbPlus', 'batSpeed', 'ev95', 'barrelPct', 'xwOBAcon', 'airPullPct', 'gbPct',
           'sdPlus', 'ctPlus', 'bbPct', 'kPct', 'chasePct', 'whiffPct']
CAND = ['hardHitPct', 'izSwingPct', 'izContactPct', 'contactPct', 'swingLength', 'attackAngle', 'attackDirection',
        'squaredUpPct', 'blastPct', 'idealAAPct', 'pullPct', 'oppoPct', 'ldPct', 'fbPct', 'puPct', 'iso', 'babip',
        'swingPct', 'firstPitchSwingPct', 'twoStrikeWhiffPct', 'sprintSpeed', 'izSwChase']
W = {'single': .89, 'double': 1.261, 'triple': 1.596, 'home_run': 2.049, 'walk': .698, 'hit_by_pitch': .729}
HX, HY = 125.42, 198.27
SWING = {'swinging_strike', 'swinging_strike_blocked', 'foul', 'foul_tip', 'hit_into_play'}
WHIFF = {'swinging_strike', 'swinging_strike_blocked'}


def part1():
    L = json.load(open(os.path.join(ROOT, 'data', 'hitter_leaderboard_rs.json')))
    M = pd.DataFrame([r for r in L if r.get('team') not in ('ROC', 'AAA') and not str(r.get('team')).endswith('TM')
                      and (r.get('pa') or 0) >= 300])
    print('Part 1: pool', len(M), ' R2 of a row from the other card rows, then its r with wRC+ and hWAR')
    w = np.ones(len(M))
    for k in CURRENT + [c for c in CAND if c in M]:
        o = [c for c in CURRENT if c != k]
        d = M[o + [k, 'wRCplus', 'hWAR']].apply(pd.to_numeric, errors='coerce').dropna()
        if len(d) < 100:
            print(f'  {k:18s} n {len(d)} too few')
            continue
        tag = '' if k in CURRENT else 'cand'
        print(f'  {k:18s} {cv_r2(d[o].to_numpy(), d[k].to_numpy(), np.ones(len(d))):.2f}   wRC+ {np.corrcoef(d[k], d.wRCplus)[0, 1]:+.2f}  hWAR {np.corrcoef(d[k], d.hWAR)[0, 1]:+.2f}  {tag}')


def season(y):
    d = pd.read_pickle(os.path.join(ROOT, 'data', f'_statcast{y}_cache.pkl'))
    de = d.description.astype('object')
    o = pd.DataFrame({'id': num(d.batter), 's': d.stand.astype('object').to_numpy(), 'bb': d.bb_type.astype('object').to_numpy()})
    o['swing'] = de.isin(SWING).to_numpy(float)
    o['whiff'] = de.isin(WHIFF).to_numpy(float)
    px, pz, top, bot = num(d.plate_x), num(d.plate_z), num(d.sz_top), num(d.sz_bot)
    dx = np.maximum(0, np.abs(px) - 8.5 / 12)
    dz = np.maximum(np.maximum(0, bot - pz), pz - top)
    iz = np.hypot(dx, dz) <= 1.45 / 12
    o['iz'] = np.where(np.isnan(dx + dz), np.nan, iz.astype(float))
    bip = ((d['type'].astype('object') == 'X') & d.bb_type.notna() & d.bb_type.astype('object').ne('bunt')).to_numpy()
    ev, la = num(d.launch_speed), num(d.launch_angle)
    o['bip'], o['ev'], o['la'] = bip.astype(float), ev, la
    o['xw'] = np.where(bip, num(d.estimated_woba_using_speedangle), np.nan)
    ang = np.degrees(np.arctan2(num(d.hc_x) - HX, HY - num(d.hc_y)))
    o['pullside'] = np.where(np.isfinite(ang) & bip, (np.where(o.s == 'R', -ang, ang) > 15).astype(float), np.nan)
    ev_ = d.events.astype('object')
    o['pa'] = ev_.notna().to_numpy(float)
    o['k'] = ev_.isin(['strikeout', 'strikeout_double_play']).to_numpy(float)
    o['w'] = ev_.map(W).fillna(0.0).to_numpy()
    del d
    gc.collect()
    return o.dropna(subset=['id'])


def feats(o):
    out = {}
    for key, g in o.groupby(['id', 's'], sort=False):
        b = g[g.bip == 1]
        if not len(b):
            continue
        sw = g[g.swing == 1]
        izp = g[g.iz == 1]
        ooz = g[g.iz == 0]
        izs = izp[izp.swing == 1]
        air = b.bb.isin(['fly_ball', 'line_drive'])
        pa = g.pa.sum()
        out[key] = {'n': len(b), 'pa': pa, 'wOBAcon': g.loc[g.bip == 1, 'w'].mean(), 'wOBA': g.w.sum() / pa if pa else np.nan,
                    'xwOBAcon': b.xw.mean(), 'EV95': np.nanpercentile(b.ev, 95) if b.ev.notna().any() else np.nan,
                    'HardHit': (b.ev >= 95).mean(),
                    'Barrel': ((b.la.between(8, 50)) & (b.ev >= 98) & (b.ev * 1.5 - b.la >= 117) & (b.ev + b.la >= 124)).mean(),
                    'AirPull': ((b.pullside == 1) & air).mean(), 'Pull': (b.pullside == 1).mean(), 'GB': (b.bb == 'ground_ball').mean(),
                    'LD': (b.bb == 'line_drive').mean(), 'PU': (b.bb == 'popup').mean(), 'K': g.k.sum() / pa if pa else np.nan,
                    'Whiff': sw.whiff.mean(), 'Chase': ooz.swing.mean(), 'ZSwing': izp.swing.mean(),
                    'ZContact': 1 - izs.whiff.mean(), 'Swing': g.swing.mean()}
    return pd.DataFrame.from_dict(out, orient='index')


def wr(a, b, w):
    ok = np.isfinite(a) & np.isfinite(b) & (w > 0)
    C = np.cov(a[ok], b[ok], aweights=w[ok])
    return C[0, 1] / np.sqrt(C[0, 0] * C[1, 1])


def part2():
    F = {y: feats(season(y)) for y in range(2021, 2026)}
    stats = [c for c in F[2021].columns if c not in ('n', 'pa')]
    res = {s: ([], [], []) for s in stats}
    for y0, y1 in zip(range(2021, 2025), range(2022, 2026)):
        a = F[y0][F[y0].n >= 250]
        j = a.join(F[y1], rsuffix='_t', how='inner')
        w = j.pa_t.to_numpy(float)
        for s in stats:
            res[s][0].append(wr(j[s].to_numpy(), j[s + '_t'].to_numpy(), w))
            res[s][1].append(wr(j[s].to_numpy(), j.wOBAcon_t.to_numpy(), w))
            res[s][2].append(wr(j[s].to_numpy(), j.wOBA_t.to_numpy(), w))
    print('Part 2: stat, year-to-year r, r with next wOBAcon, r with next wOBA')
    for s, (a, b, c) in sorted(res.items(), key=lambda kv: -abs(np.mean(kv[1][2]))):
        print(f'  {s:10s} {np.mean(a):.3f}  {np.mean(b):+.3f}  {np.mean(c):+.3f}   next wOBA by pair {[round(x, 2) for x in c]}')


if __name__ == '__main__':
    part1()
    part2()
