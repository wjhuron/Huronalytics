"""splits.py — hand splits for the metrics the site cannot rebuild from microData.

Per Wally (2026-10-08): under vs Hand, every leaderboard column splits except WAR, the
projections, and the counts he keeps at season value (IP, G, GS, SB, Sprint Speed); ERA
blanks. The site already splits the rates it can sum from microData. This module supplies
the rest, computed in the season run so a split can never drift from the season build:

  hitters (vs LHP / vs RHP, pitcher hand = the pitch's `Throws`)
    wRC+ (formula, park-adjusted), BB+, SD+, CT+, Process+, and the bat-tracking set.

THE RULE (the window_pool rule, and platoon_splits.py's design decision 1): only the
player's own pitches are split. Every league anchor, cell table and post-chain factor is the
SEASON's, so a split value sits on the season's ruler and vs L / vs R compare to each other
and to the season row.

HOW. process_data hands the hitter groups to `hitter_split_groups`, scores SD+ / CT+ for the
split groups in the SAME compute_sd_plus / compute_ct_plus call as the season (the
extra_groups option: same cells, season anchors, outside the anchor pool), then calls
`finish_hitter_splits` once the season metadata exists. The row stats come from
window_pool.build_window_hitter_row and the finishing chains from window_pool's shared
functions, so a split, a date window and (through the metadata) the season card are finished
by one copy of each chain.

SELF-CHECK. An 'A' (all hands) group per hitter runs through the same path. Its values must
reproduce the shipped season values; `finish_hitter_splits` reports the agreement and returns
None (nothing written) if it fails. wRC+ is exempt: the season value is FanGraphs', the split
value is the formula, which reads a couple of points different (window_pool says the same).

Output (data/splits.json.gz, loaded by the site only when vs Hand is used):
  {'hitters': {'<mlbId>|<team>': {'<key>_vsL': v, '<key>_vsR': v, ...}}}
"""
from pipeline.window_pool import (build_window_hitter_row, bb_plus_chain, plus_post_chain,
                                  process_plus_from_atoms, wrc_plus_formula)

HANDS = ('L', 'R')
ALL = 'A'
HITTER_KEYS = ('wRCplus', 'bbPlus', 'sdPlus', 'ctPlus', 'processPlus',
               'nCompSwings', 'batSpeed', 'swingLength', 'attackAngle', 'attackDirection',
               'swingPathTilt', 'squaredUpPct', 'blastPct', 'idealAAPct')
# self-check: |All-hands value - season value| allowed, per key
CHECK_TOL = {'bbPlus': 0.05, 'sdPlus': 0.05, 'ctPlus': 0.05, 'processPlus': 0.15,
             'batSpeed': 0.05, 'squaredUpPct': 0.001}
CHECK_MIN_SHARE = 0.98     # share of hitters within tolerance, per key


def hitter_split_groups(groups):
    """{(hitter, team, hand): pitches} for hand in L/R plus the 'A' self-check group."""
    out = {}
    for (b, t), ps in groups.items():
        out[(b, t, ALL)] = ps
        for h in HANDS:
            sub = [p for p in ps if p.get('Throws') == h]
            if sub:
                out[(b, t, h)] = sub
    return out


def hitter_split_rows(groups, skill_groups, woba_weights):
    """The pitch-derived split rows (stats, expected stats, bat tracking), built like the
    season row: every pitch for the ledger and xwOBA, the skill pitches (no position-player
    pitching) for xwOBAcon, exactly as process_data's hitter loop does."""
    from pipeline.compute import compute_expected_stats
    md = {'wobaWeights': woba_weights}
    out = {}
    for k, ps in groups.items():
        row = build_window_hitter_row(ps, md)
        sk = skill_groups.get(k) or []
        if len(sk) != len(ps):
            row['xwOBAcon'] = compute_expected_stats(sk, woba_weights=woba_weights).get('xwOBAcon')
        out[k] = row
    return out


def finish_hitter_splits(rows, sd_extra, ct_extra, metadata, season_rows):
    """Apply the season chains to every split row. Returns the site payload, or None
    when the All-hands self-check fails (logged)."""
    mlb_id = {(r['hitter'], r['team']): r.get('mlbId') for r in season_rows}
    season = {(r['hitter'], r['team']): r for r in season_rows}
    fin = {}
    for key, base in rows.items():
        row = dict(base)
        s, c = sd_extra.get(key), ct_extra.get(key)
        row['sdPlus'] = s['sdPlus'] if s else None
        row['_procSd'] = s['raw_sd'] if s else None
        row['ctPlus'] = c['ctPlus'] if c else None
        row['_procCt'] = c['raw_ct'] if c else None
        bb_plus_chain(row, metadata)
        plus_post_chain(row, metadata)
        process_plus_from_atoms(row, metadata)
        wrc_plus_formula(row, key[1], metadata)
        # the season row's BB+ display floor (sub-floor BIP prints blank on the site)
        floor = metadata.get('bbPlusMinBip')
        if floor and (row.get('nBip') or 0) < floor:
            row['bbPlus'] = None
        fin[key] = row

    # self-check: All-hands must reproduce the season row
    ok = True
    for k, tol in CHECK_TOL.items():
        n = good = 0
        worst = (0.0, None)
        for (b, t, h), row in fin.items():
            if h != ALL or (b, t) not in season:
                continue
            a, sv = row.get(k), season[(b, t)].get(k)
            if a is None or sv is None:
                continue
            n += 1
            d = abs(a - sv)
            good += d <= tol
            if d > worst[0]:
                worst = (d, f'{b} {t}')
        share = good / n if n else 0.0
        flag = share >= CHECK_MIN_SHARE
        ok &= flag
        print(f"  splits self-check {k:13s} {good}/{n} within {tol} ({share:.1%}), "
              f"worst {worst[0]:.4f} {worst[1]}" + ('' if flag else '   <-- FAILED'))
    if not ok:
        print('  splits NOT written: the All-hands path does not reproduce the season '
              'values. Fix pipeline/splits.py before shipping hand splits.')
        return None

    out = {}
    for (b, t, h), row in fin.items():
        if h == ALL:
            continue
        mid = mlb_id.get((b, t))
        if mid is None:
            continue
        d = out.setdefault(f'{mid}|{t}', {})
        for k in HITTER_KEYS:
            v = row.get(k)
            if v is not None:
                d[f'{k}_vs{h}'] = round(v, 6) if isinstance(v, float) else v
    print(f"  hand splits: {len(out)} hitter rows")
    return {'hitters': out}


