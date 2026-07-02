"""CT+ (Contact+) — per-swing contact-execution index.

Complements SD+ (decision quality) and BB+ (contact quality) to form an
orthogonal three-axis view of plate performance:
    SD+  — did you swing at the right pitch?
    CT+  — did you make contact when you swung, vs expectation?  (this file)
    BB+  — how good was the contact when you made it?

Raw metric: hitter's leverage-weighted ACTUAL contact over leverage-
weighted EXPECTED contact across the same swings:
    raw_ct = Σ (I[contact] × leverage[cell]) / Σ ((1 − p_whiff[cell]) × leverage[cell])
    leverage[cell] = rv_contact[cell] - rv_whiff[cell]
    p_whiff[cell]  = league whiff rate for that (zone × count) cell

League mean ≈ 1.0 by construction. ctPlus = 100 × raw_adj / league_adj
(BB+'s ratio-to-league convention still applies cleanly).

Why expected-contact in the denominator (2026-07-02 change): the previous
raw contact-rate form let swing selection leak in — chase-prone hitters
scored low CT+ partly through WHERE they swung, double-counting what SD+
already measures. Dividing by the league contact expectation for the same
swings removes the mix and leaves pure contact execution. Validated:
split-half r 0.60→0.67, stabilization n0 127→95 swings
(scripts/phase2_sdct_harness.py).

Why leverage weighting: 2-strike whiffs matter far more than 0-0 whiffs
because rv_whiff ≈ K (very negative) at 2K while a 0-0 whiff is just a
strike added. Heart-zone whiffs cost more than chase-zone whiffs because
rv_contact ≈ high xwOBA on heart contact. The (rv_contact - rv_whiff)
weighting makes high-stakes contact count more toward the hitter's score.

Cell RVs are count-anchored (build_bip_count_offsets) so BIP and whiff
values share the count-conditional delta-RE currency. The (zone × count)
cell structure was validated as approximately optimal at current samples —
pitch-type expansion added <1% residual variance.
"""
import math
from collections import defaultdict

from pipeline_utils import safe_float
from pipeline_sdplus import (
    classify_zone, classify_decision, get_count, is_eligible,
    make_rv_xrv, build_bip_count_offsets, ZONES, COUNTS,
)

# ── Hyperparameters ─────────────────────────────────────────────────────
CELL_SHRINK_K  = 50       # cell → zone shrinkage pseudo-swings
HITTER_PRIOR_N = 85       # hitter → league regression pseudo-swings.
                          #   Set to the metric's stabilization constant
                          #   n0 (~84 swings, measured via the split-half
                          #   reliability study). For a shrinkage estimator
                          #   adj=(n·obs+K·lg)/(n+K), the MMSE-optimal
                          #   pseudo-count is exactly K=n0. The old K=400
                          #   over-shrank ~4.7×, compressing ~55% of the
                          #   real between-hitter spread (SD 3.7 vs a true
                          #   ~6.5). Coherent with MIN_HITTER_SWINGS=85:
                          #   at the display floor the estimate is 50/50
                          #   own-data/league. Rank-preserving (ρ≈.999 vs
                          #   K=400); the qualified-pool re-anchor still
                          #   re-centers the median to 100 downstream.
MIN_HITTER_SWINGS = 85    # computation floor = split-half r=.50 point
                          #   (signal=noise). Measured directly via the
                          #   reliability study (n0~84 swings; model
                          #   prediction matched the measured crossing
                          #   exactly). Below this CT+ is majority noise.
                          #   Leaderboard qualification (3.1 × TGP) is a
                          #   separate, stricter gate applied downstream.

# ── Classification helpers ──────────────────────────────────────────────

def classify_contact_outcome(p):
    """Returns 'contact' / 'whiff' / None for swing pitches.

    Note: the scraper maps foul tips to 'Swinging Strike' upstream, so foul
    tips are counted as whiffs here — aligned with the K-risk reality.
    """
    desc = p.get('Description')
    if desc == 'Swinging Strike':
        return 'whiff'
    if desc in ('Foul', 'In Play'):
        return 'contact'
    return None


def is_ct_eligible(p):
    """CT+ sample: SD+-eligible pitches that were swings (take pitches
    excluded — no contact opportunity)."""
    if not is_eligible(p):
        return False
    if classify_decision(p) != 'swing':
        return False
    if classify_contact_outcome(p) is None:
        return False
    return True


# ── Weight table ────────────────────────────────────────────────────────

