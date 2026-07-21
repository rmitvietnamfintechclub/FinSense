"""Builds and persists EventCluster documents from clustering output.

Consumes a `Cluster` produced by `clustering.cluster_articles` plus the batch of
`Article`/embedding rows it was computed from, and turns that into the
`EventCluster` document persisted to the `event_clusters` collection.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone

import numpy as np
from numpy.typing import NDArray
from pymongo.collection import Collection

from backend.core.config import pipeline_settings
from backend.core.database import get_database
from backend.core.schemas.article import Article
from backend.core.schemas.event_cluster import (
    AggregatedAnalysis,
    EventCluster,
    EventCoverage,
    RepresentativeArticle,
    SourceBreakdown,
)
from backend.pipeline.stages.cluster.clustering import Cluster, ClusterInput, cluster_articles, cosine_similarity
from backend.pipeline.stages.cluster.embedder import embed_articles

logger = logging.getLogger(__name__)


def select_source_representatives(
    articles: Sequence[Article],
    embeddings: NDArray[np.floating],
    cluster: Cluster,
    existing: Mapping[str, RepresentativeArticle] | None = None,
) -> dict[str, RepresentativeArticle]:
    """Pick, per source, the article closest to `cluster`'s centroid.

    `existing` carries forward representatives persisted on a prior run (keyed
    by source). Each newly-assigned article's similarity to the cluster's
    updated centroid is compared against the stored `centroid_similarity` of
    the current representative for that source; the closer one wins.
    """
    best: dict[str, RepresentativeArticle] = dict(existing or {})
    for article_index in cluster.article_indices:
        article = articles[article_index]
        similarity = cosine_similarity(embeddings[article_index], cluster.centroid_embedding)
        current = best.get(article.source)
        if current is not None and current.centroid_similarity >= similarity:
            continue
        best[article.source] = RepresentativeArticle(
            url=article.url,
            published_at=article.published_at,
            content_fed_to_ai=article.full_content or "",
            centroid_similarity=similarity,
        )
    return best


def merge_event_coverage(
    articles: Sequence[Article],
    cluster: Cluster,
    existing: EventCoverage | None = None,
) -> EventCoverage:
    """Fold this batch's newly-assigned articles into the full member/URL list."""
    all_urls: dict[str, list[str]] = {
        source: list(urls) for source, urls in (existing.all_urls if existing else {}).items()
    }
    for article_index in cluster.article_indices:
        article = articles[article_index]
        urls = all_urls.setdefault(article.source, [])
        if article.url not in urls:
            urls.append(article.url)

    total_articles = sum(len(urls) for urls in all_urls.values())
    return EventCoverage(total_articles=total_articles, all_urls=all_urls)


def _pick_event_title(articles: Sequence[Article], embeddings: NDArray[np.floating], cluster: Cluster) -> str:
    best_index = max(
        cluster.article_indices,
        key=lambda i: cosine_similarity(embeddings[i], cluster.centroid_embedding),
    )
    return articles[best_index].title


def build_event_cluster(
    articles: Sequence[Article],
    embeddings: NDArray[np.floating],
    cluster: Cluster,
    existing: EventCluster | None = None,
    event_title: str | None = None,
) -> EventCluster:
    """Build the EventCluster document for `cluster`, merging in `existing` state if any."""
    if not cluster.article_indices and existing is None:
        raise ValueError("cluster has no assigned articles and no existing document to update")

    existing_representatives = (
        {entry.source: entry.representative_article for entry in existing.source_breakdown} if existing else None
    )
    representatives = select_source_representatives(articles, embeddings, cluster, existing_representatives)

    existing_extras = (
        {entry.source: (entry.ai_response, entry.is_audited) for entry in existing.source_breakdown}
        if existing
        else {}
    )
    source_breakdown = [
        SourceBreakdown(
            source=source,
            representative_article=representative,
            ai_response=existing_extras.get(source, (None, False))[0],
            is_audited=existing_extras.get(source, (None, False))[1],
        )
        for source, representative in sorted(representatives.items())
    ]

    event_coverage = merge_event_coverage(articles, cluster, existing.event_coverage if existing else None)

    if event_title is None:
        event_title = existing.event_title if existing else _pick_event_title(articles, embeddings, cluster)

    now = datetime.now(timezone.utc)
    return EventCluster(
        cluster_id=cluster.cluster_id,
        event_title=event_title,
        created_at=existing.created_at if existing else now,
        updated_at=now,
        centroid_embedding=cluster.centroid_embedding.tolist(),
        event_coverage=event_coverage,
        aggregated_analysis=existing.aggregated_analysis if existing else AggregatedAnalysis(),
        source_breakdown=source_breakdown,
    )


