"""Loc+ (Location+) — decomposition-based per-pitch location-quality metric.

The pitcher analog of a command grade: "is this pitcher putting pitches in
valuable spots, given the count, pitch type, and matchup, independent of his
stuff or what the hitter happened to do?"

MODEL (rebuilt 2026-06). For each pitch we look up the league-average
EXPECTED hitter-perspective run value of a pitch of that type/handedness at
that exact plate location, in that count, then average across the pitcher's
pitches and normalize. Lower expected RV = better location for the pitcher.

The expected value is a DECOMPOSITION over smooth league surfaces:

  ExpRV(x, z | grp, hands, count) =
      Pswing · [ Pwhiff·rvWhiff(count) + Pfoul·rvFoul(count) + Pbip·xwOBAcon(x,z) ]
    + (1-Pswing) · [ Pcs·rvCS(count) + (1-Pcs)·rvBall(count) ]

  - Pwhiff, Pfoul, xwOBAcon, Pcs (called-strike prob) and Pswing are league
    SURFACES over a (PlateX, zone-normalized PlateZ) grid, built per pitch-type
    GROUP × batter-hand × pitcher-hand. Physical surfaces (whiff/foul/contact/
    called-strike) are count-independent for sample size; swing propensity is
    count-specific. The run-value WEIGHTS (rvWhiff/rvFoul/rvCS/rvBall) are
    count-specific. Surfaces are smoothed with an anisotropic separable
    Gaussian (4.5" horizontal, 0.22 zone vertical).
  - Scoring at TRUE count level (no count-demeaning): empirically this is more
    predictive and no less stuff-independent than demeaning.
  - Contact (xwOBAcon) surface is heavily shrunk toward the group mean because
    location-driven contact suppression is mostly luck (THT command study).

Design choices were validated empirically (see scripts/locplus_*.py):
reliability (split-half), stuff-independence (low corr with whiff%/velo), and
predictive validity (first-half score vs second-half xRV allowed). This model
roughly doubles the run-prevention signal of the old 5-zone metric while
becoming markedly more stuff-independent.

Pitch-type groups (validated by clustering value surfaces):
  FF | SI | FC | SL(+ST,SW,SV) | CU(+KC,CS) | CH(+FS) | OTHER

Normalization: locPlus = 100 + 10·(mu - raw_adj)/sigma  (sign-flipped so
higher = better). mu, sigma from qualified MLB pitchers; n_prior=135 overall,
per-group dict per pitch type (N_PRIOR_OVERALL / N_PRIOR_PT below — measured
split-half r=0.5 crossings, 10-seed re-measure 2026-07-13). ROC pitchers are
scored against the MLB surfaces but excluded from the (mu, sigma) pool.
"""
import math
from collections import defaultdict

from pipeline_utils import safe_float, AAA_TEAMS
from pipeline_sdplus import classify_zone, ZONES, build_bip_count_offsets

# ── Model options (each A/B-validated on the 3-objective harness:
#    scripts/phase2_locplus_eval.py — reliability / stuff-independence /
#    predictive validity). Validated 2026-07-02: ──
PCS_BY_HAND = True             # called-strike surface per batter hand (the
                               # LHH called zone sits ~2" farther outside;
                               # takes are ~half of pitches and shadow takes
                               # are where location value concentrates).
                               # WON: rel 0.568->0.575, pred 0.079->0.082.
BIP_COUNT_ANCHOR = False       # add offset(c) to the BIP value branch
                               # (pipeline_sdplus.build_bip_count_offsets).
                               # LOST decisively for Loc+ and stays OFF:
                               # velo leak 0.29->0.38, whiff leak
                               # 0.031->0.072, predictive 0.079->-0.029.
                               # Anchoring makes ExpRV strongly count-mix
                               # dependent, and count mix is a stuff/
                               # sequencing effect — exactly the contamination
                               # Loc+ exists to exclude. (The anchor is
                               # correct and ON in SD+/CT+, which score
                               # hitter decisions against the count state.)
