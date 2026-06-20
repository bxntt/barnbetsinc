"""World Cup grading loop — the honest check on the prediction engine.

US sports are graded by engine/calibration.py; the World Cup was graded *nowhere*,
so the injury/momentum/venue weights in factors.py and the Dixon-Coles rho were
tuned by judgement, not evidence. This module closes that loop:

  1. log_predictions  — append every published call to data/history (the model's
                        stated probabilities, with the full outcome distribution).
  2. espn_results     — best-effort final scores from ESPN's free soccer scoreboard
                        (same endpoint injuries.py already uses; no key, fail-safe).
  3. grade            — settle logged calls against finals with the RIGHT metric per
                        market: the 3-way result by RPS (ordinal-aware) and log loss,
                        the binary markets (total / btts / handicap) by Brier plus a
                        reliability curve (predicted vs realized by probability bin).

Everything is closed-form pure-Python and free: predictions cost nothing to log,
finals come from a no-cost endpoint, and `grade` is a pure function over the two
logs so it is trivially testable offline. Brier/RPS/log loss all read "lower is
better". This is what tells us whether the engine's stated chances are real.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..config import ROOT
from .fixtures import canonical_team
from .models import Prediction

HISTORY_DIR = ROOT / "data" / "history"
PRED_LOG = HISTORY_DIR / "worldcup_predictions.jsonl"
RESULTS_LOG = HISTORY_DIR / "worldcup_results.jsonl"
SITE_DATA = ROOT / "site" / "worldcup_calibration.json"

# Predicted-probability buckets for the binary-market reliability curve. The pick
# is always the favourite side, so probabilities live in [0.5, 1].
_BINS: List[Tuple[float, float]] = [
    (0.50, 0.55), (0.55, 0.60), (0.60, 0.65),
    (0.65, 0.70), (0.70, 0.80), (0.80, 1.01),
]
_EPS = 1e-15  # clamp for log loss so a 0%/100% call can't score infinity
_BINARY_MARKETS = ("total", "btts", "handicap")


# --------------------------------------------------------------- persistence ---
def _key(p: Prediction) -> str:
    return f"{p.match_id}|{p.market}"


def log_predictions(preds: List[Prediction]) -> None:
    """Append published calls for later grading (one line per market call).

    Append-only for a clean audit trail; `load_predictions` de-dupes by key so a
    game polled across many ticks still counts once (its latest pre-kickoff call).
    """
    if not preds:
        return
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    with PRED_LOG.open("a") as fh:
        for p in preds:
            fh.write(json.dumps({
                "logged_at": now,
                "key": _key(p),
                "match_id": p.match_id,
                "group": p.group,
                "commence_time": p.commence_time,
                "home": p.home,
                "away": p.away,
                "market": p.market,
                "pick": p.pick,
                "prob": round(p.prob, 6),
                "outcomes": [[lbl, round(pr, 6)] for lbl, pr in p.outcomes],
            }) + "\n")


def _read_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def load_predictions() -> List[dict]:
    """Logged calls, de-duped by (match, market) keeping the latest logged one."""
    by_key: Dict[str, dict] = {}
    for rec in _read_jsonl(PRED_LOG):
        by_key[rec.get("key", "")] = rec      # later lines win
    return list(by_key.values())


def save_results(results: List[dict]) -> None:
    """Append newly-final scores, de-duped by match key (canonical pair + date)."""
    if not results:
        return
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    seen = {_result_key(r) for r in _read_jsonl(RESULTS_LOG)}
    fresh = [r for r in results if _result_key(r) not in seen]
    if not fresh:
        return
    with RESULTS_LOG.open("a") as fh:
        for r in fresh:
            fh.write(json.dumps(r) + "\n")


def load_results() -> List[dict]:
    return _read_jsonl(RESULTS_LOG)


def _result_key(r: dict) -> str:
    pair = tuple(sorted((canonical_team(r.get("home", "")) or r.get("home", ""),
                         canonical_team(r.get("away", "")) or r.get("away", ""))))
    return f"{pair[0]}|{pair[1]}|{r.get('date', '')[:10]}"


# ----------------------------------------------------------- ESPN finals (free) ---
_ESPN_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"
)
_ESPN_TIMEOUT = 4
WORLD_CUP_START = "20260611"   # first matchday of the 2026 finals (ESPN date fmt)


def espn_results(league: str = "fifa.world", dates: Optional[str] = None) -> List[dict]:
    """Completed World Cup matches from ESPN's free scoreboard. Fail-safe -> [].

    Returns {date, home, away, home_score, away_score} per finished game, team
    names left raw (graded via canonical_team). `dates` is an optional ESPN date
    filter ("YYYYMMDD" or "YYYYMMDD-YYYYMMDD"); without it ESPN returns only the
    current day's card. Any network/shape error yields [].
    """
    try:
        import requests

        url = _ESPN_SCOREBOARD.format(league=league)
        params = {"dates": dates} if dates else None
        resp = requests.get(url, params=params, timeout=_ESPN_TIMEOUT)
        resp.raise_for_status()
        events = resp.json().get("events", []) or []
    except Exception:
        return []

    out: List[dict] = []
    for ev in events:
        for comp in ev.get("competitions", []) or []:
            status = ((comp.get("status") or {}).get("type") or {})
            if not status.get("completed"):
                continue
            home = away = None
            hs = as_ = None
            for c in comp.get("competitors", []) or []:
                name = (c.get("team") or {}).get("displayName", "")
                score = c.get("score")
                score = int(score) if score not in (None, "") else None
                if c.get("homeAway") == "home":
                    home, hs = name, score
                elif c.get("homeAway") == "away":
                    away, as_ = name, score
            if home and away and hs is not None and as_ is not None:
                out.append({"date": ev.get("date", comp.get("date", "")),
                            "home": home, "away": away,
                            "home_score": hs, "away_score": as_})
    return out


def espn_results_range(league: str = "fifa.world") -> List[dict]:
    """All completed finals from the tournament's start through today.

    The plain scoreboard only returns the current day, so finals from earlier
    matchdays would never be captured. Querying the full date range backfills the
    results log in one free request, so the Elo loop and grading see every game
    played so far (save_results de-dupes, so re-querying the range is safe).
    """
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    return espn_results(league, dates=f"{WORLD_CUP_START}-{today}")


# ----------------------------------------------------------------- metrics ---
def rps(probs: List[float], outcome_index: int) -> float:
    """Ranked Probability Score for ordered categories (lower is better).

    `probs` are ordered [home win, draw, away win]; `outcome_index` is which
    actually happened. RPS penalises by *distance* on the ordinal scale, so calling
    a home win that lands on a draw is scored gentler than one landing on an away
    win — the right shape for a 3-way result, unlike Brier.
    """
    cum_p = 0.0
    cum_e = 0.0
    total = 0.0
    for i in range(len(probs) - 1):       # r-1 cumulative terms
        cum_p += probs[i]
        cum_e += 1.0 if i == outcome_index else 0.0
        total += (cum_p - cum_e) ** 2
    return total / (len(probs) - 1)


def log_loss(prob_of_outcome: float) -> float:
    """Ignorance / log loss for the probability placed on what actually happened."""
    return -math.log(min(1.0 - _EPS, max(_EPS, prob_of_outcome)))


# ------------------------------------------------------------- settlement ---
def _oriented_score(rec: dict, res: dict) -> Optional[Tuple[int, int]]:
    """(home_goals, away_goals) from `res`, oriented to `rec`'s home/away, or None."""
    rh, ra = canonical_team(rec.get("home", "")), canonical_team(rec.get("away", ""))
    sh, sa = canonical_team(res.get("home", "")), canonical_team(res.get("away", ""))
    if not (rh and ra and sh and sa):
        return None
    if {rh, ra} != {sh, sa}:
        return None
    if rh == sh:
        return res["home_score"], res["away_score"]
    return res["away_score"], res["home_score"]   # feed listed them the other way


