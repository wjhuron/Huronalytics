"""wx_apply_2026.py -- the candidate applied to the 2026 pitch cache (research copy).

RESEARCH ONLY. Writes nothing shipped. Recomputes neutral-environment movement
for every 2026 pitch from the RAW sheet columns with the final candidate
(data/_weather_audit/final_fit.json, version `nohand`), compares it with the
shipped xIndVrtBrk / xHorzBrk, and (with `stuff`) scores Stuff+ twice on the
SHIPPED bundle, once per movement set. The Stuff+ read is an estimate: the
bundle was trained on the old columns, and a retrain would follow a real change.

    neutral = (raw - shift) / exp(eP * lnP + eT * lnT)
    shift   = bP[cell] * lnP + bT[cell] * lnT + crosswind + headwind
    cell    = 30-degree spin-axis sector (RTilt) x speed band (84 / 90 mph)

Fallbacks, each counted: no measured weather -> standard-atmosphere pressure and
feed temperature; no RTilt or velocity -> exponents only.

Usage: .venv/bin/python scripts/research/weather/wx_apply_2026.py [stuff]
Output: data/_weather_audit/neutral_2026.npz (PitchID, new values) + console
"""
import os, sys, json, pickle
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from wx_exponent_sweep import OUT, RHO0, ROOT, moist
from wx_build_frame import tilt_axis
from wx_wind_hand_month import DIRS
sys.path.insert(0, ROOT)
from scrapers.pitcher2026 import compute_air_density, ROOF_CLOSED_CONDITIONS

T0K = 295.6
ROOF_K = {14: 0.4, 32: 0.5, 680: 0.6}          # Rogers, AmFam, T-Mobile (wx_roof_ingame.py)
COORS = 19


