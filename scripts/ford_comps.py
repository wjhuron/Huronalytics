"""ford_comps.py — closest player comparisons from a stat fingerprint.

Similarity = mean |z-difference| across a stat fingerprint, z-scored over the
full comparison pool (MLB + ROC, season sample floors; ROC is measured against
MLB baselines site-wide, so cross-level shape comps are legitimate).
Distances under ~0.45 are snug. Shape comps, not talent equivalences.

Hitters: 18-feature offensive fingerprint (contact quality, batted-ball
profile, swing decisions, contact skill, bat tracking, outcomes).
Pitchers: 18-feature fingerprint (release/approach: FB velo, extension, arm
angle, VAA, |HAA|; whiff/zone: SwStr%, CSW%, IZWhiff%, Chase%, IZ%;
outcomes: K%, BB%; contact against: GB%, PU%, EV, HardHit%, Barrel%, xwOBAcon).
HAA is hand-signed in the data, so the fingerprint uses its magnitude.

The comp pool is ALWAYS MLB-only — a ROC player is never comped to another
ROC player, and z-scales come from the MLB pool. The level setting
('mlb' / 'aaa' / 'both') picks which of the TARGET's stat lines to use: a
player with time at both levels (e.g. House WSH + ROC) has one row per
team, and 'aaa' comps his ROC (AAA-only) line against MLB players. 'both'
runs every row he has. Batch mode ignores level (team picks the row).

Date ranges are recomputed from the pitch cache (window pool floors are
lower; hitters lose ev50 in window mode).

Run with NO arguments to use the SELECTION block at the bottom of the file:
edit role / player / team / level / date range there directly, then run.

Usage examples:
  python3 scripts/ford_comps.py                                  selection block
  python3 scripts/ford_comps.py --hitter "Ford, Harry" --start 2026-06-01
  python3 scripts/ford_comps.py --pitcher "Kolek, Bryce" --level mlb
  python3 scripts/ford_comps.py --team ROC --role both
  python3 scripts/ford_comps.py --team ROC --exclude "Jordan, Levi;Wallace, Cayden"
"""
import os, sys, json, pickle, math, argparse
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pipeline_utils import (safe_float as sf, NON_PA_EVENTS, BB_EVENTS,
                            K_EVENTS, BUNT_BB_TYPES,
                            spray_angle, spray_direction, SWING_DESCRIPTIONS)

FEATS_H = ['avgEVAll', 'ev50', 'hardHitPct', 'barrelPct', 'xwOBAcon',
           'gbPct', 'puPct', 'pullPct', 'airPullPct',
           'swingPct', 'izSwingPct', 'chasePct', 'whiffPct',
           'kPct', 'bbPct', 'batSpeed', 'swingLength', 'attackAngle']
NICE_H = {'avgEVAll': 'EV', 'ev50': 'EV50', 'hardHitPct': 'HardHit%',
          'barrelPct': 'Barrel%', 'xwOBAcon': 'xwOBAcon', 'gbPct': 'GB%',
          'puPct': 'PU%', 'pullPct': 'Pull%', 'airPullPct': 'AirPull%',
          'swingPct': 'Swing%', 'izSwingPct': 'IZSwing%', 'chasePct': 'Chase%',
          'whiffPct': 'Whiff%', 'kPct': 'K%', 'bbPct': 'BB%',
          'batSpeed': 'BatSpd', 'swingLength': 'SwLen', 'attackAngle': 'AttackAng'}

FEATS_P = ['fbVelo', 'extension', 'armAngle', 'vaa', 'haa',
           'kPct', 'bbPct', 'swStrPct', 'cswPct', 'izWhiffPct',
           'chasePct', 'izPct',
           'gbPct', 'puPct', 'avgEVAgainst', 'hardHitPct',
           'barrelPctAgainst', 'xwOBAcon']
NICE_P = {'fbVelo': 'FBVelo', 'extension': 'Ext', 'armAngle': 'ArmAng',
          'vaa': 'VAA', 'haa': '|HAA|', 'kPct': 'K%', 'bbPct': 'BB%',
          'swStrPct': 'SwStr%', 'cswPct': 'CSW%', 'izWhiffPct': 'IZWhiff%',
          'chasePct': 'Chase%', 'izPct': 'IZ%', 'gbPct': 'GB%', 'puPct': 'PU%',
          'avgEVAgainst': 'EV', 'hardHitPct': 'HardHit%',
          'barrelPctAgainst': 'Barrel%', 'xwOBAcon': 'xwOBAcon'}

