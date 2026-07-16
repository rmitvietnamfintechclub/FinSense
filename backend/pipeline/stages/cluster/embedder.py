from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

from backend.core.config import E5_QUERY_PREFIX, EMBEDDING_BATCH_SIZE, EMBEDDING_MODEL_NAME
from backend.core.schemas.article import Article

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    """Load the sentence-transformer model once per process.

    use lru_cache means every call to
    embed_articles() within a process reuses the same loaded model
    instead of reloading it per call.
    """

    model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    logger.info(
        "Loaded embedding model %s (dim=%d)",
        EMBEDDING_MODEL_NAME,
        model.get_embedding_dimension(),
    )
    return model


def _embedding_dim() -> int:
    # Model's output width, read from the model instead of a config
    # constant so it can never drift out of sync with the model in use.
    
    return _get_model().get_embedding_dimension()


def _build_embedding_text(article: Article) -> str:
    # Build the string embedded for one article.

  
    title = article.title.strip()
    summary = article.summary.strip()

    if not title and not summary:
        logger.warning("Article has no title or summary, embedding prefix-only text: %s", article.url)

    text = " ".join(part for part in (title, summary) if part)
    return f"{E5_QUERY_PREFIX}{text}"


def embed_articles(articles: list[Article]) -> np.ndarray:
    # Embed articles into a (len(articles), model_dim) float32 array.
    
    if not articles:
        return np.empty((0, _embedding_dim()), dtype=np.float32)

    model = _get_model()
    texts = [_build_embedding_text(article) for article in articles]
    embeddings = model.encode(
        texts, batch_size=EMBEDDING_BATCH_SIZE, convert_to_numpy=True, show_progress_bar=False
    )
    return embeddings.astype(np.float32)
