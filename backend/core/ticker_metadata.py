# backend/core/ticker_dictionary.py
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from backend.core.enums import Ticker
from backend.core.schemas.ticker_metadata import TickerEntry

_DICTIONARY_PATH = Path(__file__).parent / "data" / "ticker_metadata.json"


@lru_cache(maxsize=1)
def get_ticker_dictionary() -> dict[Ticker, TickerEntry]:
    """ticker -> display name + aliases, read once per process."""
    entries = json.loads(_DICTIONARY_PATH.read_text(encoding="utf-8"))
    dictionary = {
        Ticker(symbol): TickerEntry.model_validate(entry)
        for symbol, entry in entries.items()
    }

    missing = set(Ticker) - dictionary.keys()
    if missing:
        raise ValueError(
            f"ticker_dictionary.json is missing entries for: "
            f"{sorted(t.value for t in missing)}"
        )

    return dictionary