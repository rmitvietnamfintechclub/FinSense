"""Stage 3 (cluster) — turns cleaned articles into embedding vectors.

This is the foundation the rest of the cluster stage depends on:
clustering.py groups these vectors, centroid.py picks a representative
article per group. Both consume embed_articles() positionally, so the
order guarantee documented there is load-bearing, not a style choice.
"""
from __future__ import annotations

import logging
from datetime import datetime
from functools import lru_cache

import numpy as np
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

from backend.core.config import E5_QUERY_PREFIX, EMBEDDING_DIM, EMBEDDING_MODEL_NAME

logger = logging.getLogger(__name__)


class Article(BaseModel):
    """Proposed article contract for the whole pipeline.

    No Article model existed in core/ or a clean stage at the time this
    was written (the pipeline currently has rss/ and scraper/ stages,
    no clean/). This is a first draft the team may revise once later
    stages land — treat the field set as a starting point, not final.
    """

    title: str
    summary: str
    url: str
    source: str
    published_at: datetime
    full_content: str | None = None


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    """Load the sentence-transformer model once per process.

    Loading (reading weights from disk/network) takes seconds; encoding
    a batch takes milliseconds. lru_cache means every call to
    embed_articles() within a process reuses the same loaded model
    instead of reloading it per call.
    """
    logger.info(
        "Loading embedding model %s (dim=%d)", EMBEDDING_MODEL_NAME, EMBEDDING_DIM
    )
    return SentenceTransformer(EMBEDDING_MODEL_NAME)


def _build_embedding_text(article: Article) -> str:
    """Build the string embedded for one article.

    Title carries the most signal for what an article is about; summary
    adds supporting context, so title comes first. The E5 prefix is
    applied last — see E5_QUERY_PREFIX in core/config.py for why it's
    required on every input.
    """
    text = f"{article.title} {article.summary}".strip()
    return f"{E5_QUERY_PREFIX}{text}"


def embed_articles(articles: list[Article]) -> np.ndarray:
    """Embed articles into a (len(articles), EMBEDDING_DIM) float32 array.

    ORDER GUARANTEE (load-bearing): row i of the returned array
    corresponds to articles[i]. Downstream clustering and centroid
    selection index back into the original article list by position —
    this function must never sort, filter, dedupe, or otherwise reorder
    its input.

    Articles with a missing/empty title or summary are still embedded
    (just on whatever text remains) rather than skipped, since skipping
    would break the order guarantee above.
    """
    if not articles:
        return np.empty((0, EMBEDDING_DIM), dtype=np.float32)

    texts = [_build_embedding_text(article) for article in articles]
    model = _get_model()
    embeddings = model.encode(texts, batch_size=32, convert_to_numpy=True, show_progress_bar=False)
    return embeddings.astype(np.float32)
