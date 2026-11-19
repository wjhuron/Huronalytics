"""dd_build.py - compact per-pitch frames for the 2026-11 hitter deep dive.

One DataFrame per season (2021-2026) in data/_hdd/pitch_{Y}.pkl with the
PRODUCTION per-pitch SD+ and CT+ values (pipeline.sdplus / pipeline.contact,
season-own cell tables) plus the raw fields the deep-dive tests rebuild from.
Run from the repo root:  .venv/bin/python scripts/research/hitter/deep_dive/dd_build.py [years]
"""
import gc, json, os, pickle, sys
from collections import defaultdict
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))
import statcast_hitter_adapter as A
import pipeline.sdplus as sd
import pipeline.contact as ct
from pipeline.utils import safe_float, compute_in_zone, BUNT_BB_TYPES

OUT = os.path.join(ROOT, 'data', '_hdd')
GUTS_2026 = (0.3172, 1.2343)
BIPV = {'single': .9, 'double': 1.25, 'triple': 1.6, 'home_run': 2.0, 'field_error': .9, 'fielders_choice': .9}


def load_pub(year):
    df = pickle.load(open(os.path.join(ROOT, 'data', f'_statcast{year}_cache.pkl'), 'rb'))
    if 'game_type' in df.columns:
        df = df[df['game_type'] == 'R']
    df = df.reset_index(drop=True)
    sf = A.sf
    has = 'delta_pitcher_run_exp' in df.columns
    out = []
    for i, r in enumerate(df.itertuples(index=False)):
        desc = A.DESC_MAP.get(r.description)
        if desc is None:
            continue
        ev = r.events if isinstance(r.events, str) and r.events else None
        bb = r.bb_type if isinstance(r.bb_type, str) and r.bb_type else None
        if ev in ('sac_bunt', 'sac_bunt_double_play', 'bunt_groundout', 'bunt_pop_out', 'bunt_lineout'):
            bb = 'bunt'
        rx = sf(r.delta_pitcher_run_exp) if has else None
        if rx is None:
            d = sf(r.delta_run_exp); rx = -d if d is not None else None
        b, s = sf(r.balls), sf(r.strikes)
        p = {'_i': i, '_source': 'MLB', 'Game Date': str(r.game_date)[:10],
             'Batter': str(int(r.batter)) if sf(r.batter) is not None else None, 'BTeam': 'X',
             'Bats': r.stand if r.stand in ('L', 'R') else None, 'Throws': r.p_throws if r.p_throws in ('L', 'R') else None,
             'Pitch Type': r.pitch_type if isinstance(r.pitch_type, str) else None, 'Description': desc,
             'Event': 'Intent Walk' if ev == 'intent_walk' else (ev or None), 'event_raw': ev, 'BBType': bb,
             'Count': (f"{int(b)}-{int(s)}" if b is not None and s is not None else None),
             'PlateX': sf(r.plate_x), 'PlateZ': sf(r.plate_z), 'SzTop': sf(r.sz_top), 'SzBot': sf(r.sz_bot),
             'RunExp': rx, 'xwOBA': sf(r.estimated_woba_using_speedangle), 'HC_X': sf(r.hc_x), 'HC_Y': sf(r.hc_y),
             'LaunchAngle': sf(r.launch_angle), 'ExitVelo': sf(r.launch_speed),
             '_pid': str(int(r.pitcher)) if sf(r.pitcher) is not None else None, '_gpk': sf(r.game_pk),
             '_velo': sf(r.release_speed), '_hb': (sf(r.pfx_x) * 12 * (-1 if r.p_throws == 'R' else 1)) if sf(r.pfx_x) is not None else None,
             '_ivb': sf(r.pfx_z) * 12 if sf(r.pfx_z) is not None else None, '_outs': sf(r.outs_when_up)}
        p['InZone'] = compute_in_zone(p)
        out.append(p)
    del df; gc.collect()
    return out


