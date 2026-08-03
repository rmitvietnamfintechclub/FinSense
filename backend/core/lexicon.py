# backend/core/lexicon.py
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_ONTOLOGY_PATH = Path(__file__).parent / "data" / "static_ontology.json"


@lru_cache(maxsize=1)
def load_static_ontology() -> dict[str, dict[str, float]]:
    """ticker -> {concept: weight}, read once per process."""
    entries = json.loads(_ONTOLOGY_PATH.read_text(encoding="utf-8"))
    return {
        e["ticker"]: {cw["concept"]: cw["weight"] for cw in e["concept_weights"]}
        for e in entries
    }


def get_concept_weights(ticker: str) -> dict[str, float]:
    return load_static_ontology().get(ticker, {})