def save_event_cluster(cluster: EventCluster, collection: Collection | None = None) -> None:
    if collection is None:
        collection = get_database().event_clusters

    collection.update_one(
        {"cluster_id": cluster.cluster_id},
        {"$set": cluster.model_dump()},
        upsert=True,
    )
    logger.info(
        "Wrote event cluster %s (%d articles across %d sources)",
        cluster.cluster_id,
        cluster.event_coverage.total_articles,
        len(cluster.source_breakdown),
    )


def upsert_event_cluster(
    articles: Sequence[Article],
    embeddings: NDArray[np.floating],
    cluster: Cluster,
    collection: Collection | None = None,
) -> EventCluster:
    """Read-modify-write: fetch any existing document for `cluster`, merge, and save."""
    if collection is None:
        collection = get_database().event_clusters

    existing_doc = collection.find_one({"cluster_id": cluster.cluster_id})
    existing = EventCluster.model_validate(existing_doc) if existing_doc else None

    event_cluster = build_event_cluster(articles, embeddings, cluster, existing=existing)
    save_event_cluster(event_cluster, collection=collection)
    return event_cluster


def load_existing_clusters(
    collection: Collection | None = None,
    lookback: timedelta | None = None,
) -> list[ClusterInput]:
    """Recent event_clusters documents eligible to receive newly-clustered articles.

    Bounded by `lookback` (default `pipeline_settings.CLUSTER_LOOKBACK_DAYS`) so a
    growing history of old events doesn't have to be scanned/compared on every run.
    Returned documents match `_coerce_cluster`'s Mapping shape directly — no
    conversion needed before passing them to `cluster_articles`.
    """
    if collection is None:
        collection = get_database().event_clusters
    if lookback is None:
        lookback = timedelta(days=pipeline_settings.CLUSTER_LOOKBACK_DAYS)

    cutoff = datetime.now(timezone.utc) - lookback
    return list(
        collection.find(
            {"updated_at": {"$gte": cutoff}},
            {"cluster_id": 1, "centroid_embedding": 1, "event_coverage.total_articles": 1},
        )
    )


def backfill_article_cluster_ids(
    articles: Sequence[Article],
    assignments: Sequence[str],
    collection: Collection | None = None,
) -> None:
    """Set `cluster_id` on each article's document in the `articles` collection.

    `assignments[i]` is the cluster_id `articles[i]` was placed into, positionally
    aligned as returned by `clustering.cluster_articles`. Articles are matched by
    `url` (the collection's dedup key); documents not yet present are left alone.
    """
    if collection is None:
        collection = get_database().articles

    for article, cluster_id in zip(articles, assignments, strict=True):
        collection.update_one({"url": article.url}, {"$set": {"cluster_id": cluster_id}})


def _generate_cluster_id(_article_index: int) -> str:
    # `load_existing_clusters` only fetches clusters within the lookback window, so
    # cluster_articles' own uniqueness check (scoped to that fetched list) can't see
    # older, aged-out cluster_ids. A counter-style id could collide with one of those
    # and silently merge into an unrelated document via upsert_event_cluster's
    # unscoped find-by-cluster_id — so ids must be globally unique on their own.
    return f"evt_{uuid.uuid4().hex[:12]}"


def run_cluster_stage(
    articles: Sequence[Article],
    event_clusters: Collection | None = None,
    articles_collection: Collection | None = None,
) -> list[EventCluster]:
    """Cluster-stage entrypoint: embed, assign, persist, and backfill in one pass.

    Embeds `articles`, assigns each to a recent existing cluster or a new one,
    builds/persists the resulting EventCluster documents (only for clusters that
    actually received a new article this run), and backfills `cluster_id` onto
    the matching `articles` collection documents.
    """
    if not articles:
        return []

    urls = [article.url for article in articles]
    if len(urls) != len(set(urls)):
        raise ValueError("articles must not contain duplicate URLs")

    if event_clusters is None:
        event_clusters = get_database().event_clusters
    if articles_collection is None:
        articles_collection = get_database().articles

    embeddings = embed_articles(list(articles))
    existing = load_existing_clusters(event_clusters)
    result = cluster_articles(embeddings, existing, cluster_id_factory=_generate_cluster_id)

    saved = [
        upsert_event_cluster(articles, embeddings, cluster, collection=event_clusters)
        for cluster in result.clusters
        if cluster.article_indices
    ]

    backfill_article_cluster_ids(articles, result.assignments, collection=articles_collection)
    return saved