SWING_PRIOR_COUNT_LEVEL = True # count-specific swing surfaces shrink toward
                               # collapsed-surface × league count multiplier
                               # (a sparse 3-0 surface otherwise shrinks
                               # toward a ~46% swing rate instead of ~10%).
                               # WON objective 2: whiff leak 0.031->0.019,
                               # rel +0.005, pred -0.006 (noise-level).
CS_COUNT_TRANSFORM = True      # count-transform on the called-strike surface:
                               # umpires expand the zone with more balls and
                               # shrink it with more strikes, so the SAME
                               # location is called a strike at different rates
                               # by count. One baseline CS surface + a per-
                               # (hand,count) logit intercept calibrated so the
                               # predicted called-strike count matches observed
                               # among that count's takes (BP framing-model
                               # style). WON (scripts/locplus_cs_transform_test
                               # .py): rel 0.591->0.602, stuff-leak flat, pred
                               # -0.007 (noise); learned shifts monotonic and
                               # match umpire behavior (3-0 +0.32, 0-2 -0.67).

# ── Pitch-type grouping ─────────────────────────────────────────────────
GROUP = {
    'FF': 'FF', 'FA': 'FF',
    'SI': 'SI',
    'FC': 'FC', 'CF': 'FC',
    'SL': 'SL', 'ST': 'SL', 'SW': 'SL', 'SV': 'SL',
    'CU': 'CU', 'KC': 'CU', 'CS': 'CU',
    'CH': 'CH', 'FS': 'CH',
}
GROUPS = ['FF', 'SI', 'FC', 'SL', 'CU', 'CH', 'OTHER']

def group_of(p):
    pt = p.get('Pitch Type')
    if not pt:
        return None
    return GROUP.get(pt, 'OTHER')

def group_of_code(pt):
    if not pt:
        return None
    return GROUP.get(pt, 'OTHER')

# ── Grid + smoothing ────────────────────────────────────────────────────
X_MIN, X_MAX = -1.5, 1.5            # feet (plate center = 0)
BIN_X = 2.0 / 12.0                  # 2-inch horizontal bins
NX = int(round((X_MAX - X_MIN) / BIN_X))           # 18
Z_MIN, Z_MAX = -0.6, 1.6           # zone-normalized (0 = bottom, 1 = top)
BIN_Z = 0.10
NZ = int(round((Z_MAX - Z_MIN) / BIN_Z))           # 22
PHYS_X_IN = 4.5                    # physical smoothing bandwidths
PHYS_Z_FRAC = 0.22

# Per-surface shrinkage pseudo-counts toward the group mean
K_WHIFF, K_FOUL, K_XWCON = 8, 8, 200
K_SWING_COLL, K_SWING_COUNT, K_CS = 6, 20, 10

# Per-pitcher regression + normalization. n_prior values are the measured
# split-half r=0.5 crossings (regression constant). Re-measured 2026-07-13
# on the full season, 10 shuffle seeds (scripts/locplus_nprior_multiseed.py):
# overall mean 135 (median 134, seed range 118-155) — the early-season 117
# under-regressed. Per-group is now measurable (was "breakers unmeasurable"
# in the April measurement); values are the 10-seed medians. FF/SL stabilize
# fastest (~71-74), the cutter slowest (~117). OTHER is unmeasured → 100.
# Output is low-sensitivity here, but each group should be regressed by its
# own evidence rate.
N_PRIOR_OVERALL = 135
N_PRIOR_PT = {'FF': 71, 'SI': 85, 'FC': 117, 'SL': 74, 'CU': 95, 'CH': 104,
              'OTHER': 100}
N_PRIOR_PT_DEFAULT = 100
LOC_SCALE_K = 10
MIN_POOL_OVERALL = 250             # min pitches to enter the (mu,sigma) pool
MIN_POOL_PT = 60                   # min pitches of a type to enter its group pool

COUNTS = [(b, s) for b in range(4) for s in range(3)]
HANDS = ('L', 'R')
SWING_DESC = {'Swinging Strike', 'Foul', 'In Play'}
TAKE_DESC = {'Ball', 'Called Strike'}
EXCLUDE_DESC = {'Hit By Pitch', 'Foul Bunt', 'Missed Bunt', 'Bunt Foul Tip',
                'Pitchout', 'Swinging Pitchout', 'Foul Pitchout'}
