"""Lightweight Elo model — an independent cross-check, not a source of truth.

Built from the same free results history used for calibration. The sharp closing
line already explains most outcome variance, so Elo is used only to *flag*
moneyline bets where an independent model strongly disagrees with the market —
a prompt to look closer, never an override. It stays silent until enough games
have accumulated (cold start) and for teams it has barely seen.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from .results import nickname

_BASE = 1500.0
_K = 20.0
_HFA = 50.0          # home edge, in Elo points
_MIN_TEAM_GAMES = 3  # don't trust a rating built from fewer than this many games


def _build(results: List[dict]) -> Tuple[Dict[Tuple[str, str], float], Dict[Tuple[str, str], int]]:
    ratings: Dict[Tuple[str, str], float] = {}
    games: Dict[Tuple[str, str], int] = {}
    for r in sorted(results, key=lambda x: x.get("completed_at") or ""):
        sk = r.get("sport_key", "")
        hk, ak = (sk, nickname(r.get("home"))), (sk, nickname(r.get("away")))
        hs, as_ = r.get("home_score"), r.get("away_score")
        if not hk[1] or not ak[1] or hs is None or as_ is None:
            continue
        rh, ra = ratings.get(hk, _BASE), ratings.get(ak, _BASE)
        exp_h = 1.0 / (1.0 + 10 ** (-((rh + _HFA) - ra) / 400.0))
        act_h = 1.0 if hs > as_ else 0.0 if hs < as_ else 0.5
        ratings[hk] = rh + _K * (act_h - exp_h)
        ratings[ak] = ra - _K * (act_h - exp_h)
        games[hk] = games.get(hk, 0) + 1
        games[ak] = games.get(ak, 0) + 1
    return ratings, games


def annotate(bets, results: List[dict], min_games: int, disagree: float) -> None:
    """Attach model_prob / model_flag to moneyline bets where Elo is informative."""
    if len(results) < min_games:
        return
    ratings, games = _build(results)
    for b in bets:
        if b.market != "h2h":
            continue
        hk = (b.sport_key, nickname(b.home_team))
        ak = (b.sport_key, nickname(b.away_team))
        if games.get(hk, 0) < _MIN_TEAM_GAMES or games.get(ak, 0) < _MIN_TEAM_GAMES:
            continue
        rh, ra = ratings.get(hk, _BASE), ratings.get(ak, _BASE)
        exp_h = 1.0 / (1.0 + 10 ** (-((rh + _HFA) - ra) / 400.0))
        nsel = nickname(b.selection)
        if nsel == hk[1]:
            model_prob = exp_h
        elif nsel == ak[1]:
            model_prob = 1.0 - exp_h
        else:
            continue
        b.model_prob = model_prob
        b.model_flag = "disagree" if abs(model_prob - b.fair_prob) > disagree else "agree"
