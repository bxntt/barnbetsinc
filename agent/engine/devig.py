"""De-vigging: turn a book's vig-inclusive prices into no-vig "fair" probabilities.

Three methods are supported (config `strategy.devig_method`):

  * multiplicative — spread the vig proportionally to each implied prob. Simple,
    but leaves the favorite-longshot bias in (overstates longshots).
  * power          — fair_i = raw_i ** k, with k solved so the probs sum to 1.
    Corrects favorite-longshot bias without overcorrecting; a good default.
  * shin           — Shin's insider-trading model; the strongest correction for
    favorite-longshot bias on lopsided markets.

When the methods *disagree* on an outcome (which happens most on longshots), that
disagreement is itself a useful uncertainty signal, exposed as `spread_by_key`.

The reference fair line is taken from the sharpest available book (Pinnacle by
preference). If no configured sharp book is present, we blend the other books
into a *weighted* consensus (tighter / sharper books get more weight). The target
book (Hard Rock) is never used as its own reference.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..models import BookOdds, Game, Outcome

# A market outcome is identified by (selection name, point line). Points are
# rounded so 2.5 == 2.50 when matching the target book to the reference.
Key = Tuple[str, Optional[float]]


def outcome_key(o: Outcome) -> Key:
    return (o.name, None if o.point is None else round(o.point, 1))


# --------------------------------------------------------------- de-vig math ---
def _normalize(probs: List[float]) -> List[float]:
    total = sum(probs)
    return [p / total for p in probs] if total > 0 else probs


def _devig_multiplicative(raw: List[float]) -> List[float]:
    return _normalize(raw)


def _devig_power(raw: List[float], iters: int = 60) -> List[float]:
    """fair_i = raw_i ** k, with k chosen so the fair probs sum to 1."""
    if min(raw) <= 0:
        return _devig_multiplicative(raw)
    lo, hi = 0.0001, 100.0
    for _ in range(iters):
        k = 0.5 * (lo + hi)
        if sum(p ** k for p in raw) > 1.0:
            lo = k          # sum too high -> need a larger exponent
        else:
            hi = k
    k = 0.5 * (lo + hi)
    return _normalize([p ** k for p in raw])


def _devig_shin(raw: List[float], iters: int = 60) -> List[float]:
    """Shin's model: solve for the insider proportion z so fair probs sum to 1."""
    booksum = sum(raw)
    if booksum <= 0:
        return raw
    lo, hi = 0.0, 0.99
    for _ in range(iters):
        z = 0.5 * (lo + hi)
        s = sum(
            (((z * z + 4.0 * (1.0 - z) * p * p / booksum) ** 0.5) - z) / (2.0 * (1.0 - z))
            for p in raw
        )
        if s > 1.0:
            lo = z          # sum too high -> need more insider correction
        else:
            hi = z
    z = 0.5 * (lo + hi)
    fair = [
        (((z * z + 4.0 * (1.0 - z) * p * p / booksum) ** 0.5) - z) / (2.0 * (1.0 - z))
        for p in raw
    ]
    return _normalize(fair)


DEVIG_METHODS = {
    "multiplicative": _devig_multiplicative,
    "power": _devig_power,
    "shin": _devig_shin,
}


def devig_probs(raw: List[float], method: str = "multiplicative") -> List[float]:
    return DEVIG_METHODS.get(method, _devig_multiplicative)(raw)


# ------------------------------------------------------------- book de-vig ---
@dataclass
class ReferenceFair:
    book: str                          # "pinnacle", "consensus", ...
    fair_by_key: Dict[Key, float]      # (name, point) -> no-vig fair probability
    vig: float                         # hold of the reference market (0..1)
    spread_by_key: Dict[Key, float] = field(default_factory=dict)  # method disagreement


