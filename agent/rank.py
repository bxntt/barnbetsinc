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
        f"Sharp fair value is {fair_pct}% (~{fair_price}) per {b.reference_book} — "
        f"so an estimated {fair_pct}% chance to hit. That's a +{b.ev_pct:.1f}% edge."
    ]

    # Suggested sizing (fractional Kelly).
    if b.kelly_pct and b.kelly_pct >= 0.05:
        parts.append(f"Suggested stake ~{b.kelly_pct:.1f}% of bankroll (¼-Kelly).")

    # Interpolated line caveat.
    if b.interpolated:
        parts.append(
            f"Fair value was shifted {b.reach:g} pt from the nearest sharp line, "
            "so the estimate is softer here."
        )

    # Longshot caution (favorite-longshot bias).
    if b.longshot:
        parts.append("Heads up: this is an underdog price, where market vig is heaviest — sized down.")

    # Market quality.
    if b.market_vig <= 0.035:
        parts.append("The reference market is tight (high trust).")
    elif b.market_vig >= 0.06:
        parts.append("Note: the reference market is wide, so treat with caution.")

    # Movement confirmation (target book + sharp market).
    if b.movement:
        d = b.movement.get("direction")
        if d == "toward":
            parts.append("The line has moved toward this side since open — sharp confirmation.")
        elif d == "away":
            parts.append("The line has drifted the other way since open, so the value may be fading.")
        sharp = b.movement.get("sharp")
        if sharp and sharp.get("direction") == "toward":
            parts.append("Sharp/consensus fair value has also moved toward this side — stronger confirmation.")

    # Independent model cross-check (Elo).
    if b.model_flag == "disagree" and b.model_prob is not None:
        parts.append(
            f"Independent model differs (it sees ~{b.model_prob * 100:.0f}%), so treat as lower-conviction."
        )
    elif b.model_flag == "agree":
        parts.append("An independent model agrees with the market here.")

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