def build_contact_cell_weights(swings, rv_fn):
    """For each (zone, count) cell, compute:
        n_swings, n_whiff,
        p_whiff    — league whiff rate in cell
        rv_contact — mean hitter-perspective xRV on contact pitches
        rv_whiff   — mean hitter-perspective xRV on whiff pitches
    Returns dict keyed by (zone, count).
    """
    cells = defaultdict(lambda: {
        'n_swings': 0, 'n_whiff': 0,
        'sum_rv_contact': 0.0, 'sum_rv_whiff': 0.0,
    })
    for p in swings:
        zone = classify_zone(p)
        count = get_count(p)
        outcome = classify_contact_outcome(p)
        rv = rv_fn(p)
        if rv is None:
            continue
        c = cells[(zone, count)]
        c['n_swings'] += 1
        if outcome == 'whiff':
            c['n_whiff'] += 1
            c['sum_rv_whiff'] += rv
        else:  # contact
            c['sum_rv_contact'] += rv

    out = {}
    for key, c in cells.items():
        n_sw, n_wh = c['n_swings'], c['n_whiff']
        n_ct = n_sw - n_wh
        out[key] = {
            'n_swings':  n_sw,
            'n_whiff':   n_wh,
            'p_whiff':   (n_wh / n_sw) if n_sw else 0.0,
            'rv_contact': (c['sum_rv_contact'] / n_ct) if n_ct else 0.0,
            'rv_whiff':   (c['sum_rv_whiff']   / n_wh) if n_wh else 0.0,
        }
    return out


def zone_level_contact_means(swings, rv_fn):
    """Zone-level aggregates used as shrinkage priors for the cells."""
    zones = defaultdict(lambda: {
        'n_swings': 0, 'n_whiff': 0,
        'sum_rv_contact': 0.0, 'sum_rv_whiff': 0.0,
    })
    for p in swings:
        zone = classify_zone(p)
        outcome = classify_contact_outcome(p)
        rv = rv_fn(p)
        if rv is None:
            continue
        c = zones[zone]
        c['n_swings'] += 1
        if outcome == 'whiff':
            c['n_whiff'] += 1
            c['sum_rv_whiff'] += rv
        else:
            c['sum_rv_contact'] += rv

    out = {}
    for zone, c in zones.items():
        n_sw, n_wh = c['n_swings'], c['n_whiff']
        n_ct = n_sw - n_wh
        out[zone] = {
            'n_swings':   n_sw,
            'p_whiff':    (n_wh / n_sw) if n_sw else 0.0,
            'rv_contact': (c['sum_rv_contact'] / n_ct) if n_ct else 0.0,
            'rv_whiff':   (c['sum_rv_whiff']   / n_wh) if n_wh else 0.0,
        }
    return out


def shrink_contact_cells(raw, zone_means, k=CELL_SHRINK_K):
    """Continuous Bayesian shrinkage of each cell toward its zone prior,
    for all three quantities (p_whiff, rv_contact, rv_whiff). Handles
    empty/missing cells gracefully (fall back to zone mean, then to
    neutral default)."""
    DEFAULT = {'p_whiff': 0.25, 'rv_contact': 0.0, 'rv_whiff': -0.05,
               'n_swings': 0}
    smoothed = {}
    for zone in ZONES:
        zprior = zone_means.get(zone, DEFAULT)
        for count in COUNTS:
            key = (zone, count)
            cell = raw.get(key) or {
                'n_swings': 0, 'n_whiff': 0, 'p_whiff': 0.0,
                'rv_contact': 0.0, 'rv_whiff': 0.0,
            }
            n = cell['n_swings']
            def blend(cell_val, zone_val):
                denom = n + k
                return ((n * cell_val + k * zone_val) / denom) if denom else zone_val
            smoothed[key] = {
                'n_swings':   n,
                'n_whiff':    cell['n_whiff'],
                'p_whiff':    blend(cell['p_whiff'],   zprior['p_whiff']),
                'rv_contact': blend(cell['rv_contact'], zprior['rv_contact']),
                'rv_whiff':   blend(cell['rv_whiff'],   zprior['rv_whiff']),
            }
    return smoothed


# ── Per-swing leverage-weighted contact ─────────────────────────────────

def compute_ct_swing(p, table):
    """Return (leverage_weight, contact_indicator) for aggregating into a
    leverage-weighted contact rate. `contact_indicator` is 1 if the hitter
    made contact, 0 if whiff."""
    zone = classify_zone(p)
    count = get_count(p)
    cell = table[(zone, count)]
    leverage = cell['rv_contact'] - cell['rv_whiff']
    is_contact = 1 if classify_contact_outcome(p) == 'contact' else 0
    return leverage, is_contact


# ── Per-hitter aggregation ──────────────────────────────────────────────

