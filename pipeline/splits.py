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


# ── Pitchers (vs LHH / vs RHH, batter hand = the pitch's `Bats`) ──
#
# Counts, FIP, xFIP and SIERA need a box score per batter hand, which no feed
# publishes, so it is rebuilt from the pitch rows:
#   outs   the change in per-pitch `Outs` (outs BEFORE the pitch) between a pitch
#          and the next pitch of the same fielding team in the game; a half-inning
#          ends when the next pitch belongs to the other team (3 - outs). The last
#          pitch of a game has no successor, so it takes the outs its event records
#          (a walk-off can end a game short of three). At a pitching change, outs
#          beyond the old pitcher's own event (a pickoff before the reliever's first
#          pitch) go to the reliever.
#   PA     one per row carrying a plate-appearance Event, plus the no-pitch
#          intentional-walk markers (PitchID `_00`). A walk goes to the earlier
#          pitcher when he left with the count in the batter's favour (rule 9.16(h)).
# Measured against the official box on 944 MLB pitcher-team rows (2026-10-09):
# K and unintentional BB exact for all of them; TBF exact for all of them when the
# marker set is complete; outs exact for 98.3%, never off by more than 2. The rest
# are runner outs between pitches that the pitch columns cannot place.
#
# Season ruler, as for hitters: the FIP constant, league HR/FB, the SIERA constant
# and the Command+ league miss are the season's. Each group of keys ships only if
# its All-hands rebuild reproduces the season values (the self-checks below).
EV_OUTS = {e: 1 for e in (
    'Strikeout', 'Groundout', 'Flyout', 'Lineout', 'Pop Out', 'Forceout', 'Sac Fly',
    'Sac Bunt', 'Bunt Groundout', 'Bunt Pop Out', 'Bunt Lineout', 'Fielders Choice Out',
    'Caught Stealing 2B', 'Caught Stealing 3B', 'Caught Stealing Home',
    'Pickoff 1B', 'Pickoff 2B', 'Pickoff 3B', 'Pickoff Caught Stealing 2B',
    'Pickoff Caught Stealing 3B', 'Pickoff Caught Stealing Home', 'Runner Out')}
EV_OUTS.update({'Grounded Into DP': 2, 'Double Play': 2, 'Strikeout Double Play': 2,
                'Sac Fly Double Play': 2, 'Sac Bunt Double Play': 2, 'Triple Play': 3})
WALK_TO_PRIOR_COUNTS = ('2-0', '2-1', '3-0', '3-1', '3-2')   # rule 9.16(h)
BOX_KEYS = ('outs', 'tbf', 'so', 'bb', 'ibb', 'hbp', 'hr')
BOX_SPLIT_KEYS = ('tbf', 'outs', 'fip', 'xFIP', 'siera')   # outs: the IP weight of a team rollup, not displayed
RV_SPLIT_KEYS = ('runValue', 'xRunValue', 'rv100', 'xRv100')
PITCHER_TOL = {'runValue': 1e-6, 'xRunValue': 1e-6, 'commandPlusRaw': 0.0005,
               'armAngle': 1e-9, 'extension': 1e-9, 'xFIP': 1e-9, 'siera_raw': 1e-9}
PITCH_TOL = {'runValue': 1e-6, 'xRunValue': 1e-6, 'maxVelo': 1e-9, 'strikePct': 1e-9,
             'twoStrikeWhiffPct': 1e-9, 'babip': 1e-9, 'releaseTiltMinutes': 1e-6}
