"""Match-context signals — the reasoning layer on top of the strength prior.

`ratings.py` gives each team a static Elo prior; the prediction engine then asks a
sharper question: *given who is actually available, how the teams are trending, and
where the game is played, what scoreline rates should we expect?* This module turns
three concrete signals into goal-rate adjustments the Poisson model consumes:

  * injuries   — position- and severity-weighted impact of the players who are out,
                 doubtful, or suspended. A talisman striker ruled out drops that
                 team's attack; a first-choice keeper out lifts the opponent's. The
                 raw absences come from injuries.py (curated snapshot + optional
                 ESPN), so this is FREE — no extra odds credits, no new API.
  * momentum   — attacking/defensive form from the live group standings (goals for
                 and against per game), decoupled from the goal-difference term that
                 already feeds `ratings.form_delta`, and tightly capped so a single
                 blowout can't dominate a 1-2 game sample.
  * venue      — a *real* home edge only for the 2026 host nations on home soil;
                 every other group game is treated as the neutral fixture it is.

The output is a `MatchFactors`: four goal-unit tilts (home/away x attack/defense), a
host-venue supremacy edge, and human-readable notes that flow into each pick's
rationale so the site shows the reasoning, not just a number.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from . import ratings

# 2026 is co-hosted by the USA, Canada and Mexico; only these sides carry a true
# home crowd, and only in their own matches. Everyone else plays on neutral ground.
HOST_NATIONS = {"United States", "Canada", "Mexico"}
HOST_EDGE_GOALS = 0.28          # supremacy bump (goals) for a host on home soil

# --- injury impact model --------------------------------------------------------
# Elo a fully-absent player removes, before position/severity/star weighting.
_STARTER_ELO = 34.0             # a nailed-on first-XI starter (~0.23 goals of class)
_SQUAD_ELO = 11.0               # a rotation / depth player
# Severity: a suspension or "out" is a certainty; a doubt is a partial, weighted
# bet that they miss (and play below their best if they do feature).
_STATUS_WEIGHT = {"out": 1.0, "suspended": 1.0, "doubtful": 0.45, "questionable": 0.25}
# Where the loss lands: (attack_share, defense_share). A forward hurts only scoring;
# a defender/keeper only the back line; a midfielder both.
_POS_SPLIT = {"FW": (1.0, 0.0), "MF": (0.6, 0.4), "DF": (0.0, 1.0), "GK": (0.0, 1.0)}
_UNKNOWN_SPLIT = (0.5, 0.5)
# Never let absences swing one side's attack or defense by more than this (goals);
# a depleted squad is weaker, not hopeless.
_MAX_INJURY_GOALS = 0.45

# --- momentum (form) model ------------------------------------------------------
_BASELINE_GF = 1.30             # goals/game an average side scores at this level
_FORM_COEF = 0.10               # goals of tilt per goal/game above (or below) baseline
_MAX_FORM_GOALS = 0.18          # cap so one 7-0 result doesn't run the model


def _position_group(position: str) -> str:
    """Normalize a free-form position label to FW / MF / DF / GK ('' if unknown)."""
    p = (position or "").strip().upper()
    if not p:
        return ""
    if p in _POS_SPLIT:
        return p
    if p.startswith("G"):                       # GK, G, GOALKEEPER
        return "GK"
    if p.startswith("D") or "BACK" in p:        # DF, D, CB, RB, LB, DEFENDER
        return "DF"
    if p.startswith("M") or "MID" in p:         # MF, M, CM, DM, AM
        return "MF"
    if p.startswith(("F", "W", "S")) or "FORWARD" in p or "STRIK" in p:  # FW, F, ST, W
        return "FW"
    return ""


@dataclass
class InjuryImpact:
    """A team's attack/defense quality lost to absences, in Elo points."""
    attack_elo: float = 0.0
    defense_elo: float = 0.0
    notes: List[str] = field(default_factory=list)

    @property
    def total_elo(self) -> float:
        return self.attack_elo + self.defense_elo


def injury_impact(absences: Sequence) -> InjuryImpact:
    """Weighted attack/defense quality a team loses to its absentees.

    `absences` is a list of injuries.Absence (player, position, status,
    expected_starter, impact). Each contributes Elo scaled by role (starter vs
    depth), severity (out/suspended vs doubtful), an optional per-player ``impact``
    multiplier for genuine talismen, and split to attack/defense by position. Totals
    are capped so a hard-hit squad is dampened, not deleted.
    """
    attack = defense = 0.0
    key_notes: List[tuple] = []  # (elo, text) so we can surface the biggest losses
    for a in absences:
        status = (getattr(a, "status", "") or "").lower()
        weight = _STATUS_WEIGHT.get(status, 0.6)
        base = _STARTER_ELO if getattr(a, "expected_starter", False) else _SQUAD_ELO
        elo = base * weight * float(getattr(a, "impact", 1.0) or 1.0)
        if elo <= 0:
            continue
        atk_share, def_share = _POS_SPLIT.get(
            _position_group(getattr(a, "position", "")), _UNKNOWN_SPLIT)
        attack += elo * atk_share
        defense += elo * def_share
        key_notes.append((elo, getattr(a, "player", "a key player"),
                          status or "out"))

    # Cap in goal units, then convert back to Elo for the caller.
    cap_elo = _MAX_INJURY_GOALS * ratings.RATING_SCALE
    attack = min(attack, cap_elo)
    defense = min(defense, cap_elo)

    notes: List[str] = []
    for elo, player, status in sorted(key_notes, reverse=True)[:2]:
        if elo >= _STARTER_ELO * 0.5:           # only flag genuinely material losses
            if status == "suspended":
                notes.append(f"{player} (suspended)")
            elif status in ("doubtful", "questionable"):
                notes.append(f"{player} (doubtful)")
            else:
                notes.append(player)             # "missing X" already implies out
    return InjuryImpact(attack_elo=attack, defense_elo=defense, notes=notes)


