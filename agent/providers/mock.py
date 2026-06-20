"""Mock odds provider.

Generates a realistic, fixed slate of games across sports, each priced by a few
books (Pinnacle plus a couple of US books) so the de-vig consensus has something
to blend. Lets the full pipeline and website run with no API key.

Prices vary modestly book-to-book, as they do in the real market.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from ..config import Config
from ..models import BookOdds, Game, Outcome
from .base import OddsProvider


def _iso_in(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _book(name: str, outcomes: List[tuple]) -> BookOdds:
    """outcomes: list of (selection, american, point_or_None)."""
    return BookOdds(
        book=name,
        last_update=datetime.now(timezone.utc).isoformat(),
        outcomes=[Outcome(name=o[0], price_american=o[1], point=o[2]) for o in outcomes],
    )


class MockProvider(OddsProvider):
    name = "mock"

    def fetch_odds(self) -> List[Game]:
        games: List[Game] = []

        # --- Game A: NBA moneyline, Lakers a slight consensus favorite ---
        games.append(Game(
            id="mock-nba-lal-bos",
            sport_key="basketball_nba",
            sport_title="NBA",
            commence_time=_iso_in(4),
            home_team="Boston Celtics",
            away_team="Los Angeles Lakers",
            markets={
                "h2h": [
                    _book("pinnacle", [("Los Angeles Lakers", -128, None),
                                       ("Boston Celtics", 120, None)]),
                    _book("caesars", [("Los Angeles Lakers", -110, None),
                                      ("Boston Celtics", -110, None)]),
                    _book("draftkings", [("Los Angeles Lakers", -125, None),
                                         ("Boston Celtics", 105, None)]),
                ],
            },
        ))

        # --- Game B: NFL spread, Eagles favored to cover -2.5 ---
        games.append(Game(
            id="mock-nfl-phi-dal",
            sport_key="americanfootball_nfl",
            sport_title="NFL",
            commence_time=_iso_in(28),
            home_team="Dallas Cowboys",
            away_team="Philadelphia Eagles",
            markets={
                "spreads": [
                    _book("pinnacle", [("Philadelphia Eagles", -120, -2.5),
                                       ("Dallas Cowboys", 100, 2.5)]),
                    _book("betmgm", [("Philadelphia Eagles", 100, -2.5),
                                     ("Dallas Cowboys", -120, 2.5)]),
                    _book("fanduel", [("Philadelphia Eagles", -115, -2.5),
                                      ("Dallas Cowboys", -105, 2.5)]),
                ],
            },
        ))

        # --- Game C: MLB totals, books tightly agree on a coin-flip 8.5 ---
        games.append(Game(
            id="mock-mlb-nyy-bos",
            sport_key="baseball_mlb",
            sport_title="MLB",
            commence_time=_iso_in(6),
            home_team="Boston Red Sox",
            away_team="New York Yankees",
            markets={
                "totals": [
                    _book("pinnacle", [("Over", -105, 8.5), ("Under", -105, 8.5)]),
                    _book("caesars", [("Over", -110, 8.5), ("Under", -110, 8.5)]),
                    _book("betmgm", [("Over", -108, 8.5), ("Under", -108, 8.5)]),
                ],
            },
        ))

        # --- Game D: NHL moneyline, Avalanche favored at home ---
        games.append(Game(
            id="mock-nhl-edm-col",
            sport_key="icehockey_nhl",
            sport_title="NHL",
            commence_time=_iso_in(9),
            home_team="Colorado Avalanche",
            away_team="Edmonton Oilers",
            markets={
                "h2h": [
                    _book("pinnacle", [("Edmonton Oilers", 112, None),
                                       ("Colorado Avalanche", -122, None)]),
                    _book("draftkings", [("Edmonton Oilers", 124, None),
                                         ("Colorado Avalanche", -136, None)]),
                ],
            },
        ))

        # --- Game E: NBA moneyline, Warriors a clear road favorite ---
        games.append(Game(
            id="mock-nba-gsw-mia",
            sport_key="basketball_nba",
            sport_title="NBA",
            commence_time=_iso_in(5),
            home_team="Miami Heat",
            away_team="Golden State Warriors",
            markets={
                "h2h": [
                    _book("pinnacle", [("Golden State Warriors", -150, None),
                                       ("Miami Heat", 134, None)]),
                    _book("fanduel", [("Golden State Warriors", -170, None),
                                      ("Miami Heat", 120, None)]),
                ],
            },
        ))

        return games
