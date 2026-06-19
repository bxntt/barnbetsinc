"""Match value finder — sportsbook-agnostic.

For each match market we de-vig every book into a consensus fair probability,
then find the BEST (highest-paying) price for each selection across all books. If
the best price pays more than fair, that's positive expected value — and we say
*which* book has it, so it works no matter where you bet.

    EV% = fair_prob * best_decimal - 1
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from ..models import Game
from ..odds_math import american_to_decimal, american_to_implied, format_american, implied_to_american
from .devig import consensus_fair
from .models import Key, Match, ValueQuote


def _minutes_to_start(commence_time: str) -> Optional[float]:
    try:
        start = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None
    return (start - datetime.now(timezone.utc)).total_seconds() / 60.0


def _confidence(vig: float, n_books: int, minutes: Optional[float]) -> float:
    """Trust weight: tighter consensus, more books, and not-imminent all help."""
    # Vig: a tight (<=4%) consensus is fully trusted, decaying to 0.3 by ~10% hold.
    if vig <= 0.04:
        vig_factor = 1.0
    elif vig >= 0.10:
        vig_factor = 0.3
    else:
        vig_factor = 1.0 - 0.7 * ((vig - 0.04) / 0.06)

    # Depth: one or two books is thin; full trust by ~5 books.
    depth_factor = max(0.3, min(1.0, n_books / 5.0))

    # Time: down-weight matches starting within 30 min (stale comparison).
    if minutes is None:
        time_factor = 0.85
    elif minutes <= 0:
        time_factor = 0.0
    elif minutes >= 30:
        time_factor = 1.0
    else:
        time_factor = minutes / 30.0

    return max(0.0, min(1.0, vig_factor * depth_factor * time_factor))


def _best_price(books, key: Key):
    """Highest-paying American price for `key` across books -> (american, book, all)."""
    best_dec, best_am, best_book = 0.0, None, None
    all_prices = []
    name, point = key
    for bo in books:
        for o in bo.outcomes:
            opt = None if o.point is None else round(o.point, 1)
            if o.name == name and opt == point:
                all_prices.append((bo.book, o.price_american))
                if o.decimal > best_dec:
                    best_dec, best_am, best_book = o.decimal, o.price_american, bo.book
    all_prices.sort(key=lambda bp: american_to_decimal(bp[1]), reverse=True)
    return best_am, best_book, all_prices


def find_value(match: Match, markets: List[str], min_ev_pct: float) -> List[ValueQuote]:
    """All selections in `match` whose best market price clears `min_ev_pct`."""
    quotes: List[ValueQuote] = []
    if match.played:
        return quotes
    minutes = _minutes_to_start(match.commence_time)

    for market in markets:
        books = match.game.markets.get(market, [])
        fair = consensus_fair(books)
        if fair is None:
            continue
        conf = _confidence(fair.vig, fair.n_books, minutes)

        for key, fair_prob in fair.fair_by_key.items():
            best_am, best_book, all_prices = _best_price(books, key)
            if best_am is None:
                continue
            ev_pct = (fair_prob * american_to_decimal(best_am) - 1.0) * 100.0
            if ev_pct < min_ev_pct:
                continue
            q = ValueQuote(
                match_id=match.game.id,
                group=match.group,
                commence_time=match.commence_time,
                home=match.home,
                away=match.away,
                market=market,
                selection=key[0],
                point=key[1],
                fair_prob=fair_prob,
                best_price_american=best_am,
                best_book=best_book,
                ev_pct=ev_pct,
                n_books=fair.n_books,
                vig=fair.vig,
                confidence=conf,
                all_prices=all_prices,
            )
            q.rationale = _rationale(q)
            quotes.append(q)
    return quotes


def _rationale(q: ValueQuote) -> str:
    fair_pct = round(q.fair_prob * 100, 1)
    fair_price = format_american(implied_to_american(q.fair_prob))
    best_pct = round(american_to_implied(q.best_price_american) * 100, 1)
    parts = [
        f"Fair value for {q.label()} is {fair_pct}% (~{fair_price}) across "
        f"{q.n_books} book{'s' if q.n_books != 1 else ''}. "
        f"Best price is {q.best_price_display} ({best_pct}% implied) at {q.best_book} "
        f"— a +{q.ev_pct:.1f}% edge."
    ]
    if q.vig <= 0.04:
        parts.append("The market is tight, so the fair line is trustworthy.")
    elif q.vig >= 0.08:
        parts.append("Note: the consensus is wide, so treat the edge with caution.")
    if q.n_books <= 2:
        parts.append("Thin book coverage — confirm the price before betting.")
    return " ".join(parts)


def rank_value(quotes: List[ValueQuote], limit: int = 0) -> List[ValueQuote]:
    """Confidence-weighted ranking (mirrors the Hard Rock side)."""
    ranked = sorted(quotes, key=lambda q: q.ev_pct * max(q.confidence, 0.01), reverse=True)
    return ranked[:limit] if limit and limit > 0 else ranked
