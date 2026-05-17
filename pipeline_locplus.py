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
MIN_PITCHER_PITCHES = 100  # floor for computing overall locPlus
MIN_PITCH_TYPE_PITCHES = 25  # floor for per-pitch-type locPlus
PITCH_TYPE_PRIOR_N = 150   # per-pitch-type Bayesian shrinkage pseudo-obs

HANDS = ('L', 'R')


# ═════════════════════════════════════════════════════════════════════════
#  ELIGIBILITY
# ═════════════════════════════════════════════════════════════════════════

def is_eligible_baseline(p):
    """Pitches that count toward the MLB lookup table.

    Requires RunExp because the cell weights are means of rv_fn(p), which
    is xwOBA/RunExp-derived. Excludes non-MLB sources, intent walks, HBP,
    pitchouts, bunt-attempt pitches, and any pitch missing the lookup key.
    """
    if p.get('_source') != 'MLB':
        return False
    if safe_float(p.get('RunExp')) is None:
        return False
    return _is_scorable(p)


def is_eligible_score(p):
    """Pitches that get a Loc+ contribution (used for ANY pitcher,
    including ROC).

    Scoring is a pure lookup: a pitch's Loc+ contribution is the league
    cell value for its (zone × count × pitch_type × bhand × phand) bucket.
    The pitch's OWN RunExp/xwOBA is never used to score it, so RunExp is
    NOT required here. This is what lets ROC pitchers be scored — the ROC
    sheet has location/count/pitch-type/handedness but no RunExp column.
    """
    return _is_scorable(p)


def _is_scorable(p):
    """Lookup-key validity + event exclusions. No RunExp requirement —
    that lives in is_eligible_baseline only."""
    if p.get('Event') == 'Intent Walk':
        return False
    desc = p.get('Description') or ''
    if 'bunt' in desc.lower() or 'pitchout' in desc.lower():
        return False
    if desc == 'Hit By Pitch':
        return False
    if p.get('BBType') in ('bunt', 'bunt_grounder', 'bunt_popup', 'bunt_line_drive'):
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
                          min_n_score=1,
                          min_n_pool=MIN_PITCHER_PITCHES,
                          scale_k=LOC_SCALE_K):
    """Bayesian regression + z-score normalization.

    Two separate thresholds:
    - min_n_score: minimum scorable pitches to GET a Loc+ value. Set to 1
      so every pitcher with any usable location data is scored. Tiny
      samples are pulled hard toward 100 by the n_prior shrinkage, which
      is the statistically correct "we don't know yet" behavior.
    - min_n_pool: minimum to be IN the (mu, sigma) standardization pool.
      Kept high so noisy small-sample pitchers don't distort the league
      distribution everyone is graded against.

    Standardization pool also excludes ROC (Wally's rule: ROC scored
    against the MLB baseline but not part of it). Multi-team aggregates
    (2TM/3TM) stay in the pool, matching SD+/CT+ convention.

    Loc+ = 100 + scale_k × (mu - raw_adj) / sigma   (sign-flipped so higher = better)
    """
    scored = {k: v for k, v in pitcher_raw.items() if v['n_pitches'] >= min_n_score}
    if not scored:
        return {}

    pool = {k: v for k, v in scored.items()
            if k[1] not in AAA_TEAMS and v['n_pitches'] >= min_n_pool}
    if not pool:
        return {}

    lg_raw = sum(v['raw_loc'] for v in pool.values()) / len(pool)
    for v in scored.values():
        n = v['n_pitches']
        v['raw_loc_adj'] = (n * v['raw_loc'] + n_prior * lg_raw) / (n + n_prior)

    pool_adj = [scored[k]['raw_loc_adj'] for k in pool]
    mu = sum(pool_adj) / len(pool_adj)
    sigma = math.sqrt(sum((v - mu) ** 2 for v in pool_adj) / len(pool_adj))

    for v in scored.values():
        if sigma > 1e-9:
            z = (v['raw_loc_adj'] - mu) / sigma
            # Sign flip: lower raw (better location) → higher locPlus
            v['locPlus'] = round(100.0 - scale_k * z, 1)
        else:
            v['locPlus'] = 100.0
    return scored


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


