#!/usr/bin/env python3
"""stuff_gate_target_audit.py — does the Stuff+ gate's verdict depend on the
TARGET it is graded against? (2026-09-17)

Every gate v2 adoption was decided on nxt_r: the pitcher's year-Y grade
against his year-Y+1 LUCK-NEUTRAL xRV mean. That target is modelled (xwOBA
on balls in play). The gate also logged nxt_rv_r, the same grade against
year-Y+1 ACTUAL run value (rv_raw, luck included), but never put a standard
error on it, so no verdict was ever read on it.

This script refits nothing. It re-reads what the gate already cached:

  TIER A  the per-pitcher aggregate pickles (agg_<variant>_<Y>_s<seed>.pkl)
          in data/_gate_v2 and its two archive folders. Each folder has its
          own SHIPPED baseline (the config shipped when it ran). For every
          variant, both targets get the gate's own statistic: delta r vs
          SHIPPED per pair (mean over common seeds), a PAIRED pitcher
          bootstrap SE on seed 0, the seed SD in quadrature, pooled over the
          pairs. Both targets are scored on the SAME resamples, so a
          contrast between the two deltas has an SE too.
          The contrast is NOT d_rv - d_t. Actual RV is the luck-neutral
          target plus noise, so if that noise is unrelated to the grades,
          r(grade, rv) = rho * r(grade, t) with rho = r(t, rv) over the same
          pitchers, and every delta shrinks by rho on the rv target. The
          test of "the target changes the verdict" is the EXCESS
          d_rv - rho * d_t (rho re-estimated inside every resample), which is
          zero under pure attenuation.
  TIER B  variants that survive only as lines in the 2026-08-23 run logs
          (no pickles). Per-pair deltas on both targets, wins, and the
          between-pair SE (sd of the pair deltas / sqrt k). No bootstrap.

WITHIN HAND (added the same day). nxt_r pools the hands, so a feature that
only shifts one hand's level wins it without ranking anyone better. Every
Tier A variant is also scored on G.wh_delta: grade and target demeaned
within hand, same bootstrap, plus the delta inside each hand. Written to
the 'within_hand' block of the output.

Validation, printed before any result: the 't' bootstrap SE recomputed here
must equal the se_boot_raw the gate stored in results.json, and a Tier B
delta parsed from run_hclip.log must equal the same delta from its pickle.

Usage:
  python3 scripts/research/stuff/stuff_gate_target_audit.py
"""
import glob
import json
import os
import re
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stuff_gate_v2 as G                               # noqa: E402

CACHE = G.CACHE
OUT = os.path.join(CACHE, 'target_audit.json')
# folder -> the config its SHIPPED baseline was, for the report only
FOLDERS = (('old_2026_08_23', 'v13/v14 session, 2026-08-23'),
           ('pre_0908_v14', 'v14/v15 sessions, 2026-09-02..05'),
           ('', 'v15 + location term frames, 2026-09-08'))
UNITS = (('raw', 's'), ('rend', 's_r'))
TARGETS = (('t', 'luck-neutral xRV'), ('rv', 'actual RV'))
SEED_REFS = tuple(n for n in G.SEED_REFS if n != 'SHIPPED')


def table(agg):
    """nxt_table without the column list: the 08-23 pickles have no tadj."""
    j = agg['py'].join(agg['py1'], lsuffix='_y', rsuffix='_y1', how='inner')
    return j[(j['n_y'] >= G.MIN_NXT) & (j['n_y1'] >= G.MIN_NXT)]


def _r(x, y):
    x = x - x.mean(1, keepdims=True)
    y = y - y.mean(1, keepdims=True)
    return (x * y).sum(1) / np.sqrt((x * x).sum(1) * (y * y).sum(1))


