"""Budget guard: window gating, adaptive throttle, and daily cap math."""
from datetime import datetime, timedelta, timezone

from agent import budget


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_days_left_inclusive():
    today = datetime(2026, 7, 17, tzinfo=timezone.utc).date()
    assert budget.days_left("2026-07-19", today) == 3   # 17, 18, 19
    assert budget.days_left("2026-07-17", today) == 1
    assert budget.days_left("2026-06-01", today) == 1   # past -> clamps to 1


def test_in_window_pre_and_post():
    now = datetime(2026, 6, 19, 19, 0, tzinfo=timezone.utc)
    kickoff = now + timedelta(minutes=45)               # starts in 45 min
    assert budget.in_window(now, [_iso(kickoff)], pre_min=60, post_min=150)
    # 61 min before kickoff -> outside the pre-window
    assert not budget.in_window(now, [_iso(now + timedelta(minutes=61))],
                                pre_min=60, post_min=150)
    # 2h into a match that kicked off earlier -> still hot (post=150)
    assert budget.in_window(now, [_iso(now - timedelta(minutes=120))],
                            pre_min=60, post_min=150)


def test_skip_when_no_match_in_window():
    now = datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc)
    far = now + timedelta(hours=8)
    d = budget.decide_wc_poll(
        now, [_iso(far)], remaining=400, cost=2, state={},
        pre_min=60, post_min=150, min_interval_min=15, reserve=20,
        end_date="2026-07-19",
    )
    assert not d.poll and "window" in d.reason


def test_poll_when_in_window_with_budget():
    now = datetime(2026, 6, 19, 19, 0, tzinfo=timezone.utc)
    kickoff = now + timedelta(minutes=30)
    d = budget.decide_wc_poll(
        now, [_iso(kickoff)], remaining=400, cost=2, state={},
        pre_min=60, post_min=150, min_interval_min=15, reserve=20,
        end_date="2026-07-19",
    )
    assert d.poll and d.daily_cap > 0


def test_daily_cap_blocks_overspend():
    now = datetime(2026, 7, 19, 19, 0, tzinfo=timezone.utc)  # last day
    kickoff = now + timedelta(minutes=30)
    # remaining 25, reserve 20 -> budget 5, days_left 1 -> cap 5 credits today.
    state = {"date": "2026-07-19", "wc_spent_today": 4}
    d = budget.decide_wc_poll(
        now, [_iso(kickoff)], remaining=25, cost=2, state=state,
        pre_min=60, post_min=150, min_interval_min=15, reserve=20,
        end_date="2026-07-19",
    )
    assert not d.poll and "cap" in d.reason


def test_min_interval_throttles():
    now = datetime(2026, 6, 19, 19, 0, tzinfo=timezone.utc)
    kickoff = now + timedelta(minutes=30)
    state = {"date": "2026-06-19", "wc_spent_today": 2,
             "last_wc_poll": _iso(now - timedelta(minutes=5))}
    d = budget.decide_wc_poll(
        now, [_iso(kickoff)], remaining=400, cost=2, state=state,
        pre_min=60, post_min=150, min_interval_min=15, reserve=20,
        end_date="2026-07-19",
    )
    assert not d.poll and "throttled" in d.reason


def test_credit_reserve_floor():
    now = datetime(2026, 6, 19, 19, 0, tzinfo=timezone.utc)
    kickoff = now + timedelta(minutes=30)
    # remaining 21, cost 2 -> 19 after, below reserve 20.
    d = budget.decide_wc_poll(
        now, [_iso(kickoff)], remaining=21, cost=2, state={},
        pre_min=60, post_min=150, min_interval_min=15, reserve=20,
        end_date="2026-07-19",
    )
    assert not d.poll


def test_engine_interval_and_reserve():
    now = datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc)
    ok, _ = budget.decide_engine_poll(now, remaining=400, state={},
                                      min_interval_hours=24, reserve=20)
    assert ok
    recent = {"last_engine_poll": _iso(now - timedelta(hours=3))}
    blocked, reason = budget.decide_engine_poll(now, remaining=400, state=recent,
                                                min_interval_hours=24, reserve=20)
    assert not blocked and "throttled" in reason
    low, reason = budget.decide_engine_poll(now, remaining=15, state={},
                                            min_interval_hours=24, reserve=20)
    assert not low and "reserve" in reason
