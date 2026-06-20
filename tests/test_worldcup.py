"""Unit tests for the sportsbook-agnostic World Cup tools."""
from __future__ import annotations

import math

from agent.models import BookOdds, Game, Outcome
from agent.worldcup import calibration, factors, fixtures, injuries, ratings
from agent.worldcup.devig import consensus_fair
from agent.worldcup.injuries import Absence
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


def test_dixon_coles_lifts_draws_and_stays_a_distribution():
    lh = la = 1.2
    indep = score_matrix(lh, la, rho=0.0)        # plain independent Poisson
    dc = score_matrix(lh, la)                    # default negative rho
    draw = lambda grid: sum(grid[i][i] for i in range(len(grid)))
    assert draw(dc) > draw(indep)                # the known draw understatement is corrected
    assert math.isclose(sum(c for row in dc for c in row), 1.0, rel_tol=1e-9)
    # Lift comes from the two draws; the one-goal wins are trimmed.
    assert dc[0][0] > indep[0][0] and dc[1][1] > indep[1][1]
    assert dc[1][0] < indep[1][0] and dc[0][1] < indep[0][1]


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


# --------------------------------------------------------------- injuries ---
def _wc_match(home, away, group="C", played=False, mid="inj-m"):
    game = Game(mid, "soccer_fifa_world_cup", "World Cup", _future(),
                home, away, markets={})
    return Match(game=game, group=group, matchday=2, played=played)


def test_injury_report_is_organized_by_game_and_attaches_absences():
    # Brazil has curated absences; Haiti has none.
    games = injuries.build_report([_wc_match("Brazil", "Haiti")])
    assert len(games) == 1
    g = games[0]
    assert g.home == "Brazil" and g.away == "Haiti"
    assert len(g.home_absences) >= 1            # Brazil snapshot has entries
    assert g.away_absences == []                # Haiti: squad as expected
    assert g.total == len(g.home_absences)
    # Out is sorted ahead of Doubtful (severity-first within a team).
    statuses = [a.status.lower() for a in g.home_absences]
    assert statuses == sorted(statuses, key=lambda s: injuries._STATUS_RANK.get(s, 9))


def test_injury_report_skips_played_matches_and_resolves_aliases():
    games = injuries.build_report([
        _wc_match("Brazil", "Haiti", played=True, mid="done"),   # settled -> dropped
        _wc_match("Korea Republic", "Czech Republic", group="A", mid="live"),  # aliases
    ])
    assert [g.match_id for g in games] == ["live"]               # played one is gone


def test_injury_payload_counts_match_games():
    payload = injuries.build_payload(
        injuries.build_report([_wc_match("Brazil", "France")]), used_espn=False)
    assert payload["game_count"] == 1
    assert payload["affected_games"] == 1        # both sides carry absences
    assert payload["total_absences"] == payload["games"][0]["total"]
    assert payload["as_of"] == injuries.AS_OF


def test_team_absences_map_keys_canonical_and_skips_unknown():
    mp = injuries.team_absences_map(["Brazil", "Korea Republic", "Atlantis"])
    assert mp["Brazil"]                          # curated entries present
    assert "South Korea" in mp                   # alias resolved to canonical
    assert "Atlantis" not in mp                  # unknown teams dropped


# ----------------------------------------- factor layer (injuries/form/venue) ---
def test_injury_impact_splits_by_position():
    # A striker hurts only attack; a keeper only defense.
    fw = factors.injury_impact([Absence("Striker", "FW", "Out", expected_starter=True)])
    assert fw.attack_elo > 0 and fw.defense_elo == 0
    gk = factors.injury_impact([Absence("Keeper", "GK", "Out", expected_starter=True)])
    assert gk.defense_elo > 0 and gk.attack_elo == 0


def test_injury_impact_weights_severity_and_role_and_caps():
    out = factors.injury_impact([Absence("X", "FW", "Out", expected_starter=True)]).attack_elo
    doubt = factors.injury_impact([Absence("X", "FW", "Doubtful", expected_starter=True)]).attack_elo
    depth = factors.injury_impact([Absence("X", "FW", "Out")]).attack_elo  # not a starter
    assert doubt < out and depth < out           # doubts and depth pieces count less
    # Even a decimated squad is dampened, not deleted.
    many = [Absence(f"P{i}", "FW", "Out", expected_starter=True, impact=3.0) for i in range(10)]
    cap = factors._MAX_INJURY_GOALS * ratings.RATING_SCALE
    assert factors.injury_impact(many).attack_elo <= cap + 1e-6


def test_venue_edge_only_for_hosts():
    assert factors.venue_edge("Mexico", "Brazil") > 0       # host at home
    assert factors.venue_edge("Brazil", "United States") < 0  # host listed 'away'
    assert factors.venue_edge("Brazil", "Argentina") == 0   # neutral fixture


def test_momentum_tilt_rewards_scoring_and_is_capped():
    atk, _ = factors.momentum_tilt({"points": 3, "gd": 4, "gf": 5, "played": 1})
    assert atk > 0                                          # banging goals in -> totals nudge up
    assert factors.momentum_tilt({"points": 0, "gd": 0, "gf": 0, "played": 0}) == (0.0, 0.0)
    big, _ = factors.momentum_tilt({"points": 3, "gd": 7, "gf": 7, "played": 1})
    assert big <= factors._MAX_FORM_GOALS + 1e-9            # one blowout can't run away


