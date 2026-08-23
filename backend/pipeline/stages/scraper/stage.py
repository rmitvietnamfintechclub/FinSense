import logging

from pymongo import UpdateOne
from pymongo.collection import Collection

from backend.core.database import get_database
from backend.core.schemas.event_cluster import EventCluster
from backend.pipeline.stages.scraper.source_client import fetch_body

logger = logging.getLogger(__name__)



def run_scraper(
    clusters: list[EventCluster], collection: Collection | None = None
) -> list[EventCluster]:
    if not clusters:
        return []
    if collection is None:
        collection = get_database().event_clusters

    operations = []
    for cluster in clusters:
        for sb in cluster.source_breakdown:
            if sb.representative_article.content_fed_to_ai:
                # Already fetched on an earlier run. Re-fetching would cost a
                # request to the source for a body we already hold, which is how
                # a re-run earns an HTTP 429 from the news site.
                continue

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