"""Unit tests for the win-loss track record (agent/record.py).

Exercises the pure aggregator over hand-built prediction/result logs so the four
bet categories, the US + World Cup grading, pushes, and the launch cutoff are all
covered offline.
"""
from __future__ import annotations

from agent.record import CATEGORIES, build_record

# Any kickoff after the tracker's RECORD_START so fixtures land inside the window.
AFTER = "2026-06-22T00:00:00Z"
BEFORE = "2026-06-11T19:00:00Z"   # a pre-launch group game -> must be ignored


def _cat(payload, key):
    return next(c for c in payload["categories"] if c["key"] == key)


def test_categories_cover_every_market_once():
    markets = [m for _, _, ms in CATEGORIES for m in ms]
    # No market feeds two categories, and we map the full US + WC market set.
    assert len(markets) == len(set(markets))
    assert set(markets) == {"h2h", "result", "spreads", "handicap", "totals", "total", "btts"}


def test_empty_logs_give_blank_record():
    payload = build_record([], [], [], [])
    assert payload["overall"] == {"wins": 0, "losses": 0, "pushes": 0, "win_pct": None}
    assert {c["key"] for c in payload["categories"]} == {"moneyline", "spread", "total", "btts"}
    assert all(c["win_pct"] is None for c in payload["categories"])


def test_us_moneyline_win_and_loss():
    recs = [
        {"key": "g1|h2h|Lakers|", "game_id": "g1", "sport_key": "basketball_nba",
         "commence_time": AFTER, "home_team": "Boston Celtics", "away_team": "Los Angeles Lakers",
         "market": "h2h", "selection": "Los Angeles Lakers", "point": None, "fair_prob": 0.55},
        {"key": "g2|h2h|Heat|", "game_id": "g2", "sport_key": "basketball_nba",
         "commence_time": AFTER, "home_team": "Miami Heat", "away_team": "Golden State Warriors",
         "market": "h2h", "selection": "Miami Heat", "point": None, "fair_prob": 0.52},
    ]
    results = [
        {"game_id": "g1", "sport_key": "basketball_nba", "home": "Boston Celtics",
         "away": "Los Angeles Lakers", "home_score": 100, "away_score": 110},  # Lakers win
        {"game_id": "g2", "sport_key": "basketball_nba", "home": "Miami Heat",
         "away": "Golden State Warriors", "home_score": 95, "away_score": 120},  # Heat lose
    ]
    ml = _cat(build_record([], [], recs, results), "moneyline")
    assert (ml["wins"], ml["losses"], ml["pushes"]) == (1, 1, 0)
    assert ml["win_pct"] == 50.0


def test_us_total_push_excluded_from_win_pct():
    recs = [
        {"key": "g3|totals|Over|8.5", "game_id": "g3", "sport_key": "baseball_mlb",
         "commence_time": AFTER, "home_team": "Boston Red Sox", "away_team": "New York Yankees",
         "market": "totals", "selection": "Over", "point": 8.0, "fair_prob": 0.5},
    ]
    results = [
        {"game_id": "g3", "sport_key": "baseball_mlb", "home": "Boston Red Sox",
         "away": "New York Yankees", "home_score": 4, "away_score": 4},  # total 8 == line -> push
    ]
    tot = _cat(build_record([], [], recs, results), "total")
    assert (tot["wins"], tot["losses"], tot["pushes"]) == (0, 0, 1)
    assert tot["win_pct"] is None


def test_worldcup_result_and_btts_grade_into_categories():
    wc_preds = [
        {"key": "m1|result", "match_id": "m1", "commence_time": AFTER,
         "home": "France", "away": "Iraq",
         "market": "result", "pick": "France win", "prob": 0.9,
         "outcomes": [["France win", 0.9], ["Draw", 0.07], ["Iraq win", 0.03]]},
        {"key": "m1|btts", "match_id": "m1", "commence_time": AFTER,
         "home": "France", "away": "Iraq",
         "market": "btts", "pick": "BTTS: No", "prob": 0.62,
         "outcomes": [["BTTS: No", 0.62], ["BTTS: Yes", 0.38]]},
    ]
    wc_results = [
        {"date": "2026-06-22", "home": "France", "away": "Iraq",
         "home_score": 3, "away_score": 0},
    ]
    payload = build_record(wc_preds, wc_results, [], [])
    # France won -> result/moneyline win; Iraq scored 0 -> "BTTS: No" hits.
    assert _cat(payload, "moneyline")["wins"] == 1
    assert _cat(payload, "btts")["wins"] == 1
    assert payload["overall"]["wins"] == 2


def test_pre_launch_games_are_excluded():
    # Same winning pick, but kicked off before RECORD_START -> not in the record.
    wc_preds = [
        {"key": "m9|result", "match_id": "m9", "commence_time": BEFORE,
         "home": "France", "away": "Iraq",
         "market": "result", "pick": "France win", "prob": 0.9,
         "outcomes": [["France win", 0.9], ["Draw", 0.07], ["Iraq win", 0.03]]},
    ]
    wc_results = [
        {"date": "2026-06-11", "home": "France", "away": "Iraq",
         "home_score": 3, "away_score": 0},
    ]
    payload = build_record(wc_preds, wc_results, [], [])
    assert payload["overall"] == {"wins": 0, "losses": 0, "pushes": 0, "win_pct": None}
    assert payload["since"] == "2026-06-20"


def test_unsettled_games_are_not_counted():
    recs = [
        {"key": "g9|h2h|Lakers|", "game_id": "g9", "sport_key": "basketball_nba",
         "commence_time": AFTER, "home_team": "Boston Celtics", "away_team": "Los Angeles Lakers",
         "market": "h2h", "selection": "Los Angeles Lakers", "point": None, "fair_prob": 0.55},
    ]
    payload = build_record([], [], recs, [])  # no results yet
    assert payload["overall"]["wins"] == 0 and payload["overall"]["losses"] == 0


def test_duplicate_us_logs_counted_once():
    rec = {"key": "g1|h2h|Lakers|", "game_id": "g1", "sport_key": "basketball_nba",
           "commence_time": AFTER, "home_team": "Boston Celtics", "away_team": "Los Angeles Lakers",
           "market": "h2h", "selection": "Los Angeles Lakers", "point": None, "fair_prob": 0.55}
    results = [
        {"game_id": "g1", "sport_key": "basketball_nba", "home": "Boston Celtics",
         "away": "Los Angeles Lakers", "home_score": 100, "away_score": 110},
    ]
    # Same pick logged across three ticks must count as one win.
    ml = _cat(build_record([], [], [rec, rec, rec], results), "moneyline")
    assert (ml["wins"], ml["losses"]) == (1, 0)
