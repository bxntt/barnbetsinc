"""Price an alternate spread/total line off the sharp line.

The odds feed gives one line per book per market, so when Hard Rock's spread/total
sits at a *different* number than the sharp reference we'd normally have to skip the
bet. Instead we model the game's margin (spreads) / total (totals) as Normal and
shift the reference's no-vig fair probability to Hard Rock's number:

    fair(target) = Φ( Φ⁻¹(fair(ref)) + (Δpoints / σ) )

This only needs the reference's fair prob at its own line plus a per-sport σ. It is
reach-limited (we never extrapolate far) and the caller applies a confidence
penalty that grows with the distance shifted, since σ is an approximation.
"""
from __future__ import annotations

import math
from typing import Optional, Tuple

# Per-sport standard deviation of game margin (spreads) and total (totals), in
# points/runs/goals. Approximate; interpolation is confidence-penalized to match.
_SIGMA_SPREAD = {
    "americanfootball_nfl": 13.5,
    "americanfootball_ncaaf": 16.0,
    "basketball_nba": 12.0,
    "basketball_ncaab": 10.5,
    "baseball_mlb": 3.1,
    "icehockey_nhl": 2.2,
}
_SIGMA_TOTAL = {
    "americanfootball_nfl": 9.8,
    "americanfootball_ncaaf": 11.0,
    "basketball_nba": 16.5,
    "basketball_ncaab": 12.5,
    "baseball_mlb": 4.0,
    "icehockey_nhl": 2.3,
}
_DEFAULT_SIGMA = 12.0


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
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


def interp_fair(
    market: str,
    sport_key: str,
    selection: str,
    ref_point: float,
    ref_fair: float,
    target_point: float,
    max_reach: float,
) -> Optional[Tuple[float, float]]:
    """Shift `ref_fair` (at `ref_point`) to `target_point`. Returns (fair, reach)
    where reach = |Δpoints|, or None if out of range / too far to trust."""
    if ref_point is None or target_point is None:
        return None
    if not 0.0 < ref_fair < 1.0:
        return None
    delta = target_point - ref_point
    reach = abs(delta)
    if reach == 0.0 or reach > max_reach:
        return None

    if market == "spreads":
        sigma = _SIGMA_SPREAD.get(sport_key, _DEFAULT_SIGMA)
        shift = delta / sigma                       # same for either side
    elif market == "totals":
        sigma = _SIGMA_TOTAL.get(sport_key, _DEFAULT_SIGMA)
        # Raising the line lowers Over and raises Under.
        shift = (-delta if selection.lower() == "over" else delta) / sigma
    else:
        return None

    fair = _norm_cdf(_norm_ppf(ref_fair) + shift)
    if not 0.0 < fair < 1.0:
        return None
    return fair, reach
