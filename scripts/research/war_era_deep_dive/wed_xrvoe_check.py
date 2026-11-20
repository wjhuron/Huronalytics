"""wed_xrvoe_check.py - release check for the xRVOE shrinkage constants: run compute_xrvoe itself (the real
score-only path, through xrvoe_location_compare.capture) with the old single constant and with the new pair, and
compare the unit values. The golden harness cannot see this: xRVOE is injected by train_stuff after the pipeline.
PYTHONHASHSEED=0 .venv/bin/python scripts/research/war_era_deep_dive/wed_xrvoe_check.py"""
import sys, os, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'stuff_plus')); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'locplus'))
import train_stuff as T
REAL = T.compute_xrvoe
import xrvoe_location_compare as XC
T2, box = XC.capture(); assert T2 is T
new_pt, new_ov = REAL(box['df'], box['pitches'])
keep = (T.XRVOE_N0_PT, T.XRVOE_N0_OV); T.XRVOE_N0_PT = T.XRVOE_N0_OV = 275
old_pt, old_ov = REAL(box['df'], box['pitches']); T.XRVOE_N0_PT, T.XRVOE_N0_OV = keep
lb = {(r['pitcher'], r['team']): r for r in json.load(open(os.path.join(ROOT, 'data', 'pitcher_leaderboard_rs.json')))}
m = [(k, old_ov[k]['v'], lb[k].get('xrvoe100')) for k in old_ov if k in lb and lb[k].get('xrvoe100') is not None]
print(f"old-constant run against the shipped xrvoe100 column: {len(m)} rows, max |diff| {max(abs(a - b) for _, a, b in m):.3f}, r {np.corrcoef([a for _, a, _ in m], [b for _, _, b in m])[0, 1]:.5f}")
for tag, o, n in (('pitcher', old_ov, new_ov), ('pitch type', old_pt, new_pt)):
    ks = [k for k in o if k in n]; a = np.array([o[k]['v'] for k in ks]); b = np.array([n[k]['v'] for k in ks]); nn = np.array([o[k]['n'] for k in ks])
    raw_same = all(abs(o[k]['xrvoe'] - n[k]['xrvoe']) < 1e-9 for k in ks)
    print(f"\n{tag}: units {len(ks)} (old {len(o)}, new {len(n)}); raw xRVOE identical {raw_same}; xRVOE/100 SD {a.std():.3f} -> {b.std():.3f}; r {np.corrcoef(a, b)[0, 1]:.4f}; rank r {np.corrcoef(np.argsort(np.argsort(a)), np.argsort(np.argsort(b)))[0, 1]:.4f}; largest |value| {abs(a).max():.2f} -> {abs(b).max():.2f}")
    for lo, hi in ((150, 400), (400, 800), (800, 1500), (1500, 2500), (2500, 9999)):
        q = (nn >= lo) & (nn < hi)
        if q.sum():
            print(f"   {lo}-{hi} pitches: n {int(q.sum())}, SD {a[q].std():.3f} -> {b[q].std():.3f}, kept share {np.mean(nn[q] / (nn[q] + (T.XRVOE_N0_PT if tag == 'pitch type' else T.XRVOE_N0_OV))):.2f} (was {np.mean(nn[q] / (nn[q] + 275)):.2f})")
    top = sorted(ks, key=lambda k: -n[k]['v'])[:6]; otop = sorted(ks, key=lambda k: -o[k]['v'])[:6]
    print("   top 6 old: " + "; ".join(f"{k[0]}{' ' + k[2] if len(k) > 2 else ''} {o[k]['v']:.2f} ({o[k]['n']})" for k in otop))
    print("   top 6 new: " + "; ".join(f"{k[0]}{' ' + k[2] if len(k) > 2 else ''} {n[k]['v']:.2f} ({n[k]['n']})" for k in top))
