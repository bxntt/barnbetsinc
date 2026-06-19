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
class ConfidenceConfig:
    max_trusted_vig: float = 0.06
    min_minutes_to_start: int = 30


@dataclass
class ContextConfig:
    injuries: bool = True
    weather: bool = False


@dataclass
class StrategyConfig:
    """Knobs for the upgraded value engine (de-vig, guardrails, sizing, model)."""
    devig_method: str = "power"                 # power | shin | multiplicative
    book_weights: Dict[str, float] = field(default_factory=lambda: {
        "pinnacle": 3.0, "circa": 3.0, "betonlineag": 2.0,
    })
    interpolate: bool = True                     # price alternate spread/total lines
    interp_max_reach: float = 2.0                # max points to shift a line
    interp_conf_penalty: float = 0.5            # confidence cut at full reach (0..1)
    longshot_prob: float = 0.30                  # fair_prob below this = longshot
    longshot_penalty: float = 0.5               # confidence floor for extreme longshots
    method_spread_tol: float = 0.04             # de-vig disagreement that fully discounts
    kelly_fraction: float = 0.25                 # fractional Kelly multiplier
    kelly_cap: float = 0.05                      # max stake as fraction of bankroll
    model_enabled: bool = True                   # Elo cross-check flag
    model_disagree: float = 0.10                 # |model-fair| beyond this = disagree
    model_min_games: int = 30                    # min graded games before Elo is trusted
    calibration_enabled: bool = True             # reliability tracking from results


@dataclass
class WorldCupConfig:
    """Sportsbook-agnostic World Cup tools (value finder + group simulator)."""
    enabled: bool = True
    provider: str = "mock"                      # mock | the_odds_api
    competition: str = "soccer_fifa_world_cup"
    markets: List[str] = field(default_factory=lambda: ["h2h", "totals"])
    regions: str = "us,uk,eu"
    min_ev_pct: float = 1.5
    max_published: int = 40
    sims: int = 20000
    seed: int = 42
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
    target_book: str = "hardrockbet"
    sharp_books: List[str] = field(default_factory=lambda: ["pinnacle"])
    sports: List[str] = field(default_factory=list)
    markets: List[str] = field(default_factory=lambda: ["h2h", "spreads", "totals"])
    the_odds_api_regions: str = "us,eu"
    min_ev_pct: float = 2.0
    confidence: ConfidenceConfig = field(default_factory=ConfidenceConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    max_published: int = 50
    context: ContextConfig = field(default_factory=ContextConfig)
    worldcup: WorldCupConfig = field(default_factory=WorldCupConfig)
    # Hard Rock engine throttle on a live provider (keeps the budget for World Cup).
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

        conf = raw.get("confidence", {}) or {}
        strat = raw.get("strategy", {}) or {}
        ctx = raw.get("context", {}) or {}
        wc = raw.get("worldcup", {}) or {}

        strat_defaults = StrategyConfig()

        return cls(
            provider=raw.get("provider", "mock"),
            target_book=raw.get("target_book", "hardrockbet"),
            sharp_books=raw.get("sharp_books", ["pinnacle"]),
            sports=raw.get("sports", []),
            markets=raw.get("markets", ["h2h", "spreads", "totals"]),
            the_odds_api_regions=raw.get("the_odds_api_regions", "us,eu"),
            min_ev_pct=float(raw.get("min_ev_pct", 2.0)),
            confidence=ConfidenceConfig(
                max_trusted_vig=float(conf.get("max_trusted_vig", 0.06)),
                min_minutes_to_start=int(conf.get("min_minutes_to_start", 30)),
            ),
            strategy=StrategyConfig(
                devig_method=str(strat.get("devig_method", strat_defaults.devig_method)),
                book_weights=dict(strat.get("book_weights", strat_defaults.book_weights)),
                interpolate=bool(strat.get("interpolate", strat_defaults.interpolate)),
                interp_max_reach=float(strat.get("interp_max_reach", strat_defaults.interp_max_reach)),
                interp_conf_penalty=float(strat.get("interp_conf_penalty", strat_defaults.interp_conf_penalty)),
                longshot_prob=float(strat.get("longshot_prob", strat_defaults.longshot_prob)),
                longshot_penalty=float(strat.get("longshot_penalty", strat_defaults.longshot_penalty)),
                method_spread_tol=float(strat.get("method_spread_tol", strat_defaults.method_spread_tol)),
                kelly_fraction=float(strat.get("kelly_fraction", strat_defaults.kelly_fraction)),
                kelly_cap=float(strat.get("kelly_cap", strat_defaults.kelly_cap)),
                model_enabled=bool(strat.get("model_enabled", strat_defaults.model_enabled)),
                model_disagree=float(strat.get("model_disagree", strat_defaults.model_disagree)),
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
                min_ev_pct=float(wc.get("min_ev_pct", 1.5)),
                max_published=int(wc.get("max_published", 40)),
                sims=int(wc.get("sims", 20000)),
                seed=int(wc.get("seed", 42)),
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
