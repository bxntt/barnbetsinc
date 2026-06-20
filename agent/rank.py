"""Rank predictions by how likely they are to hit.

Calls are ordered by probability (confidence breaks ties), but whole games are
kept together so the site can render one card per game without truncating a
game's markets mid-way. The plain-English "why" is built in engine/predict.py;
here we only append any context note (injuries/weather) picked up by enrichment.
"""
from __future__ import annotations

from typing import List, Optional

from .models import Prediction


def selection_label(market: str, selection: str, point: Optional[float]) -> str:
    """Human label for a pick, e.g. 'Lakers ML', 'Eagles -2.5', 'Over 8.5'."""
    if market == "h2h":
        return f"{selection} ML"
    if market == "spreads" and point is not None:
        return f"{selection} {point:+g}"
    if market == "totals" and point is not None:
        return f"{selection} {point:g}"
    return selection


def rank_predictions(preds: List[Prediction], max_games: int = 0) -> List[Prediction]:
    """Most-likely-to-hit first, keeping each game's market calls together.

    Calls are sorted by probability (confidence breaks ties); games are ordered
    by their single strongest call. `max_games` caps how many games are kept (all
    of a kept game's calls survive). 0 = no cap.
    """
    for p in preds:
        if p.context and p.context.get("notes"):
            p.rationale = (p.rationale + " " + p.context["notes"]).strip()

    ranked = sorted(preds, key=lambda p: (p.prob, p.confidence), reverse=True)
    order: List[str] = []
    seen = set()
    for p in ranked:
        if p.game_id not in seen:
            seen.add(p.game_id)
            order.append(p.game_id)
    if max_games and max_games > 0:
        keep = set(order[:max_games])
        ranked = [p for p in ranked if p.game_id in keep]
    return ranked
