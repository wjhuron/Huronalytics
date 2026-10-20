"""Empirical cost of losing a challenge early (2026 ABS).

Natural experiment. Unit = team-game. Sample = the team's FIRST challenge of
the game, made in innings 1-3 with both challenges in hand. Treatment = that
challenge failed (team drops to one) vs won (team keeps two). On a close call
the result is mostly luck, so the headline cut keeps |true margin| <= 1 in.

Outcomes, from the top of the 4th to the end of the game, for that team:
  gain   leveraged runs gained from its overturned challenges
  missed leveraged runs on blown calls against it that it could NOT challenge
         because it had none left
  chal   challenges made

Empirical cost of the lost challenge = mean(gain | won) - mean(gain | failed).
Compared with the option model's C(2, T, d) at the top of the 4th, which is
the same quantity under the model's OPTIMAL policy.

Run from the repo root:
    python3 scripts/research/abs/early_challenge_cost.py
"""

import json
import os
import random
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "scripts", "abs"))
import abs_value_engine as ve  # noqa: E402

RULING_THR_IN = 1.4495
EARLY_MAX_INNING = 3
CLOSE_MARGIN_IN = 1.0
N_BOOT = 2000


def wronged_side_and_margin(r):
    """(team wronged by the original call, margin in inches; >0 = challenge wins)."""
    if r["originalCall"] == "strike":
        return r["batSide"], r["distMidIn"] - RULING_THR_IN
    return ("home" if r["batSide"] == "away" else "away"), RULING_THR_IN - r["distMidIn"]


def main():
    data = json.load(open(os.path.join(REPO, "data", "abs_challenges_2026.json")))
    tables = ve.tables_from_json(os.path.join(REPO, "data", "abs_value_tables_2026.json"))
    om = json.load(open(os.path.join(REPO, "data", "abs_option_model_2026.json")))
    cgrid = om["core"]["Cgrid"] if "core" in om else om["Cgrid"]

    by_game = defaultdict(list)
    for r in data["records"]:
        if r["distMidIn"] is None or r.get("posPitcher"):
            continue
        by_game[r["gamePk"]].append(r)

    units = []
    for pk, recs in by_game.items():
        recs.sort(key=lambda r: (r["inning"], r["half"] == "bottom"))  # feed order kept within half
        for team in ("away", "home"):
            first = None
            for r in recs:
                c = r["challenge"]
                if c and c.get("side") == team:
                    first = r
                    break
            if first is None or first["inning"] > EARLY_MAX_INNING:
                continue
            rem_before = first["challenge"].get("remainingBefore")
            if rem_before != 2:
                continue
            side, m = wronged_side_and_margin(first)
            if side != team:
                continue
            u = {"gamePk": pk, "team": team, "failed": not first["challenge"]["overturned"],
                 "m": m, "role": first["challenge"].get("role"), "gain": 0.0, "missed": 0.0,
                 "chal": 0}
            # team's run lead at the top of the 4th (last early record is close enough)
            late = [r for r in recs if r["inning"] > EARLY_MAX_INNING]
            if not late:
                continue
            r0 = late[0]
            lead = r0["homeScore"] - r0["awayScore"]
            u["lead4"] = lead if team == "home" else -lead
            for r in late:
                s, mm = wronged_side_and_margin(r)
                if s != team:
                    continue
                g = ve.value_of_flip(r["balls"], r["strikes"], r["bases"], r["outs"], r["inning"],
                                     r["half"], r["homeScore"] - r["awayScore"], tables)["leveragedRuns"]
                rem = r["remAway"] if team == "away" else r["remHome"]
                c = r["challenge"]
                if c and c.get("side") == team:
                    u["chal"] += 1
                    if c["overturned"]:
                        u["gain"] += g
                elif mm > 0 and rem == 0:
                    u["missed"] += g
            units.append(u)

    def summarize(sub, label):
        w = [u for u in sub if not u["failed"]]
        f = [u for u in sub if u["failed"]]
        mean = lambda xs, k: sum(x[k] for x in xs) / len(xs)
        diff = mean(w, "gain") - mean(f, "gain")
        # bootstrap by game: both teams of one game share umpire and conditions
        games = defaultdict(list)
        for u in sub:
            games[u["gamePk"]].append(u)
        keys = list(games)
        rng = random.Random(0)
        boots = []
        for _ in range(N_BOOT):
            s = [u for k in (rng.choice(keys) for _ in keys) for u in games[k]]
            bw = [u for u in s if not u["failed"]]
            bf = [u for u in s if u["failed"]]
            if bw and bf:
                boots.append(mean(bw, "gain") - mean(bf, "gain"))
        boots.sort()
        se = (sum((b - diff) ** 2 for b in boots) / len(boots)) ** 0.5
        lo, hi = boots[int(0.025 * len(boots))], boots[int(0.975 * len(boots))]
        cs = [cgrid[f"2|12|{max(-12, min(12, u['lead4']))}"] for u in sub]
        print(f"\n== {label}: n won {len(w)}, n failed {len(f)}")
        print(f"  balance  margin won {mean(w,'m'):+.2f} in, failed {mean(f,'m'):+.2f} in;"
              f"  batter share won {sum(u['role']=='batter' for u in w)/len(w):.2f},"
              f" failed {sum(u['role']=='batter' for u in f)/len(f):.2f};"
              f"  lead at 4th won {mean(w,'lead4'):+.2f}, failed {mean(f,'lead4'):+.2f}")
        print(f"  innings 4+  gain   won {mean(w,'gain'):.3f}  failed {mean(f,'gain'):.3f}")
        print(f"              missed won {mean(w,'missed'):.3f}  failed {mean(f,'missed'):.3f}")
        print(f"              chal   won {mean(w,'chal'):.2f}   failed {mean(f,'chal'):.2f}")
        print(f"  EMPIRICAL COST = {diff:.3f} lev runs  (SE {se:.3f}, 95% CI {lo:.3f} to {hi:.3f})")
        print(f"  MODEL C(2, top 4th, lead) mean = {sum(cs)/len(cs):.3f}  (optimal policy)")
        return diff, se

    print(f"{len(units)} team-games with a first challenge in innings 1-{EARLY_MAX_INNING} at k=2")
    summarize([u for u in units if abs(u["m"]) <= CLOSE_MARGIN_IN], f"close calls, |m| <= {CLOSE_MARGIN_IN} in")
    summarize(units, "all first early challenges")


if __name__ == "__main__":
    main()
