"""fa_position_rankings.py: free-agent rankings by position at 1, 3 and 5 seasons (per Wally 2026-11-05). Research only, nothing reaches the site.

Reads ~/Downloads/fa_rundown_2027_{hitters,pitchers}.csv and the fits in data/_proj/_fa_rank_blend.json (fa_rank_blend.py).
2027 value B, expected WAR:
  hitters   total_blend_FA: even ours + Steamer, then the FA corrections.
  starters  total_blend: even ours + Steamer on RA9.
  relievers even ours + ZiPS on rate, ZiPS centered on ours over every projected reliever (the rundown's centering form), x our innings. Steamer weight 0 per fa_rank_blend.py.
3 and 5 seasons: cumulative expected WAR, absent seasons at 0. M2 for hitters and starters, M1 for relievers, all-sample coefficients.
Eligibility (a convention): 25 percent of a player's fielding innings and 150 innings at the position, innings weighted .3 per season back over 2024-2026, the pos_assignment_test form. DH innings stay out of the share.
A reliever-unit arm whose Steamer role is starter also gets a starter-role value and may list as a starter, marked.
List end (a convention): the floor is .2 WAR per season for hitters and starters, .1 for relievers, where free agents 2021-2026 took a major-league deal about 9 times in 10 (data/_fa_contracts/dataset.csv).
If over 30 clear the floor, the list ends at the largest drop between ranks 15 and 30.

Usage: python3 scripts/research/projection/fa_position_rankings.py
Output: ~/Downloads/fa_position_rankings_2027.csv, data/_proj/_fa_position_rankings.json
"""
import csv
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
import pos_assignment_test as pat

P = os.path.join(ROOT, 'data', '_proj')
DL = os.path.expanduser('~/Downloads')
FLOOR = {'H': .2, 'SP': .2, 'RP': .1}
INF = ('1B', '2B', '3B', 'SS')
OF = ('LF', 'CF', 'RF')
MIN_SHARE, MIN_INN = .25, 150.0


def f(x):
    return float(x) if x not in ('', None) else None


def read(path):
    return list(csv.DictReader(open(path, encoding='utf-8-sig')))


def lb(name):
    d = json.load(open(os.path.join(ROOT, 'data', name)))
    rows = d if isinstance(d, list) else next(iter(d.values()))
    out = {}
    for r in rows:
        i = r.get('mlbId')
        k = r.get('pa') or r.get('tbf') or 0
        if i is not None and (i not in out or k > (out[i].get('pa') or out[i].get('tbf') or 0)):
            out[int(i)] = r
    return out


def m2(c, B, R, a):
    return c[0] + B * (c[1] + c[2] * a) + R * (c[3] + c[4] * a) + c[5] * a


def m1(c, B, a):
    return c[0] + B * (c[1] + c[2] * a)


def end_list(rows, key, floor):
    rows = sorted([r for r in rows if r[key] is not None], key=lambda r: -r[key])
    keep = [r for r in rows if r[key] >= floor]
    if len(keep) <= 30:
        return keep
    v = [r[key] for r in keep]
    gaps = [(v[i - 1] - v[i], i) for i in range(15, 30)]
    return keep[:max(gaps)[1]]


