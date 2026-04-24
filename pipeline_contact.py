"""CT+ (Contact+) — per-swing contact-frequency index.

Complements SD+ (decision quality) and BB+ (contact quality) to form an
orthogonal three-axis view of plate performance:
    SD+  — did you swing at the right pitch?
    CT+  — did you make contact when you swung?          (this file)
    BB+  — how good was the contact when you made it?

Raw metric: hitter's LEVERAGE-WEIGHTED CONTACT RATE across their
eligible swings:
    raw_ct = Σ (I[contact] × leverage[cell]) / Σ leverage[cell]
    leverage[cell] = rv_contact[cell] - rv_whiff[cell]

That is, contact = 1 / whiff = 0, weighted by the RV gap between making
and missing contact in each (zone × count) cell. Always in [0, 1]. League
mean is ~0.74. Matches BB+'s ratio-to-league convention:
    ctPlus = 100 × hitter_raw_ct / league_raw_ct

Why leverage weighting: 2-strike whiffs matter far more than 0-0 whiffs
because rv_whiff ≈ K (very negative) at 2K while a 0-0 whiff is just a
strike added. Heart-zone whiffs cost more than chase-zone whiffs because
rv_contact ≈ high xwOBA on heart contact. The (rv_contact - rv_whiff)
weighting makes high-stakes contact count more toward the hitter's score.

Empirical validation confirmed the (zone × count) cell structure is
approximately optimal at current sample sizes — pitch-type expansion
adds <1% of residual variance; pitcher-identity adjustment is dominated
by sampling noise.
"""
import math
from collections import defaultdict

from pipeline_utils import safe_float
from pipeline_sdplus import (
    classify_zone, classify_decision, get_count, is_eligible,
    make_rv_xrv, ZONES, COUNTS,
)

# ── Hyperparameters ─────────────────────────────────────────────────────
CELL_SHRINK_K  = 50       # cell → zone shrinkage pseudo-swings
HITTER_PRIOR_N = 400      # hitter → league regression pseudo-swings
CT_SCALE_K     = 30       # ctPlus = 100 + CT_SCALE_K × z
MIN_HITTER_SWINGS = 50    # computation floor; qualification (3.1 × TGP)
                          #   is applied separately on the leaderboard

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
    """Compute hitter's leverage-weighted contact rate.
    raw_ct = Σ(I[contact] × leverage) / Σ(leverage)   ∈ [0, 1]
    Returns {(hitter, team) -> {raw_ct, n_swings, zone_dv}} where
    zone_dv[z] is the per-zone leverage-weighted contact rate (also [0, 1]).
    """
    results = {}
    for key, pitches in pitches_by_hitter.items():
        swings = [p for p in pitches if is_ct_eligible(p)]
        if not swings:
            continue
        num = 0.0
        denom = 0.0
        zone_accum = defaultdict(lambda: [0.0, 0.0])  # [num, denom] per zone
        for p in swings:
            lev, con = compute_ct_swing(p, table)
            if lev <= 0:
                # Should not happen if cells are sane — skip defensively
                continue
            num += lev * con
            denom += lev
            zone_accum[classify_zone(p)][0] += lev * con
            zone_accum[classify_zone(p)][1] += lev
        if denom <= 0:
            continue
        results[key] = {
            'raw_ct':   num / denom,
            'n_swings': len(swings),
            'zone_dv':  {z: (a/d if d > 0 else None)
                         for z, (a, d) in zone_accum.items()},
        }
    return results


def regress_and_normalize(hitter_raw, n_prior=HITTER_PRIOR_N,
                          min_n=MIN_HITTER_SWINGS):
    """Ratio-to-league scaling, matching BB+ convention:
        ctPlus = 100 × hitter_raw_adj / league_mean_raw_adj
    Same note on spread as SD+: signed, near-zero league mean produces
    a wider spread than BB+.
    """
    eligible = {k: v for k, v in hitter_raw.items() if v['n_swings'] >= min_n}
    if not eligible:
        return {}

    lg_raw = sum(v['raw_ct'] for v in eligible.values()) / len(eligible)
    for v in eligible.values():
        n = v['n_swings']
        v['raw_ct_adj'] = (n * v['raw_ct'] + n_prior * lg_raw) / (n + n_prior)

    adj_vals = [v['raw_ct_adj'] for v in eligible.values()]
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
    rv_fn = make_rv_xrv(lg_woba, woba_scale)
    swings = [p for p in all_pitches if is_ct_eligible(p)]
    raw = build_contact_cell_weights(swings, rv_fn)
    zone_means = zone_level_contact_means(swings, rv_fn)
    smoothed = shrink_contact_cells(raw, zone_means)
    hitter_raw = compute_hitter_ct(pitches_by_hitter, smoothed)
    normalized = regress_and_normalize(hitter_raw)
    return normalized, serialize_weight_table(smoothed)
