"""Persistence of predictions and final results, for the calibration loop.

Everything is committed JSON in `data/history/`. Predictions are logged with the
probability we assigned; once the games settle, `engine/calibration.py` compares
predicted vs realized hit rate (the honest check on the model).

Keys identify a specific predicted outcome across runs:
    "<game_id>|<market>|<selection>|<point>"
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .config import ROOT
from .models import Prediction

HISTORY_DIR = ROOT / "data" / "history"
RECS_LOG = HISTORY_DIR / "recommendations.jsonl"
RESULTS_LOG = HISTORY_DIR / "results.jsonl"


def bet_key(game_id: str, market: str, selection: str, point: Optional[float]) -> str:
    pt = "" if point is None else f"{round(point, 1)}"
    return f"{game_id}|{market}|{selection}|{pt}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_recommendations(preds: List[Prediction]) -> None:
    """Append published predictions for later calibration grading."""
    if not preds:
        return
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    with RECS_LOG.open("a") as fh:
        for p in preds:
            fh.write(json.dumps({
                "logged_at": _now(),
                "key": bet_key(p.game_id, p.market, p.selection, p.point),
                "game_id": p.game_id,
                "sport_key": p.sport_key,
                "commence_time": p.commence_time,
                "home_team": p.home_team,
                "away_team": p.away_team,
                "market": p.market,
                "selection": p.selection,
                "point": p.point,
                "fair_prob": p.prob,          # graded by calibration as our estimate
            }) + "\n")


def _read_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def load_recommendations() -> List[dict]:
    return _read_jsonl(RECS_LOG)


def save_results(results: List[dict]) -> None:
    """Append newly-final game results (deduped by game_id) for calibration."""
    if not results:
        return
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    seen = {r.get("game_id") for r in _read_jsonl(RESULTS_LOG)}
    fresh = [r for r in results if r.get("game_id") and r["game_id"] not in seen]
    if not fresh:
        return
    with RESULTS_LOG.open("a") as fh:
        for r in fresh:
            fh.write(json.dumps(r) + "\n")


def load_results() -> List[dict]:
    return _read_jsonl(RESULTS_LOG)