def fair_from_book(book_odds: BookOdds, method: str = "multiplicative") -> Tuple[Dict[Key, float], float]:
    """De-vig a single book's market. Returns (fair_by_key, vig)."""
    keys = [outcome_key(o) for o in book_odds.outcomes]
    raw = [o.implied for o in book_odds.outcomes]
    total = sum(raw)
    if total <= 0:
        return {}, 0.0
    fair = dict(zip(keys, devig_probs(raw, method)))
    return fair, total - 1.0


def _spread_from_book(book_odds: BookOdds) -> Dict[Key, float]:
    """Per-outcome disagreement (max-min fair prob) across all de-vig methods."""
    keys = [outcome_key(o) for o in book_odds.outcomes]
    raw = [o.implied for o in book_odds.outcomes]
    if sum(raw) <= 0:
        return {k: 0.0 for k in keys}
    per_method = [devig_probs(raw, m) for m in DEVIG_METHODS]
    return {
        k: max(col) - min(col)
        for k, col in zip(keys, zip(*per_method))
    }


def _weighted_consensus(
    others: List[BookOdds], method: str, book_weights: Optional[Dict[str, float]]
) -> Optional[ReferenceFair]:
    """Blend non-target books into a weighted consensus. Each book is de-vigged
    individually, then its fair probs are averaged with weight
    `configured_book_weight / (1 + k*vig)` so tighter/sharper books count more."""
    book_weights = book_weights or {}
    contrib: Dict[Key, List[Tuple[float, float]]] = {}   # key -> [(weight, fair)]
    spread_contrib: Dict[Key, List[Tuple[float, float]]] = {}
    vig_acc = w_acc = 0.0

    for bo in others:
        fair, vig = fair_from_book(bo, method)
        if not fair:
            continue
        w = book_weights.get(bo.book, 1.0) / (1.0 + 50.0 * max(vig, 0.0))
        spread = _spread_from_book(bo)
        vig_acc += w * vig
        w_acc += w
        for k, p in fair.items():
            contrib.setdefault(k, []).append((w, p))
            spread_contrib.setdefault(k, []).append((w, spread.get(k, 0.0)))

    # Reduce each side to its modal point line, then weight-average.
    by_name: Dict[str, List[Key]] = {}
    for (name, pt) in contrib:
        by_name.setdefault(name, []).append((name, pt))
    if len(by_name) < 2:
        return None

    def _wavg(pairs: List[Tuple[float, float]]) -> float:
        ws = sum(w for w, _ in pairs)
        return sum(w * v for w, v in pairs) / ws if ws else 0.0

    weighted: Dict[Key, float] = {}
    spreads: Dict[Key, float] = {}
    for name, keys in by_name.items():
        points = [pt for _, pt in keys]
        modal = max(set(points), key=points.count)
        weighted[(name, modal)] = _wavg(contrib[(name, modal)])
        spreads[(name, modal)] = _wavg(spread_contrib[(name, modal)])

    total = sum(weighted.values())
    if total <= 0:
        return None
    fair = {k: v / total for k, v in weighted.items()}
    cons_vig = vig_acc / w_acc if w_acc else 0.0
    return ReferenceFair("consensus", fair, cons_vig, spreads)


def reference_fair(
    game: Game,
    market: str,
    sharp_books: List[str],
    target_book: str,
    method: str = "multiplicative",
    book_weights: Optional[Dict[str, float]] = None,
) -> Optional[ReferenceFair]:
    """Compute the no-vig fair line to judge the target book against."""
    market_books = game.markets.get(market, [])

    # 1) Prefer a configured sharp book, in priority order.
    for sb in sharp_books:
        bo = game.book_in_market(market, sb)
        if bo and len(bo.outcomes) >= 2:
            fair, vig = fair_from_book(bo, method)
            return ReferenceFair(sb, fair, vig, _spread_from_book(bo))

    # 2) Otherwise blend everything except the target book into a weighted consensus.
    others = [
        bo for bo in market_books
        if bo.book != target_book and len(bo.outcomes) >= 2
    ]
    if not others:
        return None
    return _weighted_consensus(others, method, book_weights)
