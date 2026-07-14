import unicodedata
 
from .url_normalizer import normalize_url
 

# F2 — Dedup 
 
import hashlib
 
 
def make_article_id(source: str, url: str) -> str:
    normalized = normalize_url(url)
    digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:7]
    return f"{source.lower()}_{digest}"
 
 
def is_duplicate(article_id: str, collection) -> bool:
    return collection.find_one({"article_id": article_id}) is not None
 
 
# F3 — Relevance filter 
 
NOISE_KEYWORDS = [
    "sinh nhật",
    "lễ hội",
    "khai trương",
    "từ thiện",
    "giải thưởng",
    "kỷ niệm",
    "khuyến mãi",
]
 
 
def _normalize_text(text: str) -> str:
    return unicodedata.normalize("NFC", text)
 
 
def is_relevant(title: str, summary: str) -> bool:
    text = _normalize_text(f"{title} {summary}").lower()
    return not any(_normalize_text(kw) in text for kw in NOISE_KEYWORDS)
 