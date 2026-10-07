"""next_season_metric_screen.py: which single metrics predict next season's result?

Asked 2026-10-07 for offseason evaluation (FA and trade targets): which numbers to focus on when the
question is next season, not this one. One metric at a time, no fitting, so nothing here is tuned.

Pitchers: metric in season B against actual RA9 in T = B + 1 (the hpWAR target), pool >= 30 IP in B
  (the hpERA pool) and >= 1 out in T, IP_T weighted. Inputs: data/_era_battery.json (Savant season
  aggregates), _era_internal_stuff.json (LOSO Stuff+, run units), _era_internal_cmdloc.json (Loc),
  _era_xrv100.json, plus box-score ERA/RA9/FIP/xFIP/SIERA from _era_targets.json, the shipped hpERA
  formula (era_weights_final channels x W_PH) and the held-out hpWAR run model (pit_class_calibration).
Hitters: metric in B against actual wOBA in T, pool >= 200 PA in B and >= 1 PA in T, PA_T weighted.
  Inputs: xstats_batter (wOBA, xwOBA, xBA, xSLG), lines_hitting (K%, BB%, ISO, OBP), sprint speed,
  and per-pitch Statcast caches (data/_statcast{B}_cache.pkl) for batted-ball and swing metrics.
  Zone for chase / zone contact: the rulebook rectangle widened by a ball radius (0.12 ft) on every
  side, a simplification of the shipped InZone geometry. Bunts are not swings. Balls in play are
  bb_type not null. Bat speed is not in these caches (2024+ only) and is not screened.
B = 2021-2025: five independent replicates. Reported: weighted Pearson r per season, sign set so that
positive = predicts the better result; mean and the worst season.

Usage: python3 scripts/research/projection/next_season_metric_screen.py
Output: console + data/_proj/_next_season_metric_screen.json
"""
import contextlib
import csv
import io
import json
import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
P = os.path.join(ROOT, 'data', '_proj')
D = os.path.join(ROOT, 'data')
BASES = [2021, 2022, 2023, 2024, 2025]


def wr(x, y, w):
    x, y, w = (np.asarray(a, float) for a in (x, y, w))
    m = np.isfinite(x) & np.isfinite(y) & (w > 0)
    x, y, w = x[m], y[m], w[m]
    if len(x) < 30:
        return np.nan
    mx, my = np.average(x, weights=w), np.average(y, weights=w)
    c = np.average((x - mx) * (y - my), weights=w)
    return c / math.sqrt(np.average((x - mx) ** 2, weights=w) * np.average((y - my) ** 2, weights=w))


def table(title, cols, rows_by_B, target_key, weight_key, unit):
    print(f'\n== {title}: r with next-season {unit} (positive = predicts the better result)')
    print(f'   {"metric":30s} {"mean":>6s} {"worst":>6s}   ' + ' '.join(f'{B % 100}->{(B + 1) % 100}' for B in BASES) + '    n')
    res = []
    for name, key, sign in cols:
        per = [sign * wr([r.get(key, np.nan) for r in rows_by_B[B]], [r[target_key] for r in rows_by_B[B]],
                         [r[weight_key] for r in rows_by_B[B]]) for B in BASES]
        n = int(np.mean([sum(np.isfinite(r.get(key, np.nan)) for r in rows_by_B[B]) for B in BASES]))
        res.append((name, np.nanmean(per), np.nanmin(per), per, n))
    res.sort(key=lambda t: -t[1] if np.isfinite(t[1]) else 9)
    for name, m, lo, per, n in res:
        print(f'   {name:30s} {m:+.3f} {lo:+.3f}   ' + ' '.join(f'{v:+.3f}' for v in per) + f'  {n:4d}')
    return [{'metric': a, 'mean': b, 'worst': c, 'per': d, 'n': e} for a, b, c, d, e in res]