PITCH_SPLIT_KEYS = ('runValue', 'xRunValue', 'rv100', 'xRv100', 'maxVelo', 'strikePct',
                    'twoStrikeWhiffPct', 'babip', 'releaseTilt', 'releaseTiltMinutes')


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def pitcher_hand_box(pitches, markers):
    """{(pitcher, team): {'L': {...}, 'R': {...}}} box components per batter hand,
    rebuilt from the pitch rows (see the block comment above). `markers` are the
    no-pitch intentional-walk rows. Returns (box, n_unplaced): rows that could not
    be placed (no PitchID, no Outs, no batter hand) are counted, not guessed."""
    from collections import defaultdict
    from pipeline.utils import NON_PA_EVENTS, K_EVENTS, HBP_EVENTS
    by_game = defaultdict(list)
    unplaced = 0
    for i, p in enumerate(list(pitches) + list(markers)):
        parts = str(p.get('PitchID') or '').split('_')
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
            unplaced += 1
            continue
        by_game[parts[0]].append((int(parts[1]), int(parts[2]), i, p))
    box = defaultdict(lambda: {h: dict.fromkeys(BOX_KEYS, 0) for h in HANDS})

    def add(p, k, n=1):
        h = p.get('Bats')
        if h in HANDS:
            box[(p.get('Pitcher'), p.get('PTeam'))][h][k] += n
            return True
        return False

    for seq in by_game.values():
        # The marker writer (scripts/audits/enumerate_missing_ibb.py) numbers the
        # at-bat with the feed's 0-based atBatIndex, the scraper with atBatIndex + 1,
        # so a marker can share its number with the previous at-bat. A marker whose
        # number real pitches already hold belongs one at-bat later.
        taken = {ab for ab, n, _i, _p in seq if n != 0}
        seq = sorted(((ab + 1 if n == 0 and ab in taken else ab), n, i, p) for ab, n, i, p in seq)
        at_bat = defaultdict(list)
        for ab, n, _i, p in seq:
            if n != 0:
                at_bat[ab].append(p)
        ps = [(ab, p) for ab, _n, _i, p in seq]
        for j, (ab, p) in enumerate(ps):
            ev = p.get('Event') or ''
            o = _int(p.get('Outs'))
            q = ps[j + 1][1] if j + 1 < len(ps) else None
            if o is None:
                unplaced += 1
            else:
                if q is not None and q.get('PTeam') == p.get('PTeam'):
                    qo = _int(q.get('Outs'))
                    gained = (qo - o if qo >= o else 3 - o) if qo is not None else 0
                    if q.get('Pitcher') != p.get('Pitcher') and ev in EV_OUTS and gained > EV_OUTS[ev]:
                        add(q, 'outs', gained - EV_OUTS[ev])
                        gained = EV_OUTS[ev]
                elif q is not None:
                    gained = 3 - o
                else:
                    gained = min(EV_OUTS.get(ev, 0), 3 - o)
                if gained and not add(p, 'outs', gained):
                    unplaced += 1
            if not ev or ev in NON_PA_EVENTS:
                continue
            who = p
            if ev == 'Walk':
                pa = at_bat.get(ab, [])
                chg = [k for k in range(1, len(pa)) if pa[k].get('Pitcher') != pa[k - 1].get('Pitcher')]
                if chg and pa[chg[-1]].get('Count') in WALK_TO_PRIOR_COUNTS:
                    who = pa[chg[-1] - 1]
            if not add(who, 'tbf'):
                unplaced += 1
                continue
            add(who, 'so', ev in K_EVENTS)
            add(who, 'bb', ev in ('Walk', 'Intent Walk'))
            add(who, 'ibb', ev == 'Intent Walk')
            add(who, 'hbp', ev in HBP_EVENTS)
            add(who, 'hr', ev == 'Home Run')
    return box, unplaced


def _check(name, pairs, tol):
    """pairs = [(label, rebuilt, season)]; prints the agreement, returns pass/fail."""
    n = good = 0
    worst = (0.0, None)
    for label, a, sv in pairs:
        if a is None or sv is None:
            continue
        n += 1
        d = abs(a - sv)
        good += d <= tol
        if d > worst[0]:
            worst = (d, label)
    share = good / n if n else 0.0
    ok = n > 0 and share >= CHECK_MIN_SHARE
    print(f"  splits self-check pitcher {name:18s} {good}/{n} within {tol} ({share:.1%}), "
          f"worst {worst[0]:.6g} {worst[1]}" + ('' if ok else '   <-- FAILED'))
    return ok


