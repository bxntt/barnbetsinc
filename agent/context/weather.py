"""Weather enrichment for outdoor-sport totals via Open-Meteo (free, no key).

Wind and precipitation move totals in MLB and NFL. This is an extension point:
it needs a venue -> (lat, lon) mapping, which the odds feeds don't provide. Until
a venue map is wired in (see VENUE_COORDS), annotate() is a safe no-op so enabling
`context.weather` never breaks a run.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import requests

from ..models import Prediction

# Populate as needed, keyed by home_team name -> (lat, lon).
VENUE_COORDS: Dict[str, Tuple[float, float]] = {}

_FORECAST = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT = 4
_OUTDOOR_SPORTS = {"baseball_mlb", "americanfootball_nfl", "americanfootball_ncaaf"}


def _forecast(lat: float, lon: float) -> Optional[dict]:
    resp = requests.get(
        _FORECAST,
        params={"latitude": lat, "longitude": lon,
                "current": "wind_speed_10m,precipitation"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("current")


def annotate(bets: List[Prediction]) -> None:
    for b in bets:
        if b.market != "totals" or b.sport_key not in _OUTDOOR_SPORTS:
            continue
        coords = VENUE_COORDS.get(b.home_team)
        if not coords:
            continue
        try:
            cur = _forecast(*coords)
        except Exception:
            continue
        if not cur:
            continue
        wind = cur.get("wind_speed_10m")
        if wind is not None and wind >= 15:
            note = f"Weather: wind {wind} mph at {b.home_team} — favors the Under."
            b.context = {**(b.context or {}), "notes": note}
