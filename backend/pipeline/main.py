from __future__ import annotations

import logging
import time

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


def run_pipeline(db=None) -> list[EventCluster]:
    db = db if db is not None else get_database()
    articles = db.articles
    event_clusters = db.event_clusters

    new_articles = _stage("RSS", run_rss, articles)
    if not new_articles:
        logger.info("No new articles - stopping")
        return []

    clusters = _stage("CLUSTER", run_cluster, new_articles, event_clusters, articles)
    clusters = _stage("SCRAPE", run_scraper, clusters, event_clusters)
    clusters = _stage("EXTRACT", run_extract, clusters, event_clusters)
    clusters = _stage("AGGREGATE", run_aggregate, clusters, event_clusters)

    _summarise(clusters)
    return clusters


def main():
    setup_logging()
    started = time.perf_counter()
    run_pipeline()
    logger.info("Pipeline finished in %.1fs", time.perf_counter() - started)


if __name__ == "__main__":
    main()