def test_lambdas_attack_defense_adjustments_move_one_side():
    lh0, la0 = ratings.lambdas(1800, 1800, home_advantage=0.0)
    lh_inj, la_inj = ratings.lambdas(1800, 1800, home_advantage=0.0, home_attack_adj=-0.3)
    assert lh_inj < lh0 and abs(la_inj - la0) < 1e-9       # only home scoring drops
    lh_def, _ = ratings.lambdas(1800, 1800, home_advantage=0.0, away_defense_adj=-0.3)
    assert lh_def > lh0                                     # weaker away defense -> home scores more


def test_predict_factors_in_injuries():
    game = Game("m", "soccer_fifa_world_cup", "World Cup", _future(),
                "Brazil", "Haiti", markets={})
    m = Match(game=game, group="C", matchday=2)
    base = next(p for p in predict_match(m) if p.market == "result")
    hurt = next(p for p in predict_match(
        m, home_absences=[Absence("Neymar", "FW", "Out", expected_starter=True, impact=2.0)])
        if p.market == "result")
    assert hurt.prob < base.prob                            # losing a talisman lowers the favorite
    assert "Neymar" in hurt.rationale                       # and the reasoning is surfaced


def test_predict_gives_hosts_their_home_edge():
    # USA is the feed's 'away' team but still plays at home in 2026.
    game = Game("m", "soccer_fifa_world_cup", "World Cup", _future(),
                "Paraguay", "United States", markets={})
    result = next(p for p in predict_match(Match(game=game, group="D", matchday=2))
                  if p.market == "result")
    assert result.pick == "United States win"
    assert "home soil" in result.rationale


# ----------------------------------------------- grading loop (RPS/log loss) ---
def test_rps_is_ordinal_and_zero_when_perfect():
    assert calibration.rps([1.0, 0.0, 0.0], 0) == 0.0
    home = [0.7, 0.2, 0.1]                       # a home-win call...
    assert calibration.rps(home, 1) < calibration.rps(home, 2)  # ...is less wrong on a draw than an away win


def test_log_loss_rewards_confidence_in_the_truth():
    assert calibration.log_loss(1.0) < calibration.log_loss(0.5) < calibration.log_loss(0.01)


def _logged(market, pick, prob, outcomes, home="Brazil", away="Haiti"):
    return {"match_id": "g1", "group": "C", "commence_time": "", "home": home,
            "away": away, "market": market, "pick": pick, "prob": prob,
            "outcomes": outcomes}


def test_grade_scores_each_market_with_the_right_metric():
    preds = [
        _logged("result", "Brazil win", 0.8,
                [["Brazil win", 0.8], ["Draw", 0.12], ["Haiti win", 0.08]]),
        _logged("total", "Over 2.5", 0.55, [["Over 2.5", 0.55], ["Under 2.5", 0.45]]),
        _logged("btts", "BTTS: No", 0.6, [["BTTS: Yes", 0.4], ["BTTS: No", 0.6]]),
        _logged("handicap", "Brazil -1.5", 0.55,
                [["Brazil -1.5", 0.55], ["Haiti +1.5", 0.45]]),
    ]
    results = [{"date": "2026-06-21", "home": "Brazil", "away": "Haiti",
                "home_score": 3, "away_score": 0}]
    g = calibration.grade(preds, results)
    assert g["result"]["n"] == 1
    assert abs(g["result"]["rps"] - 0.0232) < 1e-3      # closed-form RPS for this call
    assert g["graded_total"] == 4
    # Brazil 3-0: over (3>2.5), BTTS No, and -1.5 all hit, so Brier = (prob-1)^2.
    assert abs(g["binary"]["total"]["brier"] - (0.55 - 1) ** 2) < 1e-9
    assert abs(g["binary"]["handicap"]["brier"] - (0.55 - 1) ** 2) < 1e-9


def test_grade_orients_score_to_the_predictions_home_away():
    preds = [_logged("result", "Brazil win", 0.8,
                     [["Brazil win", 0.8], ["Draw", 0.12], ["Haiti win", 0.08]])]
    # Feed lists the same match the other way round — must still grade as a Brazil win.
    results = [{"date": "", "home": "Haiti", "away": "Brazil",
                "home_score": 0, "away_score": 3}]
    g = calibration.grade(preds, results)
    assert g["result"]["n"] == 1 and g["result"]["rps"] < 0.05


def test_grade_handles_no_history():
    g = calibration.grade([], [])
    assert g["graded_total"] == 0 and g["result"]["n"] == 0


def test_log_predictions_dedupes_by_match_and_market(tmp_path, monkeypatch):
    from agent.worldcup.models import Prediction
    monkeypatch.setattr(calibration, "PRED_LOG", tmp_path / "preds.jsonl")
    early = Prediction("g1", "C", "", "Brazil", "Haiti", "result", "Brazil win",
                       0.70, 0.9, 0.70, None,
                       [("Brazil win", 0.70), ("Draw", 0.20), ("Haiti win", 0.10)])
    late = Prediction("g1", "C", "", "Brazil", "Haiti", "result", "Brazil win",
                      0.82, 0.9, 0.82, None,
                      [("Brazil win", 0.82), ("Draw", 0.12), ("Haiti win", 0.06)])
    calibration.log_predictions([early])
    calibration.log_predictions([late])
    loaded = calibration.load_predictions()
    assert len(loaded) == 1 and loaded[0]["prob"] == 0.82   # latest pre-kickoff call wins
