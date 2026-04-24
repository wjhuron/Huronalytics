"""SD+ (Swing Decisions+) — per-pitch decision-quality metric.

Builds a 60-cell (zone × count × decision) run-value weight table from
league-wide MLB pitch data, then scores each hitter on the mean
decision-value of their own decisions (swing/take) using the league cell
weights. 100 = league-average decision-maker; +30 points per standard
deviation above.

Design highlights:
- Zone classification: Baseball Savant attack zones, applied to the hitter-
  specific SzTop/SzBot (which already incorporate the ABS adjustment in
  this pipeline). Five buckets: heart / shadow_in / shadow_out / chase /
  waste. Shadow is split on whether the pitch is a strike (via compute_in_zone).
- Counts: all 12 as-is.
- RV for cell weights: luck-neutral (xwOBA-based for BIP, -RunExp for
  non-BIP). Makes the cell weights "expected run value given league-
  average execution" rather than "average realized outcome."
- Cell smoothing: continuous Bayesian shrinkage toward decision-specific
  zone means with k=50 pseudo-obs.
- Per-hitter regression: Bayesian regression toward the league mean with
  n_prior=400 pseudo-obs. Mitigates early-season noise.
- Normalization: sdPlus = 100 + 30 × z across hitters meeting a 100-decision
  floor (the MLB 3.1 PA × team_games_played qualification is applied
  separately by the leaderboard consumer).

The decision-value formula is `dv = RV(chosen) - RV(opposite)` — absolute
opportunity cost, not league-relative.
"""
import math
from collections import defaultdict

from pipeline_utils import (
    safe_float, SWING_DESCRIPTIONS, BUNT_BB_TYPES, MLB_TEAMS,
    ZONE_HALF_WIDTH,
)

# ── Zone thresholds ─────────────────────────────────────────────────────
# Baseball Savant attack-zone diagram, all measured relative to zone center.
# Horizontal: fractions of zone half-width (≈10"). Vertical: fractions of
# the hitter-specific strike zone.
HEART_X   = 6.7 / 12      # ±6.7" from plate center = inner 67% of plate
SHADOW_X  = 13.3 / 12     # ±13.3" = outer 133% of plate
CHASE_X   = 20.0 / 12     # ±20"  = outer 200% of plate
HEART_VERT_FRAC  = 1.0 / 3.0    # Heart covers middle 33% of zone height
SHADOW_VERT_FRAC = 1.0 / 6.0    # Shadow extends 17% of zone_ht above/below
CHASE_VERT_FRAC  = 0.5          # Chase extends 50% of zone_ht above/below

TAKE_DESCRIPTIONS = {'Called Strike', 'Ball'}

ZONES = ['heart', 'shadow_in', 'shadow_out', 'chase', 'waste']
COUNTS = [(b, s) for b in range(4) for s in range(3)]

# ── Hyperparameters ─────────────────────────────────────────────────────
CELL_SHRINK_K  = 50       # cell → zone shrinkage pseudo-obs
HITTER_PRIOR_N = 400      # hitter → league regression pseudo-obs
SD_SCALE_K     = 30       # sdPlus = 100 + SD_SCALE_K × z
MIN_HITTER_DECISIONS = 100  # floor for computing sdPlus at all

# MLB standard qualification: PA ≥ 3.1 × team games played.
PA_PER_TEAM_GAME = 3.1


# ═════════════════════════════════════════════════════════════════════════
#  CLASSIFICATION
# ═════════════════════════════════════════════════════════════════════════

def classify_zone(p):
    """Return one of {'heart','shadow_in','shadow_out','chase','waste'} or None.

    Uses hitter-specific SzTop/SzBot (ABS-adjusted in the pipeline).
    Shadow is split in/out of zone via pipeline's InZone field.
    """
    px = safe_float(p.get('PlateX'))
    pz = safe_float(p.get('PlateZ'))
    top = safe_float(p.get('SzTop'))
    bot = safe_float(p.get('SzBot'))
    if any(v is None for v in (px, pz, top, bot)):
        return None
    if top <= bot:
        return None

    sz_ht = top - bot
    ax = abs(px)

    z_heart_low  = bot + HEART_VERT_FRAC * sz_ht
    z_heart_high = top - HEART_VERT_FRAC * sz_ht
    z_shadow_low  = bot - SHADOW_VERT_FRAC * sz_ht
    z_shadow_high = top + SHADOW_VERT_FRAC * sz_ht
    z_chase_low   = bot - CHASE_VERT_FRAC * sz_ht
    z_chase_high  = top + CHASE_VERT_FRAC * sz_ht

    if ax <= HEART_X and z_heart_low <= pz <= z_heart_high:
        return 'heart'
    if ax <= SHADOW_X and z_shadow_low <= pz <= z_shadow_high:
        return 'shadow_in' if p.get('InZone') == 'Yes' else 'shadow_out'
    if ax <= CHASE_X and z_chase_low <= pz <= z_chase_high:
        return 'chase'
    return 'waste'


