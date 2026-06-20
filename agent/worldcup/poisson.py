"""Independent-Poisson scoreline model, fitted to the market.

Soccer group tables need *scorelines*, not just win/draw/loss — goal difference
and goals-for are the tiebreakers, and "8 best third-placed teams" is ranked on
them. So for each unplayed match we recover goal expectancies (lambda_home,
lambda_away) whose independent-Poisson win/draw/loss probabilities best match the
market's no-vig 1X2 line, then sample scorelines from those Poissons.

Independent Poisson slightly under-states draws vs reality, so `score_matrix`
applies the Dixon-Coles low-score correction (a small reshaping of the 0-0/1-0/
0-1/1-1 cells) to lift draws back to realistic rates. It stays fully market-derived
(no external ratings needed).
"""
from __future__ import annotations

import bisect
import math
from functools import lru_cache
from typing import List, Tuple

MAX_GOALS = 10  # truncate the scoreline grid; P(>10 goals for one team) ~ 0

# Dixon-Coles dependence parameter. Independent Poisson under-states low-score
# draws; a small negative rho lifts 0-0 and 1-1 while trimming 1-0 and 0-1, which
# corrects the known draw understatement (poisson.py docstring) without any new
# data. Empirically rho sits ~ -0.03..-0.10; -0.06 is a safe mid value.
DIXON_COLES_RHO = -0.06


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


def _dc_tau(home: int, away: int, lh: float, la: float, rho: float) -> float:
    """Dixon-Coles tau multiplier for a low-score cell (1.0 for every other cell).

    Reshapes only the four cells where the independence assumption bites: with
    rho < 0 it lifts the two draws (0-0, 1-1) and trims the one-goal wins (1-0,
    0-1), the classic correction to Poisson's draw understatement.
    """
    if home == 0 and away == 0:
        return 1.0 - lh * la * rho
    if home == 0 and away == 1:
        return 1.0 + lh * rho
    if home == 1 and away == 0:
        return 1.0 + la * rho
    if home == 1 and away == 1:
        return 1.0 - rho
    return 1.0


def score_matrix(lam_home: float, lam_away: float,
                 rho: float = DIXON_COLES_RHO) -> List[List[float]]:
    """Joint P(home=i, away=j) grid for i,j = 0..MAX_GOALS, Dixon-Coles corrected.

    Independent Poisson cells, reshaped by the Dixon-Coles tau on the four low
    scores (see `_dc_tau`) and renormalized to sum to 1. The single source for
    every derived market: 1X2, totals, both-teams-to-score, and goal-handicap
    probabilities are all sums over cells of this grid. Pass rho=0.0 for the plain
    independent grid.
    """
    h = _pmf_vector(round(lam_home, 3))
    a = _pmf_vector(round(lam_away, 3))
    grid = [[h[i] * a[j] for j in range(MAX_GOALS + 1)] for i in range(MAX_GOALS + 1)]
    if not rho:
        return grid
    total = 0.0
    for i in range(2):              # tau only touches goals 0 and 1
        for j in range(2):
            grid[i][j] = max(0.0, grid[i][j] * _dc_tau(i, j, lam_home, lam_away, rho))
    for row in grid:
        total += sum(row)
    if total <= 0:
        return grid
    return [[cell / total for cell in row] for row in grid]


def total_over_prob(mean: float, line: float) -> float:
    """P(home + away goals > line) when the match total is Poisson(`mean`).

    A closed-form read of the over side at a given line, used to translate the
    market's over/under price into the goal mean it implies (see
    `mean_from_total_over`). The sum of two independent Poissons is Poisson, so a
    single rate captures the total cleanly.
    """
    pmf = _pmf_vector(round(mean, 3))
    k = int(math.floor(line))
    return max(0.0, 1.0 - sum(pmf[:k + 1]))


def mean_from_total_over(line: float, p_over: float) -> float:
    """Invert `total_over_prob`: the Poisson total-mean implying this over prob.

    `total_over_prob` is monotonic in the mean, so a bisection recovers the goal
    expectation the market's over/under line is pricing — the input we blend into
    the model's mean to sharpen totals (and the derived BTTS/handicap) for free.
    """
    lo, hi = 0.2, 8.0
    for _ in range(40):
        mid = (lo + hi) / 2.0
        if total_over_prob(mid, line) < p_over:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


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
