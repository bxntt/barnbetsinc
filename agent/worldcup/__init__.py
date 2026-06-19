"""Sportsbook-agnostic World Cup tools.

Unlike the Hard Rock engine (which judges *one* book against a sharp reference),
these tools take the *whole market* and report things that are true regardless of
where you bet:

  * `value`      — no-vig fair odds (1X2 / totals) vs the BEST price across every
                   book, flagging where positive expected value actually lives.
  * `simulate`   — a Monte Carlo of the group stage (2026 48-team / 12-group
                   format) driven by market-implied probabilities: each team's
                   chance to win its group and to advance.

Both consume normalized `Game` odds (reusing `agent.models`) and never reference a
single target book — the edge is "what is fair" and "who is cheapest", not "is
Hard Rock mispricing this".
"""
