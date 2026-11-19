#!/usr/bin/env python3
"""hpera_location_refit.py — hpERA weights on the Loc+ release input.

Stuff+ v18 (pitcher hand in the model) is live and hpERA's weights were refit on
it (candidate 'hand-nolhp' of hpera_new_inputs_refit.py). The Loc+ release changes
the loc channel: production reads locPlusRaw, which becomes the pitcher's mean
LOCATION value (kernel 2 in / 0.12, count currency, minus the situation mean).
That input is `loc_new` in data/_era_new_inputs.json (hpera_location_input.py).

Same harness as hpera_new_inputs_refit.py (NEXT season, 5 replicates; REST of
season, 6; ERA relative to league; innings-weighted; held out by YEAR), same rows
for every arm. Stuff+ is the hand version in every arm; no hand term.

Arms: the loc channel is the shipped value ('s') or the release value ('n'),
shrunk toward league at N0 pitches before the z-score, N0 on a grid. The harness
constant is 170; production z-scores the UNSHRUNK value, which is N0 = 0 here.
  s@170   the input the live weights were fit on (the reference)
  n@N0    the release input
  noloc   no loc channel

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/era/hpera_location_refit.py
"""
import contextlib
import io
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hpera_new_inputs_refit as NR  # noqa: E402

HR, hr, ewf, TG, NEW, REST = NR.HR, NR.hr, NR.ewf, NR.TG, NR.NEW, NR.REST
OUT = os.path.join(hr.ROOT, 'data', '_hpera_location_refit.json')
GRID = (0, 40, 85, 170, 340, 680, 1360)
KEYS = {'s': ('loc_ship', 'n_loc'), 'n': ('loc_new', 'n_locnew')}
NEED = ('stuff_hand', 'loc_ship', 'loc_new')


def patch(loc_key, n_key):
    st, cl = {}, {}
    for y, pit in NEW.items():
        for pid, r in pit.items():
            s, c = {}, {}
            for sc in ('full', 'h1'):
                if f'stuff_hand_{sc}' in r:
                    s[f'stuff_{sc}'], s[f'n_{sc}'] = r[f'stuff_hand_{sc}'], r[f'n_stuff_{sc}']
                if f'{loc_key}_{sc}' in r:
                    c[f'loc_{sc}'], c[f'loc_n_{sc}'] = r[f'{loc_key}_{sc}'], r[f'{n_key}_{sc}']
            st.setdefault(y, {})[pid] = s
            cl.setdefault(y, {})[pid] = c
    ewf.STUFF, ewf.CMDLOC = st, cl


def build():
    n0_keep = ewf.N0['loc']
    reps = []
    try:
        for obj in ('next', 'ros'):
            for S in (range(2021, 2026) if obj == 'next' else range(2021, 2027)):
                scope = 'full' if obj == 'next' else 'h1'
                have = {pid for pid, r in NEW.get(str(S), {}).items() if all(f'{k}_{scope}' in r for k in NEED)}
                Zs = {}
                for kind, (lk, nk) in KEYS.items():
                    patch(lk, nk)
                    for n0 in GRID:
                        ewf.N0['loc'] = float(n0)
                        with contextlib.redirect_stdout(io.StringIO()):
                            Zs[f'{kind}@{n0}'] = ewf.shrunk_features(S, scope)
                            if kind == 's' and n0 == GRID[0]:
                                F = hr.base_features(S, scope)
                ty, tscope = (S + 1, 'full') if obj == 'next' else (S, 'h2')
                lg = HR.lg_era(ty, tscope)
                Z0 = Zs['s@170']
                rows = []
                for p, z in Z0.items():
                    f, t = F.get(p), hr.line(ty, p, tscope)
                    if p not in have or not f or not t or t['outs'] <= 0 or f['outs'] < HR.MIN_OUTS[obj]:
                        continue
                    if not all(c in z for c in ['stuff', 'loc'] + REST) or 'SIERA' not in f or 'hpERA' not in f:
                        continue
                    if not all('loc' in Zs[a].get(p, {}) for a in Zs):
                        continue
                    zz = {c: z[c] for c in REST}
                    zz['stuff_h'] = z['stuff']
                    for a in Zs:
                        zz[a] = Zs[a][p]['loc']
                    rows.append({'z': zz, 'ship': f['hpERA'], 'siera': f['SIERA'],
                                 'y': 27 * t['er'] / t['outs'] - lg, 'w': t['outs'] / 3})
                reps.append({'obj': obj, 'label': f"{obj} {S % 100}" + ('' if obj == 'ros' else f'->{(S + 1) % 100}'),
                             'years': {S, ty}, 'rows': rows})
    finally:
        ewf.N0['loc'] = n0_keep
    return reps


def main():
    cands = {'noloc': ['stuff_h'] + REST}
    for kind in KEYS:
        for n0 in GRID:
            cands[f'{kind}@{n0}'] = ['stuff_h', f'{kind}@{n0}'] + REST
    HR.CANDS.clear()
    HR.CANDS.update(cands)
    reps = build()
    print('replicates: ' + ', '.join(f"{rp['label']} n {len(rp['rows'])}" for rp in reps))
    rr = [np.corrcoef([r['z']['s@0'] for r in rp['rows']], [r['z']['n@0'] for r in rp['rows']])[0, 1] for rp in reps]
    print('r(shipped loc z, release loc z) per replicate: ' + ' '.join(f'{x:.2f}' for x in rr))
    arms = ['ship', 'SIERA'] + list(cands)
    res = HR.evaluate(reps, arms)
    out, REF = {}, 's@170'
    for obj in ('next', 'ros'):
        labels = [rp['label'] for rp in reps if rp['obj'] == obj]
        print(f'\n== {obj.upper()}: innings-weighted MSE of ERA relative to league, held out by year')
        print(f'   {"arm":<9s}{"MSE":>8s}{"r":>7s}{"vs " + REF:>10s}{"wins":>6s}{"z":>6s}   per replicate')
        b = np.array([res[REF][l][0] for l in labels])
        for a in arms:
            m = np.array([res[a][l][0] for l in labels])
            r = np.mean([res[a][l][1] for l in labels])
            d = m - b
            z = (d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))) if a != REF and d.std() > 0 else 0.0
            out[f'{obj}|{a}'] = {'mse': float(m.mean()), 'r': float(r), 'pct_vs_ref': float(100 * d.mean() / b.mean()),
                                 'wins': int((d < 0).sum()), 'n': len(labels), 'z': float(z)}
            print(f'   {a:<9s}{m.mean():>8.4f}{r:>7.3f}{100 * d.mean() / b.mean():>+9.2f}%{int((d < 0).sum()):>4d}/{len(labels)}{z:>+6.1f}   '
                  + ' '.join(f'{x:.3f}' for x in m))
    final = {a: dict(zip(['intercept'] + cands[a], [float(x) for x in HR.fit(reps, a)])) for a in cands}
    print('\nweights fit on every replicate (ERA per z unit):')
    for a, dd in final.items():
        print(f'   {a:<9s} ' + ' '.join(f'{k if "@" not in k else "loc"} {v:+.3f}' for k, v in dd.items() if k != 'intercept'))
    out['final'] = final
    tmp = OUT + '.tmp'
    json.dump(out, open(tmp, 'w'), indent=1)
    os.replace(tmp, OUT)
    print(f'\nwrote {OUT}')


if __name__ == '__main__':
    main()
