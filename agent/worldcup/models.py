"""World Cup data models.

Raw odds reuse the shared `Game` / `BookOdds` / `Outcome` types. A `Match` wraps a
`Game` with the soccer-specific metadata the simulator needs (group, matchday, and
the final score once it has been played) without polluting the generic model.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Tuple

from ..models import Game

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
class Prediction:
    """A single model call for one bet market of one match.

    The model assigns a probability to every outcome of the market; `pick` is the
    most likely one and `prob` is the (model+market blended) chance it hits. We
    keep the model-only and market-only probabilities alongside for transparency,
    so the site can show where our model and the market agree or diverge.
    """
    match_id: str
    group: str
    commence_time: str
    home: str
    away: str
    market: str                      # "result" | "total" | "btts" | "handicap"
    pick: str                        # human label of the predicted outcome
    prob: float                      # blended probability the pick hits (0..1)
    confidence: float                # 0..1 trust in this probability
    model_prob: float                # model-only probability for the pick
    market_prob: Optional[float]     # market-only probability, if odds available
    outcomes: List[Tuple[str, float]]  # full distribution: (label, prob), desc
    rationale: str = ""

    @property
    def fair_price_american(self) -> int:
        from ..odds_math import implied_to_american
        return implied_to_american(self.prob)

    def to_dict(self) -> dict:
        return {
            "match_id": self.match_id,
            "group": self.group,
            "commence_time": self.commence_time,
            "home": self.home,
            "away": self.away,
            "market": self.market,
            "pick": self.pick,
            "prob": round(self.prob, 4),
            "prob_pct": round(self.prob * 100, 1),
            "confidence": round(self.confidence, 2),
            "model_prob_pct": round(self.model_prob * 100, 1),
            "market_prob_pct": (None if self.market_prob is None
                                else round(self.market_prob * 100, 1)),
            "fair_price_american": self.fair_price_american,
            "outcomes": [{"label": lbl, "prob_pct": round(p * 100, 1)}
                         for lbl, p in self.outcomes],
            "rationale": self.rationale,
        }


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
