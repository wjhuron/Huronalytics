"""wx_swing_models.py -- the weather and the swing: bat speed, swing length, swing shape.

RESEARCH ONLY. Same form and same tests as the pitcher-output metrics (wx_all_metrics.py):
    neutral m = m - aT * lnT            (and, as a check, a version with a pressure term)
fit within (season, batter, MONTH), so the calendar cannot pose as the weather.
Data: bat speed 2024 (from mid-July), 2025, 2026; swing length 2025, 2026; attack angle,
attack direction and swing path tilt 2026 only (one season: no held-out test is possible,
so those three are a first look and are NOT ready to ship).

Tests with coefficients the test season never saw:
    HEAT   what a day 20 F hotter does inside a month, raw -> neutral
    COORS  the same batter at Coors against elsewhere, raw -> neutral

Usage: .venv/bin/python scripts/research/weather/wx_swing_models.py
"""
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
from pipeline import neutral_move as NM  # noqa: E402
import wx_flight_models as F  # noqa: E402

OUT = os.path.join(ROOT, 'data', '_weather_audit')
COORS, HOT, COORS_LNP = 19, -0.037, -0.18
f64 = F.f64


def with_air(pk, store):
    air, ven = {}, {}
    for k in np.unique(pk):
        i = store.get(str(int(k))) or {}
        air[int(k)] = NM.game_air(i.get('elevationFt'), i.get('tempF'), i.get('condition'), i.get('venueId'), i.get('obs'), i.get('wind'))
        ven[int(k)] = i.get('venueId') or -1
    return (np.array([air[k]['lnP'] if air[k] else np.nan for k in pk]), np.array([air[k]['lnT'] if air[k] else np.nan for k in pk]),
            np.array([ven[k] == COORS for k in pk]))


