"""Independent-Poisson scoreline model, fitted to the market.

Soccer group tables need *scorelines*, not just win/draw/loss — goal difference
and goals-for are the tiebreakers, and "8 best third-placed teams" is ranked on
them. So for each unplayed match we recover goal expectancies (lambda_home,
lambda_away) whose independent-Poisson win/draw/loss probabilities best match the
market's no-vig 1X2 line, then sample scorelines from those Poissons.

Independent Poisson slightly under-states draws vs reality; good enough for a
group-stage Monte Carlo and fully market-derived (no external ratings needed).
"""
from __future__ import annotations

import bisect
import math
from functools import lru_cache
from typing import List, Tuple

MAX_GOALS = 10  # truncate the scoreline grid; P(>10 goals for one team) ~ 0


@lru_cache(maxsize=4096)
def _pmf_vector(lam: float) -> Tuple[float, ...]:
    """Poisson pmf for k = 0..MAX_GOALS at rate `lam` (lam quantized by caller)."""
    out = []
    for k in range(MAX_GOALS + 1):
        out.append(math.exp(-lam) * lam ** k / math.factorial(k))
    return tuple(out)


def outcome_probs(lam_home: float, lam_away: float) -> Tuple[float, float, float]:
    """(P(home win), P(draw), P(away win)) under two independent Poissons."""
    h = _pmf_vector(round(lam_home, 3))
    a = _pmf_vector(round(lam_away, 3))
    p_home = p_draw = p_away = 0.0
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            p = h[i] * a[j]
            if i > j:
                p_home += p
            elif i == j:
                p_draw += p
            else:
                p_away += p
    return p_home, p_draw, p_away


def fit_lambdas(
    p_home: float, p_draw: float, p_away: float, mean_goals: float = 2.7
) -> Tuple[float, float]:
    """Recover (lambda_home, lambda_away) matching a no-vig 1X2 line.

    Coarse grid search then local refine, minimizing squared error to the target
    (home, draw, away) probabilities. `mean_goals` only seeds the search range.
    """
    target = (p_home, p_draw, p_away)

    def sse(lh: float, la: float) -> float:
        ph, pd, pa = outcome_probs(lh, la)
        return (ph - target[0]) ** 2 + (pd - target[1]) ** 2 + (pa - target[2]) ** 2

    lo, hi = 0.1, max(3.6, mean_goals + 1.5)
    best = (1.3, 1.3)
    best_err = float("inf")

    # Coarse pass.
    step = 0.1
    lh = lo
    while lh <= hi:
        la = lo
        while la <= hi:
            e = sse(lh, la)
            if e < best_err:
                best_err, best = e, (lh, la)
            la += step
        lh += step

    # Local refine around the coarse winner.
    cl, ca = best
    step = 0.02
    lh = max(lo, cl - 0.1)
    while lh <= cl + 0.1:
        la = max(lo, ca - 0.1)
        while la <= ca + 0.1:
            e = sse(lh, la)
            if e < best_err:
                best_err, best = e, (lh, la)
            la += step
        lh += step
    return best


def goal_cdf(lam: float) -> List[float]:
    """Cumulative Poisson over k = 0..MAX_GOALS for fast inverse-CDF sampling."""
    pmf = _pmf_vector(round(lam, 3))
    cdf, run = [], 0.0
    for p in pmf:
        run += p
        cdf.append(run)
    cdf[-1] = 1.0  # absorb the truncated tail into the max bucket
    return cdf


def sample_goals(cdf: List[float], rng) -> int:
    """Draw a goal count from a precomputed cumulative distribution."""
    return bisect.bisect_left(cdf, rng.random())
