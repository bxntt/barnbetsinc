"""Core data models shared across providers, engine, and publisher.

Normalized shape (provider-agnostic):

    Game
      └── markets: { "h2h" | "spreads" | "totals" -> [BookOdds, ...] }
                                                        └── outcomes: [Outcome, ...]

A `Prediction` is what the engine emits: for one bet market of one game, the most
likely outcome and the probability it hits, from a team-strength model blended
with the market consensus. No sportsbook is singled out — we predict what will
happen, not where a price is best.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

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
    book: str                      # canonical key, e.g. "draftkings", "pinnacle"
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
class Prediction:
    """A model call for one bet market of one game.

    The model assigns a probability to each outcome of the market; `pick` is the
    most likely and `prob` is the (model + market consensus blended) chance it
    hits. Model-only and market-only probabilities are kept alongside so the site
    can show where the model and the market agree or diverge.
    """
    game_id: str
    sport_key: str
    sport_title: str
    commence_time: str
    home_team: str
    away_team: str
    market: str                      # "h2h" | "spreads" | "totals"
    pick: str                        # human label, e.g. "Lakers ML", "Over 8.5"
    selection: str                   # gradeable outcome: team name / "Over" / "Under"
    point: Optional[float]           # spread/total line of the pick (None for h2h)

    prob: float                      # blended probability the pick hits (0..1)
    confidence: float                # 0..1 trust in this probability
    model_prob: Optional[float]      # model-only probability for the pick, if modeled
    market_prob: Optional[float]     # market-consensus probability for the pick
    outcomes: List[Tuple[str, float]] = field(default_factory=list)  # (label, prob), desc
    context: Optional[dict] = None   # injuries / weather chips, if available
    rationale: str = ""

    @property
    def fair_price_american(self) -> int:
        from .odds_math import implied_to_american
        return implied_to_american(self.prob)

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "sport_key": self.sport_key,
            "sport_title": self.sport_title,
            "commence_time": self.commence_time,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "market": self.market,
            "pick": self.pick,
            "selection": self.selection,
            "point": self.point,
            "prob": round(self.prob, 4),
            "prob_pct": round(self.prob * 100, 1),
            "confidence": round(self.confidence, 2),
            "model_prob_pct": (None if self.model_prob is None
                               else round(self.model_prob * 100, 1)),
            "market_prob_pct": (None if self.market_prob is None
                                else round(self.market_prob * 100, 1)),
            "fair_price_american": self.fair_price_american,
            "outcomes": [{"label": lbl, "prob_pct": round(p * 100, 1)}
                         for lbl, p in self.outcomes],
            "context": self.context,
            "rationale": self.rationale,
        }
