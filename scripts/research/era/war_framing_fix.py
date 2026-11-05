"""war_framing_fix.py: remove catcher framing from pitcher hdWAR so it is counted once (2026-11-04). Research only.

hwar_component_scale.py: club RA reads about 0 per catcher run with pitcher RAA in the model and about -1.4 without it, because framed
strikes sit in the pitcher's K and BB and xwOBA against carries them. Fix tested here, in the WAR step only (hdERA unchanged):

    RAA' = RAA - c x F        rate' = rate + c x F x 9 / (WAR_RAA_SCALE x IP) for the forecast tests

Two forms of F, pitcher-positive framing runs:
  club  club Savant framing (FRV 'framing'), spread to pitchers by batters faced per club. Removes the catcher's part and keeps what a
        pitcher earns within the staff. Needs nothing per pitch, so production could read it from the FRV pull.
  own   framing received per pitcher (war_improve_battery2.framing, Loc+ called-strike surface, per pitch). Also removes any edge the
        pitcher earns himself. The sheets and caches carry no catcher id, so the catcher part cannot be split out per pitch.

Rules written before the run:
  c       Solve by the club test: the framing slope in club RA ~ praa' + nonc + frame + catch_o + park should read -1 (one framing run is one
          run on the scoreboard, once). Sweep c 0..1.5. Settled only when the sweep crosses -1 inside the grid.
  guard   The pitcher slope must stay within 2 SE of its value at c = 0. Rmse cannot decide: the reparameterisation leaves it unchanged by c.
  harm    Honest next-season and rest-of-season r (base gate only, target weighted) on the raw target and on a framing-neutral target. A form
          ships only if it does not LOSE by the war_forecast_honest rule (gap over 2 SE and 4/5 or 5/6). A forecast win is not required: hdWAR is descriptive.
Who owns the credit is a convention. This test shows the amount counted twice, not the owner.
Usage: python3 scripts/research/era/war_framing_fix.py build YEAR (one per process), then python3 scripts/research/era/war_framing_fix.py run
Output: data/_war_honest/framing_YEAR.pkl, console + data/_war_honest/framing_fix.json
"""
import contextlib, gc, io, json, os, pickle, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'hitter')); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'projection'))
D = os.path.join(ROOT, 'data'); OUT = os.path.join(D, '_war_honest')


def build(y):
    import war_improve_battery2 as B2
    nm = B2.name_map(y)
    if y == 2026:
        R = pickle.load(open(os.path.join(D, 'all_pitches_rs_cache.pkl'), 'rb')); pitches = [p for p in R if p.get('_source', 'MLB') == 'MLB']; del R; gc.collect()
    else:
        pitches = B2.base.adapt(os.path.join(ROOT, B2.CACHE[y]))
    fr = {k: dict(v) for k, v in B2.framing(y, pitches, nm).items()}
    tmp = os.path.join(OUT, f'framing_{y}.pkl.tmp')
    with open(tmp, 'wb') as f:
        pickle.dump(fr, f)
    os.replace(tmp, os.path.join(OUT, f'framing_{y}.pkl'))
    v = [x['full'] for x in fr.values()]
    print(f'{y}: {len(fr)} arms, sum {sum(v):.1f}, sd {np.std(v):.2f}, max {max(v):.1f}, min {min(v):.1f}', flush=True)