def boot(a, b):
    """Paired bootstrap of r(a.s, target) - r(b.s, target) for both targets
    and both units on ONE set of resamples. The first draw from
    default_rng(0) is the draw G.boot_delta uses for its 'raw' grade, so the
    ('raw', 't') SE reproduces the gate's stored value."""
    j = a.join(b, lsuffix='_a', rsuffix='_b', how='inner')
    m = len(j)
    idx = np.random.default_rng(0).integers(0, m, size=(G.BOOT_B, m))
    out = {}
    for u, col in UNITS:
        if f'{col}_a' not in j or f'{col}_b' not in j:
            continue                    # 08-23 pickles have no rendered unit
        sa = j[f'{col}_a'].values.astype(float)[idx]
        sb = j[f'{col}_b'].values.astype(float)[idx]
        d = {}
        for tg, _ in TARGETS:
            t = j[f'{tg}_a'].values.astype(float)[idx]
            d[tg] = _r(sa, t) - _r(sb, t)
            out[(u, tg)] = float(d[tg].std())
        rho = _r(j['t_a'].values.astype(float)[idx], j['rv_a'].values.astype(float)[idx])
        out[(u, 'diff')] = float((d['rv'] - rho * d['t']).std())
    return out, m


def point(tb):
    out = {(u, tg): G.pear(tb[col], tb[tg])
           for u, col in UNITS if col in tb for tg, _ in TARGETS}
    out['rho'] = G.pear(tb['t'], tb['rv'])
    return out


def folder_variants(path):
    names = {}
    for p in glob.glob(os.path.join(path, 'agg_*_s*.pkl')):
        m = re.match(r'agg_(.+)_(\d{4})_s(\d+)\.pkl$', os.path.basename(p))
        names.setdefault(m.group(1), {}).setdefault(int(m.group(2)), {})[int(m.group(3))] = p
    return names


def pool(d, se, seed_sd, m_seeds):
    d, se, m_seeds = np.asarray(d), np.asarray(se), np.asarray(m_seeds)
    k = len(d)
    se_c = np.sqrt(se ** 2 + seed_sd ** 2 / m_seeds)
    sc = float(np.sqrt((se_c ** 2).sum()) / k)
    sp = float(d.std(ddof=1) / np.sqrt(k)) if k > 1 else float('nan')
    return {'mean_d': float(d.mean()), 'se_comb': sc, 'z': float(d.mean() / sc),
            'se_pairs': sp, 'wins': int((d > 0).sum()), 'k': k}


def tier_a():
    res = {}
    for sub, label in FOLDERS:
        path = os.path.join(CACHE, sub)
        V = folder_variants(path)
        if 'SHIPPED' not in V:
            continue
        rows = {}           # name -> Y -> per-pair record
        for name in sorted(V):
            if name == 'SHIPPED':
                continue
            for Y in sorted(V[name]):
                seeds = sorted(set(V[name][Y]) & set(V['SHIPPED'].get(Y, {})))
                if not seeds:
                    continue
                per_seed = []
                for s in seeds:
                    pa = point(table(pd.read_pickle(V[name][Y][s])))
                    pb = point(table(pd.read_pickle(V['SHIPPED'][Y][s])))
                    dd = {k: pa[k] - pb[k] for k in pa if k in pb and k != 'rho'}
                    for u, _ in UNITS:          # excess over pure attenuation
                        if (u, 't') in dd:
                            dd[(u, 'diff')] = dd[(u, 'rv')] - pa['rho'] * dd[(u, 't')]
                    dd['rho'] = pa['rho']
                    per_seed.append(dd)
                s0 = seeds[0]
                se, n = boot(table(pd.read_pickle(V[name][Y][s0])),
                             table(pd.read_pickle(V['SHIPPED'][Y][s0])))
                rows.setdefault(name, {})[Y] = dict(
                    seeds=seeds, per_seed=per_seed, se=se, n=n,
                    d={k: float(np.mean([p[k] for p in per_seed])) for k in per_seed[0]})
        # seed SD per (unit, target, and the rv - t difference), RMS over
        # pairs and reference configs, as G.seed_sd does for 't'
        var = {}
        for name in SEED_REFS:
            for Y, rec in rows.get(name, {}).items():
                if len(rec['seeds']) < 2:
                    continue
                for u, _ in UNITS:
                    if (u, 't') not in rec['per_seed'][0]:
                        continue
                    for tg in ('t', 'rv'):
                        var.setdefault((u, tg), []).append(
                            np.var([p[(u, tg)] for p in rec['per_seed']], ddof=1))
                    var.setdefault((u, 'diff'), []).append(
                        np.var([p[(u, 'diff')] for p in rec['per_seed']], ddof=1))
        ssd = {k: float(np.sqrt(np.mean(v))) for k, v in var.items()}
        res[sub or 'current'] = dict(label=label, rows=rows, seed_sd=ssd)
    # a folder with single-seed runs only borrows the seed SD of the folder
    # that has three-seed references (said in the report)
    donor = next((r['seed_sd'] for r in res.values() if r['seed_sd']), {})
    for r in res.values():
        r['seed_sd_borrowed'] = not r['seed_sd']
        if not r['seed_sd']:
            r['seed_sd'] = donor
    return res


