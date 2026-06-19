"""Core data models shared across providers, engine, and publisher.

Normalized shape (provider-agnostic):

    Game
      └── markets: { "h2h" | "spreads" | "totals" -> [BookOdds, ...] }
                                                        └── outcomes: [Outcome, ...]

A `BestBet` is what the engine emits: a single recommended wager at the target
book, with the math and a plain-English rationale attached.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from .odds_math import american_to_decimal, american_to_implied, format_american


@dataclass
class Outcome:
    """One selectable side of a market at one book."""
    name: str                      # team name, "Over"/"Under", etc.
    price_american: int            # e.g. +150, -120
    point: Optional[float] = None  # spread / total line; None for moneyline

    @property
    def decimal(self) -> float:
        return american_to_decimal(self.price_american)

    @property
    def implied(self) -> float:
        return american_to_implied(self.price_american)


@dataclass
class BookOdds:
    """One book's offering for one market of one game."""
    book: str                      # canonical key, e.g. "hardrockbet", "pinnacle"
    outcomes: List[Outcome]
    last_update: Optional[str] = None  # ISO8601, if the provider supplies it


@dataclass
class Game:
    """A single game with per-market, per-book odds."""
    id: str
    sport_key: str
    sport_title: str
    commence_time: str             # ISO8601 UTC
    home_team: str
    away_team: str
    markets: Dict[str, List[BookOdds]] = field(default_factory=dict)

    def book_in_market(self, market: str, book: str) -> Optional[BookOdds]:
        """Return this book's odds for the given market, or None if absent."""
        for bo in self.markets.get(market, []):
            if bo.book == book:
                return bo
        return None


@dataclass
class BestBet:
    """A recommended +EV wager at the target book."""
    game_id: str
    sport_key: str
    sport_title: str
    commence_time: str
    home_team: str
    away_team: str
    market: str                    # "h2h" | "spreads" | "totals"
    selection: str                 # outcome name being recommended
    point: Optional[float]

    target_book: str
    price_american: int            # target book's price for the selection
    fair_prob: float               # no-vig fair probability (0..1)
    ev_pct: float                  # expected value, in % (e.g. 5.4)
    confidence: float              # 0..1 quality weight

    reference_book: str            # which sharp ref produced the fair line ("consensus" if blended)
    market_vig: float              # hold of the reference market (0..1)
    movement: Optional[dict] = None    # line-movement summary, if available
    context: Optional[dict] = None     # injuries / weather chips, if available
    rationale: str = ""

    @property
    def price_display(self) -> str:
        return format_american(self.price_american)

    @property
    def fair_price_american(self) -> int:
        from .odds_math import implied_to_american
        return implied_to_american(self.fair_prob)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["price_display"] = self.price_display
        d["fair_price_american"] = self.fair_price_american
        return d
