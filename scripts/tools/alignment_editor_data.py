#!/usr/bin/env python3
"""Data for the interactive alignment editor (one batter, one JSON file).

Everything the page needs to score an alignment live, built with the same
functions as the spray charts (spray_advance_report), so the page's numbers
match the charts':
    panels      career and single-season Total / vs RHP / vs LHP, by runner state
                (all, bases empty, runner on first only, other), each with
                its outfield balls (x, y ft; opportunity time s; wall weight),
                grounder angles, the shading grids, and the preset alignments
                (normal, fitted shift or normal where flat, infield fit) with
                their Python-scored expected outs for the page to check
                itself against
    catch       the filled catch table (catch_grid), back x wall x time x ft,
                C order, to 6 decimals
    teams_by    the defense's mean start spot per fielder against this batter
                (Savant batter positioning) per panel, all seasons pooled and
                the latest; the vs-hand entries are estimates (team_means)

Usage (from the repo root):
    python3 scripts/tools/alignment_editor_data.py --csv ~/Downloads/savant_data.csv \
        --batter-id 695578 --out <path>.json --page <path>.html
"""
import argparse
import json
import math
import os

import numpy as np

import catch_grid
import hang_time
import spray_advance_report as sar

POS = {3: '1B', 4: '2B', 5: '3B', 6: 'SS', 7: 'LF', 8: 'CF', 9: 'RF'}
OF_GRID = (np.arange(-330, 331, 10), np.arange(0, 431, 10))


def of_density(xy, h):
    gx, gy = np.meshgrid(*OF_GRID)
    d = np.zeros_like(gx, dtype=float)
    for x, y in xy:
        d += np.exp(-((gx - x) ** 2 + (gy - y) ** 2) / (2 * h * h))
    d /= d.max()
    th = np.arctan2(gx, gy)
    r = np.hypot(gx, gy)
    arc = sar.MOUND_FT * np.cos(th) + np.sqrt(
        np.clip(sar.INFIELD_ARC_FT ** 2 - (sar.MOUND_FT * np.sin(th)) ** 2, 0, None))
    mask = (np.abs(th) > math.radians(45)) | (r < arc) | (r > 330 + 70 * np.cos(2 * th))
    return np.where(mask, -1, np.round(d * 100)).astype(int).tolist()


def gb_density(angs, h):
    th = np.arange(-45, 46, 1.0)
    d = np.exp(-(th[:, None] - angs[None, :]) ** 2 / (2 * h * h)).sum(1)
    return np.round(100 * d / d.max()).astype(int).tolist()


def panel_data(rows, total_gb, tracked, hmodel, grid, rng):
    balls, src = sar.of_balls(rows, tracked, hmodel)
    gb = np.array([r['ang'] for r in rows if r['key'] == 'ground_ball'])
    air_xy = np.array([[r['x'], r['y']] for r in rows
                       if r['key'] in ('line_drive', 'fly_ball') and r['event'] != 'Home Run'])
    h_gb, _ = sar.pick(sar.GB_BW_GRID, sar.loo_1d(gb, sar.GB_BW_GRID))
    h_air, _ = sar.pick(sar.AIR_BW_GRID, sar.loo_2d(air_xy, sar.AIR_BW_GRID))
    spots, _boot, inf, of = sar.fit_spots(rows, rng, tracked, hmodel, grid, 'fitted', total_gb)
    # Full precision: a 0.1 ft rounding moves balls across the catch table's
    # 1 ft cells and cost the page up to 0.13 outs against 'check'.
    fitted = {k: [float(v) for v in spots[k]] for k in ('LF', 'CF', 'RF')}
    normal = {k: [float(v) for v in xy] for k, xy in zip(('LF', 'CF', 'RF'), sar.positions(0.0, 0.0))}
    infield = {k: [float(v) for v in spots[k]] for k in ('3B', 'SS', '2B', '1B')}
    return {
        'n_bip': len(rows),
        # Full precision, so the page's live score reproduces 'check' exactly.
        'balls': [[float(x), float(y), float(t), float(w)] for x, y, t, w in zip(*balls)],
        'tracked': src.count('tracked'),
        'grounders': [round(float(a), 2) for a in gb],
        'shade_of': of_density(air_xy, h_air),
        'shade_gb': gb_density(gb, h_gb),
        'presets': {'normal': normal, 'fitted': fitted, 'infield': infield},
        'fit': {'flat': bool(of['flat']), 'phi': of['phi'], 'delta': of['delta']},
        'check': {'normal_xouts': round(of['normal_xouts'], 3),
                  'fitted_xouts': round(of['fit_xouts'], 3) if not of['flat'] else round(of['normal_xouts'], 3)},
    }


RUNNERS = {'all': None, 'empty': 'empty', '1b': '1b', 'other': 'other'}
RUNNER_CODE = {'empty': '0', '1b': '1', 'other': '27'}   # Savant positioning groups


