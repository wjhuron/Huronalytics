"""wed_hpera.py - WAR/ERA deep dive, tests 11, 21, 22: hpERA against the public estimators on honest pools,
an exit-velocity / launch baseline in the FRA style, and role-dependent shrinkage.

Harness: scripts/research/era/hpera_location_refit.py (NEXT season, 5 replicates; REST of season, 6; ERA relative
to league; target-innings weighted; no target gate; held out by YEAR). Stuff+ is the v18 hand series and Loc+ the
released far-miss series, unshrunk, as production reads them.
  benchmark   ship (hpERA as shipped), SIERA, xFIP, FIP, K-BB%, ERA: each one column with a held-out calibration
  base        the shipped channel set refit (stuff, loc, k, izwh, xrv, gb, gs_share, park)
  +ev         + average exit velocity allowed (shrunk N0 100 BIP)        public idea: FRA = K-BB%, EV, LA
  +ev+air     + EV and fly-ball share (the launch-angle part)
  fra         K-BB% (k, bb), EV, GB% only: the public baseline rebuilt on this harness
  +bb         + walk rate
  +thinrole   + thinness x role columns for K and xRV: what a role-specific shrink target would add
PYTHONHASHSEED=0 .venv/bin/python scripts/research/war_era_deep_dive/wed_hpera.py"""
import sys, os, io, contextlib, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'era'))
with contextlib.redirect_stdout(io.StringIO()):
    import hpera_location_refit as LR
HR, hr, ewf, REST = LR.HR, LR.hr, LR.ewf, LR.REST
N0_EV = 100.0


def zmap(vals, wts=None):
    k = list(vals); v = np.array([vals[i] for i in k], float); return dict(zip(k, (v - v.mean()) / v.std()))


def build():
    kind = 'f' if 'f' in LR.KEYS else 'n'; LR.patch(*LR.KEYS[kind]); ewf.N0['loc'] = 0.0
    reps = []
    for obj in ('next', 'ros'):
        for S in (range(2021, 2026) if obj == 'next' else range(2021, 2027)):
            scope = 'full' if obj == 'next' else 'h1'
            with contextlib.redirect_stdout(io.StringIO()):
                Z = ewf.shrunk_features(S, scope); F = hr.base_features(S, scope); raw = ewf.raw_features(S, scope)
            bat = ewf.BATTERY[str(S)]
            pool = [p for p in Z if p in bat and bat[p][scope].get('ev') is not None and bat[p][scope].get('bip')]
            lg_ev = sum(bat[p][scope]['ev'] * bat[p][scope]['bip'] for p in pool) / sum(bat[p][scope]['bip'] for p in pool)
            zev = zmap({p: (bat[p][scope]['ev'] * bat[p][scope]['bip'] + N0_EV * lg_ev) / (bat[p][scope]['bip'] + N0_EV) for p in pool})
            pf = [p for p in pool if bat[p][scope].get('fb_pct') is not None]
            lg_fb = sum(bat[p][scope]['fb_pct'] * bat[p][scope]['bip'] for p in pf) / sum(bat[p][scope]['bip'] for p in pf)
            zfb = zmap({p: (bat[p][scope]['fb_pct'] * bat[p][scope]['bip'] + 55 * lg_fb) / (bat[p][scope]['bip'] + 55) for p in pf})
            gsm = np.mean([Z[p]['gs_share'] for p in Z if 'gs_share' in Z[p]])
            ty, tscope = (S + 1, 'full') if obj == 'next' else (S, 'h2'); lg = HR.lg_era(ty, tscope); rows = []
            for p, z in Z.items():
                f, t = F.get(p), hr.line(ty, p, tscope)
                if not f or not t or t['outs'] <= 0 or f['outs'] < HR.MIN_OUTS[obj]:
                    continue
                if not all(c in z for c in ['stuff', 'loc', 'bb'] + REST) or p not in zev or p not in zfb or any(k not in f for k in ('SIERA', 'hpERA', 'xFIP', 'FIP', 'K-BB%', 'ERA')):
                    continue
                r = raw[p]; zz = {c: z[c] for c in REST + ['stuff', 'loc', 'bb']}
                zz['ev'], zz['fb'] = zev[p], zfb[p]
                zz['thin_k'] = (ewf.N0['k'] / (r['bf'] + ewf.N0['k'])) * (z['gs_share'] - gsm)
                zz['thin_x'] = (ewf.N0['xrv'] / (r['pitches'] + ewf.N0['xrv'])) * (z['gs_share'] - gsm)
                row = {'z': zz, 'ship': f['hpERA'], 'siera': f['SIERA'], 'y': 27 * t['er'] / t['outs'] - lg, 'w': t['outs'] / 3}
                for k in ('xFIP', 'FIP', 'K-BB%', 'ERA'):
                    zz['raw_' + k] = f[k]
                rows.append(row)
            reps.append({'obj': obj, 'label': f"{obj} {S % 100}" + ('' if obj == 'ros' else f'->{(S + 1) % 100}'), 'years': {S, ty}, 'rows': rows})
    return reps


def main():
    base = ['stuff', 'loc'] + REST
    cands = {'xFIP': ['raw_xFIP'], 'FIP': ['raw_FIP'], 'K-BB%': ['raw_K-BB%'], 'ERA': ['raw_ERA'], 'base': base, '+ev': base + ['ev'], '+ev+air': base + ['ev', 'fb'],
             'fra': ['k', 'bb', 'ev', 'gb'], '+bb': base + ['bb'], '+thinrole': base + ['thin_k', 'thin_x'], '+ev+bb': base + ['ev', 'bb']}
    HR.CANDS.clear(); HR.CANDS.update(cands)
    reps = build(); print('replicates: ' + ', '.join(f"{rp['label']} n {len(rp['rows'])}" for rp in reps))
    arms = ['ship', 'SIERA'] + list(cands); res = HR.evaluate(reps, arms); out = {}
    for obj in ('next', 'ros'):
        labels = [rp['label'] for rp in reps if rp['obj'] == obj]; b = np.array([res['base'][l][0] for l in labels]); s = np.array([res['SIERA'][l][0] for l in labels])
        print(f"\n== {obj.upper()}: target-innings-weighted MSE of ERA relative to league, held out by year")
        print(f"   {'arm':<10s}{'MSE':>8s}{'r':>7s}  vs base (SE; better in)        vs SIERA (better in)")
        for a in arms:
            m = np.array([res[a][l][0] for l in labels]); r = np.mean([res[a][l][1] for l in labels]); d = (m - b) / b; e = (m - s) / s
            print(f"   {a:<10s}{m.mean():>8.4f}{r:>7.3f}  {100*d.mean():+6.2f}% (SE {100*d.std(ddof=1)/np.sqrt(len(d)):.2f}; {int((d < 0).sum())}/{len(d)})     {100*e.mean():+6.2f}% ({int((e < 0).sum())}/{len(e)})")
            out[f'{obj}|{a}'] = dict(mse=float(m.mean()), r=float(r), vs_base=float(d.mean()), vs_siera=float(e.mean()))
    print("\nweights fit on every replicate (ERA per z unit):")
    for a in ('base', '+ev', '+ev+air', 'fra', '+bb', '+thinrole'):
        be = HR.fit(reps, a); print(f"   {a:<10s} " + " ".join(f"{k} {v:+.3f}" for k, v in zip(cands[a], be[1:])))
    json.dump(out, open(os.path.join(ROOT, 'data', '_wed', 'res_hpera.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
