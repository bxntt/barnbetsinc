"""End-to-end run: fetch odds -> predict outcomes -> rank -> publish.

    python -m agent.pipeline

Writes site/data.json and logs predictions for the calibration loop. Safe to run
with the default `mock` provider (no API key needed). Predictions come from a
team-strength model blended with market consensus — no single book is judged.
"""
from __future__ import annotations

import sys

from .config import Config
from .context import enrich
from .engine.predict import predict_games
from .engine.ratings import build_team_model
from .providers.base import get_provider
from .publish import build_payload, write_site_data
from .rank import rank_predictions
from .store import load_recommendations, log_recommendations


def _grade_results(config: Config) -> list:
    """Fetch + persist final scores to build the model + calibration (live provider
    only, so mock/offline runs stay deterministic). Best-effort; never raises."""
    if config.provider == "mock":
        return []
    try:
        from .engine.results import fetch_results
        from .store import load_results, save_results
        save_results(fetch_results(config.sports))
        return load_results()
    except Exception:
        return []


def _engine_due(config: Config, remaining: int = None) -> bool:
    """Low-priority throttle: with a live provider, run the paid US-sports predictor
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

    # 2) Build the team-strength model from free results history (live only).
    results = _grade_results(config)
    model = build_team_model(results, config.strategy.model_min_games)

    # 3) Predict every game's markets (model blended with market consensus).
    preds = predict_games(games, model, config)

    # 4) Context enrichment (injuries/weather), best-effort.
    enrich(preds, config)

    # 5) Rank by likelihood (whole games kept together) + trim.
    ranked = rank_predictions(preds, config.max_published)

    # 6) Probability calibration from logged predictions vs final results.
    calibration = {}
    if config.strategy.calibration_enabled:
        try:
            from .engine.calibration import compute_calibration
            calibration = compute_calibration(load_recommendations(), results)
        except Exception:
            calibration = {}

    # 7) Publish + log this run's predictions for future grading.
    payload = build_payload(ranked, calibration)
    write_site_data(payload)
    log_recommendations(ranked)

    return payload


def main() -> int:
    config = Config.load()

    # World Cup runs FIRST: its free /events call reads the live credit balance,
    # which the (lower-priority) US-sports predictor gate then reuses. WC has its own
    # window gate + budget guard, so it only spends credits during match windows.
    remaining = None
    if config.worldcup.enabled:
        from .worldcup.pipeline import run as run_worldcup
        wc = run_worldcup(config)
        remaining = wc.get("remaining")
        print(f"[pipeline] worldcup: {wc.get('prediction_count', 0)} predictions, "
              f"{len(wc.get('groups', []))} groups simulated -> site/worldcup.json")

    # US-sports predictor: gated to at most once/interval on a live provider.
    if _engine_due(config, remaining):
        payload = run(config)
        print(f"[pipeline] provider={config.provider} -> "
              f"{payload['count']} predictions published.")
        if payload["predictions"]:
            top = payload["predictions"][0]
            print(f"[pipeline] most likely: {top['pick']} ({top['prob_pct']}%) "
                  f"in {top['away_team']} @ {top['home_team']}")
        cal = payload.get("calibration", {})
        if cal.get("graded"):
            print(f"[pipeline] calibration: Brier {cal.get('brier')} "
                  f"over {cal['graded']} graded predictions.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