BUNT_BB = {'bunt', 'bunt_grounder', 'bunt_popup', 'bunt_line_drive'}


# ═════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═════════════════════════════════════════════════════════════════════════
def get_count(p):
    c = p.get('Count')
    if not isinstance(c, str) or '-' not in c:
        return None
    try:
        b, s = c.split('-', 1)
        b, s = int(b), int(s)
    except (TypeError, ValueError):
        return None
    return (b, s) if (0 <= b <= 3 and 0 <= s <= 2) else None

def _znorm(p):
    pz = safe_float(p.get('PlateZ'))
    top = safe_float(p.get('SzTop'))
    bot = safe_float(p.get('SzBot'))
    if pz is None or top is None or bot is None or top <= bot:
        return None
    return (pz - bot) / (top - bot)

def _xbin(px):
    return min(max(int((px - X_MIN) / BIN_X), 0), NX - 1)
def _zbin(zn):
    return min(max(int((zn - Z_MIN) / BIN_Z), 0), NZ - 1)

def _is_scorable(p):
    """Valid lookup key + event exclusions. No RunExp/xwOBA requirement here
    (those are checked at surface-build time), which lets ROC pitches score."""
    if p.get('Event') == 'Intent Walk':
        return False
    if p.get('Description') in EXCLUDE_DESC:
        return False
    if p.get('BBType') in BUNT_BB:
        return False
    if group_of(p) is None:
        return False
    if safe_float(p.get('PlateX')) is None or _znorm(p) is None:
        return False
    if p.get('Bats') not in HANDS or p.get('Throws') not in HANDS:
        return False
    if get_count(p) is None:
        return False
    return True

def is_eligible_baseline(p):
    return p.get('_source') == 'MLB' and _is_scorable(p)


# ═════════════════════════════════════════════════════════════════════════
#  SEPARABLE ANISOTROPIC GAUSSIAN SMOOTHER
# ═════════════════════════════════════════════════════════════════════════
def _k1d(bw):
    win = max(1, int(math.ceil(3 * bw)))
    return [(d, math.exp(-0.5 * (d / bw) ** 2)) for d in range(-win, win + 1)]

_KX = _k1d(PHYS_X_IN / 2.0)        # bandwidth in cells (bins are 2", 0.10z)
_KZ = _k1d(PHYS_Z_FRAC / BIN_Z)

def _zeros():
    return [[0.0] * NZ for _ in range(NX)]

def _smooth(num, den, prior, kprior):
    """Nadaraya-Watson kernel regression (num/den are NX×NZ arrays) with a
    prior pseudo-count. `prior` is a scalar or an NX×NZ array."""
    tn, td = _zeros(), _zeros()
    for i in range(NX):
        ni, di_, tni, tdi = num[i], den[i], tn[i], td[i]
        for j in range(NZ):
            sn = sd = 0.0
            for dj, w in _KZ:
                jj = j + dj
                if 0 <= jj < NZ:
                    sn += w * ni[jj]; sd += w * di_[jj]
            tni[j] = sn; tdi[j] = sd
    out = _zeros()
    pdict = not isinstance(prior, (int, float))
    for i in range(NX):
        oi = out[i]
        for j in range(NZ):
            sn = sd = 0.0
            for di2, w in _KX:
                ii = i + di2
                if 0 <= ii < NX:
                    sn += w * tn[ii][j]; sd += w * td[ii][j]
            pr = prior[i][j] if pdict else prior
            s = sd + kprior
            oi[j] = (sn + kprior * pr) / s if s > 0 else pr
    return out

def _gsum(a):
    return sum(sum(r) for r in a)

def _logit(p):
    p = min(max(p, 1e-6), 1.0 - 1e-6)
    return math.log(p / (1.0 - p))

def _sig(x):
    return 1.0 / (1.0 + math.exp(-x))


