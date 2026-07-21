"""ABS player grading: who challenges well, and who leaves value on the table.

Consumes the challenge dataset, value tables, and option model. Grades every
challenge and every unchallenged wrong call (truth-based, per Wally: rulings
are deterministic).

Per challenge, realized value in leveraged runs:
    overturned  -> +g  (the flip's leveraged-run gain; challenge is retained)
    upheld      -> -C(k, T)  (the option value of the challenge that was lost)

Missed opportunity: an unchallenged take where the call was actually wrong
(m > 0), the wronged team still held a challenge, and the decision clears the
matrix even through the perception model: posterior confidence at the TRUE
margin, p_side(m), >= break-even p* = C / (g + C). Missing those is a process
error by an attentive decider; near-boundary wrong calls that even perfect
attention couldn't confidently identify are NOT counted as misses.

Attribution: batting-side to the batter, fielding-side to the tracked catcher
(challenges themselves credit whoever actually challenged, incl. pitchers).

Outputs: data/abs_player_grades_2026.json + CSVs in ~/Downloads.

Usage: python3 scripts/abs_player_grades.py
"""

import csv
import json
import os
from collections import defaultdict
from datetime import date

import abs_value_engine as ve

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET = os.path.join(REPO_ROOT, "data", "abs_challenges_2026.json")
TABLES = os.path.join(REPO_ROOT, "data", "abs_value_tables_2026.json")
OPTION = os.path.join(REPO_ROOT, "data", "abs_option_model_2026.json")
OUT_JSON = os.path.join(REPO_ROOT, "data", "abs_player_grades_2026.json")
DOWNLOADS = os.path.expanduser("~/Downloads")


def posterior_at(grid, x):
    """Interpolate the [x, p] posterior grid at perceived location x."""
    if x <= grid[0][0]:
        return grid[0][1]
    if x >= grid[-1][0]:
        return grid[-1][1]
    step = grid[1][0] - grid[0][0]
    i = int((x - grid[0][0]) / step)
    x0, p0 = grid[i]
    x1, p1 = grid[i + 1]
    return p0 + (p1 - p0) * (x - x0) / (x1 - x0)


def half_innings_left(inning, half):
    inning = min(inning, 9)
    return 2 * (9 - inning) + (2 if half == "top" else 1)


def new_ledger():
    return {"chalN": 0, "chalWon": 0, "cva": 0.0, "chalMarginSum": 0.0,
            "missN": 0, "missValue": 0.0, "oppN": 0, "teams": defaultdict(int)}


