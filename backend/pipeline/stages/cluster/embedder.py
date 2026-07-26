from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

from backend.core.config import pipeline_settings
from backend.core.schemas.article import Article

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)  # Load the sentence-transformer model once per process
def _get_model() -> SentenceTransformer:
    model = SentenceTransformer(pipeline_settings.EMBEDDING_MODEL_NAME)
    logger.info(
        "Loaded embedding model %s (dim=%d)",
        pipeline_settings.EMBEDDING_MODEL_NAME,
        model.get_embedding_dimension(),
    )
    return model


def _embedding_dim() -> int:
    return _get_model().get_embedding_dimension()


def _build_embedding_text(article: Article) -> str:
    title = article.title.strip()
    summary = article.summary.strip()

    if not title and not summary:
        logger.warning(
            "Article has no title or summary, embedding prefix-only text: %s",
            article.url,
        )

    text = " ".join(part for part in (title, summary) if part)
    return f"{pipeline_settings.E5_QUERY_PREFIX}{text}"


def embed_articles(articles: list[Article]) -> np.ndarray:
    if not articles:
        return np.empty((0, _embedding_dim()), dtype=np.float32)

    model = _get_model()
    texts = [_build_embedding_text(article) for article in articles]
    embeddings = model.encode(
        texts,
        batch_size=pipeline_settings.EMBEDDING_BATCH_SIZE,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return embeddings.astype(np.float32)