# ═════════════════════════════════════════════════════════════════════════
#  BUILD LEAGUE SURFACES
# ═════════════════════════════════════════════════════════════════════════
def build_surfaces(baseline, lg_woba, woba_scale):
    """Build all league surfaces + count value scalars from MLB baseline pitches.
    Returns a dict bundle consumed by score_pitch()."""
    has_guts = (lg_woba is not None and woba_scale not in (None, 0))

    # count value scalars (hitter perspective = -RunExp)
    cv = {k: defaultdict(lambda: [0.0, 0]) for k in ('whiff', 'foul', 'cs', 'ball')}
    for p in baseline:
        re = safe_float(p.get('RunExp'))
        if re is None:
            continue
        d = p.get('Description')
        slot = {'Swinging Strike': 'whiff', 'Foul': 'foul',
                'Called Strike': 'cs', 'Ball': 'ball'}.get(d)
        if slot:
            c = get_count(p)
            cv[slot][c][0] += -re; cv[slot][c][1] += 1
    RV = {k: {c: (s / n if n else 0.0) for c, (s, n) in dd.items()} for k, dd in cv.items()}
    # Fill counts with zero baseline events (possible on partial/backfill
    # runs — e.g. no 3-0 whiffs yet) with the slot's event-weighted overall
    # mean. Without this, score_pitch's .get(c, ...) silently valued the
    # outcome at 0.0 — e.g. a 3-0 whiff at 0.0 instead of ~-0.10 —
    # distorting every pitch scored in that count.
    for k, dd in cv.items():
        tot_s = sum(s for s, n in dd.values())
        tot_n = sum(n for _s, n in dd.values())
        overall = tot_s / tot_n if tot_n else 0.0
        for c in COUNTS:
            if c not in RV[k]:
                RV[k][c] = overall

    def acc0():
        return {k: _zeros() for k in ('swn', 'swd', 'whn', 'fln', 'bipn', 'bipd')}
    A = defaultdict(acc0)                                   # [(grp,bh,ph)]
    AC = defaultdict(lambda: {'swn': _zeros(), 'swd': _zeros()})   # [(grp,bh,ph,count)]
    csn = {h: _zeros() for h in HANDS}
    csd = {h: _zeros() for h in HANDS}
    cnt_sw = defaultdict(lambda: [0, 0])   # count -> [swings, pitches] (league)
    csd_hc = defaultdict(_zeros)           # (hand,count) -> take-count grid
    cs_obs_hc = defaultdict(int)           # (hand,count) -> observed called strikes

    for p in baseline:
        bh = p['Bats']
        key = (group_of(p), bh, p['Throws'])
        c = get_count(p)
        i = _xbin(safe_float(p.get('PlateX'))); j = _zbin(_znorm(p))
        d = p.get('Description')
        a = A[key]; ac = AC[(key, c)]
        a['swd'][i][j] += 1; ac['swd'][i][j] += 1
        cnt_sw[c][1] += 1
        if d in SWING_DESC:
            a['swn'][i][j] += 1; ac['swn'][i][j] += 1
            cnt_sw[c][0] += 1
            if d == 'Swinging Strike':
                a['whn'][i][j] += 1
            elif d == 'Foul':
                a['fln'][i][j] += 1
            elif d == 'In Play':
                xw = safe_float(p.get('xwOBA'))
                if has_guts and xw is not None:
                    a['bipn'][i][j] += (xw - lg_woba) / woba_scale
                    a['bipd'][i][j] += 1
        if d in TAKE_DESC:
            csd[bh][i][j] += 1
            csd_hc[(bh, c)][i][j] += 1
            if d == 'Called Strike':
                csn[bh][i][j] += 1
                cs_obs_hc[(bh, c)] += 1

    # Called-strike surface: per batter hand (PCS_BY_HAND) or pooled. Stored
    # as {hand: grid} either way so score_pitch has one lookup shape.
    if PCS_BY_HAND:
        PCS = {h: _smooth(csn[h], csd[h],
                          _gsum(csn[h]) / max(_gsum(csd[h]), 1), K_CS)
               for h in HANDS}
    else:
        pn = _zeros(); pd_ = _zeros()
        for h in HANDS:
            for i in range(NX):
                for j in range(NZ):
                    pn[i][j] += csn[h][i][j]; pd_[i][j] += csd[h][i][j]
        pooled = _smooth(pn, pd_, _gsum(pn) / max(_gsum(pd_), 1), K_CS)
        PCS = {h: pooled for h in HANDS}

    # Count-transform (CS_COUNT_TRANSFORM): keep one baseline CS surface per hand
    # and shift it per count by a single logit intercept, calibrated so the
    # predicted called-strike count matches the observed count among that
    # (hand,count)'s takes. Reshapes PCS to {hand: {count: grid}} so score_pitch
    # indexes by count. Sparse counts (< MIN_CT_TAKES) keep the base surface.
    MIN_CT_TAKES = 50
    PCS_c = {}
    for h in HANDS:
        base = PCS[h]
        PCS_c[h] = {}
        for c in COUNTS:
            delta = 0.0
            if CS_COUNT_TRANSFORM:
                tk = csd_hc.get((h, c)); obs = cs_obs_hc.get((h, c), 0)
                if tk is not None:
                    tk_n = _gsum(tk)
                    if tk_n >= MIN_CT_TAKES and 0 < obs < tk_n:
                        pred = sum(tk[i][j] * base[i][j]
                                   for i in range(NX) for j in range(NZ))
                        if pred > 0:
                            delta = _logit(obs / tk_n) - _logit(pred / tk_n)
            if delta == 0.0:
                PCS_c[h][c] = base
            else:
                PCS_c[h][c] = [[_sig(_logit(base[i][j]) + delta)
                                for j in range(NZ)] for i in range(NX)]
    PCS = PCS_c

    # League per-count swing-rate multipliers for the count-level prior.
    tot_sw = sum(v[0] for v in cnt_sw.values())
    tot_n = sum(v[1] for v in cnt_sw.values())
    overall_rate = tot_sw / tot_n if tot_n else 0.0
    cnt_mult = {c: ((v[0] / v[1]) / overall_rate if v[1] and overall_rate else 1.0)
                for c, v in cnt_sw.items()}

    WH, FL, XW, SW = {}, {}, {}, {}
    for key, a in A.items():
        swn = _gsum(a['swn']); swd = _gsum(a['swd']); bipd = _gsum(a['bipd'])
        WH[key] = _smooth(a['whn'], a['swn'], _gsum(a['whn']) / max(swn, 1), K_WHIFF)
        FL[key] = _smooth(a['fln'], a['swn'], _gsum(a['fln']) / max(swn, 1), K_FOUL)
        XW[key] = _smooth(a['bipn'], a['bipd'], _gsum(a['bipn']) / max(bipd, 1), K_XWCON)
        coll = _smooth(a['swn'], a['swd'], swn / swd if swd else 0.0, K_SWING_COLL)
        if SWING_PRIOR_COUNT_LEVEL:
            SW[key] = {}
            for c in COUNTS:
                m = cnt_mult.get(c, 1.0)
                prior_c = [[min(1.0, coll[i][j] * m) for j in range(NZ)]
                           for i in range(NX)]
                SW[key][c] = _smooth(AC[(key, c)]['swn'], AC[(key, c)]['swd'],
                                     prior_c, K_SWING_COUNT)
        else:
            SW[key] = {c: _smooth(AC[(key, c)]['swn'], AC[(key, c)]['swd'], coll, K_SWING_COUNT)
                       for c in COUNTS}

    # Count-anchoring offsets for the BIP value branch (empty dict = off).
    BIPOFF = (build_bip_count_offsets(baseline, lg_woba, woba_scale)
              if (BIP_COUNT_ANCHOR and has_guts) else {})

    return {'RV': RV, 'PCS': PCS, 'WH': WH, 'FL': FL, 'XW': XW, 'SW': SW,
            'BIPOFF': BIPOFF}