def runner_panel(rows, base, tracked, hmodel, grid, hold_1b=None):
    """A runner-state view of a base panel: its own balls, grounders and
    shading, the BASE panel's optimal alignment (runner-state alignments
    failed research/fielding/runner_state_gate.py: outfield 0/3 vs RHP,
    infield 1/3 each hand), and with a runner on first only the 1B moved to
    the teams' average holding spot, since he must hold the runner."""
    balls, src = sar.of_balls(rows, tracked, hmodel)
    gb = np.array([r['ang'] for r in rows if r['key'] == 'ground_ball'])
    air_xy = np.array([[r['x'], r['y']] for r in rows
                       if r['key'] in ('line_drive', 'fly_ball') and r['event'] != 'Home Run'])
    h_gb, _ = sar.pick(sar.GB_BW_GRID, sar.loo_1d(gb, sar.GB_BW_GRID))
    h_air, _ = sar.pick(sar.AIR_BW_GRID, sar.loo_2d(air_xy, sar.AIR_BW_GRID))
    presets = json.loads(json.dumps(base['presets']))
    if hold_1b is not None:
        presets['infield']['1B'] = [float(v) for v in hold_1b]
    def xo(spots):
        pos = np.array([spots[k] for k in ('LF', 'CF', 'RF')])
        return round(float(sar.out_prob_matrix(pos, balls, grid).max(0).sum()), 3)
    return {
        'n_bip': len(rows),
        'balls': [[float(x), float(y), float(t), float(w)] for x, y, t, w in zip(*balls)],
        'tracked': src.count('tracked'),
        'grounders': [round(float(a), 2) for a in gb],
        'shade_of': of_density(air_xy, h_air),
        'shade_gb': gb_density(gb, h_gb),
        'presets': presets,
        'fit': dict(base['fit']),
        'check': {'normal_xouts': xo(presets['normal']), 'fitted_xouts': xo(presets['fitted'])},
        'hold_1b': hold_1b is not None,
    }


def team_means(batter_id, seasons, shade_share=None, runner=None):
    """Mean start spot per fielder. With shade_share, an ESTIMATE for one
    pitcher hand: Savant's positions carry no hand, only the infield-shaded
    flag, so the shaded and unshaded means are blended at that hand's share
    of shaded plate appearances (from the CSV labels). On Wood the blend at
    the overall share reproduces the real means within 0.1 deg and 1 ft."""
    path = os.path.join(sar.REPO, 'data', f'_positioning_{batter_id}.json')
    with open(path) as f:
        rows = [r for r in json.load(f) if r['season'] in seasons
                and (runner is None or r['group_runners_on_cd'] == RUNNER_CODE[runner])]
    out = {}
    for pid, name in POS.items():
        mine = [r for r in rows if int(r['pos_id']) == pid]
        xy = lambda rs: np.array([[float(r['start_pos_x']), float(r['start_pos_y'])] for r in rs]).mean(0)
        if shade_share is None:
            v = xy(mine)
        else:
            v = (shade_share * xy([r for r in mine if r['is_shift_infield'] == '1'])
                 + (1 - shade_share) * xy([r for r in mine if r['is_shift_infield'] == '0']))
        out[name] = [round(float(c), 1) for c in v]
    return out, len(rows) // 7