def main():
    fit = json.load(open(os.path.join(P, '_fa_rank_blend.json')))['part3']
    meta = json.load(open(os.path.join(ROOT, 'data', 'metadata_rs.json')))
    wc = meta['eraPlusConstants']['war']; rpw = meta['hwarConstants']['rpw']
    LH, LP = lb('hitter_leaderboard_rs.json'), lb('pitcher_leaderboard_rs.json')
    hp = json.load(open(os.path.join(ROOT, 'data', 'hpwar_projections.json')))
    pp = {int(r['mlbId']): r for r in read(os.path.join(P, 'projections_pitchers.csv'))}
    z = {int(r['xMLBAMID']): r for r in json.load(open(os.path.join(P, 'fg', 'zips_2027_pit.json'))) if r.get('xMLBAMID')}
    # reliever ZiPS centering, innings weighted, over every projected reliever
    pool = [(v['hpWAR'] / 60, float(z[int(k)]['WAR']) / float(z[int(k)]['IP']), v['pt']) for k, v in hp['pitchers'].items()
            if v.get('unit') == 'RP60' and v.get('hpWAR') is not None and (v.get('pt') or 0) > 0 and int(k) in z and float(z[int(k)].get('IP') or 0) >= 5 and float(z[int(k)].get('GS') or 0) < .5 * float(z[int(k)].get('G') or 1)]
    a_ = np.array(pool); d_z = float(np.average(a_[:, 0], weights=a_[:, 2]) - np.average(a_[:, 1], weights=a_[:, 2]))
    print(f'reliever ZiPS centering: {len(pool)} arms, {d_z * 60:+.3f} WAR per 60 IP')

    # ---- pitchers
    rows_p = read(os.path.join(DL, 'fa_rundown_2027_pitchers.csv'))
    ds = [f(r['RA9_blend']) - .5 * (f(r['RA9_site']) + f(r['steamer_ERA_raw'])) for r in rows_p if f(r['RA9_blend']) is not None and f(r['steamer_ERA_raw']) is not None]
    d_p = 2 * float(np.median(ds))
    print(f'Steamer ERA centering read back from the file: {d_p:+.3f}, spread {max(ds) - min(ds):.3f}')
    P_out = []
    for r in rows_p:
        i = int(r['mlbId']); age = int(r['age_2027']); a = age - 30.0; ip = f(r['IP_site']); L = LP.get(i, {})
        ev = dict(mlbId=i, name=r['name'], age=age, status=r['status'], ip=ip, thin=r['thin_age'], era=L.get('era'), hpERA=L.get('hpERA'), hdWAR=L.get('hWAR'), fWAR=L.get('fWAR'), ip26=L.get('ip'), stuff=L.get('stuffScore'), kbb=L.get('kbbPct'), rate_note='')
        if f(r['total_blend']) is None or ip is None:
            continue
        if r['unit'] == 'SP180':
            B = f(r['total_blend']); R = f(r['hpWAR_unit_blend'])
            P_out.append(dict(ev, group='SP', pos=['SP'], rate=R, B=B, v3=m2(fit['SP_3']['coef']['M2'], B, R, a), v5=m2(fit['SP_5']['coef']['M2'], B, R, a)))
        else:
            zz = z.get(i); ours = f(r['hpWAR_unit_site']) / 60
            z_rel = zz and float(zz.get('IP') or 0) >= 5 and float(zz.get('GS') or 0) < .5 * float(zz.get('G') or 1)   # a ZiPS starter's WAR per inning is not a reliever rate
            rt = .5 * ours + .5 * (float(zz['WAR']) / float(zz['IP']) + d_z) if z_rel else ours
            B = rt * ip; R = rt * 60
            P_out.append(dict(ev, group='RP', pos=['RP'], rate=R, B=B, v3=m1(fit['RP_3']['coef']['M1'], B, a), v5=m1(fit['RP_5']['coef']['M1'], B, a)))
            if r['role_differs_from_steamer'] == 'yes' and i in pp and pp[i].get('RA9_SP_2027'):
                st = .5 * float(pp[i]['RA9_SP_2027']) + .5 * (f(r['steamer_ERA_raw']) + d_p)
                Rs = (wc['lgRA9'] - st) * 20 / rpw + wc['replSp'] * 20; Bs = Rs * ip / 180
                P_out.append(dict(ev, group='SP', pos=['SP'], rate=Rs, B=Bs, v3=m2(fit['SP_3']['coef']['M2'], Bs, Rs, a), v5=m2(fit['SP_5']['coef']['M2'], Bs, Rs, a), rate_note='starter role, relieved in 2026'))

    # ---- hitters
    INN = {y: pat.innings(y) for y in (2024, 2025, 2026)}
    H_out = []; dh_only = []
    for r in read(os.path.join(DL, 'fa_rundown_2027_hitters.csv')):
        i = int(r['mlbId']); age = int(r['age_2027']); a = age - 30.0; L = LH.get(i, {})
        B, R = f(r['total_blend_FA']), f(r['hpWAR600_blend_FA'])
        if B is None or R is None:
            continue
        sh = {}
        for k, y in enumerate((2026, 2025, 2024)):
            for p_, v in (INN[y].get(i) or {}).items():
                sh[p_] = sh.get(p_, 0.0) + .3 ** k * v
        fld = {p_: v for p_, v in sh.items() if p_ != 'DH'}; tot = sum(fld.values())
        pos = [p_ for p_, v in sorted(fld.items(), key=lambda t: -t[1]) if tot and v / tot >= MIN_SHARE and v >= MIN_INN]
        row = dict(mlbId=i, name=r['name'], age=age, status=r['status'], group='H', pos=pos, rate=R, B=B, pa=f(r['PA_FA']), thin=r['thin_age'], v3=m2(fit['H_3']['coef']['M2'], B, R, a), v5=m2(fit['H_5']['coef']['M2'], B, R, a),
                   shares={p_: round(v / tot, 2) for p_, v in fld.items()} if tot else {}, wOBA=L.get('wOBA'), xwOBA=L.get('xwOBA'), hdWAR=L.get('hWAR'), fWAR=L.get('fWAR'), fld=L.get('hFldRuns'), processPlus=L.get('processPlus'), pa26=L.get('pa'))
        H_out.append(row)
        if not pos and B >= FLOOR['H']:
            dh_only.append(row)

    lists = {}
    defs = [('Starting pitchers', 'SP', lambda r: r['group'] == 'SP'), ('Relief pitchers', 'RP', lambda r: r['group'] == 'RP'), ('Catchers', 'H', lambda r: 'C' in r['pos']),
            ('First base', 'H', lambda r: '1B' in r['pos']), ('Second base', 'H', lambda r: '2B' in r['pos']), ('Third base', 'H', lambda r: '3B' in r['pos']), ('Shortstop', 'H', lambda r: 'SS' in r['pos']),
            ('All infielders', 'H', lambda r: set(r['pos']) & set(INF)), ('Left field', 'H', lambda r: 'LF' in r['pos']), ('Center field', 'H', lambda r: 'CF' in r['pos']), ('Right field', 'H', lambda r: 'RF' in r['pos']), ('All outfielders', 'H', lambda r: set(r['pos']) & set(OF))]
    for nm, g, test in defs:
        src = [r for r in (H_out if g == 'H' else P_out) if test(r)]
        lists[nm] = {}
        for hz, key, mult in (('2027', 'B', 1), ('2027-2029', 'v3', 3), ('2027-2031', 'v5', 5)):
            lists[nm][hz] = end_list(src, key, FLOOR[g] * mult)
    out = dict(lists=lists, dh_only=dh_only, all_h=H_out, all_p=P_out)
    tmp = os.path.join(P, '_fa_position_rankings.json.tmp')
    json.dump(out, open(tmp, 'w'), indent=0, default=float); os.replace(tmp, os.path.join(P, '_fa_position_rankings.json'))
    path = os.path.join(DL, 'fa_position_rankings_2027.csv')
    with open(path + '.tmp', 'w', newline='') as fh:
        w = csv.writer(fh); w.writerow(['list', 'horizon', 'rank', 'mlbId', 'player', 'age_2027', 'value_WAR', 'war_2027', 'war_2027_2029', 'war_2027_2031', 'rate_full_season', 'positions', 'thin_age', 'note'])
        for nm, hs in lists.items():
            for hz, rows in hs.items():
                key = {'2027': 'B', '2027-2029': 'v3', '2027-2031': 'v5'}[hz]
                for n, r in enumerate(rows, 1):
                    w.writerow([nm, hz, n, r['mlbId'], r['name'], r['age'], f'{r[key]:.2f}', f"{r['B']:.2f}", f"{r['v3']:.2f}", f"{r['v5']:.2f}", f"{r['rate']:.2f}", ' '.join(r['pos']), r['thin'], r.get('rate_note', '')])
    os.replace(path + '.tmp', path)
    for nm, hs in lists.items():
        print(f'\n== {nm}')
        for hz, rows in hs.items():
            key = {'2027': 'B', '2027-2029': 'v3', '2027-2031': 'v5'}[hz]
            print(f'  {hz} ({len(rows)}): ' + ', '.join(f"{r['name'].split(',')[0]}{'*' if r.get('rate_note') else ''} {r[key]:.1f}" for r in rows))
    print('\nno position list, above the floor: ' + ', '.join(f"{r['name']} {r['B']:.2f}" for r in dh_only))


if __name__ == '__main__':
    main()