# ═════════════════════════════════════════════════════════════════════════
#  SCORE
# ═════════════════════════════════════════════════════════════════════════
def score_pitch(p, S):
    """Expected hitter-perspective RV for one pitch (lower = better for the
    pitcher). None if context missing or the (group,hand) surface is absent."""
    key = (group_of(p), p.get('Bats'), p.get('Throws'))
    if key not in S['WH']:
        return None
    c = get_count(p)
    px = safe_float(p.get('PlateX')); zn = _znorm(p)
    if c is None or px is None or zn is None:
        return None
    i = _xbin(px); j = _zbin(zn)
    psw = S['SW'][key][c][i][j]
    pwh = S['WH'][key][i][j]
    pfl = S['FL'][key][i][j]
    pbip = max(0.0, 1.0 - pwh - pfl)
    # BIP value count-anchored into the same delta-RE currency as the other
    # four outcome values (offset dict is empty when the option is off).
    vbip = S['XW'][key][i][j] + S['BIPOFF'].get(c, 0.0)
    pcs = S['PCS'][p['Bats']][c][i][j]
    RV = S['RV']
    swing_val = pwh * RV['whiff'].get(c, 0.0) + pfl * RV['foul'].get(c, 0.0) + pbip * vbip
    take_val = pcs * RV['cs'].get(c, 0.0) + (1 - pcs) * RV['ball'].get(c, 0.0)
    return psw * swing_val + (1 - psw) * take_val


