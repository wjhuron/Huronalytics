"""Outing-based audit of Tyler Wells (BAL) FF/FC/SL pitch tags.

Method:
  Features per pitch: Velocity, IndVertBrk, HorzBrk, OTilt (converted to
  degrees, rotated so his arsenal spans a continuous range: FF ~ +9 deg,
  FC ~ -23, SL ~ -51; no wraparound).
  1. Robust season fit per class: per-feature mean/sd after trimming
     pitches > 3 sd on any feature (2 iterations) so mistags cannot
     corrupt the centroids.
  2. Per-outing centering: median deviation of the outing's pitches
     (all 5 pitch types) from season class medians, applied as an
     offset to every class mean for that outing.
  3. Each FF/FC/SL pitch scored by diagonal-covariance distance
     d2 = sum(z_i^2) under its tag and the adjacent alternatives
     (FF<->FC, FC<->SL only, per audit scope). Flag when an alternative
     is closer. Margin = 0.5*(d2_tag - d2_alt) + log-det term.
  4. Outing-local confirmation on (velo, IVB) centroids where the
     outing has >= 3 comparison pitches of each competing type.
  5. Full per-outing report printed for manual review.
"""
import pickle, math, json
import numpy as np
from collections import defaultdict, Counter

DATA = '/Users/wallyhuron/Huronalytics/data/all_pitches_rs_cache.pkl'
SCRATCH = '/private/tmp/claude-501/-Users-wallyhuron-Huronalytics/430b3071-b7dd-4854-b132-100cefd67fe3/scratchpad'
TYPES = ['FF', 'FC', 'SL']
ALLOWED = {'FF': ['FC'], 'FC': ['FF', 'SL'], 'SL': ['FC']}
FEATNAMES = ['velo', 'ivb', 'hb', 'otilt']

def sf(v):
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None

def tilt_deg(s):
    try:
        h, m = str(s).strip().split(':')
        dg = (((int(h) % 12) * 60 + int(m)) * 0.5) % 360
        return dg - 360 if dg > 120 else dg
    except Exception:
        return None