def run():
    from pipeline.eraplus import WAR_RAA_SCALE
    import war_forecast_honest as PH
    import war_rate_validation as W
    import hwar_component_scale as C
    SEASONS = C.SEASONS; FULL = PH.FULL; TAB = PH.TAB; res = {}
    OWN = {y: pickle.load(open(os.path.join(OUT, f'framing_{y}.pkl'), 'rb')) for y in SEASONS}
    idx = {(r['y'], r['club']): r for r in C.ROWS}

    # club framing -> pitchers by batters faced per club; own -> clubs by the same shares
    FCLUB = {}
    for y in SEASONS:
        _, p = C.shares(y); tot = defaultdict(float)
        for pid, s in p.items():
            for c, n in s.items():
                tot[c] += n
        F = defaultdict(float)
        for pid, s in p.items():
            for c, n in s.items():
                if (y, c) in idx and tot[c] > 0:
                    F[pid] += idx[(y, c)].get('frame', 0.0) * n / tot[c]
                    o = OWN[y].get(pid)
                    if o:
                        idx[(y, c)]['own'] = idx[(y, c)].get('own', 0.0) + o['full'] * n / sum(s.values())
        FCLUB[y] = dict(F)
    print('== VALIDATE: club sum of framing received (own) against club Savant framing')
    res['validate'] = {}
    for y in SEASONS:
        g = [r for r in C.ROWS if r['y'] == y]; a = np.array([r.get('own', 0.0) for r in g]); b = np.array([r.get('frame', 0.0) for r in g])
        sl = np.polyfit(b, a, 1)[0]; rr = np.corrcoef(a, b)[0, 1]; print(f'  {y}: r {rr:.3f}, own per Savant run {sl:.2f}, sd own {a.std():.1f}, sd Savant {b.std():.1f}'); res['validate'][y] = dict(r=float(rr), slope=float(sl))
    ol = [v['full'] for y in SEASONS for k, v in OWN[y].items() if v['takes'] > 0]
    print('  reliability of own framing per take, h1 v h2, base 30+ IP each half: ', end='')
    rr = []
    for y in SEASONS:
        xs, ys_ = [], []
        for pid, v in OWN[y].items():
            t = TAB[y].get(pid)
            if t and (t['h1'].get('outs') or 0) >= 90 and (t['h2'].get('outs') or 0) >= 90:
                xs.append(v['h1'] * 27 / t['h1']['outs']); ys_.append((v['full'] - v['h1']) * 27 / t['h2']['outs'])
        rr.append(float(np.corrcoef(xs, ys_)[0, 1]))
    print(' '.join(f'{v:.2f}' for v in rr) + f'  mean {np.mean(rr):.3f} (the 09-05 note read .43)'); res['own_rel'] = rr

    print('\n== PITCHER RAA ON FRAMING, club level, season intercepts (a full double count reads about +1)')
    for k in ('frame', 'own'):
        x, y_ = [], []
        for y in SEASONS:
            g = [r for r in C.ROWS if r['y'] == y]; a = np.array([r.get(k, 0.0) for r in g]); b = np.array([r['praa'] for r in g]); x += list(a - a.mean()); y_ += list(b - b.mean())
        x, y_ = np.array(x), np.array(y_); b = (x * y_).sum() / (x * x).sum(); se = np.sqrt(((y_ - b * x) ** 2).sum() / (len(x) - 7) / (x * x).sum()); print(f'  {k:6s} {b:+.2f} +/- {se:.2f}'); res[f'praa_on_{k}'] = dict(b=float(b), se=float(se))

    print('\n== c SWEEP, club test. Framing slope should read -1; the guard is the pitcher slope')
    GRID = [0, .25, .5, .75, .9, 1.0, 1.1, 1.25, 1.5]; res['sweep'] = {}
    for form in ('frame', 'own'):
        print(f'  F = {"club Savant framing" if form == "frame" else "own framing received"}; framing column = {form}')
        out = []
        for c in GRID:
            for r in C.ROWS:
                r['p_c'] = r['praa'] - c * r.get(form, 0.0)
            with contextlib.redirect_stdout(io.StringIO()):
                f = C.fit('ra', ['p_c', 'nonc', form, 'catch_o', 'park'])
                w = C.fit('wab', ['bat', 'bsr', 'nonc', form, 'catch_o', 'p_c', 'park'], scale={'bat', 'bsr', 'nonc', form, 'catch_o', 'p_c', 'park'})
            s = f['slopes']; out.append(dict(c=c, frame=s[form]['b'], se=s[form]['se'], per=s[form]['per'], p=s['p_c']['b'], p_se=s['p_c']['se'], rmse=f['rmse'], w_frame=w['slopes'][form]['b'], w_se=w['slopes'][form]['se'], w_p=w['slopes']['p_c']['b']))
            print(f"    c {c:4}: framing {s[form]['b']:+.2f} +/- {s[form]['se']:.2f}  pitcher {s['p_c']['b']:+.2f} +/- {s['p_c']['se']:.2f}  rmse {f['rmse']:.1f} | wins: framing {w['slopes'][form]['b']:+.2f} +/- {w['slopes'][form]['se']:.2f}, pitcher {w['slopes']['p_c']['b']:+.2f}")
        res['sweep'][form] = out
        a = [o['frame'] for o in out]; cross = None
        for i in range(len(GRID) - 1):
            if (a[i] + 1) * (a[i + 1] + 1) <= 0:
                cross = GRID[i] + (GRID[i + 1] - GRID[i]) * (-1 - a[i]) / (a[i + 1] - a[i])
        print(f'    crossing of -1: c = {cross}  (per season, c that zeroes the gap: ' + ' '.join(f"{(-1 - out[0]['per'][j]) / (out[1]['per'][j] - out[0]['per'][j]) * .25:.2f}" for j in range(len(SEASONS))) + ')')
        res['sweep'][form + '_cross'] = cross

    print('\n== HARM: honest forecast, A = fixed rate, B = shipped rate')

    def add(y, pid, rate, c, form, half=False):
        if rate is None:
            return np.nan
        t = TAB[y][pid]; ip = (t['h1'].get('outs') or 0) / 3 if half else t['outs'] / 3
        if ip <= 0:
            return rate
        if form == 'club':
            F = FCLUB[y].get(pid, 0.0) * (ip / (t['outs'] / 3))
        else:
            o = OWN[y].get(pid); F = (o['h1'] if half else o['full']) if o else 0.0
        return rate + c * F * 9 / (WAR_RAA_SCALE * ip)

    npool = PH.next_pool(30); n60 = PH.next_pool(60); rpool, rtab = PH.ros_pool(); res['harm'] = {}

    def neutral(pool):
        o = {}
        for y in pool:
            t = []
            for p, v in zip(pool[y]['ids'], pool[y]['y']):
                tt = TAB[y + 1][p]; t.append(v + FCLUB[y + 1].get(p, 0.0) * 9 / (tt['outs'] / 3))
            o[y] = t
        return o
    for form in ('club', 'own'):
        for c in (.5, 1.0):
            for lab, pool, need in (('next 30+', npool, 4), ('next 60+', n60, 4)):
                a = {y: [add(y, p, FULL[y][p]['hd'], c, form) for p in pool[y]['ids']] for y in pool}; b = PH.col(pool, FULL, 'hd'); y_, w_ = PH.ys(pool)
                q = PH.paired(a, b, y_, w_); PH.show(f'{form} c {c}, {lab}, raw', q, need, ('fix', 'ship')); res['harm'][f'{form}_{c}_{lab}_raw'] = q
                q = PH.paired(a, b, neutral(pool), w_); PH.show(f'{form} c {c}, {lab}, neutral target', q, need, ('fix', 'ship')); res['harm'][f'{form}_{c}_{lab}_neu'] = q
            a = {y: [add(y, p, rtab[y][p]['hd'], c, form, True) for p in rpool[y]['ids']] for y in rpool}; b = PH.col(rpool, rtab, 'hd'); y_, w_ = PH.ys(rpool)
            q = PH.paired(a, b, y_, w_); PH.show(f'{form} c {c}, rest of season, raw', q, 5, ('fix', 'ship')); res['harm'][f'{form}_{c}_ros'] = q
            yn = {y: [v + FCLUB[y].get(p, 0.0) * 9 / (TAB[y][p]['outs'] / 3) for p, v in zip(rpool[y]['ids'], rpool[y]['y'])] for y in rpool}
            q = PH.paired(a, b, yn, w_); PH.show(f'{form} c {c}, rest of season, neutral target', q, 5, ('fix', 'ship')); res['harm'][f'{form}_{c}_ros_neu'] = q

    print('\n== WHO MOVES, shipped 2026, club form, c = 1 (league recentered, so the pitcher pool is unchanged)')
    PL = C.PL; lp = {}
    for r in PL:
        t = str(r.get('team'))
        if t in ('ROC', 'AAA') or not r.get('mlbId') or r.get('hWAR') is None:
            continue
        if t.endswith('TM') or str(r['mlbId']) not in lp:
            lp[str(r['mlbId'])] = r
    rpw = C.PH.LG[2026]['rpw']; F = FCLUB[2026]; ids = [p for p in lp if p in TAB[2026]]; ipw = sum(TAB[2026][p]['outs'] for p in ids); per_out = sum(F.get(p, 0.0) for p in ids) / ipw
    d = {p: -(F.get(p, 0.0) - per_out * TAB[2026][p]['outs']) / rpw for p in ids}; o = sorted(ids, key=lambda p: d[p])
    print('  biggest losses: ' + '; '.join(f"{lp[p]['pitcher']} {lp[p]['team']} {lp[p]['hWAR']:.1f} {d[p]:+.2f}" for p in o[:8]))
    print('  biggest gains:  ' + '; '.join(f"{lp[p]['pitcher']} {lp[p]['team']} {lp[p]['hWAR']:.1f} {d[p]:+.2f}" for p in o[::-1][:8]))
    v = np.array(list(d.values())); print(f'  over {len(v)} pitchers: sd {v.std():.2f}, sum {v.sum():+.2f}, n moving .2+ {int((np.abs(v) >= .2).sum())}, .4+ {int((np.abs(v) >= .4).sum())}')
    g = sorted([r for r in C.ROWS if r['y'] == 2026], key=lambda r: r.get('frame', 0.0))
    from pipeline.utils import TEAM_ABBREV_TO_ID
    nm = {v: k for k, v in TEAM_ABBREV_TO_ID.items() if k != 'ROC'}
    print('  club framing runs, 2026: ' + ' '.join(f"{nm.get(r['club'], r['club'])} {r.get('frame', 0.0):+.0f}" for r in g[:4]) + ' ... ' + ' '.join(f"{nm.get(r['club'], r['club'])} {r.get('frame', 0.0):+.0f}" for r in g[-4:]))
    res['moves'] = dict(sd=float(v.std()), n2=int((np.abs(v) >= .2).sum()), n4=int((np.abs(v) >= .4).sum()))
    with open(os.path.join(OUT, 'framing_fix.json.tmp'), 'w') as f:
        json.dump(res, f, indent=1, default=float)
    os.replace(os.path.join(OUT, 'framing_fix.json.tmp'), os.path.join(OUT, 'framing_fix.json'))
    print('\nwrote data/_war_honest/framing_fix.json')


if __name__ == '__main__':
    if sys.argv[1] == 'build':
        build(int(sys.argv[2]))
    else:
        run()