LINE = re.compile(r'^\s+([A-Z0-9_]+)\s+s(\d+)\s.*\|\s+nxt (?:raw )?([\d.]+).*?nxt_rv ([\d.]+)')


def parse_log(fn):
    out, Y = {}, None
    for ln in open(os.path.join(CACHE, fn)):
        m = re.match(r'=== pair (\d{4})->', ln)
        if m:
            Y = int(m.group(1))
            continue
        m = LINE.match(ln)
        if m and Y:
            out.setdefault(m.group(1), {}).setdefault(Y, {})[int(m.group(2))] = (
                float(m.group(3)), float(m.group(4)))
    return out


def tier_b():
    """The 2026-08-23 session. run_protocol.log carries SHIPPED at seed 0 and
    run_combo.log carries it at seed 1 (same v13 config, same day), so those
    three logs share one seed-matched baseline. run_hclip.log ran after v14
    shipped and carries its own SHIPPED."""
    session = {}
    for fn in ('run_protocol.log', 'run_combo.log'):
        for Y, by_seed in parse_log(fn).get('SHIPPED', {}).items():
            session.setdefault(Y, {}).update(by_seed)
    res = {}
    for fn, base in (('run_protocol.log', session), ('run_features.log', session),
                     ('run_combo.log', session),
                     ('run_hclip.log', parse_log('run_hclip.log')['SHIPPED'])):
        for name, by in parse_log(fn).items():
            if name == 'SHIPPED':
                continue
            d_t, d_rv, seeds = [], [], set()
            for Y in sorted(by):
                common = sorted(set(by[Y]) & set(base[Y]))
                if not common:
                    raise SystemExit(f'{fn} {name} {Y}: no seed-matched SHIPPED line')
                d_t.append(float(np.mean([by[Y][s][0] - base[Y][s][0] for s in common])))
                d_rv.append(float(np.mean([by[Y][s][1] - base[Y][s][1] for s in common])))
                seeds |= set(common)
            res[f'{name}@{fn[4:-4]}'] = dict(years=sorted(by), d_t=d_t, d_rv=d_rv,
                                             seeds=sorted(seeds))
    return res