def deg_to_clock(dg):
    mins = (dg % 360) * 2
    h = int(mins // 60); m = int(round(mins % 60))
    if m == 60: h += 1; m = 0
    h = 12 if h % 12 == 0 else h % 12
    return f"{h}:{m:02d}"

import sys
if '--fresh' in sys.argv:
    # Pull the BAL tab live from the ALE2026 workbook so retags already made
    # in Sheets are reflected (the local pickle cache can lag).
    sys.path.insert(0, '/Users/wallyhuron/Huronalytics')
    from pipeline.fetch import _gspread_client, DIVISION_WORKBOOK_IDS, sheets_call_with_retry, read_sheet_with_retry
    gc = _gspread_client()
    sh = sheets_call_with_retry(lambda: gc.open_by_key(DIVISION_WORKBOOK_IDS['ALE2026']))
    ws = sheets_call_with_retry(lambda: sh.worksheet('BAL'))
    rows = read_sheet_with_retry(ws)
    header = rows[0]
    col_idx = {name: idx for idx, name in enumerate(header) if name}
    allp = []
    for row_num, row in enumerate(rows[1:], start=2):
        pitch = {c: (row[i] if i < len(row) and row[i] != '' else None) for c, i in col_idx.items()}
        pitch['_sheet_tab'] = 'BAL'
        pitch['_sheet_row'] = row_num
        allp.append(pitch)
    print(f"Fresh pull: {len(allp)} BAL rows from ALE2026")
else:
    with open(DATA, 'rb') as f:
        allp = pickle.load(f)
tw = [p for p in allp if p.get('Pitcher') == 'Wells, Tyler' and (p.get('PTeam') == 'BAL' or p.get('PTeam') is None or '--fresh' in sys.argv)]
for p in tw:
    p['otilt_deg'] = tilt_deg(p.get('OTilt'))
    p['rtilt_deg'] = tilt_deg(p.get('RTilt'))

def fvec(p):
    v = [sf(p['Velocity']), sf(p['IndVertBrk']), sf(p['HorzBrk']), p['otilt_deg']]
    return None if any(x is None for x in v) else np.array(v, float)

# ---- 1. robust season fits (diagonal) ----
fits = {}
for t in TYPES:
    X = np.array([fvec(p) for p in tw if p['Pitch Type'] == t and fvec(p) is not None])
    keep = np.ones(len(X), bool)
    for _ in range(2):
        mu = X[keep].mean(0); sd = X[keep].std(0, ddof=1)
        keep = (np.abs((X - mu) / sd) < 3).all(1)
    fits[t] = (mu, sd, keep.sum(), len(X))

print("Robust season fits (diagonal):")
for t in TYPES:
    mu, sd, nk, n = fits[t]
    print(f"  {t}: velo {mu[0]:5.1f} ({sd[0]:.1f})  IVB {mu[1]:5.1f} ({sd[1]:.1f})  "
          f"HB {mu[2]:5.1f} ({sd[2]:.1f})  OTilt {deg_to_clock(mu[3])} ({sd[3]*2:.0f}min)  ({nk}/{n} kept)")

med = {}
for t in ['FF', 'FC', 'SL', 'CH', 'CU']:
    for i, m in enumerate(['Velocity', 'IndVertBrk', 'HorzBrk', 'otilt_deg']):
        vals = [sf(p[m]) if m != 'otilt_deg' else p['otilt_deg'] for p in tw if p['Pitch Type'] == t]
        vals = [v for v in vals if v is not None]
        med[(t, i)] = float(np.median(vals))

def d2(x, t, off):
    mu, sd, _, _ = fits[t]
    z = (x - (mu + off)) / sd
    return float((z * z).sum()), z

def score(x, t, off):
    # gaussian log-density up to constant: -0.5*d2 - sum(log sd)
    dd, z = d2(x, t, off)
    return -0.5 * dd - float(np.log(fits[t][1]).sum()), dd, z

# ---- outing loop ----
outings = defaultdict(list)
for p in tw:
    outings[p['Game Date']].append(p)

flags = []
report = []
for dt in sorted(outings):
    ps = outings[dt]
    devs = []
    for p in ps:
        x = fvec(p)
        if x is None: continue
        devs.append([x[i] - med[(p['Pitch Type'], i)] for i in range(4)])
    off = np.median(np.array(devs), 0) if devs else np.zeros(4)

    mix = Counter(p['Pitch Type'] for p in ps)
    report.append(f"\n=== {dt}  n={len(ps)}  mix FF/FC/SL/CH/CU: "
                  f"{mix['FF']}/{mix['FC']}/{mix['SL']}/{mix['CH']}/{mix['CU']}  "
                  f"off(v,i,h,o)=({off[0]:+.1f},{off[1]:+.1f},{off[2]:+.1f},{off[3]:+.1f})")
    # sort by type then velo for readability
    for p in sorted(ps, key=lambda q: ({'FF':0,'FC':1,'SL':2,'CH':3,'CU':4}.get(q['Pitch Type'],9), -(sf(q['Velocity']) or 0))):
        t = p['Pitch Type']
        x = fvec(p)
        if x is None or t in ('CH','CU'):
            if t in ('CH','CU') and x is not None:
                report.append(f"    {t}  {x[0]:5.1f}  ivb {x[1]:5.1f}  hb {x[2]:5.1f}  ot {deg_to_clock(x[3]):>5s}")
            continue
        s_tag, d_tag, z_tag = score(x, t, off)
        alts = []
        for a in ALLOWED[t]:
            s_a, d_a, z_a = score(x, a, off)
            alts.append((s_a, a, d_a))
        alts.sort(reverse=True)
        s_alt, alt, d_alt = alts[0]
        margin = s_alt - s_tag
        flagstr = ''
        if margin > 0:
            # outing-local confirmation
            local = ''
            others_t = [fvec(q)[:2] for q in ps if q['Pitch Type'] == t and q is not p and fvec(q) is not None]
            others_a = [fvec(q)[:2] for q in ps if q['Pitch Type'] == alt and fvec(q) is not None]
            if len(others_t) >= 3 and len(others_a) >= 3:
                ct = np.mean(others_t, 0); ca = np.mean(others_a, 0)
                sc = np.array([1.1, 2.5])
                dl_t = float(np.linalg.norm((x[:2] - ct) / sc)); dl_a = float(np.linalg.norm((x[:2] - ca) / sc))
                local = f"local:{'ALT' if dl_a < dl_t else 'TAG'}({dl_t:.1f}v{dl_a:.1f})"
            flagstr = f"  <<< {t}->{alt} margin {margin:.1f} {local}"
            flags.append(dict(
                date=dt, pid=p.get('PitchID'), tab=p.get('_sheet_tab'), row=p.get('_sheet_row'),
                tag=t, alt=alt, margin=round(float(margin), 2),
                d2_tag=round(d_tag, 1), d2_alt=round(d_alt, 1),
                z_tag=[round(float(v), 1) for v in z_tag],
                velo=x[0], ivb=x[1], hb=x[2], otilt=deg_to_clock(x[3]),
                rtilt=deg_to_clock(p['rtilt_deg']) if p['rtilt_deg'] is not None else '',
                spin=sf(p.get('Spin Rate')), vaa=sf(p.get('VAA')), armangle=sf(p.get('ArmAngle')),
                batter=p.get('Batter'), count=p.get('Count'), desc=p.get('Description'),
                local=local))
        report.append(f"    {t}  {x[0]:5.1f}  ivb {x[1]:5.1f}  hb {x[2]:5.1f}  ot {deg_to_clock(x[3]):>5s}  "
                      f"d2tag {d_tag:5.1f} d2alt {d_alt:5.1f}{flagstr}")

with open(f'{SCRATCH}/wells_outing_report.txt', 'w') as f:
    f.write("\n".join(report))
with open(f'{SCRATCH}/wells_flags.json', 'w') as f:
    json.dump(flags, f, indent=1)

print(f"\n{len(flags)} candidates flagged. Sorted by margin:\n")
for r in sorted(flags, key=lambda r: -r['margin']):
    print(f"{r['date']}  {r['tag']}->{r['alt']}  margin {r['margin']:6.1f}  "
          f"velo {r['velo']:.1f} ivb {r['ivb']:5.1f} hb {r['hb']:5.1f} ot {r['otilt']:>5s} "
          f"d2 {r['d2_tag']:5.1f}->{r['d2_alt']:4.1f}  {r['local']:20s} pid={r['pid']}")
print("\nWrote wells_outing_report.txt + wells_flags.json")
