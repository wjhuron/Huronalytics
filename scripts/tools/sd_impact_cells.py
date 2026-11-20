"""SD+ cell decomposition for the zone x count-state impact pages (2026-11-19).

Shipped SD+ is mix-neutral over (zone, two-strike flag): raw = sum over strata
(z, t) of the league share w(z,t) times the hitter's mean decision atom there
(pipeline.sdplus.league_mix_weights). The impact pages show cells (zone,
count state), where the count state is ahead / even / behind. The state is not
nested in the two-strike flag, so each displayed cell sums its two strata:

    impact(z, st) = sum_t w(z,t) * [ s_h(st | z,t) * g'_h(z,st,t)
                                     - s_lg(st | z,t) * g_lg(z,st,t) ]

s(st | z,t) = share of the stratum's decisions in that count state, g = mean
decision atom, g'_h shrunk toward g_lg with k pseudo-decisions per sub-cell.
Summed over every cell this is sum_(z,t) w(z,t) * (hitter mean - league mean),
the shipped aggregate (before the missing-stratum renormalization, the n0
shrink and the scale, which the page's kappa carries). Until this date the
formula weighted by the league ZONE share only, which counted the two-strike
mix as the hitter's doing.

One home for render_sd_zones_impact.py and sdzone_impact_sweeps.py.
An atom is (value, zone, state, two) with two = 1 in a two-strike count.
"""
import math
from collections import defaultdict

ZONES = ['heart', 'shadow_in', 'shadow_out', 'chase', 'waste']
STATES = ['ahead', 'even', 'behind']
CELLS = [(z, s) for z in ZONES for s in STATES]
TWO = (0, 1)


def sd_league(atoms):
    acc = defaultdict(lambda: [0.0, 0.0, 0])
    for v, z, st, t in atoms:
        c = acc[(z, st, t)]
        c[0] += v
        c[1] += v * v
        c[2] += 1
    tot = len(atoms)
    sub = {}
    for z in ZONES:
        for st in STATES:
            for t in TWO:
                s, ss, n = acc.get((z, st, t), [0.0, 0.0, 0])
                if n:
                    m = s / n
                    sub[(z, st, t)] = (n / tot, m, math.sqrt(max(ss / n - m * m, 0.0)))
                else:
                    sub[(z, st, t)] = (0.0, 0.0, 0.0)
    wzt = {(z, t): sum(sub[(z, st, t)][0] for st in STATES) for z in ZONES for t in TWO}
    slg = {k: (sub[k][0] / wzt[(k[0], k[2])] if wzt[(k[0], k[2])] else 0.0) for k in sub}
    # displayed league figures per (zone, state), both strata together
    joint = {}
    for z, st in CELLS:
        n = sum(acc.get((z, st, t), [0.0, 0.0, 0])[2] for t in TWO)
        s = sum(acc.get((z, st, t), [0.0, 0.0, 0])[0] for t in TWO)
        ss = sum(acc.get((z, st, t), [0.0, 0.0, 0])[1] for t in TWO)
        if n:
            m = s / n
            joint[(z, st)] = (n / tot, m, math.sqrt(max(ss / n - m * m, 0.0)))
        else:
            joint[(z, st)] = (0.0, 0.0, 0.0)
    wz = {z: sum(joint[(z, st)][0] for st in STATES) for z in ZONES}
    state = {st: sum(joint[(z, st)][0] for z in ZONES) for st in STATES}
    return {'sub': sub, 'wzt': wzt, 'slg': slg, 'joint': joint, 'wz': wz, 'state': state,
            'slg_zone': {(z, st): (joint[(z, st)][0] / wz[z] if wz[z] else 0.0) for z, st in CELLS}}


def sd_cell_agg(atoms):
    acc = defaultdict(lambda: [0.0, 0])
    for v, z, st, t in atoms:
        acc[(z, st, t)][0] += v
        acc[(z, st, t)][1] += 1
    return acc


def sd_cells_from_acc(acc, lg, k):
    """{(zone, state): dict} in uncalibrated units (kappa = 1): impact, mix,
    exec, se, and the display counts."""
    nzt = {(z, t): sum(acc.get((z, st, t), [0.0, 0])[1] for st in STATES)
           for z in ZONES for t in TWO}
    out = {}
    for z, st in CELLS:
        impact = mix = execu = var = 0.0
        n = sum(acc.get((z, st, t), [0.0, 0])[1] for t in TWO)
        s_all = sum(acc.get((z, st, t), [0.0, 0])[0] for t in TWO)
        nz = nzt[(z, 0)] + nzt[(z, 1)]
        for t in TWO:
            if nzt[(z, t)] == 0:
                continue
            _ls, lgg, sd = lg['sub'][(z, st, t)]
            s_sum, m = acc.get((z, st, t), [0.0, 0])
            w = lg['wzt'][(z, t)]
            s_h = m / nzt[(z, t)]
            s_lg = lg['slg'][(z, st, t)]
            g_shr = ((s_sum + k * lgg) / (m + k)) if m else lgg
            impact += w * (s_h * g_shr - s_lg * lgg)
            mix += w * lgg * (s_h - s_lg)
            execu += w * s_h * (g_shr - lgg)
            if m:
                se_g = sd / math.sqrt(m)
                se_s = math.sqrt(max(s_h * (1 - s_h), 1e-9) / nzt[(z, t)])
                var += (w * s_h * se_g) ** 2 + (w * lgg * se_s) ** 2
        out[(z, st)] = {'n': n, 'nz': nz, 'share': (n / nz) if nz else None,
                        'g_raw': (s_all / n) if n else None,
                        'impact': impact, 'mix': mix, 'exec': execu,
                        'se': math.sqrt(var)}
    return out