def _aggregate(pitches_by_key, S, want_zone=False, want_heatmap=False):
    """Mean ExpRV per key, plus optional zone rollups / heatmap grid."""
    out = {}
    for key, pitches in pitches_by_key.items():
        vals = []
        zone_acc = defaultdict(list) if want_zone else None
        cell_acc = defaultdict(lambda: [0.0, 0]) if want_heatmap else None
        for p in pitches:
            if not _is_scorable(p):
                continue
            v = score_pitch(p, S)
            if v is None:
                continue
            vals.append(v)
            if want_zone:
                z = classify_zone(p)
                if z is not None:
                    zone_acc[z].append(v)
            if want_heatmap:
                i = _xbin(safe_float(p.get('PlateX'))); j = _zbin(_znorm(p))
                cell_acc[(i, j)][0] += v; cell_acc[(i, j)][1] += 1
        if not vals:
            continue
        rec = {'raw_loc': sum(vals) / len(vals), 'n_pitches': len(vals)}
        if want_zone:
            rec['zone_loc'] = {z: (sum(vs) / len(vs) if vs else None)
                               for z, vs in zone_acc.items()}
        if want_heatmap:
            rec['heatmap'] = [[i, j, round(s / n, 4), n]
                              for (i, j), (s, n) in sorted(cell_acc.items())]
        out[key] = rec
    return out


# ═════════════════════════════════════════════════════════════════════════
#  REGRESS + NORMALIZE
# ═════════════════════════════════════════════════════════════════════════
def _is_combined_team(t):
    return isinstance(t, str) and t.endswith('TM') and t[:-2].isdigit()


def _pool_identity(k):
    # Player identity independent of team (team is k[1]); groups a combined
    # 2TM/3TM row with its per-team stint rows so we can keep only the combined
    # row in the normalization pool (matching the percentile-pool convention).
    return k[:1] + k[2:]


def _in_norm_pool(k, pool_filter, combined_ids):
    if not pool_filter(k):
        return False
    # Exclude per-team stint rows of a pitcher who also has a combined row.
    if not _is_combined_team(k[1]) and _pool_identity(k) in combined_ids:
        return False
    return True


