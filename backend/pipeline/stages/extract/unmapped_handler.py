import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def log_unmapped_concept(concept: str, article_id: str | None = None) -> None:
    logger.warning(
        "Unmapped concept dropped: concept=%s article_id=%s",
        concept,
        article_id,
        extra={
            "concept": concept,
            "article_id": article_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
