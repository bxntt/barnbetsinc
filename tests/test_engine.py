"""Unit tests for the odds math, de-vig, EV, and ranking engine."""
from __future__ import annotations

import math

import pytest

from agent.config import Config
from agent.engine.devig import fair_from_book, reference_fair
from agent.engine.ev import evaluate_game
from agent.models import BookOdds, Game, Outcome
from agent.odds_math import (
    american_to_decimal,
    american_to_implied,
    decimal_to_american,
    implied_to_american,
)
from agent.rank import rank_bets, selection_label


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
    # -110 / -110 market: each implies ~52.38%, total ~104.76% (4.76% vig).
    book = BookOdds(book="pinnacle", outcomes=[
        Outcome("A", -110), Outcome("B", -110),
    ])
    fair, vig = fair_from_book(book)
    assert math.isclose(vig, 0.04762, rel_tol=1e-3)
    # Symmetric market -> fair is 50/50 and sums to 1.
    assert math.isclose(fair[("A", None)], 0.5, rel_tol=1e-9)
    assert math.isclose(sum(fair.values()), 1.0, rel_tol=1e-12)


def test_reference_prefers_configured_sharp_book():
    game = Game("g", "basketball_nba", "NBA", "2099-01-01T00:00:00+00:00",
                "Home", "Away", markets={"h2h": [
                    BookOdds("hardrockbet", [Outcome("Away", -110), Outcome("Home", -110)]),
                    BookOdds("pinnacle", [Outcome("Away", -130), Outcome("Home", 110)]),
                ]})
    ref = reference_fair(game, "h2h", ["pinnacle"], "hardrockbet")
    assert ref.book == "pinnacle"


def test_reference_consensus_fallback_excludes_target():
    # No sharp book present -> consensus of the non-target books.
    game = Game("g", "basketball_nba", "NBA", "2099-01-01T00:00:00+00:00",
                "Home", "Away", markets={"h2h": [
                    BookOdds("hardrockbet", [Outcome("Away", 200), Outcome("Home", -250)]),
                    BookOdds("draftkings", [Outcome("Away", -120), Outcome("Home", 100)]),
                    BookOdds("fanduel", [Outcome("Away", -125), Outcome("Home", 105)]),
                ]})
    ref = reference_fair(game, "h2h", ["pinnacle"], "hardrockbet")
    assert ref.book == "consensus"
    # Consensus must not be skewed by Hard Rock's outlier price.
    assert ref.fair_by_key[("Away", None)] > 0.5


# ----------------------------------------------------------------------- EV ---
def _cfg(**kw) -> Config:
    base = dict(provider="mock", target_book="hardrockbet", sharp_books=["pinnacle"],
                sports=[], markets=["h2h"], min_ev_pct=2.0)
    base.update(kw)
    return Config(**base)


def test_positive_ev_detected_and_negative_ignored():
    # Pinnacle implies Away fair ~55.3%; Hard Rock pays -110 (decimal 1.909)
    # -> EV = 0.553*1.909 - 1 ~= +5.5%. The Home side is clearly -EV.
    game = Game("g", "basketball_nba", "NBA", "2099-01-01T00:00:00+00:00",
                "Home", "Away", markets={"h2h": [
                    BookOdds("pinnacle", [Outcome("Away", -128), Outcome("Home", 120)]),
                    BookOdds("hardrockbet", [Outcome("Away", -110), Outcome("Home", -110)]),
                ]})
    bets = evaluate_game(game, _cfg())
    assert len(bets) == 1
    bet = bets[0]
    assert bet.selection == "Away"
    assert 5.0 < bet.ev_pct < 6.0
    assert math.isclose(bet.fair_prob, 0.5526, rel_tol=1e-3)


def test_no_bet_when_hardrock_is_worse_than_market():
    game = Game("g", "basketball_nba", "NBA", "2099-01-01T00:00:00+00:00",
                "Home", "Away", markets={"h2h": [
                    BookOdds("pinnacle", [Outcome("Away", -150), Outcome("Home", 134)]),
                    BookOdds("hardrockbet", [Outcome("Away", -170), Outcome("Home", 120)]),
                ]})
    assert evaluate_game(game, _cfg()) == []


def test_spread_requires_matching_point():
    # Hard Rock offers a +EV-looking price but at a DIFFERENT line than the
    # reference, so it must not be compared (no recommendation).
    game = Game("g", "americanfootball_nfl", "NFL", "2099-01-01T00:00:00+00:00",
                "Home", "Away", markets={"spreads": [
                    BookOdds("pinnacle", [Outcome("Away", -110, -3.5), Outcome("Home", -110, 3.5)]),
                    BookOdds("hardrockbet", [Outcome("Away", 120, -2.5), Outcome("Home", -140, 2.5)]),
                ]})
    cfg = _cfg(markets=["spreads"])
    assert evaluate_game(game, cfg) == []


# --------------------------------------------------------------------- rank ---
def test_ranking_weights_confidence():
    # Two bets: lower raw EV but high confidence should beat higher EV/low conf.
    from agent.models import BestBet
    high_ev_low_conf = BestBet("g1", "nba", "NBA", "2099-01-01T00:00:00+00:00",
                               "H", "A", "h2h", "A", None, "hardrockbet",
                               -110, 0.55, ev_pct=6.0, confidence=0.3,
                               reference_book="consensus", market_vig=0.08)
    low_ev_high_conf = BestBet("g2", "nba", "NBA", "2099-01-01T00:00:00+00:00",
                               "H", "A", "h2h", "A", None, "hardrockbet",
                               -110, 0.55, ev_pct=4.0, confidence=1.0,
                               reference_book="pinnacle", market_vig=0.02)
    ranked = rank_bets([high_ev_low_conf, low_ev_high_conf])
    assert ranked[0].ev_pct == 4.0  # confidence-weighted winner


def test_selection_label():
    assert selection_label("h2h", "Lakers", None) == "Lakers ML"
    assert selection_label("spreads", "Eagles", -2.5) == "Eagles -2.5"
    assert selection_label("totals", "Over", 8.5) == "Over 8.5"
