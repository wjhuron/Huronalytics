"""CT+ (Contact+) — per-swing contact-frequency index.

Complements SD+ (decision quality) and BB+ (contact quality) to form an
orthogonal three-axis view of plate performance:
    SD+  — did you swing at the right pitch?
    CT+  — did you make contact when you swung?          (this file)
    BB+  — how good was the contact when you made it?

Structure mirrors SD+: same 60-cell (zone × count) table, same xRV-based
leverage weights, same Bayesian shrinkage, same SD-scaled output. The
only difference is the per-pitch "decision value" — for CT+, every swing
contributes dv based on whether contact was made vs the league's
expected contact rate in that cell, weighted by the RV gap between
contact and whiff.

Per-swing formula:
    dv = (I[contact] - (1 - p_whiff[cell])) × leverage[cell]
       = p_whiff[cell]        × leverage[cell]    if contact
       = -(1 - p_whiff[cell]) × leverage[cell]    if whiff
    leverage[cell] = rv_contact[cell] - rv_whiff[cell]

Count and zone leverage are handled automatically through the RV gap:
2-strike whiffs cost more because rv_whiff ≈ K ≈ large negative;
heart whiffs cost more because rv_contact ≈ high xwOBA on contact.

Empirical validation confirmed the (zone × count) cell structure is
approximately optimal at current sample sizes — pitch-type expansion
adds <1% of residual variance, pitcher-identity adjustment is dominated
by sampling noise. See scripts/ct_plus_analysis.py if/when needed.
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


# ── Per-swing dv ────────────────────────────────────────────────────────

def compute_ct_dv(p, table):
    """dv = (I[contact] - (1 - p_whiff)) × leverage. By construction, the
    league-average hitter has mean dv = 0 across all swings."""
    zone = classify_zone(p)
    count = get_count(p)
    cell = table[(zone, count)]
    p_whiff = cell['p_whiff']
    leverage = cell['rv_contact'] - cell['rv_whiff']
    outcome = classify_contact_outcome(p)
    if outcome == 'contact':
        return p_whiff * leverage
    else:  # whiff
        return -(1 - p_whiff) * leverage


# ── Per-hitter aggregation ──────────────────────────────────────────────

def compute_hitter_ct(pitches_by_hitter, table):
    """Aggregate per-hitter. Returns {(hitter, team) -> {raw_ct, n_swings,
    zone_dv}}."""
    results = {}
    for key, pitches in pitches_by_hitter.items():
        swings = [p for p in pitches if is_ct_eligible(p)]
        if not swings:
            continue
        dvs = [compute_ct_dv(p, table) for p in swings]
        zone_dvs = defaultdict(list)
        for p, dv in zip(swings, dvs):
            zone_dvs[classify_zone(p)].append(dv)
        results[key] = {
            'raw_ct':    sum(dvs) / len(dvs),
            'n_swings':  len(dvs),
            'zone_dv':   {z: (sum(vs)/len(vs) if vs else None)
                          for z, vs in zone_dvs.items()},
        }
    return results


def regress_and_normalize(hitter_raw, n_prior=HITTER_PRIOR_N,
                          min_n=MIN_HITTER_SWINGS, scale_k=CT_SCALE_K):
    """Bayesian regression + SD scaling → ctPlus."""
    eligible = {k: v for k, v in hitter_raw.items() if v['n_swings'] >= min_n}
    if not eligible:
        return {}

    lg_raw = sum(v['raw_ct'] for v in eligible.values()) / len(eligible)
    for v in eligible.values():
        n = v['n_swings']
        v['raw_ct_adj'] = (n * v['raw_ct'] + n_prior * lg_raw) / (n + n_prior)

    adj_vals = [v['raw_ct_adj'] for v in eligible.values()]
    lg_mean = sum(adj_vals) / len(adj_vals)
    lg_sd   = math.sqrt(sum((x - lg_mean) ** 2 for x in adj_vals) / len(adj_vals))

    for v in eligible.values():
        if lg_sd > 0:
            z = (v['raw_ct_adj'] - lg_mean) / lg_sd
            v['z'] = z
            v['ctPlus'] = round(100 + scale_k * z, 1)
        else:
            v['z'] = 0.0
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
