"""fa_rundown_table.py: the 2027 free-agent projection table for the offseason rundown (per Wally 2026-11-02).

Rundown only: nothing here reaches the site. For every player in data/free_agents.json:
  site     shipped hpWAR rate, projected PT and total (data/hpwar_projections.json)
  blend    50/50 ours + Steamer 2027 on wOBA (hitters) or RA9 vs ERA (pitchers). Steamer is centered on ours over everyone both project,
           projected-PT weighted (h2h_batting's centering), so the level stays ours and Steamer contributes ranking and spread.
  FA       hitters only: blend wOBA + FA_WOBA and projected PA + the tier gap (fa_rundown_constants.py).
           The PA gap is piecewise linear through the four tier means at each tier's mean projected PA, a convention, with the
           +5.5 (SE 5.9) lowest tier read as 0. Pitchers carry no correction: no rate gap, and the 4 IP gap is small.
  Since 2026-11-02 the site's pitcher projection carries 2026 Stuff+ and exit velocity allowed, so the pitcher blend is on the site's RA9.
Conversions are project_players.py's: hitter bat runs = wOBA delta / scale x 600, pitcher WAR = (lgRA9 - RA9) x IP / 9 / RPW + repl x IP / 9.
A rate comes only from the player's own unit (PA600, SP180, RP60). Players ours does not project keep Steamer alone, with no blend.

Usage: python3 scripts/research/projection/fa_rundown_table.py
Output: ~/Downloads/fa_rundown_2027_hitters.csv, ~/Downloads/fa_rundown_2027_pitchers.csv
"""
import csv
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
P = os.path.join(ROOT, 'data', '_proj')
OUTDIR = os.path.expanduser('~/Downloads')
FA_WOBA = -0.0060
UNIT = {'PA600': 600.0, 'SP180': 180.0, 'RP60': 60.0}


def rate3(v):
    """Three-decimal rate with no leading zero."""
    if v is None:
        return ''
    s = f'{v:.3f}'
    return s.replace('0.', '.', 1)


def num(v, d=2):
    return '' if v is None else f'{v:.{d}f}'


