"""Tests for the prediction engine internals: de-vig methods, the team-strength
model (Elo + scoring), and the calibration loop."""
from __future__ import annotations

import math

from agent.engine.calibration import compute_calibration
from agent.engine.devig import devig_probs
from agent.engine.ratings import build_team_model


# --------------------------------------------------------------- de-vig math ---
def test_all_methods_normalize_and_symmetric():
    raw = [1 / 1.909, 1 / 1.909]  # -110 / -110
    for method in ("multiplicative", "power", "shin"):
        fair = devig_probs(raw, method)
        assert math.isclose(sum(fair), 1.0, rel_tol=1e-9)
        assert math.isclose(fair[0], 0.5, rel_tol=1e-6)


def test_power_corrects_favorite_longshot_bias():
    raw = [1 / 1.25, 1 / 4.0]  # fav decimal 1.25, dog decimal 4.0
    mult = devig_probs(raw, "multiplicative")
    power = devig_probs(raw, "power")
    assert power[0] > mult[0]      # favorite fair prob higher under power
    assert power[1] < mult[1]      # longshot fair prob lower under power


# ----------------------------------------------------- team-strength model ---
def _wins(home, away, hs, as_, n, start_month):
    return [{"sport_key": "x", "home": home, "away": away,
             "home_score": hs, "away_score": as_,
             "completed_at": f"2026-{start_month:02d}-{i+1:02d}"} for i in range(n)]


def test_model_cold_starts_below_min_games():
    model = build_team_model(_wins("Alpha", "Beta", 30, 10, 2, 1), min_team_games=3)
    # Only 2 games each -> not enough to model.
    assert model.p_home_win("x", "Alpha", "Beta") is None


def test_model_favors_the_stronger_team():
    results = _wins("Alpha", "Beta", 30, 10, 5, 1)  # Alpha dominates Beta 5x
    model = build_team_model(results, min_team_games=3)
    p = model.p_home_win("x", "Alpha", "Beta")
    assert p is not None and p > 0.6                 # Alpha clearly favored
    # Expected margin points the same way and is positive (home advantage too).
    assert model.expected_margin("x", "Alpha", "Beta") > 0


def test_model_expected_total_tracks_scoring():
    # Two high-scoring teams -> a high projected total.
    hi = _wins("Hi", "Filler", 130, 120, 4, 1) + _wins("Hi2", "Filler", 128, 122, 4, 2)
    model = build_team_model(hi, min_team_games=3)
    et = model.expected_total("x", "Hi", "Hi2")
    assert et is not None and et > 200


# --------------------------------------------------------------- calibration ---
def _rec(market, selection, point, fair_prob):
    return {"sport_key": "x", "home_team": "Aa Bb", "away_team": "Cc Dd",
            "market": market, "selection": selection, "point": point,
            "fair_prob": fair_prob}


def test_calibration_settles_and_buckets():
    results = [{"game_id": "1", "sport_key": "x", "home": "Aa Bb", "away": "Cc Dd",
                "home_score": 5, "away_score": 3, "completed_at": "2026-01-01"}]
    recs = [
        _rec("h2h", "Aa Bb", None, 0.70),   # home won -> hit
        _rec("totals", "Over", 7.0, 0.55),  # total 8 > 7 -> hit
        _rec("totals", "Under", 7.0, 0.52), # total 8 -> miss
    ]
    cal = compute_calibration(recs, results)
    assert cal["graded"] == 3
    assert cal["brier"] is not None
    assert cal["bins"]  # at least one populated bucket
