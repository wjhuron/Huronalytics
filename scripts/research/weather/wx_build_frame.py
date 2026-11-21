"""wx_build_frame.py -- one compact audit frame per season, 2021-2026.

RESEARCH ONLY. Reads the public Statcast caches (2021-2025) and the 2026
pitch pickle, joins the per-game weather sidecars, and writes
data/_weather_audit/frame_{yr}.npz with what the density-audit scripts need:

  pk, pid (pitcher key), pt (pitch-type code), rhp, ivb, hb_arm (arm side
  positive), velo, spin, venue, elev, temp (after the roof clamp), closed,
  rho (the shipped model's density), and for 2021-2025 the kinematic extras
  kdrag (drag deceleration / v^2, a direct per-pitch density probe), vaa,
  haa_arm, tflight.

The shipped density model is imported, not copied, so the audit scores
exactly what production computes.

Usage: .venv/bin/python scripts/research/weather/wx_build_frame.py [years...]
"""
import os, sys, json, pickle, zlib

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from scrapers.pitcher2026 import (compute_air_density, DEFAULT_TEMP_F,
                                  ROOF_CLOSED_TEMP_F, ROOF_CLOSED_CONDITIONS)

OUT = os.path.join(ROOT, 'data', '_weather_audit')
PT = ['FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS', 'KC', 'SV']
PT_CODE = {p: i for i, p in enumerate(PT)}
G = 32.174


def f64(s):
    return pd.to_numeric(s, errors='coerce').to_numpy(dtype='float64', na_value=np.nan)


def weather_arrays(pks, store):
    """Per-pitch venue, elevation, clamped temperature, closed flag, model rho."""
    n = len(pks)
    venue = np.full(n, -1, dtype=np.int32)
    elev = np.full(n, np.nan); temp = np.full(n, np.nan); rho = np.full(n, np.nan)
    feed_temp = np.full(n, np.nan)
    closed = np.zeros(n, dtype=bool)
    cache = {}
    for pk in np.unique(pks):
        info = store.get(str(int(pk)))
        if not info or info.get('error'):
            cache[pk] = None
            continue
        cond = (info.get('condition') or '').strip().lower()
        cl = cond in ROOF_CLOSED_CONDITIONS
        t_feed = info.get('tempF')
        t = ROOF_CLOSED_TEMP_F if cl else t_feed
        t_used = t if t is not None else DEFAULT_TEMP_F
        el = info.get('elevationFt')
        r = compute_air_density(el, t_used) if el is not None else np.nan
        cache[pk] = (info.get('venueId') or -1, el if el is not None else np.nan,
                     t_used, cl, r, t_feed if t_feed is not None else np.nan)
    for pk, v in cache.items():
        if v is None:
            continue
        m = pks == pk
        venue[m], elev[m], temp[m], closed[m], rho[m], feed_temp[m] = v
    return venue, elev, temp, closed, rho, feed_temp


def build_statcast(yr, path=None, store=None):
    df = pickle.load(open(path or os.path.join(ROOT, 'data', f'_statcast{yr}_cache.pkl'), 'rb'))
    df = df[df['game_type'] == 'R']
    pt = df['pitch_type'].map(PT_CODE)
    keep = pt.notna().to_numpy()
    df = df[keep]
    pt = pt[keep].to_numpy(dtype=np.int8)
    pks = f64(df['game_pk']).astype(np.int64)
    rhp = (df['p_throws'].astype(str) == 'R').to_numpy()
    ivb = f64(df['pfx_z']) * 12.0
    hb_sheet = -f64(df['pfx_x']) * 12.0          # sheet convention: RHP arm side positive
    hb_arm = np.where(rhp, hb_sheet, -hb_sheet)
    vx, vy, vz = f64(df['vx0']), f64(df['vy0']), f64(df['vz0'])
    ax, ay, az = f64(df['ax']), f64(df['ay']), f64(df['az'])
    # flight time from y = 50 ft to the front of the plate (17/12 ft)
    disc = vy * vy - 2.0 * ay * (50.0 - 17.0 / 12.0)
    with np.errstate(invalid='ignore', divide='ignore'):
        t = (-vy - np.sqrt(disc)) / ay
        # mid-flight velocity, aerodynamic acceleration (gravity removed)
        mx, my, mz = vx + ax * t / 2, vy + ay * t / 2, vz + az * t / 2
        vm = np.sqrt(mx * mx + my * my + mz * mz)
        drag = -(ax * mx + ay * my + (az + G) * mz) / vm
        kdrag = drag / (vm * vm)
        # vertical 'induced break' that is drag, not spin: drag opposes a falling ball
        dlift = 12.0 * 0.5 * drag * (-mz / vm) * t * t
        dside = 12.0 * 0.5 * drag * (-mx / vm) * t * t      # same for the horizontal, catcher frame
        pfz_chk = 12.0 * 0.5 * (az + G) * t * t
        vyf, vzf, vxf = vy + ay * t, vz + az * t, vx + ax * t
        vaa = np.degrees(np.arctan(vzf / -vyf))
        haa = np.degrees(np.arctan(vxf / -vyf))
    haa_arm = np.where(rhp, -haa, haa)
    if store is None:
        store = json.load(open(os.path.join(ROOT, 'data', 'game_weather_2025.json')))
    venue, elev, temp, closed, rho, feed_temp = weather_arrays(pks, store)
    return dict(pk=pks, pid=f64(df['pitcher']).astype(np.int64), pt=pt, rhp=rhp,
                ivb=ivb, hb_arm=hb_arm, velo=f64(df['release_speed']),
                spin=f64(df['release_spin_rate']), venue=venue, elev=elev, temp=temp,
                feed_temp=feed_temp, closed=closed, rho=rho, kdrag=kdrag, vaa=vaa,
                haa_arm=haa_arm, tflight=t, axis=f64(df['spin_axis']), dlift=dlift,
                pz=f64(df['plate_z']), px_arm=np.where(rhp, -f64(df['plate_x']), f64(df['plate_x'])),
                ext=f64(df['release_extension']),
                relz=f64(df['release_pos_z']), relx_arm=np.where(rhp, -f64(df['release_pos_x']), f64(df['release_pos_x'])),
                arm_angle=f64(df['arm_angle']), vplate=np.sqrt(vxf * vxf + vyf * vyf + vzf * vzf) * 0.681818,
                ev=f64(df['launch_speed']), la=f64(df['launch_angle']), dist=f64(df['hit_distance_sc']),
                xwoba=f64(df['estimated_woba_using_speedangle']), bip=df['bb_type'].notna().to_numpy(),
                whiff=df['description'].isin(['swinging_strike', 'swinging_strike_blocked', 'foul_tip']).to_numpy(),
                swing=df['description'].isin(['swinging_strike', 'swinging_strike_blocked', 'foul_tip', 'foul', 'hit_into_play']).to_numpy(),
                dside_arm=np.where(rhp, -dside, dside), pfz_chk=pfz_chk,
                date=df['game_date'].astype(str).str[:10].to_numpy(dtype='U10'))


