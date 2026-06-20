"""Unit tests for the odds math, de-vig consensus, and the prediction engine."""
from __future__ import annotations

import math

from agent.config import Config, StrategyConfig
from agent.engine.devig import fair_from_book, reference_fair
from agent.engine.predict import predict_game
from agent.engine.ratings import TeamModel
from agent.models import BookOdds, Game, Outcome
from agent.odds_math import (
    american_to_decimal,
    american_to_implied,
    decimal_to_american,
    implied_to_american,
)
from agent.rank import rank_predictions, selection_label


# ---------------------------------------------------------------- odds math ---
def test_american_decimal_roundtrip():
    for am in (-250, -150, -110, 100, 145, 320):
        assert decimal_to_american(american_to_decimal(am)) == am


def test_known_conversions():
    assert math.isclose(american_to_decimal(100), 2.0)
    assert math.isclose(american_to_decimal(-110), 1.9090909, rel_tol=1e-6)
    assert math.isclose(american_to_implied(100), 0.5)
    assert implied_to_american(0.5) == 100


# -------------------------------------------------------------------- devig ---
def test_fair_from_book_removes_vig():
    book = BookOdds(book="pinnacle", outcomes=[Outcome("A", -110), Outcome("B", -110)])
    fair, vig = fair_from_book(book)
    assert math.isclose(vig, 0.04762, rel_tol=1e-3)
    assert math.isclose(fair[("A", None)], 0.5, rel_tol=1e-9)
    assert math.isclose(sum(fair.values()), 1.0, rel_tol=1e-12)


def test_reference_consensus_blends_all_books():
    # With no sharp book named, the reference is a consensus across every book.
    game = Game("g", "basketball_nba", "NBA", "2099-01-01T00:00:00+00:00",
                "Home", "Away", markets={"h2h": [
                    BookOdds("draftkings", [Outcome("Away", -120), Outcome("Home", 100)]),
                    BookOdds("fanduel", [Outcome("Away", -125), Outcome("Home", 105)]),
                ]})
    ref = reference_fair(game, "h2h", [], "")
    assert ref.book == "consensus"
    assert ref.fair_by_key[("Away", None)] > 0.5  # Away is the favorite here


# ----------------------------------------------------------- prediction engine ---
def _cfg(**kw) -> Config:
    base = dict(provider="mock", sports=[], markets=["h2h"])
    base.update(kw)
    return Config(**base)


def _h2h_game(away_price, home_price):
    return Game("g", "basketball_nba", "NBA", "2099-01-01T00:00:00+00:00",
                "Home", "Away", markets={"h2h": [
                    BookOdds("draftkings", [Outcome("Away", away_price), Outcome("Home", home_price)]),
                    BookOdds("fanduel", [Outcome("Away", away_price), Outcome("Home", home_price)]),
                ]})


def test_predict_picks_the_market_favorite_when_model_cold():
    # No results -> model is cold -> prediction is the de-vigged consensus.
    game = _h2h_game(-200, 170)  # Away is the heavy favorite
    preds = predict_game(game, TeamModel(), _cfg())
    assert len(preds) == 1
    p = preds[0]
    assert p.market == "h2h"
    assert p.pick == "Away ML" and p.selection == "Away"
    assert p.prob > 0.6
    assert p.model_prob is None          # cold start: market carries it
    assert p.market_prob is not None
    # Outcomes form a distribution.
    assert math.isclose(sum(pr for _, pr in p.outcomes), 1.0, abs_tol=0.01)


def test_model_pulls_prediction_toward_team_strength():
    # Build a model where Home has thrashed everyone; it should lift Home's prob
    # above the pick-em market consensus.
    results = []
    for i in range(6):
        results.append({"sport_key": "basketball_nba", "home": "Home", "away": f"Patsy{i}",
                        "home_score": 120, "away_score": 90, "completed_at": f"2026-01-0{i+1}"})
        results.append({"sport_key": "basketball_nba", "home": f"Patsy{i}", "away": "Away",
                        "home_score": 110, "away_score": 105, "completed_at": f"2026-02-0{i+1}"})
    from agent.engine.ratings import build_team_model
    model = build_team_model(results, min_team_games=3)
    game = _h2h_game(-110, -110)  # market: coin flip
    p = next(x for x in predict_game(game, model, _cfg()) if x.market == "h2h")
    assert p.model_prob is not None          # model is warm for both teams
    assert p.pick == "Home ML"               # model favors the stronger Home side
    assert p.prob > 0.5


def test_rank_predictions_orders_and_keeps_games_whole():
    strong = _h2h_game(-300, 240)
    strong.id = "g_strong"
    even = _h2h_game(-110, -110)
    even.id = "g_even"
    even.markets = {**even.markets, "totals": [
        BookOdds("draftkings", [Outcome("Over", -110, 210.5), Outcome("Under", -110, 210.5)]),
        BookOdds("fanduel", [Outcome("Over", -110, 210.5), Outcome("Under", -110, 210.5)]),
    ]}
    preds = predict_game(strong, TeamModel(), _cfg()) + \
        predict_game(even, TeamModel(), _cfg(markets=["h2h", "totals"]))
    ranked = rank_predictions(preds)
    assert ranked[0].prob >= ranked[-1].prob          # most likely first
    one = rank_predictions(preds, max_games=1)
    assert len({p.game_id for p in one}) == 1          # whole-game cap


def test_selection_label():
    assert selection_label("h2h", "Lakers", None) == "Lakers ML"
    assert selection_label("spreads", "Eagles", -2.5) == "Eagles -2.5"
    assert selection_label("totals", "Over", 8.5) == "Over 8.5"
