"""End-to-end run: fetch odds -> evaluate +EV -> rank -> publish.

    python -m agent.pipeline

Writes site/data.json, records a history snapshot, and logs recommendations for
CLV grading. Safe to run with the default `mock` provider (no API key needed).
"""
from __future__ import annotations

import sys

from .config import Config
from .context import enrich
from .engine.clv import compute_track_record
from .engine.devig import reference_fair
from .engine.ev import evaluate_game
from .engine.movement import attach_movement
from .providers.base import get_provider
from .publish import build_payload, write_site_data
from .rank import rank_bets
from .store import (
    bet_key,
    load_recommendations,
    load_snapshots,
    log_recommendations,
    save_snapshot,
)


def _ref_probs(games, config: Config) -> dict:
    """Sharp/consensus no-vig fair prob per bet key, stored in the snapshot so CLV
    and steam can be measured against the sharp market over time."""
    st = config.strategy
    out = {}
    for g in games:
        for market in config.markets:
            ref = reference_fair(
                g, market, config.sharp_books, config.target_book,
                method=st.devig_method, book_weights=st.book_weights,
            )
            if not ref:
                continue
            for (name, point), p in ref.fair_by_key.items():
                out[bet_key(g.id, market, name, point)] = round(p, 6)
    return out


def _grade_results(config: Config) -> list:
    """Fetch + persist final scores for grading/calibration (live provider only,
    so mock/offline runs stay deterministic). Best-effort; never raises."""
    if config.provider == "mock":
        return []
    if not (config.strategy.model_enabled or config.strategy.calibration_enabled):
        return []
    try:
        from .engine.results import fetch_results
        from .store import load_results, save_results
        save_results(fetch_results(config.sports))
        return load_results()
    except Exception:
        return []


def _engine_due(config: Config, remaining: int = None) -> bool:
    """Low-priority throttle: with a live provider, run the paid Hard Rock engine
    at most once per `engine_min_interval_hours` so the World Cup keeps the budget.
    The mock provider is free, so it always runs. `remaining` is the live credit
    balance (read for free by the World Cup /events call)."""
    if config.provider == "mock":
        return True
    from datetime import datetime, timezone

    from . import budget
    now = datetime.now(timezone.utc)
    state = budget.load_today_state(now)
    due, reason = budget.decide_engine_poll(
        now, remaining=remaining if remaining is not None else 10**6, state=state,
        min_interval_hours=config.engine_min_interval_hours,
        reserve=config.engine_credit_reserve,
    )
    print(f"[pipeline] engine {'RUN' if due else 'skip'} ({reason})")
    if due:
        budget.record_engine_poll(state, now)
    return due


def run(config: Config = None) -> dict:
    config = config or Config.load()

    # 1) Fetch normalized games from the configured provider.
    provider = get_provider(config)
    games = provider.fetch_odds()

    # 2) Snapshot the target book's prices + sharp fair probs BEFORE evaluating
    #    (so movement/CLV use history that excludes this run's current prices).
    snapshots = load_snapshots()
    save_snapshot(games, config.target_book, _ref_probs(games, config))

    # 3) Evaluate every game for +EV bets at the target book.
    bets = []
    for g in games:
        bets.extend(evaluate_game(g, config))

    # 4) Confirming signals + context.
    attach_movement(bets, snapshots)
    enrich(bets, config)

    # 5) Independent-model cross-check (Elo) before ranking, so the rationale can
    #    note agreement/disagreement. No-op until enough graded games exist.
    results = _grade_results(config)
    if config.strategy.model_enabled and results:
        try:
            from .engine.elo import annotate as elo_annotate
            elo_annotate(bets, results, config.strategy.model_min_games,
                         config.strategy.model_disagree)
        except Exception:
            pass

    # 6) Rank and trim.
    ranked = rank_bets(bets, config.max_published)

    # 7) Track record (CLV) + probability calibration from history.
    track_record = compute_track_record(load_recommendations(), snapshots)
    calibration = {}
    if config.strategy.calibration_enabled:
        try:
            from .engine.calibration import compute_calibration
            calibration = compute_calibration(load_recommendations(), results)
        except Exception:
            calibration = {}

    # 8) Publish + log this run's recommendations for future grading.
    payload = build_payload(ranked, track_record, config.target_book, calibration)
    write_site_data(payload)
    log_recommendations(ranked)

    return payload


def main() -> int:
    config = Config.load()

    # World Cup runs FIRST: its free /events call reads the live credit balance,
    # which the (lower-priority) Hard Rock engine gate then reuses. WC has its own
    # window gate + budget guard, so it only spends credits during match windows.
    remaining = None
    if config.worldcup.enabled:
        from .worldcup.pipeline import run as run_worldcup
        wc = run_worldcup(config)
        remaining = wc.get("remaining")
        if wc.get("skipped"):
            print("[pipeline] worldcup: skipped this tick (last snapshot kept).")
        else:
            print(f"[pipeline] worldcup: {wc['value_count']} value bets, "
                  f"{len(wc['groups'])} groups simulated -> site/worldcup.json")

    # Hard Rock engine: gated to at most once/interval on a live provider.
    if _engine_due(config, remaining):
        payload = run(config)
        tr = payload["track_record"]
        print(
            f"[pipeline] provider={config.provider} "
            f"games_evaluated -> {payload['count']} best bets published."
        )
        if payload["bets"]:
            top = payload["bets"][0]
            print(f"[pipeline] top: {top['label']} {top['price_display']} "
                  f"(+{top['ev_pct']}% EV, conf {top['confidence']})")
        if tr.get("avg_clv_pct") is not None:
            print(f"[pipeline] CLV: avg {tr['avg_clv_pct']}% over {tr['graded']} graded bets.")
        else:
            print(f"[pipeline] CLV: {tr.get('note', 'n/a')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
