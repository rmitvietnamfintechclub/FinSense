import logging
import random
import time
from collections.abc import Callable

from pymongo import UpdateOne
from pymongo.collection import Collection

from backend.core.config import pipeline_settings
from backend.core.database import get_database
from backend.core.schemas.event_cluster import EventCluster
from backend.pipeline.stages.scraper.source_client import fetch_body

logger = logging.getLogger(__name__)


def _pace(sleep: Callable[[float], None]) -> None:
    """Wait before the next fetch. Read from settings per call so a test (or an
    operator with a rate-limit problem) can set the delay to zero."""
    delay = pipeline_settings.SCRAPER_DELAY_SECONDS
    jitter = pipeline_settings.SCRAPER_JITTER_SECONDS
    if delay <= 0 and jitter <= 0:
        return
    sleep(delay + random.uniform(0, jitter))


def run_scraper(
    clusters: list[EventCluster],
    collection: Collection | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> list[EventCluster]:
    if not clusters:
        return []
    if collection is None:
        collection = get_database().event_clusters

    operations = []
    fetched_any = False
    for cluster in clusters:
        for sb in cluster.source_breakdown:
            if sb.representative_article.content_fed_to_ai:
                # Already fetched on an earlier run. Re-fetching would cost a
                # request to the source for a body we already hold, which is how
                # a re-run earns an HTTP 429 from the news site.
                continue

            # Paced between fetches, not before the first: a run that scrapes one
            # article should not sit idle for a second before doing it. The pacing
            # is global rather than per-host, which is stricter than needed when
            # sources interleave — deliberately, since the two feeds are polled in
            # source order and rarely do.
            if fetched_any:
                _pace(sleep)
            fetched_any = True

            full_content = fetch_body(sb.source, sb.representative_article.url)
            if full_content is None:
                logger.warning(
                    "No body content for %s (%s) - leaving content unset",
                    sb.source,
                    sb.representative_article.url,
                )
                continue
            sb.representative_article.content_fed_to_ai = full_content
            operations.append(
                UpdateOne(
                    {"cluster_id": cluster.cluster_id},
                    {"$set": {"source_breakdown.$[entry].representative_article.content_fed_to_ai": full_content}},
                    array_filters=[{"entry.source": sb.source}],
                )
            )

    if operations:
        collection.bulk_write(operations, ordered=False)
    return clusters