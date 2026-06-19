"""World Cup pipeline: fetch matches -> value finder + group simulator -> JSON.

    python -m agent.worldcup.pipeline

Writes site/worldcup.json (read by the "World Cup" tab on the site). Works out of
the box with the bundled mock field; set `worldcup.provider: the_odds_api` in
config.yaml (and THE_ODDS_API_KEY) for live odds.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..config import Config, ROOT
from .provider import get_matches, the_odds_api_events, the_odds_api_matches_meta
from .simulate import simulate
from .value import find_value, rank_value

SITE_DATA = ROOT / "site" / "worldcup.json"


def _fetch_live_or_skip(config: Config):
    """Free /events gate + budget guard for the live provider.

    Returns (matches, remaining). `matches` is None when this tick is skipped
    (no credits spent, last site/worldcup.json left in place); `remaining` is the
    live credit balance read for free from /events (so the engine gate can use it).
    """
    from .. import budget

    wc = config.worldcup
    now = datetime.now(timezone.utc)
    commence_times, remaining = the_odds_api_events(config.the_odds_api_key, wc.competition)
    if remaining is None:
        remaining = 0

    state = budget.load_today_state(now)
    cost = len(wc.markets) * len([r for r in wc.regions.split(",") if r.strip()])
    decision = budget.decide_wc_poll(
        now, commence_times,
        remaining=remaining, cost=cost, state=state,
        pre_min=wc.pre_kickoff_min, post_min=wc.post_kickoff_min,
        min_interval_min=wc.min_interval_min, reserve=wc.credit_reserve,
        end_date=wc.tournament_end,
    )
    print(f"[worldcup] remaining={remaining} cr, cost/poll={cost}, "
          f"decision={'POLL' if decision.poll else 'skip'} ({decision.reason})")
    if not decision.poll:
        return None, remaining

    matches, remaining_after = the_odds_api_matches_meta(
        config.the_odds_api_key, wc.competition, wc.markets, wc.regions)
    budget.record_wc_poll(state, cost, now)
    if remaining_after is not None:
        remaining = remaining_after
        print(f"[worldcup] polled live odds -> {len(matches)} matches "
              f"({remaining_after} cr remaining)")
    return matches, remaining


def run(config: Config = None) -> dict:
    config = config or Config.load()
    wc = config.worldcup

    remaining = None
    if wc.provider == "the_odds_api":
        matches, remaining = _fetch_live_or_skip(config)
        if matches is None:
            return {"skipped": True, "value_count": 0, "groups": [], "remaining": remaining}
    else:
        matches = get_matches(
            wc.provider,
            the_odds_api_key=config.the_odds_api_key,
            competition=wc.competition,
            markets=wc.markets,
            seed=wc.seed % 100,  # provider slate seed (distinct from the sim seed)
        )

    # 1) Match value finder (works for any provider — needs only odds).
    quotes = []
    for m in matches:
        quotes.extend(find_value(m, wc.markets, wc.min_ev_pct))
    value_bets = rank_value(quotes, wc.max_published)

    # 2) Group simulator — only when matches carry a real group label.
    grouped = [m for m in matches if m.group]
    group_projections = []
    sim_note = ""
    if grouped:
        group_projections = simulate(grouped, sims=wc.sims, seed=wc.seed)
    else:
        sim_note = (
            "Group simulator needs group/schedule metadata, which the live odds feed "
            "doesn't provide. Use the mock provider (or add a fixtures map) to enable it."
        )

    payload = _build_payload(value_bets, group_projections, sim_note, wc)
    SITE_DATA.parent.mkdir(parents=True, exist_ok=True)
    SITE_DATA.write_text(json.dumps(payload, indent=2))
    return {**payload, "remaining": remaining}


def _build_payload(value_bets, group_projections, sim_note, wc) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "competition": wc.competition,
        "provider": wc.provider,
        "min_ev_pct": wc.min_ev_pct,
        "sims": wc.sims,
        "value_count": len(value_bets),
        "value_bets": [q.to_dict() for q in value_bets],
        "groups": [g.to_dict() for g in group_projections],
        "sim_note": sim_note,
        "disclaimer": (
            "Sportsbook-agnostic. Fair odds and advancement chances are estimates from "
            "the public market, not predictions. Informational only, 21+ where legal."
        ),
    }


def main() -> int:
    payload = run()
    if payload.get("skipped"):
        print("[worldcup] skipped — no paid poll this tick (last snapshot kept).")
        return 0
    print(f"[worldcup] provider={payload['provider']} -> "
          f"{payload['value_count']} value bets, {len(payload['groups'])} groups simulated.")
    if payload["value_bets"]:
        top = payload["value_bets"][0]
        print(f"[worldcup] top value: {top['label']} {top['best_price_display']} "
              f"@ {top['best_book']} (+{top['ev_pct']}% EV)")
    if payload["groups"]:
        g = payload["groups"][0]
        fav = max(g["teams"], key=lambda t: t["p_win_group"])
        print(f"[worldcup] Group {g['group']} favorite: {fav['team']} "
              f"({fav['p_win_group_pct']}% to win group, {fav['p_advance_pct']}% to advance)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
