"""Per-game predictions for US sports — what will happen, not where to bet.

For each game and each market the feed carries (moneyline / spread / total) we
predict the most likely outcome and the probability it hits. The probability is a
blend of two independent views:

  * the **team-strength model** (ratings.py: Elo win prob + expected margin from
    results, scoring averages for the total), and
  * the **market consensus** — every book de-vigged into one no-vig probability
    (devig.py). No single book is privileged and no price is "shopped"; the
    consensus is just the crowd's prediction, folded in as one more signal.

Model-first: when the model has seen enough games it leads, with the market
capped at `max_market_weight`. Before the model warms up (cold start) the
consensus carries the prediction on its own.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from ..config import Config
from ..models import Game, Prediction
from .devig import reference_fair
from .ratings import TeamModel, norm_cdf, sigma_margin, sigma_total


def _minutes_to_start(commence_time: str) -> Optional[float]:
    try:
        start = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None
    return (start - datetime.now(timezone.utc)).total_seconds() / 60.0


def _market_weight(vig: float, max_w: float) -> float:
    """How much the consensus pulls the blend (0..max_w), by market tightness."""
    if vig <= 0.03:
        tight = 1.0
    elif vig >= 0.08:
        tight = 0.4
    else:
        tight = 1.0 - 0.6 * ((vig - 0.03) / 0.05)
    return max_w * tight


def _confidence(model_prob: Optional[float], market_prob: float, vig: float,
                minutes: Optional[float]) -> float:
    """Trust weight: model/market agreement, market tightness, time to start."""
    if model_prob is None:
        agree = 0.7  # market-only: no independent confirmation
    else:
        agree = max(0.5, 1.0 - abs(model_prob - market_prob) / 0.25)
    if vig <= 0.03:
        vig_factor = 1.0
    elif vig >= 0.08:
        vig_factor = 0.5
    else:
        vig_factor = 1.0 - 0.5 * ((vig - 0.03) / 0.05)
    if minutes is None:
        time_factor = 0.85
    elif minutes <= 0:
        time_factor = 0.3
    elif minutes >= 60:
        time_factor = 1.0
    else:
        time_factor = 0.6 + 0.4 * (minutes / 60.0)
    return max(0.0, min(1.0, agree * vig_factor * time_factor))


def _blend(model_p: Optional[float], market_p: float, vig: float, max_w: float) -> float:
    if model_p is None:
        return market_p
    w = _market_weight(vig, max_w)
    return (1.0 - w) * model_p + w * market_p


def _argmax(outcomes: List[Tuple[str, float]]) -> Tuple[str, float]:
    return max(outcomes, key=lambda o: o[1])


def predict_game(game: Game, model: TeamModel, config: Config) -> List[Prediction]:
    """All market predictions for one game."""
    st = config.strategy
    minutes = _minutes_to_start(game.commence_time)
    sport, home, away = game.sport_key, game.home_team, game.away_team
    preds: List[Prediction] = []

    def add(market, pick, selection, point, prob, model_p, market_p, outcomes, rationale):
        preds.append(Prediction(
            game_id=game.id, sport_key=sport, sport_title=game.sport_title,
            commence_time=game.commence_time, home_team=home, away_team=away,
            market=market, pick=pick, selection=selection, point=point, prob=prob,
            confidence=_confidence(model_p, market_p, _vig, minutes),
            model_prob=model_p, market_prob=market_p,
            outcomes=sorted(outcomes, key=lambda o: o[1], reverse=True),
            rationale=rationale,
        ))

    for market in config.markets:
        ref = reference_fair(game, market, [], "", method=st.devig_method,
                             book_weights=st.book_weights)
        if ref is None:
            continue
        _vig = ref.vig
        fair = ref.fair_by_key

        if market == "h2h":
            ph_mkt = fair.get((home, None))
            pa_mkt = fair.get((away, None))
            if ph_mkt is None or pa_mkt is None:
                continue
            s = ph_mkt + pa_mkt
            ph_mkt /= s
            ph_model = model.p_home_win(sport, home, away)
            ph = _blend(ph_model, ph_mkt, _vig, st.max_market_weight)
            outs = [(f"{home} ML", ph), (f"{away} ML", 1.0 - ph)]
            pick, prob = _argmax(outs)
            pick_is_home = pick.startswith(home)
            add("h2h", pick, home if pick_is_home else away, None, prob,
                None if ph_model is None else (ph_model if pick_is_home else 1.0 - ph_model),
                ph_mkt if pick_is_home else 1.0 - ph_mkt, outs,
                _h2h_rationale(home, away, pick, prob, ph_model))

        elif market == "spreads":
            hk = next((k for k in fair if k[0] == home and k[1] is not None), None)
            ak = next((k for k in fair if k[0] == away and k[1] is not None), None)
            if hk is None or ak is None:
                continue
            home_pt = hk[1]
            ph_mkt = fair[hk]
            em = model.expected_margin(sport, home, away)
            ph_model = None if em is None else norm_cdf((em + home_pt) / sigma_margin(sport))
            ph = _blend(ph_model, ph_mkt, _vig, st.max_market_weight)
            outs = [(f"{home} {home_pt:+g}", ph), (f"{away} {ak[1]:+g}", 1.0 - ph)]
            pick, prob = _argmax(outs)
            pick_is_home = pick.startswith(home)
            add("spreads", pick, home if pick_is_home else away,
                home_pt if pick_is_home else ak[1], prob,
                None if ph_model is None else (ph_model if pick_is_home else 1.0 - ph_model),
                ph_mkt if pick_is_home else 1.0 - ph_mkt, outs,
                _spread_rationale(pick, prob, em, ph_model))

        elif market == "totals":
            ok = next((k for k in fair if k[0] == "Over" and k[1] is not None), None)
            if ok is None:
                continue
            line = ok[1]
            po_mkt = fair[ok]
            et = model.expected_total(sport, home, away)
            po_model = None if et is None else 1.0 - norm_cdf((line - et) / sigma_total(sport))
            po = _blend(po_model, po_mkt, _vig, st.max_market_weight)
            outs = [(f"Over {line:g}", po), (f"Under {line:g}", 1.0 - po)]
            pick, prob = _argmax(outs)
            pick_is_over = pick.startswith("Over")
            add("totals", pick, "Over" if pick_is_over else "Under", line, prob,
                None if po_model is None else (po_model if pick_is_over else 1.0 - po_model),
                po_mkt if pick_is_over else 1.0 - po_mkt, outs,
                _total_rationale(pick, prob, et, po_model))

    return preds


# ----------------------------------------------------------------- rationale ---
def _conf_phrase(prob: float) -> str:
    return "a clear call" if prob >= 0.6 else "a lean" if prob >= 0.52 else "a coin-flip"


def _h2h_rationale(home, away, pick, prob, model_p) -> str:
    team = pick.replace(" ML", "")
    src = (f"Our model and the market agree" if model_p is not None
           else "The market consensus")
    return (f"{src} makes {team} the {prob*100:.0f}% pick to win — {_conf_phrase(prob)}.")


def _spread_rationale(pick, prob, em, model_p) -> str:
    if model_p is not None and em is not None:
        return (f"Model expects a {abs(em):.1f}-point margin; {pick} is the "
                f"{prob*100:.0f}% side to cover — {_conf_phrase(prob)}.")
    return f"Consensus makes {pick} the {prob*100:.0f}% side to cover."


def _total_rationale(pick, prob, et, model_p) -> str:
    if model_p is not None and et is not None:
        return (f"Model projects ~{et:.1f} combined points; {pick} is the "
                f"{prob*100:.0f}% call — {_conf_phrase(prob)}.")
    return f"Consensus makes {pick} the {prob*100:.0f}% call."


def predict_games(games: List[Game], model: TeamModel, config: Config) -> List[Prediction]:
    out: List[Prediction] = []
    for g in games:
        out.extend(predict_game(g, model, config))
    return out
