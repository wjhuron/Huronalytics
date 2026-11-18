#!/usr/bin/env python3
"""hpera_new_inputs_refit.py — does hpERA forecast better on the candidate Stuff+
and Loc+ definitions of 2026-11-18?

Same design as hpera_honest_refit.py (its fit and evaluate are imported): two
objectives on honest pools, NEXT season and REST of season, target = ERA relative
to league, innings-weighted, held out by YEAR. Only the inputs change
(data/_era_new_inputs.json, built by hpera_new_inputs_build.py):

  stuff_b  shipped-feature Stuff+        stuff_h  Stuff+ with pitcher hand as a feature
  loc_s    shipped Loc+ value            loc_l    location part (count-currency pricing)
                                         sit      situation part (shipped pricing)
Each is shrunk and z-scored by era_weights_final.shrunk_features exactly as the
shipped stuff and loc channels are (N0 15 and 170); the other channels are the
harness's own. A pitcher enters only when every new input exists for the scope,
so every candidate is scored on the same rows.

Candidates (fixed before the run):
  base        stuff_b + loc_s + the six other channels + lhp     (the shipped channel set)
  base-nolhp  the same without the hand term
  hand        stuff_h in place of stuff_b, lhp kept
  hand-nolhp  stuff_h, no hand term      <- "the hand level moved into Stuff+"
  split       loc_l + sit in place of loc_s
  loconly     loc_l only                 sitonly  sit only
  both        stuff_h + loc_l + sit, no hand term
  both+lhp    the same with the hand term
DECISION RULE (the harness's): a candidate replaces base only if it wins most
held-out replicates of BOTH objectives.

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/era/hpera_new_inputs_refit.py
"""
import contextlib
import io
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hpera_honest_refit as HR  # noqa: E402

hr, ewf, TG = HR.hr, HR.ewf, HR.TG
ROOT = hr.ROOT
NEW = json.load(open(os.path.join(ROOT, 'data', '_era_new_inputs.json')))
OUT = os.path.join(ROOT, 'data', '_hpera_new_inputs_refit.json')
REST = ['k', 'izwh', 'xrv', 'gb', 'gs_share', 'park']
CANDS = {
    'base': ['stuff_b', 'loc_s'] + REST + ['lhp'],
    'base-nolhp': ['stuff_b', 'loc_s'] + REST,
    'hand': ['stuff_h', 'loc_s'] + REST + ['lhp'],
    'hand-nolhp': ['stuff_h', 'loc_s'] + REST,
    'split': ['stuff_b', 'loc_l', 'sit'] + REST + ['lhp'],
    'loconly': ['stuff_b', 'loc_l'] + REST + ['lhp'],
    'sitonly': ['stuff_b', 'sit'] + REST + ['lhp'],
    'both': ['stuff_h', 'loc_l', 'sit'] + REST,
    'both+lhp': ['stuff_h', 'loc_l', 'sit'] + REST + ['lhp'],
    # the Pitcher+ component set (no role, park or hand term), same targets: a stand-in for
    # the Pitcher+ refit, whose own harness targets future xRV/100 on split halves
    'pp-base': ['stuff_b', 'loc_s', 'k', 'izwh', 'xrv', 'gb'],
    'pp-hand': ['stuff_h', 'loc_s', 'k', 'izwh', 'xrv', 'gb'],
    'pp-split': ['stuff_b', 'loc_l', 'sit', 'k', 'izwh', 'xrv', 'gb'],
    'pp-both': ['stuff_h', 'loc_l', 'sit', 'k', 'izwh', 'xrv', 'gb'],
    'pp-hand-loconly': ['stuff_h', 'loc_l', 'k', 'izwh', 'xrv', 'gb'],
}
RUNS = (('base', 'loc_ship', 'stuff_b', 'loc_s'), ('hand', 'loc_part', 'stuff_h', 'loc_l'), ('base', 'sit', None, 'sit'))
NEED = ('stuff_base', 'stuff_hand', 'loc_ship', 'loc_part', 'sit')


def patch(stuff_arm, loc_key):
    st, cl = {}, {}
    for y, pit in NEW.items():
        for pid, r in pit.items():
            s, c = {}, {}
            for sc in ('full', 'h1'):
                if f'stuff_{stuff_arm}_{sc}' in r:
                    s[f'stuff_{sc}'], s[f'n_{sc}'] = r[f'stuff_{stuff_arm}_{sc}'], r[f'n_stuff_{sc}']
                if f'{loc_key}_{sc}' in r:
                    c[f'loc_{sc}'], c[f'loc_n_{sc}'] = r[f'{loc_key}_{sc}'], r[f'n_loc_{sc}']
            st.setdefault(y, {})[pid] = s
            cl.setdefault(y, {})[pid] = c
    ewf.STUFF, ewf.CMDLOC = st, cl