def classify_decision(p):
    desc = p.get('Description')
    if desc in SWING_DESCRIPTIONS:
        return 'swing'
    if desc in TAKE_DESCRIPTIONS:
        return 'take'
    return None


def get_count(p):
    """Parse 'Count' column (e.g., '2-2') into (balls, strikes). None if invalid."""
    c = p.get('Count')
    if not isinstance(c, str) or '-' not in c:
        return None
    try:
        b_str, s_str = c.split('-', 1)
        b, s = int(b_str), int(s_str)
    except (TypeError, ValueError):
        return None
    if not (0 <= b <= 3 and 0 <= s <= 2):
        return None
    return (b, s)


def is_eligible(p):
    """Filter to pitches where a genuine swing/take decision occurred."""
    if p.get('_source') != 'MLB':
        return False
    if p.get('Event') == 'Intent Walk':
        return False
    desc = p.get('Description') or ''
    if 'bunt' in desc.lower():
        return False
    if 'pitchout' in desc.lower():
        return False
    if desc == 'Hit By Pitch':
        return False
    if p.get('BBType') in BUNT_BB_TYPES:
        return False
    if p.get('RunExp') is None or safe_float(p.get('RunExp')) is None:
        return False
    if classify_decision(p) is None:
        return False
    if classify_zone(p) is None:
        return False
    if get_count(p) is None:
        return False
    return True


# ═════════════════════════════════════════════════════════════════════════
#  RUN-VALUE STRATEGIES
# ═════════════════════════════════════════════════════════════════════════

def rv_hitter_runexp(p):
    """Raw hitter-perspective RV: -RunExp."""
    rv = safe_float(p.get('RunExp'))
    return -rv if rv is not None else None


def make_rv_xrv(lg_woba, woba_scale):
    """Return an rv_fn that produces luck-neutral hitter-perspective RV:
    xwOBA-based for BIP pitches with xwOBA, -RunExp for everything else
    (including BIP without xwOBA). Falls back gracefully if Guts constants
    are missing."""
    has_guts = (lg_woba is not None and woba_scale is not None
                and woba_scale != 0)

    def _fn(p):
        if has_guts and p.get('Description') == 'In Play':
            xw = safe_float(p.get('xwOBA'))
            if xw is not None:
                return (xw - lg_woba) / woba_scale
        rv = safe_float(p.get('RunExp'))
        return -rv if rv is not None else None
    return _fn


# ═════════════════════════════════════════════════════════════════════════
#  WEIGHT TABLE
# ═════════════════════════════════════════════════════════════════════════

def build_weight_table(pitches, rv_fn):
    """dict[(zone, count, decision)] -> (mean_rv, n)."""
    cells = defaultdict(lambda: {'sum': 0.0, 'n': 0})
    for p in pitches:
        zone = classify_zone(p)
        decision = classify_decision(p)
        count = get_count(p)
        rv = rv_fn(p)
        if rv is None:
            continue
        key = (zone, count, decision)
        cells[key]['sum'] += rv
        cells[key]['n'] += 1
    return {k: (v['sum'] / v['n'], v['n']) for k, v in cells.items()}


def zone_level_means(pitches, rv_fn):
    """Decision-specific zone means. Used as shrinkage priors."""
    zsum = defaultdict(float)
    zn = defaultdict(int)
    for p in pitches:
        zone = classify_zone(p)
        decision = classify_decision(p)
        rv = rv_fn(p)
        if rv is None:
            continue
        zsum[(zone, decision)] += rv
        zn[(zone, decision)] += 1
    return {k: (zsum[k] / zn[k], zn[k]) for k in zsum}


def shrink_table(raw_table, zone_means, k=CELL_SHRINK_K):
    """Continuous Bayesian shrinkage: smoothed = (n × cell + k × zone) / (n + k).
    Returns dict keyed by (zone, count, decision) with ALL 120 combinations
    populated (even when raw cell was empty — falls back to zone mean)."""
    smoothed = {}
    for zone in ZONES:
        for count in COUNTS:
            for decision in ('swing', 'take'):
                key = (zone, count, decision)
                if key in raw_table:
                    cell_mean, n = raw_table[key]
                else:
                    cell_mean, n = 0.0, 0
                zone_mean, _ = zone_means.get((zone, decision), (0.0, 0))
                rv = (n * cell_mean + k * zone_mean) / (n + k)
                smoothed[key] = (rv, n)
    return smoothed


# ═════════════════════════════════════════════════════════════════════════
#  PER-HITTER SCORING
# ═════════════════════════════════════════════════════════════════════════

