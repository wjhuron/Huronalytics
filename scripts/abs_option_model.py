"""ABS option model: what is a held challenge worth for the rest of the game?

Consumes data/abs_challenges_2026.json (every near-zone take with full state)
and data/abs_value_tables_2026.json (flip pricing). Produces C(k, T): the
marginal value, in leveraged runs, of holding your k-th challenge with T
half-innings of regulation remaining, plus the perception model that turns a
pitch location into a challenge-success confidence.

Model:
  1. Margin m per take, from the wronged side's perspective: m > 0 means a
     challenge would succeed (ruling boundary = ball-edge rule, center within
     1.4495in of the zone at the plate-midpoint plane).
  2. Perception: deciders observe x ~ N(m, sigma). Sigma is fit per side
     (fielding = catcher eyes, batting = batter eyes) by probit MLE on
     observed challenge decisions: P(challenge | m) = Phi((m - x*) / sigma).
     Rulings are deterministic, so failed challenges exist ONLY because of
     perception noise; sigma is identified by how challenge rates ramp with
     true margin.
  3. Confidence: p(x) = P(m > 0 | x) by Bayes against the empirical margin
     prior. This is "how sure the decider can be" after seeing x.
  4. DP: V(k, T) = A(C_k) + (1 - Pf(C_k)) V(k, T-1) + Pf(C_k) V(k-1, T-1),
     linearized per half-inning over the empirical opportunity stream, where
     the optimal policy challenges iff p(x) g >= (1 - p(x)) C_k, each record's
     gain g priced by the value engine at its true game state (so blowout
     opportunities contribute ~nothing, exactly as they should).
  Successful challenges are retained: only failures decrement k.

Decision rule output: challenge iff confidence >= p* = C(k,T) / (g + C(k,T)).

Output: data/abs_option_model_2026.json.

Usage: python3 scripts/abs_option_model.py
"""

import argparse
import json
import math
import os
from collections import defaultdict
from datetime import date

import abs_value_engine as ve

RULING_THR_IN = 1.4495       # ball-edge boundary at the midpoint plane
M_RANGE = 6.0                # margin grid half-width, inches
M_BIN = 0.1
REG_HALVES = 18              # regulation half-innings per game
EPS_COST = 0.01              # nuisance friction: never challenge for less than
                             # this expected edge (stops degenerate challenge-
                             # everything behavior when a challenge is free)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET = os.path.join(REPO_ROOT, "data", "abs_challenges_2026.json")
TABLES = os.path.join(REPO_ROOT, "data", "abs_value_tables_2026.json")
DEFAULT_OUT = os.path.join(REPO_ROOT, "data", "abs_option_model_2026.json")


def phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def norm_pdf(z):
    return math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)


# ------------------------------------------------------------- opportunities

def load_opportunities(dataset_path, tables):
    """One opportunity per take, for the side wronged by the ORIGINAL call.

    Returns list of dicts: side ('bat'/'fld'), m (inches, >0 = challenge
    succeeds), g (leveraged-run gain if flipped), challenged, hadChallenge
    (wronged team had one remaining), T (half-innings of regulation left,
    current one included).
    """
    with open(dataset_path) as f:
        data = json.load(f)
    opps, side_mismatch = [], 0
    for r in data["records"]:
        if r["distMidIn"] is None:
            continue
        if r["originalCall"] == "strike":
            side = "bat"                      # batting team wants a ball
            m = r["distMidIn"] - RULING_THR_IN
            wronged = r["batSide"]            # 'away'/'home' of batting team
        else:
            side = "fld"                      # fielding team wants a strike
            m = RULING_THR_IN - r["distMidIn"]
            wronged = "home" if r["batSide"] == "away" else "away"
        rem = r["remAway"] if wronged == "away" else r["remHome"]
        challenged = r["challenge"] is not None
        if challenged and r["challenge"].get("side") not in (wronged, None):
            side_mismatch += 1
            challenged = False
        v = ve.value_of_flip(r["balls"], r["strikes"], r["bases"], r["outs"],
                             r["inning"], r["half"], r["homeScore"] - r["awayScore"],
                             tables)
        inning = min(r["inning"], 9)
        T = 2 * (9 - inning) + (2 if r["half"] == "top" else 1)
        opps.append({"side": side, "m": m, "g": v["leveragedRuns"],
                     "challenged": challenged, "hadChallenge": rem > 0,
                     "T": T, "playId": r["playId"]})
    if side_mismatch:
        print(f"note: {side_mismatch} challenges by non-wronged side ignored in fit")
    return opps, data["meta"]["games"]


def count_half_innings(games):
    """Total half-innings ~= games x league average (17.7 with 51% skipped
    bottom 9ths and extras roughly cancelling)."""
    return games * 17.7


# ---------------------------------------------------------- perception model

