"""Tests for the upgraded value engine: de-vig methods, line interpolation,
fractional Kelly, calibration, and the Elo cross-check."""
from __future__ import annotations

import math

from agent.engine.calibration import compute_calibration
from agent.engine.devig import devig_probs
from agent.engine.elo import annotate as elo_annotate
from agent.engine.interpolate import interp_fair
from agent.engine.kelly import kelly_fraction, kelly_stake
from agent.models import BestBet


# --------------------------------------------------------------- de-vig math ---
def test_all_methods_normalize_and_symmetric():
    raw = [1 / 1.909, 1 / 1.909]  # -110 / -110
    for method in ("multiplicative", "power", "shin"):
        fair = devig_probs(raw, method)
        assert math.isclose(sum(fair), 1.0, rel_tol=1e-9)
        assert math.isclose(fair[0], 0.5, rel_tol=1e-6)


def test_power_corrects_favorite_longshot_bias():
    # Heavy favorite (-400) vs longshot (+300). Power should pull the longshot's
    # fair prob DOWN (and the favorite's UP) relative to multiplicative.
    raw = [1 / 1.25, 1 / 4.0]  # fav decimal 1.25, dog decimal 4.0
    mult = devig_probs(raw, "multiplicative")
    power = devig_probs(raw, "power")
    assert power[0] > mult[0]      # favorite fair prob higher under power
    assert power[1] < mult[1]      # longshot fair prob lower under power


# --------------------------------------------------------------------- kelly ---
def test_kelly_fraction_and_stake():
    # 55% at even money (decimal 2.0): full-Kelly = (2*0.55-1)/(2-1) = 0.10.
    assert math.isclose(kelly_fraction(0.55, 2.0), 0.10, rel_tol=1e-9)
    # Quarter-Kelly under the 5% cap -> 0.025.
    assert math.isclose(kelly_stake(0.55, 2.0, 0.25, 0.05), 0.025, rel_tol=1e-9)


def test_kelly_zero_when_not_positive_ev():
    assert kelly_fraction(0.45, 2.0) == 0.0
    assert kelly_stake(0.45, 2.0) == 0.0


def test_kelly_respects_cap():
    assert kelly_stake(0.95, 5.0, 1.0, 0.05) == 0.05


# --------------------------------------------------------------- interpolate ---
def test_interp_shorter_spread_is_more_likely():
    # Reference: favorite covers -6.5 with fair 0.50. At -3.5 it should be higher.
    res = interp_fair("spreads", "americanfootball_nfl", "Home", -6.5, 0.50, -3.5, 3.5)
    assert res is not None
    fair, reach = res
    assert fair > 0.5 and reach == 3.0


def test_interp_respects_max_reach():
    assert interp_fair("spreads", "basketball_nba", "Home", -3.0, 0.5, 0.5, 2.0) is None


def test_interp_totals_over_drops_when_line_rises():
    res = interp_fair("totals", "basketball_nba", "Over", 220.0, 0.50, 224.0, 6.0)
    assert res is not None and res[0] < 0.5


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


# ----------------------------------------------------------------------- elo ---
def _ml_bet(selection):
    return BestBet("g", "x", "X", "2099-01-01T00:00:00+00:00", "Alpha City",
                   "Beta Town", "h2h", selection, None, "hardrockbet",
                   100, 0.5, 1.0, 1.0, "consensus", 0.02)


def test_elo_flags_disagreement_with_market():
    # Alpha thrashes Beta six times; market priced as a coin flip on Beta.
    results = [{"game_id": str(i), "sport_key": "x", "home": "Alpha City",
                "away": "Beta Town", "home_score": 30, "away_score": 10,
                "completed_at": f"2026-01-0{i}"} for i in range(1, 7)]
    bet = _ml_bet("Beta Town")
    elo_annotate([bet], results, min_games=5, disagree=0.10)
    assert bet.model_prob is not None and bet.model_prob < 0.4
    assert bet.model_flag == "disagree"


def test_elo_silent_before_min_games():
    bet = _ml_bet("Beta Town")
    elo_annotate([bet], [], min_games=30, disagree=0.10)
    assert bet.model_prob is None and bet.model_flag is None
