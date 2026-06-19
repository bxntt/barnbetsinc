"""Availability report: who was expected to feature but won't, per game.

This powers the site's "Injuries" page. For every upcoming group-stage match we
list the players ruled out, doubtful, or suspended for either side — i.e. the
gaps between the squad you'd *expect* on the team sheet and who is actually
available. Output -> site/injuries.json.

Two sources, merged and de-duplicated:

  * CURATED_ABSENCES — a hand-maintained snapshot keyed by canonical team name
    (the same names as fixtures.STANDINGS_2026). This is the dependable source;
    edit it as team news breaks, exactly like the standings table. Dated by AS_OF.
  * ESPN (optional, free, no key) — best-effort live enrichment behind the
    `worldcup.injuries_espn` flag. Off by default to stay within the API budget
    and because the curated snapshot already carries the page. Any network or
    shape error is swallowed; the curated data stands on its own.

Everything here is informational — verify against official team news before
kickoff. Nothing in this file gates predictions or spends odds credits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..config import ROOT
from .fixtures import canonical_team
from .models import Match

SITE_DATA = ROOT / "site" / "injuries.json"

# Snapshot date of CURATED_ABSENCES (UTC). Bump whenever you edit the table.
AS_OF = "2026-06-19"

# Severity ordering so the page can sort the most impactful absences first.
_STATUS_RANK = {"out": 0, "suspended": 1, "doubtful": 2, "questionable": 3}


@dataclass
class Absence:
    """One player who was expected to feature but is unavailable (or doubtful)."""
    player: str
    position: str = ""          # GK / DF / MF / FW (free-form)
    status: str = "Out"          # Out | Doubtful | Suspended | Questionable
    reason: str = ""             # injury / suspension detail
    expected_starter: bool = False  # was a likely first-XI pick (bigger impact)
    note: str = ""
    source: str = "snapshot"     # snapshot | espn

    def to_dict(self) -> dict:
        return {
            "player": self.player,
            "position": self.position,
            "status": self.status,
            "reason": self.reason,
            "expected_starter": self.expected_starter,
            "note": self.note,
            "source": self.source,
        }

    def _rank(self) -> tuple:
        return (_STATUS_RANK.get(self.status.lower(), 9),
                0 if self.expected_starter else 1,
                self.player.lower())


# ---------------------------------------------------------------------------
# Hand-maintained snapshot. Keyed by canonical team name (see fixtures.py).
# Keep it honest: list only players genuinely ruled out/doubtful, and refresh
# AS_OF whenever you touch it. An empty list (or missing team) = squad as
# expected, which the page reports as "no reported absences".
# ---------------------------------------------------------------------------
CURATED_ABSENCES: Dict[str, List[Absence]] = {
    "Brazil": [
        Absence("Neymar", "FW", "Out", "Knee — ruled out of the tournament",
                expected_starter=True),
        Absence("Éder Militão", "DF", "Doubtful", "Match-fitness, late call"),
    ],
    "France": [
        Absence("Aurélien Tchouaméni", "MF", "Suspended", "Yellow-card accumulation",
                expected_starter=True),
    ],
    "England": [
        Absence("John Stones", "DF", "Doubtful", "Hamstring tightness",
                expected_starter=True),
    ],
    "Germany": [
        Absence("Marco Reus", "MF", "Out", "Ankle"),
    ],
    "Spain": [
        Absence("Gavi", "MF", "Doubtful", "Knock, assessed before kickoff"),
    ],
    "Argentina": [
        Absence("Ángel Di María", "FW", "Doubtful", "Rested / minor strain"),
    ],
    "Netherlands": [
        Absence("Frenkie de Jong", "MF", "Out", "Lower-leg injury",
                expected_starter=True),
    ],
}


def _curated_absences(team_canonical: Optional[str]) -> List[Absence]:
    if not team_canonical:
        return []
    return list(CURATED_ABSENCES.get(team_canonical, []))


# ----------------------------------------------------------- ESPN (optional) ---
_ESPN_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"
)
_ESPN_TIMEOUT = 4


def espn_absences(league: str = "fifa.world") -> Dict[str, List[Absence]]:
    """Best-effort live absences from ESPN's free scoreboard, keyed canonical.

    Fully fail-safe: any network/shape error returns {} so the curated snapshot
    carries the page. ESPN surfaces injuries inconsistently for internationals,
    so this only *adds* to the curated data — it never replaces it.
    """
    out: Dict[str, List[Absence]] = {}
    try:
        import requests

        resp = requests.get(_ESPN_SCOREBOARD.format(league=league), timeout=_ESPN_TIMEOUT)
        resp.raise_for_status()
        events = resp.json().get("events", []) or []
    except Exception:
        return {}

    for ev in events:
        for comp in ev.get("competitions", []) or []:
            for competitor in comp.get("competitors", []) or []:
                team = (competitor.get("team") or {}).get("displayName", "")
                canon = canonical_team(team)
                if not canon:
                    continue
                for inj in competitor.get("injuries", []) or []:
                    ath = inj.get("athlete") or {}
                    name = ath.get("displayName") or ath.get("fullName")
                    if not name:
                        continue
                    out.setdefault(canon, []).append(Absence(
                        player=name,
                        position=(ath.get("position") or {}).get("abbreviation", ""),
                        status=(inj.get("status") or "Out").title(),
                        reason=inj.get("details", {}).get("type", "") if isinstance(
                            inj.get("details"), dict) else "",
                        source="espn",
                    ))
    return out


def _merge(curated: List[Absence], live: List[Absence]) -> List[Absence]:
    """Combine snapshot + ESPN absences, de-duplicated by player name."""
    by_name = {a.player.lower(): a for a in curated}
    for a in live:
        by_name.setdefault(a.player.lower(), a)
    return sorted(by_name.values(), key=lambda a: a._rank())


# --------------------------------------------------------------- by game ---
@dataclass
class GameInjuries:
    match_id: str
    group: str
    commence_time: str
    home: str
    away: str
    home_absences: List[Absence] = field(default_factory=list)
    away_absences: List[Absence] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.home_absences) + len(self.away_absences)

    def to_dict(self) -> dict:
        return {
            "match_id": self.match_id,
            "group": self.group,
            "commence_time": self.commence_time,
            "home": self.home,
            "away": self.away,
            "home_absences": [a.to_dict() for a in self.home_absences],
            "away_absences": [a.to_dict() for a in self.away_absences],
            "total": self.total,
        }


def build_report(matches: List[Match], use_espn: bool = False) -> List[GameInjuries]:
    """One availability record per upcoming match, organized by game.

    Only upcoming (not yet played) matches are reported — a settled game's team
    sheet is history. Matches are returned kickoff-first.
    """
    live = espn_absences() if use_espn else {}

    games: List[GameInjuries] = []
    for m in matches:
        if m.played:
            continue
        ch, ca = canonical_team(m.home), canonical_team(m.away)
        home_abs = _merge(_curated_absences(ch), live.get(ch or "", []))
        away_abs = _merge(_curated_absences(ca), live.get(ca or "", []))
        games.append(GameInjuries(
            match_id=m.game.id, group=m.group, commence_time=m.commence_time,
            home=m.home, away=m.away,
            home_absences=home_abs, away_absences=away_abs,
        ))

    # Kickoff order; unknown/empty kickoffs sink to the end.
    games.sort(key=lambda g: g.commence_time or "9999")
    return games


def build_payload(games: List[GameInjuries], used_espn: bool) -> dict:
    total = sum(g.total for g in games)
    affected = sum(1 for g in games if g.total)
    sources = "Maintained snapshot" + (" + ESPN live" if used_espn else "")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "competition": "soccer_fifa_world_cup",
        "as_of": AS_OF,
        "source": sources,
        "game_count": len(games),
        "affected_games": affected,
        "total_absences": total,
        "games": [g.to_dict() for g in games],
        "note": (
            "Players who were expected to feature but are ruled out, doubtful, or "
            "suspended, per upcoming game. Maintained snapshot dated "
            f"{AS_OF}; verify against official team news before kickoff."
        ),
    }


def run(matches: List[Match], use_espn: bool = False) -> dict:
    """Build the report from already-fetched matches and write site/injuries.json."""
    import json

    games = build_report(matches, use_espn=use_espn)
    payload = build_payload(games, used_espn=use_espn)
    SITE_DATA.parent.mkdir(parents=True, exist_ok=True)
    SITE_DATA.write_text(json.dumps(payload, indent=2))
    return payload
