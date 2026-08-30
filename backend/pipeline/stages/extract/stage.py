import logging

from pymongo import UpdateOne
from pymongo.collection import Collection

from backend.core.database import get_database
from backend.core.schemas.event_cluster import EventCluster
from backend.pipeline.stages.extract.extractor import extract_from_text

logger = logging.getLogger(__name__)

QUOTA_FAILURE = "llm_quota_exhausted"

def run_extract(
    clusters: list[EventCluster], collection: Collection | None = None
) -> list[EventCluster]:
    if not clusters:
        return []
    if collection is None:
        collection = get_database().event_clusters

    operations = []
    quota_exhausted = False
    for cluster in clusters:
        if quota_exhausted:
            break
        for sb in cluster.source_breakdown:
            if sb.is_audited or sb.ai_response is not None:
                continue
            if not sb.representative_article.content_fed_to_ai:
                logger.warning(
                    "No scraped body for %s (%s) - skipping extraction",
                    sb.source,
                    sb.representative_article.url,
                )
                continue

            result = extract_from_text(sb.representative_article.content_fed_to_ai)
            if result.failure_type == QUOTA_FAILURE:
                logger.error(
                    "Gemini quota exhausted at %s in %s - stopping extraction, "
                    "remaining sources will be retried next run",
                    sb.source,
                    cluster.cluster_id,
                )
                quota_exhausted = True
                break
            if not result.succeeded:
                logger.warning(
                    "Extraction failed for %s in %s (%s) - leaving unset",
                    sb.source,
                    cluster.cluster_id,
                    result.failure_type,
                )
                continue

            sb.ai_response = result.ai_response
            operations.append(
                UpdateOne(
                    {"cluster_id": cluster.cluster_id},
                    {
                        "$set": {
                            "source_breakdown.$[entry].ai_response": result.ai_response.model_dump(
                                mode="json"
                            )
                        }
                    },
                    array_filters=[{"entry.source": sb.source}],
                )
            )

    if operations:
        collection.bulk_write(operations, ordered=False)
    return clusters