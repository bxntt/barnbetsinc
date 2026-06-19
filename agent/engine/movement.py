"""Line movement (steam) from stored snapshots.

Two signals are derived per recommended bet:

  * target movement — the target book's earliest recorded price vs its current
    price. Shortening (implied prob up) means the book is moving toward this side.
  * sharp movement  — the *sharp/consensus* no-vig fair prob (stored as `ref_probs`
    in each snapshot) at open vs now. When the sharp market moves toward a side it
    is a stronger confirmation than the target book's own move; when the sharp
    market moves toward a side the target book hasn't followed yet, that is exactly
    where lingering value tends to live.
"""
from __future__ import annotations

from typing import List, Optional

from ..odds_math import american_to_implied
from ..store import bet_key

# Movement smaller than this (in implied-probability points) is treated as flat.
_FLAT = 0.005


def _direction(delta: float) -> str:
    if delta > _FLAT:
        return "toward"      # shortening -> market backing this side
    if delta < -_FLAT:
        return "away"        # drifting -> market fading this side
    return "flat"


def _first(snapshots: List[dict], field: str, key: str):
    """Earliest recorded value for `key` under snapshot `field` (oldest-first)."""
    for snap in snapshots:
        val = snap.get(field, {}).get(key)
        if val is not None:
            return val
    return None


def movement_for(key: str, current_american: int, snapshots: List[dict]) -> Optional[dict]:
    """Open-vs-current movement for the target book's price."""
    open_price = _first(snapshots, "target_prices", key)
    if open_price is None or open_price == current_american:
        return None
    open_implied = american_to_implied(open_price)
    cur_implied = american_to_implied(current_american)
    delta = cur_implied - open_implied
    return {
        "open_price": open_price,
        "current_price": current_american,
        "delta_implied_pct": round(delta * 100, 2),
        "direction": _direction(delta),
    }


def sharp_movement_for(key: str, current_fair: float, snapshots: List[dict]) -> Optional[dict]:
    """Open-vs-current movement of the sharp/consensus no-vig fair prob."""
    open_fair = _first(snapshots, "ref_probs", key)
    if open_fair is None:
        return None
    delta = current_fair - open_fair
    if abs(delta) <= _FLAT:
        return {"delta_pct": round(delta * 100, 2), "direction": "flat"}
    return {
        "open_prob_pct": round(open_fair * 100, 1),
        "current_prob_pct": round(current_fair * 100, 1),
        "delta_pct": round(delta * 100, 2),
        "direction": _direction(delta),
    }


def attach_movement(bets, snapshots: List[dict]) -> None:
    """Annotate each bet in-place with target + sharp movement (if available)."""
    for b in bets:
        key = bet_key(b.game_id, b.market, b.selection, b.point)
        mv = movement_for(key, b.price_american, snapshots) or {}
        sharp = sharp_movement_for(key, b.fair_prob, snapshots)
        if sharp and sharp.get("direction") != "flat":
            mv["sharp"] = sharp
        b.movement = mv or None
