#!/usr/bin/env python3
"""Tune the zone x count impact-page constants for SD+ / CT+ hitter pages.

2026-11-19: the SD+ cells follow shipped SD+, which is mix-neutral over
(zone, two-strike flag). The math lives in sd_impact_cells.py (shared with
render_sd_zones_impact.py). The two table-key formats were also brought up
to the shipped ones (SD 'zone|ALL|b-s', CT 'zone|cat|b-s'); this script
did not run on a current metadata file before that. Constants re-swept on
the full 2026 season the same day: see METRICS in the render tool.

v2 (2026-08-10): re-swept for the CARD-COHERENT cell formulas after Wally
rejected the v1 decomposition (it counted pitch diet / swing selection,
which the leaderboard metrics deliberately neutralize, so page and card
values disagreed). The v1 constants (SD k=0 lam=0.25, CT k=10 lam=0.75)
were tuned on the old formulas and do not carry over.

Cell formulas being tuned (both decompose the SHIPPED metric's own
aggregate, so the season page can sum to leaderboard value - 100):

  SD+ (diet-neutral, mirroring compute_hitter_sd's mix-neutral form):
      impact(z,st) = w_z_lg * [ s_h(st|z) * g'_h(z,st) - s_lg(st|z) * g_lg(z,st) ]
      w_z_lg = league share of zone z, s(st|z) = within-zone count-state
      share, g = mean decision atom (100 * dv / lg_mean_dv), g'_h shrunk
      toward g_lg with k pseudo-decisions. Zone diet is neutralized by
      construction (league zone weights on both sides); count mix and
      execution both count. A zone the hitter never visits contributes 0.

  CT+ (execution-only, mirroring raw_ct = sum(lev*I) / sum(lev*E)):
      impact(z,st) = 100 * shrink * sum_cell[lev * (I - E)] / T
      E = league contact expectation (1 - p_whiff) for the pitch's cell,
      T = sum(lev * E) over ALL the hitter's swings, shrink = n/(n+k)
      (excess shrunk toward 0 = league). Swing selection contributes 0 by
      construction. T is a per-hitter constant, so Pearson objectives are
      invariant to it.

Sweep 1 (shrinkage k): even/odd pitch split per (hitter, team, category)
unit; correlate the shrunk 15-cell impact vector from half A with the raw
(k=0) vector from half B, both directions, averaged. Sweep 2 (callout
lam): SEDISC score = sign(imp) * max(0, |imp| - lam * SE); objective =
EXPECTED realized raw-impact spread of top-2/bottom-2 picks in the
opposite half (no-pick pages score 0 — the conditional spread is gameable
by coverage collapse).

Units are capped so MLB tuning halves match a ROC season's per-category
volume (tuning at larger n than production favors too little shrinkage).

Usage: python3 scripts/tools/sdzone_impact_sweeps.py
"""
import json
import math
import os
import pickle
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sd_impact_cells as SDC  # noqa: E402
from pipeline.sdplus import (  # noqa: E402
    is_eligible, classify_zone, classify_decision, get_count, cat_of,
)
from pipeline.contact import is_ct_eligible, classify_contact_outcome  # noqa: E402

ZONES = ['heart', 'shadow_in', 'shadow_out', 'chase', 'waste']
STATES = ['ahead', 'even', 'behind']
CELLS = [(z, s) for z in ZONES for s in STATES]

SD_MIN, SD_CAP = 250, 800
CT_MIN, CT_CAP = 120, 400
K_GRID = [0, 5, 10, 20, 40, 80, 160, 320, 640]
LAM_GRID = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]


def count_state_hitter(p):
    c = get_count(p)
    if c is None:
        return None
    b, s = c
    return 'ahead' if b > s else ('behind' if s > b else 'even')


