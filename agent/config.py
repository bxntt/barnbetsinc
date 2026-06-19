"""Load configuration from config.yaml and secrets from the environment.

Environment variables (via .env or the real environment) hold API keys only;
everything else lives in config.yaml so it's reviewable and committable.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

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
class Config:
    provider: str = "mock"
    target_book: str = "hardrockbet"
    sharp_books: List[str] = field(default_factory=lambda: ["pinnacle"])
    sports: List[str] = field(default_factory=list)
    markets: List[str] = field(default_factory=lambda: ["h2h", "spreads", "totals"])
    the_odds_api_regions: str = "us,eu"
    min_ev_pct: float = 2.0
    confidence: ConfidenceConfig = field(default_factory=ConfidenceConfig)
    max_published: int = 50
    context: ContextConfig = field(default_factory=ContextConfig)

    # secrets
    odds_api_io_key: Optional[str] = None
    the_odds_api_key: Optional[str] = None

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Config":
        raw = {}
        if path.exists():
            raw = yaml.safe_load(path.read_text()) or {}

        conf = raw.get("confidence", {}) or {}
        ctx = raw.get("context", {}) or {}

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
            max_published=int(raw.get("max_published", 50)),
            context=ContextConfig(
                injuries=bool(ctx.get("injuries", True)),
                weather=bool(ctx.get("weather", False)),
            ),
            odds_api_io_key=os.getenv("ODDS_API_IO_KEY") or None,
            the_odds_api_key=os.getenv("THE_ODDS_API_KEY") or None,
        )
