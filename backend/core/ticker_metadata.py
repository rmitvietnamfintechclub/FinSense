# backend/core/ticker_metadata.py
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from backend.core.enums import Ticker
from backend.core.schemas.ticker_metadata import TickerMetadata

_METADATA_PATH = Path(__file__).parent / "data" / "ticker_metadata.json"


@lru_cache(maxsize=1)
def get_ticker_metadata() -> dict[Ticker, TickerMetadata]:
    """ticker -> display metadata (name + primary sector), read once per process."""
    entries = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    return {
        Ticker(symbol): TickerMetadata.model_validate(entry)
        for symbol, entry in entries.items()
    }