def _result_outcome(hg: int, ag: int) -> int:
    """Index into [home win, draw, away win]."""
    return 0 if hg > ag else (1 if hg == ag else 2)


def _ordered_result_probs(rec: dict) -> Optional[List[float]]:
    """Pull [P(home win), P(draw), P(away win)] from a logged result call."""
    by_label = {lbl: pr for lbl, pr in rec.get("outcomes", [])}
    ph = by_label.get(f"{rec.get('home')} win")
    pa = by_label.get(f"{rec.get('away')} win")
    pd = by_label.get("Draw")
    if ph is None or pd is None or pa is None:
        return None
    return [ph, pd, pa]


def _binary_hit(rec: dict, hg: int, ag: int) -> Optional[bool]:
    """Did the logged pick (total/btts/handicap) hit? None if it can't be graded."""
    market, pick = rec.get("market"), rec.get("pick", "")
    if market == "total":
        line = _parse_line(pick)
        if line is None:
            return None
        total = hg + ag
        if total == line:                 # half-goal lines never push, but be safe
            return None
        over = pick.lower().startswith("over")
        return (total > line) if over else (total < line)
    if market == "btts":
        yes = (hg > 0 and ag > 0)
        return yes if "yes" in pick.lower() else (not yes)
    if market == "handicap":
        # pick is "<team> -1.5" (favourite covers) or "<team> +1.5" (dog +1.5).
        fav_covers = _favourite_covers(rec, hg, ag)
        if fav_covers is None:
            return None
        return fav_covers if "-1.5" in pick else (not fav_covers)
    return None


