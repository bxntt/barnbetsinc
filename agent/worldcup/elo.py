"""Online Elo for the World Cup — strength ratings that correct themselves.

`ratings.py` holds a static, hand-set strength prior; its own docstring admits the
numbers were set by judgement, not evidence. This module closes that gap with the
free ESPN finals we already pull for calibration: after each settled match we nudge
both teams toward what actually happened, then persist the result so it becomes the
prior for the next tick. The engine therefore *learns from the tournament as it
plays out* — at zero API cost (no odds credits; finals come from the no-key ESPN
scoreboard).

Design choices that keep it honest and safe:

  * Expected score from the *model itself* — P(win) + ½·P(draw) via the same
    ratings→Poisson path the predictor uses — so the update needs no second,
    arbitrary Elo scale to reconcile with our goal model.
  * Zero-sum: the winner gains exactly what the loser sheds, so total Elo (and the
    overall scoring baseline) is conserved.
  * Margin-of-victory weighted with the standard World Football Elo curve, and the
    World Cup K of 60 — a 4-0 moves ratings more than a 1-0.
  * Idempotent: every result is keyed (canonical pair + date) and folded in at most
    once, so re-running a tick — or backfilling a date range — never double-counts.

The updated ratings feed `ratings.effective_rating`, which prefers them over the
static prior once a team has a settled result (and so drops the crude standings
form nudge for that team, avoiding double-counting the same games).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..config import ROOT
from . import factors, ratings
from .fixtures import canonical_team
from .poisson import outcome_probs

STATE_PATH = ROOT / "data" / "history" / "worldcup_elo.json"

K_WORLD_CUP = 60.0   # World Football Elo's K for World Cup finals matches


def _mov_multiplier(goal_diff: int) -> float:
    """World Football Elo margin-of-victory weight: bigger wins move ratings more."""
    g = abs(goal_diff)
    if g <= 1:
        return 1.0
    if g == 2:
        return 1.5
    return (11.0 + g) / 8.0


def _empty_state() -> dict:
    return {"updated_at": None, "ratings": {}, "applied": []}


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return _empty_state()
    try:
        data = json.loads(STATE_PATH.read_text())
        data.setdefault("ratings", {})
        data.setdefault("applied", [])
        return data
    except (json.JSONDecodeError, OSError):
        return _empty_state()


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE_PATH.write_text(json.dumps(state, indent=2))


# Process-cached so a tick's Elo update is visible to the predictions that follow
# it (the pipeline updates before it predicts). Reset for tests via `reset()`.
_STATE: Optional[dict] = None


def _state() -> dict:
    global _STATE
    if _STATE is None:
        _STATE = _load_state()
    return _STATE


def reset() -> None:
    """Drop the cached state (tests / a fresh process)."""
    global _STATE
    _STATE = None


def _result_key(home: str, away: str, date: str) -> Optional[str]:
    ch, ca = canonical_team(home), canonical_team(away)
    if not (ch and ca):
        return None
    a, b = sorted((ch, ca))
    return f"{a}|{b}|{(date or '')[:10]}"


def rating_for(name: str) -> Optional[float]:
    """Results-adjusted Elo for a team, or None if it has no settled match yet."""
    ratings_map = _state()["ratings"]
    canon = canonical_team(name)
    if canon and canon in ratings_map:
        return ratings_map[canon]
    return ratings_map.get(name)


def _expected_home(home: str, away: str, r_home: float, r_away: float) -> float:
    """Model expected score for the home side: P(win) + ½·P(draw).

    Uses the same ratings→Poisson mapping as the predictor (host-venue edge
    included) so the Elo update is consistent with how we model the game.
    """
    lh, la = ratings.lambdas(
        r_home, r_away, mean_goals=ratings.BASE_GOALS,
        home_advantage=factors.venue_edge(home, away))
    ph, pd, _pa = outcome_probs(lh, la)
    return ph + 0.5 * pd


def update_from_results(results: List[dict]) -> dict:
    """Fold any not-yet-applied finals into the Elo ratings and persist.

    `results` are calibration result rows ({date, home, away, home_score,
    away_score}). Applied in chronological order; each keyed so it counts once,
    seeding an unseen team from its static prior. Returns a small summary.
    """
    state = _state()
    ratings_map: Dict[str, float] = state["ratings"]
    applied = set(state["applied"])
    new = 0

    for res in sorted(results, key=lambda r: r.get("date", "")):
        key = _result_key(res.get("home", ""), res.get("away", ""), res.get("date", ""))
        if not key or key in applied:
            continue
        home, away = canonical_team(res.get("home", "")), canonical_team(res.get("away", ""))
        if not (home and away):
            continue
        try:
            hg, ag = int(res["home_score"]), int(res["away_score"])
        except (KeyError, TypeError, ValueError):
            continue

        r_home = ratings_map.get(home, ratings.base_rating(home))
        r_away = ratings_map.get(away, ratings.base_rating(away))
        s_home = 1.0 if hg > ag else (0.5 if hg == ag else 0.0)
        e_home = _expected_home(home, away, r_home, r_away)
        change = K_WORLD_CUP * _mov_multiplier(hg - ag) * (s_home - e_home)
        ratings_map[home] = round(r_home + change, 2)
        ratings_map[away] = round(r_away - change, 2)   # zero-sum: loser sheds it
        applied.add(key)
        new += 1

    if new:
        state["ratings"] = ratings_map
        state["applied"] = sorted(applied)
        _save_state(state)
    return {"applied": new, "rated": len(ratings_map)}
