"""Real 2026 FIFA World Cup group map — the metadata the live odds feed lacks.

The Odds API's odds endpoint returns matchups + prices but no group/schedule
context, so the group simulator can't run off it alone. This module supplies the
missing piece: the actual 48-team / 12-group draw plus each team's current group
standings, so live matches can be tagged to their group and the simulator can be
seeded from where the tournament really stands.

We seed the simulation from *standings* (points / goal difference / goals for /
matches played) rather than replaying individual scorelines: the standings are the
exact figures the site shows and the exact starting state the Monte Carlo needs,
and they were cross-checked against the live feed (every fixture the feed returned
falls inside exactly one of these groups). The remaining matches are then modeled
from live market odds by the simulator.

Standings are a snapshot — refresh STANDINGS_2026 and AS_OF as results come in.
"""
from __future__ import annotations

import unicodedata
from typing import Dict, List, Optional, Set, Tuple

from .models import Match

# Snapshot date of STANDINGS_2026 (UTC). Bump this whenever results are updated.
AS_OF = "2026-06-19"
SOURCE = "public group standings, cross-checked against the live odds feed"

# Canonical group standings as of AS_OF: team -> (points, goal_diff, goals_for,
# played). Team names are the canonical display names; the live feed's spellings
# are bridged to these by `canonical_team` via _ALIASES below.
#                           pts  gd  gf  pl
STANDINGS_2026: Dict[str, Dict[str, Tuple[int, int, int, int]]] = {
    "A": {
        "Mexico":        (6,  3, 3, 2),
        "South Korea":   (3,  0, 2, 2),
        "Czechia":       (1, -1, 2, 2),
        "South Africa":  (1, -2, 1, 2),
    },
    "B": {
        "Canada":                (4,  6, 7, 2),
        "Switzerland":           (4,  3, 5, 2),
        "Bosnia & Herzegovina":  (1, -3, 2, 2),
        "Qatar":                 (1, -6, 1, 2),
    },
    "C": {
        "Scotland": (3,  1, 1, 1),
        "Brazil":   (1,  0, 1, 1),
        "Morocco":  (1,  0, 1, 1),
        "Haiti":    (0, -1, 0, 1),
    },
    "D": {
        "United States": (3,  3, 4, 1),
        "Australia":     (3,  2, 2, 1),
        "Turkey":        (0, -2, 0, 1),
        "Paraguay":      (0, -3, 1, 1),
    },
    "E": {
        "Germany":      (3,  6, 7, 1),
        "Ivory Coast":  (3,  1, 1, 1),
        "Ecuador":      (0, -1, 0, 1),
        "Curaçao":      (0, -6, 1, 1),
    },
    "F": {
        "Sweden":       (3,  4, 5, 1),
        "Netherlands":  (1,  0, 2, 1),
        "Japan":        (1,  0, 2, 1),
        "Tunisia":      (0, -4, 1, 1),
    },
    "G": {
        "Belgium":      (1, 0, 1, 1),
        "Egypt":        (1, 0, 1, 1),
        "Iran":         (1, 0, 2, 1),
        "New Zealand":  (1, 0, 2, 1),
    },
    "H": {
        "Spain":         (1, 0, 0, 1),
        "Cape Verde":    (1, 0, 0, 1),
        "Saudi Arabia":  (1, 0, 1, 1),
        "Uruguay":       (1, 0, 1, 1),
    },
    "I": {
        "Norway":   (3,  3, 4, 1),
        "France":   (3,  2, 3, 1),
        "Senegal":  (0, -2, 1, 1),
        "Iraq":     (0, -3, 1, 1),
    },
    "J": {
        "Argentina":  (3,  3, 3, 1),
        "Austria":    (3,  2, 3, 1),
        "Algeria":    (0, -3, 0, 1),
        "Jordan":     (0, -2, 1, 1),
    },
    "K": {
        "Colombia":    (3,  2, 3, 1),
        "Portugal":    (1,  0, 1, 1),
        "DR Congo":    (1,  0, 1, 1),
        "Uzbekistan":  (0, -2, 1, 1),
    },
    "L": {
        "England":  (3,  2, 4, 1),
        "Ghana":    (3,  1, 1, 1),
        "Croatia":  (0, -2, 2, 1),
        "Panama":   (0, -1, 0, 1),
    },
}

