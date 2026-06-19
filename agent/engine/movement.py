"""Line movement (steam) from stored snapshots.

For a recommended bet, compare the target book's *earliest recorded* price to its
current price. If the price has shortened (implied probability rose), the market
is moving toward that side — supporting confirmation for a +EV pick. If it has
drifted out, the market is moving away.
"""
from __future__ import annotations

from typing import List, Optional

from ..odds_math import american_to_implied
from ..store import bet_key

# Movement smaller than this (in implied-probability points) is treated as flat.
_FLAT = 0.005


def movement_for(key: str, current_american: int, snapshots: List[dict]) -> Optional[dict]:
    """Return an open-vs-current movement summary, or None if no history."""
    open_price = None
    for snap in snapshots:  # snapshots are oldest-first
        price = snap.get("target_prices", {}).get(key)
        if price is not None:
            open_price = price
            break
    if open_price is None or open_price == current_american:
        return None

    open_implied = american_to_implied(open_price)
    cur_implied = american_to_implied(current_american)
    delta = cur_implied - open_implied

    if delta > _FLAT:
        direction = "toward"      # line shortening -> market backing this side
    elif delta < -_FLAT:
        direction = "away"        # line drifting -> market fading this side
    else:
        direction = "flat"

    return {
        "open_price": open_price,
        "current_price": current_american,
        "delta_implied_pct": round(delta * 100, 2),
        "direction": direction,
    }


def attach_movement(bets, snapshots: List[dict]) -> None:
    """Annotate each bet in-place with its movement summary (if any)."""
    for b in bets:
        key = bet_key(b.game_id, b.market, b.selection, b.point)
        b.movement = movement_for(key, b.price_american, snapshots)