MIN_FEATS = 12
NL = {'hitter': 'PA', 'pitcher': 'TBF'}          # sample-count label
SEASON_POOL_MIN = {'hitter': 250, 'pitcher': 150}
WINDOW_POOL_MIN = {'hitter': 100, 'pitcher': 60}
SMALL_FLAG = {'hitter': 200, 'pitcher': 150}
AAA_TEAMS = {'ROC', 'AAA'}


def zstats(pool, feats):
    out = {}
    for f in feats:
        vals = [r[f] for r in pool if r.get(f) is not None]
        m = sum(vals) / len(vals)
        s = math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))
        out[f] = (m, s if s > 0 else 1.0)
    return out


def dist(a, b, feats, stats):
    ds = []
    for f in feats:
        va, vb = a.get(f), b.get(f)
        if va is None or vb is None:
            continue
        m, s = stats[f]
        ds.append((abs((va - m) / s - (vb - m) / s), f))
    if len(ds) < MIN_FEATS:
        return None, ds
    return sum(d for d, _ in ds) / len(ds), ds


def why_lines(t, best, ds, feats, stats, nice):
    """Shared extremes (both |z|>=0.75 same sign) + the biggest gap."""
    def z(r, f):
        v = r.get(f)
        if v is None:
            return None
        m, s = stats[f]
        return (v - m) / s
    shared = []
    for f in feats:
        za, zb = z(t, f), z(best, f)
        if za is None or zb is None:
            continue
        if abs(za) >= 0.75 and abs(zb) >= 0.75 and za * zb > 0:
            shared.append((min(abs(za), abs(zb)), f, za))
    shared.sort(reverse=True)
    tr = ', '.join(f"{nice[f]} {'high' if zz > 0 else 'low'}"
                   for _, f, zz in shared[:4]) or 'league-average across the board'
    gap_d, gap_f = max(ds, key=lambda x: x[0])[0], max(ds, key=lambda x: x[0])[1]
    fmt = lambda v: f'{v:.4g}' if isinstance(v, float) else v
    return (f"   shared: {tr}\n"
            f"   biggest gap: {nice[gap_f]} (Δz {gap_d:.1f}: "
            f"{fmt(t.get(gap_f))} vs {fmt(best.get(gap_f))})")


def report(target, pool, feats, stats, label, nice, topn=5, verbose=True,
           nl='PA', small=200):
    scored = []
    for r in pool:
        d, ds = dist(target, r, feats, stats)
        if d is not None:
            scored.append((d, r, ds))
    scored.sort(key=lambda x: x[0])
    if not scored:
        print(f"\n{label}\n   (no pool candidates with >= {MIN_FEATS} shared features)")
        return []
    flag = ' [small sample]' if target['pa'] < small else ''
    print(f"\n{label}{flag}")
    for d, r, _ in scored[:topn]:
        hand = f" ({r['throws']}HP)" if r.get('throws') else ''
        print(f"   {d:.3f}  {r['name']:24s} {r['team']:3s}  {nl} {r['pa']}{hand}")
    d0, b0, ds0 = scored[0]
    print(why_lines(target, b0, ds0, feats, stats, nice))
    if verbose:
        print(f"\n   feature detail vs {b0['name']} (z-units):")
        for f in feats:
            vf, vb = target.get(f), b0.get(f)
            if vf is None or vb is None:
                continue
            m, s = stats[f]
            print(f"    {nice[f]:10s} {target['name'].split(',')[0]:12s} {vf:8.3f} "
                  f"(z{(vf-m)/s:+.2f})   {b0['name'].split(',')[0]:12s} {vb:8.3f} "
                  f"(z{(vb-m)/s:+.2f})")
    return scored[:topn]


def in_level(team, level):
    if level == 'mlb':
        return team not in AAA_TEAMS
    if level == 'aaa':
        return team in AAA_TEAMS
    return True


