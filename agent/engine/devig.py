"""De-vigging: turn a book's vig-inclusive prices into no-vig "fair" probabilities.

Standard proportional (multiplicative) method for a balanced market:

    raw_i  = 1 / decimal_odds_i          # implied prob, includes vig
    total  = sum(raw_i)                  # ~ 1 + vig
    fair_i = raw_i / total               # vig removed, sums to 1
    vig    = total - 1                   # the book's hold

The reference fair line is taken from the sharpest available book (Pinnacle by
preference). If no configured sharp book is present, we blend the other books
into a consensus. The target book (Hard Rock) is never used as its own reference.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..models import BookOdds, Game, Outcome

# A market outcome is identified by (selection name, point line). Points are
# rounded so 2.5 == 2.50 when matching the target book to the reference.
Key = Tuple[str, Optional[float]]


def outcome_key(o: Outcome) -> Key:
    return (o.name, None if o.point is None else round(o.point, 1))


@dataclass
class ReferenceFair:
    book: str                       # label of the reference ("pinnacle", "consensus", ...)
    fair_by_key: Dict[Key, float]   # (name, point) -> no-vig fair probability
    vig: float                      # hold of the reference market (0..1)


def fair_from_book(book_odds: BookOdds) -> Tuple[Dict[Key, float], float]:
    """De-vig a single book's market. Returns (fair_by_key, vig)."""
    implied = {outcome_key(o): o.implied for o in book_odds.outcomes}
    total = sum(implied.values())
    if total <= 0:
        return {}, 0.0
    fair = {k: v / total for k, v in implied.items()}
    return fair, total - 1.0


def _consensus(others: List[BookOdds]) -> Optional[ReferenceFair]:
    """Blend non-target books into a consensus fair line. Handles the common
    2-way market by averaging each side's implied prob (at its modal line)."""
    # Collect implied probs per side name, tracking the line each was priced at.
    by_name: Dict[str, List[Tuple[Optional[float], float]]] = {}
    for bo in others:
        for o in bo.outcomes:
            by_name.setdefault(o.name, []).append(
                (None if o.point is None else round(o.point, 1), o.implied)
            )
    if len(by_name) != 2:  # only handle clean 2-way markets in consensus
        return None

    avg_implied: Dict[Key, float] = {}
    for name, entries in by_name.items():
        # Pick the modal point line for this side, then average its prices.
        points = [p for p, _ in entries]
        modal = max(set(points), key=points.count)
        vals = [imp for p, imp in entries if p == modal]
        avg_implied[(name, modal)] = sum(vals) / len(vals)

    total = sum(avg_implied.values())
    if total <= 0:
        return None
    fair = {k: v / total for k, v in avg_implied.items()}
    return ReferenceFair("consensus", fair, total - 1.0)


def reference_fair(
    game: Game,
    market: str,
    sharp_books: List[str],
    target_book: str,
) -> Optional[ReferenceFair]:
    """Compute the no-vig fair line to judge the target book against."""
    market_books = game.markets.get(market, [])

    # 1) Prefer a configured sharp book, in priority order.
    for sb in sharp_books:
        bo = game.book_in_market(market, sb)
        if bo and len(bo.outcomes) >= 2:
            fair, vig = fair_from_book(bo)
            return ReferenceFair(sb, fair, vig)

    # 2) Otherwise blend everything except the target book into a consensus.
    others = [
        bo for bo in market_books
        if bo.book != target_book and len(bo.outcomes) >= 2
    ]
    if not others:
        return None
    return _consensus(others)
