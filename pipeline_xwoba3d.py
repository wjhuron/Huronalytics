"""xwOBA3D — joint EV × LA × spray × bats empirical wOBA lookup.

Current BB+ combines two independent 2D lookups:
  xwOBAcon  ← Savant's EV × LA per-pitch model
  xwOBAsp   ← Our SACQ table: spray × LA × bats

Those two components assume additive independence. In reality, contact
outcome varies jointly with all three dimensions — e.g., a 95 mph pulled
line drive at 20° has very different league wOBA than a 95 mph opposite-
field line drive at 20°, and the current additive composite can't
express that interaction.

This module builds the 3D (EV × LA × spray × bats) empirical wOBA table
from league BIP data, applies hierarchical Bayesian shrinkage toward 2D
marginals for thin cells, and computes a per-hitter xwOBA3D — the mean
3D-lookup wOBA across their BIP. Intended as a drop-in replacement or
supplement for xwOBAsp in BB+.
"""
import math
from collections import defaultdict

from pipeline_utils import (
    safe_float, BUNT_BB_TYPES, spray_angle, spray_direction,
)

# ── Bucket boundaries ───────────────────────────────────────────────────
# Coarse bins for stability. With ~18k BIP early in season, these give
# ~100 obs/cell on average across the ~288 cells.
EV_BINS = [(0, 70), (70, 80), (80, 88), (88, 95), (95, 102), (102, 200)]
LA_BINS = [(-90, -10), (-10, 0), (0, 10), (10, 20), (20, 30), (30, 40), (40, 90)]
SPRAY_DIRS = ['pull', 'middle', 'opposite']
HANDS = ['R', 'L', 'S']  # 'S' = switch hitter — rare per-pitch attribute

# Hierarchical shrinkage pseudo-count toward 2D marginals.
CELL_SHRINK_K = 20


# ── Classification ──────────────────────────────────────────────────────

def _bucket(v, bins):
    for i, (lo, hi) in enumerate(bins):
        if lo <= v < hi:
            return i
    return None


def classify_bip(p):
    """Return (ev_bin, la_bin, spray_direction, bats) or None."""
    if p.get('Description') != 'In Play':
        return None
    if p.get('BBType') in BUNT_BB_TYPES:
        return None
    ev = safe_float(p.get('ExitVelo'))
    la = safe_float(p.get('LaunchAngle'))
    hcx = safe_float(p.get('HC_X'))
    hcy = safe_float(p.get('HC_Y'))
    bats = p.get('Bats')
    if any(v is None for v in (ev, la, hcx, hcy, bats)):
        return None
    if bats not in HANDS:
        return None
    angle = spray_angle(hcx, hcy)
    direction = spray_direction(angle, bats)
    if not direction:
        return None
    evi = _bucket(ev, EV_BINS)
    lai = _bucket(la, LA_BINS)
    if evi is None or lai is None:
        return None
    return (evi, lai, direction, bats)


# ── Weight table ────────────────────────────────────────────────────────

def build_xwoba3d_table(bip_pitches):
    """Raw cell means: dict[(evi, lai, spray, bats)] → (mean_xwoba, n)."""
    cells = defaultdict(lambda: {'sum': 0.0, 'n': 0})
    for p in bip_pitches:
        key = classify_bip(p)
        if key is None:
            continue
        xw = safe_float(p.get('xwOBA'))
        if xw is None:
            continue
        cells[key]['sum'] += xw
        cells[key]['n'] += 1
    return {k: (v['sum'] / v['n'], v['n']) for k, v in cells.items() if v['n'] > 0}


