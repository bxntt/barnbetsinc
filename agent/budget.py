"""Credit budget guard for live polling on The Odds API's free tier.

The whole point: never exceed the monthly credit quota, while still polling
often enough to stay fresh during World Cup matches. Two free signals make this
possible — the `/events` endpoint (schedule) costs 0 credits and every response
(even free ones) reports `x-requests-remaining`.

Decision logic, evaluated each cron tick:

  1. Window gate    — only consider polling when a match is within
                      [kickoff - pre, kickoff + post].
  2. Adaptive cap   — a rolling daily budget = (remaining - reserve) / days_left.
                      Polls are spaced evenly across the day's hot windows so a
                      busy match day can't drain the month.
  3. Min interval   — never poll more than once per `min_interval` regardless.

State (spent-so-far today, last poll times) lives in a small JSON file under
data/history/ so it survives across stateless CI runs (committed by the workflow).
`remaining` itself is read live from response headers, so local accounting can
never drift away from the provider's real number.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from .config import ROOT

STATE_PATH = ROOT / "data" / "history" / "api_budget.json"


def remaining_from_response(resp) -> Optional[int]:
    """Read x-requests-remaining from a requests.Response (None if absent)."""
    val = resp.headers.get("x-requests-remaining")
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------- state ---

def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text()) or {}
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def _roll_day(state: dict, today: str) -> dict:
    """Reset per-day counters when the UTC date changes."""
    if state.get("date") != today:
        state = {
            "date": today,
            "wc_spent_today": 0,
            "wc_polls_today": 0,
            "last_wc_poll": state.get("last_wc_poll"),
            "last_engine_poll": state.get("last_engine_poll"),
        }
    state.setdefault("wc_spent_today", 0)
    state.setdefault("wc_polls_today", 0)
    return state


# ------------------------------------------------------------- pure helpers ---

def days_left(end: str, today: Optional[date] = None) -> int:
    """Inclusive days from today through the tournament end date (>= 1)."""
    today = today or datetime.now(timezone.utc).date()
    try:
        end_d = date.fromisoformat(end)
    except (TypeError, ValueError):
        return 1
    return max(1, (end_d - today).days + 1)


def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def in_window(now: datetime, commence_times: Iterable[str],
              pre_min: int, post_min: int) -> bool:
    """True if `now` falls in any match's [kickoff-pre, kickoff+post] window."""
    for ts in commence_times:
        k = _parse_iso(ts)
        if k is None:
            continue
        if k - timedelta(minutes=pre_min) <= now <= k + timedelta(minutes=post_min):
            return True
    return False


def _hot_minutes_today(now: datetime, commence_times: Iterable[str],
                       pre_min: int, post_min: int) -> float:
    """Approx total minutes of hot windows for matches kicking off today (UTC).

    Sums per-match window length without subtracting overlap — an overestimate,
    which makes the spacing interval larger and keeps spending conservative.
    """
    span = pre_min + post_min
    today = now.date()
    count = 0
    for ts in commence_times:
        k = _parse_iso(ts)
        if k is not None and k.date() == today:
            count += 1
    return max(span, count * span)  # at least one window so interval is finite


@dataclass
class WCDecision:
    poll: bool
    reason: str
    interval_min: float = 0.0
    daily_cap: float = 0.0


def decide_wc_poll(
    now: datetime,
    commence_times: List[str],
    *,
    remaining: int,
    cost: int,
    state: dict,
    pre_min: int,
    post_min: int,
    min_interval_min: int,
    reserve: int,
    end_date: str,
) -> WCDecision:
    """Decide whether to spend `cost` credits on a live World Cup odds poll.

    Pure: callers pass live `remaining` (from a free /events response) and the
    persisted `state`. Spacing is adaptive — the day's spend cap is spread across
    the day's hot windows so coverage stays even instead of front-loaded.
    """
    if not in_window(now, commence_times, pre_min, post_min):
        return WCDecision(False, "no match in window")

    budget = max(0, remaining - reserve)
    daily_cap = budget / days_left(end_date, now.date())
    spent = state.get("wc_spent_today", 0)
    if spent + cost > daily_cap:
        return WCDecision(False, f"daily cap reached ({spent}/{daily_cap:.0f} cr)",
                          daily_cap=daily_cap)
    if remaining - cost < reserve:
        return WCDecision(False, f"credit reserve ({remaining} left)", daily_cap=daily_cap)

    allowed_polls = max(1, int(daily_cap // max(1, cost)))
    hot = _hot_minutes_today(now, commence_times, pre_min, post_min)
    interval = max(min_interval_min, hot / allowed_polls)

    last = _parse_iso(state.get("last_wc_poll") or "")
    if last is not None and (now - last) < timedelta(minutes=interval):
        elapsed = (now - last).total_seconds() / 60
        return WCDecision(False, f"throttled ({elapsed:.0f}/{interval:.0f} min)",
                          interval_min=interval, daily_cap=daily_cap)

    return WCDecision(True, "poll", interval_min=interval, daily_cap=daily_cap)


def decide_engine_poll(
    now: datetime,
    *,
    remaining: int,
    state: dict,
    min_interval_hours: int,
    reserve: int,
) -> Tuple[bool, str]:
    """Low-priority gate for the Hard Rock engine: at most once per interval."""
    if remaining <= reserve:
        return False, f"credit reserve ({remaining} left)"
    last = _parse_iso(state.get("last_engine_poll") or "")
    if last is not None and (now - last) < timedelta(hours=min_interval_hours):
        elapsed = (now - last).total_seconds() / 3600
        return False, f"throttled ({elapsed:.1f}/{min_interval_hours} h)"
    return True, "poll"


# ------------------------------------------------------ stateful entrypoints ---

def load_today_state(now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return _roll_day(_load_state(), now.date().isoformat())


def record_wc_poll(state: dict, cost: int, now: datetime) -> None:
    state["wc_spent_today"] = state.get("wc_spent_today", 0) + cost
    state["wc_polls_today"] = state.get("wc_polls_today", 0) + 1
    state["last_wc_poll"] = now.isoformat()
    _save_state(state)


def record_engine_poll(state: dict, now: datetime) -> None:
    state["last_engine_poll"] = now.isoformat()
    _save_state(state)
