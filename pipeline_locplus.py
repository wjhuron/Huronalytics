"""Loc+ (Location+) — per-pitch location-quality metric for pitchers.

The pitcher analog of SD+. For each pitch a pitcher throws, look up the
league-average expected hitter-perspective xRV for that pitch's
(zone × count × pitch_type × batter_hand × pitcher_hand) bucket, average
across all of a pitcher's pitches, and normalize.

Conceptually: "Is this pitcher putting pitches in valuable spots, given
the count, pitch type, and matchup — independent of his stuff or what
the hitter happened to do with the pitch?"

Design highlights:
- Zone classification: same 5 Baseball Savant attack zones as SD+
  (heart / shadow_in / shadow_out / chase / waste). Reused via import
  from pipeline_sdplus.
- Counts: all 12 as-is. Count is the single biggest contextual modifier
  for location value; collapsing to 3 buckets loses real signal
  (3-0 vs 1-0, 0-2 vs 0-1).
- Pitch type: 6 groups (FF, SI, FC, SL, CB, CH) plus OTHER. Including
  pitch type makes Loc+ measure "command given the pitch identity"
  rather than penalizing fastball-heavy guys for living in the zone.
- Handedness: batter × pitcher hand in the key.
- RV for cell weights: luck-neutral hitter-perspective (xwOBA-based on
  BIP, -RunExp otherwise). Same rv_fn as SD+.
- Cell smoothing: continuous Bayesian shrinkage toward the
  (zone × count × pitch_type) handedness-marginal mean, k=50 pseudo-obs.
- Per-pitcher regression: Bayesian shrinkage toward league mean with
  n_prior=400, mirroring SD+.
- Normalization: z-score with sign flip. Loc+ = 100 + 10 × (mu - raw_adj) / sigma
  where mu, sigma come from qualified MLB pitchers. Higher = better.

Why z-score instead of SD+'s ratio-to-league: SD+'s league mean dv is
non-zero (~0.015) because hitters' decisions correlate with the data.
For Loc+, raw mean xRV across pitchers is ~0 by construction (run values
balance league-wide), so a ratio normalization is unstable. Z-score is
the standard "+" stat convention (Stuff+, Pitching+) and works with any
sign of league mean.

ROC handling: ROC pitchers are scored against the MLB-only lookup table
but excluded from the baseline pool, so their data doesn't influence
either the cell weights or the (mu, sigma) standardization parameters.
"""
import math
from collections import defaultdict

from pipeline_utils import safe_float, AAA_TEAMS
from pipeline_sdplus import (
    classify_zone, get_count, make_rv_xrv,
    ZONES, COUNTS,
)

# ── Pitch type grouping ──────────────────────────────────────────────────
# Map raw pitch-type codes to coarse families. Anything not in the main
# six (KN, EP, SC, etc.) gets bucketed into OTHER.
PITCH_TYPE_GROUPS = {
    'FF': 'FF', 'FA': 'FF',
    'SI': 'SI',
    'FC': 'FC', 'CF': 'FC',
    'SL': 'SL', 'ST': 'SL', 'SV': 'SL', 'SW': 'SL',
    'CU': 'CB', 'KC': 'CB', 'CS': 'CB',
    'CH': 'CH', 'FS': 'CH',
}
PT_GROUPS = ['FF', 'SI', 'FC', 'SL', 'CB', 'CH', 'OTHER']


def pitch_type_group(p):
    pt = p.get('Pitch Type')
    if not pt:
        return None
    return PITCH_TYPE_GROUPS.get(pt, 'OTHER')


# ── Hyperparameters ─────────────────────────────────────────────────────
CELL_SHRINK_K   = 50       # cell → marginal-prior shrinkage pseudo-obs
PITCHER_PRIOR_N = 400      # pitcher → league regression pseudo-obs
LOC_SCALE_K     = 10       # locPlus = 100 + LOC_SCALE_K × z
MIN_PITCHER_PITCHES = 100  # floor for computing locPlus at all

HANDS = ('L', 'R')


# ═════════════════════════════════════════════════════════════════════════
#  ELIGIBILITY
# ═════════════════════════════════════════════════════════════════════════

def is_eligible_baseline(p):
    """Pitches that count toward the MLB lookup table.

    Excludes: non-MLB sources, intent walks, HBP, pitchouts, bunt-attempt
    pitches, and any pitch missing zone/count/pitch-type/handedness/RunExp.
    """
    if p.get('_source') != 'MLB':
        return False
    return _is_scorable(p)