# Extra spellings the live feed may use, normalized -> canonical name. The
# canonical names above are registered automatically; only true variants go here.
_ALIASES = {
    "korearepublic": "South Korea",
    "republicofkorea": "South Korea",
    "czechrepublic": "Czechia",
    "bosniaandherzegovina": "Bosnia & Herzegovina",
    "bosnia": "Bosnia & Herzegovina",
    "cotedivoire": "Ivory Coast",
    "unitedstatesofamerica": "United States",
    "usa": "United States",
    "us": "United States",
    "turkiye": "Turkey",
    "caboverde": "Cape Verde",
    "drcongo": "DR Congo",
    "democraticrepublicofthecongo": "DR Congo",
    "democraticrepublicofcongo": "DR Congo",
    "congodr": "DR Congo",
}


def _norm(name: str) -> str:
    """Accent/punctuation/case-insensitive key (e.g. 'Curaçao' -> 'curacao')."""
    decomposed = unicodedata.normalize("NFKD", name or "")
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    return "".join(ch for ch in ascii_only.lower() if ch.isalnum())


def _build_lookup() -> Tuple[Dict[str, str], Dict[str, str]]:
    """(_NORM_TO_CANON, _CANON_TO_GROUP) built once from STANDINGS_2026."""
    to_canon: Dict[str, str] = {}
    to_group: Dict[str, str] = {}
    for group, teams in STANDINGS_2026.items():
        for team in teams:
            to_canon[_norm(team)] = team
            to_group[team] = group
    for norm, canon in _ALIASES.items():
        to_canon[norm] = canon
    return to_canon, to_group


_NORM_TO_CANON, _CANON_TO_GROUP = _build_lookup()


def canonical_team(name: str) -> Optional[str]:
    """Map a feed team name to its canonical name, or None if unknown."""
    return _NORM_TO_CANON.get(_norm(name))


def group_of(name: str) -> Optional[str]:
    """Group letter ('A'..'L') for a team (feed or canonical name), or None."""
    canon = canonical_team(name)
    return _CANON_TO_GROUP.get(canon) if canon else None


def attach_groups(matches: List[Match]) -> List[Match]:
    """Tag live matches with their real group and normalize team names.

    A match is tagged only when both teams resolve to the *same* group (true for
    every group-stage fixture; cross-group knockout matches never share a group).
    Team names are rewritten to canonical so the simulator's standings keys line
    up. Matches whose teams aren't recognized are left untagged (group == "").
    """
    for m in matches:
        ch, ca = canonical_team(m.home), canonical_team(m.away)
        if ch and ca and _CANON_TO_GROUP[ch] == _CANON_TO_GROUP[ca]:
            m.game.home_team = ch
            m.game.away_team = ca
            m.group = _CANON_TO_GROUP[ch]
    return matches


def unknown_teams(matches: List[Match]) -> Set[str]:
    """Feed team names that didn't resolve — surface these to add an alias."""
    missing: Set[str] = set()
    for m in matches:
        for name in (m.home, m.away):
            if name and canonical_team(name) is None:
                missing.add(name)
    return missing


def group_standings() -> Dict[str, Dict[str, Dict[str, int]]]:
    """Standings shaped for `simulate(..., seed_standings=...)`."""
    return {
        group: {
            team: {"points": pts, "gd": gd, "gf": gf, "played": played}
            for team, (pts, gd, gf, played) in teams.items()
        }
        for group, teams in STANDINGS_2026.items()
    }