def _favourite_covers(rec: dict, hg: int, ag: int) -> Optional[bool]:
    """True iff the -1.5 favourite won by 2+. Identifies the fav from the outcomes."""
    fav = None
    for lbl, _ in rec.get("outcomes", []):
        if "-1.5" in lbl:
            fav = lbl.replace("-1.5", "").strip()
            break
    if fav is None:
        return None
    if canonical_team(fav) == canonical_team(rec.get("home", "")):
        margin = hg - ag
    elif canonical_team(fav) == canonical_team(rec.get("away", "")):
        margin = ag - hg
    else:
        return None
    return margin >= 2


def _parse_line(label: str) -> Optional[float]:
    for tok in label.replace(":", " ").split():
        try:
            return float(tok)
        except ValueError:
            continue
    return None


# --------------------------------------------------------------- grading ---
def grade(predictions: List[dict], results: List[dict]) -> dict:
    """Score logged calls against finals. Pure function over the two logs.

    Returns RPS + log loss for the result market, Brier + reliability bins for each
    binary market, and the counts behind them. Empty/ungradable inputs yield a
    well-formed "still accumulating" payload rather than an error.
    """
    res_index: Dict[frozenset, dict] = {}
    for r in results:
        rh, ra = canonical_team(r.get("home", "")), canonical_team(r.get("away", ""))
        if rh and ra:
            res_index[frozenset((rh, ra))] = r

    result_rps: List[float] = []
    result_ll: List[float] = []
    binary: Dict[str, List[Tuple[float, bool]]] = {m: [] for m in _BINARY_MARKETS}

    for rec in predictions:
        rh, ra = canonical_team(rec.get("home", "")), canonical_team(rec.get("away", ""))
        if not (rh and ra):
            continue
        res = res_index.get(frozenset((rh, ra)))
        if res is None:
            continue
        oriented = _oriented_score(rec, res)
        if oriented is None:
            continue
        hg, ag = oriented

        if rec.get("market") == "result":
            probs = _ordered_result_probs(rec)
            if probs is None:
                continue
            outcome = _result_outcome(hg, ag)
            result_rps.append(rps(probs, outcome))
            result_ll.append(log_loss(probs[outcome]))
        elif rec.get("market") in _BINARY_MARKETS:
            hit = _binary_hit(rec, hg, ag)
            if hit is None:
                continue
            binary[rec["market"]].append((float(rec.get("prob", 0.0)), hit))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "result": _result_summary(result_rps, result_ll),
        "binary": {m: _binary_summary(binary[m]) for m in _BINARY_MARKETS},
        "graded_total": len(result_rps) + sum(len(v) for v in binary.values()),
        "note": ("Calibration sharpens as group-stage results settle. RPS/log loss "
                 "and Brier all read lower-is-better."),
    }


def _result_summary(rps_vals: List[float], ll_vals: List[float]) -> dict:
    if not rps_vals:
        return {"n": 0, "rps": None, "log_loss": None}
    return {
        "n": len(rps_vals),
        "rps": round(sum(rps_vals) / len(rps_vals), 4),
        "log_loss": round(sum(ll_vals) / len(ll_vals), 4),
    }


def _binary_summary(graded: List[Tuple[float, bool]]) -> dict:
    if not graded:
        return {"n": 0, "brier": None, "bins": []}
    brier = sum((p - (1.0 if w else 0.0)) ** 2 for p, w in graded) / len(graded)
    bins = []
    for lo, hi in _BINS:
        sub = [(p, w) for p, w in graded if lo <= p < hi]
        if not sub:
            continue
        bins.append({
            "lo": lo, "hi": hi, "n": len(sub),
            "predicted_pct": round(100.0 * sum(p for p, _ in sub) / len(sub), 1),
            "actual_pct": round(100.0 * sum(1 for _, w in sub if w) / len(sub), 1),
        })
    return {"n": len(graded), "brier": round(brier, 4), "bins": bins}


def run(use_espn: bool = True) -> dict:
    """Pull finals, persist them, grade the full history, write the site artifact.

    Best-effort and never raises through to the caller's publish step: a grading
    hiccup must not stop predictions going out.
    """
    try:
        if use_espn:
            save_results(espn_results())
        payload = grade(load_predictions(), load_results())
        SITE_DATA.parent.mkdir(parents=True, exist_ok=True)
        SITE_DATA.write_text(json.dumps(payload, indent=2))
        return payload
    except Exception as exc:                       # pragma: no cover - safety net
        return {"generated_at": datetime.now(timezone.utc).isoformat(),
                "error": str(exc), "graded_total": 0}
