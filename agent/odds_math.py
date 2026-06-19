"""Pure odds-math helpers: American <-> decimal <-> implied probability.

These are deliberately dependency-free and side-effect-free so they're trivial
to unit-test and reuse across the engine.
"""
from __future__ import annotations


def american_to_decimal(american: int) -> float:
    """Convert American odds (e.g. +150, -120) to decimal odds (e.g. 2.50, 1.833)."""
    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 + 100.0 / abs(american)


def decimal_to_american(decimal: float) -> int:
    """Convert decimal odds back to American odds, rounded to the nearest integer."""
    if decimal <= 1.0:
        raise ValueError(f"decimal odds must be > 1.0, got {decimal}")
    if decimal >= 2.0:
        return round((decimal - 1.0) * 100.0)
    return round(-100.0 / (decimal - 1.0))


def american_to_implied(american: int) -> float:
    """Implied probability (includes the book's vig) for American odds. Returns 0..1."""
    return decimal_to_implied(american_to_decimal(american))


def decimal_to_implied(decimal: float) -> float:
    """Implied probability (includes vig) for decimal odds. Returns 0..1."""
    return 1.0 / decimal


def implied_to_american(prob: float) -> int:
    """Convert a probability (0..1) to the equivalent fair American odds."""
    if not 0.0 < prob < 1.0:
        raise ValueError(f"prob must be in (0, 1), got {prob}")
    return decimal_to_american(1.0 / prob)


def format_american(american: int) -> str:
    """Render American odds the way a sportsbook does: +150 / -120."""
    return f"+{american}" if american > 0 else str(american)
