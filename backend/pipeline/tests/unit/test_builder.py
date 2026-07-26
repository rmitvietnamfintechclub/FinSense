"""Unit tests for building and persisting EventCluster documents."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import mongomock
import numpy as np
import pytest

from backend.core.schemas.article import Article
from backend.core.schemas.event_cluster import EventCoverage, RepresentativeArticle
from backend.pipeline.stages.cluster.clustering import Cluster
from backend.pipeline.stages.cluster.stage import (
    backfill_article_cluster_ids,
    build_event_cluster,
    load_existing_clusters,
    merge_event_coverage,
    run_cluster,
    save_event_cluster,
    select_source_representatives,
    upsert_event_cluster,
)


def _article(
    title: str, url: str, source: str, published_at: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc)
) -> Article:
    return Article(
        title=title,
        summary="summary",
        url=url,
        source=source,
        published_at=published_at,
        full_content=f"full content for {url}",
    )


def _collection() -> mongomock.collection.Collection:
    return mongomock.MongoClient().finsense.event_clusters


def test_select_source_representatives_picks_closest_per_source():
    articles = [
        _article("A1", "http://a/1", "CafeF"),
        _article("A2", "http://a/2", "CafeF"),
        _article("B1", "http://b/1", "VnExpress"),
    ]
    embeddings = np.array(
        [[1.0, 0.0], [0.9, 0.1], [0.85, 0.15]],
        dtype=np.float32,
    )
    centroid = np.array([0.9, 0.1], dtype=np.float32)
    cluster = Cluster("evt_1", centroid, article_count=3, article_indices=[0, 1, 2])

    result = select_source_representatives(articles, embeddings, cluster)

    assert result["CafeF"].url == "http://a/2"
    assert result["VnExpress"].url == "http://b/1"
    assert result["CafeF"].centroid_similarity == pytest.approx(1.0, abs=1e-5)
    assert result["CafeF"].content_fed_to_ai is None


def test_select_source_representatives_keeps_closer_existing():
    articles = [_article("New", "http://a/new", "CafeF")]
    embeddings = np.array(
        [[0.0, 1.0]], dtype=np.float32
    )  # orthogonal to centroid -> similarity 0
    centroid = np.array([1.0, 0.0], dtype=np.float32)
    cluster = Cluster("evt_1", centroid, article_count=2, article_indices=[0])

    existing = {
        "CafeF": RepresentativeArticle(
            url="http://a/old",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            content_fed_to_ai="old content",
            centroid_similarity=0.95,
        )
    }

    result = select_source_representatives(articles, embeddings, cluster, existing)

    assert result["CafeF"].url == "http://a/old"


def test_select_source_representatives_replaces_when_closer():
    articles = [_article("New", "http://a/new", "CafeF")]
    embeddings = np.array([[1.0, 0.0]], dtype=np.float32)
    centroid = np.array([1.0, 0.0], dtype=np.float32)
    cluster = Cluster("evt_1", centroid, article_count=2, article_indices=[0])

    existing = {
        "CafeF": RepresentativeArticle(
            url="http://a/old",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            content_fed_to_ai="old content",
            centroid_similarity=0.5,
        )
    }

    result = select_source_representatives(articles, embeddings, cluster, existing)

    assert result["CafeF"].url == "http://a/new"
    assert result["CafeF"].centroid_similarity == pytest.approx(1.0)
    assert result["CafeF"].content_fed_to_ai is None  # swapped-in rep not yet scraped


def test_merge_event_coverage_retains_full_member_list_and_urls():
    articles = [
        _article("A1", "http://a/1", "CafeF"),
        _article("B1", "http://b/1", "VnExpress"),
    ]
    cluster = Cluster(
        "evt_1", np.array([1.0, 0.0]), article_count=2, article_indices=[0, 1]
    )
    existing = EventCoverage(total_articles=1, all_urls={"CafeF": ["http://a/0"]})

    coverage = merge_event_coverage(articles, cluster, existing)

    assert coverage.all_urls["CafeF"] == ["http://a/0", "http://a/1"]
    assert coverage.all_urls["VnExpress"] == ["http://b/1"]
    assert coverage.total_articles == 3


def test_merge_event_coverage_deduplicates_urls():
    articles = [_article("A1", "http://a/1", "CafeF")]
    cluster = Cluster(
        "evt_1", np.array([1.0, 0.0]), article_count=1, article_indices=[0]
    )
    existing = EventCoverage(total_articles=1, all_urls={"CafeF": ["http://a/1"]})

    coverage = merge_event_coverage(articles, cluster, existing)

    assert coverage.all_urls["CafeF"] == ["http://a/1"]
    assert coverage.total_articles == 1


def test_build_event_cluster_from_scratch():
    articles = [
        _article("HPG steel news", "http://a/1", "CafeF"),
        _article("HPG steel update", "http://a/2", "CafeF"),
        _article("HPG profit", "http://b/1", "VnExpress"),
    ]
    embeddings = np.array([[1.0, 0.0], [0.9, 0.1], [0.85, 0.15]], dtype=np.float32)
    centroid = np.array([0.9, 0.1], dtype=np.float32)
    cluster = Cluster("evt_hpg", centroid, article_count=3, article_indices=[0, 1, 2])

    result = build_event_cluster(articles, embeddings, cluster)

    assert result.cluster_id == "evt_hpg"
    assert (
        result.event_title == "HPG steel update"
    )  # exactly on centroid, closest overall
    assert result.centroid_embedding == pytest.approx(centroid.tolist())
    assert result.event_coverage.total_articles == 3
    assert set(result.event_coverage.all_urls.keys()) == {"CafeF", "VnExpress"}
    assert len(result.source_breakdown) == 2
    assert all(
        b.ai_response is None and b.is_audited is False for b in result.source_breakdown
    )
    assert result.created_at == result.updated_at
    assert all(
        b.representative_article.content_fed_to_ai is None
        for b in result.source_breakdown
    )


def test_build_event_cluster_merges_with_existing():
    first_articles = [_article("HPG steel news", "http://a/1", "CafeF")]
    first_embeddings = np.array([[1.0, 0.0]], dtype=np.float32)
    first_cluster = Cluster(
        "evt_hpg", np.array([1.0, 0.0]), article_count=1, article_indices=[0]
    )
    existing = build_event_cluster(first_articles, first_embeddings, first_cluster)

    second_articles = [_article("HPG profit", "http://b/1", "VnExpress")]
    second_embeddings = np.array([[0.95, 0.05]], dtype=np.float32)
    second_cluster = Cluster(
        "evt_hpg", np.array([0.95, 0.05]), article_count=2, article_indices=[0]
    )

    updated = build_event_cluster(
        second_articles, second_embeddings, second_cluster, existing=existing
    )

    assert updated.created_at == existing.created_at
    assert updated.event_title == existing.event_title
    assert updated.event_coverage.total_articles == 2
    assert set(updated.event_coverage.all_urls.keys()) == {"CafeF", "VnExpress"}
    assert len(updated.source_breakdown) == 2
    assert updated.centroid_embedding == pytest.approx([0.95, 0.05])


def test_build_event_cluster_requires_articles_or_existing():
    cluster = Cluster(
        "evt_empty", np.array([1.0, 0.0]), article_count=0, article_indices=[]
    )
    with pytest.raises(ValueError):
        build_event_cluster([], np.empty((0, 2), dtype=np.float32), cluster)


def test_save_event_cluster_upserts():
    collection = _collection()
    articles = [_article("HPG steel news", "http://a/1", "CafeF")]
    embeddings = np.array([[1.0, 0.0]], dtype=np.float32)
    cluster = Cluster(
        "evt_hpg", np.array([1.0, 0.0]), article_count=1, article_indices=[0]
    )
    event_cluster = build_event_cluster(articles, embeddings, cluster)

    save_event_cluster(event_cluster, collection=collection)
    stored = collection.find_one({"cluster_id": "evt_hpg"})
    assert stored is not None
    assert stored["event_coverage"]["total_articles"] == 1

    save_event_cluster(event_cluster, collection=collection)
    assert collection.count_documents({"cluster_id": "evt_hpg"}) == 1


def test_upsert_event_cluster_round_trip_grows_coverage():
    collection = _collection()

    first_articles = [_article("HPG steel news", "http://a/1", "CafeF")]
    first_embeddings = np.array([[1.0, 0.0]], dtype=np.float32)
    first_cluster = Cluster(
        "evt_hpg", np.array([1.0, 0.0]), article_count=1, article_indices=[0]
    )
    upsert_event_cluster(
        first_articles, first_embeddings, first_cluster, collection=collection
    )

    second_articles = [_article("HPG profit", "http://b/1", "VnExpress")]
    second_embeddings = np.array([[0.95, 0.05]], dtype=np.float32)
    second_cluster = Cluster(
        "evt_hpg", np.array([0.95, 0.05]), article_count=2, article_indices=[0]
    )
    result = upsert_event_cluster(
        second_articles, second_embeddings, second_cluster, collection=collection
    )

    assert result.event_coverage.total_articles == 2
    assert collection.count_documents({"cluster_id": "evt_hpg"}) == 1
    stored = collection.find_one({"cluster_id": "evt_hpg"})
    assert set(stored["event_coverage"]["all_urls"].keys()) == {"CafeF", "VnExpress"}


def test_load_existing_clusters_filters_by_lookback():
    collection = _collection()
    now = datetime.now(timezone.utc)
    collection.insert_one(
        {
            "cluster_id": "recent",
            "centroid_embedding": [1.0, 0.0],
            "event_coverage": {"total_articles": 2},
            "updated_at": now,
        }
    )
    collection.insert_one(
        {
            "cluster_id": "stale",
            "centroid_embedding": [0.0, 1.0],
            "event_coverage": {"total_articles": 5},
            "updated_at": now - timedelta(days=10),
        }
    )

    result = load_existing_clusters(collection, lookback=timedelta(days=3))

    assert {doc["cluster_id"] for doc in result} == {"recent"}


def test_backfill_article_cluster_ids_matches_by_url():
    collection = mongomock.MongoClient().finsense.articles
    collection.insert_one({"url": "http://a/1", "source": "CafeF", "cluster_id": None})
    collection.insert_one(
        {"url": "http://b/1", "source": "VnExpress", "cluster_id": None}
    )
    articles = [
        _article("A1", "http://a/1", "CafeF"),
        _article("B1", "http://b/1", "VnExpress"),
    ]

    backfill_article_cluster_ids(articles, ["evt_1", "evt_2"], collection=collection)

    assert collection.find_one({"url": "http://a/1"})["cluster_id"] == "evt_1"
    assert collection.find_one({"url": "http://b/1"})["cluster_id"] == "evt_2"


def test_backfill_article_cluster_ids_ignores_missing_articles():
    collection = mongomock.MongoClient().finsense.articles
    articles = [_article("Ghost", "http://missing", "CafeF")]

    backfill_article_cluster_ids(articles, ["evt_1"], collection=collection)

    assert collection.count_documents({}) == 0


def test_run_cluster_persists_and_backfills(monkeypatch):
    event_clusters = mongomock.MongoClient().finsense.event_clusters
    articles_collection = mongomock.MongoClient().finsense.articles

    articles = [
        _article("HPG steel news", "http://a/1", "CafeF"),
        _article("HPG steel update", "http://a/2", "CafeF"),
    ]
    articles_collection.insert_many(
        [{"url": a.url, "source": a.source, "cluster_id": None} for a in articles]
    )

    fake_embeddings = np.array([[1.0, 0.0], [0.95, 0.05]], dtype=np.float32)
    monkeypatch.setattr(
        "backend.pipeline.stages.cluster.stage.embed_articles",
        lambda arts: fake_embeddings,
    )

    saved = run_cluster(
        articles, event_clusters=event_clusters, articles_collection=articles_collection
    )

    assert len(saved) == 1
    assert saved[0].event_coverage.total_articles == 2
    assert event_clusters.count_documents({}) == 1
    stored_cluster_ids = {doc["cluster_id"] for doc in articles_collection.find({})}
    assert stored_cluster_ids == {saved[0].cluster_id}


def test_run_cluster_skips_untouched_existing_clusters(monkeypatch):
    event_clusters = mongomock.MongoClient().finsense.event_clusters
    articles_collection = mongomock.MongoClient().finsense.articles

    event_clusters.insert_one(
        {
            "cluster_id": "evt_old",
            "event_title": "Old event",
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "centroid_embedding": [0.0, 1.0],
            "event_coverage": {
                "total_articles": 1,
                "all_urls": {"CafeF": ["http://old/1"]},
            },
            "aggregated_analysis": {"ticker_sentiments": [], "concept_sentiments": []},
            "source_breakdown": [],
        }
    )

    articles = [_article("New unrelated event", "http://a/1", "CafeF")]
    articles_collection.insert_one(
        {"url": articles[0].url, "source": "CafeF", "cluster_id": None}
    )

    monkeypatch.setattr(
        "backend.pipeline.stages.cluster.stage.embed_articles",
        lambda arts: np.array([[1.0, 0.0]], dtype=np.float32),
    )

    saved = run_cluster(
        articles, event_clusters=event_clusters, articles_collection=articles_collection
    )

    assert len(saved) == 1
    assert saved[0].cluster_id != "evt_old"
    old_doc = event_clusters.find_one({"cluster_id": "evt_old"})
    assert old_doc["event_coverage"]["total_articles"] == 1


def test_run_cluster_empty_input_is_noop():
    assert run_cluster([]) == []


def test_run_cluster_rejects_duplicate_urls():
    articles = [
        _article("A1", "http://a/1", "CafeF"),
        _article("A1 again", "http://a/1", "VnExpress"),
    ]

    with pytest.raises(ValueError, match="duplicate"):
        run_cluster(
            articles, event_clusters=_collection(), articles_collection=_collection()
        )


def test_run_cluster_new_cluster_never_collides_with_aged_out_cluster(monkeypatch):
    event_clusters = mongomock.MongoClient().finsense.event_clusters
    articles_collection = mongomock.MongoClient().finsense.articles

    # This cluster is outside the default lookback window, so load_existing_clusters
    # won't fetch it — its auto-generated id must still never be reused.
    event_clusters.insert_one(
        {
            "cluster_id": "cluster_1",
            "event_title": "Old unrelated event",
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "updated_at": datetime.now(timezone.utc) - timedelta(days=10),
            "centroid_embedding": [0.0, 1.0],
            "event_coverage": {
                "total_articles": 1,
                "all_urls": {"CafeF": ["http://old/1"]},
            },
            "aggregated_analysis": {"ticker_sentiments": [], "concept_sentiments": []},
            "source_breakdown": [],
        }
    )

    articles = [_article("Completely different new event", "http://new/1", "CafeF")]
    articles_collection.insert_one(
        {"url": articles[0].url, "source": "CafeF", "cluster_id": None}
    )
    monkeypatch.setattr(
        "backend.pipeline.stages.cluster.stage.embed_articles",
        lambda arts: np.array([[1.0, 0.0]], dtype=np.float32),
    )

    saved = run_cluster(
        articles, event_clusters=event_clusters, articles_collection=articles_collection
    )

    assert saved[0].cluster_id != "cluster_1"
    assert event_clusters.count_documents({}) == 2

    old_doc = event_clusters.find_one({"cluster_id": "cluster_1"})
    assert old_doc["event_title"] == "Old unrelated event"
    assert old_doc["event_coverage"]["total_articles"] == 1
    assert old_doc["centroid_embedding"] == [0.0, 1.0]
