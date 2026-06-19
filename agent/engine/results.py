"""Final-score grading from ESPN's public scoreboard (free, no key).

Best-effort: for each sport in the slate, pull ESPN's scoreboard and keep the
games that are final, with both scores. These settle past recommendations for the
calibration loop. Any network error returns nothing rather than breaking the run.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import requests

# Canonical sport_key -> ESPN scoreboard path (mirrors context/espn.py).
_ESPN_PATHS = {
    "americanfootball_nfl": "football/nfl",
    "americanfootball_ncaaf": "football/college-football",
    "basketball_nba": "basketball/nba",
    "basketball_ncaab": "basketball/mens-college-basketball",
    "baseball_mlb": "baseball/mlb",
    "icehockey_nhl": "hockey/nhl",
}
_BASE = "https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"
_TIMEOUT = 5


def _final_games(sport_key: str) -> List[dict]:
    path = _ESPN_PATHS.get(sport_key)
    if not path:
        return []
    resp = requests.get(_BASE.format(path=path), timeout=_TIMEOUT)
    resp.raise_for_status()
    out: List[dict] = []
    for ev in resp.json().get("events", []) or []:
        status = ev.get("status", {}).get("type", {})
        if status.get("state") != "post" or not status.get("completed"):
            continue
        comp = (ev.get("competitions") or [{}])[0]
        home = away = hs = as_ = None
        for c in comp.get("competitors", []):
            team = (c.get("team") or {}).get("displayName")
            try:
                score = int(c.get("score"))
            except (TypeError, ValueError):
                continue
            if c.get("homeAway") == "home":
                home, hs = team, score
            elif c.get("homeAway") == "away":
                away, as_ = team, score
        if None in (home, away, hs, as_):
            continue
        out.append({
            "game_id": str(ev.get("id")),
            "sport_key": sport_key,
            "home": home,
            "away": away,
            "home_score": hs,
            "away_score": as_,
            "completed_at": ev.get("date"),
        })
    return out


def fetch_results(sport_keys: List[str]) -> List[dict]:
    """Final scores for the given sports. Never raises."""
    seen: Dict[str, dict] = {}
    for sk in set(sport_keys):
        try:
            for g in _final_games(sk):
                seen[g["game_id"]] = g
        except Exception:
            continue
    return list(seen.values())


def nickname(team: Optional[str]) -> str:
    """Last word of a team name, lowercased — a loose cross-provider join key."""
    return (team or "").strip().lower().split()[-1] if team else ""
