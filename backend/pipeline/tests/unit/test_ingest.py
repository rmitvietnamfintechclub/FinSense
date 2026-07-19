from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

import backend.pipeline.stages.rss.rss_fetcher as rss_fetcher
from backend.pipeline.stages.rss import filter as rss_filter
from backend.pipeline.stages.rss.url_normalizer import normalize_url


# --- url_normalizer --------------------------------------------------------
class TestNormalizeUrl:
    def test_strips_tracking_params_lowercases_host_and_forces_https(self):
        result = normalize_url("HTTP://Example.com/path/?utm_source=rss&ref=abc&id=1")
        assert result == "https://example.com/path?id=1"

    def test_keeps_meaningful_query_params(self):
        # ?id=123 can distinguish genuinely different articles — must survive.
        assert normalize_url("https://x.vn/a?id=123") == "https://x.vn/a?id=123"

    def test_strips_trailing_slash(self):
        assert normalize_url("https://example.com/a/b/") == "https://example.com/a/b"

    def test_drops_fragment(self):
        assert normalize_url("https://example.com/a#section") == "https://example.com/a"

    def test_equivalent_urls_normalize_identically(self):
        a = normalize_url("https://example.com/a?id=1&utm_source=fb")
        b = normalize_url("HTTP://EXAMPLE.com/a/?utm_campaign=x&id=1")
        assert a == b

    @pytest.mark.parametrize("bad_url", ["", "   ", None])
    def test_rejects_empty_or_blank_url(self, bad_url):
        with pytest.raises(ValueError):
            normalize_url(bad_url)


# --- filter: dedup ---------------------------------------------------------
class FakeCollection:
    """Minimal stand-in: articles collection queried by url."""

    def __init__(self, urls: set[str] | None = None):
        self.urls = set(urls or set())

    def find_one(self, query: dict):
        return {"url": query["url"]} if query["url"] in self.urls else None


class TestIsDuplicate:
    def test_true_when_normalized_url_already_present(self):
        collection = FakeCollection({"https://cafef.vn/a"})
        assert rss_filter.is_duplicate("HTTP://CafeF.vn/a/?utm_source=x", collection)

    def test_false_when_not_present(self):
        assert rss_filter.is_duplicate("https://cafef.vn/b", FakeCollection()) is False


# --- filter: relevance -----------------------------------------------------
class TestIsRelevant:
    def test_drops_noise_keyword_article(self):
        assert rss_filter.is_relevant("Lễ hội khai trương chi nhánh", "") is False

    def test_keeps_financial_article(self):
        assert rss_filter.is_relevant("HPG báo lãi quý 2", "Giá thép tăng") is True

    def test_noise_match_is_accent_and_case_insensitive(self):
        assert rss_filter.is_relevant("SINH NHẬT công ty", "") is False


# --- rss_fetcher -----------------------------------------------------------
def _parsed(entries, bozo=0, exc=None):
    return SimpleNamespace(bozo=bozo, bozo_exception=exc, entries=entries)


def _fake_response(content: bytes = b""):
    """A stand-in requests.Response that passes raise_for_status()."""
    return SimpleNamespace(content=content, raise_for_status=lambda: None)


class TestFetchFeed:
    def test_captures_all_required_fields(self, monkeypatch):
        entry = {
            "link": "https://cafef.vn/a.html",
            "title": "Tiêu đề",
            "summary": "Tóm tắt",
            "published_parsed": time.struct_time((2026, 7, 17, 3, 0, 0, 0, 0, 0)),
        }
        monkeypatch.setattr(rss_fetcher.requests, "get", lambda *a, **k: _fake_response())
        monkeypatch.setattr(rss_fetcher.feedparser, "parse", lambda content: _parsed([entry]))

        [article] = rss_fetcher.fetch_feed("CafeF", "http://feed")

        assert article["url"] == "https://cafef.vn/a.html"
        assert article["title"] == "Tiêu đề"
        assert article["summary"] == "Tóm tắt"
        assert article["source"] == "CafeF"
        assert article["published_at"] is not None

    def test_entry_without_link_is_skipped(self, monkeypatch):
        entries = [{"title": "no link"}, {"link": "https://x.vn/ok"}]
        monkeypatch.setattr(rss_fetcher.requests, "get", lambda *a, **k: _fake_response())
        monkeypatch.setattr(rss_fetcher.feedparser, "parse", lambda content: _parsed(entries))

        result = rss_fetcher.fetch_feed("VnExpress", "http://feed")

        assert [a["url"] for a in result] == ["https://x.vn/ok"]

    def test_missing_timestamp_yields_none(self, monkeypatch):
        entry = {"link": "https://x.vn/a", "title": "t", "summary": "s"}
        monkeypatch.setattr(rss_fetcher.requests, "get", lambda *a, **k: _fake_response())
        monkeypatch.setattr(rss_fetcher.feedparser, "parse", lambda content: _parsed([entry]))

        [article] = rss_fetcher.fetch_feed("CafeF", "http://feed")

        assert article["published_at"] is None


class TestFetchAllFeeds:
    def test_one_bad_feed_does_not_abort_run(self, monkeypatch):
        good = {"link": "https://vnexpress.net/x.html", "title": "t", "summary": "s"}

        def fake_get(url, *a, **k):
            if "bad" in url:
                raise rss_fetcher.requests.ConnectionError("boom")
            return _fake_response()

        monkeypatch.setattr(rss_fetcher.requests, "get", fake_get)
        monkeypatch.setattr(rss_fetcher.feedparser, "parse", lambda content: _parsed([good]))

        feeds = [("CafeF", "http://bad-feed"), ("VnExpress", "http://good-feed")]
        result = rss_fetcher.fetch_all_feeds(feeds)

        # The bad feed is skipped; the good one still contributes.
        assert [a["source"] for a in result] == ["VnExpress"]

    def test_aggregates_across_feeds(self, monkeypatch):
        monkeypatch.setattr(rss_fetcher.requests, "get", lambda *a, **k: _fake_response())
        monkeypatch.setattr(
            rss_fetcher.feedparser,
            "parse",
            lambda content: _parsed([{"link": "https://x.vn/a"}, {"link": "https://x.vn/b"}]),
        )

        feeds = [("CafeF", "http://f1"), ("VnExpress", "http://f2")]
        result = rss_fetcher.fetch_all_feeds(feeds)

        assert len(result) == 4