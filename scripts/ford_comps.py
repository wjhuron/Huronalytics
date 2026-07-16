"""ford_comps.py — closest offensive comparisons from the hitter fingerprint.

Similarity = mean |z-difference| across an 18-feature offensive fingerprint
(contact quality, batted-ball profile, swing decisions, contact skill, bat
tracking, outcomes), z-scored over the comparison pool (MLB + ROC hitters,
season PA >= 250; ROC is measured against MLB baselines site-wide, so
cross-level shape comps are legitimate). Distances under ~0.45 are snug.
Shape comps, not talent equivalences.

Modes:
  --hitter "Ford, Harry" [--hitter-team ROC]     one hitter, full season
  --hitter ... --start 2026-06-01                add a date-window run
                                                 (recomputed from the pitch
                                                 cache; window pool PA >= 100)
  --team ROC [--exclude "House, Brady;..."]      batch, full season only

Usage examples:
  python3 scripts/ford_comps.py --hitter "Ford, Harry" --start 2026-06-01
  python3 scripts/ford_comps.py --team ROC --exclude "Jordan, Levi;Wallace, Cayden"
"""
import os, sys, json, pickle, math, argparse
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pipeline_utils import (safe_float as sf, NON_PA_EVENTS, BB_EVENTS,
                            K_EVENTS, BUNT_BB_TYPES,
                            spray_angle, spray_direction, SWING_DESCRIPTIONS)

FEATS = ['avgEVAll', 'ev50', 'hardHitPct', 'barrelPct', 'xwOBAcon',
         'gbPct', 'puPct', 'pullPct', 'airPullPct',
         'swingPct', 'izSwingPct', 'chasePct', 'whiffPct',
         'kPct', 'bbPct', 'batSpeed', 'swingLength', 'attackAngle']
NICE = {'avgEVAll': 'EV', 'ev50': 'EV50', 'hardHitPct': 'HardHit%',
        'barrelPct': 'Barrel%', 'xwOBAcon': 'xwOBAcon', 'gbPct': 'GB%',
        'puPct': 'PU%', 'pullPct': 'Pull%', 'airPullPct': 'AirPull%',
        'swingPct': 'Swing%', 'izSwingPct': 'IZSwing%', 'chasePct': 'Chase%',
        'whiffPct': 'Whiff%', 'kPct': 'K%', 'bbPct': 'BB%',
        'batSpeed': 'BatSpd', 'swingLength': 'SwLen', 'attackAngle': 'AttackAng'}
MIN_FEATS = 12


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


def why_lines(t, best, ds, feats, stats):
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
    tr = ', '.join(f"{NICE[f]} {'high' if zz > 0 else 'low'}"
                   for _, f, zz in shared[:4]) or 'league-average across the board'
    gap_d, gap_f = max(ds, key=lambda x: x[0])[0], max(ds, key=lambda x: x[0])[1]
    return (f"   shared: {tr}\n"
            f"   biggest gap: {NICE[gap_f]} (Δz {gap_d:.1f}: "
            f"{t.get(gap_f)} vs {best.get(gap_f)})")


def report(target, pool, feats, stats, label, topn=5, verbose=True):
    scored = []
    for r in pool:
        d, ds = dist(target, r, feats, stats)
        if d is not None:
            scored.append((d, r, ds))
    scored.sort(key=lambda x: x[0])
    flag = ' [small sample]' if target['pa'] < 200 else ''
    print(f"\n{label}{flag}")
    for d, r, _ in scored[:topn]:
        print(f"   {d:.3f}  {r['name']:24s} {r['team']:3s}  PA {r['pa']}")
    d0, b0, ds0 = scored[0]
    if b0['team'] == target['team'] == 'ROC':
        mlb = next(((d, r) for d, r, _ in scored if r['team'] != 'ROC'), None)
        if mlb:
            print(f"   best MLB: {mlb[0]:.3f}  {mlb[1]['name']} {mlb[1]['team']}")
    print(why_lines(target, b0, ds0, feats, stats))
    if verbose:
        print(f"\n   feature detail vs {b0['name']} (z-units):")
        for f in feats:
            vf, vb = target.get(f), b0.get(f)
            if vf is None or vb is None:
                continue
            m, s = stats[f]
            print(f"    {NICE[f]:10s} {target['name'].split(',')[0]:12s} {vf:8.3f} "
                  f"(z{(vf-m)/s:+.2f})   {b0['name'].split(',')[0]:12s} {vb:8.3f} "
                  f"(z{(vb-m)/s:+.2f})")
    return scored[:topn]


