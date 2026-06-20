"""odds-api.io provider — generous free tier (100 req/hour), 250+ bookmakers.

NOTE: odds-api.io uses a two-step flow (GET /events then GET /odds?eventId=...)
and its public docs do not fully pin down the odds JSON field names or whether
prices are decimal or American. The parser below is therefore DEFENSIVE and
clearly isolated in `_parse_odds_payload` / `_outcomes_from_market` — once you
have a key, print a sample /odds response and adjust the field names there if
needed. `_to_american` auto-detects decimal vs American prices.

Docs: https://docs.odds-api.io/   Base: https://api.odds-api.io/v3/
"""
from __future__ import annotations

from typing import List, Optional

import requests

from ..models import BookOdds, Game, Outcome
from ..odds_math import decimal_to_american
from .base import OddsProvider

_BASE = "https://api.odds-api.io/v3"
_TIMEOUT = 15

# Our canonical sport keys -> odds-api.io sport slugs.
_SPORT_SLUGS = {
    "americanfootball_nfl": "americanfootball",
    "americanfootball_ncaaf": "americanfootball",
    "basketball_nba": "basketball",
    "basketball_ncaab": "basketball",
    "baseball_mlb": "baseball",
    "icehockey_nhl": "icehockey",
}

# Map common market labels to our canonical keys.
_MARKET_ALIASES = {
    "moneyline": "h2h", "ml": "h2h", "h2h": "h2h", "1x2": "h2h",
    "spread": "spreads", "spreads": "spreads", "handicap": "spreads",
    "asian handicap": "spreads", "total": "totals", "totals": "totals",
    "over/under": "totals", "ou": "totals",
}


def _normalize_book(name: str) -> str:
    """Canonicalize a bookmaker label, e.g. 'DraftKings' -> 'draftkings'."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _to_american(value) -> Optional[int]:
    """Accept either American (ints with |v|>=100) or decimal (floats >1) odds."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v >= 100 or v <= -100:          # already American
        return int(round(v))
    if 1.0 < v < 100:                  # decimal odds
        return decimal_to_american(v)
    return None


class OddsApiIoProvider(OddsProvider):
    name = "odds_api_io"

    def fetch_odds(self) -> List[Game]:
        if not self.config.odds_api_io_key:
            raise RuntimeError(
                "ODDS_API_IO_KEY is not set. Add it to .env or switch provider to 'mock'."
            )
        games: List[Game] = []
        seen_slugs = set()
        for sport_key in self.config.sports:
            slug = _SPORT_SLUGS.get(sport_key)
            if not slug or slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            for ev in self._list_events(slug):
                game = self._fetch_event_odds(ev, sport_key)
                if game and game.markets:
                    games.append(game)
        return games

    def _list_events(self, sport_slug: str) -> List[dict]:
        params = {"apiKey": self.config.odds_api_io_key, "sport": sport_slug}
        resp = requests.get(f"{_BASE}/events", params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        # Tolerate either a bare list or {"events": [...]} / {"data": [...]}.
        if isinstance(data, dict):
            data = data.get("events") or data.get("data") or []
        return data or []

    def _fetch_event_odds(self, ev: dict, sport_key: str) -> Optional[Game]:
        event_id = ev.get("id") or ev.get("eventId")
        if not event_id:
            return None
        params = {"apiKey": self.config.odds_api_io_key, "eventId": event_id}
        resp = requests.get(f"{_BASE}/odds", params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return self._parse_odds_payload(resp.json(), ev, sport_key)

    # ---- Adjust the two methods below to match your account's JSON if needed ----

    def _parse_odds_payload(self, payload: dict, ev: dict, sport_key: str) -> Optional[Game]:
        if isinstance(payload, dict) and "data" in payload:
            payload = payload["data"]
        home = ev.get("home") or ev.get("home_team") or payload.get("home", "")
        away = ev.get("away") or ev.get("away_team") or payload.get("away", "")
        game = Game(
            id=str(ev.get("id") or ev.get("eventId")),
            sport_key=sport_key,
            sport_title=ev.get("league") or sport_key,
            commence_time=ev.get("startTime") or ev.get("commence_time") or "",
            home_team=home,
            away_team=away,
            markets={},
        )
        bookmakers = payload.get("bookmakers") or payload.get("books") or []
        for bm in bookmakers:
            book_key = _normalize_book(bm.get("name") or bm.get("key") or "")
            for mkt in bm.get("markets") or bm.get("odds") or []:
                mkey = _MARKET_ALIASES.get(str(mkt.get("name") or mkt.get("key") or "").lower())
                if not mkey:
                    continue
                outcomes = self._outcomes_from_market(mkt, home, away)
                if outcomes:
                    game.markets.setdefault(mkey, []).append(
                        BookOdds(book=book_key, outcomes=outcomes)
                    )
        return game

    @staticmethod
    def _outcomes_from_market(mkt: dict, home: str, away: str) -> List[Outcome]:
        outcomes: List[Outcome] = []
        for o in mkt.get("outcomes") or mkt.get("selections") or []:
            american = _to_american(o.get("price") or o.get("odds"))
            if american is None:
                continue
            outcomes.append(Outcome(
                name=o.get("name") or o.get("selection") or "",
                price_american=american,
                point=o.get("point") if o.get("point") is not None else o.get("handicap"),
            ))
        return outcomes