def _two_d_marginals(bip_pitches):
    """Compute the three 2D marginals used as shrinkage priors:
      ev_la_bats   = mean xwOBA by (evi, lai, bats)
      la_sp_bats   = mean xwOBA by (lai, spray, bats)
      ev_sp_bats   = mean xwOBA by (evi, spray, bats)
    plus the bats-level grand mean as an ultimate fallback.
    """
    ev_la = defaultdict(lambda: {'sum': 0.0, 'n': 0})
    la_sp = defaultdict(lambda: {'sum': 0.0, 'n': 0})
    ev_sp = defaultdict(lambda: {'sum': 0.0, 'n': 0})
    by_bats = defaultdict(lambda: {'sum': 0.0, 'n': 0})
    overall = {'sum': 0.0, 'n': 0}
    for p in bip_pitches:
        key = classify_bip(p)
        if key is None:
            continue
        xw = safe_float(p.get('xwOBA'))
        if xw is None:
            continue
        evi, lai, sp, bats = key
        for k, d in [((evi, lai, bats), ev_la),
                     ((lai, sp, bats),   la_sp),
                     ((evi, sp, bats),   ev_sp),
                     (bats,              by_bats)]:
            d[k]['sum'] += xw
            d[k]['n']   += 1
        overall['sum'] += xw
        overall['n']   += 1

    def flat(d):
        return {k: v['sum'] / v['n'] for k, v in d.items() if v['n'] > 0}

    return {
        'ev_la':   flat(ev_la),
        'la_sp':   flat(la_sp),
        'ev_sp':   flat(ev_sp),
        'by_bats': flat(by_bats),
        'global':  overall['sum'] / overall['n'] if overall['n'] else 0.33,
    }


def shrink_xwoba3d(raw_table, bip_pitches, k=CELL_SHRINK_K):
    """Shrink each 3D cell toward the mean of its 2D marginals.
    Missing cells fall back through marginals → bats avg → global avg.
    Returns every possible cell (fully-populated table)."""
    mg = _two_d_marginals(bip_pitches)
    smoothed = {}
    for evi in range(len(EV_BINS)):
        for lai in range(len(LA_BINS)):
            for sp in SPRAY_DIRS:
                for bats in HANDS:
                    key = (evi, lai, sp, bats)
                    cell_mean, n = raw_table.get(key, (None, 0))
                    # Build prior from 2D marginals (average of three if available).
                    priors = []
                    for m_key, m_dict in [((evi, lai, bats), 'ev_la'),
                                          ((lai, sp,  bats), 'la_sp'),
                                          ((evi, sp,  bats), 'ev_sp')]:
                        v = mg[m_dict].get(m_key)
                        if v is not None:
                            priors.append(v)
                    if priors:
                        prior = sum(priors) / len(priors)
                    else:
                        prior = mg['by_bats'].get(bats, mg['global'])
                    if cell_mean is None:
                        smoothed[key] = (prior, 0)
                    else:
                        rv = (n * cell_mean + k * prior) / (n + k)
                        smoothed[key] = (rv, n)
    return smoothed


# ── Per-hitter aggregation ──────────────────────────────────────────────

def compute_hitter_xwoba3d(hitter_pitches, table):
    """Return hitter's mean expected wOBA via 3D lookup. None if no BIP."""
    vals = []
    for p in hitter_pitches:
        key = classify_bip(p)
        if key is None:
            continue
        if key in table:
            vals.append(table[key][0])
    return sum(vals) / len(vals) if vals else None


def compute_all_hitters_xwoba3d(all_pitches, pitches_by_hitter):
    """Returns (hitter_dict, league_mean, smoothed_table)."""
    bip = [p for p in all_pitches if p.get('_source') == 'MLB']
    raw = build_xwoba3d_table(bip)
    smoothed = shrink_xwoba3d(raw, bip)

    hitter_results = {}
    for key, pitches in pitches_by_hitter.items():
        r = compute_hitter_xwoba3d(pitches, smoothed)
        if r is not None:
            hitter_results[key] = r

    # League average = BIP-weighted overall mean from the cell table
    total_sum = 0.0
    total_n = 0
    for (rv, n) in smoothed.values():
        total_sum += rv * n
        total_n   += n
    lg_avg = total_sum / total_n if total_n else None

    return hitter_results, lg_avg, smoothed


def serialize_table(smoothed):
    """For metadata output."""
    out = {}
    for key, (rv, n) in smoothed.items():
        evi, lai, sp, bats = key
        out[f"ev{evi}|la{lai}|{sp}|{bats}"] = {'rv': round(rv, 5), 'n': n}
    return out
