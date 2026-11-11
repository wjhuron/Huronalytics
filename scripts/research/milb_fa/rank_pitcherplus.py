"""Does AAA Pitcher+ help rank free-agent AAA pitchers? (2026-11-11, per Wally: "a weighted blend
of K-BB%, SwStr%, and Pitcher+ makes sense"; "Yes, test it").

rank_backtest.py unchanged, with its extra-grade slot ('stuff') filled by AAA Pitcher+ from
pplus_aaa_build.py instead of Stuff+. So in the second table every row named "Stuff+" reads
"Pitcher+": 'Stuff+ alone' is Pitcher+ alone, 'SHIPPED + Stuff+' is the shipped projection with
Pitcher+ as a seventh input, and 'K-BB% + SwStr% + Stuff+' is Wally's blend with fitted weights.
Same pool (AAA-primary, age 25+), same objective (within-role weighted r with Y+1 all-level RA9),
same three Hawk-Eye pairs (2023, 2024, 2025 bases), each held out in turn.
    PYTHONHASHSEED=0 python3 scripts/research/milb_fa/rank_pitcherplus.py
Output: data/_milb_fa/_pplus/rank_backtest_pitcherplus.json
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rank_backtest as RB  # noqa: E402

RB.STUFF_SRC = os.path.join('_pplus', 'aaa_pitcherplus.json')
RB.OUT = os.path.join(RB.D, '_pplus', 'rank_backtest_pitcherplus.json')

if __name__ == '__main__':
    RB.main()
