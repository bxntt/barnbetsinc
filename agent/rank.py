"""Rank best bets and attach a plain-English "why".

Ranking score weights the raw edge by confidence, so a +3% edge from a tight
sharp market outranks a +4% edge from a wide, untrustworthy one.
"""
from __future__ import annotations

from typing import List, Optional

from .models import BestBet
from .odds_math import american_to_implied, format_american, implied_to_american


def selection_label(market: str, selection: str, point: Optional[float]) -> str:
    """Human label for a bet, e.g. 'Lakers ML', 'Eagles -2.5', 'Over 8.5'."""
    if market == "h2h":
        return f"{selection} ML"
    if market == "spreads" and point is not None:
        return f"{selection} {point:+g}"
    if market == "totals" and point is not None:
        return f"{selection} {point:g}"
    return selection


def _rationale(b: BestBet) -> str:
    label = selection_label(b.market, b.selection, b.point)
    fair_pct = round(b.fair_prob * 100, 1)
    fair_price = format_american(implied_to_american(b.fair_prob))
    hr_pct = round(american_to_implied(b.price_american) * 100, 1)

    parts = [
        f"Hard Rock has {label} at {b.price_display} ({hr_pct}% implied). "
        f"Sharp fair value is {fair_pct}% (~{fair_price}) per {b.reference_book}. "
        f"That's a +{b.ev_pct:.1f}% edge."
    ]

    # Market quality.
    if b.market_vig <= 0.035:
        parts.append("The reference market is tight (high trust).")
    elif b.market_vig >= 0.06:
        parts.append("Note: the reference market is wide, so treat with caution.")

    # Movement confirmation.
    if b.movement:
        d = b.movement["direction"]
        if d == "toward":
            parts.append("The line has moved toward this side since open — sharp confirmation.")
        elif d == "away":
            parts.append("The line has drifted the other way since open, so the value may be fading.")

    # Context chips.
    if b.context:
        notes = b.context.get("notes")
        if notes:
            parts.append(notes)

    return " ".join(parts)


def rank_bets(bets: List[BestBet], max_published: int = 0) -> List[BestBet]:
    """Sort by confidence-weighted EV, attach rationale, and trim to max."""
    for b in bets:
        b.rationale = _rationale(b)
    ranked = sorted(bets, key=lambda b: b.ev_pct * max(b.confidence, 0.01), reverse=True)
    if max_published and max_published > 0:
        ranked = ranked[:max_published]
    return ranked
