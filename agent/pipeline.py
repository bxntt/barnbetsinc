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
from .engine.ev import evaluate_game
from .engine.movement import attach_movement
from .providers.base import get_provider
from .publish import build_payload, write_site_data
from .rank import rank_bets
from .store import (
    load_recommendations,
    load_snapshots,
    log_recommendations,
    save_snapshot,
)


def run(config: Config = None) -> dict:
    config = config or Config.load()

    # 1) Fetch normalized games from the configured provider.
    provider = get_provider(config)
    games = provider.fetch_odds()

    # 2) Snapshot the target book's prices BEFORE evaluating (so movement uses
    #    history that does not yet include this run's current prices).
    snapshots = load_snapshots()
    save_snapshot(games, config.target_book)

    # 3) Evaluate every game for +EV bets at the target book.
    bets = []
    for g in games:
        bets.extend(evaluate_game(g, config))

    # 4) Confirming signals + context.
    attach_movement(bets, snapshots)
    enrich(bets, config)

    # 5) Rank and trim.
    ranked = rank_bets(bets, config.max_published)

    # 6) Track record (CLV) from prior recommendations + snapshots.
    track_record = compute_track_record(load_recommendations(), snapshots)

    # 7) Publish + log this run's recommendations for future grading.
    payload = build_payload(ranked, track_record, config.target_book)
    write_site_data(payload)
    log_recommendations(ranked)

    return payload


def main() -> int:
    payload = run()
    tr = payload["track_record"]
    print(
        f"[pipeline] provider={Config.load().provider} "
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