def fit_probit(opps, side):
    """MLE grid fit of P(challenge | m) = Phi((m - x*) / sigma) for one side.

    Uses only takes where the wronged team had a challenge available.
    """
    hist = defaultdict(lambda: [0, 0])       # m bin -> [challenged, total]
    for o in opps:
        if o["side"] != side or not o["hadChallenge"]:
            continue
        b = round(max(-M_RANGE, min(M_RANGE, o["m"])) / 0.05) * 0.05
        hist[b][1] += 1
        hist[b][0] += o["challenged"]
    best = None
    for sigma in [0.2 + 0.02 * i for i in range(240)]:
        for x_star in [0.0 + 0.02 * i for i in range(350)]:
            ll = 0.0
            for m, (c, n) in hist.items():
                p = min(max(phi((m - x_star) / sigma), 1e-9), 1 - 1e-9)
                ll += c * math.log(p) + (n - c) * math.log(1.0 - p)
            if best is None or ll > best[0]:
                best = (ll, sigma, x_star)
    return {"sigma": best[1], "xStar": best[2], "logLik": best[0]}


def margin_prior(opps, side):
    """Empirical density of true margins for one side (0.1in bins)."""
    hist = defaultdict(int)
    n = 0
    for o in opps:
        if o["side"] != side:
            continue
        b = round(max(-M_RANGE, min(M_RANGE, o["m"])) / M_BIN) * M_BIN
        hist[b] += 1
        n += 1
    return {b: c / n for b, c in hist.items()}


def posterior_grid(prior, sigma):
    """p(x) = P(m > 0 | perceived x) on a grid; monotone increasing in x."""
    xs = [round(-M_RANGE + 0.05 * i, 3) for i in range(int(2 * M_RANGE / 0.05) + 1)]
    grid = []
    for x in xs:
        num = den = 0.0
        for m, w in prior.items():
            lik = norm_pdf((x - m) / sigma)
            den += w * lik
            if m > 0:
                num += w * lik
        grid.append((x, num / den if den > 0 else (1.0 if x > 0 else 0.0)))
    # enforce monotonicity against tail-bin noise
    for i in range(1, len(grid)):
        if grid[i][1] < grid[i - 1][1]:
            grid[i] = (grid[i][0], grid[i - 1][1])
    return grid


def interp_grid(grid, x):
    """Linear interpolation on a [[x, p], ...] grid with uniform steps."""
    if x <= grid[0][0]:
        return grid[0][1]
    if x >= grid[-1][0]:
        return grid[-1][1]
    step = grid[1][0] - grid[0][0]
    i = int((x - grid[0][0]) / step)
    x0, p0 = grid[i]
    x1, p1 = grid[min(i + 1, len(grid) - 1)]
    return p0 + (p1 - p0) * (x - x0) / max(x1 - x0, 1e-9)


def look_grids(post, sigma, x_star):
    """Expected-confidence curves vs the TRUE margin m.

    pLook(m) = E[p(x) | x ~ N(m, sigma)]: what an attentive decider's
    confidence averages out to when the pitch is truly at m (used for grading
    unchallenged pitches - can this wrong call be identified at all?).

    pSel(m) = E[p(x) | x ~ N(m, sigma), x >= x*]: the same conditioned on the
    decider having seen enough to pull the trigger (league threshold x*). This
    is the right confidence for grading challenges that were actually made -
    evaluating the raw posterior at x = m ignores that selection and grades
    real challenges far too harshly.
    """
    p_at_xstar = interp_grid(post, x_star)
    ms = [round(-M_RANGE + 0.1 * i, 2) for i in range(int(2 * M_RANGE / 0.1) + 1)]
    p_look, p_sel = [], []
    for m in ms:
        num = den = num_s = den_s = 0.0
        for x, p in post:
            w = norm_pdf((x - m) / sigma)
            num += w * p
            den += w
            if x >= x_star:
                num_s += w * p
                den_s += w
        p_look.append([m, num / den if den > 0 else p_at_xstar])
        p_sel.append([m, num_s / den_s if den_s > 1e-12 else p_at_xstar])
    return p_look, p_sel


def x_threshold(post, c_over_g):
    """Smallest perceived x with p/(1-p) >= C/g; None if unreachable."""
    if c_over_g <= 0:
        return -M_RANGE
    lo, hi = 0, len(post) - 1
    if post[hi][1] / max(1 - post[hi][1], 1e-12) < c_over_g:
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        p = post[mid][1]
        if p / max(1 - p, 1e-12) >= c_over_g:
            hi = mid
        else:
            lo = mid + 1
    return post[lo][0]


# ----------------------------------------------------------------- DP for C