def main():
    with open(DATASET) as f:
        data = json.load(f)
    with open(OPTION) as f:
        opt = json.load(f)
    tables = ve.tables_from_json(TABLES)
    thr = opt["meta"]["rulingThrIn"]
    C = {1: opt["C"]["1"], 2: opt["C"]["2"]}
    posts = {s: opt["posterior"][s] for s in ("bat", "fld")}
    game_teams = {g["gamePk"]: (g["away"], g["home"]) for g in data["games"]}

    catchers = defaultdict(new_ledger)   # id -> ledger (fielding side)
    hitters = defaultdict(new_ledger)    # id -> ledger (batting side)
    pitchers = defaultdict(new_ledger)   # pitcher-initiated challenges only
    teams = defaultdict(new_ledger)
    names = {}

    for r in data["records"]:
        if r["distMidIn"] is None:
            continue
        if r["originalCall"] == "strike":
            side, m = "bat", r["distMidIn"] - thr
            wronged = r["batSide"]
        else:
            side, m = "fld", thr - r["distMidIn"]
            wronged = "home" if r["batSide"] == "away" else "away"
        rem = r["remAway"] if wronged == "away" else r["remHome"]
        team_abbr = game_teams[r["gamePk"]][0 if wronged == "away" else 1]
        v = ve.value_of_flip(r["balls"], r["strikes"], r["bases"], r["outs"],
                             r["inning"], r["half"], r["homeScore"] - r["awayScore"],
                             tables)
        g = v["leveragedRuns"]
        T = half_innings_left(r["inning"], r["half"])
        chal = r["challenge"]

        if side == "bat":
            owner_id, owner_name = r["batterId"], r["batter"]
            book = hitters
        else:
            owner_id, owner_name = r["catcherId"], r["catcher"]
            book = catchers
        if owner_id is not None:
            led = book[owner_id]
            names[owner_id] = owner_name
            led["teams"][team_abbr] += 1
            led["oppN"] += 1

        if chal is not None and chal.get("side") == wronged:
            k = max(1, min(2, chal.get("remainingBefore") or rem or 1))
            cost = C[k][T]
            value = g if chal["overturned"] else -cost
            pid = chal.get("playerId")
            pname = chal.get("playerName")
            if chal["role"] == "batter":
                led_c = hitters[pid]
            elif chal["role"] == "pitcher":
                led_c = pitchers[pid]
            else:
                led_c = catchers[pid]
            if pid is not None:
                names[pid] = pname
            led_c["chalN"] += 1
            led_c["chalWon"] += chal["overturned"]
            led_c["cva"] += value
            led_c["chalMarginSum"] += m
            led_c["teams"][team_abbr] += 1
            teams[team_abbr]["chalN"] += 1
            teams[team_abbr]["chalWon"] += chal["overturned"]
            teams[team_abbr]["cva"] += value
        elif chal is None and m > 0 and rem > 0 and g > 0:
            k = max(1, min(2, rem))
            cost = C[k][T]
            p_star = cost / (g + cost)
            if posterior_at(posts[side], m) >= p_star:
                if owner_id is not None:
                    led["missN"] += 1
                    led["missValue"] += g
                teams[team_abbr]["missN"] += 1
                teams[team_abbr]["missValue"] += g

    def rows(book, min_opp=0):
        out = []
        for pid, led in book.items():
            if led["chalN"] == 0 and led["missN"] == 0:
                continue
            if led["oppN"] < min_opp and led["chalN"] == 0:
                continue
            team = max(led["teams"], key=led["teams"].get) if led["teams"] else ""
            out.append({
                "playerId": pid, "player": names.get(pid, str(pid)), "team": team,
                "challenges": led["chalN"], "won": led["chalWon"],
                "successPct": (100.0 * led["chalWon"] / led["chalN"]) if led["chalN"] else None,
                "cva": led["cva"],
                "avgChalMargin": (led["chalMarginSum"] / led["chalN"]) if led["chalN"] else None,
                "oppN": led["oppN"], "missN": led["missN"], "missValue": led["missValue"],
                "netValue": led["cva"] - led["missValue"],
            })
        out.sort(key=lambda r: r["netValue"], reverse=True)
        return out

    result = {
        "meta": {"generated": date.today().isoformat(),
                 "games": data["meta"]["games"], "rulingThrIn": thr,
                 "note": "values in leveraged runs; miss = policy-approved wrong "
                         "call left unchallenged with a challenge in hand"},
        "catchers": rows(catchers), "hitters": rows(hitters),
        "pitchers": rows(pitchers), "teams": rows(teams),
    }
    with open(OUT_JSON, "w") as f:
        json.dump(result, f, indent=1)
    print(f"wrote {OUT_JSON}")

    for key, fname in (("catchers", "abs_catcher_grades_2026.csv"),
                       ("hitters", "abs_hitter_grades_2026.csv"),
                       ("teams", "abs_team_grades_2026.csv")):
        path = os.path.join(DOWNLOADS, fname)
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Player" if key != "teams" else "Team", "Tm", "Challenges",
                        "Won", "Success%", "CVA", "AvgChalMargin", "Opportunities",
                        "Missed", "MissedValue", "NetValue"])
            for r in result[key]:
                w.writerow([
                    r["player"] if key != "teams" else r["team"], r["team"],
                    r["challenges"], r["won"],
                    "" if r["successPct"] is None else round(r["successPct"]),
                    round(r["cva"], 2),
                    "" if r["avgChalMargin"] is None else round(r["avgChalMargin"], 2),
                    r["oppN"], r["missN"], round(r["missValue"], 2),
                    round(r["netValue"], 2)])
        print(f"wrote {path}")

    def show(title, rs, n=8):
        print(f"\n{title}")
        for r in rs[:n]:
            sp = "" if r["successPct"] is None else f"{r['successPct']:.0f}%"
            print(f"  {r['player']:<24} {r['team']:<4} chal {r['challenges']:>2} "
                  f"({sp:>4}) CVA {r['cva']:6.2f} | miss {r['missN']:>3} "
                  f"({r['missValue']:5.2f}) | net {r['netValue']:6.2f}")

    show("TOP CATCHERS (net leveraged runs):", result["catchers"])
    show("BOTTOM CATCHERS:", sorted(result["catchers"], key=lambda r: r["netValue"])[:8])
    show("TOP HITTERS:", result["hitters"])
    show("BOTTOM HITTERS:", sorted(result["hitters"], key=lambda r: r["netValue"])[:8])
    n_miss = sum(r["missN"] for r in result["teams"])
    v_miss = sum(r["missValue"] for r in result["teams"])
    print(f"\nleague missed opportunities: {n_miss} worth {v_miss:.1f} leveraged runs")


if __name__ == "__main__":
    main()
