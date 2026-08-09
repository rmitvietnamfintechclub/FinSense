"""Aggregate-stage entrypoint."""

from __future__ import annotations

import logging

from pymongo.collection import Collection

from backend.core.config import pipeline_settings
from backend.core.database import get_database
from backend.core.schemas.event_cluster import EventCluster
from backend.pipeline.stages.aggregate.event_aggregator import build_aggregated_analysis

logger = logging.getLogger(__name__)


def run_aggregate(
    clusters: list[EventCluster],
    collection: Collection | None = None,
    *,
    threshold: float | None = None,
) -> list[EventCluster]:
    if not clusters:
        return []
    if threshold is None:
        threshold = pipeline_settings.AI_CONFIDENCE_THRESHOLD
    if collection is None:
        collection = get_database().event_clusters

    for cluster in clusters:
        analysis = build_aggregated_analysis(cluster.source_breakdown, threshold)
        cluster.aggregated_analysis = analysis
        collection.update_one(
            {"cluster_id": cluster.cluster_id},
            {"$set": {"aggregated_analysis": analysis.model_dump(mode="json")}},
        )
        logger.info(
            "Aggregated %s: %d tickers, %d concepts",
            cluster.cluster_id,
            len(analysis.ticker_sentiments),
            len(analysis.concept_sentiments),
        )
    return clusters