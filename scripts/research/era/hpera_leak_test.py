"""hpera_leak_test.py: does hpERA's next-season fit carry the Stuff+ target leak? (2026-11-05). Research only.
hpera_honest_refit.py reads full-season Stuff+ from data/_era_internal_stuff.json, where season B's model was fit on the other seasons, B+1 included, so the
NEXT objective's channel has seen its own target for B 2021-2024. ROS reads first-half Stuff+ of S from a model without S: clean.
CLEAN swaps each full-season value for the gate's agg_SHIPPED_{B} raw mean (model fit without B and B+1, seeds 0-2 averaged). First-half values are untouched.
Runs hpera_honest_refit.main twice, LEAK then CLEAN, and restores data/_hpera_honest_refit.json afterwards.
Usage: python3 scripts/research/era/hpera_leak_test.py
Output: console + data/_hpera_leak_test.json
"""
import contextlib, io, json, os, shutil, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'projection'))
import hpera_honest_refit as H
import pit_stuff_scale_test as T
OUT = os.path.join(ROOT, 'data', '_hpera_honest_refit.json'); BAK = OUT + '.bak_leaktest'
shutil.copy(OUT, BAK)
res = {}
try:
    print('===== LEAK (as shipped)'); H.main(); res['LEAK'] = json.load(open(OUT))
    raw, _ = T.agg_tables(); ST = H.ewf.STUFF; n_sw = n_keep = 0
    for y, d in ST.items():
        if y not in raw:
            continue
        for pid, rec in d.items():
            a = raw[y].get(pid)
            if a and 'stuff_full' in rec:
                rec['stuff_full'], rec['n_full'] = a['stuff_full'], a['n_full']; n_sw += 1
            elif 'stuff_full' in rec:
                n_keep += 1
    print(f'\n===== CLEAN: {n_sw} full-season values swapped, {n_keep} left as filed (no gate value)'); H.main(); res['CLEAN'] = json.load(open(OUT))
finally:
    shutil.move(BAK, OUT)
json.dump(res, open(os.path.join(ROOT, 'data', '_hpera_leak_test.json'), 'w'), indent=1, default=float)
print('restored', OUT)
