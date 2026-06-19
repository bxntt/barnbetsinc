"""Unit tests for the sportsbook-agnostic World Cup tools."""
from __future__ import annotations

import math

from agent.models import BookOdds, Game, Outcome
from agent.worldcup import fixtures, ratings
from agent.worldcup.devig import consensus_fair
from agent.worldcup.models import Match
from agent.worldcup.poisson import fit_lambdas, outcome_probs, score_matrix
from agent.worldcup.predict import predict_match, predict_all, rank_predictions
from agent.worldcup.provider import mock_matches
from agent.worldcup.simulate import simulate


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


# ---------------------------------------------------------------- ratings ---
def test_ratings_resolve_aliases_and_default():
    # Canonical, alias, and unknown all resolve sanely.
    assert ratings.base_rating("Argentina") > ratings.base_rating("Jordan")
    assert ratings.base_rating("Korea Republic") == ratings.base_rating("South Korea")
    assert ratings.base_rating("Atlantis") == ratings.DEFAULT_RATING


def test_form_delta_rewards_results():
    # A team with 2 wins and +6 GD should get a positive nudge; a loser negative.
    winner = ratings.form_delta({"points": 6, "gd": 6, "gf": 7, "played": 2})
    loser = ratings.form_delta({"points": 0, "gd": -6, "gf": 1, "played": 2})
    assert winner > 0 > loser
    assert abs(winner) <= 90.0 and abs(loser) <= 90.0  # capped


def test_lambdas_favor_the_stronger_side():
    lh, la = ratings.lambdas(2100, 1700)  # strong home vs weak away
    assert lh > la


# ---------------------------------------------------------- score matrix ---
def test_score_matrix_is_a_distribution():
    grid = score_matrix(1.6, 1.1)
    total = sum(cell for row in grid for cell in row)
    assert math.isclose(total, 1.0, rel_tol=1e-4)


# -------------------------------------------------------------- predictions ---
def test_predict_emits_a_call_per_market():
    books = [
        BookOdds("a", [Outcome("Home", -150), Outcome("Draw", 280), Outcome("Away", 320)]),
        BookOdds("b", [Outcome("Home", -145), Outcome("Draw", 290), Outcome("Away", 330)]),
    ]
    preds = predict_match(_match(books))
    markets = {p.market for p in preds}
    assert markets == {"result", "total", "btts", "handicap"}
    for p in preds:
        assert 0.0 <= p.prob <= 1.0
        assert 0.0 <= p.confidence <= 1.0
        # The pick is the most likely outcome in its market.
        assert p.pick == max(p.outcomes, key=lambda o: o[1])[0]
        # Each market's outcomes form a distribution.
        assert math.isclose(sum(pr for _, pr in p.outcomes), 1.0, abs_tol=0.02)


def test_prediction_favors_stronger_team_without_market():
    # No odds at all -> pure model. Argentina should be favored over Jordan.
    game = Game("m", "soccer_fifa_world_cup", "World Cup", _future(),
                "Argentina", "Jordan", markets={})
    preds = predict_match(Match(game=game, group="J", matchday=2))
    result = next(p for p in preds if p.market == "result")
    assert result.pick == "Argentina win"
    assert result.prob > 0.5
    assert result.market_prob is None  # no market to blend


def test_played_match_yields_no_prediction():
    books = [BookOdds("a", [Outcome("Home", -150), Outcome("Draw", 280), Outcome("Away", 650)])]
    m = _match(books)
    m.played = True
    m.home_goals, m.away_goals = 2, 1
    assert predict_match(m) == []


def test_rank_predictions_orders_by_probability_and_keeps_whole_games():
    strong = Game("g1", "soccer_fifa_world_cup", "World Cup", _future(),
                  "Argentina", "Jordan", markets={})       # lopsided -> high-prob calls
    weak = Game("g2", "soccer_fifa_world_cup", "World Cup", _future(),
                "Spain", "Portugal", markets={})           # even -> lower-prob calls
    preds = predict_all([Match(game=strong, group="J", matchday=2),
                         Match(game=weak, group="H", matchday=2)])

    ranked = rank_predictions(preds)
    assert ranked[0].prob >= ranked[-1].prob               # sorted most-likely first

    # Capping to one game keeps ALL of that game's market calls, not a partial set.
    one = rank_predictions(preds, limit_games=1)
    assert len({p.match_id for p in one}) == 1
    assert {p.market for p in one} == {"result", "total", "btts", "handicap"}


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