def regress_and_normalize_by_pt(pitch_raw,
                                pt_group_fn,
                                pool_filter_fn,
                                n_prior=PITCH_TYPE_PRIOR_N,
                                min_n_score=1,
                                min_n_pool=MIN_PITCH_TYPE_PITCHES,
                                scale_k=LOC_SCALE_K):
    """Per-pitch-type-GROUP Bayesian regression + z-score normalization.

    Each row in `pitch_raw` is keyed by some tuple that includes a raw
    pitch type (e.g., 'FF', 'ST'). `pt_group_fn(key)` returns the family
    name ('FF', 'SI', 'FC', 'SL', 'CB', 'CH', 'OTHER') used for the
    standardization bucket. Raw sweepers (ST) and traditional sliders (SL)
    therefore standardize against the same SL-group pool even though they
    appear as separate leaderboard rows.

    Two thresholds (same philosophy as the overall metric):
    - min_n_score: minimum scorable pitches of that type to GET a value.
      Set to 1 so EVERY pitch type a pitcher throws gets a Loc+. A pitcher
      who threw 4 curveballs gets a curveball Loc+ ≈ 100 (n_prior pulls it
      to the group mean) rather than a blank cell.
    - min_n_pool: minimum to be IN the group's (mu, sigma) distribution.
      Keeps the per-group baseline from being warped by 3-pitch samples.

    `pool_filter_fn(key)` further restricts the pool (used to drop ROC
    rows from the baseline while still scoring them). Multi-team
    aggregates stay in the pool, matching the overall-Loc+ convention.
    """
    scored = {k: v for k, v in pitch_raw.items() if v['n_pitches'] >= min_n_score}
    if not scored:
        return {}

    # Bucket every scorable row by pitch-type group
    by_group = defaultdict(dict)
    for k, v in scored.items():
        by_group[pt_group_fn(k)][k] = v

    for group, rows in by_group.items():
        pool = {k: v for k, v in rows.items()
                if pool_filter_fn(k) and v['n_pitches'] >= min_n_pool}
        if not pool:
            # No stable baseline for this group — everyone is league-average
            for k in rows:
                rows[k]['raw_loc_adj'] = rows[k]['raw_loc']
                rows[k]['locPlus'] = 100.0
            continue
        lg_raw = sum(v['raw_loc'] for v in pool.values()) / len(pool)
        for v in rows.values():
            n = v['n_pitches']
            v['raw_loc_adj'] = (n * v['raw_loc'] + n_prior * lg_raw) / (n + n_prior)
        pool_adj = [rows[k]['raw_loc_adj'] for k in pool]
        mu = sum(pool_adj) / len(pool_adj)
        sigma = math.sqrt(sum((v - mu) ** 2 for v in pool_adj) / len(pool_adj))
        for v in rows.values():
            if sigma > 1e-9:
                z = (v['raw_loc_adj'] - mu) / sigma
                v['locPlus'] = round(100.0 - scale_k * z, 1)
            else:
                v['locPlus'] = 100.0

    # Flatten back into one dict
    out = {}
    for rows in by_group.values():
        out.update(rows)
    return out


def compute_loc_plus(all_pitches, pitches_by_pitcher, pitches_by_pitch_type,
                    lg_woba, woba_scale):
    """Main entry point.

    Args:
        all_pitches: flat list of pitch dicts (MLB + AAA). MLB-only is
            filtered inside via is_eligible_baseline.
        pitches_by_pitcher: dict[(pitcher, team, throws)] -> list of pitch dicts
        pitches_by_pitch_type: dict[(pitcher, team, pitch_type, throws)] ->
            list of pitch dicts (matches pitch_groups key order in
            process_data.py)
        lg_woba, woba_scale: FanGraphs Guts constants for xRV

    Returns:
        pitcher_results: dict[(pitcher, team, throws)] -> {locPlus, ...}
            (one row per pitcher, all pitch types combined)
        pitch_results: dict[(pitcher, team, pitch_type, throws)] -> {locPlus, ...}
            (one row per pitcher × pitch type, standardized within pitch-type
            GROUP — so sweepers and traditional sliders share a baseline)
        weight_table_json: dict for metadata output
    """
    rv_fn = make_rv_xrv(lg_woba, woba_scale)
    baseline = [p for p in all_pitches if is_eligible_baseline(p)]

    raw_table = build_weight_table(baseline, rv_fn)
    marginals = marginal_means(baseline, rv_fn)
    smoothed = shrink_table(raw_table, marginals)

    pitcher_raw = compute_pitcher_raw(pitches_by_pitcher, smoothed)
    pitcher_results = regress_and_normalize(pitcher_raw)

    pitch_raw = compute_pitcher_raw(pitches_by_pitch_type, smoothed)
    pitch_results = regress_and_normalize_by_pt(
        pitch_raw,
        pt_group_fn=lambda k: PITCH_TYPE_GROUPS.get(k[2], 'OTHER'),
        pool_filter_fn=lambda k: k[1] not in AAA_TEAMS,
    )

    return pitcher_results, pitch_results, serialize_weight_table(smoothed)