def within_hand():
    """Every Tier A variant on the within-hand twin of nxt_r (target t)."""
    res = {}
    blocks = []
    for sub, label in FOLDERS:
        V = folder_variants(os.path.join(CACHE, sub))
        if 'SHIPPED' not in V:
            continue
        rows = {}
        for name in sorted(V):
            if name == 'SHIPPED':
                continue
            for Y in sorted(V[name]):
                seeds = sorted(set(V[name][Y]) & set(V['SHIPPED'].get(Y, {})))
                if not seeds:
                    continue
                per = [G.wh_delta(table(pd.read_pickle(V[name][Y][s])),
                                  table(pd.read_pickle(V['SHIPPED'][Y][s])),
                                  Y, boot=(s == seeds[0])) for s in seeds]
                pooled = [point(table(pd.read_pickle(V[name][Y][s])))[('raw', 't')]
                          - point(table(pd.read_pickle(V['SHIPPED'][Y][s])))[('raw', 't')]
                          for s in seeds]
                rows.setdefault(name, {})[Y] = dict(per=per, seeds=seeds,
                                                    pooled=float(np.mean(pooled)))
        var = {}
        for name in SEED_REFS:
            for Y, rec in rows.get(name, {}).items():
                if len(rec['seeds']) >= 2:
                    for g, _ in G.WH_GRADES:
                        for k in (g, f'{g}_R', f'{g}_L'):
                            if f'd_{k}' in rec['per'][0]:
                                var.setdefault(k, []).append(
                                    np.var([w[f'd_{k}'] for w in rec['per']], ddof=1))
        blocks.append((sub or 'current', label, rows,
                       {g: float(np.sqrt(np.mean(v))) for g, v in var.items()}))
    donor = next((b[3] for b in blocks if b[3]), {})
    for sub, label, rows, ssd in blocks:
        borrowed = not ssd
        ssd = ssd or donor
        print(f'\n=== WITHIN HAND  {sub}: {label} ===')
        print('  seed SD' + (' (BORROWED)' if borrowed else '') + ': '
              + ', '.join(f'{g} {v:.4f}' for g, v in ssd.items()))
        for name, by in rows.items():
            ys = sorted(by)
            m = [len(by[Y]['seeds']) for Y in ys]
            rec = {'pooled_raw_mean_d': float(np.mean([by[Y]['pooled'] for Y in ys]))}
            for g, _ in G.WH_GRADES:
                if f'd_{g}' not in by[ys[0]]['per'][0]:
                    continue
                d = [float(np.mean([w[f'd_{g}'] for w in by[Y]['per']])) for Y in ys]
                rec[g] = pool(d, [by[Y]['per'][0][f'se_boot_{g}'] for Y in ys],
                              ssd.get(g, 0.0), m)
                for tag in ('R', 'L'):
                    dh = [float(np.mean([w[f'd_{g}_{tag}'] for w in by[Y]['per']])) for Y in ys]
                    rec[f'{g}_{tag}'] = pool(dh, [by[Y]['per'][0][f'se_boot_{g}_{tag}'] for Y in ys],
                                             ssd.get(f'{g}_{tag}', 0.0), m)
            w = rec['wh']
            print(f'  {name:<12} pooled {rec["pooled_raw_mean_d"]:+.4f} | within hand {fmt(w)} | '
                  f'RHP {rec["wh_R"]["mean_d"]:+.4f} z {rec["wh_R"]["z"]:+.1f} {rec["wh_R"]["wins"]}/{w["k"]}  '
                  f'LHP {rec["wh_L"]["mean_d"]:+.4f} z {rec["wh_L"]["z"]:+.1f} {rec["wh_L"]["wins"]}/{w["k"]}'
                  + (f' | rend {fmt(rec["wh_rend"])}' if 'wh_rend' in rec else ''))
            res[f'{sub}:{name}'] = rec
    return res


def fmt(p):
    return (f'{p["mean_d"]:+.4f} se {p["se_comb"]:.4f} z {p["z"]:+.1f} '
            f'{p["wins"]}/{p["k"]}')


