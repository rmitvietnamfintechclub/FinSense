from __future__ import annotations

import backend.pipeline.stages.scraper.source_client as source_client
from backend.pipeline.stages.scraper.html_stripper import strip_html


class TestHtmlStripper:
    def test_returns_none_for_empty_input(self):
        assert strip_html(None) is None
        assert strip_html("") is None

    def test_extracts_plain_text(self):
        assert strip_html("<div><p>Xin</p><p>chào</p></div>") == "Xin chào"


class TestSourceClient:
    def test_lookup_is_case_and_whitespace_insensitive(self, monkeypatch):
        monkeypatch.setitem(
            source_client._ADAPTERS, "cafef", lambda url: "<div>Hello <b>World</b></div>"
        )
        assert source_client.fetch_body("  CafeF ", "http://x") == "Hello World"

    def test_output_is_stripped_to_text(self, monkeypatch):
        monkeypatch.setitem(
            source_client._ADAPTERS, "cafef", lambda url: "<div><p>A</p><p>B</p></div>"
        )
        assert source_client.fetch_body("cafef", "http://x") == "A B"

    def test_unknown_source_returns_none(self):
        assert source_client.fetch_body("Unknown", "http://x") is None

    def test_none_source_returns_none(self):
        assert source_client.fetch_body(None, "http://x") is None
