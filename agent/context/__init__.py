"""Optional context enrichment for best bets (injuries, weather).

Enrichment is best-effort and fully fail-safe: any network error leaves bets
untouched rather than breaking the pipeline. Controlled by config.context flags
(off by default so core runs stay fast, offline, and deterministic).
"""
from __future__ import annotations

from typing import List

from ..config import Config
from ..models import BestBet


def enrich(bets: List[BestBet], config: Config) -> None:
    if not bets:
        return
    if config.context.injuries:
        try:
            from . import espn
            espn.annotate(bets)
        except Exception:
            pass  # context is secondary; never break the run
    if config.context.weather:
        try:
            from . import weather
            weather.annotate(bets)
        except Exception:
            pass
