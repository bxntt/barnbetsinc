"""World Cup data models.

Raw odds reuse the shared `Game` / `BookOdds` / `Outcome` types. A `Match` wraps a
`Game` with the soccer-specific metadata the simulator needs (group, matchday, and
the final score once it has been played) without polluting the generic model.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

from ..models import Game
from ..odds_math import format_american

# (selection name, point) — point is None for 1X2, the line for totals.
Key = Tuple[str, Optional[float]]


@dataclass
class Match:
    """A single World Cup match: its odds plus tournament context."""
    game: Game
    group: str                       # "A".."L"
    matchday: int                    # 1..3 (group stage)
    played: bool = False
    home_goals: Optional[int] = None
    away_goals: Optional[int] = None

    @property
    def home(self) -> str:
        return self.game.home_team

    @property
    def away(self) -> str:
        return self.game.away_team

    @property
    def commence_time(self) -> str:
        return self.game.commence_time


@dataclass
class FairLine:
    """No-vig consensus for one market of one match, blended across books."""
    fair_by_key: Dict[Key, float]    # (name, point) -> fair probability (sums to ~1)
    vig: float                       # average book hold across the market (0..1)
    n_books: int                     # how many books contributed


@dataclass
class ValueQuote:
    """The best available price for one selection vs the no-vig fair line."""
    match_id: str
    group: str
    commence_time: str
    home: str
    away: str
    market: str                      # "h2h" | "totals"
    selection: str                   # team name, "Draw", "Over"/"Under"
    point: Optional[float]

    fair_prob: float                 # consensus no-vig probability (0..1)
    best_price_american: int         # cheapest (highest-paying) price found
    best_book: str
    ev_pct: float                    # fair_prob * best_decimal - 1, in %
    n_books: int
    vig: float                       # avg market hold of the consensus
    confidence: float                # 0..1 trust weight
    all_prices: List[Tuple[str, int]] = field(default_factory=list)  # (book, american)
    rationale: str = ""

    @property
    def best_price_display(self) -> str:
        return format_american(self.best_price_american)

    @property
    def fair_price_american(self) -> int:
        from ..odds_math import implied_to_american
        return implied_to_american(self.fair_prob)

    def label(self) -> str:
        if self.market == "h2h":
            if self.selection == "Draw":
                return "Draw"
            return f"{self.selection} to win"
        if self.market == "totals" and self.point is not None:
            return f"{self.selection} {self.point:g}"
        return self.selection

    def to_dict(self) -> dict:
        d = asdict(self)
        d["label"] = self.label()
        d["best_price_display"] = self.best_price_display
        d["fair_price_american"] = self.fair_price_american
        d["fair_prob_pct"] = round(self.fair_prob * 100, 1)
        d["ev_pct"] = round(self.ev_pct, 2)
        d["vig_pct"] = round(self.vig * 100, 2)
        d["confidence"] = round(self.confidence, 2)
        # all_prices: list of {book, price_display}
        d["all_prices"] = [
            {"book": bk, "price_display": format_american(am)} for bk, am in self.all_prices
        ]
        return d


@dataclass
class TeamProjection:
    """Simulated outlook for one team in its group."""
    team: str
    group: str
    played: int
    points: int                      # current points from played matches
    goal_diff: int                   # current GD from played matches
    p_win_group: float               # 0..1
    p_top2: float
    p_advance: float                 # top-2 OR one of the 8 best thirds
    exp_points: float                # mean final group points
    finish_probs: Dict[str, float]   # {"1": .., "2": .., "3": .., "4": ..}

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("p_win_group", "p_top2", "p_advance"):
            d[k + "_pct"] = round(getattr(self, k) * 100, 1)
        d["exp_points"] = round(self.exp_points, 2)
        d["finish_probs_pct"] = {k: round(v * 100, 1) for k, v in self.finish_probs.items()}
        return d


@dataclass
class GroupProjection:
    """A group's standings + simulated advancement outlook."""
    group: str
    teams: List[TeamProjection]
    matches_played: int
    matches_total: int

    def to_dict(self) -> dict:
        return {
            "group": self.group,
            "matches_played": self.matches_played,
            "matches_total": self.matches_total,
            "teams": [t.to_dict() for t in self.teams],
        }
