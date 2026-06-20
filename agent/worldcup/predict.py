"""Model-driven match predictions — what we think will happen, per bet type.

This is the heart of the restructure. Instead of asking "which book is offering a
good price", we ask "what is most likely to happen in this game", and report a
call for every bet type:

    * result   — home win / draw / away win (1X2)
    * total    — over / under the central goal line
    * btts     — both teams to score: yes / no
    * handicap — the favorite to cover a goal line (win by N+)

The probabilities come from a team-strength model: each side's effective rating
(strength prior + live form) sets two Poisson goal rates, whose joint scoreline
grid yields every market exactly. When live odds are available we *blend* the
model with the no-vig market consensus — the market is sharp, so it sharpens us,
but the model always keeps majority weight (we are not just echoing the book).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from . import factors, ratings
from .devig import consensus_fair
from .models import Match, Prediction
from .poisson import fit_lambdas, mean_from_total_over, score_matrix

# Market blend: how much weight the (sharp) market can take from the model when
# odds are deep and tight. The model keeps at least (1 - MAX_MARKET_WEIGHT).
# The closing consensus is the single best predictor of what actually happens, so
# for a *likelihood* engine we let it lead when the line is deep and tight (the
# model still anchors thin/loose markets). Calibration (RPS/Brier) arbitrates the
# level — raise/lower here and watch site/worldcup_calibration.json.
MAX_MARKET_WEIGHT = 0.75


def _minutes_to_start(commence_time: str) -> Optional[float]:
    try:
        start = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None
    return (start - datetime.now(timezone.utc)).total_seconds() / 60.0


# ----------------------------------------------------- derived market math ---
def _result_probs(grid) -> Tuple[float, float, float]:
    """(P home win, P draw, P away win) from the scoreline grid."""
    ph = pd = pa = 0.0
    for i, row in enumerate(grid):
        for j, p in enumerate(row):
            if i > j:
                ph += p
            elif i == j:
                pd += p
            else:
                pa += p
    return ph, pd, pa


def _total_over(grid, line: float) -> float:
    """P(total goals > line)."""
    p = 0.0
    for i, row in enumerate(grid):
        for j, cell in enumerate(row):
            if i + j > line:
                p += cell
    return p


def _btts_yes(grid) -> float:
    """P(both teams score) = 1 - P(home 0) - P(away 0) + P(0-0)."""
    p_home_zero = sum(grid[0])
    p_away_zero = sum(row[0] for row in grid)
    p_nil_nil = grid[0][0]
    return max(0.0, 1.0 - p_home_zero - p_away_zero + p_nil_nil)


def _cover(grid, handicap: float, side: str) -> float:
    """P(`side` covers `handicap`). handicap is the favorite's line, e.g. -1.5.

    side="home": home margin (i-j) + handicap > 0. side="away": (j-i) - handicap > 0.
    Half-goal lines never push, so this is a clean win probability.
    """
    p = 0.0
    for i, row in enumerate(grid):
        for j, cell in enumerate(row):
            margin = (i - j) if side == "home" else (j - i)
            if margin + handicap > 0:
                p += cell
    return p


# ----------------------------------------------------------- market blend ---
def _market_result(match: Match) -> Optional[Tuple[float, float, float, float, int]]:
    """No-vig consensus 1X2 as (p_home, p_draw, p_away, vig, n_books), or None."""
    fair = consensus_fair(match.game.markets.get("h2h", []))
    if fair is None:
        return None
    by_name = {k[0]: v for k, v in fair.fair_by_key.items()}
    ph = by_name.get(match.home)
    pa = by_name.get(match.away)
    pd = by_name.get("Draw")
    if ph is None or pa is None:
        return None
    if pd is None:
        pd = max(0.0, 1.0 - ph - pa)
    s = ph + pd + pa
    if s <= 0:
        return None
    return ph / s, pd / s, pa / s, fair.vig, fair.n_books


def _market_total(match: Match) -> Optional[Tuple[float, float, float, float, int]]:
    """No-vig consensus over/under as (line, p_over, p_under, vig, n_books), or None.

    Reads the `totals` market we already poll (and were, until now, discarding in
    the per-game calls): the modal line plus its de-vigged over/under split.
    """
    fair = consensus_fair(match.game.markets.get("totals", []))
    if fair is None:
        return None
    over = under = line = None
    for (name, point), p in fair.fair_by_key.items():
        nl = (name or "").lower()
        if nl.startswith("over"):
            over, line = p, point
        elif nl.startswith("under"):
            under = p
            if line is None:
                line = point
    if over is None or under is None or line is None:
        return None
    s = over + under
    if s <= 0:
        return None
    return float(line), over / s, under / s, fair.vig, fair.n_books


def _market_weight(vig: float, n_books: int) -> float:
    """How much to trust the market in the blend (0..MAX_MARKET_WEIGHT)."""
    depth = max(0.0, min(1.0, n_books / 5.0))
    if vig <= 0.04:
        tight = 1.0
    elif vig >= 0.10:
        tight = 0.3
    else:
        tight = 1.0 - 0.7 * ((vig - 0.04) / 0.06)
    return MAX_MARKET_WEIGHT * depth * tight


def _total_line(lh: float, la: float) -> float:
    """Central over/under line: nearest 0.5 to the expected total goals."""
    return round((lh + la) * 2) / 2


# --------------------------------------------------------------- builder ---
def _confidence(model_market_gap: Optional[float], minutes: Optional[float],
                rated: bool, injury_uncertainty: float = 0.0) -> float:
    """Trust weight for a prediction.

    Higher when the model and market agree (small gap), the game isn't imminent,
    and at least one side has a real rating (not the default fallback). Lower when a
    doubtful key player leaves the team sheet genuinely uncertain.
    """
    # Agreement: full trust at a perfect match, decaying to 0.5 at a 25pt gap.
    if model_market_gap is None:
        agree = 0.8  # model-only: no independent confirmation
    else:
        agree = max(0.5, 1.0 - model_market_gap / 0.25)
    if minutes is None:
        time_factor = 0.9
    elif minutes <= 0:
        time_factor = 0.4  # in-play / just kicked off: stale inputs
    elif minutes >= 60:
        time_factor = 1.0
    else:
        time_factor = 0.6 + 0.4 * (minutes / 60.0)
    rated_factor = 1.0 if rated else 0.7
    sheet_factor = 1.0 - 0.5 * max(0.0, min(1.0, injury_uncertainty))
    return max(0.0, min(1.0, agree * time_factor * rated_factor * sheet_factor))


def _argmax(outcomes: List[Tuple[str, float]]) -> Tuple[str, float]:
    return max(outcomes, key=lambda o: o[1])


def predict_match(match: Match, standing_home: dict = None,
                  standing_away: dict = None, home_absences=None,
                  away_absences=None) -> List[Prediction]:
    """All bet-type calls for one upcoming match. Empty for played matches.

    `standing_*` form-adjusts each side's rating (points/GD momentum); `*_absences`
    are injuries.Absence lists that, with attacking/defensive form and host venue,
    are folded into the goal model by `factors.compute`.
    """
    if match.played:
        return []

    rh = ratings.effective_rating(match.home, standing_home)
    ra = ratings.effective_rating(match.away, standing_away)
    rated = (ratings.base_rating(match.home) != ratings.DEFAULT_RATING
             or ratings.base_rating(match.away) != ratings.DEFAULT_RATING)
    mf = factors.compute(match.home, match.away, standing_home, standing_away,
                         home_absences, away_absences)
    lh, la = ratings.lambdas(
        rh, ra, mean_goals=ratings.BASE_GOALS, home_advantage=mf.home_advantage,
        home_attack_adj=mf.home_attack_adj, home_defense_adj=mf.home_defense_adj,
        away_attack_adj=mf.away_attack_adj, away_defense_adj=mf.away_defense_adj)
    grid = score_matrix(lh, la)

    minutes = _minutes_to_start(match.commence_time)

    # --- Result (1X2): blend model with market when present ---
    m_ph, m_pd, m_pa = _result_probs(grid)
    mk = _market_result(match)
    market_prob_pick = None
    gap = None
    if mk is not None:
        k_ph, k_pd, k_pa, vig, n_books = mk
        # Re-fit a market-consistent lambda pair so derived markets also benefit.
        lh, la = fit_lambdas(k_ph, k_pd, k_pa, mean_goals=lh + la)
        w = _market_weight(vig, n_books)
        ph = (1 - w) * m_ph + w * k_ph
        pd = (1 - w) * m_pd + w * k_pd
        pa = (1 - w) * m_pa + w * k_pa
        s = ph + pd + pa
        ph, pd, pa = ph / s, pd / s, pa / s
        grid = score_matrix(lh, la)  # refreshed grid drives total/btts/handicap
        gap = (abs(m_ph - k_ph) + abs(m_pd - k_pd) + abs(m_pa - k_pa)) / 2.0
    else:
        ph, pd, pa = m_ph, m_pd, m_pa

    # --- Totals: fold the market over/under into the goal mean. Until now the
    #     totals odds we pay for were unused in the per-game calls; here they
    #     sharpen the total AND the derived BTTS/handicap, since shifting the mean
    #     (while preserving supremacy lh-la, so the 1X2 blend above is untouched)
    #     reshapes the whole grid. ---
    market_total_line = None
    market_over_prob = market_under_prob = None
    mt = _market_total(match)
    if mt is not None:
        market_total_line, market_over_prob, market_under_prob, t_vig, t_books = mt
        mu_model = lh + la
        mu_mkt = mean_from_total_over(market_total_line, market_over_prob)
        w_t = _market_weight(t_vig, t_books)
        delta = ((1 - w_t) * mu_model + w_t * mu_mkt - mu_model) / 2.0
        lh, la = max(0.15, lh + delta), max(0.15, la + delta)
        grid = score_matrix(lh, la)

    preds: List[Prediction] = []
    suffix = mf.rationale_suffix(match.home, match.away)

    def add(market, pick, prob, model_prob, market_prob, outcomes, rationale):
        preds.append(Prediction(
            match_id=match.game.id, group=match.group,
            commence_time=match.commence_time, home=match.home, away=match.away,
            market=market, pick=pick, prob=prob,
            confidence=_confidence(gap, minutes, rated, mf.injury_uncertainty),
            model_prob=model_prob, market_prob=market_prob,
            outcomes=sorted(outcomes, key=lambda o: o[1], reverse=True),
            rationale=rationale + suffix,
        ))

    # Result
    res_out = [(f"{match.home} win", ph), ("Draw", pd), (f"{match.away} win", pa)]
    res_model = {f"{match.home} win": m_ph, "Draw": m_pd, f"{match.away} win": m_pa}
    pick, prob = _argmax(res_out)
    mkt_p = None
    if mk is not None:
        mkt_p = {f"{match.home} win": mk[0], "Draw": mk[1], f"{match.away} win": mk[2]}[pick]
    add("result", pick, prob, res_model[pick], mkt_p, res_out,
        _result_rationale(match, pick, prob, lh, la))

    # Total goals — priced at the market's quoted line when we have one (a real
    # bettable number), else the model's central line.
    line = market_total_line if market_total_line is not None else _total_line(lh, la)
    p_over = _total_over(grid, line)
    p_under = 1.0 - p_over
    tot_out = [(f"Over {line:g}", p_over), (f"Under {line:g}", p_under)]
    pick, prob = _argmax(tot_out)
    tot_mkt_p = None
    if market_over_prob is not None:
        tot_mkt_p = market_over_prob if pick.lower().startswith("over") else market_under_prob
    add("total", pick, prob, prob, tot_mkt_p, tot_out,
        f"Expected ~{lh + la:.1f} goals ({match.home} {lh:.2f}, "
        f"{match.away} {la:.2f}); {pick.lower()} is the {prob*100:.0f}% side.")

    # Both teams to score
    p_btts = _btts_yes(grid)
    btts_out = [("BTTS: Yes", p_btts), ("BTTS: No", 1.0 - p_btts)]
    pick, prob = _argmax(btts_out)
    add("btts", pick, prob, prob, None, btts_out,
        f"With scoring rates of {lh:.2f} and {la:.2f}, both teams scoring is a "
        f"{p_btts*100:.0f}% chance — {pick}.")

    # Handicap: favorite to cover -1.5 (win by 2+), reported for the stronger side.
    fav_side = "home" if (ph >= pa) else "away"
    fav_name = match.home if fav_side == "home" else match.away
    dog_name = match.away if fav_side == "home" else match.home
    p_fav_minus = _cover(grid, -1.5, fav_side)
    p_dog_plus = 1.0 - p_fav_minus
    hcp_out = [
        (f"{fav_name} -1.5", p_fav_minus),
        (f"{dog_name} +1.5", p_dog_plus),
    ]
    pick, prob = _argmax(hcp_out)
    add("handicap", pick, prob, prob, None, hcp_out,
        f"{fav_name} wins by 2+ goals {p_fav_minus*100:.0f}% of the time; "
        f"the {prob*100:.0f}% call is {pick}.")

    return preds


def _result_rationale(match: Match, pick: str, prob: float, lh: float, la: float) -> str:
    edge = "a clear favorite" if prob >= 0.55 else "a slight edge" if prob >= 0.4 else "a toss-up"
    if pick == "Draw":
        return (f"Evenly matched ({match.home} {lh:.2f} vs "
                f"{match.away} {la:.2f} expected goals) — a draw is the "
                f"{prob*100:.0f}% most-likely result.")
    return (f"{pick.replace(' win','')} is the {prob*100:.0f}% pick — {edge} "
            f"(expected goals {match.home} {lh:.2f}, {match.away} {la:.2f}).")


def predict_all(matches: List[Match],
                standings: dict = None, absences: dict = None) -> List[Prediction]:
    """Predictions for every upcoming match, flattened.

    `standings` is the fixtures.group_standings() map {group: {team: {...}}} used
    to form-adjust ratings; pass None to predict from the strength prior alone.
    `absences` is the injuries.team_absences_map() {canonical_team: [Absence,...]}
    used to injury-adjust the goal model; None disables the injury signal.
    """
    from .fixtures import canonical_team

    def team_abs(name: str):
        if not absences:
            return None
        return absences.get(canonical_team(name) or name) or absences.get(name)

    out: List[Prediction] = []
    for m in matches:
        sh = sa = None
        if standings and m.group in standings:
            g = standings[m.group]
            sh, sa = g.get(m.home), g.get(m.away)
        out.extend(predict_match(m, sh, sa, team_abs(m.home), team_abs(m.away)))
    return out


def rank_predictions(preds: List[Prediction], limit_games: int = 0) -> List[Prediction]:
    """Order calls most-likely-to-hit first, keeping whole games together.

    Calls are sorted by probability (confidence breaks ties); games are then
    ordered by their single strongest call. `limit_games` caps how many *games*
    are kept (all of a kept game's market calls survive) so the per-game cards on
    the site are never truncated mid-game. 0 = no cap.
    """
    ranked = sorted(preds, key=lambda p: (p.prob, p.confidence), reverse=True)
    game_order: List[str] = []
    seen = set()
    for p in ranked:
        if p.match_id not in seen:
            seen.add(p.match_id)
            game_order.append(p.match_id)
    if limit_games and limit_games > 0:
        keep = set(game_order[:limit_games])
        ranked = [p for p in ranked if p.match_id in keep]
    return ranked
