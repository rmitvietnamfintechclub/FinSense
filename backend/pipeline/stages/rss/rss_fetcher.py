"""Stage 1 (rss) — discovers candidate articles from source RSS feeds.

The entry point is `fetch_all_feeds`: it walks the configured (source,
feed_url) pairs and returns one flat list of candidate articles, each a
dict with url / title / summary / source / published_at. Downstream
stages (url_normalizer, filter, scraper) consume that shape.

Resilience is a hard requirement: a single malformed or unreachable feed
must never abort the whole run. Every per-feed failure is caught, logged,
and skipped so the remaining feeds still contribute.
"""
from __future__ import annotations

import logging
from calendar import timegm
from datetime import datetime, timezone

import feedparser

from backend.core.config import RSS_FEEDS

logger = logging.getLogger(__name__)


def _to_datetime(parsed_time) -> datetime | None:
    """Convert feedparser's struct_time (already UTC) to an aware datetime."""
    if not parsed_time:
        return None
    return datetime.fromtimestamp(timegm(parsed_time), tz=timezone.utc)


def _entry_to_article(entry, source: str) -> dict | None:
    """Map one feed entry to a candidate article, or None if it has no URL."""
    url = (entry.get("link") or "").strip()
    if not url:
        return None
    return {
        "url": url,
        "title": (entry.get("title") or "").strip(),
        "summary": (entry.get("summary") or "").strip(),
        "source": source,
        "published_at": _to_datetime(
            entry.get("published_parsed") or entry.get("updated_parsed")
        ),
    }


def fetch_feed(source: str, feed_url: str) -> list[dict]:
    """Fetch and parse a single feed into a list of candidate articles.

    feedparser reports malformed feeds via `bozo` rather than raising, so
    we log that but still salvage whatever entries parsed.
    """
    parsed = feedparser.parse(feed_url)
    if parsed.bozo:
        logger.warning(
            "rss feed parse issue (source=%s url=%s): %s",
            source, feed_url, parsed.bozo_exception,
        )

    articles = [
        article
        for entry in parsed.entries
        if (article := _entry_to_article(entry, source)) is not None
    ]
    logger.info("rss feed fetched: source=%s entries=%d", source, len(articles))
    return articles


def fetch_all_feeds(feeds: list[tuple[str, str]] | None = None) -> list[dict]:
    """Fetch every configured feed, isolating failures per feed.

    A feed that raises (network error, unexpected feedparser state) is
    logged and skipped — it never stops the other feeds from running.
    """
    feeds = feeds if feeds is not None else RSS_FEEDS
    all_articles: list[dict] = []

    for source, feed_url in feeds:
        try:
            all_articles.extend(fetch_feed(source, feed_url))
        except Exception:
            logger.exception(
                "rss feed failed, skipping (source=%s url=%s)", source, feed_url
            )
            continue

    logger.info(
        "rss discovery: feeds=%d articles=%d", len(feeds), len(all_articles)
    )
    return all_articles
