"""Serialize ranked predictions + metadata to site/data.json for the website.

The payload mirrors the World Cup feed (site/worldcup.json): a flat list of
per-game, per-market predictions ranked most-likely-to-hit first, plus a
calibration block (the honest check on whether our probabilities hold up).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from .config import ROOT
from .models import Prediction

SITE_DATA = ROOT / "site" / "data.json"


def build_payload(
    predictions: List[Prediction],
    calibration: dict = None,
) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(predictions),
        "predictions": [p.to_dict() for p in predictions],
        "calibration": calibration or {},
        "disclaimer": (
            "Predictions are estimates, not certainties. "
            "Informational only, 21+ where legal."
        ),
    }


def write_site_data(payload: dict, path: Path = SITE_DATA) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return path
