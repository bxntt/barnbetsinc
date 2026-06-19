"""Provider interface. A provider turns an external odds source into a list of
normalized `Game` objects. Keeping this narrow lets us swap free APIs (or the
mock) without touching the engine."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..config import Config
from ..models import Game


class OddsProvider(ABC):
    name: str = "base"

    def __init__(self, config: Config):
        self.config = config

    @abstractmethod
    def fetch_odds(self) -> List[Game]:
        """Return games with per-market, per-book odds (including the target book
        and at least one sharp/reference book where available)."""
        raise NotImplementedError


def get_provider(config: Config) -> OddsProvider:
    """Factory: map config.provider to a concrete provider instance."""
    name = (config.provider or "mock").lower()
    if name == "mock":
        from .mock import MockProvider
        return MockProvider(config)
    if name == "odds_api_io":
        from .odds_api_io import OddsApiIoProvider
        return OddsApiIoProvider(config)
    if name == "the_odds_api":
        from .the_odds_api import TheOddsApiProvider
        return TheOddsApiProvider(config)
    raise ValueError(f"Unknown provider: {config.provider!r}")