def pitcher_splits(rows, pitch_rows, pitcher_groups, pitch_groups, stints, box, ctx):
    """The pitcher and Arsenal hand splits.

    rows / pitch_rows   season pitcher / pitch-type rows (pitcher rows still carry `_box`)
    pitcher_groups      {(pitcher, team, throws): pitches}, combined rows included
    pitch_groups        {(pitcher, team, pitchType, throws): pitches}
    stints              {(pitcher, throws): [team, ...]} for combined 2TM.. rows
    box                 pitcher_hand_box output
    ctx                 season constants: fip_constant, lg_hr_fb, siera_constant,
                        cmd_mu, xrv_kwargs, aaa_teams, is_combined
    Returns {'pitchers': {...}, 'pitches': {...}}; a key group whose All-hands
    rebuild fails its self-check is left out (logged), so the site blanks it."""
    from collections import defaultdict
    from pipeline.compute import (compute_stats, compute_pitcher_batted_ball, compute_xrv,
                                  fip_family, METRIC_KEYS)
    from pipeline.commandplus import score_misses_by_hand
    from pipeline.utils import (safe_float, avg, round_metric, break_tilt_to_minutes,
                                circular_mean_minutes, minutes_to_tilt_display)
    aaa, is_comb = ctx['aaa_teams'], ctx['is_combined']

    def hand_box(pitcher, team, throws, h):
        teams = stints.get((pitcher, throws), []) if is_comb(team) else [team]
        out = dict.fromkeys(BOX_KEYS, 0)
        for t in teams:
            b = box.get((pitcher, t))
            if b:
                for k in BOX_KEYS:
                    out[k] += sum(b[x][k] for x in HANDS) if h == ALL else b[h][k]
        return out

    def sub(plist, h):
        return plist if h == ALL else [p for p in plist if p.get('Bats') == h]

    # ── Arsenal rows: one per (pitcher, team, pitch type), the season row's functions
    types_of = defaultdict(list)
    pitch_out = {}       # (pitcher, team, pt) -> {hand: values}
    for (pitcher, team, pt, throws), plist in pitch_groups.items():
        if not pt:
            continue
        types_of[(pitcher, team, throws)].append(pt)
        vals = {}
        for h in HANDS + (ALL,):
            s = sub(plist, h)
            if not s:
                continue
            st = compute_stats(s)
            v = {'runValue': st.get('runValue'), 'strikePct': st.get('strikePct'),
                 'twoStrikeWhiffPct': st.get('twoStrikeWhiffPct'), 'babip': st.get('babip'),
                 'xRunValue': compute_xrv(s, **ctx['xrv_kwargs']).get('xRunValue'),
                 'count': len(s)}
            v['rv100'] = v['runValue'] / len(s) * 100 if v['runValue'] is not None else None
            v['xRv100'] = v['xRunValue'] / len(s) * 100 if v['xRunValue'] is not None else None
            velos = [x for x in (safe_float(p.get('Velocity')) for p in s) if x is not None]
            v['maxVelo'] = round(max(velos), 1) if velos else None
            rt = [m for m in (break_tilt_to_minutes(p.get('RTilt')) for p in s) if m is not None]
            v['releaseTiltMinutes'] = circular_mean_minutes(rt)
            v['releaseTilt'] = minutes_to_tilt_display(v['releaseTiltMinutes'])
            vals[h] = v
        pitch_out[(pitcher, team, pt)] = vals

    pitch_ok = {}
    season_pitch = {(r['pitcher'], r['team'], r['pitchType']): r for r in pitch_rows}
    for k, tol in PITCH_TOL.items():
        pairs = [(f'{key[0]} {key[1]} {key[2]}', v[ALL].get(k), season_pitch[key].get(k))
                 for key, v in pitch_out.items() if ALL in v and key in season_pitch]
        pitch_ok[k] = _check(f'arsenal {k}', pairs, tol)
    pitch_ok['rv100'] = pitch_ok['runValue']
    pitch_ok['xRv100'] = pitch_ok['xRunValue']
    pitch_ok['releaseTilt'] = pitch_ok['releaseTiltMinutes']

    # ── Pitcher rows
    cmd = score_misses_by_hand({k: v for k, v in pitcher_groups.items()})
    pit_out = {}
    for row in rows:
        key = (row['pitcher'], row['team'], row.get('throws'))
        plist = pitcher_groups.get(key)
        if not plist:
            continue
        sbox = row.get('_box') or {}
        is_roc = row['team'] in aaa
        vals = {}
        for h in HANDS + (ALL,):
            s = sub(plist, h)
            if not s:
                continue
            v = {'count': len(s)}
            st = compute_stats(s)
            v['pa'] = st.get('pa')
            # run value: the season row's sum over its typed pitch-type rows
            rv = xrv = None
            for pt in types_of.get(key, []):
                pv = pitch_out.get((row['pitcher'], row['team'], pt), {}).get(h)
                if not pv:
                    continue
                if pv['runValue'] is not None:
                    rv = (rv or 0.0) + pv['runValue']
                if pv['xRunValue'] is not None:
                    xrv = (xrv or 0.0) + pv['xRunValue']
            v['runValue'], v['xRunValue'] = rv, xrv
            v['rv100'] = rv / len(s) * 100 if rv is not None else None
            v['xRv100'] = xrv / len(s) * 100 if xrv is not None else None
            for col in ('ArmAngle', 'Extension'):
                v[METRIC_KEYS[col]] = round_metric(col, avg([safe_float(p.get(col)) for p in s]))
            c = cmd.get(key)
            if c is not None:
                sm = sum(c[x][0] for x in HANDS) if h == ALL else c[h][0]
                n = sum(c[x][1] for x in HANDS) if h == ALL else c[h][1]
                v['commandPlusRaw'] = sm / n if n else None
                v['commandPlus'] = (round(200.0 - 100.0 * v['commandPlusRaw'] / ctx['cmd_mu'], 1)
                                    if n and ctx['cmd_mu'] else None)
            b = hand_box(row['pitcher'], row['team'], row.get('throws'), h)
            v['_box'] = b
            v['tbf'], v['outs'] = b['tbf'], b['outs']
            if not is_roc and sbox:
                bbs = compute_pitcher_batted_ball(s)
                bb_in = (st.get('nBip', 0), bbs.get('fbPct'), bbs.get('puPct'), st.get('gbPct'),
                         sbox.get('gs', 0), sbox.get('g', 1), ctx['lg_hr_fb'], ctx['fip_constant'])
                fip, xfip, sraw = fip_family(b['outs'], b['hr'], b['bb'], b['hbp'], b['so'],
                                             b['tbf'], *bb_in)
                v['fip'], v['xFIP'] = fip, xfip
                v['siera'] = (round(sraw + ctx['siera_constant'], 2)
                              if sraw is not None and ctx['siera_constant'] is not None else None)
                if h == ALL:
                    # the batted-ball inputs alone: the OFFICIAL box through the same
                    # formulas must give the season row's xFIP and raw SIERA
                    _f, v['_xfip_off'], v['_sraw_off'] = fip_family(
                        sbox['outs'], sbox['hr'], sbox['bb'], sbox['hbp'], sbox['so'],
                        sbox['tbf'], *bb_in)
            vals[h] = v
        pit_out[key] = (row, vals)

    # ── self-checks: All-hands against the season row (box: against the official box)
    mlb = [(row, vals) for row, vals in pit_out.values()
           if row['team'] not in aaa and not is_comb(row['team']) and ALL in vals]
    lab = lambda row: f"{row['pitcher']} {row['team']}"
    box_ok = all([_check(f'box {k}', [(lab(r), v[ALL]['_box'][k], (r.get('_box') or {}).get(k))
                                      for r, v in mlb if r.get('_box')], 0)
                  for k in BOX_KEYS])
    if not box_ok:
        print('  pitcher TBF/FIP/xFIP/SIERA hand splits NOT written: the rebuilt box does not '
              'reproduce the official one. If tbf/bb/ibb failed, the no-pitch intentional-walk '
              'markers are behind: python3 scripts/audits/enumerate_missing_ibb.py, then '
              'python3 scripts/ops/write_missing_ibb.py --apply')
    # the batted-ball inputs of xFIP and SIERA (the season row holds the formula
    # values until the FanGraphs override further down the run)
    box_ok &= all([_check('bb inputs xFIP', [(lab(r), v[ALL].get('_xfip_off'), r.get('xFIP'))
                                             for r, v in mlb], PITCHER_TOL['xFIP']),
                   _check('bb inputs SIERA', [(lab(r), v[ALL].get('_sraw_off'), r.get('_siera_raw'))
                                              for r, v in mlb], PITCHER_TOL['siera_raw'])])
    allr = [(row, vals) for row, vals in pit_out.values() if ALL in vals]
    rv_ok = all([_check(k, [(lab(r), v[ALL].get(k), r.get(k)) for r, v in allr], PITCHER_TOL[k])
                 for k in ('runValue', 'xRunValue')])
    cmd_ok = _check('commandPlusRaw', [(lab(r), v[ALL].get('commandPlusRaw'), r.get('commandPlusRaw'))
                                       for r, v in allr], PITCHER_TOL['commandPlusRaw'])
    phys_ok = {k: _check(k, [(lab(r), v[ALL].get(k), r.get(k)) for r, v in allr], PITCHER_TOL[k])
               for k in ('armAngle', 'extension')}

    keep = set()
    if box_ok:
        keep |= set(BOX_SPLIT_KEYS)
    if rv_ok:
        keep |= set(RV_SPLIT_KEYS)
    if cmd_ok:
        keep.add('commandPlus')
    keep |= {k for k, ok in phys_ok.items() if ok}
    keep |= {'pa', 'count'}     # inputs for the inject-time splits (hdERA, Pitcher+)
    pitchers = {}
    for row, vals in pit_out.values():
        mid = row.get('mlbId')
        if mid is None:
            continue
        d = {}
        for h in HANDS:
            for k, x in (vals.get(h) or {}).items():
                if k in keep and x is not None:
                    d[f'{k}_vs{h}'] = round(x, 6) if isinstance(x, float) else x
        if d:
            pitchers[f"{mid}|{row['team']}"] = d
    pkeep = {k for k in PITCH_SPLIT_KEYS if pitch_ok.get(k)}
    mids = {(r['pitcher'], r['team']): r.get('mlbId') for r in pitch_rows}
    pitches = {}
    for (pitcher, team, pt), vals in pitch_out.items():
        mid = mids.get((pitcher, team))
        if mid is None:
            continue
        d = {}
        for h in HANDS:
            for k, x in (vals.get(h) or {}).items():
                if k in pkeep and x is not None:
                    d[f'{k}_vs{h}'] = round(x, 6) if isinstance(x, float) else x
        if d:
            pitches[f'{mid}|{team}|{pt}'] = d
    dropped = sorted(set(BOX_SPLIT_KEYS + RV_SPLIT_KEYS + ('commandPlus', 'armAngle', 'extension')) - keep)
    print(f"  hand splits: {len(pitchers)} pitcher rows, {len(pitches)} Arsenal rows"
          + (f"; NOT written: {', '.join(dropped)}" if dropped else ''))
    return {'pitchers': pitchers, 'pitches': pitches}