def main():
    A = tier_a()
    # ── validation 1: reproduce the gate's stored bootstrap SE ───────────
    for sub, rj in (('pre_0908_v14', 'pre_0908_v14/results.json'), ('current', 'results.json')):
        stored = json.load(open(os.path.join(CACHE, rj)))['_summary']['variants']
        for name, blk in stored.items():
            for pr in blk['pairs']:
                mine = A[sub]['rows'][name][pr['Y']]
                print(f'VALIDATE {sub} {name} {pr["Y"]}: se_boot_raw stored '
                      f'{pr["se_boot_raw"]:.6f} here {mine["se"][("raw", "t")]:.6f} | '
                      f'd_raw stored {pr["d_raw"]:+.6f} here {mine["d"][("raw", "t")]:+.6f} | '
                      f'd_rv stored {pr["d_rv_raw"]:+.6f} here {mine["d"][("raw", "rv")]:+.6f}')
    B = tier_b()
    # ── validation 2: a log-parsed delta equals its pickle delta ─────────
    for name in ('NOHEIGHT', 'HCLIP80'):
        b = B[f'{name}@hclip']
        for Y, dt, drv in zip(b['years'], b['d_t'], b['d_rv']):
            a = A['old_2026_08_23']['rows'][name][Y]['d']
            print(f'VALIDATE log-vs-pickle {name} {Y}: d_t {dt:+.4f} vs {a[("raw", "t")]:+.4f} | '
                  f'd_rv {drv:+.4f} vs {a[("raw", "rv")]:+.4f}')

    out = {'tier_a': {}, 'tier_b': {}}
    for sub, blk in A.items():
        print(f'\n=== TIER A  {sub}: {blk["label"]} ===')
        any_rows = next(iter(blk['rows'].values()))
        print('  rho = r(t, rv) by pair: ' + ', '.join(
            f'{Y} {rec["d"]["rho"]:.3f}' for Y, rec in sorted(any_rows.items())))
        print('  seed SD' + (' (BORROWED: single-seed folder)' if blk['seed_sd_borrowed'] else '')
              + ': ' + ', '.join(f'{u}/{tg} {v:.4f}' for (u, tg), v in sorted(blk['seed_sd'].items())))
        for name, by in blk['rows'].items():
            for drop_partial in (False, True):
                ys = [Y for Y in sorted(by) if not (drop_partial and Y == G.PARTIAL_Y)]
                if drop_partial and len(ys) == len(by):
                    continue
                m = [len(by[Y]['seeds']) for Y in ys]
                rec = {}
                for u, _ in UNITS:
                    if (u, 't') not in by[ys[0]]['d']:
                        continue
                    for tg in ('t', 'rv'):
                        rec[f'{u}_{tg}'] = pool([by[Y]['d'][(u, tg)] for Y in ys],
                                                [by[Y]['se'][(u, tg)] for Y in ys],
                                                blk['seed_sd'].get((u, tg), 0.0), m)
                    rec[f'{u}_diff'] = pool(
                        [by[Y]['d'][(u, 'diff')] for Y in ys],
                        [by[Y]['se'][(u, 'diff')] for Y in ys],
                        blk['seed_sd'].get((u, 'diff'), 0.0), m)
                rec['rho'] = float(np.mean([by[Y]['d']['rho'] for Y in ys]))
                tag = name + (' [no 2025->26]' if drop_partial else '')
                rec['m_seeds'] = m
                print(f'  {tag:<26} raw: t {fmt(rec["raw_t"])} | rv {fmt(rec["raw_rv"])} | '
                      f'excess {fmt(rec["raw_diff"])}')
                if 'rend_t' in rec:
                    print(f'  {"":<26} rend: t {fmt(rec["rend_t"])} | rv {fmt(rec["rend_rv"])} | '
                          f'excess {fmt(rec["rend_diff"])}')
                out['tier_a'][f'{sub}:{tag}'] = rec
    # rho per pair for the 08-23 session, from that session's own pickles
    # (the targets do not depend on the variant)
    rho_y = {Y: rec['d']['rho'] for Y, rec in A['old_2026_08_23']['rows']['NOHEIGHT'].items()}
    print('\n=== TIER B  log-only variants (raw unit, no bootstrap; se = sd of pair deltas / sqrt k) ===')
    print('  rho by pair: ' + ', '.join(f'{Y} {v:.3f}' for Y, v in sorted(rho_y.items())))

    def pairs(x):
        x = np.asarray(x)
        se = float(x.std(ddof=1) / np.sqrt(len(x)))
        return dict(mean_d=float(x.mean()), se_pairs=se, z_pairs=float(x.mean() / se),
                    wins=int((x > 0).sum()), k=len(x))
    for key, b in B.items():
        dt, drv = np.array(b['d_t']), np.array(b['d_rv'])
        rho = np.array([rho_y[Y] for Y in b['years']])
        rec = dict(years=b['years'], seeds=b['seeds'], t=pairs(dt), rv=pairs(drv),
                   excess=pairs(drv - rho * dt))
        print(f'  {key:<22} ' + ' | '.join(
            f'{lab} {rec[k]["mean_d"]:+.4f} se {rec[k]["se_pairs"]:.4f} z {rec[k]["z_pairs"]:+.1f} '
            f'{rec[k]["wins"]}/{rec[k]["k"]}' for lab, k in (('t', 't'), ('rv', 'rv'), ('excess', 'excess'))))
        out['tier_b'][key] = rec
    out['within_hand'] = within_hand()
    tmp = OUT + '.tmp'
    json.dump(out, open(tmp, 'w'), indent=1)
    os.replace(tmp, OUT)
    print(f'\nwrote {OUT}')


if __name__ == '__main__':
    main()