# ---------------------------------------------------------------- pitchers
def pitchers():
    import pit_class_calibration as pcc
    sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'era'))
    import era_weights_final as ewf
    BAT = json.load(open(os.path.join(D, '_era_battery.json')))
    TG = json.load(open(os.path.join(D, '_era_targets.json')))
    ST = json.load(open(os.path.join(D, '_era_internal_stuff.json')))
    CL = json.load(open(os.path.join(D, '_era_internal_cmdloc.json')))
    XR = json.load(open(os.path.join(D, '_era_xrv100.json')))
    W_PH = {'stuff': 0.315, 'loc': 0.105, 'k': 0.053, 'izwh': 0.101, 'xrv': 0.16, 'gb': 0.151, 'gs_share': 0.298, 'park': 0.152}
    with contextlib.redirect_stdout(io.StringIO()):
        recs = pcc.heldout_records(min_ip_t=0)
    proj = {(r['T'], r['pid']): r['pred'] for r in recs}
    lines = {y: {r['id']: r for r in json.load(open(os.path.join(P, f'lines_pitching_{y}.json')))} for y in range(2021, 2027)}

    def lg_ra9(y):
        L = lines[y].values()
        return 27 * sum(int(r.get('runs') or 0) for r in L) / sum(int(r.get('outs') or 0) for r in L)

    out = {}
    for B in BASES:
        T = B + 1
        tg = TG[str(B)]['pitchers']
        # league HR/FB for xFIP, and league constants for FIP
        lgB = [v for v in tg.values() if v['outs'] > 0]
        fipc = (sum(v['er'] for v in lgB) * 27 / sum(v['outs'] for v in lgB)) - \
            sum(13 * v['hr'] + 3 * (v['bb'] + v['hbp']) - 2 * v['so'] for v in lgB) * 3 / sum(v['outs'] for v in lgB)
        hrs, fbs = 0.0, 0.0
        for p, v in tg.items():
            m = BAT[str(B)].get(p, {}).get('full')
            if m and m.get('fb_pct') is not None and m.get('bip'):
                hrs += v['hr']; fbs += m['fb_pct'] * m['bip']
        lg_hrfb = hrs / fbs
        with contextlib.redirect_stdout(io.StringIO()):
            Z = ewf.shrunk_features(B, 'full')
        rows = []
        for p, v in tg.items():
            if v['outs'] < 90:
                continue
            tl = lines[T].get(int(p))
            if not tl or int(tl.get('outs') or 0) <= 0 or tl.get('pos') not in ('P', 'TWP'):
                continue
            ipT = int(tl['outs']) / 3
            r = {'ra9T': 9 * int(tl.get('runs') or 0) / ipT - lg_ra9(T), 'ipT': ipT}
            ip = v['outs'] / 3
            r['ERA'] = 9 * v['er'] / ip; r['RA9'] = 9 * v['r'] / ip
            r['FIP'] = (13 * v['hr'] + 3 * (v['bb'] + v['hbp']) - 2 * v['so']) / ip + fipc
            m = BAT[str(B)].get(p, {}).get('full') or {}
            pa = v['bf']
            r['K%'] = v['so'] / pa; r['BB%'] = v['bb'] / pa; r['K-BB%'] = r['K%'] - r['BB%']
            if m.get('fb_pct') is not None and m.get('bip'):
                r['xFIP'] = (13 * lg_hrfb * m['fb_pct'] * m['bip'] + 3 * (v['bb'] + v['hbp']) - 2 * v['so']) / ip + fipc
            if all(m.get(k) is not None for k in ('gb_pct', 'fb_pct', 'pu_pct')) and m.get('bip'):
                # the pipeline's SIERA (process_data.py): net GB = GB - (FB + PU) per PA, constant omitted
                so, bb = v['so'] / pa, v['bb'] / pa
                gbn, fbn = m['gb_pct'] * m['bip'], (m['fb_pct'] + m['pu_pct']) * m['bip']
                ng = (gbn - fbn) / pa
                sp = min(v['gs'] / v['g'], 1.0) if v.get('g') else 0.0
                r['SIERA'] = (-15.518 * so + 9.146 * so ** 2 + 8.648 * bb + 27.252 * bb ** 2 - 2.298 * ng
                              + (-1.0 if gbn >= fbn else 1.0) * 4.920 * ng ** 2 - 4.036 * so * bb
                              + 5.155 * so * ng + 4.546 * bb * ng + 0.367 * sp)
            for k, name in (('xwoba', 'xwOBA'), ('xwobacon', 'xwOBAcon'), ('woba', 'wOBA'), ('gb_pct', 'GB%'),
                            ('hr_fb', 'HR/FB'), ('hh_pct', 'Hard-hit%'), ('brl_pct', 'Barrel%'), ('csw_pct', 'CSW%'),
                            ('swstr_pct', 'SwStr%'), ('whiff_pct', 'Whiff%'), ('chase_pct', 'Chase%'),
                            ('zcon_pct', 'Z-Contact%'), ('fps_pct', 'First-pitch strike%'), ('zone_pct', 'Zone%'),
                            ('velo', 'Velo (all)'), ('ff_velo', 'FF velo'), ('ff_ivb', 'FF IVB'), ('ext', 'Extension'),
                            ('stuff_plus', 'Savant Stuff+ (battery)'), ('loc_plus', 'Savant Location+'),
                            ('pitching_plus', 'Savant Pitching+')):
                if m.get(k) is not None:
                    r[name] = m[k]
            s = ST.get(str(B), {}).get(p)
            if s and s.get('n_full'):
                r['Stuff+ (ours, LOSO)'] = s['stuff_full']
            c = CL.get(str(B), {}).get(p)
            if c and c.get('loc_full') is not None:
                r['Loc+ (ours)'] = c['loc_full']
            if c and c.get('cmd_full') is not None:
                r['Command+ (ours)'] = c['cmd_full']
            x = XR.get(str(B), {}).get(p)
            if x and x.get('full') is not None:
                r['xRV/100 (ours)'] = x['full']
            z = Z.get(p)
            if z and all(k in z for k in W_PH):
                r['hpERA (shipped formula)'] = sum(W_PH[k] * (-z[k] if k == 'xrv' else z[k]) for k in W_PH)   # research xRV sign is reversed
            if (T, int(p)) in proj:
                r['hpWAR run model (held out)'] = proj[(T, int(p))]
            rows.append(r)
        out[B] = rows
    # sign: lower is better for run metrics; set +1 where higher = better run prevention
    lo_better = {'ERA', 'RA9', 'FIP', 'xFIP', 'SIERA', 'BB%', 'xwOBA', 'xwOBAcon', 'wOBA', 'HR/FB', 'Hard-hit%',
                 'Barrel%', 'Z-Contact%', 'hpERA (shipped formula)', 'hpWAR run model (held out)'}
    names = sorted({k for B in BASES for r in out[B] for k in r if k not in ('ra9T', 'ipT')})
    # our Stuff+/xRV files: check their direction from the data rather than assume it
    cols = []
    for n in names:
        s = -1 if n in lo_better else 1
        if n in ('Stuff+ (ours, LOSO)', 'Loc+ (ours)', 'Command+ (ours)', 'xRV/100 (ours)'):
            raw = np.nanmean([wr([r.get(n, np.nan) for r in out[B]], [r['ra9T'] for r in out[B]], [r['ipT'] for r in out[B]]) for B in BASES])
            s = -1 if raw > 0 else 1
        cols.append((n, n, -s))       # target is RA9 (lower better): flip so positive = better
    return table('PITCHERS (>= 30 IP in B, IP_T weighted)', cols, out, 'ra9T', 'ipT', 'RA9 (lower)')


