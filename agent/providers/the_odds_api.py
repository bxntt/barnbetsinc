"""The Odds API (the-odds-api.com) provider — the recommended real data source.

Free tier: 500 credits/mo. One call per sport returns every bookmaker (US books in
the `us` region, and Pinnacle as `pinnacle` in EU), which feed the consensus blend.
Cost per call = (#markets x #regions). Tune `sports`, `markets`, and
`the_odds_api_regions` in config.yaml to stay within budget.

Docs: https://the-odds-api.com/liveapi/guides/v4/
"""
from __future__ import annotations

from typing import List

import requests

from ..models import BookOdds, Game, Outcome
from .base import OddsProvider

_BASE = "https://api.the-odds-api.com/v4/sports/{sport}/odds"
_TIMEOUT = 15


class TheOddsApiProvider(OddsProvider):
    name = "the_odds_api"

    def fetch_odds(self) -> List[Game]:
        if not self.config.the_odds_api_key:
            raise RuntimeError(
                "THE_ODDS_API_KEY is not set. Add it to .env or switch provider to 'mock'."
            )
        games: List[Game] = []
        for sport in self.config.sports:
            games.extend(self._fetch_sport(sport))
        return games

    def _fetch_sport(self, sport: str) -> List[Game]:
        params = {
            "apiKey": self.config.the_odds_api_key,
            "regions": self.config.the_odds_api_regions,
            "markets": ",".join(self.config.markets),
            "oddsFormat": "american",
            "dateFormat": "iso",
        }
        resp = requests.get(_BASE.format(sport=sport), params=params, timeout=_TIMEOUT)
        if resp.status_code == 422:
            # Sport out of season / unknown key -> no games, not an error.
            return []
        resp.raise_for_status()
        return [self._parse_event(ev) for ev in resp.json()]

    @staticmethod
    def _parse_event(ev: dict) -> Game:
        game = Game(
            id=ev["id"],
            sport_key=ev.get("sport_key", ""),
            sport_title=ev.get("sport_title", ""),
            commence_time=ev.get("commence_time", ""),
            home_team=ev.get("home_team", ""),
            away_team=ev.get("away_team", ""),
            markets={},
        )
        for bm in ev.get("bookmakers", []):
            book_key = bm.get("key", "")
            last_update = bm.get("last_update")
            for mkt in bm.get("markets", []):
                mkey = mkt.get("key")
                if not mkey:
                    continue
                outcomes = [
                    Outcome(
                        name=o.get("name", ""),
                        price_american=int(o["price"]),
                        point=o.get("point"),
                    )
                    for o in mkt.get("outcomes", [])
                    if o.get("price") is not None
                ]
                if outcomes:
                    game.markets.setdefault(mkey, []).append(
                        BookOdds(book=book_key, outcomes=outcomes, last_update=last_update)
                    )
        return game
