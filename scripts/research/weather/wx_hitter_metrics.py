"""wx_hitter_metrics.py -- which HITTER metrics does the weather move, and by how much?

RESEARCH ONLY, a scoping pass (no model is fitted for release). 2021-2025 Statcast,
pooled, within (season, batter). Each metric is regressed on the two parts of air density
from pipeline/neutral_move.game_air: lnP (pressure and humidity) and lnT (temperature),
SE clustered by game. Read as
    at Coors = slope on lnP x (-0.18)       hot day = slope on lnT x (-0.037), 20 F warmer
The pitch-side rule holds here too: an air effect on the FLIGHT shows on both drivers with
one sign. An effect on one driver is the hitter, the ball or the park.

Three families:
  SWING     bat speed, swing length (2024-2025, swings only)            what the hitter does
  CONTACT   exit velocity, launch angle, xwOBA on contact, barrel rate  what leaves the bat
  FLIGHT    distance at equal EV and LA, wOBA on contact minus xwOBA on contact, home runs
            per fly ball                                                what the air does next
  PA        whiff per swing, strikeout and walk rate                    the matchup

Balls in play are rows with bb_type (the cache carries estimated_woba on strikeouts and
walks too; CLAUDE.md failure log).

Usage: .venv/bin/python scripts/research/weather/wx_hitter_metrics.py
"""
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from wx_density_slopes import fe_ols  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
from pipeline import neutral_move as NM  # noqa: E402

OUT = os.path.join(ROOT, 'data', '_weather_audit')
STORE = os.path.join(ROOT, 'data', 'game_weather_2025.json')      # the 2021-2025 weather record
YEARS = (2021, 2022, 2023, 2024, 2025)
COORS_LNP, HOT_LNT = -0.18, -0.037
MIN_GROUP = 30
SWINGS = {'swinging_strike', 'swinging_strike_blocked', 'foul', 'foul_tip', 'hit_into_play', 'missed_bunt'}
WHIFFS = {'swinging_strike', 'swinging_strike_blocked', 'missed_bunt'}
WOBA_W = {'single': 0.88, 'double': 1.25, 'triple': 1.59, 'home_run': 2.05}
COLS = ['game_pk', 'batter', 'description', 'events', 'bb_type', 'launch_speed', 'launch_angle', 'hit_distance_sc',
        'estimated_woba_using_speedangle']


def f64(s):
    return pd.to_numeric(s, errors='coerce').to_numpy(dtype='float64', na_value=np.nan)


def load(yr, store):
    df = pickle.load(open(os.path.join(ROOT, 'data', f'_statcast{yr}_cache.pkl'), 'rb'))
    df = df[[c for c in COLS if c in df.columns]].copy()
    pk = f64(df['game_pk']).astype(np.int64)
    air = {}
    for k in np.unique(pk):
        i = store.get(str(int(k))) or {}
        air[int(k)] = NM.game_air(i.get('elevationFt'), i.get('tempF'), i.get('condition'), i.get('venueId'), i.get('obs'), i.get('wind'))
    lnp = np.array([air[k]['lnP'] if air[k] else np.nan for k in pk]); lnt = np.array([air[k]['lnT'] if air[k] else np.nan for k in pk])
    desc = df['description'].astype(object).to_numpy(); ev_ = df['events'].astype(object).to_numpy()
    bip = df['bb_type'].notna().to_numpy()
    d = dict(pk=pk, bat=f64(df['batter']).astype(np.int64) + yr * 10_000_000, lnP=lnp, lnT=lnt, bip=bip,
             swing=np.isin(desc, list(SWINGS)), whiff=np.isin(desc, list(WHIFFS)),
             pa=pd.notna(ev_) & (ev_ != ''), k=np.isin(ev_, ['strikeout', 'strikeout_double_play']), bb=np.isin(ev_, ['walk']),
             hr=(ev_ == 'home_run'), fb=(df['bb_type'].astype(object).to_numpy() == 'fly_ball'),
             ev=f64(df['launch_speed']), la=f64(df['launch_angle']), dist=f64(df['hit_distance_sc']),
             xw=f64(df['estimated_woba_using_speedangle']),
             # wOBA value of a ball in play from its event (the cache has no woba_value column);
             # fixed weights, so one currency in every season
             w=np.array([WOBA_W.get(e, 0.0) for e in ev_]),
             bs=np.full(len(df), np.nan), sl=np.full(len(df), np.nan))
    del df
    return d


def cat(parts):
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


def slope(d, y, mask, group=None):
    m = mask & np.isfinite(y) & np.isfinite(d['lnP']) & np.isfinite(d['lnT'])
    key = d['bat'][m] if group is None else group[m]
    g = np.unique(key, return_inverse=True)[1]
    big = np.bincount(g)[g] >= MIN_GROUP
    idx = np.where(m)[0][big]
    g = np.unique(key[big], return_inverse=True)[1]
    b, se = fe_ols(y[idx], np.column_stack([d['lnP'][idx], d['lnT'][idx]]), g, d['pk'][idx])
    return float(np.mean(y[idx])), b, se, len(idx)


