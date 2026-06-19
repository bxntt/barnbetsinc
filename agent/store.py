"""Persistence of odds snapshots and recommendations.

Everything is committed JSON in `data/history/` (free to store in the repo),
which powers two longer-horizon features:
  * line movement  -> compare the target book's current price to its earliest
  * closing line value (CLV) -> compare recommendations to where the line closed

Keys identify a specific bettable outcome across runs:
    "<game_id>|<market>|<selection>|<point>"
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .config import ROOT
from .models import BestBet, Game

HISTORY_DIR = ROOT / "data" / "history"
RECS_LOG = HISTORY_DIR / "recommendations.jsonl"
RESULTS_LOG = HISTORY_DIR / "results.jsonl"


def bet_key(game_id: str, market: str, selection: str, point: Optional[float]) -> str:
    pt = "" if point is None else f"{round(point, 1)}"
    return f"{game_id}|{market}|{selection}|{pt}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_snapshot(
    games: List[Game], target_book: str, ref_probs: Optional[Dict[str, float]] = None
) -> Path:
    """Record the target book's current prices for every market/outcome, plus the
    sharp/consensus no-vig fair prob per key (`ref_probs`) so CLV and steam can be
    measured against the sharp market, not the target book's vig-inclusive price."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    target_prices: Dict[str, int] = {}
    commence_times: Dict[str, str] = {}

    for g in games:
        commence_times[g.id] = g.commence_time
        for market, books in g.markets.items():
            for bo in books:
                if bo.book != target_book:
                    continue
                for o in bo.outcomes:
                    target_prices[bet_key(g.id, market, o.name, o.point)] = o.price_american

    snapshot = {
        "generated_at": _now(),
        "target_book": target_book,
        "target_prices": target_prices,
        "ref_probs": ref_probs or {},
        "commence_times": commence_times,
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = HISTORY_DIR / f"odds-{ts}.json"
    path.write_text(json.dumps(snapshot, indent=2))
    return path


def load_snapshots() -> List[dict]:
    """All odds snapshots, oldest first."""
    if not HISTORY_DIR.exists():
        return []
    snaps = []
    for p in sorted(HISTORY_DIR.glob("odds-*.json")):
        try:
            snaps.append(json.loads(p.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return snaps


def log_recommendations(bets: List[BestBet]) -> None:
    """Append published recommendations for later CLV grading."""
    if not bets:
        return
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    with RECS_LOG.open("a") as fh:
        for b in bets:
            fh.write(json.dumps({
                "logged_at": _now(),
                "key": bet_key(b.game_id, b.market, b.selection, b.point),
                "game_id": b.game_id,
                "sport_key": b.sport_key,
                "commence_time": b.commence_time,
                "home_team": b.home_team,
                "away_team": b.away_team,
                "market": b.market,
                "selection": b.selection,
                "point": b.point,
                "price_american": b.price_american,
                "fair_prob": b.fair_prob,
                "ev_pct": b.ev_pct,
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
    """Append newly-final game results (deduped by game_id) for grading/calibration."""
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