def load_season():
    rows = json.load(open(os.path.join(ROOT, 'data', 'hitter_leaderboard_rs.json')))
    season = []
    for r in rows:
        if (r.get('team') or '').endswith('TM'):
            continue
        rec = {f: r.get(f) for f in FEATS}
        rec.update(name=r['hitter'], team=r['team'], pa=r.get('pa') or 0)
        season.append(rec)
    return season


def window_rows(start):
    """Recompute the fingerprint from the pitch cache for dates >= start."""
    D = pickle.load(open(os.path.join(ROOT, 'data', 'all_pitches_rs_cache.pkl'), 'rb'))
    agg = defaultdict(lambda: defaultdict(float))
    for p in D:
        if (p.get('Game Date') or '') < start:
            continue
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


def main():
    ap = argparse.ArgumentParser(description='Closest offensive comps')
    ap.add_argument('--hitter', default=None, help='"Last, First" for single-hitter mode')
    ap.add_argument('--hitter-team', default='ROC', help='team of --hitter (default ROC)')
    ap.add_argument('--start', default=None, help='also run a window from this date (single mode)')
    ap.add_argument('--team', default=None, help='batch mode: all hitters of this team, full season')
    ap.add_argument('--exclude', default='', help='batch mode: semicolon-separated names to skip')
    ap.add_argument('--min-pa', type=int, default=100, help='batch mode: min PA to include a target')
    args = ap.parse_args()

    season = load_season()
    pool_all = [r for r in season if r['pa'] >= 250]
    stats = zstats(pool_all, FEATS)

    if args.team:
        excl = {n.strip() for n in args.exclude.split(';') if n.strip()}
        targets = [r for r in season if r['team'] == args.team
                   and r['name'] not in excl and r['pa'] >= args.min_pa]
        targets.sort(key=lambda r: -r['pa'])
        for t in targets:
            pool = [r for r in pool_all if (r['name'], r['team']) != (t['name'], t['team'])]
            report(t, pool, FEATS, stats,
                   f"{t['name']} ({t['team']}, PA {t['pa']}) — full season",
                   topn=3, verbose=False)
        return

    name = args.hitter or 'Ford, Harry'
    t = next(r for r in season if r['name'] == name and r['team'] == args.hitter_team)
    pool = [r for r in pool_all if (r['name'], r['team']) != (name, args.hitter_team)]
    report(t, pool, FEATS, stats, f'{name} — FULL SEASON (PA {t["pa"]}, pool {len(pool)})')

    if args.start:
        win = window_rows(args.start)
        feats_w = [f for f in FEATS if f != 'ev50']
        tw = next((r for r in win if (r['name'], r['team']) == (name, args.hitter_team)), None)
        if tw is None:
            print(f'\n(window from {args.start}: {name} below sample floors — skipped)')
            return
        pool_w = [r for r in win if (r['name'], r['team']) != (name, args.hitter_team)
                  and r['pa'] >= 100]
        stats_w = zstats(pool_w + [tw], feats_w)
        report(tw, pool_w, feats_w, stats_w,
               f'{name} — {args.start} -> NOW (PA {tw["pa"]}, pool {len(pool_w)})')


if __name__ == '__main__':
    main()
