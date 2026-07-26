"""Centroid calculations for article clusters."""

from __future__ import annotations

from numbers import Integral

import numpy as np
from numpy.typing import ArrayLike, NDArray


def _vector(value: ArrayLike, *, name: str) -> NDArray[np.floating]:
    vector = np.asarray(value)
    if vector.ndim != 1 or vector.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional vector")
    if not np.issubdtype(vector.dtype, np.number):
        raise TypeError(f"{name} must contain numeric values")

    vector = vector.astype(np.result_type(vector.dtype, np.float32), copy=False)
    if not np.isfinite(vector).all():
        raise ValueError(f"{name} must contain only finite values")
    return vector


def calculate_centroid(embeddings: ArrayLike) -> NDArray[np.floating]:
    """Return the arithmetic mean of a non-empty embedding matrix."""
    matrix = np.asarray(embeddings)
    if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] == 0:
        raise ValueError("embeddings must be a non-empty two-dimensional matrix")
    if not np.issubdtype(matrix.dtype, np.number):
        raise TypeError("embeddings must contain numeric values")

    matrix = matrix.astype(np.result_type(matrix.dtype, np.float32), copy=False)
    if not np.isfinite(matrix).all():
        raise ValueError("embeddings must contain only finite values")
    return np.mean(matrix, axis=0, dtype=matrix.dtype)


def update_centroid(
    centroid_embedding: ArrayLike,
    article_count: int,
    new_embedding: ArrayLike,
) -> NDArray[np.floating]:
    """Add one embedding to a centroid without retaining old embeddings.

    ``old + (new - old) / (n + 1)`` is algebraically identical to
    ``(n * old + new) / (n + 1)`` and avoids a potentially large
    intermediate multiplication.
    """
    if isinstance(article_count, bool) or not isinstance(article_count, Integral):
        raise TypeError("article_count must be an integer")
    if article_count < 1:
        raise ValueError("article_count must be at least 1")

    centroid = _vector(centroid_embedding, name="centroid_embedding")
    embedding = _vector(new_embedding, name="new_embedding")
    if centroid.shape != embedding.shape:
        raise ValueError(
            "centroid_embedding and new_embedding must have the same shape"
        )

    dtype = np.result_type(centroid.dtype, embedding.dtype)
    centroid = centroid.astype(dtype, copy=False)
    embedding = embedding.astype(dtype, copy=False)
    return centroid + (embedding - centroid) / (article_count + 1)