def load_2026():
    D = pickle.load(open(os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl'), 'rb'))
    D = [p for p in D if p.get('_source', 'MLB') == 'MLB']
    lb = json.load(open(os.path.join(ROOT, 'data', 'hitter_leaderboard_rs.json')))
    n2i = {r['hitter']: str(int(r['mlbId'])) for r in lb if r.get('mlbId') is not None and r.get('hitter')}
    for i, p in enumerate(D):
        p['_i'] = i
        p['_name'] = p.get('Batter')
        p['Batter'] = n2i.get(p.get('Batter'))
        e = (p.get('Event') or '').strip()
        p['event_raw'] = e.lower().replace(' ', '_') or None
        p['_pid'] = p.get('Pitcher')
        pid = str(p.get('PitchID') or '')
        p['_gpk'] = safe_float(pid.split('_')[0]) if pid else None
        p['_velo'] = safe_float(p.get('Velocity'))
        hb = safe_float(p.get('HorzBrk'))
        p['_hb'] = (hb * (1 if p.get('Throws') == 'R' else -1)) if hb is not None else None   # arm side positive
        p['_ivb'] = safe_float(p.get('IndVertBrk'))
        p['_outs'] = safe_float(p.get('Outs'))
        for k in ('PlateX', 'PlateZ', 'SzTop', 'SzBot', 'HC_X', 'HC_Y', 'LaunchAngle', 'ExitVelo'):
            pass
    return [p for p in D if p['Batter']]


def build(Y):
    P = load_2026() if Y == 2026 else load_pub(Y)
    lg, sc = GUTS_2026 if Y == 2026 else A.GUTS[Y]
    P = [p for p in P if p.get('Batter')]
    by_h = defaultdict(list)
    for p in P:
        by_h[(p['Batter'], '')].append(p)
    # production tables
    elig = [p for p in P if sd.is_eligible(p)]
    rv_fn = sd.make_rv_xrv(lg, sc)
    sdtab = sd.shrink_table(sd.build_weight_table(elig, rv_fn), sd.zone_level_means(elig, rv_fn))
    swings = [p for p in P if ct.is_ct_eligible(p)]
    offs = ct.build_bip_count_offsets(swings, lg, sc)
    rv_a = ct.make_rv_xrv(lg, sc, offs)
    cttab = ct.shrink_contact_cells(ct.build_contact_cell_weights(swings, rv_a), ct.zone_level_contact_means(swings, rv_a))
    sdn, _ = sd.compute_sd_plus(P, by_h, lg, sc)
    ctn, _ = ct.compute_ct_plus(P, by_h, lg, sc)
    rows = []
    for p in P:
        z = sd.classify_zone(p); c = sd.get_count(p); dec = sd.classify_decision(p)
        el = sd.is_eligible(p)
        sw = tk = lev = pwh = con = None
        if el:
            sw = sdtab[(z, c, sd._sd_cat(p), 'swing')][0]; tk = sdtab[(z, c, sd._sd_cat(p), 'take')][0]
        cel = el and dec == 'swing' and ct.classify_contact_outcome(p) is not None
        cat = sd.cat_of(p)
        if cel:
            cell = cttab[(z, c, cat)]
            lev = cell['rv_contact'] - cell['rv_whiff']; pwh = cell['p_whiff']
            con = 1 if ct.classify_contact_outcome(p) == 'contact' else 0
        desc = p.get('Description'); er = p.get('event_raw') or ''
        bunt = (p.get('BBType') in BUNT_BB_TYPES) or ('bunt' in er)
        bip = desc == 'In Play' and not bunt
        wv = wd = None
        if er and er not in ('intent_walk',):
            if desc == 'In Play':
                if not ('sac_bunt' in er):
                    wv, wd = BIPV.get(er, 0.0), 1
            elif er == 'walk':
                wv, wd = .69, 1
            elif er == 'hit_by_pitch':
                wv, wd = .72, 1
            elif 'strikeout' in er:
                wv, wd = 0.0, 1
        iz = p.get('InZone')
        rows.append((p['Batter'], p.get('_pid'), p.get('Game Date'), p.get('_gpk'), p.get('Bats'), p.get('Throws'),
                     p.get('Pitch Type'), cat, z, c[0] if c else None, c[1] if c else None, dec, el, sw, tk,
                     rv_fn(p), rv_a(p), cel, lev, pwh, con, bip, safe_float(p.get('xwOBA')), safe_float(p.get('ExitVelo')),
                     safe_float(p.get('LaunchAngle')), safe_float(p.get('HC_X')), safe_float(p.get('HC_Y')),
                     p.get('_velo'), p.get('_hb'), p.get('_ivb'), safe_float(p.get('PlateX')), safe_float(p.get('PlateZ')),
                     safe_float(p.get('SzTop')), safe_float(p.get('SzBot')), iz in (True, 'Yes', 1), er or None, wv, wd,
                     desc, p.get('_outs'),
                     safe_float(p.get('BatSpeed')), safe_float(p.get('SwingLength')), safe_float(p.get('AttackAngle')),
                     safe_float(p.get('AttackDirection')), safe_float(p.get('SwingPathTilt'))))
    cols = ['bid', 'pid', 'date', 'gpk', 'bats', 'throws', 'pt', 'cat', 'zone', 'b', 's', 'dec', 'sd_el', 'sw_rv', 'tk_rv',
            'rv', 'rv_a', 'ct_el', 'lev', 'pwh', 'con', 'bip', 'xw', 'ev', 'la', 'hcx', 'hcy', 'velo', 'hb', 'ivb', 'px', 'pz',
            'sztop', 'szbot', 'iz', 'event', 'wv', 'wd', 'desc', 'outs', 'bs', 'sl', 'aa', 'ad', 'tilt']
    df = pd.DataFrame(rows, columns=cols)
    for c_ in ('bats', 'throws', 'pt', 'cat', 'zone', 'dec', 'event', 'desc'):
        df[c_] = df[c_].astype('category')
    for c_ in df.columns:
        if df[c_].dtype == 'float64':
            df[c_] = df[c_].astype('float32') if c_ not in ('gpk',) else df[c_]
    # production per-hitter outputs, for parity
    prod = {b: dict(sd_raw=(sdn.get((b, '')) or {}).get('raw_sd'), sdPlus=(sdn.get((b, '')) or {}).get('sdPlus'),
                    ct_raw=(ctn.get((b, '')) or {}).get('raw_ct'), ctPlus=(ctn.get((b, '')) or {}).get('ctPlus'),
                    n_dec=(sdn.get((b, '')) or {}).get('n_decisions'), n_sw=(ctn.get((b, '')) or {}).get('n_swings'))
            for (b, _t) in by_h}
    lgz = df[df.sd_el].zone.value_counts(normalize=True).to_dict()
    # parity: mix-neutral raw_sd from the frame
    e = df[df.sd_el].copy(); e['dv'] = np.where(e.dec == 'swing', e.sw_rv - e.tk_rv, e.tk_rv - e.sw_rv)
    zm = e.groupby(['bid', 'zone'], observed=True).dv.mean().unstack()
    w = pd.Series(lgz).reindex(zm.columns)
    mine = (zm * w).sum(axis=1) / (zm.notna() * w).sum(axis=1)
    pr = pd.Series({b: v['sd_raw'] for b, v in prod.items() if v['sd_raw'] is not None})
    k = mine.index.intersection(pr.index)
    print(f"{Y}: rows {len(df)}, hitters {df.bid.nunique()}, SD parity max|d| {np.max(np.abs(mine[k] - pr[k])):.2e}", flush=True)
    s = df[df.ct_el & (df.lev > 0)]
    a = (s.lev * s.con).groupby(s.bid).sum(); x = (s.lev * (1 - s.pwh)).groupby(s.bid).sum()
    mc = a / x; pc = pd.Series({b: v['ct_raw'] for b, v in prod.items() if v['ct_raw'] is not None}); k = mc.index.intersection(pc.index)
    print(f"{Y}: CT parity max|d| {np.max(np.abs(mc[k] - pc[k])):.2e}; dates {df.date.min()} {df.date.max()}", flush=True)
    os.makedirs(OUT, exist_ok=True)
    pickle.dump(dict(df=df, prod=prod, lgz=lgz, guts=(lg, sc)), open(os.path.join(OUT, f'pitch_{Y}.pkl'), 'wb'))
    del P, elig, swings, rows, df; gc.collect()


if __name__ == '__main__':
    ys = [int(a) for a in sys.argv[1:]] or [2021, 2022, 2023, 2024, 2025, 2026]
    for Y in ys:
        build(Y)
