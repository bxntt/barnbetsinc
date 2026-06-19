"""Unit tests for the sportsbook-agnostic World Cup tools."""
from __future__ import annotations

import math

from agent.models import BookOdds, Game, Outcome
from agent.worldcup.devig import consensus_fair
from agent.worldcup.models import Match
from agent.worldcup.poisson import fit_lambdas, outcome_probs
from agent.worldcup.provider import mock_matches
from agent.worldcup.simulate import simulate
from agent.worldcup.value import find_value


def _future(hours: float = 48) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _match(h2h_books, group="A", totals_books=None):
    markets = {"h2h": h2h_books}
    if totals_books:
        markets["totals"] = totals_books
    game = Game("m1", "soccer_fifa_world_cup", "World Cup", _future(),
                "Home", "Away", markets=markets)
    return Match(game=game, group=group, matchday=2)


# -------------------------------------------------------------- 3-way devig ---
def test_consensus_fair_3way_removes_vig_and_sums_to_one():
    # Two books on a 1X2 market; each carries vig, consensus should be no-vig.
    books = [
        BookOdds("pinnacle", [Outcome("Home", -110), Outcome("Draw", 260), Outcome("Away", 280)]),
        BookOdds("bet365", [Outcome("Home", -115), Outcome("Draw", 250), Outcome("Away", 300)]),
    ]
    fair = consensus_fair(books)
    assert fair is not None
    assert fair.n_books == 2
    assert math.isclose(sum(fair.fair_by_key.values()), 1.0, rel_tol=1e-9)
    assert fair.vig > 0  # the books hold a margin
    # Home is the favorite here.
    assert fair.fair_by_key[("Home", None)] > fair.fair_by_key[("Away", None)]


def test_consensus_needs_two_outcomes():
    books = [BookOdds("pinnacle", [Outcome("Home", -110)])]
    assert consensus_fair(books) is None


# ----------------------------------------------------------------- poisson ---
def test_outcome_probs_sum_to_one():
    # Sums to ~1 minus the truncated tail beyond MAX_GOALS (negligible).
    p = outcome_probs(1.6, 1.1)
    assert math.isclose(sum(p), 1.0, rel_tol=1e-4)


def test_fit_lambdas_roundtrip():
    # Probabilities generated from known lambdas should recover them closely.
    lh, la = 1.8, 0.9
    ph, pd, pa = outcome_probs(lh, la)
    fh, fa = fit_lambdas(ph, pd, pa)
    assert abs(fh - lh) < 0.12
    assert abs(fa - la) < 0.12


# ------------------------------------------------------------- value finder ---
def test_value_detected_for_outlier_best_price():
    # Two books price the away side ~+290; a third dangles +650 -> clear +EV.
    books = [
        BookOdds("a", [Outcome("Home", -150), Outcome("Draw", 280), Outcome("Away", 320)]),
        BookOdds("b", [Outcome("Home", -145), Outcome("Draw", 290), Outcome("Away", 330)]),
        BookOdds("c", [Outcome("Home", -170), Outcome("Draw", 270), Outcome("Away", 650)]),
    ]
    quotes = find_value(_match(books), markets=["h2h"], min_ev_pct=2.0)
    away = [q for q in quotes if q.selection == "Away"]
    assert away, "expected the underpriced Away side to be flagged"
    assert away[0].best_book == "c"
    assert away[0].best_price_american == 650
    assert away[0].ev_pct > 2.0


def test_no_value_when_books_agree():
    # Identical, vig-inclusive books -> best price never beats the fair line.
    book = lambda name: BookOdds(name, [
        Outcome("Home", -120), Outcome("Draw", 270), Outcome("Away", 280)])
    quotes = find_value(_match([book("a"), book("b"), book("c")]),
                        markets=["h2h"], min_ev_pct=2.0)
    assert quotes == []


def test_played_match_yields_no_value():
    books = [BookOdds("a", [Outcome("Home", -150), Outcome("Draw", 280), Outcome("Away", 650)])]
    m = _match(books)
    m.played = True
    m.home_goals, m.away_goals = 2, 1
    assert find_value(m, markets=["h2h"], min_ev_pct=1.0) == []


# --------------------------------------------------------------- simulator ---
def test_mock_field_shape():
    matches = mock_matches(seed=7)
    assert len(matches) == 72                       # 12 groups x 6 matches
    assert sum(1 for m in matches if m.played) == 24  # matchday 1 already played
    assert {m.group for m in matches} == set("ABCDEFGHIJKL")


def test_simulation_invariants():
    projections = simulate(mock_matches(seed=7), sims=3000, seed=1)
    assert len(projections) == 12
    teams = [t for g in projections for t in g.teams]
    assert len(teams) == 48

    for t in teams:
        assert 0.0 <= t.p_advance <= 1.0
        assert 0.0 <= t.p_win_group <= 1.0
        assert t.p_win_group <= t.p_top2 + 1e-9      # winning ⊆ top-2
        assert t.p_top2 <= t.p_advance + 1e-9        # top-2 ⊆ advancing

    # One winner per group, and 32 teams advance (24 top-2 + 8 best thirds).
    assert abs(sum(t.p_win_group for t in teams) - 12.0) < 0.4
    assert abs(sum(t.p_advance for t in teams) - 32.0) < 0.6
