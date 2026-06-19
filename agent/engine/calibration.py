"""Probability calibration — the empirical check on the whole pipeline.

Settle past recommendations against final scores, then bucket them by the fair
probability we assigned and compare predicted vs realized hit rate. A well-
calibrated engine has, e.g., ~60% of its "60% chance" picks actually win. The
Brier score summarizes overall calibration (lower is better). This is the honest
answer to "what are the real chances of hitting?" and it sharpens over time.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .results import nickname

# Fair-prob buckets (favorites side; longshots collapse into the lowest bin).
_BINS: List[Tuple[float, float]] = [
    (0.0, 0.40), (0.40, 0.50), (0.50, 0.55), (0.55, 0.60),
    (0.60, 0.65), (0.65, 0.75), (0.75, 1.01),
]


def _index(results: List[dict]) -> Dict[Tuple[str, str, str], dict]:
    idx = {}
    for r in results:
        idx[(r.get("sport_key", ""), nickname(r.get("home")), nickname(r.get("away")))] = r
    return idx


def _match(rec: dict, idx: Dict[Tuple[str, str, str], dict]) -> Optional[dict]:
    sk = rec.get("sport_key", "")
    nh, na = nickname(rec.get("home_team")), nickname(rec.get("away_team"))
    return idx.get((sk, nh, na)) or idx.get((sk, na, nh))


def _settle(rec: dict, res: dict) -> Optional[bool]:
    """True = bet won, False = lost, None = push / can't grade."""
    hs, as_ = res.get("home_score"), res.get("away_score")
    if hs is None or as_ is None:
        return None
    market, sel = rec.get("market"), rec.get("selection", "")
    point = rec.get("point")

    if market == "h2h":
        nsel = nickname(sel)
        if nsel == nickname(res.get("home")):
            return hs > as_ if hs != as_ else None
        if nsel == nickname(res.get("away")):
            return as_ > hs if hs != as_ else None
        return None
    if market == "spreads" and point is not None:
        nsel = nickname(sel)
        if nsel == nickname(res.get("home")):
            margin = (hs - as_) + point
        elif nsel == nickname(res.get("away")):
            margin = (as_ - hs) + point
        else:
            return None
        return None if margin == 0 else margin > 0
    if market == "totals" and point is not None:
        total = hs + as_
        if total == point:
            return None
        return total > point if sel.lower() == "over" else total < point
    return None


def compute_calibration(recommendations: List[dict], results: List[dict]) -> dict:
    idx = _index(results)
    graded: List[Tuple[float, bool]] = []
    for rec in recommendations:
        fp = rec.get("fair_prob")
        res = _match(rec, idx)
        if fp is None or res is None:
            continue
        outcome = _settle(rec, res)
        if outcome is None:
            continue
        graded.append((float(fp), outcome))

    if not graded:
        return {"graded": 0, "brier": None, "bins": [],
                "note": "Calibration builds as graded results accumulate."}

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
    return {"graded": len(graded), "brier": round(brier, 4), "bins": bins, "note": ""}
