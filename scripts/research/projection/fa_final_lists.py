"""fa_final_lists.py: the free-agent lists by position, hpWAR Full 2027, hpWAR 2027, hpWAR 3yr and hpWAR 5yr, on the most accurate forecast tested (per Wally 2026-11-05). Research only.

Reads ~/Downloads/fa_rundown_2027_{hitters,pitchers}.csv (rebuild them first), the shipped data/hpwar_projections.json, and the fits in _fa_rank_blend.json (hitters) and _pit_clean_blend.json (pitchers).
  Full 2027   blended rate at a full season: 600 PA, 180 IP or 60 IP.
  2027        expected total WAR. A pitcher's total reads his start share.
  3yr, 5yr    cumulative expected WAR over 2027-2029 and 2027-2031, a missed season counted as 0: BQA for hitters, M2 for starters, M1 for relievers.
Blend: hitters total_blend_FA, starters even ours + Steamer on RA9 (ZiPS replaces a 1 IP Steamer placeholder, ours alone without ZiPS; a convention: placeholder ERA correlates .32 with ZiPS against .61 elsewhere), relievers even ours + ZiPS when ZiPS has him relieving.
Lists: a pitcher lists as a starter at start share .5 or more, or at .3 or more when Steamer or ZiPS also has him starting (a convention). A swingman on the starter list carries a starter-role rate and does not list as a reliever.
Eligibility at a position: 25 percent of fielding innings and 150 innings, 2024-2026 weighted (a convention). Full lists leave out the rows the site blanks for small samples.
List ends (conventions): 2027, 3yr, 5yr: .2 WAR per season, relievers .1; Full 2027: 1.0 per 600 PA or 180 IP, .3 per 60 IP. Over 30 listed, the largest drop between ranks 15 and 30.
Usage: python3 scripts/research/projection/fa_final_lists.py
Output: data/_proj/_fa_final_lists.json
"""
import csv, json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE))); sys.path.insert(0, HERE)
import pos_assignment_test as pat
P = os.path.join(ROOT, 'data', '_proj'); DL = os.path.expanduser('~/Downloads')
FLOOR = {'H': .2, 'SP': .2, 'RP': .1}; FULL = {'H': 1.0, 'SP': 1.0, 'RP': .3}
H_FIT = json.load(open(os.path.join(P, '_fa_age_band_fit.json')))   # BQA on every hitter (fa_age_band_test.py part 4): M2 ran 13-18% high for productive hitters 31-34
P_FIT = json.load(open(os.path.join(P, '_pit_clean_blend.json')))['part3']
f = lambda x: float(x) if x not in ('', None) else None


def m2(c, B, R, a): return c[0] + B * (c[1] + c[2] * a) + R * (c[3] + c[4] * a) + c[5] * a
def m1(c, B, a): return c[0] + B * (c[1] + c[2] * a)
def bqa(c, B, R, a): return m2(c, B, R, a) + c[6] * B * B + c[7] * B * B * a + c[8] * B * max(a, 0) ** 2


def lb(name):
    d = json.load(open(os.path.join(ROOT, 'data', name))); rows = d if isinstance(d, list) else next(iter(d.values())); out = {}
    for r in rows:
        i = r.get('mlbId'); k = r.get('pa') or r.get('tbf') or 0
        if i is not None and r.get('team') not in ('ROC', 'AAA') and (i not in out or k > (out[i].get('pa') or out[i].get('tbf') or 0)):
            out[int(i)] = r
    return out


def end_list(rows, key, floor):
    rows = sorted([r for r in rows if r.get(key) is not None], key=lambda r: -r[key]); keep = [r for r in rows if r[key] >= floor]
    if len(keep) <= 30:
        return keep
    v = [r[key] for r in keep]; return keep[:max((v[i - 1] - v[i], i) for i in range(15, 30))[1]]


