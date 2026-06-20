"""ESPN unofficial scoreboard enrichment (free, no key).

Best-effort: for each sport in the bet slate, fetch ESPN's public scoreboard and,
when a game matches by team name, attach a short status/headline note. ESPN
occasionally surfaces injury/news headlines here; at minimum it flags
postponed/delayed games so you don't chase a stale line.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import requests

from ..models import Prediction

# Canonical sport_key -> ESPN scoreboard path.
_ESPN_PATHS = {
    "americanfootball_nfl": "football/nfl",
    "americanfootball_ncaaf": "football/college-football",
    "basketball_nba": "basketball/nba",
    "basketball_ncaab": "basketball/mens-college-basketball",
    "baseball_mlb": "baseball/mlb",
    "icehockey_nhl": "hockey/nhl",
}
_BASE = "https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"
_TIMEOUT = 4


def _fetch_events(sport_key: str) -> List[dict]:
    path = _ESPN_PATHS.get(sport_key)
    if not path:
        return []
    resp = requests.get(_BASE.format(path=path), timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("events", []) or []


def _note_for(events: List[dict], home: str, away: str) -> Optional[str]:
    home_l, away_l = home.lower(), away.lower()
    for ev in events:
        name = ev.get("name", "").lower()  # e.g. "Los Angeles Lakers at Boston Celtics"
        if any(t.split()[-1] in name for t in (home_l, away_l)):
            status = ev.get("status", {}).get("type", {})
            state = status.get("state")
            if state and state != "pre":
                return f"ESPN: game is {status.get('description', state)}."
            headline = (ev.get("competitions", [{}])[0].get("notes") or [{}])[0].get("headline")
            if headline:
                return f"ESPN: {headline}."
    return None


def annotate(bets: List[Prediction]) -> None:
    cache: Dict[str, List[dict]] = {}
    for b in bets:
        if b.sport_key not in cache:
            try:
                cache[b.sport_key] = _fetch_events(b.sport_key)
            except Exception:
                cache[b.sport_key] = []
        note = _note_for(cache[b.sport_key], b.home_team, b.away_team)
        if note:
            b.context = {**(b.context or {}), "notes": note}