# ---------------------------------------------------------------- hitters
def zone(df):
    x = pd.to_numeric(df['plate_x'], errors='coerce').to_numpy('float64', na_value=np.nan)
    z = pd.to_numeric(df['plate_z'], errors='coerce').to_numpy('float64', na_value=np.nan)
    top = pd.to_numeric(df['sz_top'], errors='coerce').to_numpy('float64', na_value=np.nan)
    bot = pd.to_numeric(df['sz_bot'], errors='coerce').to_numpy('float64', na_value=np.nan)
    return (np.abs(x) <= 17 / 24 + 0.12) & (z >= bot - 0.12) & (z <= top + 0.12)


def statcast_hitter(B):
    d = pd.read_pickle(os.path.join(D, f'_statcast{B}_cache.pkl'))
    d = d[d['game_type'] == 'R']
    desc = d['description'].astype(str)
    swing = desc.isin(['swinging_strike', 'swinging_strike_blocked', 'foul', 'foul_tip', 'hit_into_play'])
    whiff = desc.isin(['swinging_strike', 'swinging_strike_blocked'])
    inz = zone(d)
    bip = d['bb_type'].notna().to_numpy()
    ev = pd.to_numeric(d['launch_speed'], errors='coerce').to_numpy('float64', na_value=np.nan)
    la = pd.to_numeric(d['launch_angle'], errors='coerce').to_numpy('float64', na_value=np.nan)
    hx = pd.to_numeric(d['hc_x'], errors='coerce').to_numpy('float64', na_value=np.nan)
    hy = pd.to_numeric(d['hc_y'], errors='coerce').to_numpy('float64', na_value=np.nan)
    spray = np.degrees(np.arctan2(hx - 125.42, 198.27 - hy))
    rhh = (d['stand'] == 'R').to_numpy()
    pulled = np.where(rhh, spray < -15, spray > 15)
    air = d['bb_type'].isin(['fly_ball', 'line_drive']).to_numpy()
    f = pd.DataFrame({'batter': d['batter'].to_numpy(), 'pitch': 1, 'swing': swing.to_numpy(), 'whiff': whiff.to_numpy(),
                      'oz': ~inz, 'oz_sw': (~inz) & swing.to_numpy(), 'iz_sw': inz & swing.to_numpy(),
                      'iz_con': inz & swing.to_numpy() & ~whiff.to_numpy(),
                      'bip': bip, 'ev_bip': np.where(bip, ev, np.nan), 'hh': bip & (ev >= 95),
                      'ss': bip & (la >= 8) & (la <= 32), 'pullair': bip & air & pulled,
                      'la_bip': np.where(bip, la, np.nan)})
    g = f.groupby('batter')
    s = g[['pitch', 'swing', 'whiff', 'oz', 'oz_sw', 'iz_sw', 'iz_con', 'bip', 'hh', 'ss', 'pullair']].sum()
    s['ev'] = g['ev_bip'].mean(); s['ev90'] = g['ev_bip'].quantile(0.9); s['evmax'] = g['ev_bip'].max()
    s['la'] = g['la_bip'].mean()
    o = {}
    for b, r in s.iterrows():
        o[int(b)] = {'Swing%': r['swing'] / r['pitch'], 'Whiff% (per swing)': r['whiff'] / r['swing'] if r['swing'] else np.nan,
                     'Chase%': r['oz_sw'] / r['oz'] if r['oz'] else np.nan,
                     'Z-Contact%': r['iz_con'] / r['iz_sw'] if r['iz_sw'] else np.nan,
                     'Hard-hit%': r['hh'] / r['bip'] if r['bip'] else np.nan, 'Avg EV': r['ev'],
                     'EV90': r['ev90'], 'Max EV': r['evmax'], 'Sweet-spot%': r['ss'] / r['bip'] if r['bip'] else np.nan,
                     'Pull-air%': r['pullair'] / r['bip'] if r['bip'] else np.nan, 'Avg LA': r['la']}
    return o


