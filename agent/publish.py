"""Serialize ranked best bets + metadata to site/data.json for the website."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from .config import ROOT
from .models import BestBet
from .rank import selection_label

SITE_DATA = ROOT / "site" / "data.json"


def build_payload(
    bets: List[BestBet],
    track_record: dict,
    target_book: str,
    calibration: dict = None,
) -> dict:
    items = []
    for b in bets:
        d = b.to_dict()
        d["label"] = selection_label(b.market, b.selection, b.point)
        d["ev_pct"] = round(b.ev_pct, 2)
        d["fair_prob_pct"] = round(b.fair_prob * 100, 1)   # estimated chance to hit
        d["chance_pct"] = round(b.fair_prob * 100, 1)
        d["confidence"] = round(b.confidence, 2)
        d["market_vig_pct"] = round(b.market_vig * 100, 2)
        d["kelly_pct"] = round(b.kelly_pct, 2)
        d["method_spread_pct"] = round(b.method_spread * 100, 1)
        d["model_prob_pct"] = None if b.model_prob is None else round(b.model_prob * 100, 1)
        items.append(d)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_book": target_book,
        "count": len(items),
        "track_record": track_record,
        "calibration": calibration or {},
        "bets": items,
        "disclaimer": (
            "Informational only. Not financial advice. For 21+ where legal. "
            "Edges are estimates; sportsbooks may limit winning accounts."
        ),
    }


def write_site_data(payload: dict, path: Path = SITE_DATA) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return path