def tilt_axis(val):
    """Sheet RTilt (clock, 'H:MM' or minutes) -> Statcast spin_axis degrees (12:00 = 180)."""
    if val is None or val == '':
        return np.nan
    if isinstance(val, (int, float)):
        m = float(val) % 720.0
    elif isinstance(val, str) and ':' in val:
        try:
            h, mm = val.strip().split(':')[:2]
            m = (int(h) % 12) * 60.0 + int(mm)
        except (ValueError, IndexError):
            return np.nan
    else:
        return np.nan
    return ((m / 60.0 + 6.0) * 30.0) % 360.0


def build_2026():
    D = pickle.load(open(os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl'), 'rb'))

    def sf(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return np.nan
    rows = []
    for p in D:
        c = PT_CODE.get(p.get('Pitch Type'))
        pid_s = p.get('PitchID') or ''
        if c is None or '_' not in pid_s:
            continue
        try:
            pk = int(pid_s.split('_')[0])
        except ValueError:
            continue
        thr = p.get('Throws')
        src = p.get('_source', 'MLB')
        rows.append((pk, zlib.crc32(f"{p.get('Pitcher')}|{thr}".encode()), c, thr == 'R',
                     sf(p.get('IndVertBrk')), sf(p.get('HorzBrk')), sf(p.get('xIndVrtBrk')),
                     sf(p.get('xHorzBrk')), sf(p.get('Velocity')), sf(p.get('Spin Rate')),
                     sf(p.get('VAA')), sf(p.get('HAA')), 0 if src == 'MLB' else 1,
                     (p.get('Game Date') or '')[:10], tilt_axis(p.get('RTilt')),
                     sf(pid_s.split('_')[1]) if pid_s.count('_') >= 2 else np.nan,
                     sf(p.get('PlateZ')), sf(p.get('PlateX')), sf(p.get('Extension'))))
    del D
    a = list(zip(*rows))
    pks = np.array(a[0], dtype=np.int64)
    rhp = np.array(a[3], dtype=bool)
    hb = np.array(a[5]); xhb = np.array(a[7])
    store = json.load(open(os.path.join(ROOT, 'data', 'game_weather_rs.json')))
    venue, elev, temp, closed, rho, feed_temp = weather_arrays(pks, store)
    in_store = np.array([str(int(k)) in store for k in pks])
    return dict(pk=pks, pid=np.array(a[1], dtype=np.int64), pt=np.array(a[2], dtype=np.int8),
                rhp=rhp, ivb=np.array(a[4]), hb_arm=np.where(rhp, hb, -hb),
                xivb=np.array(a[6]), xhb_arm=np.where(rhp, xhb, -xhb),
                velo=np.array(a[8]), spin=np.array(a[9]), vaa=np.array(a[10]),
                haa_arm=np.where(rhp, np.array(a[11]), -np.array(a[11])),
                minors=np.array(a[12], dtype=np.int8), venue=venue, elev=elev, temp=temp,
                feed_temp=feed_temp, closed=closed, rho=rho, in_store=in_store,
                date=np.array(a[13], dtype='U10'), axis=np.array(a[14], dtype=float),
                ab=np.array(a[15], dtype=float), pz=np.array(a[16], dtype=float),
                px_arm=np.where(rhp, -np.array(a[17], dtype=float), np.array(a[17], dtype=float)),
                ext=np.array(a[18], dtype=float))


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    years = [int(y) for y in sys.argv[1:]] or [2021, 2022, 2023, 2024, 2025, 2026]
    for yr in years:
        fr = build_2026() if yr == 2026 else build_statcast(yr)
        np.savez_compressed(os.path.join(OUT, f'frame_{yr}.npz'), **fr)
        n = len(fr['pk'])
        print(f"{yr}: {n} pitches, {len(np.unique(fr['pk']))} games, "
              f"rho missing {np.isnan(fr['rho']).mean():.4%}, "
              f"ivb missing {np.isnan(fr['ivb']).mean():.4%}", flush=True)
        del fr