# ----------------------------------------------------- real 2026 fixtures map ---
def test_fixtures_map_is_a_complete_48_team_draw():
    standings = fixtures.group_standings()
    assert set(standings) == set("ABCDEFGHIJKL")               # 12 groups
    teams = [t for g in standings.values() for t in g]
    assert len(teams) == 48 and len(set(teams)) == 48          # 48 distinct teams
    assert all(len(g) == 4 for g in standings.values())        # 4 per group


def test_canonical_team_bridges_feed_spellings():
    # Accents, '&', and common alternate names all resolve to one canonical team.
    assert fixtures.canonical_team("Curaçao") == "Curaçao"
    assert fixtures.canonical_team("Bosnia and Herzegovina") == "Bosnia & Herzegovina"
    assert fixtures.canonical_team("Korea Republic") == "South Korea"
    assert fixtures.canonical_team("Côte d'Ivoire") == "Ivory Coast"
    assert fixtures.canonical_team("Atlantis") is None


def test_every_live_feed_pairing_falls_inside_one_group():
    # Real matchups pulled from the live odds feed — each pair must share a group
    # (this is the cross-check that validates the hand-entered draw).
    feed_pairs = [
        ("Belgium", "Iran"), ("New Zealand", "Belgium"), ("New Zealand", "Egypt"),
        ("Brazil", "Haiti"), ("Scotland", "Brazil"), ("Netherlands", "Sweden"),
        ("Tunisia", "Netherlands"), ("Spain", "Saudi Arabia"), ("Uruguay", "Spain"),
        ("France", "Iraq"), ("Senegal", "Iraq"), ("Ecuador", "Curaçao"),
        ("Curaçao", "Ivory Coast"), ("England", "Ghana"), ("Panama", "Croatia"),
        ("Panama", "England"), ("Portugal", "Uzbekistan"), ("Colombia", "DR Congo"),
        ("Bosnia & Herzegovina", "Qatar"), ("Jordan", "Argentina"),
    ]
    for home, away in feed_pairs:
        gh, ga = fixtures.group_of(home), fixtures.group_of(away)
        assert gh is not None and gh == ga, f"{home} vs {away} not in one group"


def test_attach_groups_tags_and_canonicalizes():
    books = [BookOdds("a", [Outcome("Belgium", 120), Outcome("Draw", 240),
                            Outcome("New Zealand", 260)])]
    game = Game("m", "soccer_fifa_world_cup", "World Cup", _future(),
                "Belgium", "New Zealand", markets={"h2h": books})
    m = Match(game=game, group="", matchday=0)
    fixtures.attach_groups([m])
    assert m.group == "G"


def test_seeded_simulation_uses_real_standings():
    # Seed every group from the real table, with one remaining match for Group G.
    books = [BookOdds("a", [Outcome("Belgium", 120), Outcome("Draw", 240),
                            Outcome("New Zealand", 260)])]
    game = Game("m", "soccer_fifa_world_cup", "World Cup", _future(),
                "Belgium", "New Zealand", markets={"h2h": books})
    remaining = [Match(game=game, group="G", matchday=2)]

    projections = simulate(remaining, sims=3000, seed=1,
                           seed_standings=fixtures.group_standings())
    assert len(projections) == 12
    teams = [t for g in projections for t in g.teams]
    assert len(teams) == 48

    for t in teams:
        assert 0.0 <= t.p_advance <= 1.0
        assert t.p_win_group <= t.p_top2 + 1e-9
        assert t.p_top2 <= t.p_advance + 1e-9

    assert abs(sum(t.p_win_group for t in teams) - 12.0) < 0.4
    assert abs(sum(t.p_advance for t in teams) - 32.0) < 0.6

    # Displayed table reflects the seeded standings, not a from-zero recount.
    mexico = next(t for g in projections if g.group == "A"
                  for t in g.teams if t.team == "Mexico")
    assert mexico.points == 6 and mexico.played == 2