def is_eligible_score(p):
    """Pitches that get a Loc+ contribution (used for any pitcher,
    including ROC). Same physical/data-quality requirements as the
    baseline filter, just without the MLB-only restriction."""
    return _is_scorable(p)


def _is_scorable(p):
    if p.get('Event') == 'Intent Walk':
        return False
    desc = p.get('Description') or ''
    if 'bunt' in desc.lower() or 'pitchout' in desc.lower():
        return False
    if desc == 'Hit By Pitch':
        return False
    if p.get('BBType') in ('bunt', 'bunt_grounder', 'bunt_popup', 'bunt_line_drive'):
        return False
    if safe_float(p.get('RunExp')) is None:
        return False
    if classify_zone(p) is None:
        return False
    if get_count(p) is None:
        return False
    if pitch_type_group(p) is None:
        return False
    if p.get('Bats') not in HANDS:
        return False
    if p.get('Throws') not in HANDS:
        return False
    return True


# ═════════════════════════════════════════════════════════════════════════
#  WEIGHT TABLE
# ═════════════════════════════════════════════════════════════════════════

def build_weight_table(pitches, rv_fn):
    """dict[(zone, count, pt_group, bhand, phand)] -> (mean_rv, n).

    Cell value is mean hitter-perspective xRV. Lower = better for the
    pitcher who threw a pitch into this cell.
    """
    cells = defaultdict(lambda: {'sum': 0.0, 'n': 0})
    for p in pitches:
        rv = rv_fn(p)
        if rv is None:
            continue
        key = (
            classify_zone(p),
            get_count(p),
            pitch_type_group(p),
            p['Bats'],
            p['Throws'],
        )
        cells[key]['sum'] += rv
        cells[key]['n'] += 1
    return {k: (v['sum'] / v['n'], v['n']) for k, v in cells.items()}


def marginal_means(pitches, rv_fn):
    """(zone, count, pt_group) handedness-marginal means.
    Used as shrinkage priors so sparse hand-split cells fall back to the
    overall mean for that zone × count × pitch type."""
    msum = defaultdict(float)
    mn = defaultdict(int)
    for p in pitches:
        rv = rv_fn(p)
        if rv is None:
            continue
        key = (classify_zone(p), get_count(p), pitch_type_group(p))
        msum[key] += rv
        mn[key] += 1
    return {k: (msum[k] / mn[k], mn[k]) for k in msum}


def shrink_table(raw_table, marginals, k=CELL_SHRINK_K):
    """Continuous Bayesian shrinkage: smoothed = (n × cell + k × marginal) / (n + k).
    Returns a dict populated for every (zone × count × pt_group × bhand × phand)
    combination — empty raw cells fall back fully to the marginal mean.
    """
    smoothed = {}
    for zone in ZONES:
        for count in COUNTS:
            for pt in PT_GROUPS:
                marg_mean, _ = marginals.get((zone, count, pt), (0.0, 0))
                for bhand in HANDS:
                    for phand in HANDS:
                        key = (zone, count, pt, bhand, phand)
                        if key in raw_table:
                            cell_mean, n = raw_table[key]
                        else:
                            cell_mean, n = 0.0, 0
                        rv = (n * cell_mean + k * marg_mean) / (n + k)
                        smoothed[key] = (rv, n)
    return smoothed


# ═════════════════════════════════════════════════════════════════════════
#  PER-PITCHER SCORING
# ═════════════════════════════════════════════════════════════════════════

def lookup_pitch(p, table):
    """Return the smoothed cell value (hitter-perspective xRV) for one
    pitch. None if any context field is missing."""
    key = (
        classify_zone(p),
        get_count(p),
        pitch_type_group(p),
        p.get('Bats'),
        p.get('Throws'),
    )
    cell = table.get(key)
    return cell[0] if cell is not None else None