# ── vs Pitches rows (hitter x pitch type, plus the All row and the categories) ──
HITTER_PITCH_KEYS = ('wOBA', 'xwOBAsp', 'runValue', 'xRunValue', 'rv100', 'xRv100',
                     'avgFbDist', 'avgHrDist')
HP_CHECK_TOL = {'wOBA': 0.0005, 'xwOBAsp': 0.0005, 'rv100': 1e-6, 'xRv100': 1e-6,
                'avgFbDist': 0.05}
HP_CHECK_EVERY = 10        # self-check every Nth row (the full set would double the pass)


def _hp_row_values(sub, woba_weights, xrv_fn, xwobasp_fn):
    """The season row's own functions, on a pitch subset."""
    from pipeline.compute import compute_expected_stats, compute_hitter_stats
    v = {'wOBA': compute_expected_stats(sub, woba_weights=woba_weights).get('wOBA'),
         'xwOBAsp': xwobasp_fn(sub)}
    xr = xrv_fn(sub)
    hs = compute_hitter_stats(sub)
    n = len(sub)
    # runValue comes from compute_hitter_stats and xRunValue from compute_xrv,
    # exactly as on the season row
    v['runValue'], v['xRunValue'] = hs.get('runValue'), xr.get('xRunValue')
    v['rv100'] = v['runValue'] / n * 100 if v['runValue'] is not None and n else None
    v['xRv100'] = v['xRunValue'] / n * 100 if v['xRunValue'] is not None and n else None
    v['avgFbDist'], v['avgHrDist'] = hs.get('avgFbDist'), hs.get('avgHrDist')
    return v


def hitter_pitch_splits(hp_rows, hitter_groups, categories, woba_weights, xrv_fn, xwobasp_fn):
    """{'<mlbId>|<team>|<pitchType>': {'<key>_vsL': v, ...}} for the vs Pitches rows, or None
    when the sampled All-hands self-check does not reproduce the season rows."""
    out, checks = {}, {k: [0, 0, (0.0, None)] for k in HP_CHECK_TOL}
    for i, row in enumerate(hp_rows):
        mid = row.get('mlbId')
        if mid is None:
            continue
        ps = hitter_groups.get((row['hitter'], row['team']), [])
        pt = row['pitchType']
        if pt in categories:
            cs = set(categories[pt])
            ps = [p for p in ps if p.get('Pitch Type') in cs]
        elif pt != 'All':
            ps = [p for p in ps if p.get('Pitch Type') == pt]
        if i % HP_CHECK_EVERY == 0 and ps:
            a = _hp_row_values(ps, woba_weights, xrv_fn, xwobasp_fn)
            for k, tol in HP_CHECK_TOL.items():
                x, y = a.get(k), row.get(k)
                if x is None or y is None:
                    continue
                c = checks[k]
                c[0] += 1
                d = abs(x - y)
                c[1] += d <= tol
                if d > c[2][0]:
                    c[2] = (d, f"{row['hitter']} {row['team']} {pt}")
        d = {}
        for h in HANDS:
            sub = [p for p in ps if p.get('Throws') == h]
            if not sub:
                continue
            for k, v in _hp_row_values(sub, woba_weights, xrv_fn, xwobasp_fn).items():
                if v is not None:
                    d[f'{k}_vs{h}'] = round(v, 6) if isinstance(v, float) else v
        if d:
            out[f"{mid}|{row['team']}|{pt}"] = d
    ok = True
    for k, (n, good, worst) in checks.items():
        share = good / n if n else 0.0
        flag = share >= CHECK_MIN_SHARE
        ok &= flag
        print(f"  splits self-check vsPitch {k:10s} {good}/{n} within {HP_CHECK_TOL[k]} ({share:.1%}), "
              f"worst {worst[0]:.6f} {worst[1]}" + ('' if flag else '   <-- FAILED'))
    if not ok:
        print('  vs Pitches splits NOT written: the All-hands path does not reproduce the season rows.')
        return None
    print(f"  hand splits: {len(out)} vs Pitches rows")
    return out
