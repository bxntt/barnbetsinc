"""Expected-value evaluation.

For each outcome offered at the target book (Hard Rock), compare its payout to
the no-vig fair probability from the reference line:

    EV%  = fair_prob * target_decimal_odds - 1      (expressed as a percentage)

A positive EV% means Hard Rock pays more than the bet is "worth" — a value bet.
Fair probabilities come from the configured de-vig method (power by default) on the
sharpest reference, with a weighted consensus fallback. When Hard Rock's spread/total
sits at a different number than the reference, the fair prob is interpolated.

Confidence multiplies several quality signals, each in [0, 1]:
  * vig_factor      — tight reference markets are trusted; wide ones discounted.
  * time_factor     — games starting very soon are discounted.
  * agree_factor    — de-vig methods agreeing raises trust (they diverge on longshots).
  * longshot_factor — heavy underdogs are discounted (favorite-longshot bias).
  * interp_factor   — interpolated lines are discounted by how far they were shifted.

Fractional-Kelly sizing is attached for ranking and display.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from ..config import Config, StrategyConfig
from ..models import BestBet, Game
from .devig import outcome_key, reference_fair
from .interpolate import interp_fair
from .kelly import kelly_fraction, kelly_stake


def _minutes_to_start(commence_time: str) -> Optional[float]:
    try:
        start = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None
    return (start - datetime.now(timezone.utc)).total_seconds() / 60.0


def _confidence(
    vig: float,
    minutes: Optional[float],
    conf_cfg,
    spread: float,
    fair_prob: float,
    interpolated: bool,
    reach: float,
    st: StrategyConfig,
) -> float:
    # Vig factor: tight reference markets (<=3% hold) get full trust; it decays
    # to 0.3 by the max-trusted-vig threshold.
    if vig <= 0.03:
        vig_factor = 1.0
    elif vig >= conf_cfg.max_trusted_vig:
        vig_factor = 0.3
    else:
        span = conf_cfg.max_trusted_vig - 0.03
        vig_factor = 1.0 - 0.7 * ((vig - 0.03) / span)

    # Time factor: down-weight games starting inside the minimum window.
    if minutes is None:
        time_factor = 0.8
    elif minutes <= 0:
        time_factor = 0.0
    elif minutes >= conf_cfg.min_minutes_to_start:
        time_factor = 1.0
    else:
        time_factor = minutes / conf_cfg.min_minutes_to_start

    # Method-agreement factor: de-vig methods agreeing -> trust; diverging -> discount.
    if spread <= 0.005:
        agree_factor = 1.0
    elif spread >= st.method_spread_tol:
        agree_factor = 0.4
    else:
        agree_factor = 1.0 - 0.6 * ((spread - 0.005) / (st.method_spread_tol - 0.005))

    # Longshot factor: discount heavy underdogs (vig is loaded onto longshots).
    if fair_prob >= st.longshot_prob:
        longshot_factor = 1.0
    else:
        longshot_factor = st.longshot_penalty + (1.0 - st.longshot_penalty) * (
            fair_prob / st.longshot_prob
        )

    # Interpolation factor: trust shrinks with how far the line was shifted.
    if interpolated and st.interp_max_reach > 0:
        interp_factor = 1.0 - st.interp_conf_penalty * min(reach / st.interp_max_reach, 1.0)
    else:
        interp_factor = 1.0

    score = vig_factor * time_factor * agree_factor * longshot_factor * interp_factor
    return max(0.0, min(1.0, score))


def _interp_for(ref, game: Game, market: str, o, st: StrategyConfig):
    """Return (fair_prob, spread, reach) by shifting the nearest same-side
    reference line to this outcome's point, or None if not possible."""
    if not st.interpolate or market not in ("spreads", "totals") or o.point is None:
        return None
    cand = [
        (pt, p) for (nm, pt), p in ref.fair_by_key.items()
        if nm == o.name and pt is not None
    ]
    if not cand:
        return None
    target_pt = round(o.point, 1)
    ref_pt, ref_p = min(cand, key=lambda c: abs(c[0] - target_pt))
    res = interp_fair(market, game.sport_key, o.name, ref_pt, ref_p, target_pt, st.interp_max_reach)
    if res is None:
        return None
    fair_prob, reach = res
    return fair_prob, ref.spread_by_key.get((o.name, ref_pt), 0.0), reach


def evaluate_game(game: Game, config: Config) -> List[BestBet]:
    """Return all +EV bets at the target book for a single game."""
    bets: List[BestBet] = []
    st = config.strategy
    minutes = _minutes_to_start(game.commence_time)

    for market in config.markets:
        ref = reference_fair(
            game, market, config.sharp_books, config.target_book,
            method=st.devig_method, book_weights=st.book_weights,
        )
        if ref is None:
            continue
        target = game.book_in_market(market, config.target_book)
        if target is None:
            continue

        for o in target.outcomes:
            key = outcome_key(o)
            fair_prob = ref.fair_by_key.get(key)
            spread = ref.spread_by_key.get(key, 0.0)
            interpolated = False
            reach = 0.0

            if fair_prob is None:  # no exact line -> try interpolation
                interp = _interp_for(ref, game, market, o, st)
                if interp is None:
                    continue
                fair_prob, spread, reach = interp
                interpolated = True

            ev_pct = (fair_prob * o.decimal - 1.0) * 100.0
            if ev_pct < config.min_ev_pct:
                continue

            bets.append(BestBet(
                game_id=game.id,
                sport_key=game.sport_key,
                sport_title=game.sport_title,
                commence_time=game.commence_time,
                home_team=game.home_team,
                away_team=game.away_team,
                market=market,
                selection=o.name,
                point=o.point,
                target_book=config.target_book,
                price_american=o.price_american,
                fair_prob=fair_prob,
                ev_pct=ev_pct,
                confidence=_confidence(
                    ref.vig, minutes, config.confidence, spread, fair_prob,
                    interpolated, reach, st,
                ),
                reference_book=ref.book,
                market_vig=ref.vig,
                method_spread=spread,
                interpolated=interpolated,
                reach=reach,
                longshot=fair_prob < st.longshot_prob,
                kelly_frac=kelly_fraction(fair_prob, o.decimal),
                kelly_pct=kelly_stake(fair_prob, o.decimal, st.kelly_fraction, st.kelly_cap) * 100.0,
            ))
    return bets
