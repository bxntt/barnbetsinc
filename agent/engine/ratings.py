"""Team-strength model for US sports, built from free results history.

This is the independent model the predictor blends with the market. From the same
ESPN final scores used for grading we build, per sport+team:

  * an **Elo rating** (win/loss) -> win probability + expected scoring margin, and
  * **scoring averages** (points for / against) -> an expected game total.

Both cold-start gracefully: a team we've barely seen returns ``None`` from the
probability helpers, and the predictor falls back to the market consensus for that
game. Nothing here references a sportsbook price — it is pure "how good is this
team" derived from results.

Per-sport margin / total standard deviations live here too (used to turn an
expected margin/total into cover/over probabilities via a Normal model).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from .results import nickname

_BASE = 1500.0
_K = 20.0
_HFA = 50.0            # home edge, in Elo points
_MIN_TEAM_GAMES = 3   # don't trust a team rating/scoring built from fewer games

# Per-sport standard deviation of final margin and total, in points/runs/goals.
# Approximate; predictions derived through these are confidence-discounted.
SIGMA_MARGIN = {
    "americanfootball_nfl": 13.5,
    "americanfootball_ncaaf": 16.0,
    "basketball_nba": 12.0,
    "basketball_ncaab": 10.5,
    "baseball_mlb": 3.1,
    "icehockey_nhl": 2.2,
}
SIGMA_TOTAL = {
    "americanfootball_nfl": 9.8,
    "americanfootball_ncaaf": 11.0,
    "basketball_nba": 16.5,
    "basketball_ncaab": 12.5,
    "baseball_mlb": 4.0,
    "icehockey_nhl": 2.3,
}
_DEFAULT_SIGMA = 12.0


# --------------------------------------------------------------- normal math ---
def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """Inverse normal CDF (Acklam's rational approximation)."""
    if p <= 0.0:
        return -1e9
    if p >= 1.0:
        return 1e9
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1.0 - 0.02425
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)
    if p > phigh:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1.0)


def sigma_margin(sport: str) -> float:
    return SIGMA_MARGIN.get(sport, _DEFAULT_SIGMA)


def sigma_total(sport: str) -> float:
    return SIGMA_TOTAL.get(sport, _DEFAULT_SIGMA)


# ------------------------------------------------------------------- model ---
@dataclass
class TeamModel:
    """Built team strengths. Keys are (sport_key, team_nickname)."""
    elo: Dict[Tuple[str, str], float] = field(default_factory=dict)
    games: Dict[Tuple[str, str], int] = field(default_factory=dict)
    pts_for: Dict[Tuple[str, str], float] = field(default_factory=dict)   # avg scored
    pts_against: Dict[Tuple[str, str], float] = field(default_factory=dict)  # avg allowed
    min_team_games: int = _MIN_TEAM_GAMES

    def _seen(self, sport: str, team: str) -> Optional[Tuple[str, str]]:
        key = (sport, nickname(team))
        if not key[1] or self.games.get(key, 0) < self.min_team_games:
            return None
        return key

    def p_home_win(self, sport: str, home: str, away: str) -> Optional[float]:
        """Elo win probability for the home side, or None if cold-started."""
        hk, ak = self._seen(sport, home), self._seen(sport, away)
        if hk is None or ak is None:
            return None
        rh, ra = self.elo[hk], self.elo[ak]
        return 1.0 / (1.0 + 10 ** (-((rh + _HFA) - ra) / 400.0))

    def expected_margin(self, sport: str, home: str, away: str) -> Optional[float]:
        """Expected home margin (home_pts - away_pts), from the Elo win prob."""
        p = self.p_home_win(sport, home, away)
        if p is None:
            return None
        return norm_ppf(min(0.999, max(0.001, p))) * sigma_margin(sport)

    def expected_total(self, sport: str, home: str, away: str) -> Optional[float]:
        """Expected combined score, from the two teams' scoring averages."""
        hk, ak = self._seen(sport, home), self._seen(sport, away)
        if hk is None or ak is None:
            return None
        home_pts = 0.5 * (self.pts_for[hk] + self.pts_against[ak])
        away_pts = 0.5 * (self.pts_for[ak] + self.pts_against[hk])
        return home_pts + away_pts


def build_team_model(results, min_team_games: int = _MIN_TEAM_GAMES) -> TeamModel:
    """Build Elo + scoring averages from chronological final scores."""
    m = TeamModel(min_team_games=min_team_games)
    for r in sorted(results, key=lambda x: x.get("completed_at") or ""):
        sk = r.get("sport_key", "")
        hk, ak = (sk, nickname(r.get("home"))), (sk, nickname(r.get("away")))
        hs, as_ = r.get("home_score"), r.get("away_score")
        if not hk[1] or not ak[1] or hs is None or as_ is None:
            continue
        # Elo update.
        rh, ra = m.elo.get(hk, _BASE), m.elo.get(ak, _BASE)
        exp_h = 1.0 / (1.0 + 10 ** (-((rh + _HFA) - ra) / 400.0))
        act_h = 1.0 if hs > as_ else 0.0 if hs < as_ else 0.5
        m.elo[hk] = rh + _K * (act_h - exp_h)
        m.elo[ak] = ra - _K * (act_h - exp_h)
        # Scoring running averages.
        for key, sf, sa in ((hk, hs, as_), (ak, as_, hs)):
            n = m.games.get(key, 0)
            m.pts_for[key] = (m.pts_for.get(key, 0.0) * n + sf) / (n + 1)
            m.pts_against[key] = (m.pts_against.get(key, 0.0) * n + sa) / (n + 1)
            m.games[key] = n + 1
    return m
