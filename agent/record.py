"""Win-loss track record — the simple story a bettor wants up front.

Calibration (engine/calibration.py + worldcup/calibration.py) answers "are our
*probabilities* honest?"; this answers the blunter question "how often did the
published pick actually hit?". Every settled call is a win or a loss (pushes set
aside), bucketed into the four bet categories the site speaks in:

    Moneyline   <- h2h (US) + result (World Cup)
    Spread      <- spreads (US) + handicap (World Cup)
    Total       <- totals (US) + total (World Cup)
    BTTS        <- btts (World Cup)

It is pure functions over the very same prediction/result logs the calibration
loops already keep, so it costs nothing extra to compute and is trivially
testable offline. Reuses the existing settlement helpers rather than restating
the grading rules, so a win here always agrees with calibration. Writes
site/record.json, read by the record tracker at the top of the picks page.

    python -m agent.record
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Dict, Iterator, List, Optional, Tuple

from .config import ROOT

SITE_DATA = ROOT / "site" / "record.json"

# The tracker starts here: only picks for games kicking off on/after this moment
# count, so the record begins at a clean 0-0 at launch and grows as new games
# settle (rather than retroactively crediting games played before it existed).
RECORD_START = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)

# The four categories, and the raw provider markets that feed each one.
CATEGORIES: List[Tuple[str, str, Tuple[str, ...]]] = [
    ("moneyline", "Moneyline", ("h2h", "result")),
    ("spread", "Spread", ("spreads", "handicap")),
    ("total", "Total", ("totals", "total")),
    ("btts", "Both Teams to Score", ("btts",)),
]
_MARKET_CATEGORY = {m: key for key, _, markets in CATEGORIES for m in markets}


# ----------------------------------------------------------------- helpers ---
def _dedupe(recs: List[dict]) -> List[dict]:
    """One record per pick, keeping the freshest log line (later lines win).

    The World Cup log is already de-duped on load, but the US log is append-only
    across ticks, so the same pick can appear many times — counting each would
    inflate the record. Both logs carry a stable per-pick ``key``.
    """
    by_key: Dict[str, dict] = {}
    for r in recs:
        by_key[r.get("key", "")] = r
    return list(by_key.values())


def _in_window(rec: dict) -> bool:
    """True iff the pick's game kicks off at/after the tracker's start.

    Excludes anything without a parseable kickoff so a pick we can't place in
    time never silently inflates the record.
    """
    raw = rec.get("commence_time", "") or ""
    if not raw:
        return False
    try:
        t = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t >= RECORD_START


def _grade_us(recs: List[dict], results: List[dict]) -> Iterator[Tuple[str, str]]:
    """Yield (category, "win"|"loss"|"push") for every *settled* US-sports pick."""
    from .engine.calibration import _index, _match, _settle

    idx = _index(results)
    for rec in _dedupe(recs):
        cat = _MARKET_CATEGORY.get(rec.get("market"))
        if cat is None or not _in_window(rec):
            continue
        res = _match(rec, idx)
        if res is None:
            continue                      # game not final yet -> not in the record
        won = _settle(rec, res)
        yield cat, ("push" if won is None else ("win" if won else "loss"))


def _wc_hit(rec: dict, hg: int, ag: int) -> Optional[bool]:
    """Did the logged World Cup pick hit? None == push / ungradable."""
    from .worldcup import calibration as wc

    if rec.get("market") == "result":
        outcome = wc._result_outcome(hg, ag)     # 0 home, 1 draw, 2 away
        pick = rec.get("pick", "")
        if pick == f"{rec.get('home')} win":
            return outcome == 0
        if pick == f"{rec.get('away')} win":
            return outcome == 2
        if pick == "Draw":
            return outcome == 1
        return None
    return wc._binary_hit(rec, hg, ag)


def _grade_wc(preds: List[dict], results: List[dict]) -> Iterator[Tuple[str, str]]:
    """Yield (category, "win"|"loss"|"push") for every *settled* World Cup pick."""
    from .worldcup import calibration as wc
    from .worldcup.fixtures import canonical_team

    res_index = {}
    for r in results:
        rh, ra = canonical_team(r.get("home", "")), canonical_team(r.get("away", ""))
        if rh and ra:
            res_index[frozenset((rh, ra))] = r

    for rec in _dedupe(preds):
        market = rec.get("market")
        cat = _MARKET_CATEGORY.get(market)
        if cat is None or not _in_window(rec):
            continue
        rh, ra = canonical_team(rec.get("home", "")), canonical_team(rec.get("away", ""))
        if not (rh and ra):
            continue
        res = res_index.get(frozenset((rh, ra)))
        if res is None:
            continue                      # game not final yet -> not in the record
        oriented = wc._oriented_score(rec, res)
        if oriented is None:
            continue
        won = _wc_hit(rec, oriented[0], oriented[1])
        if won is None:
            if market in wc._BINARY_MARKETS:
                yield cat, "push"         # e.g. total landed exactly on the line
            continue                      # result pick we couldn't read -> skip
        yield cat, ("win" if won else "loss")


# ----------------------------------------------------------------- record ---
def build_record(
    wc_preds: List[dict],
    wc_results: List[dict],
    us_recs: List[dict],
    us_results: List[dict],
) -> dict:
    """Aggregate settled picks into a per-category and overall win-loss record.

    Pure function over the four logs so it can be exercised offline. ``win_pct``
    excludes pushes; it is None until a category has at least one decided pick.
    """
    tally = {key: {"wins": 0, "losses": 0, "pushes": 0} for key, _, _ in CATEGORIES}
    for cat, outcome in (*_grade_us(us_recs, us_results), *_grade_wc(wc_preds, wc_results)):
        bucket = tally[cat]
        bucket[{"win": "wins", "loss": "losses", "push": "pushes"}[outcome]] += 1

    categories = []
    overall = {"wins": 0, "losses": 0, "pushes": 0}
    for key, label, _ in CATEGORIES:
        t = tally[key]
        decided = t["wins"] + t["losses"]
        categories.append({
            "key": key,
            "label": label,
            "wins": t["wins"],
            "losses": t["losses"],
            "pushes": t["pushes"],
            "win_pct": round(100.0 * t["wins"] / decided, 1) if decided else None,
        })
        for k in ("wins", "losses", "pushes"):
            overall[k] += t[k]

    decided = overall["wins"] + overall["losses"]
    overall["win_pct"] = round(100.0 * overall["wins"] / decided, 1) if decided else None

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since": RECORD_START.date().isoformat(),
        "overall": overall,
        "categories": categories,
        "note": ("Win-loss record of the published pick in each game, settled "
                 "against final scores. Pushes are excluded from win %."),
    }


def _empty_record(error: str = "") -> dict:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since": RECORD_START.date().isoformat(),
        "overall": {"wins": 0, "losses": 0, "pushes": 0, "win_pct": None},
        "categories": [
            {"key": k, "label": l, "wins": 0, "losses": 0, "pushes": 0, "win_pct": None}
            for k, l, _ in CATEGORIES
        ],
        "note": "Track record builds as games settle.",
    }
    if error:
        payload["error"] = error
    return payload


def run() -> dict:
    """Load every log, build the record, and write the site artifact. Never raises."""
    try:
        from .store import load_recommendations, load_results as load_us_results
        from .worldcup.calibration import (
            load_predictions as load_wc_preds,
            load_results as load_wc_results,
        )
        payload = build_record(
            load_wc_preds(), load_wc_results(),
            load_recommendations(), load_us_results(),
        )
    except Exception as exc:                          # pragma: no cover - safety net
        payload = _empty_record(str(exc))
    SITE_DATA.parent.mkdir(parents=True, exist_ok=True)
    SITE_DATA.write_text(json.dumps(payload, indent=2))
    return payload


def main() -> int:
    payload = run()
    o = payload["overall"]
    print(f"[record] overall {o['wins']}-{o['losses']} "
          f"(win% {o.get('win_pct')}) across {len(payload['categories'])} "
          f"categories -> site/record.json")
    for c in payload["categories"]:
        print(f"[record]   {c['label']}: {c['wins']}-{c['losses']} "
              f"(push {c['pushes']}, win% {c['win_pct']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