def shade_shares(csv, seasons, runner=None):
    """Share of plate appearances with an 'Infield shade' label, by hand."""
    import pandas as pd
    sv = pd.read_csv(os.path.expanduser(csv), low_memory=False,
                     usecols=['game_year', 'events', 'p_throws', 'if_fielding_alignment',
                              'on_1b', 'on_2b', 'on_3b'])
    pa = sv[sv.events.notna() & sv.game_year.isin(seasons)]
    if runner is not None:
        st = np.where(pa.on_1b.isna() & pa.on_2b.isna() & pa.on_3b.isna(), 'empty',
                      np.where(pa.on_2b.isna() & pa.on_3b.isna(), '1b', 'other'))
        pa = pa[st == runner]
    return {h: float((pa[pa.p_throws == h].if_fielding_alignment == 'Infield shade').mean())
            for h in ('R', 'L')}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--csv', required=True)
    ap.add_argument('--batter-id', type=int, required=True)
    ap.add_argument('--seasons', type=int, nargs='+', default=[2024, 2025, 2026])
    ap.add_argument('--out', required=True)
    ap.add_argument('--page', default=None,
                    help='also write the editor page (alignment_editor.html with this data)')
    args = ap.parse_args()

    grid, _ = catch_grid.fill(catch_grid.build())
    tracked = sar.load_tracked(args.seasons)
    hmodel, *_ = hang_time.fit(args.seasons, exclude=args.batter_id)
    rng = np.random.default_rng(0)
    data = {'panels': {}}
    latest = max(args.seasons)
    for label, seasons in (('career', args.seasons), (str(latest), [latest])):
        rows, _d, (d0, d1) = sar.load(None, args.csv, seasons)
        for hand, sub in (('Total', rows), ('vs RHP', [r for r in rows if r['throws'] == 'R']),
                          ('vs LHP', [r for r in rows if r['throws'] == 'L'])):
            key = f'{label}|{hand}|all'
            # Each panel's optimal infield is fitted on its own grounders
            # (Wally 2026-10-28). The gate found hand and Total infields flat
            # against each other (within 0.05 deg), so neither is better.
            own_gb = np.array([r['ang'] for r in sub if r['key'] == 'ground_ball'])
            data['panels'][key] = panel_data(sub, own_gb, tracked, hmodel, grid, rng)
            data['panels'][key]['dates'] = [d0, d1]
            p = data['panels'][key]
            print(f'{key:22s} {p["n_bip"]} BIP, {len(p["balls"])} OF balls, '
                  f'{len(p["grounders"])} GB; normal {p["check"]["normal_xouts"]}, '
                  f'fitted {p["check"]["fitted_xouts"]} (flat={p["fit"]["flat"]})')
            hold, _ = team_means(args.batter_id, seasons, runner='1b')
            for rs in ('empty', '1b', 'other'):
                rkey = f'{label}|{hand}|{rs}'
                data['panels'][rkey] = runner_panel([r for r in sub if r['runners'] == rs], p,
                                                    tracked, hmodel, grid,
                                                    hold['1B'] if rs == '1b' else None)
                data['panels'][rkey]['dates'] = [d0, d1]
                q = data['panels'][rkey]
                print(f'{rkey:22s} {q["n_bip"]} BIP, {len(q["balls"])} OF balls, {len(q["grounders"])} GB')
    # Savant start spots against this batter, keyed like the panels' data
    # choice: every season pooled (plate-appearance weighted) and the latest.
    data['teams_by'], data['teams_pa'], data['shade_share'] = {}, {}, {}
    for label, seasons in (('career', args.seasons), (str(latest), [latest])):
        for rs, code in RUNNERS.items():
            sh = shade_shares(args.csv, seasons, code)
            data['teams_by'][f'{label}|Total|{rs}'], n = team_means(args.batter_id, seasons, runner=code)
            data['teams_by'][f'{label}|vs RHP|{rs}'], _ = team_means(args.batter_id, seasons, sh['R'], code)
            data['teams_by'][f'{label}|vs LHP|{rs}'], _ = team_means(args.batter_id, seasons, sh['L'], code)
            data['teams_pa'][f'{label}|{rs}'] = n
            data['shade_share'][f'{label}|{rs}'] = {'vs RHP': round(sh['R'], 3), 'vs LHP': round(sh['L'], 3)}
    print('teams PA:', data['teams_pa'], 'shade share:', data['shade_share'])
    # Flat panels (no outfield shift held up) fall back to the teams' real
    # spots against THIS batter, not the league-normal outfield (Wally
    # 2026-10-28): fixed and never fitted to his balls, they beat normal in
    # 3/3 seasons for Total and 2/3 for each hand on Wood 2024-2026.
    for key, p in data['panels'].items():
        if not p['fit']['flat']:
            continue
        t = data['teams_by'][key]
        p['presets']['fitted'] = {k: [float(v) for v in t[k]] for k in ('LF', 'CF', 'RF')}
        b = np.array(p['balls']).T
        pos = np.array([p['presets']['fitted'][k] for k in ('LF', 'CF', 'RF')])
        p['check']['fitted_xouts'] = round(float(sar.out_prob_matrix(pos, tuple(b), grid).max(0).sum()), 3)
        p['fit']['fallback'] = 'teams'
    data['catch'] = {
        't0': catch_grid.T0, 'nt': grid.shape[2], 'dmax': catch_grid.D_MAX,
        'values': [round(float(v), 6) for v in grid.ravel()],
    }
    data['geometry'] = {'mound_ft': sar.MOUND_FT, 'arc_ft': sar.INFIELD_ARC_FT,
                        'base_ft': sar.BASE_PATH_FT, 'of_grid': [-330, 0, 10]}
    out = os.path.expanduser(args.out)
    tmp = out + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, separators=(',', ':'))
    os.replace(tmp, out)
    print(f'-> {out} ({os.path.getsize(out) / 1e6:.2f} MB)')
    if args.page:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'alignment_editor.html')) as f:
            tpl = f.read()
        if tpl.count('__DATA__') != 1:
            raise SystemExit('alignment_editor.html must hold exactly one __DATA__ marker.')
        # '</' cannot appear inside a <script> block; JSON allows the '\/' escape.
        page = tpl.replace('__DATA__', json.dumps(data, separators=(',', ':')).replace('</', '<\\/'))
        dest = os.path.expanduser(args.page)
        with open(dest + '.tmp', 'w') as f:
            f.write(page)
        os.replace(dest + '.tmp', dest)
        print(f'-> {dest} ({os.path.getsize(dest) / 1e6:.2f} MB)')


if __name__ == '__main__':
    main()
