"""Closing Line Value (CLV) — the bot's credibility metric.

For each past recommendation whose game has started, we find the closing snapshot
(the last one recorded before kickoff) and measure how the recommended price did
against the closing no-vig fair value:

    clv_pct = (rec_decimal * closing_fair_prob - 1) * 100

`closing_fair_prob` is the sharp/consensus no-vig fair prob stored in the snapshot
(`ref_probs`); if a snapshot predates that field we fall back to the target book's
own implied prob. Consistently positive CLV is the strongest evidence a betting
process is genuinely +EV. Results are also broken out by sport so segments that
beat the close can be trusted (and those that don't, down-weighted).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..odds_math import american_to_decimal, american_to_implied


def _parse(ts: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def _closing(key: str, commence: datetime, snapshots: List[dict]):
    """(closing sharp fair prob, closing target price) from the last pre-kickoff
    snapshot. Either may be None if not recorded."""
    fair = price = None
    for snap in snapshots:  # oldest-first
        snap_time = _parse(snap.get("generated_at", ""))
        if snap_time is None or snap_time > commence:
            continue
        p = snap.get("target_prices", {}).get(key)
        if p is not None:
            price = p
        rp = snap.get("ref_probs", {}).get(key)
        if rp is not None:
            fair = rp
    return fair, price


def _summary(clvs: List[float]) -> dict:
    return {
        "graded": len(clvs),
        "avg_clv_pct": round(sum(clvs) / len(clvs), 2),
        "beat_close_pct": round(100.0 * sum(1 for c in clvs if c > 0) / len(clvs), 1),
    }


def compute_track_record(recommendations: List[dict], snapshots: List[dict]) -> dict:
    """Aggregate CLV over all gradeable recommendations, overall and by sport."""
    now = datetime.now(timezone.utc)
    clvs: List[float] = []
    by_sport: Dict[str, List[float]] = defaultdict(list)

    for rec in recommendations:
        commence = _parse(rec.get("commence_time", ""))
        if commence is None or commence > now:
            continue  # game hasn't started; can't grade yet
        closing_fair, closing_price = _closing(rec["key"], commence, snapshots)
        if closing_fair is None:
            if closing_price is None:
                continue
            closing_fair = american_to_implied(closing_price)  # fallback proxy
        rec_decimal = american_to_decimal(rec["price_american"])
        clv = (rec_decimal * closing_fair - 1.0) * 100.0
        clvs.append(clv)
        by_sport[rec.get("sport_key", "?")].append(clv)

    if not clvs:
        return {
            "graded": 0,
            "avg_clv_pct": None,
            "beat_close_pct": None,
            "by_sport": {},
            "note": "Tracking — needs graded games to report a record.",
        }

    out = _summary(clvs)
    out["by_sport"] = {s: _summary(v) for s, v in sorted(by_sport.items())}
    out["note"] = ""
    return out