def compute_hitter_ct(pitches_by_hitter, table):
    """Compute hitter's mix-adjusted contact ratio.
    raw_ct = Σ(I[contact] × lev) / Σ((1 − p_whiff_cell) × lev)   (~1.0 = league)
    Returns {(hitter, team) -> {raw_ct, n_swings, zone_dv}} where
    zone_dv[z] is the per-zone actual/expected contact ratio.
    """
    results = {}
    for key, pitches in pitches_by_hitter.items():
        swings = [p for p in pitches if is_ct_eligible(p)]
        if not swings:
            continue
        actual = 0.0     # Σ lev·I[contact]
        expected = 0.0   # Σ lev·(1 − p_whiff_cell): league contact given the SAME swings
        zone_accum = defaultdict(lambda: [0.0, 0.0])  # [actual, expected] per zone
        for p in swings:
            lev, con = compute_ct_swing(p, table)
            if lev <= 0:
                # Two waste-zone hitter's-count cells carry (slightly) negative
                # leverage in practice (contact there is worth less than the
                # ball a whiff would concede); zero-stakes swings drop out.
                continue
            cell = table[(classify_zone(p), get_count(p))]
            exp_con = lev * (1.0 - cell['p_whiff'])
            actual += lev * con
            expected += exp_con
            z = classify_zone(p)
            zone_accum[z][0] += lev * con
            zone_accum[z][1] += exp_con
        if expected <= 0:
            continue
        results[key] = {
            # Mix-adjusted contact ratio: leverage-weighted ACTUAL contact
            # over leverage-weighted EXPECTED contact for the same swings
            # (league p_whiff per cell). ~1.0 = league-average contact GIVEN
            # where/when this hitter swings — swing-selection differences no
            # longer leak in (they belong to SD+). Validated 2026-07-02:
            # split-half r 0.60→0.67, n0 127→95 swings vs the raw-rate form
            # (scripts/phase2_sdct_harness.py).
            'raw_ct':   actual / expected,
            'n_swings': len(swings),
            'zone_dv':  {z: (a / e if e > 0 else None)
                         for z, (a, e) in zone_accum.items()},
        }
    return results


def regress_and_normalize(hitter_raw, n_prior=HITTER_PRIOR_N,
                          min_n=MIN_HITTER_SWINGS):
    """Ratio-to-league scaling, matching BB+ convention:
        ctPlus = 100 × hitter_raw_adj / league_mean_raw_adj
    (raw_ct is the actual/expected contact ratio, league mean ≈ 1.0,
    so the ratio spread is naturally narrow.)
    """
    eligible = {k: v for k, v in hitter_raw.items() if v['n_swings'] >= min_n}
    if not eligible:
        return {}

    # League anchors (lg_raw, lg_mean) use a de-duplicated POOL, mirroring
    # pipeline_sdplus.regress_and_normalize: for a multi-team hitter, only the
    # combined 2TM/3TM row represents them — their per-team stint rows are
    # excluded so a traded hitter isn't counted 2-3x in the shrinkage target
    # and ratio denominator. ctPlus is still computed for every eligible row.
    def _is_combined(t):
        return isinstance(t, str) and t.endswith('TM') and t[:-2].isdigit()
    combined_ids = {k[:1] for k in eligible if _is_combined(k[1])}
    pool = {k: v for k, v in eligible.items()
            if _is_combined(k[1]) or k[:1] not in combined_ids}

    lg_raw = sum(v['raw_ct'] for v in pool.values()) / len(pool)
    for v in eligible.values():
        n = v['n_swings']
        v['raw_ct_adj'] = (n * v['raw_ct'] + n_prior * lg_raw) / (n + n_prior)

    adj_vals = [pool[k]['raw_ct_adj'] for k in pool]
    lg_mean = sum(adj_vals) / len(adj_vals)

    for v in eligible.values():
        if abs(lg_mean) > 1e-6:
            v['ctPlus'] = round(100.0 * v['raw_ct_adj'] / lg_mean, 1)
        else:
            v['ctPlus'] = 100.0
    return eligible


# ── Packaging ───────────────────────────────────────────────────────────

def serialize_weight_table(smoothed):
    """Cell table in JSON-friendly form for metadata output."""
    out = {}
    for (zone, count), cell in smoothed.items():
        out[f"{zone}|{count[0]}-{count[1]}"] = {
            'p_whiff':    round(cell['p_whiff'],    5),
            'rv_contact': round(cell['rv_contact'], 5),
            'rv_whiff':   round(cell['rv_whiff'],   5),
            'n_swings':   cell['n_swings'],
        }
    return out


def compute_ct_plus(all_pitches, pitches_by_hitter, lg_woba, woba_scale):
    """Main entry point. Returns (normalized_hitter_dict, weight_table_json).

    Matches compute_sd_plus signature for symmetric integration in
    process_data.py.
    """
    # Cell weight tables stay MLB-baselined (translation framing); ROC
    # hitters are looked up against this MLB table by compute_hitter_ct.
    swings = [p for p in all_pitches if p.get('_source','MLB')=='MLB' and is_ct_eligible(p)]
    # Count-anchor the BIP branch (same currency fix as SD+/Loc+; see
    # pipeline_sdplus.build_bip_count_offsets).
    offsets = build_bip_count_offsets(swings, lg_woba, woba_scale)
    rv_fn = make_rv_xrv(lg_woba, woba_scale, offsets)
    raw = build_contact_cell_weights(swings, rv_fn)
    zone_means = zone_level_contact_means(swings, rv_fn)
    smoothed = shrink_contact_cells(raw, zone_means)
    hitter_raw = compute_hitter_ct(pitches_by_hitter, smoothed)
    normalized = regress_and_normalize(hitter_raw)
    return normalized, serialize_weight_table(smoothed)