def pearson(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return num / (da * db) if da > 0 and db > 0 else None


# ── SD machinery ────────────────────────────────────────────────────────
# The math is sd_impact_cells.py (stratified by the two-strike flag, as
# shipped SD+ is). An atom is (value, zone, state, two).

sd_league = SDC.sd_league
sd_cell_agg = SDC.sd_cell_agg


def sd_impact_vector(acc, lg, k):
    cells = SDC.sd_cells_from_acc(acc, lg, k)
    return [cells[c]['impact'] for c in CELLS]


def sd_se(acc, lg, cell):
    return SDC.sd_cells_from_acc(acc, lg, 0)[cell]['se']


# ── CT machinery ────────────────────────────────────────────────────────
# per-pitch tuple: (e, var, z, st) with e = lev*(I-E), var = lev^2*E*(1-E).
# Impact in sweep units: shrink * sum(e) per cell (T cancels in Pearson;
# for the lam sweep, SEs and impacts share the same unit).

def ct_cell_agg(pitches):
    acc = defaultdict(lambda: [0.0, 0.0, 0])   # [sum_e, sum_var, n]
    for e, var, z, st in pitches:
        c = acc[(z, st)]
        c[0] += e
        c[1] += var
        c[2] += 1
    return acc


def ct_impact_vector(acc, k):
    out = []
    for cell in CELLS:
        s_e, _v, n = acc.get(cell, [0.0, 0.0, 0])
        out.append((n / (n + k)) * s_e if n else 0.0)
    return out


# ── Sweeps ──────────────────────────────────────────────────────────────

def sweep_k(tag, units, vec_fn):
    print(f'--- {tag}: shrinkage k sweep ({len(units)} units) ---')
    results = []
    for k in K_GRID:
        corrs = []
        for u in units:
            half_a, half_b = u['halves']
            for x, y in ((vec_fn(half_a, u, k), vec_fn(half_b, u, 0)),
                         (vec_fn(half_b, u, k), vec_fn(half_a, u, 0))):
                c = pearson(x, y)
                if c is not None:
                    corrs.append(c)
        mean_r = sum(corrs) / len(corrs)
        results.append((k, mean_r))
        print(f'  k={k:>4}  cross-half predictive r={mean_r:.4f}')
    best = max(results, key=lambda kr: kr[1])
    interior = results[0][1] < best[1] and results[-1][1] < best[1]
    print(f'  best on grid: k={best[0]} (r={best[1]:.4f}) — '
          + ('interior optimum bracketed' if interior else
             ('boundary optimum at k=0 (k<0 undefined)' if best[0] == 0
              else 'EDGE — extend the grid')) + '\n')
    return best[0]


def sweep_lam(tag, hitter_dirs, k_display):
    """hitter_dirs: list of (rows_a, b_map) where rows_a carry
    {'grp','cell','imp','se'} at k_display and b_map maps (grp, cell) to
    the raw k=0 impact in the opposite half."""
    print(f'--- {tag}: callout SE-discount sweep (k_display={k_display}) ---')
    results = []
    for lam in LAM_GRID:
        spreads = []
        for rows_a, b_map in hitter_dirs:
            scored = []
            for r in rows_a:
                d = abs(r['imp']) - lam * r['se']
                sc = math.copysign(max(0.0, d), r['imp']) if d > 0 else 0.0
                scored.append((sc, r))
            pos = sorted((x for x in scored if x[0] > 0), key=lambda x: -x[0])[:2]
            neg = sorted((x for x in scored if x[0] < 0), key=lambda x: x[0])[:2]
            vp = [b_map.get((r['grp'], r['cell'])) for _, r in pos]
            vn = [b_map.get((r['grp'], r['cell'])) for _, r in neg]
            vp = [v for v in vp if v is not None]
            vn = [v for v in vn if v is not None]
            spreads.append((sum(vp) / len(vp) - sum(vn) / len(vn))
                           if (vp and vn) else 0.0)
        exp_sp = sum(spreads) / len(spreads)
        n_made = sum(1 for s in spreads if s != 0.0)
        results.append((lam, exp_sp, n_made))
        print(f'  lam={lam:>4}: expected realized spread {exp_sp:.3f} '
              f'(picks on {n_made}/{len(hitter_dirs)} directions)')
    best = max(results, key=lambda r: r[1])
    interior = results[0][1] < best[1] and results[-1][1] < best[1]
    print(f'  best on grid: lam={best[0]} (expected spread {best[1]:.3f}) — '
          + ('interior optimum bracketed'
         if interior else 'EDGE — extend the grid') + '\n')
    return best[0]


def cap_unit(ps, cap):
    if len(ps) <= cap:
        return ps
    half = ps[0::2] + ps[1::2]
    return half[:cap]


def main():
    print('Loading cache + tables ...')
    with open(os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl'), 'rb') as f:
        allp = pickle.load(f)
    meta = json.load(open(os.path.join(ROOT, 'data', 'metadata_rs.json')))
    sdw, ctw = meta['sdPlusWeights'], meta['ctPlusWeights']

    mlb = [p for p in allp if p.get('_source', 'MLB') == 'MLB' and is_eligible(p)]

    def dv(p):
        # SD+ cells are category-collapsed since 2026-08-15 ('ALL' key)
        z, c = classify_zone(p), get_count(p)
        s = sdw[f'{z}|ALL|{c[0]}-{c[1]}|swing']['rv']
        t = sdw[f'{z}|ALL|{c[0]}-{c[1]}|take']['rv']
        return (s - t) if classify_decision(p) == 'swing' else (t - s)

    lg_mean_dv = sum(dv(p) for p in mlb) / len(mlb)

    # ── SD units ──
    lg_atoms = defaultdict(list)
    by_unit = defaultdict(list)
    by_hitter = defaultdict(lambda: defaultdict(list))
    for p in mlb:
        st = count_state_hitter(p)
        if st is None:
            continue
        a = 100.0 * dv(p) / lg_mean_dv
        z, grp = classify_zone(p), cat_of(p)
        two = 1 if get_count(p)[1] == 2 else 0
        lg_atoms[grp].append((a, z, st, two))
        by_unit[(p.get('Batter'), p.get('BTeam'), grp)].append((a, z, st, two))
        by_hitter[(p.get('Batter'), p.get('BTeam'))][grp].append((a, z, st, two))
    sd_lg = {g: sd_league(v) for g, v in lg_atoms.items()}

    sd_units = []
    for (_h, _t, grp), ps in by_unit.items():
        if len(ps) >= SD_MIN:
            ps = cap_unit(ps, SD_CAP)
            sd_units.append({'grp': grp,
                             'halves': (sd_cell_agg(ps[0::2]),
                                        sd_cell_agg(ps[1::2]))})

    def sd_vec(acc, u, k):
        return sd_impact_vector(acc, sd_lg[u['grp']], k)

    k_sd = sweep_k('SD', sd_units, sd_vec)

    sd_dirs = []
    for _key, grps in by_hitter.items():
        capped = {g: cap_unit(ps, SD_CAP) for g, ps in grps.items()
                  if len(ps) >= SD_MIN}
        if not capped:
            continue
        halves = [({g: sd_cell_agg(ps[0::2]) for g, ps in capped.items()},
                   {g: sd_cell_agg(ps[1::2]) for g, ps in capped.items()}),
                  ({g: sd_cell_agg(ps[1::2]) for g, ps in capped.items()},
                   {g: sd_cell_agg(ps[0::2]) for g, ps in capped.items()})]
        for ha, hb in halves:
            rows_a = []
            for g, acc in ha.items():
                vec = sd_impact_vector(acc, sd_lg[g], k_sd)
                for cell, imp in zip(CELLS, vec):
                    rows_a.append({'grp': g, 'cell': cell, 'imp': imp,
                                   'se': sd_se(acc, sd_lg[g], cell)})
            b_map = {}
            for g, acc in hb.items():
                for cell, imp in zip(CELLS, sd_impact_vector(acc, sd_lg[g], 0)):
                    b_map[(g, cell)] = imp
            sd_dirs.append((rows_a, b_map))
    sweep_lam('SD', sd_dirs, k_sd)

    # ── CT units ──
    mlb_sw = [p for p in mlb if is_ct_eligible(p)]

    def ct_tuple(p):
        # cat3 key format since 2026-08-15 (zone|cat|b-s)
        cell = ctw[f'{classify_zone(p)}|{cat_of(p)}|{get_count(p)[0]}-{get_count(p)[1]}']
        lev = cell['rv_contact'] - cell['rv_whiff']
        E = 1.0 - cell['p_whiff']
        made = 1.0 if classify_contact_outcome(p) == 'contact' else 0.0
        st = count_state_hitter(p)
        return (lev * (made - E), lev * lev * E * (1 - E),
                classify_zone(p), st)

    ct_by_unit = defaultdict(list)
    ct_by_hitter = defaultdict(lambda: defaultdict(list))
    for p in mlb_sw:
        t = ct_tuple(p)
        if t[3] is None:
            continue
        grp = cat_of(p)
        ct_by_unit[(p.get('Batter'), p.get('BTeam'), grp)].append(t)
        ct_by_hitter[(p.get('Batter'), p.get('BTeam'))][grp].append(t)

    ct_units = []
    for (_h, _t, grp), ps in ct_by_unit.items():
        if len(ps) >= CT_MIN:
            ps = cap_unit(ps, CT_CAP)
            ct_units.append({'grp': grp,
                             'halves': (ct_cell_agg(ps[0::2]),
                                        ct_cell_agg(ps[1::2]))})

    def ct_vec(acc, _u, k):
        return ct_impact_vector(acc, k)

    k_ct = sweep_k('CT', ct_units, ct_vec)

    ct_dirs = []
    for _key, grps in ct_by_hitter.items():
        capped = {g: cap_unit(ps, CT_CAP) for g, ps in grps.items()
                  if len(ps) >= CT_MIN}
        if not capped:
            continue
        halves = [({g: ct_cell_agg(ps[0::2]) for g, ps in capped.items()},
                   {g: ct_cell_agg(ps[1::2]) for g, ps in capped.items()}),
                  ({g: ct_cell_agg(ps[1::2]) for g, ps in capped.items()},
                   {g: ct_cell_agg(ps[0::2]) for g, ps in capped.items()})]
        for ha, hb in halves:
            rows_a = []
            for g, acc in ha.items():
                for cell in CELLS:
                    s_e, s_v, n = acc.get(cell, [0.0, 0.0, 0])
                    shrink = n / (n + k_ct) if (n + k_ct) else 0.0
                    rows_a.append({'grp': g, 'cell': cell,
                                   'imp': shrink * s_e,
                                   'se': shrink * math.sqrt(s_v)})
            b_map = {}
            for g, acc in hb.items():
                for cell, imp in zip(CELLS, ct_impact_vector(acc, 0)):
                    b_map[(g, cell)] = imp
            ct_dirs.append((rows_a, b_map))
    sweep_lam('CT', ct_dirs, k_ct)


if __name__ == '__main__':
    main()
