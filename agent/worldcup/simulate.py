"""Monte Carlo group-stage simulator (2026 format).

48 teams, 12 groups (A-L) of four, single round-robin (6 matches/group). The top
two of each group plus the eight best third-placed teams advance to the Round of
32. We drive it entirely off the market: each unplayed match's no-vig 1X2 line is
turned into Poisson goal expectancies, scorelines are sampled, group tables are
built with FIFA-style tiebreakers, and we count how often each team wins its group
and advances.

Played matches use their real scoreline, so projections sharpen as the group stage
progresses. Tiebreakers: points, goal difference, goals for, then a (seeded)
random draw — head-to-head is intentionally omitted for simplicity.
"""
from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .devig import consensus_fair
from .models import GroupProjection, Match, TeamProjection
from .poisson import fit_lambdas, goal_cdf, sample_goals

THIRD_PLACE_SLOTS = 8  # how many third-placed teams advance (full 2026 field)


@dataclass
class _MatchModel:
    home: str
    away: str
    played: bool
    home_goals: int = 0
    away_goals: int = 0
    cdf_home: Optional[List[float]] = None
    cdf_away: Optional[List[float]] = None


def _fair_1x2(match: Match) -> Optional[Tuple[float, float, float]]:
    """(P home, P draw, P away) from the consensus 1X2 line, or None."""
    fair = consensus_fair(match.game.markets.get("h2h", []))
    if fair is None:
        return None
    by_name = {k[0]: v for k, v in fair.fair_by_key.items()}
    ph = by_name.get(match.home)
    pa = by_name.get(match.away)
    pd = by_name.get("Draw")
    if ph is None or pa is None:
        return None
    if pd is None:  # 2-way line (no draw quoted) — shouldn't happen for soccer
        pd = max(0.0, 1.0 - ph - pa)
    return ph, pd, pa


def _mean_goals(match: Match) -> float:
    """Seed the Poisson search from the totals line if the book quotes one."""
    totals = match.game.markets.get("totals", [])
    fair = consensus_fair(totals)
    if fair:
        points = [k[1] for k in fair.fair_by_key if k[1] is not None]
        if points:
            return float(points[0])
    return 2.7


def _build_model(match: Match) -> _MatchModel:
    if match.played and match.home_goals is not None and match.away_goals is not None:
        return _MatchModel(match.home, match.away, True, match.home_goals, match.away_goals)

    probs = _fair_1x2(match)
    if probs is None:
        lh = la = 1.35  # no market -> neutral coin-flip-ish model
    else:
        lh, la = fit_lambdas(*probs, mean_goals=_mean_goals(match))
    return _MatchModel(
        match.home, match.away, False,
        cdf_home=goal_cdf(lh), cdf_away=goal_cdf(la),
    )


def _current_standings(models: List[_MatchModel], teams: List[str]) -> Dict[str, Dict]:
    """Points / GD / games-played from matches already decided."""
    table = {t: {"points": 0, "gd": 0, "gf": 0, "played": 0} for t in teams}
    for m in models:
        if not m.played:
            continue
        for t, gf, ga in ((m.home, m.home_goals, m.away_goals),
                          (m.away, m.away_goals, m.home_goals)):
            if t not in table:
                continue
            table[t]["played"] += 1
            table[t]["gf"] += gf
            table[t]["gd"] += gf - ga
            table[t]["points"] += 3 if gf > ga else (1 if gf == ga else 0)
    return table


def simulate(
    matches: List[Match],
    sims: int = 20000,
    seed: int = 42,
    third_place_slots: int = THIRD_PLACE_SLOTS,
) -> List[GroupProjection]:
    """Run the Monte Carlo and return per-group, per-team projections."""
    rng = random.Random(seed)

    by_group: Dict[str, List[Match]] = defaultdict(list)
    for m in matches:
        by_group[m.group].append(m)

    groups = sorted(by_group)
    n_thirds = min(third_place_slots, len(groups))

    # Precompute the per-match scoreline model once (the expensive fit).
    models: Dict[str, List[_MatchModel]] = {
        g: [_build_model(m) for m in by_group[g]] for g in groups
    }
    teams_in: Dict[str, List[str]] = {}
    for g in groups:
        seen: List[str] = []
        for m in models[g]:
            for t in (m.home, m.away):
                if t not in seen:
                    seen.append(t)
        teams_in[g] = seen

    # Tallies.
    win_group = defaultdict(int)
    top2 = defaultdict(int)
    advance = defaultdict(int)
    points_sum = defaultdict(float)
    finish = {g: {t: defaultdict(int) for t in teams_in[g]} for g in groups}

    for _ in range(sims):
        third_pool: List[Tuple[Tuple[int, int, int], str]] = []  # (key, team)

        for g in groups:
            stats = {t: [0, 0, 0] for t in teams_in[g]}  # [points, gd, gf]
            for m in models[g]:
                if m.played:
                    hg, ag = m.home_goals, m.away_goals
                else:
                    hg = sample_goals(m.cdf_home, rng)
                    ag = sample_goals(m.cdf_away, rng)
                sh, sa = stats[m.home], stats[m.away]
                sh[1] += hg - ag; sa[1] += ag - hg
                sh[2] += hg; sa[2] += ag
                if hg > ag:
                    sh[0] += 3
                elif hg < ag:
                    sa[0] += 3
                else:
                    sh[0] += 1; sa[0] += 1

            # Rank: points, GD, GF, then a random draw to break exact ties.
            ranked = sorted(
                teams_in[g],
                key=lambda t: (stats[t][0], stats[t][1], stats[t][2], rng.random()),
                reverse=True,
            )
            for pos, t in enumerate(ranked):
                finish[g][t][pos + 1] += 1
                points_sum[t] += stats[t][0]
            win_group[ranked[0]] += 1
            top2[ranked[0]] += 1
            top2[ranked[1]] += 1
            advance[ranked[0]] += 1
            advance[ranked[1]] += 1
            third = ranked[2]
            s = stats[third]
            third_pool.append(((s[0], s[1], s[2]), third))

        # Eight best third-placed teams advance too.
        third_pool.sort(key=lambda x: (x[0][0], x[0][1], x[0][2], rng.random()), reverse=True)
        for _key, team in third_pool[:n_thirds]:
            advance[team] += 1

    # Assemble projections.
    out: List[GroupProjection] = []
    for g in groups:
        cur = _current_standings(models[g], teams_in[g])
        projs = []
        for t in teams_in[g]:
            fp = {str(p): finish[g][t][p] / sims for p in (1, 2, 3, 4)}
            projs.append(TeamProjection(
                team=t,
                group=g,
                played=cur[t]["played"],
                points=cur[t]["points"],
                goal_diff=cur[t]["gd"],
                p_win_group=win_group[t] / sims,
                p_top2=top2[t] / sims,
                p_advance=advance[t] / sims,
                exp_points=points_sum[t] / sims,
                finish_probs=fp,
            ))
        # Display order: current points, then projected advancement.
        projs.sort(key=lambda p: (p.points, p.goal_diff, p.p_advance), reverse=True)
        played = sum(1 for m in models[g] if m.played)
        out.append(GroupProjection(
            group=g, teams=projs, matches_played=played, matches_total=len(models[g]),
        ))
    return out