def momentum_tilt(standing: Optional[Dict[str, int]]) -> tuple:
    """(attack_goals, defense_goals) form tilt from live group output.

    Reads goals-for and goals-against per game (against a baseline) so a side that
    is *scoring* freely gets a small totals bump and a *leaky* side concedes a touch
    more — distinct from the points/goal-difference momentum already in
    `ratings.form_delta`. Returns (0.0, 0.0) before a team has played.
    """
    if not standing:
        return 0.0, 0.0
    played = standing.get("played", 0)
    if not played:
        return 0.0, 0.0
    gf = standing.get("gf", 0)
    gd = standing.get("gd", 0)
    ga = gf - gd
    gf_pg, ga_pg = gf / played, ga / played
    attack = _clamp(_FORM_COEF * (gf_pg - _BASELINE_GF), _MAX_FORM_GOALS)
    # Fewer goals conceded than baseline = positive defense tilt (opponent scores less).
    defense = _clamp(_FORM_COEF * (_BASELINE_GF - ga_pg), _MAX_FORM_GOALS)
    return attack, defense


def _clamp(x: float, lim: float) -> float:
    return max(-lim, min(lim, x))


@dataclass
class MatchFactors:
    """All non-prior signals for one match, as goal-unit tilts + venue edge."""
    home_attack_adj: float = 0.0     # goals added to (or removed from) home scoring
    home_defense_adj: float = 0.0    # goals of home defensive solidity (subtracts from away)
    away_attack_adj: float = 0.0
    away_defense_adj: float = 0.0
    home_advantage: float = 0.0      # net host-venue supremacy edge (goals, favors home)
    home_notes: List[str] = field(default_factory=list)
    away_notes: List[str] = field(default_factory=list)
    injury_uncertainty: float = 0.0  # 0..1, how much a doubtful key man clouds the call

    def rationale_suffix(self, home: str, away: str) -> str:
        """A compact ' — Factoring in ...' clause for a pick's rationale, or ''."""
        bits: List[str] = []
        if self.home_notes:
            bits.append(f"{home} missing {', '.join(self.home_notes)}")
        if self.away_notes:
            bits.append(f"{away} missing {', '.join(self.away_notes)}")
        if self.home_advantage >= 0.12:
            bits.append(f"{home} on home soil")
        elif self.home_advantage <= -0.12:
            bits.append(f"{away} on home soil")
        if not bits:
            return ""
        return " Factoring in " + "; ".join(bits) + "."

    def to_dict(self) -> dict:
        return {
            "home_notes": self.home_notes,
            "away_notes": self.away_notes,
            "home_field": round(self.home_advantage, 2),
        }


def venue_edge(home: str, away: str) -> float:
    """Net host-venue supremacy edge in goals (positive favors the feed's home side).

    Only the 2026 hosts earn it, and only in their own games; a host listed as the
    feed's 'away' team still gets the crowd, which shows up as a negative edge.
    """
    edge = 0.0
    if home in HOST_NATIONS:
        edge += HOST_EDGE_GOALS
    if away in HOST_NATIONS:
        edge -= HOST_EDGE_GOALS
    return edge


def compute(
    home: str,
    away: str,
    standing_home: Optional[Dict[str, int]] = None,
    standing_away: Optional[Dict[str, int]] = None,
    home_absences: Optional[Sequence] = None,
    away_absences: Optional[Sequence] = None,
) -> MatchFactors:
    """Fold injuries + momentum + venue into one `MatchFactors` for a match."""
    h_inj = injury_impact(home_absences or [])
    a_inj = injury_impact(away_absences or [])
    h_form_atk, h_form_def = momentum_tilt(standing_home)
    a_form_atk, a_form_def = momentum_tilt(standing_away)

    scale = ratings.RATING_SCALE
    mf = MatchFactors(
        home_attack_adj=h_form_atk - h_inj.attack_elo / scale,
        home_defense_adj=h_form_def - h_inj.defense_elo / scale,
        away_attack_adj=a_form_atk - a_inj.attack_elo / scale,
        away_defense_adj=a_form_def - a_inj.defense_elo / scale,
        home_advantage=venue_edge(home, away),
        home_notes=h_inj.notes,
        away_notes=a_inj.notes,
    )
    # A doubtful key player on either side means a less certain call.
    doubt = sum(1 for a in (list(home_absences or []) + list(away_absences or []))
                if (getattr(a, "status", "") or "").lower() in ("doubtful", "questionable")
                and getattr(a, "expected_starter", False))
    mf.injury_uncertainty = min(1.0, 0.12 * doubt)
    return mf