def compute_dv(p, table):
    """dv = RV(chosen) - RV(opposite). Symmetric opportunity cost."""
    zone = classify_zone(p)
    decision = classify_decision(p)
    count = get_count(p)
    swing_rv, _ = table[(zone, count, 'swing')]
    take_rv,  _ = table[(zone, count, 'take')]
    if decision == 'swing':
        return swing_rv - take_rv
    else:
        return take_rv - swing_rv


def compute_hitter_sd(pitches_by_hitter, table):
    """dict[(hitter, team)] -> {'raw_sd', 'n_decisions', 'zone_dv'}."""
    results = {}
    for key, pitches in pitches_by_hitter.items():
        elig = [p for p in pitches if is_eligible(p)]
        if not elig:
            continue
        dvs = [compute_dv(p, table) for p in elig]
        zone_dvs = defaultdict(list)
        for p, dv in zip(elig, dvs):
            zone_dvs[classify_zone(p)].append(dv)
        results[key] = {
            'raw_sd': sum(dvs) / len(dvs),
            'n_decisions': len(dvs),
            'zone_dv': {z: (sum(vs) / len(vs) if vs else None)
                        for z, vs in zone_dvs.items()},
        }
    return results


def regress_and_normalize(hitter_raw, n_prior=HITTER_PRIOR_N,
                          min_n=MIN_HITTER_DECISIONS):
    """Ratio-to-league scaling, matching BB+ convention:
        sdPlus = 100 × hitter_raw_adj / league_mean_raw_adj
    where raw_sd_adj is the Bayesian-regressed per-hitter mean decision
    value, and league mean is computed across eligible hitters.

    Because the raw metric is signed and centered near a small positive
    league mean (~0.015), the ratio spread is wider than BB+'s. Hitters
    below league mean produce values below 100; hitters with negative
    raw_sd_adj produce negative sdPlus.
    """
    eligible = {k: v for k, v in hitter_raw.items() if v['n_decisions'] >= min_n}
    if not eligible:
        return {}

    lg_raw = sum(v['raw_sd'] for v in eligible.values()) / len(eligible)
    for v in eligible.values():
        n = v['n_decisions']
        v['raw_sd_adj'] = (n * v['raw_sd'] + n_prior * lg_raw) / (n + n_prior)

    adj_vals = [v['raw_sd_adj'] for v in eligible.values()]
    lg_mean = sum(adj_vals) / len(adj_vals)

    for v in eligible.values():
        if abs(lg_mean) > 1e-6:
            v['sdPlus'] = round(100.0 * v['raw_sd_adj'] / lg_mean, 1)
        else:
            v['sdPlus'] = 100.0
    return eligible


# ═════════════════════════════════════════════════════════════════════════
#  PACKAGING
# ═════════════════════════════════════════════════════════════════════════

def serialize_weight_table(smoothed):
    """Turn the smoothed cell table into a JSON-friendly dict keyed by
    `{zone}|{balls}-{strikes}|{decision}` → {'rv': float, 'n': int}."""
    out = {}
    for (zone, count, decision), (rv, n) in smoothed.items():
        key = f"{zone}|{count[0]}-{count[1]}|{decision}"
        out[key] = {'rv': round(rv, 5), 'n': n}
    return out


def compute_team_games_played(all_pitches):
    """Distinct (Game Date) count per MLB team, using both pitcher and
    batter team columns. Close enough for MLB-standard qualification;
    double-headers (rare) would be undercounted by at most a handful
    per team per season."""
    team_dates = defaultdict(set)
    for p in all_pitches:
        if p.get('_source') != 'MLB':
            continue
        date = p.get('Game Date')
        if not date:
            continue
        for team_col in ('PTeam', 'BTeam'):
            team = p.get(team_col)
            if team and team in MLB_TEAMS:
                team_dates[team].add(date)
    return {t: len(d) for t, d in team_dates.items()}


def compute_sd_plus(all_pitches, pitches_by_hitter, lg_woba, woba_scale):
    """Main entry point.

    Args:
        all_pitches: flat list of pitch dicts (MLB + AAA/ROC filtered
            inside via is_eligible)
        pitches_by_hitter: dict[(hitter, team)] -> list of pitch dicts
        lg_woba, woba_scale: FanGraphs Guts constants for xRV

    Returns:
        normalized: dict[(hitter, team)] -> {sdPlus, raw_sd, raw_sd_adj,
            n_decisions, zone_dv, z}
        weight_table_json: dict for metadata output (audit/frontend)
    """
    rv_fn = make_rv_xrv(lg_woba, woba_scale)
    eligible = [p for p in all_pitches if is_eligible(p)]

    raw_table = build_weight_table(eligible, rv_fn)
    zone_means = zone_level_means(eligible, rv_fn)
    smoothed = shrink_table(raw_table, zone_means)

    hitter_raw = compute_hitter_sd(pitches_by_hitter, smoothed)
    normalized = regress_and_normalize(hitter_raw)

    return normalized, serialize_weight_table(smoothed)