def _normalize(raw, n_prior, min_pool, pool_filter):
    """Bayesian-regress each raw_loc toward the pool league mean, then z-score
    to locPlus = 100 - K·z. Adds 'raw_loc_adj', 'locPlus', 'locRuns100'.
    Mutates and returns the same dict."""
    if not raw:
        return raw
    combined_ids = {_pool_identity(k) for k in raw if _is_combined_team(k[1])}
    pool = {k: v for k, v in raw.items()
            if _in_norm_pool(k, pool_filter, combined_ids) and v['n_pitches'] >= min_pool}
    if not pool:
        for v in raw.values():
            v['raw_loc_adj'] = v['raw_loc']; v['locPlus'] = 100.0; v['locRuns100'] = 0.0
        return raw
    lg_raw = sum(v['raw_loc'] for v in pool.values()) / len(pool)
    for v in raw.values():
        n = v['n_pitches']
        v['raw_loc_adj'] = (n * v['raw_loc'] + n_prior * lg_raw) / (n + n_prior)
    pool_adj = [raw[k]['raw_loc_adj'] for k in pool]
    mu = sum(pool_adj) / len(pool_adj)
    sigma = math.sqrt(sum((x - mu) ** 2 for x in pool_adj) / len(pool_adj))
    for v in raw.values():
        if sigma > 1e-12:
            z = (v['raw_loc_adj'] - mu) / sigma
            v['locPlus'] = round(100.0 - LOC_SCALE_K * z, 1)
        else:
            v['locPlus'] = 100.0
        # interpretable tooltip: location runs saved per 100 pitches (pitcher persp)
        v['locRuns100'] = round(-(v['raw_loc_adj'] - lg_raw) * 100.0, 3)
    return raw


def _normalize_by_group(raw, group_fn, n_prior, min_pool, pool_filter):
    """Per-pitch-type rows standardized within their pitch-type GROUP.
    n_prior may be a scalar or a per-group dict (measured per-group
    stabilization constants)."""
    if not raw:
        return raw
    combined_ids = {_pool_identity(k) for k in raw if _is_combined_team(k[1])}
    by_group = defaultdict(dict)
    for k, v in raw.items():
        by_group[group_fn(k)][k] = v
    for grp, rows in by_group.items():
        grp_prior = (n_prior.get(grp, N_PRIOR_PT_DEFAULT)
                     if isinstance(n_prior, dict) else n_prior)
        pool = {k: v for k, v in rows.items()
                if _in_norm_pool(k, pool_filter, combined_ids) and v['n_pitches'] >= min_pool}
        if not pool:
            for v in rows.values():
                v['raw_loc_adj'] = v['raw_loc']; v['locPlus'] = 100.0; v['locRuns100'] = 0.0
            continue
        lg_raw = sum(v['raw_loc'] for v in pool.values()) / len(pool)
        for v in rows.values():
            n = v['n_pitches']
            v['raw_loc_adj'] = (n * v['raw_loc'] + grp_prior * lg_raw) / (n + grp_prior)
        pool_adj = [rows[k]['raw_loc_adj'] for k in pool]
        mu = sum(pool_adj) / len(pool_adj)
        sigma = math.sqrt(sum((x - mu) ** 2 for x in pool_adj) / len(pool_adj))
        for v in rows.values():
            if sigma > 1e-12:
                z = (v['raw_loc_adj'] - mu) / sigma
                v['locPlus'] = round(100.0 - LOC_SCALE_K * z, 1)
            else:
                v['locPlus'] = 100.0
            v['locRuns100'] = round(-(v['raw_loc_adj'] - lg_raw) * 100.0, 3)
    out = {}
    for rows in by_group.values():
        out.update(rows)
    return out


# ═════════════════════════════════════════════════════════════════════════
#  SERIALIZE (metadata / audit)
# ═════════════════════════════════════════════════════════════════════════
def serialize_surfaces(S):
    """Compact, JSON-friendly snapshot for metadata: config + count scalars +
    the league value surface per group×hand (the count-collapsed ExpRV proxy
    is reconstructable client-side from these if needed for a league heatmap)."""
    return {
        'config': {'binX_in': 2.0, 'binZ_frac': BIN_Z, 'nx': NX, 'nz': NZ,
                   'xMin': X_MIN, 'xMax': X_MAX, 'zMin': Z_MIN, 'zMax': Z_MAX,
                   'physX_in': PHYS_X_IN, 'physZ_frac': PHYS_Z_FRAC,
                   'scaleK': LOC_SCALE_K, 'nPriorOverall': N_PRIOR_OVERALL,
                   'nPriorPt': N_PRIOR_PT, 'groups': GROUPS,
                   'pcsByHand': PCS_BY_HAND,
                   'bipCountAnchor': BIP_COUNT_ANCHOR,
                   'swingPriorCountLevel': SWING_PRIOR_COUNT_LEVEL,
                   'csCountTransform': CS_COUNT_TRANSFORM},
        'countValues': {slot: {f"{c[0]}-{c[1]}": round(v, 5) for c, v in d.items()}
                        for slot, d in S['RV'].items()},
    }


