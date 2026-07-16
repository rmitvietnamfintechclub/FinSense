"""Stage 1 (rss) — dedup + relevance filtering of discovered candidates.

Two independent filters:
- F2 dedup: has this URL already been ingested? Compared by normalized
  URL against the `articles` collection (which is unique-indexed on
  `url`), so no separate hashed id is needed.
- F3 relevance: drop obvious non-financial noise (birthdays, festivals,
  promotions). The noise vocabulary lives in the lexicon so it can be
  edited without touching code.
"""
from __future__ import annotations

import json
import logging
import unicodedata
from pathlib import Path

from .url_normalizer import normalize_url

logger = logging.getLogger(__name__)


# --- F2: dedup by normalized URL ------------------------------------------
def is_duplicate(url: str, collection) -> bool:
    """True if this URL (normalized) has already been ingested."""
    return collection.find_one({"url": normalize_url(url)}) is not None


# --- F3: relevance filter --------------------------------------------------
_KEYWORDS_PATH = (
    Path(__file__).resolve().parents[2] / "lexicon" / "relevance_keywords.json"
)


def _load_noise_keywords() -> list[str]:
    data = json.loads(_KEYWORDS_PATH.read_text(encoding="utf-8"))
    return data.get("noise_keywords", [])


NOISE_KEYWORDS = _load_noise_keywords()


def _normalize_text(text: str) -> str:
    return unicodedata.normalize("NFC", text).lower()


def is_relevant(title: str, summary: str) -> bool:
    """False if the article looks like non-financial noise."""
    text = _normalize_text(f"{title} {summary}")
    return not any(_normalize_text(kw) in text for kw in NOISE_KEYWORDS)