def hitters():
    import bat_rate_backtest as v1
    X = {y: v1.load_xstats(y) for y in range(2021, 2027)}
    XS = {}
    for y in range(2021, 2027):
        with open(os.path.join(P, f'xstats_batter_{y}.csv'), encoding='utf-8-sig') as f:
            XS[y] = {int(r['player_id']): r for r in csv.DictReader(f)}
    lines = {y: {r['id']: r for r in json.load(open(os.path.join(P, f'lines_hitting_{y}.json')))} for y in range(2021, 2027)}
    sprint = {}
    for y in range(2021, 2026):
        with open(os.path.join(P, f'sprint_{y}.csv'), encoding='utf-8-sig') as f:
            rd = csv.DictReader(f)
            key = 'player_id' if 'player_id' in rd.fieldnames else rd.fieldnames[1]
            sprint[y] = {int(r[key]): float(r['sprint_speed']) for r in rd if r.get('sprint_speed') not in (None, '')}
    out = {}
    for B in BASES:
        T = B + 1
        sc = statcast_hitter(B)
        rows = []
        for pid, L in lines[B].items():
            pa = int(L.get('plateAppearances') or 0)
            if L.get('pos') == 'P' or pa < 200:
                continue
            t = X[T].get(pid)
            if not t:
                continue
            r = {'wobaT': t[1], 'paT': t[0]}
            ab, bb, k = int(L.get('atBats') or 0), int(L.get('baseOnBalls') or 0), int(L.get('strikeOuts') or 0)
            r['K%'] = k / pa; r['BB%'] = bb / pa; r['BB-K%'] = (bb - k) / pa
            for fld, name in (('obp', 'OBP'), ('slg', 'SLG'), ('avg', 'AVG')):
                try:
                    r[name] = float(L[fld])
                except (TypeError, ValueError, KeyError):
                    pass
            if 'SLG' in r and 'AVG' in r:
                r['ISO'] = r['SLG'] - r['AVG']
            xs = XS[B].get(pid)
            if xs:
                for fld, name in (('woba', 'wOBA'), ('est_woba', 'xwOBA'), ('est_ba', 'xBA'), ('est_slg', 'xSLG')):
                    if xs.get(fld) not in ('', None):
                        r[name] = float(xs[fld])
                if 'wOBA' in r and 'xwOBA' in r:
                    r['.75 xwOBA + .25 wOBA'] = 0.75 * r['xwOBA'] + 0.25 * r['wOBA']
            if pid in sprint.get(B, {}):
                r['Sprint speed'] = sprint[B][pid]
            r.update(sc.get(pid, {}))
            rows.append(r)
        out[B] = rows
    hi_better = {'OBP', 'SLG', 'AVG', 'ISO', 'wOBA', 'xwOBA', 'xBA', 'xSLG', '.75 xwOBA + .25 wOBA', 'BB%', 'BB-K%',
                 'Sprint speed', 'Hard-hit%', 'Avg EV', 'EV90', 'Max EV', 'Sweet-spot%', 'Pull-air%', 'Z-Contact%', 'Avg LA'}
    names = sorted({k for B in BASES for r in out[B] for k in r if k not in ('wobaT', 'paT')})
    cols = [(n, n, 1 if n in hi_better else -1) for n in names]
    return table('HITTERS (>= 200 PA in B, PA_T weighted)', cols, out, 'wobaT', 'paT', 'wOBA')


def main():
    res = {'pitchers': pitchers(), 'hitters': hitters()}
    with open(os.path.join(P, '_next_season_metric_screen.json'), 'w') as f:
        json.dump(res, f, indent=1, default=float)


if __name__ == '__main__':
    main()
