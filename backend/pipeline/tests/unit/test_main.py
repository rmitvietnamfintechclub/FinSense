"""Unit tests for the pipeline orchestrator.

Two layers:
  1. load_unfinished_clusters — the resume query itself
  2. run_pipeline             — which stages run, on what, and when it stops

Every stage is monkeypatched: this file is about orchestration, not stage
behaviour, and each stage has its own test module.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import mongomock
import pytest

from backend.core.config import pipeline_settings
from backend.core.schemas.article import Article
from backend.core.schemas.event_cluster import (
    EventCluster,
    EventCoverage,
    RepresentativeArticle,
    SourceBreakdown,
)
from backend.core.schemas.sentiment import AIResponse
from backend.pipeline import main as pipeline_main

NOW = datetime(2026, 8, 29, 6, 0, tzinfo=UTC)


def make_cluster(cluster_id: str, *, extracted: bool) -> EventCluster:
    ai_response = (
        AIResponse(
            ticker_sentiments=[],
            concept_sentiments=[],
            ai_confidence=0.8,
            model_version="m",
            prompt_version="v3",
        )
        if extracted
        else None
    )
    return EventCluster(
        cluster_id=cluster_id,
        event_title=f"title {cluster_id}",
        created_at=NOW,
        updated_at=NOW,
        centroid_embedding=[0.1, 0.2],
        event_coverage=EventCoverage(total_articles=1, all_urls={"CafeF": ["u"]}),
        source_breakdown=[
            SourceBreakdown(
                source="CafeF",
                representative_article=RepresentativeArticle(
                    title="t",
                    url="u",
                    published_at=NOW,
                    content_fed_to_ai="body",
                    centroid_similarity=0.95,
                ),
                ai_response=ai_response,
            )
        ],
    )


def make_article(url: str) -> Article:
    return Article(
        url=url, title="t", summary="s", source="CafeF", published_at=NOW
    )


class RecordingCollection:
    """Captures the query it was handed and replays a canned result."""

    def __init__(self, docs: list[dict] | None = None):
        self.docs = docs or []
        self.queries: list[dict] = []

    def find(self, query, *args, **kwargs):
        self.queries.append(query)
        return iter(self.docs)


# --------------------------------------------------------------------------
# Layer 1: the resume query
# --------------------------------------------------------------------------


@pytest.fixture
def mongo():
    """A real (in-memory) collection, so the query is executed rather than
    compared against itself — these tests are about Mongo semantics."""
    return mongomock.MongoClient().db.event_clusters


def store(collection, cluster: EventCluster, **overrides) -> None:
    doc = cluster.model_dump()
    doc.update(overrides)
    collection.insert_one(doc)


class TestUnfinishedQuerySemantics:
    """Executed against mongomock. The read path uses only find/$elemMatch/
    $size/$exists — none of the bulk_write or array_filters gaps CLAUDE.md
    warns about apply here."""

    def test_selects_unextracted_and_skips_completed(self, mongo):
        store(mongo, make_cluster("evt_unextracted", extracted=False))
        store(mongo, make_cluster("evt_done", extracted=True),
              aggregated_analysis={"ticker_sentiments": [{"ticker": "VIC", "score": 0.4}],
                                   "concept_sentiments": []})

        result = pipeline_main.load_unfinished_clusters(mongo, exclude=set())

        assert [c.cluster_id for c in result] == ["evt_unextracted"]

    def test_a_missing_ai_response_counts_as_unextracted(self, mongo):
        # Documents written before the field existed have no key at all, which
        # means the same thing as an explicit null and must match too.
        cluster = make_cluster("evt_legacy", extracted=False)
        doc = cluster.model_dump()
        del doc["source_breakdown"][0]["ai_response"]
        mongo.insert_one(doc)

        result = pipeline_main.load_unfinished_clusters(mongo, exclude=set())

        assert [c.cluster_id for c in result] == ["evt_legacy"]

    def test_selects_a_cluster_extracted_but_never_aggregated(self, mongo):
        # Died between run_extract's bulk_write and run_aggregate's writes: the
        # LLM calls are paid for but contribute nothing until this is repaired.
        store(mongo, make_cluster("evt_stranded", extracted=True))

        result = pipeline_main.load_unfinished_clusters(mongo, exclude=set())

        assert [c.cluster_id for c in result] == ["evt_stranded"]

    def test_ignores_clusters_outside_the_lookback_window(self, mongo):
        old = make_cluster("evt_aged_out", extracted=False)
        old.updated_at = datetime.now(UTC) - timedelta(days=30)
        store(mongo, old)

        assert pipeline_main.load_unfinished_clusters(mongo, exclude=set()) == []

    def test_excluded_cluster_is_not_returned(self, mongo):
        store(mongo, make_cluster("evt_a", extracted=False))
        store(mongo, make_cluster("evt_b", extracted=False))

        result = pipeline_main.load_unfinished_clusters(mongo, exclude={"evt_a"})

        assert [c.cluster_id for c in result] == ["evt_b"]

    def test_one_unparseable_document_does_not_abort_the_run(self, mongo):
        # This query runs before every stage now, so a single legacy document
        # must not stop the pipeline doing any work at all.
        store(mongo, make_cluster("evt_ok", extracted=False))
        broken = make_cluster("evt_broken", extracted=False).model_dump()
        del broken["event_title"]  # required, non-nullable on EventCluster
        mongo.insert_one(broken)

        result = pipeline_main.load_unfinished_clusters(mongo, exclude=set())

        assert [c.cluster_id for c in result] == ["evt_ok"]


class TestLoadUnfinishedClusters:
    def test_lookback_defaults_to_the_cluster_stage_window(self):
        collection = RecordingCollection()
        before = datetime.now(UTC)

        pipeline_main.load_unfinished_clusters(collection, exclude=set())

        cutoff = collection.queries[0]["updated_at"]["$gte"]
        expected = before - timedelta(days=pipeline_settings.CLUSTER_LOOKBACK_DAYS)
        # The same window the cluster stage uses, so an article that can never be
        # scraped stops being retried instead of costing a request every run.
        assert abs((cutoff - expected).total_seconds()) < 5

    def test_explicit_lookback_overrides_the_default(self):
        collection = RecordingCollection()
        before = datetime.now(UTC)

        pipeline_main.load_unfinished_clusters(
            collection, exclude=set(), lookback=timedelta(hours=6)
        )

        cutoff = collection.queries[0]["updated_at"]["$gte"]
        assert abs((cutoff - (before - timedelta(hours=6))).total_seconds()) < 5

    def test_omits_the_exclusion_clause_when_nothing_to_exclude(self):
        collection = RecordingCollection()

        pipeline_main.load_unfinished_clusters(collection, exclude=set())

        assert "cluster_id" not in collection.queries[0]


# --------------------------------------------------------------------------
# Layer 2: orchestration
# --------------------------------------------------------------------------


class FakeDB:
    def __init__(self):
        self.articles = object()
        self.event_clusters = object()


@pytest.fixture
def stages(monkeypatch):
    """Records what each stage was called with; every stage is a no-op that
    passes its clusters straight through."""
    calls: dict[str, list] = {}

    def record(name, result=None):
        def fake(*args, **kwargs):
            calls.setdefault(name, []).append(args)
            return result if result is not None else (args[0] if args else [])

        return fake

    monkeypatch.setattr(pipeline_main, "run_scraper", record("scrape"))
    monkeypatch.setattr(pipeline_main, "run_extract", record("extract"))
    monkeypatch.setattr(pipeline_main, "run_aggregate", record("aggregate"))
    return calls


class TestRunPipeline:
    def test_resumes_unfinished_clusters_when_there_are_no_new_articles(
        self, monkeypatch, stages
    ):
        # The regression this whole change exists for: RSS filters every URL as
        # already-ingested, and the half-finished clusters from the run before
        # must still be picked up.
        unfinished = [make_cluster("evt_old", extracted=False)]
        monkeypatch.setattr(pipeline_main, "run_rss", lambda *a: [])
        monkeypatch.setattr(
            pipeline_main, "load_unfinished_clusters", lambda *a, **k: unfinished
        )

        result = pipeline_main.run_pipeline(FakeDB())

        assert [c.cluster_id for c in result] == ["evt_old"]
        assert [c.cluster_id for c in stages["extract"][0][0]] == ["evt_old"]

    def test_does_not_cluster_when_there_are_no_new_articles(
        self, monkeypatch, stages
    ):
        # run_cluster is the only writer of updated_at, and updated_at means
        # "when an article last joined this cluster" — it drives the live
        # gauge's decay. Resuming must never route back through it. This guards
        # a future change rather than the original bug: the pre-fix early return
        # also never reached run_cluster.
        def fail(*args, **kwargs):
            raise AssertionError("run_cluster must not run without new articles")

        monkeypatch.setattr(pipeline_main, "run_rss", lambda *a: [])
        monkeypatch.setattr(pipeline_main, "run_cluster", fail)
        monkeypatch.setattr(
            pipeline_main,
            "load_unfinished_clusters",
            lambda *a, **k: [make_cluster("evt_old", extracted=False)],
        )

        pipeline_main.run_pipeline(FakeDB())

    def test_stops_when_there_are_neither_new_articles_nor_unfinished_work(
        self, monkeypatch, stages
    ):
        monkeypatch.setattr(pipeline_main, "run_rss", lambda *a: [])
        monkeypatch.setattr(
            pipeline_main, "load_unfinished_clusters", lambda *a, **k: []
        )

        assert pipeline_main.run_pipeline(FakeDB()) == []
        assert stages == {}

    def test_backlog_is_processed_before_this_runs_new_clusters(
        self, monkeypatch, stages
    ):
        # run_extract stops the whole run on the first quota 429, so position in
        # this list decides what gets extracted. Fresh-first would let a
        # chronically rate-limited key spend every hourly run on new work while
        # the backlog ages out of the lookback window unfinished.
        fresh = [make_cluster("evt_new", extracted=False)]
        unfinished = [make_cluster("evt_old", extracted=False)]
        monkeypatch.setattr(pipeline_main, "run_rss", lambda *a: [make_article("u1")])
        monkeypatch.setattr(pipeline_main, "run_cluster", lambda *a: fresh)
        monkeypatch.setattr(
            pipeline_main, "load_unfinished_clusters", lambda *a, **k: unfinished
        )

        result = pipeline_main.run_pipeline(FakeDB())

        assert [c.cluster_id for c in result] == ["evt_old", "evt_new"]
        assert [c.cluster_id for c in stages["extract"][0][0]] == ["evt_old", "evt_new"]

    def test_clusters_touched_this_run_are_excluded_from_the_resume_query(
        self, monkeypatch, stages
    ):
        fresh = [make_cluster("evt_new", extracted=False)]
        seen: dict = {}

        def capture(collection, exclude, *args, **kwargs):
            seen["exclude"] = exclude
            return []

        monkeypatch.setattr(pipeline_main, "run_rss", lambda *a: [make_article("u1")])
        monkeypatch.setattr(pipeline_main, "run_cluster", lambda *a: fresh)
        monkeypatch.setattr(pipeline_main, "load_unfinished_clusters", capture)

        pipeline_main.run_pipeline(FakeDB())

        assert seen["exclude"] == {"evt_new"}
