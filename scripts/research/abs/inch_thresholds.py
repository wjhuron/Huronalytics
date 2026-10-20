"""Break-even challenge thresholds in INCHES, by count (2026 ABS research).

The matrix gives a break-even confidence p* = C / (g + C). A player cannot
read a confidence in two seconds, so this turns p* into the perceived margin
he must see before a challenge pays, using the option model's own perception
posteriors (p(x) = P(call is wrong | perceived margin x), per side and edge).

Margin unit, the same as the option model:
  hitter (called strike): the gap between the edge of the ball and the zone;
  catcher (called ball):  how much of the ball's width covers the zone.
A positive threshold means the call must LOOK wrong by that much; a negative
one means challenge even when it looks right by that much.

For each real take in a game-state slice, the threshold is computed at that
take's exact count, runners, outs, inning, score, and challenges left; the
tables report the median per count. The optimal thresholds are then set
against the thresholds players actually used (perception x* per count class,
fitted by the option model), in the same inches.

Run from the repo root:
    python3 scripts/research/abs/inch_thresholds.py
Writes data/_abs_inch_thresholds.json (scratch).
"""

import json
import os
import statistics as st
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "scripts", "abs"))
import abs_option_model as om  # noqa: E402
import abs_value_engine as ve  # noqa: E402

COUNTS = [f"{b}-{s}" for b in range(4) for s in range(3)]
SIDES = ("fld", "bat")
REGIONS = ("side", "top", "bottom")
SLICES = {
    # name: (record filter, challenges left)
    "early_k2": (lambda r, lead: r["inning"] <= 3, 2),
    "early_k1": (lambda r, lead: r["inning"] <= 3, 1),
    "late_close_k2": (lambda r, lead: 7 <= r["inning"] <= 9 and abs(lead) <= 1, 2),
    "late_close_k1": (lambda r, lead: 7 <= r["inning"] <= 9 and abs(lead) <= 1, 1),
    # every take at the deciding team's real challenges left (k=0 skipped): the
    # like-for-like optimum for the players' pooled fitted thresholds
    "all_actual_k": (lambda r, lead: True, None),
}
OUT = os.path.join(REPO, "data", "_abs_inch_thresholds.json")


def T_for(inning, half):
    return 2 * (9 - min(inning, 9)) + (2 if half == "top" else 1)


def count_class(cnt):
    b, s = map(int, cnt.split("-"))
    return om.count_class(b, s)


def main():
    model = json.load(open(os.path.join(REPO, "data", "abs_option_model_2026.json")))
    cgrid = model["Cgrid"]
    posts = {key: [tuple(p) for p in grid] for key, grid in model["posterior"].items()}
    perception = model["perception"]
    tables = ve.tables_from_json(os.path.join(REPO, "data", "abs_value_tables_2026.json"))
    data = json.load(open(os.path.join(REPO, "data", "abs_challenges_2026.json")))

    # thresholds[slice][side|region][count] -> list of inches (None = never)
    thr = {s: defaultdict(lambda: defaultdict(list)) for s in SLICES}
    for r in data["records"]:
        if r.get("posPitcher"):
            continue
        diff = r["homeScore"] - r["awayScore"]
        bat_lead = -diff if r["half"] == "top" else diff
        g = ve.value_of_flip(r["balls"], r["strikes"], r["bases"], r["outs"], r["inning"],
                             r["half"], diff, tables)["leveragedRuns"]
        cnt = f"{r['balls']}-{r['strikes']}"
        for name, (keep, k) in SLICES.items():
            if not keep(r, bat_lead):
                continue
            for side in SIDES:
                lead = bat_lead if side == "bat" else -bat_lead
                kk = k
                if kk is None:
                    team = r["batSide"] if side == "bat" else ("home" if r["batSide"] == "away" else "away")
                    kk = min(r["remAway"] if team == "away" else r["remHome"], 2)
                    if kk <= 0:
                        continue
                c = cgrid[f"{kk}|{T_for(r['inning'], r['half'])}|{max(-12, min(12, lead))}"]
                for reg in REGIONS:
                    x = om.x_threshold(posts[f"{side}|{reg}"], c / g if g > 0 else float("inf"))
                    thr[name][f"{side}|{reg}"][cnt].append(x)

    def med(xs):
        real = [x for x in xs if x is not None]
        if len(real) < len(xs) / 2:
            return None                       # never worth it in most states
        return round(st.median(real + [om.M_RANGE] * (len(xs) - len(real))), 1)

    out = {"meta": {"unit": "perceived margin, inches",
                    "note": "median over real takes in the slice; None = not worth it in most states"},
           "tables": {}, "actual_vs_optimal": {}}
    for name in SLICES:
        out["tables"][name] = {key: {cnt: med(thr[name][key][cnt]) for cnt in COUNTS}
                               for key in thr[name]}

    # players' fitted thresholds (all innings, all k) vs the optimum over the
    # same states at the real challenges left, per count class
    for side in SIDES:
        for reg in REGIONS:
            key = f"{side}|{reg}"
            by_cls = defaultdict(list)
            for cnt in COUNTS:
                by_cls[count_class(cnt)].extend(thr["all_actual_k"][key][cnt])
            out["actual_vs_optimal"][key] = {
                cls: {"actual": round(perception[side][reg]["xStar"][cls], 1), "optimal": med(xs)}
                for cls, xs in by_cls.items()}

    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f, indent=1)
    os.replace(tmp, OUT)

    label = {"fld": "Catcher", "bat": "Hitter"}
    for name in SLICES:
        print(f"\n== {name}: perceived inches needed before a challenge pays")
        print("count  " + "  ".join(f"{label[s]}-{reg:6}" for s in SIDES for reg in REGIONS))
        for cnt in COUNTS:
            row = [out["tables"][name][f"{s}|{reg}"][cnt] for s in SIDES for reg in REGIONS]
            print(f"{cnt:5}  " + "  ".join(f"{('never' if v is None else f'{v:+.1f}'):>14}" for v in row))
    print("\n== players' actual threshold vs optimum, all states at real k: (actual, optimal) inches")
    for key, d in out["actual_vs_optimal"].items():
        print(key, {cls: (v["actual"], v["optimal"]) for cls, v in d.items()})
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
