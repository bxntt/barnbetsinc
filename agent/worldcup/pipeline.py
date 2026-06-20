"""World Cup pipeline: predict every match -> group simulator -> JSON.

    python -m agent.worldcup.pipeline

Writes site/worldcup.json (read by the "World Cup" tab on the site). We model
what is most likely to happen in each game — result, total, both-teams-to-score,
and handicap — from team strength + live form, blended with the market when odds
are available. Works out of the box with the bundled mock field; set
`worldcup.provider: the_odds_api` (and THE_ODDS_API_KEY) for the live schedule.

Predictions are model-driven and therefore FREE: the schedule (with matchups)
comes from the no-cost /events endpoint, so we refresh every tick. A paid odds
poll is made only inside a match window and within the credit budget, and it only
*sharpens* the prediction blend — it never gates whether we publish.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..config import Config, ROOT
from .predict import predict_all, rank_predictions
from .provider import (
    get_matches,
    the_odds_api_events,
    the_odds_api_matches_meta,
    the_odds_api_schedule,
)
from .simulate import simulate

SITE_DATA = ROOT / "site" / "worldcup.json"


def _maybe_poll_odds(config: Config, remaining):
    """Budget-guarded paid odds poll. Returns (odds_matches, remaining).

    Returns ([], remaining) when this tick shouldn't spend credits — predictions
    still run model-only. Mirrors the original budget guard, but a skip now only
    means "no market sharpening this tick", not "publish nothing".
    """
    from .. import budget

    wc = config.worldcup
    now = datetime.now(timezone.utc)
    commence_times, ev_remaining = the_odds_api_events(config.the_odds_api_key, wc.competition)
    if ev_remaining is not None:
        remaining = ev_remaining

    state = budget.load_today_state(now)
    cost = len(wc.markets) * len([r for r in wc.regions.split(",") if r.strip()])
    decision = budget.decide_wc_poll(
        now, commence_times,
        remaining=remaining or 0, cost=cost, state=state,
        pre_min=wc.pre_kickoff_min, post_min=wc.post_kickoff_min,
        min_interval_min=wc.min_interval_min, reserve=wc.credit_reserve,
        end_date=wc.tournament_end,
    )
    print(f"[worldcup] remaining={remaining} cr, cost/poll={cost}, "
          f"odds={'POLL' if decision.poll else 'skip'} ({decision.reason})")
    if not decision.poll:
        return [], remaining

    odds_matches, remaining_after = the_odds_api_matches_meta(
        config.the_odds_api_key, wc.competition, wc.markets, wc.regions)
    budget.record_wc_poll(state, cost, now)
    if remaining_after is not None:
        remaining = remaining_after
    print(f"[worldcup] polled live odds -> {len(odds_matches)} matches "
          f"({remaining} cr remaining)")
    return odds_matches, remaining


def _merge_odds(schedule, odds_matches):
    """Overlay polled odds onto the free schedule, keyed by event id."""
    if not odds_matches:
        return schedule
    by_id = {m.game.id: m for m in schedule}
    for om in odds_matches:
        by_id[om.game.id] = om  # odds carry the markets the schedule lacks
    return list(by_id.values())


def run(config: Config = None) -> dict:
    config = config or Config.load()
    wc = config.worldcup

    remaining = None
    standings = None
    sim_note = ""

    if wc.provider == "the_odds_api":
        # Free schedule (matchups) every tick; paid odds only to sharpen the blend.
        matches, remaining = the_odds_api_schedule(config.the_odds_api_key, wc.competition)
        odds_matches, remaining = _maybe_poll_odds(config, remaining)
        matches = _merge_odds(matches, odds_matches)

        from .fixtures import AS_OF, attach_groups, group_standings, unknown_teams
        attach_groups(matches)
        missing = unknown_teams(matches)
        if missing:
            print(f"[worldcup] unmapped feed teams (add aliases in fixtures.py): "
                  f"{sorted(missing)}")
        standings = group_standings()
        sim_note = (
            f"Predictions use team strength + form from the real standings as of "
            f"{AS_OF}, blended with live market odds when available. Group "
            f"advancement is a Monte Carlo over the remaining matches."
        )
    else:
        matches = get_matches(
            wc.provider,
            the_odds_api_key=config.the_odds_api_key,
            competition=wc.competition,
            markets=wc.markets,
            seed=wc.seed % 100,
        )

    grouped = [m for m in matches if m.group]

    # 0) Availability report (who was expected to play but isn't), by game, plus a
    #    canonical team -> absences map that the predictor and simulator consume so
    #    injuries actually move the numbers (not just the Injuries page).
    from .injuries import run as run_injuries, team_absences_map
    match_pool = grouped if grouped else matches
    injuries = run_injuries(match_pool, use_espn=wc.injuries_espn)
    print(f"[worldcup] injuries: {injuries['total_absences']} absences across "
          f"{injuries['affected_games']}/{injuries['game_count']} games -> site/injuries.json")
    teams = {name for m in match_pool for name in (m.home, m.away) if name}
    absences = team_absences_map(sorted(teams), use_espn=wc.injuries_espn)

    # 0b) Settle finals + self-correct ratings (live only) BEFORE predicting, so
    #     this tick's calls use the freshest team strength. Finals come from the
    #     free ESPN scoreboard (no odds credits) and are decoupled from
    #     injuries_espn — they fund both the Elo loop and the grading loop below.
    if wc.provider == "the_odds_api":
        from . import calibration, elo
        calibration.save_results(calibration.espn_results_range())
        elo_summary = elo.update_from_results(calibration.load_results())
        if elo_summary.get("applied"):
            print(f"[worldcup] elo: folded {elo_summary['applied']} new result(s) -> "
                  f"{elo_summary['rated']} teams now results-adjusted "
                  f"(data/history/worldcup_elo.json)")

    # 1) Per-game predictions (model + injuries/form/venue + optional market blend).
    preds = predict_all(match_pool, standings, absences)
    predictions = rank_predictions(preds, wc.max_published)

    # 1b) Grading loop (live only): log these calls, then settle past calls against
    #     the finals already fetched above -> RPS/log loss/Brier. Never gates publishing.
    if wc.provider == "the_odds_api":
        calibration.log_predictions(predictions)
        calib = calibration.run(use_espn=False)  # finals already saved in step 0b
        res = calib.get("result", {})
        if res.get("n"):
            print(f"[worldcup] calibration: result RPS={res['rps']} "
                  f"log_loss={res['log_loss']} over {res['n']} graded "
                  f"({calib['graded_total']} calls total) -> site/worldcup_calibration.json")
        else:
            print(f"[worldcup] calibration: {calib.get('graded_total', 0)} calls "
                  f"graded so far (builds as results settle)")

    # 2) Group-stage Monte Carlo.
    group_projections = []
    if standings:
        upcoming = [m for m in grouped if not m.played]
        group_projections = simulate(
            upcoming, sims=wc.sims, seed=wc.seed, seed_standings=standings,
            absences=absences)
    elif grouped:
        group_projections = simulate(grouped, sims=wc.sims, seed=wc.seed,
                                     absences=absences)
        sim_note = ("Each remaining match is played out thousands of times from "
                    "the team-strength model (sharpened by market odds where quoted).")

    payload = _build_payload(predictions, group_projections, sim_note, wc)
    SITE_DATA.parent.mkdir(parents=True, exist_ok=True)
    SITE_DATA.write_text(json.dumps(payload, indent=2))
    return {**payload, "remaining": remaining}


def _build_payload(predictions, group_projections, sim_note, wc) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "competition": wc.competition,
        "provider": wc.provider,
        "sims": wc.sims,
        "prediction_count": len(predictions),
        "predictions": [p.to_dict() for p in predictions],
        "groups": [g.to_dict() for g in group_projections],
        "sim_note": sim_note,
        "disclaimer": (
            "Predictions are estimates, not certainties. "
            "Informational only, 21+ where legal."
        ),
    }


def main() -> int:
    payload = run()
    print(f"[worldcup] provider={payload['provider']} -> "
          f"{payload['prediction_count']} predictions, "
          f"{len(payload['groups'])} groups simulated.")
    if payload["predictions"]:
        top = payload["predictions"][0]
        print(f"[worldcup] most likely: {top['pick']} ({top['prob_pct']}%) "
              f"in {top['home']} vs {top['away']}")
    if payload["groups"]:
        g = payload["groups"][0]
        fav = max(g["teams"], key=lambda t: t["p_win_group"])
        print(f"[worldcup] Group {g['group']} favorite: {fav['team']} "
              f"({fav['p_win_group_pct']}% to win group, {fav['p_advance_pct']}% to advance)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
