"""Expected-value evaluation.

For each outcome offered at the target book (Hard Rock), compare its payout to
the no-vig fair probability from the reference line:

    EV%  = fair_prob * target_decimal_odds - 1      (expressed as a percentage)

A positive EV% means Hard Rock pays more than the bet is "worth" — a value bet.
Confidence down-weights wide (high-vig) reference markets and games starting soon.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from ..config import Config
from ..models import BestBet, Game
from .devig import outcome_key, reference_fair


def _minutes_to_start(commence_time: str) -> Optional[float]:
    try:
        start = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None
    return (start - datetime.now(timezone.utc)).total_seconds() / 60.0


def _confidence(vig: float, minutes: Optional[float], conf_cfg) -> float:
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
        time_factor = 0.8  # unknown start time -> mild discount
    elif minutes <= 0:
        time_factor = 0.0
    elif minutes >= conf_cfg.min_minutes_to_start:
        time_factor = 1.0
    else:
        time_factor = minutes / conf_cfg.min_minutes_to_start

    return max(0.0, min(1.0, vig_factor * time_factor))


def evaluate_game(game: Game, config: Config) -> List[BestBet]:
    """Return all +EV bets at the target book for a single game."""
    bets: List[BestBet] = []
    minutes = _minutes_to_start(game.commence_time)

    for market in config.markets:
        ref = reference_fair(game, market, config.sharp_books, config.target_book)
        if ref is None:
            continue
        target = game.book_in_market(market, config.target_book)
        if target is None:
            continue

        for o in target.outcomes:
            key = outcome_key(o)
            fair_prob = ref.fair_by_key.get(key)
            if fair_prob is None:  # target line has no comparable reference line
                continue
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
                confidence=_confidence(ref.vig, minutes, config.confidence),
                reference_book=ref.book,
                market_vig=ref.vig,
            ))
    return bets
