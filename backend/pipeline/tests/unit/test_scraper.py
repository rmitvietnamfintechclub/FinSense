from __future__ import annotations

from types import SimpleNamespace

import backend.pipeline.stages.scraper.stage as scraper_stage


# --- fakes -----------------------------------------------------------------
def _representative(url: str):
    """Stand-in for representative_article: only the fields run_scraper touches."""
    return SimpleNamespace(url=url, published_at=None, content_fed_to_ai=None)


def _breakdown(source: str, url: str):
    return SimpleNamespace(source=source, representative_article=_representative(url))


def _cluster(cluster_id: str, *breakdowns):
    return SimpleNamespace(cluster_id=cluster_id, source_breakdown=list(breakdowns))


def _fake_fetch(mapping: dict[str, str | None]):
    """fetch_body stub driven by a url -> body lookup. Unknown urls yield None."""
    return lambda source, url: mapping.get(url)


# --- run_scraper -----------------------------------------------------------
class TestRunScraper:
    def test_populates_content_for_each_representative(self, monkeypatch):
        cluster = _cluster(
            "evt_1",
            _breakdown("CafeF", "https://cafef.vn/a"),
            _breakdown("VnExpress", "https://vnexpress.net/a"),
        )
        monkeypatch.setattr(
            scraper_stage,
            "fetch_body",
            _fake_fetch(
                {
                    "https://cafef.vn/a": "Nội dung CafeF",
                    "https://vnexpress.net/a": "Nội dung VnExpress",
                }
            ),
        )

        [result] = scraper_stage.run_scraper([cluster])

        contents = [
            sb.representative_article.content_fed_to_ai
            for sb in result.source_breakdown
        ]
        assert contents == ["Nội dung CafeF", "Nội dung VnExpress"]

    def test_failed_scrape_leaves_content_unset(self, monkeypatch):
        cluster = _cluster("evt_1", _breakdown("CafeF", "https://cafef.vn/dead"))
        monkeypatch.setattr(scraper_stage, "fetch_body", _fake_fetch({}))

        [result] = scraper_stage.run_scraper([cluster])

        assert (
            result.source_breakdown[0].representative_article.content_fed_to_ai is None
        )

    def test_failed_scrape_does_not_block_other_sources(self, monkeypatch):
        cluster = _cluster(
            "evt_1",
            _breakdown("CafeF", "https://cafef.vn/dead"),
            _breakdown("VnExpress", "https://vnexpress.net/ok"),
        )
        monkeypatch.setattr(
            scraper_stage,
            "fetch_body",
            _fake_fetch({"https://vnexpress.net/ok": "Nội dung"}),
        )

        [result] = scraper_stage.run_scraper([cluster])

        cafef, vnexpress = result.source_breakdown
        assert cafef.representative_article.content_fed_to_ai is None
        assert vnexpress.representative_article.content_fed_to_ai == "Nội dung"

    def test_scrapes_across_multiple_clusters(self, monkeypatch):
        clusters = [
            _cluster("evt_1", _breakdown("CafeF", "https://cafef.vn/a")),
            _cluster("evt_2", _breakdown("VnExpress", "https://vnexpress.net/b")),
        ]
        monkeypatch.setattr(
            scraper_stage,
            "fetch_body",
            _fake_fetch(
                {
                    "https://cafef.vn/a": "A",
                    "https://vnexpress.net/b": "B",
                }
            ),
        )

        result = scraper_stage.run_scraper(clusters)

        assert [
            c.source_breakdown[0].representative_article.content_fed_to_ai
            for c in result
        ] == ["A", "B"]

    def test_mutates_in_place_and_returns_same_objects(self, monkeypatch):
        """run_scraper enriches the caller's clusters — flow B relies on this."""
        cluster = _cluster("evt_1", _breakdown("CafeF", "https://cafef.vn/a"))
        monkeypatch.setattr(
            scraper_stage, "fetch_body", _fake_fetch({"https://cafef.vn/a": "Nội dung"})
        )

        result = scraper_stage.run_scraper([cluster])

        assert result[0] is cluster
        assert (
            cluster.source_breakdown[0].representative_article.content_fed_to_ai
            == "Nội dung"
        )

    def test_empty_input_is_a_noop(self, monkeypatch):
        monkeypatch.setattr(scraper_stage, "fetch_body", _fake_fetch({}))
        assert scraper_stage.run_scraper([]) == []

    def test_cluster_with_no_sources_is_skipped(self, monkeypatch):
        monkeypatch.setattr(scraper_stage, "fetch_body", _fake_fetch({}))
        [result] = scraper_stage.run_scraper([_cluster("evt_empty")])
        assert result.source_breakdown == []

    def test_fetch_body_called_with_the_source_name(self, monkeypatch):
        """Dispatch is by source — a wrong source silently yields no body."""
        calls = []

        def spy(source, url):
            calls.append((source, url))
            return "body"

        monkeypatch.setattr(scraper_stage, "fetch_body", spy)
        scraper_stage.run_scraper(
            [_cluster("evt_1", _breakdown("CafeF", "https://cafef.vn/a"))]
        )

        assert calls == [("CafeF", "https://cafef.vn/a")]
