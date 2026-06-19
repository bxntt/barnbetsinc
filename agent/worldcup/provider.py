"""World Cup match providers.

`mock` (default) generates a full, deterministic 2026 field: 48 teams seeded into
12 groups, each group a 6-match round-robin. Matchday 1 is already played (real
scorelines sampled from each match's true model); matchdays 2-3 are upcoming with
multi-book 1X2 + totals odds. Per-book noise + vig make the cross-book value finder
and the simulator both exercise real data with no API key.

`the_odds_api` fetches live soccer odds (1X2 + totals) for the value finder. The
odds endpoint carries no group/schedule metadata, so the pipeline tags live matches
to the real 2026 draw via `fixtures.py` (group + current standings) and seeds the
simulator from there — the live odds then drive every remaining match.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from ..models import BookOdds, Game, Outcome
from ..odds_math import decimal_to_american
from .models import Match
from .poisson import outcome_probs

# ---------------------------------------------------------------- mock field ---

# 48 nations with rough strength ratings (Elo-ish). Order is irrelevant; the
# snake draft below spreads strong sides across the 12 groups.
_TEAMS = [
    ("Argentina", 2105), ("France", 2080), ("Spain", 2070), ("England", 2055),
    ("Brazil", 2050), ("Portugal", 2035), ("Netherlands", 2010), ("Germany", 2000),
    ("Italy", 1985), ("Belgium", 1975), ("Croatia", 1955), ("Uruguay", 1945),
    ("Colombia", 1935), ("Morocco", 1930), ("USA", 1915), ("Mexico", 1905),
    ("Japan", 1900), ("Senegal", 1890), ("Switzerland", 1885), ("Denmark", 1880),
    ("Korea Republic", 1870), ("Ecuador", 1860), ("Austria", 1855), ("Ukraine", 1845),
    ("Australia", 1835), ("Canada", 1830), ("Nigeria", 1825), ("Serbia", 1820),
    ("Egypt", 1815), ("Poland", 1810), ("Peru", 1800), ("Sweden", 1795),
    ("Wales", 1785), ("Ghana", 1780), ("Cameroon", 1775), ("Ivory Coast", 1770),
    ("Tunisia", 1760), ("Costa Rica", 1750), ("Qatar", 1740), ("Saudi Arabia", 1735),
    ("Iran", 1730), ("Algeria", 1725), ("Paraguay", 1720), ("Panama", 1700),
    ("Jamaica", 1690), ("New Zealand", 1640), ("Jordan", 1620), ("Uzbekistan", 1610),
]

_BOOKS = ["pinnacle", "bet365", "draftkings", "fanduel", "betmgm", "williamhill"]
_GROUPS = [chr(ord("A") + i) for i in range(12)]  # A..L
# Round-robin schedule for 4 teams (indices), one pair per matchday slot.
_FIXTURES = [
    (1, (0, 1), (2, 3)),   # matchday 1
    (2, (0, 2), (3, 1)),   # matchday 2
    (3, (3, 0), (1, 2)),   # matchday 3
]
_HOME_ADV = 0.20           # goal bump applied to the nominal "home" side
_BASE_GOALS = 2.65         # baseline total goals for an even match


def _lambdas(rating_a: float, rating_b: float) -> tuple:
    """Goal expectancies for A vs B from their ratings (A is nominal home).

    Delegates to ratings.lambdas so the rating->goals mapping has one source
    shared with the live prediction engine and the simulator fallback.
    """
    from . import ratings
    return ratings.lambdas(rating_a, rating_b,
                           mean_goals=_BASE_GOALS, home_advantage=_HOME_ADV)


def _prob_to_american(p: float) -> int:
    """Fair probability -> American odds, clamped to a sane book range."""
    p = min(0.97, max(0.005, p))
    return decimal_to_american(1.0 / p)


def _quote_book(fair: dict, rng: random.Random) -> List[Outcome]:
    """One book's priced outcomes: nudge the fair opinion, add vig, go American.

    `fair` maps (name, point) -> fair probability for the whole market.
    """
    opinion = {k: p * math.exp(rng.uniform(-0.06, 0.06)) for k, p in fair.items()}
    norm = sum(opinion.values())
    vig = rng.uniform(0.035, 0.07)
    outs = []
    for (name, point), p in opinion.items():
        implied = (p / norm) * (1.0 + vig)
        outs.append(Outcome(name=name, price_american=_prob_to_american(implied), point=point))
    return outs


def _market_books(fair: dict, rng: random.Random, n_books: int) -> List[BookOdds]:
    books = []
    for b in _BOOKS[:n_books]:
        books.append(BookOdds(book=b, outcomes=_quote_book(fair, rng),
                              last_update=datetime.now(timezone.utc).isoformat()))
    return books


def _make_match(group: str, matchday: int, home: str, away: str,
                rh: float, ra: float, rng: random.Random,
                commence: str, played: bool) -> Match:
    lh, la = _lambdas(rh, ra)
    ph, pd, pa = outcome_probs(lh, la)
    total_line = round((lh + la) * 2) / 2  # nearest 0.5
    # P(total > line) under independent Poisson, approximated from the means.
    p_over = _poisson_over(lh + la, total_line)
    p_under = 1.0 - p_over

    h2h_fair = {(home, None): ph, ("Draw", None): pd, (away, None): pa}
    totals_fair = {("Over", total_line): p_over, ("Under", total_line): p_under}

    game = Game(
        id=f"wc-{group}-{matchday}-{_slug(home)}-{_slug(away)}",
        sport_key="soccer_fifa_world_cup",
        sport_title="World Cup",
        commence_time=commence,
        home_team=home,
        away_team=away,
        markets={
            "h2h": _market_books(h2h_fair, rng, n_books=len(_BOOKS)),
            "totals": _market_books(totals_fair, rng, n_books=4),
        },
    )

    m = Match(game=game, group=group, matchday=matchday)
    if played:
        # Sample a real scoreline from the true model and freeze it.
        m.played = True
        m.home_goals = _sample_poisson(lh, rng)
        m.away_goals = _sample_poisson(la, rng)
    return m


def _poisson_over(mean_total: float, line: float) -> float:
    """P(combined goals > line) for a single Poisson(mean_total)."""
    k_max = math.floor(line)
    cum = 0.0
    for k in range(k_max + 1):
        cum += math.exp(-mean_total) * mean_total ** k / math.factorial(k)
    return max(0.01, min(0.99, 1.0 - cum))


def _sample_poisson(lam: float, rng: random.Random) -> int:
    """Knuth Poisson sampler (lambda is small here)."""
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


def _slug(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _seed_groups() -> List[List[tuple]]:
    """Snake-draft the rating-sorted teams into 12 groups of 4."""
    ranked = sorted(_TEAMS, key=lambda t: t[1], reverse=True)
    groups: List[List[tuple]] = [[] for _ in range(12)]
    for i, team in enumerate(ranked):
        rnd = i // 12
        col = i % 12
        idx = col if rnd % 2 == 0 else (11 - col)  # serpentine
        groups[idx].append(team)
    return groups


def mock_matches(seed: int = 7) -> List[Match]:
    """A full, deterministic 12-group slate: MD1 played, MD2-3 upcoming."""
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    seeded = _seed_groups()
    matches: List[Match] = []

    for gi, group in enumerate(_GROUPS):
        members = seeded[gi]  # 4 (name, rating) tuples
        for matchday, p1, p2 in _FIXTURES:
            played = matchday == 1
            for (hi, ai) in (p1, p2):
                home, rh = members[hi]
                away, ra = members[ai]
                if played:
                    commence = (now - timedelta(days=3, hours=gi % 5)).isoformat()
                else:
                    commence = (now + timedelta(days=(matchday - 2) * 3 + 1,
                                                hours=(gi % 6) * 3)).isoformat()
                matches.append(_make_match(group, matchday, home, away, rh, ra,
                                           rng, commence, played))
    return matches


# ----------------------------------------------------------- the_odds_api ----

_SOCCER_BASE = "https://api.the-odds-api.com/v4/sports/{sport}/odds"
_SOCCER_EVENTS = "https://api.the-odds-api.com/v4/sports/{sport}/events"


def the_odds_api_events(api_key: str, competition: str):
    """FREE schedule lookup: kickoff times + remaining credit balance.

    The /events endpoint costs 0 credits, so this can run on every cron tick to
    decide whether a paid odds poll is worth it. Returns (commence_times, remaining).
    """
    import requests

    from ..budget import remaining_from_response

    if not api_key:
        return [], None
    params = {"apiKey": api_key, "dateFormat": "iso"}
    resp = requests.get(_SOCCER_EVENTS.format(sport=competition), params=params, timeout=15)
    if resp.status_code == 422:
        return [], remaining_from_response(resp)
    resp.raise_for_status()
    times = [ev.get("commence_time", "") for ev in resp.json() if ev.get("commence_time")]
    return times, remaining_from_response(resp)


def the_odds_api_schedule(api_key: str, competition: str):
    """FREE schedule WITH matchups: Match objects (teams + kickoff, no odds).

    The /events endpoint costs 0 credits and returns home_team / away_team, so we
    can predict every upcoming match from our model at zero credit cost. Paid odds
    polls (the_odds_api_matches_meta) only *sharpen* these via the market blend.
    Returns (matches, remaining).
    """
    import requests

    from ..budget import remaining_from_response

    if not api_key:
        return [], None
    params = {"apiKey": api_key, "dateFormat": "iso"}
    resp = requests.get(_SOCCER_EVENTS.format(sport=competition), params=params, timeout=15)
    if resp.status_code == 422:
        return [], remaining_from_response(resp)
    resp.raise_for_status()
    matches = []
    for ev in resp.json():
        home, away = ev.get("home_team", ""), ev.get("away_team", "")
        if not home or not away:
            continue
        game = Game(
            id=ev.get("id", f"wc-{_slug(home)}-{_slug(away)}"),
            sport_key=ev.get("sport_key", competition),
            sport_title="World Cup",
            commence_time=ev.get("commence_time", ""),
            home_team=home,
            away_team=away,
            markets={},  # no odds from /events — model-only until a paid poll
        )
        matches.append(Match(game=game, group="", matchday=0))
    return matches, remaining_from_response(resp)


def the_odds_api_matches_meta(api_key: str, competition: str, markets: List[str],
                              regions: str = "us,uk,eu"):
    """Live soccer odds for the value finder. Returns (matches, remaining)."""
    import requests

    from ..budget import remaining_from_response
    from ..providers.the_odds_api import TheOddsApiProvider

    if not api_key:
        raise RuntimeError("THE_ODDS_API_KEY is not set. Use the mock provider instead.")
    params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": ",".join(markets),
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    resp = requests.get(_SOCCER_BASE.format(sport=competition), params=params, timeout=15)
    if resp.status_code == 422:
        return [], remaining_from_response(resp)
    resp.raise_for_status()
    matches = []
    for ev in resp.json():
        game = TheOddsApiProvider._parse_event(ev)
        # Odds feed has no group label; the pipeline tags it via fixtures.py.
        matches.append(Match(game=game, group="", matchday=0))
    return matches, remaining_from_response(resp)


def the_odds_api_matches(api_key: str, competition: str, markets: List[str],
                         regions: str = "us,uk,eu") -> List[Match]:
    """Live soccer odds for the value finder (no group metadata available)."""
    matches, _ = the_odds_api_matches_meta(api_key, competition, markets, regions)
    return matches


def get_matches(provider: str, *, the_odds_api_key: Optional[str] = None,
                competition: str = "soccer_fifa_world_cup",
                markets: Optional[List[str]] = None,
                seed: int = 7) -> List[Match]:
    """Factory: return World Cup matches from the configured provider."""
    name = (provider or "mock").lower()
    if name == "mock":
        return mock_matches(seed=seed)
    if name == "the_odds_api":
        return the_odds_api_matches(the_odds_api_key or "", competition,
                                    markets or ["h2h", "totals"])
    raise ValueError(f"Unknown World Cup provider: {provider!r}")
