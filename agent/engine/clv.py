"""Closing Line Value (CLV) — the bot's credibility metric.

For each past recommendation whose game has started, we find the closing snapshot
(the last one recorded before kickoff) and measure how the recommended price did
against the closing no-vig fair value:

    clv_pct = (rec_decimal * closing_fair_prob - 1) * 100

This is "EV measured at the closing line." Consistently positive CLV is the
strongest evidence a betting process is genuinely +EV. With no graded history
yet, returns a friendly placeholder.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from ..odds_math import american_to_decimal, american_to_implied
from .devig import outcome_key  # noqa: F401  (kept for parity / future use)


def _parse(ts: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def _closing_price(key: str, commence: datetime, snapshots: List[dict]) -> Optional[int]:
    """Target-book price in the last snapshot taken before kickoff."""
    closing = None
    for snap in snapshots:  # oldest-first
        snap_time = _parse(snap.get("generated_at", ""))
        if snap_time is None or snap_time > commence:
            continue
        price = snap.get("target_prices", {}).get(key)
        if price is not None:
            closing = price
    return closing


def compute_track_record(recommendations: List[dict], snapshots: List[dict]) -> dict:
    """Aggregate CLV over all gradeable recommendations."""
    now = datetime.now(timezone.utc)
    clvs: List[float] = []

    for rec in recommendations:
        commence = _parse(rec.get("commence_time", ""))
        if commence is None or commence > now:
            continue  # game hasn't started; can't grade yet
        closing = _closing_price(rec["key"], commence, snapshots)
        if closing is None:
            continue
        # Closing no-vig fair value, approximated from the closing target price's
        # implied probability (best available proxy when no reference is stored).
        closing_fair_prob = american_to_implied(closing)
        rec_decimal = american_to_decimal(rec["price_american"])
        clvs.append((rec_decimal * closing_fair_prob - 1.0) * 100.0)

    if not clvs:
        return {
            "graded": 0,
            "avg_clv_pct": None,
            "beat_close_pct": None,
            "note": "Tracking — needs graded games to report a record.",
        }

    return {
        "graded": len(clvs),
        "avg_clv_pct": round(sum(clvs) / len(clvs), 2),
        "beat_close_pct": round(100.0 * sum(1 for c in clvs if c > 0) / len(clvs), 1),
        "note": "",
    }