def compute_pitcher_raw(pitches_by_pitcher, table):
    """dict[(pitcher, team, throws)] -> {'raw_loc', 'n_pitches', 'zone_loc'}.

    raw_loc is the mean lookup-xRV across all of the pitcher's eligible
    pitches (hitter perspective — lower is better for the pitcher).
    zone_loc breaks that out by zone for the player-page display.
    """
    results = {}
    for key, pitches in pitches_by_pitcher.items():
        elig = [p for p in pitches if is_eligible_score(p)]
        if not elig:
            continue
        rvs = []
        zone_rvs = defaultdict(list)
        for p in elig:
            v = lookup_pitch(p, table)
            if v is None:
                continue
            rvs.append(v)
            zone_rvs[classify_zone(p)].append(v)
        if not rvs:
            continue
        results[key] = {
            'raw_loc': sum(rvs) / len(rvs),
            'n_pitches': len(rvs),
            'zone_loc': {z: (sum(vs) / len(vs) if vs else None)
                         for z, vs in zone_rvs.items()},
        }
    return results


def regress_and_normalize(pitcher_raw,
                          n_prior=PITCHER_PRIOR_N,
                          min_n=MIN_PITCHER_PITCHES,
                          scale_k=LOC_SCALE_K):
    """Bayesian regression + z-score normalization.

    Standardization pool: qualified MLB pitchers (no ROC, no multi-team
    aggregates). Multi-team aggregates and ROC pitchers are scored against
    that standardization but excluded from (mu, sigma).

    Loc+ = 100 + scale_k × (mu - raw_adj) / sigma   (sign-flipped so higher = better)
    """
    eligible = {k: v for k, v in pitcher_raw.items() if v['n_pitches'] >= min_n}
    if not eligible:
        return {}

    # Standardization pool: exclude ROC only. Multi-team aggregates (2TM/3TM)
    # are kept in the pool to match SD+/CT+ convention — Wally explicitly
    # wants ROC excluded from the baseline, but multi-team players still
    # contribute to the league distribution they're being graded against.
    pool = {k: v for k, v in eligible.items() if k[1] not in AAA_TEAMS}
    if not pool:
        return {}

    lg_raw = sum(v['raw_loc'] for v in pool.values()) / len(pool)
    for v in eligible.values():
        n = v['n_pitches']
        v['raw_loc_adj'] = (n * v['raw_loc'] + n_prior * lg_raw) / (n + n_prior)

    pool_adj = [v['raw_loc_adj'] for k, v in eligible.items() if k in pool]
    mu = sum(pool_adj) / len(pool_adj)
    sigma = math.sqrt(sum((v - mu) ** 2 for v in pool_adj) / len(pool_adj))

    for v in eligible.values():
        if sigma > 1e-9:
            z = (v['raw_loc_adj'] - mu) / sigma
            # Sign flip: lower raw (better location) → higher locPlus
            v['locPlus'] = round(100.0 - scale_k * z, 1)
        else:
            v['locPlus'] = 100.0
    return eligible


# ═════════════════════════════════════════════════════════════════════════
#  PACKAGING
# ═════════════════════════════════════════════════════════════════════════

def serialize_weight_table(smoothed):
    """JSON-friendly dict keyed by
    `{zone}|{balls}-{strikes}|{pt_group}|{bhand}|{phand}` → {'rv': float, 'n': int}.
    """
    out = {}
    for (zone, count, pt, bhand, phand), (rv, n) in smoothed.items():
        key = f"{zone}|{count[0]}-{count[1]}|{pt}|{bhand}|{phand}"
        out[key] = {'rv': round(rv, 5), 'n': n}
    return out


def compute_loc_plus(all_pitches, pitches_by_pitcher, lg_woba, woba_scale):
    """Main entry point.

    Args:
        all_pitches: flat list of pitch dicts (MLB + AAA). MLB-only is
            filtered inside via is_eligible_baseline.
        pitches_by_pitcher: dict[(pitcher, team, throws)] -> list of pitch dicts
        lg_woba, woba_scale: FanGraphs Guts constants for xRV

    Returns:
        normalized: dict[(pitcher, team, throws)] -> {locPlus, raw_loc,
            raw_loc_adj, n_pitches, zone_loc}
        weight_table_json: dict for metadata output
    """
    rv_fn = make_rv_xrv(lg_woba, woba_scale)
    baseline = [p for p in all_pitches if is_eligible_baseline(p)]

    raw_table = build_weight_table(baseline, rv_fn)
    marginals = marginal_means(baseline, rv_fn)
    smoothed = shrink_table(raw_table, marginals)

    pitcher_raw = compute_pitcher_raw(pitches_by_pitcher, smoothed)
    normalized = regress_and_normalize(pitcher_raw)

    return normalized, serialize_weight_table(smoothed)