# ── Inject-time pitcher splits (stuff_plus/train_stuff.py inject) ──
#
# hdERA, hdERA+ and Pitcher+ need the fresh Stuff+ and the season's hdERA and
# Pitcher+ scales, which exist only in the inject step after the pipeline, so
# they are added to the split file there. Same season-ruler rule: a split scores
# on the season pool, z statistics, anchor and baseline. Inputs per hand:
#   Stuff+, Loc+   plain means of the integer per-pitch atoms (the grade dumps),
#                  the values the site itself shows under vs Hand
#   K%, in-zone whiff%, GB%, xwOBA against   the row's own <field>_vsL/_vsR
#   PA, pitches, xRV/100                      this file (pitcher_splits)
#   park           the pitcher's SEASON park shift on xRV/100: his parks do not
#                  depend on the batter's hand
INJECT_SPLIT_KEYS = ('hdERA', 'hdERAPlus', 'pitcherPlus', 'pitcherRuns100')
# Pitcher+ 0.1: the season row's Stuff+ and Loc+ are not exactly the atom means the
# split uses (0.1 apart on ~3% of rows, 2026-10-09), so the All-hands rebuild can
# move one tenth on those rows; hdERA has no such input and must be exact.
INJECT_TOL = {'hdERA': 1e-9, 'pitcherPlus': 0.1 + 1e-9}


