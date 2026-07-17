

#F2 (dedup) + F3 (relevance filter) — gộp chung theo thiết kế lead.


from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from .url_normalizer import normalize_url

_LEXICON_PATH = (
    # rss/filter.py -> stages/rss/ -> stages/ -> pipeline/ -> pipeline/lexicon/
    # (khớp đúng cấu trúc thật: lexicon/ nằm NGANG CẤP với stages/,
    # không phải nằm trong stages/)
    Path(__file__).resolve().parent.parent.parent / "lexicon" / "relevance_keywords.json"
)
_noise_keywords_cache: list[str] | None = None


def _load_noise_keywords() -> list[str]:
    """Đọc NOISE_KEYWORDS từ lexicon/relevance_keywords.json, cache lại
    sau lần đọc đầu tiên để không phải đọc file mỗi lần gọi is_relevant()."""
    global _noise_keywords_cache
    if _noise_keywords_cache is None:
        with open(_LEXICON_PATH, encoding="utf-8") as f:
            data = json.load(f)
        _noise_keywords_cache = data["noise_keywords"]
    return _noise_keywords_cache


# ============================================================
# F2 — Dedup
# ============================================================


def is_duplicate(url: str, collection) -> bool:
    """
    Kiểm tra URL (sau khi normalize) đã tồn tại trong collection chưa.
    Dùng thẳng field `url` làm khóa dedup thay vì hash trung gian.

    `collection` cần có method find_one(query) — tương thích cả
    pymongo Collection thật lẫn FakeCollection dùng để test.
    """
    normalized = normalize_url(url)
    return collection.find_one({"url": normalized}) is not None


# ============================================================
# F3 — Relevance filter
# ============================================================


def _normalize_text(text: str) -> str:
    """Chuẩn hóa Unicode NFC — tránh so khớp keyword fail âm thầm nếu
    text tới từ nguồn encode theo NFD (dấu tổ hợp rời)."""
    return unicodedata.normalize("NFC", text)


def is_relevant(title: str, summary: str) -> bool:
    """
    Trả False nếu title/summary chứa bất kỳ từ khóa nào trong
    lexicon/relevance_keywords.json.
    """
    text = _normalize_text(f"{title} {summary}").lower()
    keywords = _load_noise_keywords()
    return not any(_normalize_text(kw) in text for kw in keywords)
