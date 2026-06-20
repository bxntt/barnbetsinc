"""Load configuration from config.yaml and secrets from the environment.

Environment variables (via .env or the real environment) hold API keys only;
everything else lives in config.yaml so it's reviewable and committable.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # dotenv is optional at runtime
    pass

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


@dataclass
class ContextConfig:
    injuries: bool = True
    weather: bool = False


@dataclass
class StrategyConfig:
    """Knobs for the prediction engine (consensus blend + team-strength model)."""
    devig_method: str = "power"                 # power | shin | multiplicative
    book_weights: Dict[str, float] = field(default_factory=lambda: {
        "pinnacle": 3.0, "circa": 3.0, "betonlineag": 2.0,
    })
    max_market_weight: float = 0.50             # cap on the market's pull in the blend
    model_min_games: int = 3                     # min games before a team is modeled
    calibration_enabled: bool = True             # reliability tracking from results


@dataclass
class WorldCupConfig:
    """Model-driven World Cup predictor (per-game bet calls + group simulator)."""
    enabled: bool = True
    provider: str = "mock"                      # mock | the_odds_api
    competition: str = "soccer_fifa_world_cup"
    markets: List[str] = field(default_factory=lambda: ["h2h", "totals"])
    regions: str = "us,uk,eu"
    max_published: int = 60                      # cap on games shown (all calls per game kept)
    sims: int = 20000
    seed: int = 42
    injuries_espn: bool = False                  # enrich the injuries page with ESPN live data
    # Live-polling budget guard (the_odds_api provider only). A paid odds poll is
    # only made inside a match window AND within the rolling daily credit cap.
    pre_kickoff_min: int = 60         # start polling this long before kickoff
    post_kickoff_min: int = 150       # keep polling until ~this long after kickoff
    min_interval_min: int = 15        # never poll more than once per this many min
    credit_reserve: int = 20          # never spend below this many remaining credits
    tournament_end: str = "2026-07-19"  # spread remaining credits through this date


@dataclass
class Config:
    provider: str = "mock"
    sports: List[str] = field(default_factory=list)
    markets: List[str] = field(default_factory=lambda: ["h2h", "spreads", "totals"])
    the_odds_api_regions: str = "us,eu"
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    max_published: int = 50
    context: ContextConfig = field(default_factory=ContextConfig)
    worldcup: WorldCupConfig = field(default_factory=WorldCupConfig)
    # US-sports predictor throttle on a live provider (keeps the budget for World Cup).
    engine_min_interval_hours: int = 24
    engine_credit_reserve: int = 20

    # secrets
    odds_api_io_key: Optional[str] = None
    the_odds_api_key: Optional[str] = None

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Config":
        raw = {}
        if path.exists():
            raw = yaml.safe_load(path.read_text()) or {}

        strat = raw.get("strategy", {}) or {}
        ctx = raw.get("context", {}) or {}
        wc = raw.get("worldcup", {}) or {}

        strat_defaults = StrategyConfig()

        return cls(
            provider=raw.get("provider", "mock"),
            sports=raw.get("sports", []),
            markets=raw.get("markets", ["h2h", "spreads", "totals"]),
            the_odds_api_regions=raw.get("the_odds_api_regions", "us,eu"),
            strategy=StrategyConfig(
                devig_method=str(strat.get("devig_method", strat_defaults.devig_method)),
                book_weights=dict(strat.get("book_weights", strat_defaults.book_weights)),
                max_market_weight=float(strat.get("max_market_weight", strat_defaults.max_market_weight)),
                model_min_games=int(strat.get("model_min_games", strat_defaults.model_min_games)),
                calibration_enabled=bool(strat.get("calibration_enabled", strat_defaults.calibration_enabled)),
            ),
            max_published=int(raw.get("max_published", 50)),
            context=ContextConfig(
                injuries=bool(ctx.get("injuries", True)),
                weather=bool(ctx.get("weather", False)),
            ),
            worldcup=WorldCupConfig(
                enabled=bool(wc.get("enabled", True)),
                provider=wc.get("provider", "mock"),
                competition=wc.get("competition", "soccer_fifa_world_cup"),
                markets=wc.get("markets", ["h2h", "totals"]),
                regions=wc.get("regions", "us,uk,eu"),
                max_published=int(wc.get("max_published", 60)),
                sims=int(wc.get("sims", 20000)),
                seed=int(wc.get("seed", 42)),
                injuries_espn=bool(wc.get("injuries_espn", False)),
                pre_kickoff_min=int(wc.get("pre_kickoff_min", 60)),
                post_kickoff_min=int(wc.get("post_kickoff_min", 150)),
                min_interval_min=int(wc.get("min_interval_min", 15)),
                credit_reserve=int(wc.get("credit_reserve", 20)),
                tournament_end=str(wc.get("tournament_end", "2026-07-19")),
            ),
            engine_min_interval_hours=int(raw.get("engine_min_interval_hours", 24)),
            engine_credit_reserve=int(raw.get("engine_credit_reserve", 20)),
            odds_api_io_key=os.getenv("ODDS_API_IO_KEY") or None,
            the_odds_api_key=os.getenv("THE_ODDS_API_KEY") or None,
        )