def read_splits(path):
    import gzip
    import json
    with gzip.open(path, 'rt') as f:
        return json.load(f)


def write_splits(path, data):
    """Atomic: build next to the target, then move."""
    import gzip
    import json
    import os
    tmp = path + '.tmp'
    with gzip.open(tmp, 'wt') as f:
        json.dump(data, f, separators=(',', ':'))
    os.replace(tmp, path)


def inject_pitcher_splits(rows, pitches, stuff_grades, loc_grades, pp_base, path,
                          aaa_teams=('ROC', 'AAA')):
    """Add hdERA / hdERA+ / Pitcher+ / pitcherRuns100 vs each hand to the split
    file at `path`. rows = the injected pitcher leaderboard (Stuff+ still at its
    1-decimal value), pitches = MLB + ROC pitch dicts, *_grades = the per-pitch
    grade dumps keyed "tab\\trow", pp_base = apply_pitcher_plus's baseline.
    Each key ships only if its All-hands rebuild reproduces the season row."""
    import os
    from collections import defaultdict
    from pipeline.pitcherplus import score_row, PRED_SLOPE, PARK_ADJ_KEY
    from pipeline.eraplus import hdera_from_xw, _HD_SCALE
    if not os.path.exists(path):
        print(f'  inject hand splits SKIPPED: {path} missing (process_data writes it)')
        return
    data = read_splits(path)
    pit = data.get('pitchers')
    if pit is None:
        print('  inject hand splits SKIPPED: the split file has no pitcher section')
        return
    if pp_base is None or not _HD_SCALE:
        print('  inject hand splits SKIPPED: no Pitcher+ baseline or hdERA scale this run')
        return
    aaa = set(aaa_teams)
    is_comb = lambda t: isinstance(t, str) and t.endswith('TM') and t[:-2].isdigit()

    # integer atoms per (pitcher, team, hand)
    atoms = defaultdict(lambda: [0, 0, 0, 0])
    for p in pitches:
        h = p.get('Bats')
        if h not in HANDS:
            continue
        k = f"{p.get('_sheet_tab')}\t{p.get('_sheet_row')}"
        a = atoms[(p.get('Pitcher'), p.get('PTeam'), h)]
        g = stuff_grades.get(k)
        if g is not None:
            a[0] += int(round(g)); a[1] += 1
        g = loc_grades.get(k)
        if g is not None:
            a[2] += int(round(g)); a[3] += 1
    stints = defaultdict(list)
    for r in rows:
        if r['team'] not in aaa and not is_comb(r['team']):
            stints[(r['pitcher'], r.get('throws'))].append(r['team'])

    def atom_mean(r, h, i):
        teams = stints.get((r['pitcher'], r.get('throws')), []) if is_comb(r['team']) else [r['team']]
        hands = HANDS if h == ALL else (h,)
        s = n = 0
        for t in teams:
            for x in hands:
                a = atoms.get((r['pitcher'], t, x))
                if a:
                    s += a[i]; n += a[i + 1]
        return s / n if n else None

    out, pairs = {}, {k: [] for k in INJECT_TOL}
    for r in rows:
        sp = pit.get(f"{r.get('mlbId')}|{r['team']}")
        park = None
        if r.get(PARK_ADJ_KEY) is not None and r.get('xRv100') is not None:
            park = r[PARK_ADJ_KEY] - r['xRv100']
        for h in HANDS + (ALL,):
            if h == ALL:
                g = lambda k: r.get(k)
                cnt, pa, xrv = r.get('count'), r.get('pa'), r.get('xRv100')
            else:
                if not sp:
                    continue
                g = lambda k, h=h: r.get(f'{k}_vs{h}')
                cnt, pa, xrv = sp.get(f'count_vs{h}'), sp.get(f'pa_vs{h}'), sp.get(f'xRv100_vs{h}')
                if not cnt:
                    continue
            st, lc = atom_mean(r, h, 0), atom_mean(r, h, 2)
            view = {'count': cnt,
                    'stuffScore': round(st, 1) if st is not None else None,
                    'locPlus': round(lc, 1) if lc is not None else None,
                    'kPct': g('kPct'), 'izWhiffPct': g('izWhiffPct'), 'gbPct': g('gbPct'),
                    'xRv100': xrv,
                    PARK_ADJ_KEY: (xrv + park) if (xrv is not None and park is not None) else None}
            pp = score_row(view, pp_base)
            dh = None if r['team'] in aaa else hdera_from_xw(g('xwOBA'), pa)
            if h == ALL:
                lab = f"{r['pitcher']} {r['team']}"
                pairs['pitcherPlus'].append((lab, pp, r.get('pitcherPlus')))
                pairs['hdERA'].append((lab, round(dh, 2) if dh is not None else None, r.get('hdERA')))
                continue
            d = out.setdefault(f"{r.get('mlbId')}|{r['team']}", {})
            if pp is not None:
                d[f'pitcherPlus_vs{h}'] = pp
                d[f'pitcherRuns100_vs{h}'] = round(PRED_SLOPE * (pp - 100.0), 2)
            if dh is not None:
                d[f'hdERA_vs{h}'] = round(dh, 2)
                d[f'hdERAPlus_vs{h}'] = round(200.0 - 100.0 * dh / _HD_SCALE['anchor'])
    ok = {k: _check(f'inject {k}', pairs[k], tol) for k, tol in INJECT_TOL.items()}
    keys = {k for k in INJECT_SPLIT_KEYS
            if ok['pitcherPlus' if k.startswith('pitcher') else 'hdERA']}
    n = 0
    for mk, d in out.items():
        tgt = pit.get(mk)
        if tgt is None:
            continue
        for k, v in d.items():
            if k.rsplit('_vs', 1)[0] in keys:
                tgt[k] = v
                n += 1
    write_splits(path, data)
    dropped = sorted(set(INJECT_SPLIT_KEYS) - keys)
    print(f'  inject hand splits: {n} values written'
          + (f"; NOT written: {', '.join(dropped)}" if dropped else ''))