def build_dp(opps, halves_total, perception, posts):
    """V(k, T) and C(k, T) = V(k,T) - V(k-1,T), k in {1,2}, T in 0..18."""
    per_half = 1.0 / (2.0 * halves_total)    # each take is one team's opp

    def half_stats(cost):
        """(expected gain, fail prob, attempts) per team-half at challenge cost."""
        gain = fail = att = 0.0
        for o in opps:
            g = o["g"]
            if g <= 0 and o["m"] <= 0:
                continue
            sig = perception[o["side"]]["sigma"]
            xc = x_threshold(posts[o["side"]], cost / g if g > 0 else float("inf"))
            if xc is None:
                continue
            r = phi((o["m"] - xc) / sig)
            att += r
            if o["m"] > 0:
                gain += r * g
            else:
                fail += r
        return gain * per_half, fail * per_half, att * per_half

    V = {0: [0.0] * (REG_HALVES + 1), 1: [0.0] * (REG_HALVES + 1),
         2: [0.0] * (REG_HALVES + 1)}
    stats_log = {}
    for T in range(1, REG_HALVES + 1):
        for k in (1, 2):
            cost = max(V[k][T - 1] - V[k - 1][T - 1], EPS_COST)
            a, pf, att = half_stats(cost)
            V[k][T] = a + (1.0 - pf) * V[k][T - 1] + pf * V[k - 1][T - 1]
            stats_log[(k, T)] = {"cost": cost, "gain": a, "failP": pf, "attempts": att}
    C = {k: [V[k][T] - V[k - 1][T] for T in range(REG_HALVES + 1)] for k in (1, 2)}
    return V, C, stats_log


# ------------------------------------------------------------------- output

def main():
    ap = argparse.ArgumentParser(description="Build ABS option-value model")
    ap.add_argument("--dataset", default=DATASET)
    ap.add_argument("--tables", default=TABLES)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    tables = ve.tables_from_json(args.tables)
    opps, n_games = load_opportunities(args.dataset, tables)
    halves = count_half_innings(n_games)
    print(f"{len(opps)} opportunities from {n_games} games")

    perception, posts, priors = {}, {}, {}
    for side in ("fld", "bat"):
        perception[side] = fit_probit(opps, side)
        priors[side] = margin_prior(opps, side)
        posts[side] = posterior_grid(priors[side], perception[side]["sigma"])
        p = perception[side]
        print(f"perception[{side}]: sigma={p['sigma']:.2f}in threshold x*={p['xStar']:.2f}in")

    looks, sels = {}, {}
    for side in ("fld", "bat"):
        looks[side], sels[side] = look_grids(posts[side], perception[side]["sigma"],
                                             perception[side]["xStar"])
        chal = [o for o in opps if o["side"] == side and o["challenged"]]
        pred = sum(interp_grid(sels[side], o["m"]) for o in chal) / len(chal)
        actual = sum(1 for o in chal if o["m"] > 0) / len(chal)
        print(f"self-check [{side}]: mean selection-conditioned confidence on "
              f"actual challenges {pred:.3f} vs observed success {actual:.3f}")

    V, C, stats = build_dp(opps, halves, perception, posts)

    out = {
        "meta": {"generated": date.today().isoformat(), "games": n_games,
                 "opportunities": len(opps), "rulingThrIn": RULING_THR_IN,
                 "regHalves": REG_HALVES},
        "perception": perception,
        "marginPrior": {s: {f"{b:.1f}": round(w, 6) for b, w in sorted(priors[s].items())}
                        for s in priors},
        "posterior": {s: [[x, round(p, 5)] for x, p in posts[s]] for s in posts},
        "pLook": {s: [[m, round(p, 5)] for m, p in looks[s]] for s in looks},
        "pSel": {s: [[m, round(p, 5)] for m, p in sels[s]] for s in sels},
        "V": {str(k): [round(v, 5) for v in V[k]] for k in V},
        "C": {str(k): [round(c, 5) for c in C[k]] for k in C},
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=1)
    print(f"wrote {args.out}")

    # ------------------------------------------------------------ validation
    print("\nC(k, T) leveraged runs (T = regulation half-innings remaining):")
    print("  T:      " + " ".join(f"{T:5d}" for T in (18, 14, 10, 6, 4, 2, 1)))
    for k in (1, 2):
        row = " ".join(f"{C[k][T]:.3f}" for T in (18, 14, 10, 6, 4, 2, 1))
        print(f"  C(k={k}): {row}")
    # forward-simulate the k chain for honest usage numbers
    pk = {2: 1.0, 1: 0.0, 0: 0.0}
    att_game = fail_game = 0.0
    for T in range(REG_HALVES, 0, -1):
        nxt = {2: 0.0, 1: 0.0, 0: pk[0]}
        for k in (1, 2):
            s = stats[(k, T)]
            att_game += pk[k] * s["attempts"]
            fail_game += pk[k] * s["failP"]
            nxt[k] += pk[k] * (1.0 - s["failP"])
            nxt[k - 1] += pk[k] * s["failP"]
        pk = nxt
    succ = att_game - fail_game
    print(f"\noptimal-policy usage/team-game: {att_game:.2f} attempts, "
          f"{100 * succ / att_game:.0f}% success (league: ~2.1 attempts, ~61%)")

    print("\nbreak-even confidence p* = C/(g+C):")
    demos = [("0-0 pitch, neutral, game start (k=2)", 0.078, C[2][18]),
             ("0-0 pitch, neutral, game start (k=1)", 0.078, C[1][18]),
             ("3-2 loaded, bottom 9 tie (k=1)", 8.17, C[1][1]),
             ("2-2 pitch, neutral, 8th inning (k=1)", 0.140, C[1][4])]
    for label, g, c in demos:
        print(f"  {label}: p* = {c / (g + c):.2f}")


if __name__ == "__main__":
    main()
