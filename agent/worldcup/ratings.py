"""Team strength ratings — the prior the prediction engine is built on.

These are Elo-style ratings (1500 = average international side; ~2100 = the very
best). They are a *prior*, not the final word: the prediction engine adjusts a
team's effective rating by its live tournament form (standings) before modeling a
match, and blends the resulting model probability with the market when odds exist.

Ratings cover the real 2026 field (keyed by the canonical names in fixtures.py)
plus the mock provider's teams, so a single table feeds both the live and offline
paths. Unknown teams fall back to DEFAULT_RATING rather than breaking a run.

Refine these as real results accumulate — calibration (engine/calibration.py) is
the honest check on whether the priors are any good.
"""
from __future__ import annotations

import unicodedata
from typing import Dict, Tuple

DEFAULT_RATING = 1700.0   # a mid-tier side we have no specific rating for
HOME_ADVANTAGE = 0.20     # goal bump applied to the nominal "home" side
BASE_GOALS = 2.65         # baseline combined goals for an evenly matched game
RATING_SCALE = 150.0      # Elo points worth ~1 goal of supremacy

# Canonical team -> rating. Names match fixtures.STANDINGS_2026 spellings so the
# live feed (bridged via fixtures.canonical_team) lines up; mock-only names are
# included too. Order is irrelevant.
_RATINGS: Dict[str, float] = {
    # Top tier
    "Argentina": 2105, "France": 2080, "Spain": 2070, "England": 2055,
    "Brazil": 2050, "Portugal": 2035, "Netherlands": 2010, "Germany": 2000,
    # Strong
    "Italy": 1985, "Belgium": 1975, "Croatia": 1955, "Uruguay": 1945,
    "Colombia": 1935, "Morocco": 1930, "Norway": 1920, "United States": 1915,
    "Mexico": 1905, "Japan": 1900, "Senegal": 1890, "Switzerland": 1885,
    "Denmark": 1880, "South Korea": 1870, "Ecuador": 1860, "Austria": 1855,
    "Ukraine": 1845, "Turkey": 1840, "Australia": 1835, "Canada": 1830,
    # Mid
    "Nigeria": 1825, "Serbia": 1820, "Scotland": 1820, "Czechia": 1818,
    "Egypt": 1815, "Poland": 1810, "Peru": 1800, "Sweden": 1795,
    "Wales": 1785, "Ghana": 1780, "Bosnia & Herzegovina": 1780, "Cameroon": 1775,
    "Ivory Coast": 1770, "DR Congo": 1760, "Tunisia": 1760, "Costa Rica": 1750,
    "Qatar": 1740, "Saudi Arabia": 1735, "South Africa": 1732, "Iran": 1730,
    "Algeria": 1725, "Paraguay": 1720, "Panama": 1700, "Iraq": 1700,
    # Lower
    "Jamaica": 1690, "Cape Verde": 1680, "New Zealand": 1640, "Curaçao": 1640,
    "Haiti": 1635, "Jordan": 1620, "Uzbekistan": 1610,
}

# Mock-provider / feed spellings that aren't the canonical key above.
_ALIASES = {
    "korearepublic": "South Korea",
    "republicofkorea": "South Korea",
    "usa": "United States",
    "us": "United States",
    "unitedstatesofamerica": "United States",
    "cotedivoire": "Ivory Coast",
    "bosniaandherzegovina": "Bosnia & Herzegovina",
    "bosnia": "Bosnia & Herzegovina",
    "czechrepublic": "Czechia",
    "caboverde": "Cape Verde",
    "drcongo": "DR Congo",
    "turkiye": "Turkey",
}


def _norm(name: str) -> str:
    """Accent/punctuation/case-insensitive key (e.g. 'Curaçao' -> 'curacao')."""
    decomposed = unicodedata.normalize("NFKD", name or "")
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    return "".join(ch for ch in ascii_only.lower() if ch.isalnum())


_NORM_TO_CANON = {_norm(name): name for name in _RATINGS}
_NORM_TO_CANON.update(_ALIASES)


def base_rating(name: str) -> float:
    """The static strength prior for a team (DEFAULT_RATING if unknown)."""
    canon = _NORM_TO_CANON.get(_norm(name))
    return _RATINGS.get(canon, DEFAULT_RATING)


def form_delta(standing: Dict[str, int]) -> float:
    """A modest rating nudge from live tournament form, in Elo points.

    Uses points-per-game (above/below the 1.0 average of a random result) and
    goal-difference-per-game. Deliberately small: a 1-2 game sample shouldn't
    overwhelm the strength prior, only tilt it. `standing` is one team's
    {points, gd, gf, played} dict (as produced by fixtures.group_standings()).
    """
    played = standing.get("played", 0)
    if not played:
        return 0.0
    ppg = standing.get("points", 0) / played           # 0..3
    gdpg = standing.get("gd", 0) / played
    # ~+25 Elo per point-per-game above average, ~+15 per goal of GD/game, capped.
    delta = 25.0 * (ppg - 1.0) + 15.0 * gdpg
    return max(-90.0, min(90.0, delta))


def effective_rating(name: str, standing: Dict[str, int] = None) -> float:
    """Strength rating for a match: results-adjusted Elo, else prior + live form.

    Once a team has a settled result, `elo.py` has folded the actual outcome into a
    self-correcting rating; that already integrates form, so we use it directly and
    do *not* also add the standings nudge (which would double-count the same games).
    Before any result settles we fall back to the static prior plus a small
    form_delta from the live table.
    """
    from . import elo  # lazy: elo imports ratings, so avoid a load-time cycle

    rated = elo.rating_for(name)
    if rated is not None:
        return rated
    r = base_rating(name)
    if standing:
        r += form_delta(standing)
    return r


def lambdas(
    rating_home: float,
    rating_away: float,
    mean_goals: float = BASE_GOALS,
    home_advantage: float = HOME_ADVANTAGE,
    *,
    home_attack_adj: float = 0.0,
    home_defense_adj: float = 0.0,
    away_attack_adj: float = 0.0,
    away_defense_adj: float = 0.0,
) -> Tuple[float, float]:
    """Goal expectancies (lambda_home, lambda_away) from two ratings.

    supremacy = (R_home - R_away)/RATING_SCALE + home_advantage, split around the
    baseline goal total. The single source of the rating->goals mapping (the mock
    provider and the simulator's no-market fallback both use this).

    The four ``*_adj`` arguments are goal-unit tilts (see factors.py) that move a
    single side's scoring without touching overall supremacy — so an injury to a
    striker lowers only that team's goals, while an injury to a defense raises only
    the *opponent's*. A positive ``defense_adj`` is a stronger defense, so it is
    *subtracted* from the opponent's rate. Both rates floor at 0.15.
    """
    supremacy = (rating_home - rating_away) / RATING_SCALE + home_advantage
    lh = (mean_goals + supremacy) / 2.0 + home_attack_adj - away_defense_adj
    la = (mean_goals - supremacy) / 2.0 + away_attack_adj - home_defense_adj
    return max(0.15, lh), max(0.15, la)
