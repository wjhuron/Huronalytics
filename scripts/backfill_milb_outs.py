"""backfill_milb_outs.py — fill the Outs column for the ROC/AAA tabs.

The Triple-A feed omits `about.outs` (what Pitcher2026 reads for MLB), so every
MiLB row has a blank Outs. The value is recoverable from each pitch's
`playEvents[].count.outs`, which was verified to reproduce the stored MLB Outs
exactly (157/157 on game 822757). This writes Outs only into currently-blank
cells (guarded); it never overwrites. Runs locally (write-capable account).

  python3 scripts/backfill_milb_outs.py            # DRY RUN
  python3 scripts/backfill_milb_outs.py --apply
"""
import os, sys, time, warnings, concurrent.futures as cf
from collections import defaultdict
warnings.filterwarnings('ignore')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
import requests, gspread
import backfill_supplement as B

APPLY = '--apply' in sys.argv
FEED = "https://statsapi.mlb.com/api/v1.1/game/{}/feed/live"
MILB_BOOK = 'NLE2026'      # the book carrying ROC/AAA/FCL
MILB_TABS = ('ROC', 'AAA')


def feed_outs(pk):
    """{PitchID -> count.outs} for one game, replicating Pitcher2026 numbering."""
    try:
        plays = requests.get(FEED.format(pk), timeout=60).json()['liveData']['plays']['allPlays']
    except Exception:
        return None
    out = {}
    for play in plays:
        ab = play.get('atBatIndex', 0) + 1
        for ev in play.get('playEvents', []):
            if not ev.get('isPitch', False):
                continue
            pn = ev.get('pitchNumber') or 0
            o = (ev.get('count', {}) or {}).get('outs')
            if o is not None:
                out[f"{pk}_{ab:03d}_{pn:02d}"] = int(o)
    return out


def main():
    gc = gspread.service_account()
    sh = gc.open_by_key(B.SPREADSHEET_IDS[MILB_BOOK])
    tabs = []; pks = set()
    for name in MILB_TABS:
        ws = sh.worksheet(name)
        vals = ws.get_all_values()
        ci = {n: j for j, n in enumerate(vals[0]) if n}
        if 'PitchID' not in ci or 'Outs' not in ci:
            print(f"[{name}] no PitchID/Outs column — skipping"); continue
        tabs.append((name, ws, vals, ci))
        pc = ci['PitchID']
        for r in vals[1:]:
            p = (r[pc] if pc < len(r) else '').split('_')
            if len(p) == 3 and p[0].isdigit():
                pks.add(int(p[0]))
    print(f"MiLB tabs: {[t[0] for t in tabs]}   distinct games: {len(pks)}", flush=True)

    print("pulling feeds ...", flush=True)
    feed = {}; failed = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(feed_outs, pk): pk for pk in pks}
        for fu in cf.as_completed(futs):
            res = fu.result()
            if res is None: failed.append(futs[fu])
            else: feed.update(res)
    print(f"feed pitches with outs: {len(feed)}   failed games: {len(failed)} {failed[:6]}", flush=True)

    staged = []   # (name, ws, ri, col, outs)
    no_feed = 0
    for name, ws, vals, ci in tabs:
        pc = ci['PitchID']; oc = ci['Outs']
        blank = filled = 0
        for ri in range(1, len(vals)):
            r = vals[ri]
            cur = r[oc] if oc < len(r) else ''
            if str(cur).strip() != '':
                filled += 1; continue        # never overwrite an existing value
            blank += 1
            pid = r[pc] if pc < len(r) else ''
            if pid in feed:
                staged.append((name, ws, ri + 1, oc + 1, feed[pid]))
            else:
                no_feed += 1
        print(f"  [{name}] blank Outs={blank}  already-filled={filled}", flush=True)

    dist = defaultdict(int)
    for s in staged:
        dist[s[4]] += 1
    print(f"\nOuts cells to fill: {len(staged)}   (blank rows with no feed match: {no_feed})")
    print(f"  distribution: {dict(sorted(dist.items()))}")

    if not APPLY:
        print("=== DRY RUN (no writes) ===")
        return
    byws = defaultdict(list)
    for name, ws, ri, col, o in staged:
        byws[(name, ws)].append((ri, col, o))
    total = 0
    for (name, ws), items in byws.items():
        cells = [gspread.Cell(ri, col, str(o)) for (ri, col, o) in items]
        B.update_cells_with_retry(ws, cells, value_input_option='USER_ENTERED')
        total += len(cells)
        print(f"  [{name}] wrote {len(cells)}", flush=True)
        time.sleep(1.0)
    print(f"=== APPLIED: {total} Outs cells ===")


if __name__ == '__main__':
    main()
