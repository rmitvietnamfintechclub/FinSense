import logging

from backend.core.schemas.event_cluster import EventCluster
from backend.pipeline.stages.scraper.source_client import fetch_body

logger = logging.getLogger(__name__)


def run_scraper(clusters: list[EventCluster]) -> list[EventCluster]:
    for cluster in clusters:
        for sb in cluster.source_breakdown:
            full_content = fetch_body(sb.source, sb.representative_article.url)
            if full_content is None:
                logger.warning(
                    f"No body content for {sb.source} ({sb.representative_article.url}) - leaving content unset"
                )
                continue
            sb.representative_article.content_fed_to_ai = full_content
    return clusters