def build():
    reps = []
    for obj in ('next', 'ros'):
        for S in (range(2021, 2026) if obj == 'next' else range(2021, 2027)):
            scope = 'full' if obj == 'next' else 'h1'
            have = {pid for pid, r in NEW.get(str(S), {}).items() if all(f'{k}_{scope}' in r for k in NEED)}
            Zs = {}
            for stuff_arm, loc_key, sname, lname in RUNS:
                patch(stuff_arm, loc_key)
                with contextlib.redirect_stdout(io.StringIO()):
                    Z = ewf.shrunk_features(S, scope)
                    if sname == 'stuff_b':
                        F = hr.base_features(S, scope)
                Zs[(sname, lname)] = Z
            ty, tscope = (S + 1, 'full') if obj == 'next' else (S, 'h2')
            lg = HR.lg_era(ty, tscope)
            Z0 = Zs[('stuff_b', 'loc_s')]
            rows = []
            for p, z in Z0.items():
                f, t = F.get(p), hr.line(ty, p, tscope)
                if p not in have or not f or not t or t['outs'] <= 0 or f['outs'] < HR.MIN_OUTS[obj]:
                    continue
                if not all(c in z for c in ['stuff', 'loc'] + REST) or 'SIERA' not in f or 'hpERA' not in f:
                    continue
                zh, zs = Zs[('stuff_h', 'loc_l')].get(p, {}), Zs[(None, 'sit')].get(p, {})
                if 'stuff' not in zh or 'loc' not in zh or 'loc' not in zs:
                    continue
                zz = {c: z[c] for c in REST}
                zz.update(stuff_b=z['stuff'], loc_s=z['loc'], stuff_h=zh['stuff'], loc_l=zh['loc'], sit=zs['loc'],
                          lhp=1.0 if TG[str(S)]['pitchers'][p].get('hand') == 'L' else 0.0)
                rows.append({'z': zz, 'ship': f['hpERA'], 'siera': f['SIERA'],
                             'y': 27 * t['er'] / t['outs'] - lg, 'w': t['outs'] / 3})
            reps.append({'obj': obj, 'label': f"{obj} {S % 100}" + ('' if obj == 'ros' else f'->{(S + 1) % 100}'),
                         'years': {S, ty}, 'rows': rows})
    return reps


def main():
    HR.CANDS.clear()
    HR.CANDS.update(CANDS)
    reps = build()
    print('replicates: ' + ', '.join(f"{rp['label']} n {len(rp['rows'])}" for rp in reps))
    arms = ['ship', 'SIERA'] + list(CANDS)
    res = HR.evaluate(reps, arms)
    out = {}
    for obj in ('next', 'ros'):
        labels = [rp['label'] for rp in reps if rp['obj'] == obj]
        print(f'\n== {obj.upper()}: innings-weighted MSE of ERA relative to league, held out by year')
        print(f'   {"arm":<12s}{"MSE":>7s}{"r":>7s}{"vs base":>9s}{"wins":>6s}{"z":>6s}   per replicate')
        b = np.array([res['base'][l][0] for l in labels])
        for a in arms:
            m = np.array([res[a][l][0] for l in labels])
            r = np.mean([res[a][l][1] for l in labels])
            d = m - b
            z = (d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))) if a != 'base' and d.std() > 0 else 0.0
            out[f'{obj}|{a}'] = {'mse': float(m.mean()), 'r': float(r), 'pct_vs_base': float(100 * d.mean() / b.mean()),
                                 'wins': int((d < 0).sum()), 'n': len(labels), 'z': float(z)}
            print(f'   {a:<12s}{m.mean():>7.3f}{r:>7.3f}{100 * d.mean() / b.mean():>+8.1f}%{int((d < 0).sum()):>4d}/{len(labels)}{z:>+6.1f}   '
                  + ' '.join(f'{x:.3f}' for x in m))
    final = {a: dict(zip(['intercept'] + CANDS[a], [float(x) for x in HR.fit(reps, a)])) for a in CANDS}
    print('\nweights fit on every replicate (ERA per z unit; lhp per left-hander):')
    for a, dd in final.items():
        print(f'   {a:<12s} ' + ' '.join(f'{k} {v:+.3f}' for k, v in dd.items() if k != 'intercept'))
    out['final'] = final
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