if __name__ == '__main__':
    store = json.load(open(STORE))
    d = cat([load(y, store) for y in YEARS])
    print(f'{len(d["pk"])} pitches, {int(d["bip"].sum())} balls in play, {int(np.isfinite(d["bs"]).sum())} tracked swings')
    one = lambda b: b.astype(float)
    # distance and results at EQUAL contact: group = (EV 2 mph, LA 2 deg) cell, not the batter
    cell = (np.floor(np.nan_to_num(d['ev']) / 2).astype(np.int64) * 1000 + np.floor(np.nan_to_num(d['la'], nan=-99) / 2).astype(np.int64) + 500)
    air_ball = d['bip'] & (d['la'] >= 20) & (d['la'] <= 40) & (d['ev'] >= 90)
    rows = [
        ('CONTACT', 'exit velocity', 'mph', d['ev'], d['bip'], None),
        ('CONTACT', 'launch angle', 'deg', d['la'], d['bip'], None),
        ('CONTACT', 'xwOBA on contact', '', d['xw'], d['bip'], None),
        ('CONTACT', 'hard-hit rate (EV 95+)', 'rate', (d['ev'] >= 95).astype(float), d['bip'] & np.isfinite(d['ev']), None),
        ('CONTACT', 'sweet-spot rate (LA 8 to 32)', 'rate', ((d['la'] >= 8) & (d['la'] <= 32)).astype(float), d['bip'] & np.isfinite(d['la']), None),
        ('FLIGHT', 'distance at equal EV, LA (air balls)', 'ft', d['dist'], air_ball, cell),
        ('FLIGHT', 'wOBAcon minus xwOBAcon', '', d['w'] - d['xw'], d['bip'], None),
        ('FLIGHT', 'wOBA on contact', '', d['w'], d['bip'], None),
        ('FLIGHT', 'home runs per fly ball', 'rate', one(d['hr']), d['bip'] & d['fb'], None),
        ('PA', 'whiff per swing', 'rate', one(d['whiff']), d['swing'], None),
        ('PA', 'strikeouts per PA', 'rate', one(d['k']), d['pa'], None),
        ('PA', 'walks per PA', 'rate', one(d['bb']), d['pa'], None),
    ]
    print(f"\n{'':8s}{'metric':38s}{'mean':>9s} | {'at Coors':>10s} {'t':>6s} | {'20 F hotter':>12s} {'t':>6s} | n")
    res = {}
    for fam, name, unit, y, mask, grp in rows:
        mu, b, se, n = slope(d, y, mask, grp)
        c, h = b[0] * COORS_LNP, b[1] * HOT_LNT
        res[name] = dict(family=fam, mean=mu, coors=c, coors_t=float(b[0] / se[0]), hot=h, hot_t=float(b[1] / se[1]), n=n, unit=unit)
        print(f'{fam:8s}{name:38s}{mu:9.3f} | {c:+10.4f} {b[0] / se[0]:+6.1f} | {h:+12.4f} {b[1] / se[1]:+6.1f} | {n} {unit}')
    # SWING family: bat tracking is not in the 2021-2025 files, so it is read from the 2026
    # pitch cache (MLB rows) with the 2026 weather record. One season: read it as a first look.
    P = pickle.load(open(os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl'), 'rb'))
    P = [p for p in P if p.get('_source') == 'MLB' and p.get('BatSpeed') not in (None, '')]
    s26 = json.load(open(os.path.join(ROOT, 'data', 'game_weather_rs.json')))
    air = {}
    def _air(p):
        k = (p.get('PitchID') or '').split('_')[0]
        if k not in air:
            i = s26.get(k) or {}
            air[k] = NM.game_air(i.get('elevationFt'), i.get('tempF'), i.get('condition'), i.get('venueId'), i.get('obs'), i.get('wind'))
        return air[k], k
    A = [_air(p) for p in P]
    names = {n: i for i, n in enumerate(sorted({(p.get('Batter'), p.get('BTeam')) for p in P}, key=str))}
    num = lambda key: np.array([float(p[key]) if p.get(key) not in (None, '') else np.nan for p in P])
    e = dict(pk=np.array([int(k) if k.isdigit() else -1 for _, k in A]), bat=np.array([names[(p.get('Batter'), p.get('BTeam'))] for p in P]),
             lnP=np.array([a['lnP'] if a else np.nan for a, _ in A]), lnT=np.array([a['lnT'] if a else np.nan for a, _ in A]))
    allm = np.ones(len(P), dtype=bool)
    for name, unit, key in (('bat speed (2026)', 'mph', 'BatSpeed'), ('swing length (2026)', 'ft', 'SwingLength'), ('attack angle (2026)', 'deg', 'AttackAngle')):
        mu, b, se, n = slope(e, num(key), allm, None)
        c, h = b[0] * COORS_LNP, b[1] * HOT_LNT
        res[name] = dict(family='SWING', mean=mu, coors=c, coors_t=float(b[0] / se[0]), hot=h, hot_t=float(b[1] / se[1]), n=n, unit=unit)
        print(f"{'SWING':8s}{name:38s}{mu:9.3f} | {c:+10.4f} {b[0] / se[0]:+6.1f} | {h:+12.4f} {b[1] / se[1]:+6.1f} | {n} {unit}")
    tmp = os.path.join(OUT, 'hitter_metrics.json.tmp')
    json.dump(res, open(tmp, 'w'), indent=1)
    os.replace(tmp, os.path.join(OUT, 'hitter_metrics.json'))
