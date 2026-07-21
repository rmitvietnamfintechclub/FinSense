"""Unit tests for the pipeline entrypoint."""
from __future__ import annotations

from datetime import datetime

from backend.core.schemas.article import Article
from backend.pipeline.main import main


def _article(title: str, url: str) -> Article:
    return Article(
        title=title,
        summary="summary",
        url=url,
        source="CafeF",
        published_at=datetime(2026, 1, 1),
        full_content="full content",
    )


def test_main_delegates_to_run_cluster_stage(monkeypatch):
    articles = [_article("HPG steel news", "http://a/1")]
    sentinel = ["sentinel-result"]

    def fake_run_cluster_stage(passed_articles):
        assert passed_articles == articles
        return sentinel

    monkeypatch.setattr("backend.pipeline.main.run_cluster_stage", fake_run_cluster_stage)

    assert main(articles) is sentinel