def sf(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def game_table(pks):
    """Per game: lnP, lnT, head mph, cross mph, venue, fallback flag."""
    side = json.load(open(os.path.join(ROOT, 'data', 'game_weather_rs.json')))
    obs = json.load(open(os.path.join(OUT, 'game_obs.json')))
    wind = json.load(open(os.path.join(OUT, 'wind.json')))
    T = {}
    for pk in pks:
        s = side.get(str(pk)) or {}
        o = obs.get(str(pk))
        el = s.get('elevationFt')
        closed = (s.get('condition') or '').strip().lower() in ROOF_CLOSED_CONDITIONS
        feed_t = s.get('tempF') if s.get('tempF') is not None else 70.0
        venue = s.get('venueId') or -1
        if o and el is not None:
            if closed:
                t = 72.0 + ROOF_K.get(venue, 0.0) * (o['tempF'] - 72.0)
                rho = moist(o['p_hpa'], t, 50.0)
            else:
                t = 0.5 * feed_t + 0.5 * o['tempF']
                rho = moist(o['p_hpa'], t, o['rh'])
            fb = 0
        elif el is not None:
            t = feed_t
            rho = compute_air_density(el, t); fb = 1
        else:
            T[pk] = (0.0, 0.0, 0.0, 0.0, venue, 2); continue
        lnT = -np.log(((t - 32) * 5 / 9 + 273.15) / T0K)
        lr = float(np.log(rho / RHO0))
        head = cross = 0.0
        w = wind.get(str(pk))
        if w and ',' in w and not closed:
            sp_, dr = w.split(',', 1)
            v = DIRS.get(dr.strip())
            try:
                mph = float(sp_.split()[0])
            except ValueError:
                mph = 0.0
            if v:
                head, cross = mph * v[0], mph * v[1]
        T[pk] = (lr - lnT, lnT, head, cross, venue, fb)
    return T


def main():
    F = json.load(open(os.path.join(OUT, 'final_fit.json'))); K = F['K']
    D = pickle.load(open(os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl'), 'rb'))
    n = len(D)
    pk = np.array([int(p['PitchID'].split('_')[0]) if p.get('PitchID') and p['PitchID'].split('_')[0].isdigit() else -1 for p in D])
    G = game_table([int(k) for k in np.unique(pk) if k > 0])
    rhp = np.array([p.get('Throws') == 'R' for p in D])
    has_hand = np.array([p.get('Throws') in ('L', 'R') for p in D])
    ivb = np.array([sf(p.get('IndVertBrk')) for p in D]); hb = np.array([sf(p.get('HorzBrk')) for p in D])
    xivb = np.array([sf(p.get('xIndVrtBrk')) for p in D]); xhb = np.array([sf(p.get('xHorzBrk')) for p in D])
    velo = np.array([sf(p.get('Velocity')) for p in D]); axis = np.array([tilt_axis(p.get('RTilt')) for p in D])
    gt = np.array([G.get(int(k), (0, 0, 0, 0, -1, 2)) for k in pk], dtype=float)
    lnP, lnT, head, cross, venue, fb = gt.T
    s = np.where(rhp, -1.0, 1.0)
    run = np.where(rhp, hb, -hb)
    # cell
    phi = np.radians(axis)
    ux = np.where(rhp, -np.sin(phi), np.sin(phi)); uz = -np.cos(phi)
    ang = (np.degrees(np.arctan2(uz, ux)) + 360.0) % 360.0
    okc = np.isfinite(axis) & np.isfinite(velo) & has_hand
    cell = np.where(okc, np.minimum(np.nan_to_num(ang) // 30, 11) * 3 + np.digitize(np.nan_to_num(velo), [84.0, 90.0]), 0).astype(int)
    # group mean movement for the headwind term (pitcher x pitch type, season)
    key = np.array([hash((p.get('Pitcher'), p.get('Throws'), p.get('Pitch Type'))) for p in D])
    g = np.unique(key, return_inverse=True)[1]
    out = {}
    for lab, raw in (('run', run), ('ride', ivb)):
        f = F[f'nohand|{lab}']; b = np.array(f['b'])
        cnt = np.bincount(g, weights=np.isfinite(raw)); gm = (np.bincount(g, weights=np.nan_to_num(raw)) / np.maximum(cnt, 1))[g]
        shift = np.where(okc, b[cell] * lnP + b[K + cell] * lnT, 0.0)
        if lab == 'run':
            shift = shift + b[2 * K] * cross * s
        shift = shift + b[2 * K + 1] * head * gm / 100.0
        out[lab] = (raw - shift) / np.exp(f['eP'] * lnP + f['eT'] * lnT)
    new_ivb = out['ride']; new_hb = np.where(rhp, out['run'], -out['run'])
    none = fb == 2
    new_ivb = np.where(none, ivb, new_ivb); new_hb = np.where(none, hb, new_hb)
    tracked = np.isfinite(ivb) & np.isfinite(hb)
    print(f'{n} pitches; tracked {tracked.sum()}')
    print(f'  fallback to the old density (no measured weather): {(tracked & (fb == 1)).sum()}')
    print(f'  no adjustment at all (no elevation): {(tracked & none).sum()}')
    print(f'  exponents only (no RTilt or velocity): {(tracked & ~okc & ~none).sum()}')
    np.savez_compressed(os.path.join(OUT, 'neutral_2026.npz'), pid=np.array([p.get('PitchID') or '' for p in D]),
                        new_ivb=new_ivb, new_hb=new_hb)
    # ---- size of the change against the shipped columns
    src = np.array([p.get('_source', 'MLB') for p in D]); pt = np.array([p.get('Pitch Type') or '' for p in D])
    mlb = (src == 'MLB') & tracked & np.isfinite(xivb) & np.isfinite(xhb)
    d_ride = new_ivb - xivb; d_run = np.where(rhp, new_hb - xhb, -(new_hb - xhb))
    print(f'\nMLB pitches: mean factor-equivalent change, per pitch: ride mean {d_ride[mlb].mean():+.2f} sd {d_ride[mlb].std():.2f} | '
          f'run (arm side) mean {d_run[mlb].mean():+.2f} sd {d_run[mlb].std():.2f}')
    ng = g.max() + 1
    nn = np.bincount(g, weights=mlb, minlength=ng)
    shc = np.bincount(g, weights=mlb & (venue == COORS), minlength=ng) / np.maximum(nn, 1)
    first = np.zeros(ng, int); first[g] = np.arange(n)
    print('change in the pitcher x pitch type SEASON MEAN, inches (new minus shipped), groups with 100+ pitches')
    print(f"  {'type':4s} {'ride: league mean / sd / max':>30s}   {'Colorado staff':>14s} | {'run: league mean / sd / max':>30s}   {'Colorado staff':>14s}")
    for p in ('FF', 'SI', 'FC', 'SL', 'ST', 'CU', 'CH', 'FS'):
        gm_ = (nn >= 100) & (pt[first] == p)
        col = gm_ & (shc >= 0.35)
        row = []
        for dv in (d_ride, d_run):
            m = np.bincount(g, weights=np.where(mlb, dv, 0.0), minlength=ng) / np.maximum(nn, 1)
            row.append(f'{m[gm_].mean():+.2f} / {m[gm_].std():.2f} / {np.abs(m[gm_]).max():.2f}   {m[col].mean() if col.any() else float("nan"):+.2f} (k{col.sum()})')
        print(f'  {p:4s} {row[0]:>46s} | {row[1]:>46s}')

    if len(sys.argv) > 1 and sys.argv[1] == 'stuff':
        import stuff_plus.train_stuff as sv
        bundle = pickle.load(open(os.path.join(ROOT, 'stuff_plus', 'stuff_models.pkl'), 'rb'))
        sv.check_bundle_fresh(bundle)
        names = np.array([p.get('Pitcher') or '' for p in D])
        at_coors = set(names[mlb & (venue == COORS)])
        rng = np.random.default_rng(0)
        others = sorted(set(names[mlb]) - at_coors)
        pick = at_coors | set(rng.choice(others, size=min(150, len(others)), replace=False))
        idx = [i for i in range(n) if src[i] == 'MLB' and names[i] in pick]
        sub = [D[i] for i in idx]
        del D
        print(f'\nStuff+ estimate: {len(pick)} pitchers ({len(at_coors)} threw at Coors), {len(sub)} pitches, bundle {bundle.get("version")}')
        league, _ = sv.live_scales(bundle)
        folds = bundle.get('fold_pitchers') or []; fold_of = {pp: k for k, ps in enumerate(folds) for pp in ps}

        def score():
            df = sv.build_df(sub)
            df = sv.fill_arm_prior(df, bundle.get('arm_prior'))
            res = {}
            for pitcher, sdf in df.groupby('pitcher'):
                if not bool(sdf['arm_angle'].notna().any()):
                    continue
                fi = fold_of.get(pitcher, 0); fms = bundle.get('fold_models') or []
                model = fms[fi] if fi < len(fms) else bundle['model']
                X = sv.design(sdf).reindex(columns=bundle['features'], fill_value=0)
                raw = -model.predict(X)
                for ptt in sdf['pitch_type'].unique():
                    sc = league.get(ptt)
                    if not sc or not sc.get('sd'):
                        continue
                    mk = (sdf['pitch_type'] == ptt).values
                    res[(pitcher, ptt)] = (float(np.mean(100 + sv.K_SCALE * (raw[mk] - sc['mu']) / sc['sd'])), int(mk.sum()))
            return res
        old = score()
        for j, i in enumerate(idx):
            if np.isfinite(new_ivb[i]) and np.isfinite(new_hb[i]):
                sub[j]['xIndVrtBrk'] = round(float(new_ivb[i]), 1); sub[j]['xHorzBrk'] = round(float(new_hb[i]), 1)
        new = score()
        col_names = set(names[(src == 'MLB') & (np.array([shc[k] for k in g]) >= 0.35)])
        rows = [(k[0], k[1], new[k][0] - old[k][0], old[k][0], old[k][1]) for k in old if k in new and old[k][1] >= 100]
        dv = np.array([r[2] for r in rows])
        print(f'  pitcher x pitch type (100+ pitches): {len(rows)} units; Stuff+ change mean {dv.mean():+.2f}, sd {dv.std():.2f}, '
              f'|change| p50 {np.median(np.abs(dv)):.2f} p90 {np.percentile(np.abs(dv), 90):.2f} max {np.abs(dv).max():.2f}')
        cr = [r for r in rows if r[0] in col_names]
        if cr:
            cv = np.array([r[2] for r in cr])
            print(f'  Colorado staff: {len(cr)} units; change mean {cv.mean():+.2f}, sd {cv.std():.2f}, range {cv.min():+.2f} to {cv.max():+.2f}')
            for r in sorted(cr, key=lambda r: -abs(r[2]))[:10]:
                print(f'     {r[0]:22s} {r[1]:3s} {r[3]:6.1f} -> {r[3] + r[2]:6.1f}  ({r[2]:+.1f}, {r[4]} pitches)')
        print('  largest movers, any team:')
        for r in sorted(rows, key=lambda r: -abs(r[2]))[:10]:
            print(f'     {r[0]:22s} {r[1]:3s} {r[3]:6.1f} -> {r[3] + r[2]:6.1f}  ({r[2]:+.1f}, {r[4]} pitches)')
        json.dump([dict(pitcher=r[0], pt=r[1], d=r[2], old=r[3], n=r[4]) for r in rows],
                  open(os.path.join(OUT, 'stuff_effect_2026.json'), 'w'))


if __name__ == '__main__':
    main()
