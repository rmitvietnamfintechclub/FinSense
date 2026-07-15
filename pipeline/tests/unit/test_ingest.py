from __future__ import annotations

from unittest.mock import Mock, patch

import requests

from backend.pipeline.stages.rss.rss_fetcher import RSSSource, fetch_all_feeds, fetch_feed
from backend.pipeline.stages.rss.source_tagger import tag_source
from backend.pipeline.stages.rss.url_normalizer import normalize_url

SAMPLE_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Sample</title>
<item>
<title>Bai bao mau</title>
<link>https://example.com/bai-bao-mau.html?utm_source=rss&amp;ref=abc&amp;id=1</link>
<description>&lt;a href="https://example.com/bai-bao-mau.html"&gt;&lt;img src="https://example.com/thumb.jpg" /&gt;&lt;/a&gt;Tom tat bai bao</description>
<pubDate>Wed, 16 Jul 2026 09:00:00 +0700</pubDate>
</item>
<item>
<title></title>
<link>https://example.com/no-title.html</link>
<description>missing title, should be skipped</description>
</item>
</channel>
</rss>"""


def _mock_response(content: bytes) -> Mock:
    response = Mock()
    response.content = content
    response.raise_for_status = Mock()
    return response


class TestNormalizeUrl:
    def test_strips_tracking_params_lowercases_host_and_forces_https(self):
        result = normalize_url("HTTP://Example.com/path/?utm_source=rss&ref=abc&id=1")
        assert result == "https://example.com/path?id=1"


class TestTagSource:
    def test_adds_source_field_without_mutating_input(self):
        article = {"url": "https://example.com/a", "title": "t"}
        tagged = tag_source(article, "CafeF")
        assert tagged["source"] == "CafeF"
        assert "source" not in article


class TestFetchFeed:
    def test_parses_entries_and_skips_ones_missing_required_fields(self):
        source = RSSSource(name="Example", feed_url="https://example.com/rss")
        with patch(
            "backend.pipeline.stages.rss.rss_fetcher.requests.get",
            return_value=_mock_response(SAMPLE_FEED),
        ):
            articles = fetch_feed(source)

        assert len(articles) == 1
        article = articles[0]
        assert article["url"] == "https://example.com/bai-bao-mau.html?id=1"
        assert article["title"] == "Bai bao mau"
        assert article["summary"] == "Tom tat bai bao"
        assert article["source"] == "Example"
        assert article["published_at"].year == 2026


class TestFetchAllFeeds:
    def test_one_bad_feed_does_not_abort_the_run(self):
        good_source = RSSSource(name="Good", feed_url="https://good.example/rss")
        bad_source = RSSSource(name="Bad", feed_url="https://bad.example/rss")

        def fake_get(url, timeout):
            if url == bad_source.feed_url:
                raise requests.exceptions.ConnectionError("boom")
            return _mock_response(SAMPLE_FEED)

        with patch(
            "backend.pipeline.stages.rss.rss_fetcher.requests.get", side_effect=fake_get
        ):
            articles = fetch_all_feeds([bad_source, good_source])

        assert len(articles) == 1
        assert articles[0]["source"] == "Good"

    def test_http_error_on_one_feed_does_not_abort_the_run(self):
        good_source = RSSSource(name="Good", feed_url="https://good.example/rss")
        bad_source = RSSSource(name="Bad", feed_url="https://bad.example/rss")

        def fake_get(url, timeout):
            response = _mock_response(SAMPLE_FEED if url == good_source.feed_url else b"")
            if url == bad_source.feed_url:
                response.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
            return response

        with patch(
            "backend.pipeline.stages.rss.rss_fetcher.requests.get", side_effect=fake_get
        ):
            articles = fetch_all_feeds([bad_source, good_source])

        assert len(articles) == 1
        assert articles[0]["source"] == "Good"