def main():
    fa = json.load(open(os.path.join(ROOT, 'data', 'free_agents.json')))['players']
    hp = json.load(open(os.path.join(ROOT, 'data', 'hpwar_projections.json')))
    meta = json.load(open(os.path.join(ROOT, 'data', 'metadata_rs.json')))
    hc = meta['hwarConstants']; wc = meta['eraPlusConstants']['war']
    scale, rpw = hc['wobaScale'], hc['rpw']
    lg_ra9 = wc['lgRA9']
    st_b = {int(r['xMLBAMID']): r for r in json.load(open(os.path.join(P, 'fg', 'steamer_2027_bat.json'))) if r.get('xMLBAMID')}
    st_p = {int(r['xMLBAMID']): r for r in json.load(open(os.path.join(P, 'fg', 'steamer_2027_pit.json'))) if r.get('xMLBAMID')}
    ph = {int(r['mlbId']): r for r in csv.DictReader(open(os.path.join(P, 'projections_hitters.csv')))}
    pp = {int(r['mlbId']): r for r in csv.DictReader(open(os.path.join(P, 'projections_pitchers.csv')))}
    tiers = json.load(open(os.path.join(P, '_fa_rundown_constants.json')))['pa_tiers']
    xs = [v['proj'] for v in tiers.values()]; ys = [0.0] + [v['fa'] for k, v in tiers.items() if not k.startswith('0-')]

    def pa_fa(pa):
        return max(0.0, pa + float(np.interp(pa, xs, ys, left=0.0)))

    # ---- centering
    hb = [(int(k), v) for k, v in hp['hitters'].items() if int(k) in st_b and int(k) in ph and st_b[int(k)].get('wOBA') is not None and (v.get('pt') or 0) > 0 and ph[int(k)].get('wOBA_2027')]
    w = np.array([v['pt'] for _, v in hb]); ours = np.array([float(ph[k]['wOBA_2027']) for k, _ in hb]); th = np.array([float(st_b[k]['wOBA']) for k, _ in hb])
    d_h = float(np.average(ours, weights=w) - np.average(th, weights=w))
    pb = []
    for k, v in hp['pitchers'].items():
        k = int(k)
        if k in st_p and k in pp and st_p[k].get('ERA') is not None and (v.get('pt') or 0) > 0:
            role = 'SP' if v['unit'] == 'SP180' else 'RP'
            pb.append((float(pp[k][f'RA9_{role}_2027']), float(st_p[k]['ERA']), v['pt']))
    a = np.array(pb); d_p = float(np.average(a[:, 0], weights=a[:, 2]) - np.average(a[:, 1], weights=a[:, 2]))
    print(f'centering pools: hitters {len(hb)} (steamer + {d_h:+.4f}), pitchers {len(pb)} (steamer + {d_p:+.3f})')

    # ---- validation: conversions reproduce the shipped rates
    dd = []
    for k, v in hp['pitchers'].items():
        k = int(k)
        if k in pp and v.get('hpWAR') is not None:
            role, ip = ('SP', 180.0) if v['unit'] == 'SP180' else ('RP', 60.0)
            repl = wc['replSp'] if role == 'SP' else wc['replRp']
            dd.append(abs((lg_ra9 - float(pp[k][f'RA9_{role}_2027'])) * ip / 9 / rpw + repl * ip / 9 - v['hpWAR']))
    print(f'pitcher WAR conversion vs shipped hpWAR: n {len(dd)} max |d| {max(dd):.3f} rows > .02: {sum(x > .02 for x in dd)}')
    if max(dd) > 0.02:
        raise SystemExit('conversion does not reproduce shipped hpWAR: stop')
    dt = [abs(v['hpWAR'] * v['pt'] / UNIT[v['unit']] - v['tot']) for v in hp['hitters'].values() if v.get('pt') is not None and v.get('hpWAR') is not None]
    print(f'hitter total = rate x PT / unit vs shipped: n {len(dt)} max |d| {max(dt):.3f}')

    H, Pi = [], []
    for r in fa:
        i = int(r['mlbId'])
        base = dict(mlbId=i, name=r['name'], age_2027=r.get('age', ''), status=r.get('fgStatus', ''))
        if i in st_b and i not in st_p:
            v = hp['hitters'].get(str(i)); o = ph.get(i); st = float(st_b[i]['wOBA']) if st_b[i].get('wOBA') is not None else None
            row = dict(base, steamer_wOBA_raw=rate3(st), steamer_WAR=num(st_b[i].get('WAR')), steamer_PA=num(st_b[i].get('PA'), 0))
            if v and o and o.get('wOBA_2027') and v.get('hpWAR') is not None:
                ours_w = float(o['wOBA_2027']); pa = v.get('pt')
                bl = 0.5 * ours_w + 0.5 * (st + d_h) if st is not None else None
                war_b = v['hpWAR'] + (bl - ours_w) * 600 / scale / rpw if bl is not None else None
                war_f = war_b + FA_WOBA * 600 / scale / rpw if war_b is not None else None
                paf = pa_fa(pa) if pa is not None else None
                row.update(wOBA_site=rate3(ours_w), wOBA_blend=rate3(bl), wOBA_blend_FA=rate3(bl + FA_WOBA if bl is not None else None),
                           PA_site=num(pa, 0), PA_FA=num(paf, 0), hpWAR600_site=num(v['hpWAR']), hpWAR600_blend=num(war_b), hpWAR600_blend_FA=num(war_f),
                           total_site=num(v.get('tot')), total_blend=num(war_b * pa / 600 if war_b is not None and pa is not None else None),
                           total_blend_FA=num(war_f * paf / 600 if war_f is not None and paf is not None else None), thin_age=v.get('thin') or '')
            else:
                row['note'] = 'no projection of ours: Steamer only'
            H.append(row)
        elif i in st_p:
            v = hp['pitchers'].get(str(i)); s_ = st_p[i]; st = float(s_['ERA']) if s_.get('ERA') is not None else None
            row = dict(base, steamer_ERA_raw=num(st), steamer_WAR=num(s_.get('WAR')), steamer_IP=num(s_.get('IP'), 0))
            if v and i in pp and v.get('hpWAR') is not None:
                role, ip = ('SP', 180.0) if v['unit'] == 'SP180' else ('RP', 60.0)
                repl = wc['replSp'] if role == 'SP' else wc['replRp']
                war = lambda ra: (lg_ra9 - ra) * ip / 9 / rpw + repl * ip / 9
                r0 = float(pp[i][f'RA9_{role}_2027'])
                bl = 0.5 * r0 + 0.5 * (st + d_p) if st is not None else None
                g = float(s_.get('G') or 0); gs = float(s_.get('GS') or 0)
                st_role = 'SP' if g and gs / g >= 0.5 else 'RP'
                ipt = v.get('pt')
                # the total reads his start share, as build_hpwar.py does; the rate keeps the unit
                sh = v.get('share', 1.0 if role == 'SP' else 0.0)
                ra_sh = float(pp[i]['RA9_RP_2027']) + sh * (float(pp[i]['RA9_SP_2027']) - float(pp[i]['RA9_RP_2027']))
                rep_sh = wc['replRp'] + sh * (wc['replSp'] - wc['replRp'])
                bl_sh = 0.5 * ra_sh + 0.5 * (st + d_p) if st is not None else None
                row.update(unit=v['unit'], RA9_site=num(r0), RA9_blend=num(bl),
                           IP_site=num(ipt, 0), hpWAR_unit_site=num(v['hpWAR']), hpWAR_unit_blend=num(war(bl) if bl is not None else None),
                           total_site=num(v.get('tot')),
                           total_blend=num(((lg_ra9 - bl_sh) / rpw + rep_sh) * ipt / 9 if bl_sh is not None and ipt is not None else None),
                           role_differs_from_steamer='yes' if st_role != role else '', thin_age=v.get('thin') or '')
            else:
                row['note'] = 'no projection of ours: Steamer only'
            Pi.append(row)
        else:
            raise SystemExit(f'{r["name"]} {i} in neither Steamer file')
    key = lambda c: float(c) if c not in ('', None) else -99
    H.sort(key=lambda x: -key(x.get('total_blend_FA'))); Pi.sort(key=lambda x: -key(x.get('total_blend')))
    HC = ['mlbId', 'name', 'age_2027', 'status', 'total_site', 'total_blend', 'total_blend_FA', 'hpWAR600_site', 'hpWAR600_blend', 'hpWAR600_blend_FA', 'PA_site', 'PA_FA',
          'wOBA_site', 'wOBA_blend', 'wOBA_blend_FA', 'steamer_wOBA_raw', 'steamer_WAR', 'steamer_PA', 'thin_age', 'note']
    PC = ['mlbId', 'name', 'age_2027', 'status', 'unit', 'total_site', 'total_blend', 'hpWAR_unit_site', 'hpWAR_unit_blend', 'IP_site',
          'RA9_site', 'RA9_blend', 'steamer_ERA_raw', 'steamer_WAR', 'steamer_IP', 'role_differs_from_steamer', 'thin_age', 'note']
    for name, rows, cols in (('fa_rundown_2027_hitters.csv', H, HC), ('fa_rundown_2027_pitchers.csv', Pi, PC)):
        path = os.path.join(OUTDIR, name)
        with open(path + '.tmp', 'w', newline='') as f:
            wr = csv.DictWriter(f, fieldnames=cols); wr.writeheader(); wr.writerows(rows)
        os.replace(path + '.tmp', path)
        print(f'wrote {path}: {len(rows)} rows, no projection of ours {sum(1 for r in rows if r.get("note"))}')


if __name__ == '__main__':
    main()