def load(yr):
    hist = json.load(open(os.path.join(ROOT, 'data', 'game_weather_2025.json')))
    if yr == 2024:
        b = pickle.load(open(os.path.join(ROOT, 'data', '_battrack_pitch_2024.pkl'), 'rb'))
        b = b[b['bat_speed'].notna().to_numpy() & (b['game_type'].astype(object) == 'R').to_numpy()]
        sc = pickle.load(open(os.path.join(ROOT, 'data', '_statcast2024_cache.pkl'), 'rb'))[['game_date', 'batter', 'game_pk']].drop_duplicates(['game_date', 'batter'])
        b = b.merge(sc, on=['game_date', 'batter'], how='inner')          # a doubleheader takes its first game: same day, same air
        pk = f64(b['game_pk']).astype(np.int64); lnP, lnT, co = with_air(pk, hist)
        d = dict(bat=f64(b['batter']).astype(np.int64), date=b['game_date'].astype(str).to_numpy(), bs=f64(b['bat_speed']))
    elif yr == 2025:
        b = pickle.load(open(os.path.join(ROOT, 'data', '_statcast2025_full_cache.pkl'), 'rb'))
        b = b[b['bat_speed'].notna().to_numpy()]
        pk = f64(b['game_pk']).astype(np.int64); lnP, lnT, co = with_air(pk, hist)
        d = dict(bat=f64(b['batter']).astype(np.int64), date=b['game_date'].astype(str).to_numpy(), bs=f64(b['bat_speed']), sl=f64(b['swing_length']))
    else:
        P = [p for p in pickle.load(open(os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl'), 'rb'))
             if p.get('_source') == 'MLB' and p.get('BatSpeed') not in (None, '')]
        pk = np.array([int((p.get('PitchID') or '0_').split('_')[0] or 0) for p in P])
        lnP, lnT, co = with_air(pk, json.load(open(os.path.join(ROOT, 'data', 'game_weather_rs.json'))))
        names = {n: i for i, n in enumerate(sorted({(p.get('Batter'), p.get('Bats')) for p in P}, key=str))}
        num = lambda k: np.array([float(p[k]) if p.get(k) not in (None, '') else np.nan for p in P])
        d = dict(bat=np.array([names[(p.get('Batter'), p.get('Bats'))] for p in P]), date=np.array([str(p.get('Game Date'))[:10] for p in P]),
                 bs=num('BatSpeed'), sl=num('SwingLength'), aa=num('AttackAngle'), ad=num('AttackDirection'), spt=num('SwingPathTilt'))
    d.update(pk=pk, lnP=lnP, lnT=lnT, coors=co)
    ok = np.isfinite(lnT) & np.isfinite(lnP)
    d = {k: v[ok] for k, v in d.items()}
    mo = np.array([int(s[5:7]) if len(s) >= 7 and s[5:7].isdigit() else 0 for s in d['date']])
    d['gm'] = np.unique(d['bat'].astype(np.int64) * 16 + mo, return_inverse=True)[1]
    d['gb'] = np.unique(d['bat'], return_inverse=True)[1]
    return d


def sums(d, key, press):
    m = np.isfinite(d[key]); g = np.unique(d['gm'][m], return_inverse=True)[1]
    big = np.bincount(g)[g] >= 30; idx = np.where(m)[0][big]; g = np.unique(d['gm'][idx], return_inverse=True)[1]
    X = np.column_stack([d['lnT'][idx]] + ([d['lnP'][idx]] if press else []))
    return F.sums(d[key][idx], X, g), idx


def heat(d, v, idx):
    g = np.unique(d['gm'][idx], return_inverse=True)[1]
    A, b = F.sums(v[idx], np.column_stack([d['lnP'][idx], d['lnT'][idx]]), g)
    return float(F.solve(A, b)[1] * HOT)


def coors_gap(d, v, idx):
    g = np.unique(d['gb'][idx], return_inverse=True)[1]; ng = g.max() + 1
    hi = d['coors'][idx].astype(float); lo = 1 - hi; x = v[idx]
    nH, nL = np.bincount(g, weights=hi, minlength=ng), np.bincount(g, weights=lo, minlength=ng)
    ok = (nH >= 20) & (nL >= 20)
    wt = np.where(ok, 1 / (1 / np.maximum(nH, 1) + 1 / np.maximum(nL, 1)), 0)
    dd = np.bincount(g, weights=x * hi, minlength=ng) / np.maximum(nH, 1) - np.bincount(g, weights=x * lo, minlength=ng) / np.maximum(nL, 1)
    return float(np.sum(wt * dd) / wt.sum()) if wt.sum() > 0 else float('nan')


if __name__ == '__main__':
    D = {y: load(y) for y in (2024, 2025, 2026)}
    print('tracked swings: ' + ', '.join(f'{y} {len(d["pk"])}' for y, d in D.items()))
    res = {}
    for key, label, unit in (('bs', 'bat speed', 'mph'), ('sl', 'swing length', 'ft'), ('aa', 'attack angle', 'deg'),
                             ('ad', 'attack direction', 'deg'), ('spt', 'swing path tilt', 'deg')):
        yrs = [y for y in D if key in D[y] and np.isfinite(D[y][key]).sum() > 10000]
        for press in (False, True):
            S = {y: sums(D[y], key, press) for y in yrs}
            full = F.solve(sum(S[y][0][0] for y in yrs), sum(S[y][0][1] for y in yrs))
            per = np.array([F.solve(*S[y][0]) for y in yrs])
            line = f'{label:17s} {"T + P" if press else "T only":7s} seasons {yrs}  aT {full[0]:+.3f} [{per[:, 0].min():+.2f}, {per[:, 0].max():+.2f}]'
            if press:
                line += f'  aP {full[1]:+.3f} [{per[:, 1].min():+.2f}, {per[:, 1].max():+.2f}] (Coors {full[1] * COORS_LNP:+.3f} {unit})'
            he, co = [], []
            if len(yrs) >= 2:
                for y in yrs:
                    b = F.solve(sum(S[t][0][0] for t in yrs if t != y), sum(S[t][0][1] for t in yrs if t != y))
                    d, idx = D[y], S[y][1]
                    neu = d[key] - b[0] * d['lnT'] - (b[1] * d['lnP'] if press else 0.0)
                    he.append((heat(d, d[key], idx), heat(d, neu, idx))); co.append((coors_gap(d, d[key], idx), coors_gap(d, neu, idx)))
                mean = lambda v, i: float(np.nanmean([x[i] for x in v]))
                line += (f' | held-out: 20 F hotter {mean(he, 0):+.3f} -> {mean(he, 1):+.3f} {unit} (' + ' '.join(f'{x[1]:+.3f}' for x in he)
                         + f') | Coors {mean(co, 0):+.3f} -> {mean(co, 1):+.3f}')
            else:
                d, idx = D[yrs[0]], S[yrs[0]][1]
                line += f' | ONE season, in-sample only: 20 F hotter {heat(d, d[key], idx):+.3f} {unit}'
            print(line)
            res[f'{key}|{"TP" if press else "T"}'] = dict(fit=[float(x) for x in full], per_season=per.tolist(), seasons=yrs, heat=he, coors=co)
    tmp = os.path.join(OUT, 'swing_models.json.tmp')
    json.dump(res, open(tmp, 'w'), indent=1)
    os.replace(tmp, os.path.join(OUT, 'swing_models.json'))