def load_season(role):
    fn = 'hitter_leaderboard_rs.json' if role == 'hitter' else 'pitcher_leaderboard_rs.json'
    rows = json.load(open(os.path.join(ROOT, 'data', fn)))
    season = []
    for r in rows:
        if (r.get('team') or '').endswith('TM'):
            continue
        if role == 'hitter':
            rec = {f: r.get(f) for f in FEATS_H}
            rec.update(name=r['hitter'], team=r['team'], pa=r.get('pa') or 0)
        else:
            rec = {f: r.get(f) for f in FEATS_P}
            haa = r.get('haa')
            rec['haa'] = abs(haa) if haa is not None else None
            rec.update(name=r['pitcher'], team=r['team'], pa=r.get('tbf') or 0,
                       ip=sf(r.get('ip')), throws=r.get('throws'))
        season.append(rec)
    return season


def _load_cache(start, end):
    D = pickle.load(open(os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl'), 'rb'))
    for p in D:
        d = p.get('Game Date') or ''
        if d < start or (end and d > end):
            continue
        yield p


def window_hitters(start, end=None):
    """Recompute the hitter fingerprint from the pitch cache for the window."""
    agg = defaultdict(lambda: defaultdict(float))
    for p in _load_cache(start, end):
        h, t = p.get('Batter'), p.get('BTeam')
        if not h or not t:
            continue
        a = agg[(h, t)]
        desc = p.get('Description')
        ev_field = sf(p.get('ExitVelo'))
        a['pitches'] += 1
        in_z = p.get('InZone') == 'Yes'
        if in_z:
            a['iz'] += 1
        is_swing = desc in SWING_DESCRIPTIONS and 'Bunt' not in (desc or '')
        if is_swing:
            a['sw'] += 1
            if in_z:
                a['izsw'] += 1
            else:
                a['oozsw'] += 1
            if desc == 'Swinging Strike':
                a['wh'] += 1
            bs, sl = sf(p.get('BatSpeed')), sf(p.get('SwingLength'))
            aa = sf(p.get('AttackAngle'))
            if bs is not None and bs > 50:
                a['bs_sum'] += bs; a['bs_n'] += 1
            if sl is not None:
                a['sl_sum'] += sl; a['sl_n'] += 1
            if aa is not None:
                a['aa_sum'] += aa; a['aa_n'] += 1
        if not in_z:
            a['ooz'] += 1
        ev = p.get('Event')
        if ev and ev not in NON_PA_EVENTS and ev != 'Intent Walk':
            a['pa'] += 1
            if ev in K_EVENTS:
                a['k'] += 1
            elif ev in BB_EVENTS:
                a['bb'] += 1
        bb_type = p.get('BBType')
        if desc == 'In Play' and bb_type and bb_type not in BUNT_BB_TYPES:
            a['bip'] += 1
            if bb_type == 'ground_ball':
                a['gb'] += 1
            if bb_type == 'popup':
                a['pu'] += 1
            if ev_field is not None:
                a['ev_sum'] += ev_field; a['ev_n'] += 1
                if ev_field >= 95:
                    a['hh'] += 1
            try:
                if int(sf(p.get('Barrel')) or 0) == 6:   # lsa code 6 = barrel
                    a['barrel'] += 1
            except (TypeError, ValueError):
                pass
            xw = sf(p.get('xwOBA'))
            if xw is not None:
                a['xw_sum'] += xw; a['xw_n'] += 1
            d_dir = spray_direction(spray_angle(sf(p.get('HC_X')), sf(p.get('HC_Y'))),
                                    p.get('Bats'))
            if d_dir in ('pull', 'pull_side'):
                a['pull'] += 1
                if bb_type in ('line_drive', 'fly_ball'):
                    a['airpull'] += 1
    out = []
    for (h, t), a in agg.items():
        bip, sw, pa_n = a['bip'], a['sw'], a['pa']
        if bip < 25 or sw < 50 or pa_n < 50:
            continue
        out.append(dict(
            name=h, team=t, pa=int(pa_n),
            avgEVAll=a['ev_sum'] / a['ev_n'] if a['ev_n'] else None,
            hardHitPct=a['hh'] / a['ev_n'] if a['ev_n'] else None,
            barrelPct=a['barrel'] / bip,
            xwOBAcon=a['xw_sum'] / a['xw_n'] if a['xw_n'] else None,
            gbPct=a['gb'] / bip, puPct=a['pu'] / bip,
            pullPct=a['pull'] / bip, airPullPct=a['airpull'] / bip,
            swingPct=sw / a['pitches'],
            izSwingPct=a['izsw'] / a['iz'] if a['iz'] else None,
            chasePct=a['oozsw'] / a['ooz'] if a['ooz'] else None,
            whiffPct=a['wh'] / sw,
            kPct=a['k'] / pa_n, bbPct=a['bb'] / pa_n,
            batSpeed=a['bs_sum'] / a['bs_n'] if a['bs_n'] >= 20 else None,
            swingLength=a['sl_sum'] / a['sl_n'] if a['sl_n'] >= 20 else None,
            attackAngle=a['aa_sum'] / a['aa_n'] if a['aa_n'] >= 20 else None,
        ))
    return out


def window_pitchers(start, end=None):
    """Recompute the pitcher fingerprint from the pitch cache for the window.

    fbVelo / VAA / HAA come from the pitcher's primary fastball (the more-used
    of FF/SI in the window), matching the season leaderboard's FB framing.
    """
    agg = defaultdict(lambda: defaultdict(float))
    throws = {}
    for p in _load_cache(start, end):
        h, t = p.get('Pitcher'), p.get('PTeam')
        if not h or not t:
            continue
        a = agg[(h, t)]
        if p.get('Throws'):
            throws[(h, t)] = p['Throws']
        desc = p.get('Description')
        a['pitches'] += 1
        ext, ang = sf(p.get('Extension')), sf(p.get('ArmAngle'))
        if ext is not None:
            a['ext_sum'] += ext; a['ext_n'] += 1
        if ang is not None:
            a['ang_sum'] += ang; a['ang_n'] += 1
        pt = p.get('Pitch Type')
        if pt in ('FF', 'SI'):
            v, va, ha = sf(p.get('Velocity')), sf(p.get('VAA')), sf(p.get('HAA'))
            a[f'{pt}_n'] += 1
            if v is not None:
                a[f'{pt}_v_sum'] += v; a[f'{pt}_v_n'] += 1
            if va is not None:
                a[f'{pt}_vaa_sum'] += va; a[f'{pt}_vaa_n'] += 1
            if ha is not None:
                a[f'{pt}_haa_sum'] += ha; a[f'{pt}_haa_n'] += 1
        in_z = p.get('InZone') == 'Yes'
        if in_z:
            a['iz'] += 1
        else:
            a['ooz'] += 1
        is_swing = desc in SWING_DESCRIPTIONS and 'Bunt' not in (desc or '')
        if is_swing:
            a['sw'] += 1
            if in_z:
                a['izsw'] += 1
            else:
                a['oozsw'] += 1
            if desc == 'Swinging Strike':
                a['wh'] += 1
                if in_z:
                    a['izwh'] += 1
        if desc == 'Called Strike':
            a['cs'] += 1
        ev = p.get('Event')
        if ev and ev not in NON_PA_EVENTS and ev != 'Intent Walk':
            a['tbf'] += 1
            if ev in K_EVENTS:
                a['k'] += 1
            elif ev in BB_EVENTS:
                a['bb'] += 1
        bb_type = p.get('BBType')
        if desc == 'In Play' and bb_type and bb_type not in BUNT_BB_TYPES:
            a['bip'] += 1
            if bb_type == 'ground_ball':
                a['gb'] += 1
            if bb_type == 'popup':
                a['pu'] += 1
            ev_f = sf(p.get('ExitVelo'))
            if ev_f is not None:
                a['ev_sum'] += ev_f; a['ev_n'] += 1
                if ev_f >= 95:
                    a['hh'] += 1
            try:
                if int(sf(p.get('Barrel')) or 0) == 6:   # lsa code 6 = barrel
                    a['barrel'] += 1
            except (TypeError, ValueError):
                pass
            xw = sf(p.get('xwOBA'))
            if xw is not None:
                a['xw_sum'] += xw; a['xw_n'] += 1
    out = []
    for (h, t), a in agg.items():
        bip, sw, tbf = a['bip'], a['sw'], a['tbf']
        if a['pitches'] < 200 or tbf < 50 or bip < 30:
            continue
        fb = 'FF' if a['FF_n'] >= a['SI_n'] else 'SI'
        haa = (a[f'{fb}_haa_sum'] / a[f'{fb}_haa_n']) if a[f'{fb}_haa_n'] else None
        out.append(dict(
            # no outs-recorded field in the cache; IP estimated at 4.3 TBF/inning
            name=h, team=t, pa=int(tbf), ip=round(tbf / 4.3, 1),
            throws=throws.get((h, t)),
            fbVelo=a[f'{fb}_v_sum'] / a[f'{fb}_v_n'] if a[f'{fb}_v_n'] else None,
            vaa=a[f'{fb}_vaa_sum'] / a[f'{fb}_vaa_n'] if a[f'{fb}_vaa_n'] else None,
            haa=abs(haa) if haa is not None else None,
            extension=a['ext_sum'] / a['ext_n'] if a['ext_n'] else None,
            armAngle=a['ang_sum'] / a['ang_n'] if a['ang_n'] else None,
            kPct=a['k'] / tbf, bbPct=a['bb'] / tbf,
            swStrPct=a['wh'] / a['pitches'],
            cswPct=(a['wh'] + a['cs']) / a['pitches'],
            izWhiffPct=a['izwh'] / a['izsw'] if a['izsw'] else None,
            chasePct=a['oozsw'] / a['ooz'] if a['ooz'] else None,
            izPct=a['iz'] / a['pitches'],
            gbPct=a['gb'] / bip, puPct=a['pu'] / bip,
            avgEVAgainst=a['ev_sum'] / a['ev_n'] if a['ev_n'] else None,
            hardHitPct=a['hh'] / a['ev_n'] if a['ev_n'] else None,
            barrelPctAgainst=a['barrel'] / bip,
            xwOBAcon=a['xw_sum'] / a['xw_n'] if a['xw_n'] else None,
        ))
    return out


def get_rows(role, start=None, end=None):
    """Rows + feats + windowed flag for a role and optional date range."""
    if start or end:
        rows = (window_hitters(start or '2026-01-01', end) if role == 'hitter'
                else window_pitchers(start or '2026-01-01', end))
        feats = ([f for f in FEATS_H if f != 'ev50'] if role == 'hitter'
                 else FEATS_P)
        return rows, feats, True
    return load_season(role), (FEATS_H if role == 'hitter' else FEATS_P), False


def range_label(start, end):
    if not start and not end:
        return 'full season'
    return f"{start or 'season start'} -> {end or 'now'}"


def big_enough(r, role, args):
    """Batch target floor: min_pa (PA) for hitters, min_ip (IP) for pitchers."""
    if role == 'hitter':
        return r['pa'] >= args.min_pa
    return r.get('ip') is not None and r['ip'] >= args.min_ip


def run_role(role, args):
    """One role's worth of reports (single player or team batch)."""
    nice = NICE_H if role == 'hitter' else NICE_P
    nl, small = NL[role], SMALL_FLAG[role]
    rows, feats, windowed = get_rows(role, args.start, args.end)
    pool_min = (WINDOW_POOL_MIN if windowed else SEASON_POOL_MIN)[role]
    # comp pool is ALWAYS MLB-only: never comp a ROC player to another ROC player
    mlb_pool = [r for r in rows if r['pa'] >= pool_min
                and r['team'] not in AAA_TEAMS]
    stats = zstats(mlb_pool, feats)          # z-scales from the MLB pool
    rlab = range_label(args.start, args.end)

    def pool_for(t):
        return [r for r in mlb_pool
                if (r['name'], r['team']) != (t['name'], t['team'])]

    if args.team:
        excl = {n.strip() for n in args.exclude.split(';') if n.strip()}
        targets = [r for r in rows if r['team'] == args.team
                   and r['name'] not in excl and big_enough(r, role, args)]
        targets.sort(key=lambda r: -r['pa'])
        floor = (f"{args.min_pa} PA" if role == 'hitter' else f"{args.min_ip} IP")
        if not targets:
            print(f"\n(no {args.team} {role}s over {floor} — {rlab})")
        for t in targets:
            report(t, pool_for(t), feats, stats,
                   f"{t['name']} ({t['team']}, {nl} {t['pa']}) — {rlab}",
                   nice, topn=3, verbose=False, nl=nl, small=small)
        return

    # single player: level picks which of their stat lines to use as the target
    name = args.player
    matches = [r for r in rows if r['name'] == name
               and in_level(r['team'], args.level)]
    if args.player_team:
        matches = [r for r in matches if r['team'] == args.player_team]
    if not matches:
        print(f"\n({name} not found as a {role} at level '{args.level}' — {rlab}"
              f"{' (below window sample floors?)' if windowed else ''})")
        return
    for t in matches:
        pool = pool_for(t)
        report(t, pool, feats, stats,
               f"{name} ({t['team']}) — {rlab.upper()} ({nl} {t['pa']}, "
               f"pool {len(pool)})",
               nice, nl=nl, small=small)


def main():
    if len(sys.argv) == 1:
        interactive()
        return
    ap = argparse.ArgumentParser(description='Closest player comps')
    ap.add_argument('--hitter', default=None, help='"Last, First" single-hitter mode')
    ap.add_argument('--pitcher', default=None, help='"Last, First" single-pitcher mode')
    ap.add_argument('--hitter-team', '--player-team', dest='player_team',
                    default=None, help='pin --hitter/--pitcher to one team row')
    ap.add_argument('--role', choices=['hitter', 'pitcher', 'both'],
                    default='hitter', help='batch mode roles (default hitter)')
    ap.add_argument('--level', choices=['mlb', 'aaa', 'both'], default='both',
                    help="which of the TARGET's stat lines to use (pool is always MLB)")
    ap.add_argument('--start', default=None, help='date window start (recomputed from cache)')
    ap.add_argument('--end', default=None, help='date window end (inclusive)')
    ap.add_argument('--team', default=None, help='batch mode: all players of this team')
    ap.add_argument('--exclude', default='', help='batch mode: semicolon-separated names to skip')
    ap.add_argument('--min-pa', type=int, default=100,
                    help='batch mode: min PA to include a hitter target')
    ap.add_argument('--min-ip', type=float, default=25,
                    help='batch mode: min IP to include a pitcher target')
    args = ap.parse_args()

    if args.team:
        args.player = None
        for r in (['hitter', 'pitcher'] if args.role == 'both' else [args.role]):
            run_role(r, args)
        return

    single = [('hitter', args.hitter), ('pitcher', args.pitcher)]
    ran = False
    for role, name in single:
        if not name:
            continue
        args.player = name
        # season report first, then the window if a range was given
        s, e = args.start, args.end
        args.start = args.end = None
        run_role(role, args)
        if s or e:
            args.start, args.end = s, e
            run_role(role, args)
            args.start = args.end = None
        args.start, args.end = s, e
        ran = True
    if not ran:
        args.player = 'Ford, Harry'
        run_role('hitter', args)


# ═══════════════════════════════════════════════════════════════════════════
# SELECTION
# ═══════════════════════════════════════════════════════════════════════════
def interactive():
    # — Settings (edit these directly, or pass command-line flags instead) —
    role       = "both"     # "hitter", "pitcher", or "both"
    player     = ""         # "Last, First" for one player, or "" for whole team
    team       = "ROC"      # batch mode: team whose players get comped
    level      = "both"     # which of the TARGET's stat lines to use: "mlb",
                            #   "aaa", or "both" (comp pool is ALWAYS MLB-only)
    start_date = None       # "yyyy-mm-dd", or None for full season
    end_date   = None       # "yyyy-mm-dd", or None for through today
    exclude    = ""         # batch mode: semicolon-separated names to skip
    min_pa     = 100        # batch mode: min PA to include a hitter
    min_ip     = 25         # batch mode: min IP to include a pitcher

    args = argparse.Namespace(player=player or None, player_team=None,
                              team=None if player else team,
                              level=level, start=start_date, end=end_date,
                              exclude=exclude, min_pa=min_pa, min_ip=min_ip)
    for r in (['hitter', 'pitcher'] if role == 'both' else [role]):
        run_role(r, args)


if __name__ == '__main__':
    main()