# ═════════════════════════════════════════════════════════════════════════
#  MAIN ENTRY
# ═════════════════════════════════════════════════════════════════════════
def compute_loc_plus(all_pitches, pitches_by_pitcher, pitches_by_pitch_type,
                     lg_woba, woba_scale):
    """Main entry point. Signature preserved for process_data.py.

    Returns:
        pitcher_results: dict[(pitcher, team, throws)] ->
            {locPlus, raw_loc_adj, n_pitches, zone_loc, heatmap, locRuns100}
        pitch_results:   dict[(pitcher, team, pitch_type, throws)] ->
            {locPlus, raw_loc_adj, n_pitches, locRuns100}  (std within group)
        weight_table_json: metadata dict
    """
    baseline = [p for p in all_pitches if is_eligible_baseline(p)]
    S = build_surfaces(baseline, lg_woba, woba_scale)

    pitcher_raw = _aggregate(pitches_by_pitcher, S, want_zone=True, want_heatmap=True)
    pitcher_results = _normalize(
        pitcher_raw, N_PRIOR_OVERALL, MIN_POOL_OVERALL,
        pool_filter=lambda k: k[1] not in AAA_TEAMS)

    pitch_raw = _aggregate(pitches_by_pitch_type, S)
    pitch_results = _normalize_by_group(
        pitch_raw, group_fn=lambda k: group_of_code(k[2]),
        n_prior=N_PRIOR_PT, min_pool=MIN_POOL_PT,
        pool_filter=lambda k: k[1] not in AAA_TEAMS)

    return pitcher_results, pitch_results, serialize_surfaces(S)


# ═════════════════════════════════════════════════════════════════════════
#  STANDALONE VALIDATION  (reproduces the V3 lab leaderboard)
# ═════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    import pickle, os
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, 'data', 'all_pitches_rs_cache.pkl'), 'rb') as f:
        ALL = pickle.load(f)
    by_pitcher = defaultdict(list)
    by_pt = defaultdict(list)
    for p in ALL:
        k = (p.get('Pitcher'), p.get('PTeam'), p.get('Throws'))
        by_pitcher[k].append(p)
        by_pt[(p.get('Pitcher'), p.get('PTeam'), p.get('Pitch Type'), p.get('Throws'))].append(p)
    pr, ptr, meta = compute_loc_plus(ALL, by_pitcher, by_pt,
                                     lg_woba=0.3169, woba_scale=1.2393)
    qual = {k: v for k, v in pr.items() if v['n_pitches'] >= 400
            and k[1] not in AAA_TEAMS}
    order = sorted(qual, key=lambda k: -qual[k]['locPlus'])
    vals = [qual[k]['locPlus'] for k in order]
    print(f"qualified pitchers (>=400 pitches): {len(qual)}")
    print(f"locPlus range: {min(vals):.0f} .. {max(vals):.0f}   "
          f"mean={sum(vals)/len(vals):.1f}")
    print("\nTOP 10:")
    for k in order[:10]:
        v = qual[k]
        print(f"  {k[0]:24s} {k[1]:4s}  locPlus={v['locPlus']:5.1f}  "
              f"runs/100={v['locRuns100']:+.2f}  n={v['n_pitches']}")
    print("BOTTOM 6:")
    for k in order[-6:]:
        v = qual[k]
        print(f"  {k[0]:24s} {k[1]:4s}  locPlus={v['locPlus']:5.1f}  "
              f"runs/100={v['locRuns100']:+.2f}  n={v['n_pitches']}")
    # sanity: a multi-pitch starter's per-type rows
    print("\nexample per-pitch-type rows (Skubal if present):")
    for key, v in sorted(ptr.items(), key=lambda kv: -kv[1]['n_pitches']):
        if 'Skubal' in (key[0] or ''):
            print(f"  {key[0]} {key[2]:3s} ({key[1]}): locPlus={v['locPlus']:.1f}  n={v['n_pitches']}")