def main():
    meta = json.load(open(os.path.join(ROOT, 'data', 'metadata_rs.json'))); wc = meta['eraPlusConstants']['war']; rpw = meta['hwarConstants']['rpw']; lg = wc['lgRA9']
    hp = json.load(open(os.path.join(ROOT, 'data', 'hpwar_projections.json'))); LH, LP = lb('hitter_leaderboard_rs.json'), lb('pitcher_leaderboard_rs.json')
    pp = {int(r['mlbId']): r for r in csv.DictReader(open(os.path.join(P, 'projections_pitchers.csv')))}
    z = {int(r['xMLBAMID']): r for r in json.load(open(os.path.join(P, 'fg', 'zips_2027_pit.json'))) if r.get('xMLBAMID')}; st = {int(r['xMLBAMID']): r for r in json.load(open(os.path.join(P, 'fg', 'steamer_2027_pit.json'))) if r.get('xMLBAMID')}
    is_rel = lambda r: float(r.get('GS') or 0) < .5 * float(r.get('G') or 1)
    pool = [(v['hpWAR'] / 60, float(z[int(k)]['WAR']) / float(z[int(k)]['IP']), v['pt']) for k, v in hp['pitchers'].items() if v.get('unit') == 'RP60' and v.get('hpWAR') is not None and (v.get('pt') or 0) > 0 and int(k) in z and float(z[int(k)].get('IP') or 0) >= 5 and is_rel(z[int(k)])]
    a = np.array(pool); d_z = float(np.average(a[:, 0], weights=a[:, 2]) - np.average(a[:, 1], weights=a[:, 2]))
    rows_p = list(csv.DictReader(open(os.path.join(DL, 'fa_rundown_2027_pitchers.csv'))))
    ds = [f(r['RA9_blend']) - .5 * (f(r['RA9_site']) + f(r['steamer_ERA_raw'])) for r in rows_p if f(r['RA9_blend']) is not None and f(r['steamer_ERA_raw']) is not None]; d_p = 2 * float(np.median(ds))
    sp_pool = [(float(pp[int(k)]['RA9_SP_2027']), float(z[int(k)]['ERA']), v['pt']) for k, v in hp['pitchers'].items() if v.get('unit') == 'SP180' and (v.get('pt') or 0) > 0 and int(k) in z and z[int(k)].get('ERA') is not None and int(k) in pp]
    a = np.array(sp_pool); d_ze = float(np.average(a[:, 0], weights=a[:, 2]) - np.average(a[:, 1], weights=a[:, 2]))
    print(f'centering: ZiPS reliever WAR per 60 {d_z * 60:+.3f}, Steamer ERA {d_p:+.3f}, ZiPS ERA {d_ze:+.3f}')
    P_all = []
    for r in rows_p:
        i = int(r['mlbId']); v = hp['pitchers'].get(str(i)); ipt = f(r['IP_site'])
        if not v or ipt is None or i not in pp or not pp[i].get('RA9_SP_2027'):
            continue
        age = int(r['age_2027']); ag = age - 30.0; sh = v.get('share', 1.0 if v['unit'] == 'SP180' else 0.0); L = LP.get(i, {})
        sp_, rp_ = float(pp[i]['RA9_SP_2027']), float(pp[i]['RA9_RP_2027']); ev = dict(mlbId=i, name=r['name'], age=age, status=r['status'], thin=v.get('thin') or '', ip=ipt, share=round(sh, 2), low=bool(v.get('low')), era=L.get('era'), hpERA=L.get('hpERA'), hdWAR=L.get('hWAR'), fWAR=L.get('fWAR'), ip26=L.get('ip'), stuff=L.get('stuffScore'), kbb=L.get('kbbPct'), gs=L.get('gs'), g=L.get('g'), site_tot=v.get('tot'), site_full=None if v.get('low') else v.get('hpWAR'))
        sera = f(st[i].get('ERA')) if i in st else None; sip = f(st[i].get('IP')) if i in st else 0.0; zr = z.get(i)
        s_ok = sera is not None and sip > 1.5
        rel_sys = (zr is not None and float(zr.get('IP') or 0) >= 5 and is_rel(zr))
        start_sys = (zr is not None and not is_rel(zr) and float(zr.get('GS') or 0) >= 5) or (i in st and sip > 1.5 and f(st[i].get('G')) and f(st[i].get('GS')) / f(st[i].get('G')) >= .5)
        other = sera + d_p if s_ok else (float(zr['ERA']) + d_ze if zr is not None and zr.get('ERA') is not None else None)
        def ra_blend(x):
            return .5 * x + .5 * other if other is not None else x
        rep_sh = wc['replRp'] + sh * (wc['replSp'] - wc['replRp'])
        tot_sp = ((lg - ra_blend(rp_ + sh * (sp_ - rp_))) / rpw + rep_sh) * ipt / 9
        rate_sp = (lg - ra_blend(sp_)) * 20 / rpw + wc['replSp'] * 20
        if v['unit'] == 'SP180' or (sh >= .3 and start_sys):
            c3, c5 = P_FIT['SP_3']['coef']['M2'], P_FIT['SP_5']['coef']['M2']
            P_all.append(dict(ev, group='SP', pos=['SP'], rate=rate_sp, B=tot_sp, v3=m2(c3, tot_sp, rate_sp, ag), v5=m2(c5, tot_sp, rate_sp, ag), mark='^' if v['unit'] != 'SP180' else ''))
        if v['unit'] == 'RP60' and not (sh >= .3 and start_sys):
            ours_r = ((lg - rp_) / rpw + wc['replRp']) / 9; ours_sh = ((lg - (rp_ + sh * (sp_ - rp_))) / rpw + rep_sh) / 9
            zrate = float(zr['WAR']) / float(zr['IP']) + d_z if rel_sys else None
            rt = .5 * ours_r + .5 * zrate if zrate is not None else ours_r; rt_sh = .5 * ours_sh + .5 * zrate if zrate is not None else ours_sh
            R, B = rt * 60, rt_sh * ipt
            P_all.append(dict(ev, group='RP', pos=['RP'], rate=R, B=B, v3=m1(P_FIT['RP_3']['coef']['M1'], B, ag), v5=m1(P_FIT['RP_5']['coef']['M1'], B, ag), mark=''))
    INN = {y: pat.innings(y) for y in (2024, 2025, 2026)}; H_all = []; no_pos = []
    for r in csv.DictReader(open(os.path.join(DL, 'fa_rundown_2027_hitters.csv'))):
        i = int(r['mlbId']); B, R = f(r['total_blend_FA']), f(r['hpWAR600_blend_FA']); v = hp['hitters'].get(str(i)) or {}
        if B is None or R is None:
            continue
        age = int(r['age_2027']); ag = age - 30.0; L = LH.get(i, {}); sh = {}
        for k, y in enumerate((2026, 2025, 2024)):
            for p_, x in (INN[y].get(i) or {}).items():
                sh[p_] = sh.get(p_, 0.0) + .3 ** k * x
        fld = {p_: x for p_, x in sh.items() if p_ != 'DH'}; tot = sum(fld.values())
        pos = [p_ for p_, x in sorted(fld.items(), key=lambda t: -t[1]) if tot and x / tot >= .25 and x >= 150]
        row = dict(mlbId=i, name=r['name'], age=age, status=r['status'], group='H', pos=pos, rate=R, B=B, pa=f(r['PA_FA']), thin=r['thin_age'], low=bool(v.get('low')), v3=bqa(H_FIT['H_3']['coef'], B, R, ag), v5=bqa(H_FIT['H_5']['coef'], B, R, ag), mark='', wOBA=L.get('wOBA'), xwOBA=L.get('xwOBA'), hdWAR=L.get('hWAR'), fWAR=L.get('fWAR'), fld=L.get('hFldRuns'), processPlus=L.get('processPlus'), pa26=L.get('pa'), site_tot=v.get('tot'), site_full=None if v.get('low') else v.get('hpWAR'))
        H_all.append(row)
        if not pos and B >= FLOOR['H']:
            no_pos.append(row)
    INF, OF = {'1B', '2B', '3B', 'SS'}, {'LF', 'CF', 'RF'}
    defs = [('Starting pitchers', 'SP', lambda r: True), ('Relief pitchers', 'RP', lambda r: True), ('Catchers', 'H', lambda r: 'C' in r['pos']), ('First base', 'H', lambda r: '1B' in r['pos']), ('Second base', 'H', lambda r: '2B' in r['pos']), ('Third base', 'H', lambda r: '3B' in r['pos']), ('Shortstop', 'H', lambda r: 'SS' in r['pos']), ('All infielders', 'H', lambda r: set(r['pos']) & INF), ('Left field', 'H', lambda r: 'LF' in r['pos']), ('Center field', 'H', lambda r: 'CF' in r['pos']), ('Right field', 'H', lambda r: 'RF' in r['pos']), ('All outfielders', 'H', lambda r: set(r['pos']) & OF)]
    L = {}
    for nm, g, t in defs:
        src = [r for r in (H_all if g == 'H' else P_all) if r['group'] == g and t(r)]
        L[nm] = {'Full 2027': end_list([r for r in src if not r['low']], 'rate', FULL[g]), '2027': end_list(src, 'B', FLOOR[g]), '3yr': end_list(src, 'v3', FLOOR[g] * 3), '5yr': end_list(src, 'v5', FLOOR[g] * 5)}
    tmp = os.path.join(P, '_fa_final_lists.json.tmp'); json.dump(dict(lists=L, no_pos=no_pos, all=H_all + P_all), open(tmp, 'w'), default=float); os.replace(tmp, os.path.join(P, '_fa_final_lists.json'))
    K = {'Full 2027': 'rate', '2027': 'B', '3yr': 'v3', '5yr': 'v5'}
    for nm, hs in L.items():
        print(f'\n== {nm}')
        for h, rows in hs.items():
            print(f'  {h} ({len(rows)}): ' + ', '.join(f"{r['name'].split(',')[0]}{r.get('mark', '')} {r[K[h]]:.2f}" for r in rows))
    print('\nno position list: ' + ', '.join(f"{r['name']} {r['B']:.2f}" for r in no_pos))


if __name__ == '__main__':
    main()
