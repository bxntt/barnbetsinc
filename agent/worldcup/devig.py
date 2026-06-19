"""No-vig fair lines for soccer markets, blended across every book.

The Hard Rock engine de-vigs ONE sharp book and judges Hard Rock against it. Here
there is no target book: we de-vig *each* book multiplicatively, then average the
fair probabilities across books into a consensus. This works for any number of
outcomes, so it covers 1X2 (home / draw / away) as cleanly as a 2-way total.

    per book:   fair_i = (1/decimal_i) / sum_j(1/decimal_j)      # vig removed
    consensus:  mean of fair_i across books, renormalized to sum 1
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..models import BookOdds
from .models import FairLine, Key


def _modal_point(books: List[BookOdds]) -> Dict[str, Optional[float]]:
    """For each selection name, the most common point line across books.

    1X2 outcomes have point=None (so this is a no-op). Totals can differ by book
    (7.5 vs 8.5); we consensus only the modal line so we compare like with like.
    """
    seen: Dict[str, List[Optional[float]]] = {}
    for bo in books:
        for o in bo.outcomes:
            pt = None if o.point is None else round(o.point, 1)
            seen.setdefault(o.name, []).append(pt)
    return {name: max(set(pts), key=pts.count) for name, pts in seen.items()}


def consensus_fair(books: List[BookOdds]) -> Optional[FairLine]:
    """Blend all books into a no-vig consensus for one market.

    Returns None if fewer than two outcomes can be assembled (nothing to de-vig).
    """
    books = [bo for bo in books if len(bo.outcomes) >= 2]
    if not books:
        return None

    modal = _modal_point(books)
    fair_sums: Dict[Key, float] = {}
    fair_counts: Dict[Key, int] = {}
    vigs: List[float] = []

    for bo in books:
        # Only consider outcomes sitting on this market's modal line.
        picks = [
            o for o in bo.outcomes
            if (None if o.point is None else round(o.point, 1)) == modal.get(o.name)
        ]
        if len(picks) < 2:
            continue
        implied = {(o.name, modal.get(o.name)): o.implied for o in picks}
        total = sum(implied.values())
        if total <= 0:
            continue
        vigs.append(total - 1.0)
        for k, v in implied.items():
            fair_sums[k] = fair_sums.get(k, 0.0) + v / total
            fair_counts[k] = fair_counts.get(k, 0) + 1

    if len(fair_sums) < 2 or not vigs:
        return None

    avg = {k: fair_sums[k] / fair_counts[k] for k in fair_sums}
    norm = sum(avg.values())
    if norm <= 0:
        return None
    fair = {k: v / norm for k, v in avg.items()}
    return FairLine(fair_by_key=fair, vig=sum(vigs) / len(vigs), n_books=len(vigs))
