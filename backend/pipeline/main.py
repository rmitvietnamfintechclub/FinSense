from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from pymongo.collection import Collection

from backend.core.config import pipeline_settings
from backend.core.database import get_database
from backend.core.log import setup_logging
from backend.core.schemas.event_cluster import EventCluster
from backend.pipeline.stages.aggregate.stage import run_aggregate
from backend.pipeline.stages.cluster.stage import run_cluster
from backend.pipeline.stages.extract.stage import run_extract
from backend.pipeline.stages.rss.stage import run_rss
from backend.pipeline.stages.scraper.stage import run_scraper

logger = logging.getLogger(__name__)


def _stage(name: str, function, *args):
    """Run one stage, timing it and reporting what came out."""
    logger.info("--- %s: starting", name)
    started = time.perf_counter()
    result = function(*args)
    logger.info(
        "--- %s: done in %.1fs (%d items)",
        name,
        time.perf_counter() - started,
        len(result),
    )
    return result


def _summarise(clusters: list[EventCluster]) -> None:
    """Per-cluster state after the run: scraped, extracted, scored."""
    sources = scraped = extracted = 0

    for cluster in clusters:
        for sb in cluster.source_breakdown:
            sources += 1
            scraped += bool(sb.representative_article.content_fed_to_ai)
            extracted += sb.ai_response is not None

        scores = {
            t.ticker.value: t.score
            for t in cluster.aggregated_analysis.ticker_sentiments
        }
        logger.info(
            "%s | %s | %d sources | %s",
            cluster.cluster_id,
            cluster.event_title[:60],
            len(cluster.source_breakdown),
            scores or "no tickers",
        )

    logger.info(
        "TOTAL: %d clusters | %d sources | %d scraped | %d extracted",
        len(clusters),
        sources,
        scraped,
        extracted,
    )


def load_unfinished_clusters(
    collection: Collection,
    exclude: set[str],
    lookback: timedelta | None = None,
) -> list[EventCluster]:
    """Clusters from earlier runs still carrying a source with no ai_response.

    run_scraper, run_extract and run_aggregate were all written to resume — each
    skips a source that is already done — but nothing ever handed them a cluster
    from a previous run. run_cluster only emits clusters that received an article
    *this* run, so without this a run that dies mid-extraction leaves its clusters
    unfinished permanently: the next run's RSS finds every URL already ingested
    and stops at the gate.

    Deliberately does NOT go through run_cluster. `updated_at` is written in
    exactly one place (cluster/stage.py::build_event_cluster) and means "when an
    article last joined this cluster" — it drives the live gauge's decay and the
    cluster lookback, so finishing an extraction must not move it.

    `lookback` doubles as the retry ceiling: an article that can never be scraped
    stops being retried once it ages out, which is why no attempt counter is
    persisted on the document.
    """
    if lookback is None:
        lookback = timedelta(days=pipeline_settings.CLUSTER_LOOKBACK_DAYS)
    cutoff = datetime.now(UTC) - lookback

    # $size/$exists rather than an equality test against []: mongomock and real
    # MongoDB disagree about whether `{"$in": [None, []]}` matches an empty
    # array, and the tests run on the former while production runs on the latter.
    def _empty(field: str) -> dict:
        return {
            "$or": [
                {f"aggregated_analysis.{field}": {"$size": 0}},
                {f"aggregated_analysis.{field}": {"$exists": False}},
            ]
        }

    query: dict = {
        "updated_at": {"$gte": cutoff},
        "$or": [
            # Never extracted. A null ai_response and a missing one both match,
            # and both mean the same thing.
            {"source_breakdown": {"$elemMatch": {"ai_response": None}}},
            # Extracted but never aggregated: a run that died between
            # run_extract's bulk_write and run_aggregate's per-cluster writes
            # leaves paid-for extractions contributing nothing to the gauge or
            # the EOD rollup, and no other query would ever revisit it.
            # A cluster whose extraction genuinely found nothing also matches
            # and is re-aggregated once per run until it ages out — one
            # update_one, no LLM call, which is cheaper than persisting a
            # "genuinely empty" marker to tell the two apart.
            {
                "$and": [
                    {"source_breakdown": {"$elemMatch": {"ai_response": {"$ne": None}}}},
                    _empty("ticker_sentiments"),
                    _empty("concept_sentiments"),
                ]
            },
        ],
    }
    if exclude:
        # A cluster already being processed this run must not be loaded a second
        # time: two EventCluster objects for one cluster_id would each see the
        # same source unextracted, spend two LLM calls on it, and race on write.
        query["cluster_id"] = {"$nin": sorted(exclude)}

    clusters: list[EventCluster] = []
    for doc in collection.find(query):
        try:
            clusters.append(EventCluster.model_validate(doc))
        except ValidationError:
            # One unparseable stored document must not abort the run. This query
            # now runs before every stage, so without this a single legacy
            # document — one written before a required field existed — would
            # stop the pipeline doing any work at all, for every cluster.
            logger.warning(
                "Skipping unfinished cluster %s: stored document does not validate",
                doc.get("cluster_id"),
                exc_info=True,
            )
    return clusters


def run_pipeline(db=None) -> list[EventCluster]:
    db = db if db is not None else get_database()
    articles = db.articles
    event_clusters = db.event_clusters

    new_articles = _stage("RSS", run_rss, articles)

    clusters: list[EventCluster] = []
    if new_articles:
        clusters = _stage("CLUSTER", run_cluster, new_articles, event_clusters, articles)
    else:
        logger.info("No new articles - looking for unfinished clusters instead")

    resumed = _stage(
        "RESUME",
        load_unfinished_clusters,
        event_clusters,
        {cluster.cluster_id for cluster in clusters},
    )

    # The gate is "is there work", not "are there new articles" — the latter is
    # what stranded half-finished clusters forever.
    #
    # Backlog first: run_extract stops the whole run on the first quota 429, so
    # whichever clusters are at the front are the ones that get extracted. With
    # fresh clusters first, a chronically rate-limited key would spend every
    # hourly run on new work and let the backlog age out of the lookback window
    # unfinished — the exact outcome this function exists to prevent.
    work = resumed + clusters
    if not work:
        logger.info("No new articles and nothing unfinished - stopping")
        return []

    work = _stage("SCRAPE", run_scraper, work, event_clusters)
    work = _stage("EXTRACT", run_extract, work, event_clusters)
    work = _stage("AGGREGATE", run_aggregate, work, event_clusters)

    _summarise(work)
    return work


def main():
    setup_logging()
    started = time.perf_counter()
    run_pipeline()
    logger.info("Pipeline finished in %.1fs", time.perf_counter() - started)


if __name__ == "__main__":
    main()