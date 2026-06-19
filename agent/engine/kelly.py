"""Fractional Kelly bet sizing.

Kelly stakes a wager in proportion to its edge, maximizing long-run bankroll
growth. Full Kelly assumes the win probability is known exactly; since our
`fair_prob` is an estimate, we use *fractional* Kelly (default quarter) plus a
hard cap, which protects against overbetting when the edge is overestimated.

    f* = (decimal*p - 1) / (decimal - 1)        # full-Kelly fraction of bankroll
    stake = clamp(fraction * f*, 0, cap)         # fractional, capped
"""
from __future__ import annotations


def kelly_fraction(prob: float, decimal: float) -> float:
    """Full-Kelly fraction of bankroll (0 if the bet is not +EV)."""
    if decimal <= 1.0:
        return 0.0
    f = (decimal * prob - 1.0) / (decimal - 1.0)
    return max(0.0, f)


def kelly_stake(prob: float, decimal: float, fraction: float = 0.25, cap: float = 0.05) -> float:
    """Recommended stake as a fraction of bankroll (fractional Kelly, capped)."""
    return min(cap, fraction * kelly_fraction(prob, decimal))
