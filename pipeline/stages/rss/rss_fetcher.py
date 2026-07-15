from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser
import requests

from backend.core.logging import get_logger
from backend.pipeline.stages.rss.source_tagger import tag_source
from backend.pipeline.stages.rss.url_normalizer import normalize_url

logger = get_logger(__name__)

REQUEST_TIMEOUT_SECONDS = 10

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", _HTML_TAG_RE.sub("", text)).strip()


@dataclass(frozen=True)
class RSSSource:
    name: str
    feed_url: str


SOURCES: list[RSSSource] = [
    RSSSource(name="CafeF", feed_url="https://cafef.vn/home.rss"),
    RSSSource(name="VnExpress", feed_url="https://vnexpress.net/rss/kinh-doanh.rss"),
]


def _parse_published_at(entry: feedparser.FeedParserDict) -> datetime:
    time_struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if time_struct is None:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(time.mktime(time_struct), tz=timezone.utc)


def _entry_to_article(entry: feedparser.FeedParserDict, source: RSSSource) -> dict | None:
    url = entry.get("link")
    title = entry.get("title", "").strip()
    if not url or not title:
        return None
    summary = _strip_html(entry.get("summary", entry.get("description", "")))
    article = {
        "url": normalize_url(url),
        "title": title,
        "summary": summary,
        "published_at": _parse_published_at(entry),
    }
    return tag_source(article, source.name)


def fetch_feed(source: RSSSource, timeout: int = REQUEST_TIMEOUT_SECONDS) -> list[dict]:
    response = requests.get(source.feed_url, timeout=timeout)
    response.raise_for_status()
    parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"unparseable feed: {parsed.bozo_exception}")
    articles = [_entry_to_article(entry, source) for entry in parsed.entries]
    return [article for article in articles if article is not None]


def fetch_all_feeds(sources: list[RSSSource] | None = None) -> list[dict]:
    articles: list[dict] = []
    for source in sources if sources is not None else SOURCES:
        try:
            source_articles = fetch_feed(source)
        except Exception as exc:
            logger.error("rss fetch failed source=%s error=%s", source.name, exc)
            continue
        logger.info("rss fetch ok source=%s count=%d", source.name, len(source_articles))
        articles.extend(source_articles)
    return articles


if __name__ == "__main__":
    for article in fetch_all_feeds():
        print(article)
