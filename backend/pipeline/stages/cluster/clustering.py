"""Incremental cosine-similarity clustering implemented with NumPy."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from numbers import Integral, Real
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

from backend.core.config import pipeline_settings
from backend.pipeline.stages.cluster.centroid import update_centroid

DEFAULT_SIMILARITY_THRESHOLD = pipeline_settings.CLUSTER_SIMILARITY_THRESHOLD


@dataclass(slots=True)
class Cluster:
    """Mutable state needed to assign new articles to one event cluster.

    ``article_indices`` contains indices from the current input batch only;
    ``article_count`` includes both historical and newly assigned articles.
    """

    cluster_id: str
    centroid_embedding: NDArray[np.floating]
    article_count: int
    article_indices: list[int] = field(default_factory=list)
    is_new: bool = False


@dataclass(frozen=True, slots=True)
class ClusteringResult:
    """Clusters after assignment plus one positional result per input row."""

    clusters: tuple[Cluster, ...]
    assignments: tuple[str, ...]
    similarities: NDArray[np.float64]
    new_cluster_ids: tuple[str, ...]


ClusterInput = Cluster | Mapping[str, Any]


def _embedding_matrix(embeddings: ArrayLike) -> NDArray[np.floating]:
    matrix = np.asarray(embeddings)
    if matrix.ndim == 1 and matrix.size == 0:
        return np.empty((0, 0), dtype=np.float32)
    if matrix.ndim != 2:
        raise ValueError("article_embeddings must be a two-dimensional matrix")
    if matrix.shape[0] and matrix.shape[1] == 0:
        raise ValueError("article_embeddings must have at least one column")
    if not np.issubdtype(matrix.dtype, np.number):
        raise TypeError("article_embeddings must contain numeric values")

    matrix = matrix.astype(np.result_type(matrix.dtype, np.float32), copy=False)
    if not np.isfinite(matrix).all():
        raise ValueError("article_embeddings must contain only finite values")
    if matrix.shape[0] and np.any(np.linalg.norm(matrix, axis=1) == 0):
        raise ValueError("article_embeddings must not contain zero vectors")
    return matrix


def _cluster_count(value: Mapping[str, Any]) -> Any:
    if "article_count" in value:
        return value["article_count"]

    coverage = value.get("event_coverage")
    if isinstance(coverage, Mapping) and "total_articles" in coverage:
        return coverage["total_articles"]
    raise ValueError(
        "an existing cluster needs article_count or event_coverage.total_articles"
    )


def _coerce_cluster(value: ClusterInput, *, dimension: int | None) -> Cluster:
    if isinstance(value, Cluster):
        cluster_id = value.cluster_id
        centroid = value.centroid_embedding
        article_count = value.article_count
    elif isinstance(value, Mapping):
        try:
            cluster_id = value["cluster_id"]
            centroid = value["centroid_embedding"]
        except KeyError as error:
            raise ValueError(f"existing cluster is missing {error.args[0]}") from error
        article_count = _cluster_count(value)
    else:
        raise TypeError("existing_clusters must contain Cluster or mapping values")

    if not isinstance(cluster_id, str) or not cluster_id:
        raise ValueError("cluster_id must be a non-empty string")
    if isinstance(article_count, bool) or not isinstance(article_count, Integral):
        raise TypeError("cluster article_count must be an integer")
    if article_count < 1:
        raise ValueError("cluster article_count must be at least 1")

    vector = np.asarray(centroid)
    if vector.ndim != 1 or vector.size == 0:
        raise ValueError("centroid_embedding must be a non-empty one-dimensional vector")
    if not np.issubdtype(vector.dtype, np.number):
        raise TypeError("centroid_embedding must contain numeric values")
    vector = vector.astype(np.result_type(vector.dtype, np.float32), copy=True)
    if not np.isfinite(vector).all():
        raise ValueError("centroid_embedding must contain only finite values")
    if np.linalg.norm(vector) == 0:
        raise ValueError("centroid_embedding must not be a zero vector")
    if dimension is not None and vector.shape[0] != dimension:
        raise ValueError("all centroids and article embeddings must have the same dimension")

    return Cluster(
        cluster_id=cluster_id,
        centroid_embedding=vector,
        article_count=int(article_count),
    )


def _validate_threshold(similarity_threshold: float) -> float:
    if isinstance(similarity_threshold, bool) or not isinstance(similarity_threshold, Real):
        raise TypeError("similarity_threshold must be a real number")
    threshold = float(similarity_threshold)
    if not np.isfinite(threshold) or not -1.0 <= threshold <= 1.0:
        raise ValueError("similarity_threshold must be between -1 and 1")
    return threshold


def cosine_similarities(
    embedding: ArrayLike,
    centroid_embeddings: ArrayLike,
) -> NDArray[np.float64]:
    """Return cosine similarity from one embedding to every centroid."""
    vector = np.asarray(embedding, dtype=np.float64)
    centroids = np.asarray(centroid_embeddings, dtype=np.float64)
    if vector.ndim != 1 or vector.size == 0:
        raise ValueError("embedding must be a non-empty one-dimensional vector")
    if centroids.ndim != 2 or centroids.shape[1] != vector.shape[0]:
        raise ValueError("centroid_embeddings must be a matrix with the same dimension")
    if not np.isfinite(vector).all() or not np.isfinite(centroids).all():
        raise ValueError("embeddings must contain only finite values")
    if centroids.shape[0] == 0:
        return np.empty(0, dtype=np.float64)

    vector_norm = np.linalg.norm(vector)
    centroid_norms = np.linalg.norm(centroids, axis=1)
    if vector_norm == 0 or np.any(centroid_norms == 0):
        raise ValueError("cosine similarity is undefined for zero vectors")

    scores = (centroids @ vector) / (centroid_norms * vector_norm)
    return np.clip(scores, -1.0, 1.0)


def cosine_similarity(left: ArrayLike, right: ArrayLike) -> float:
    """Return cosine similarity for two embedding vectors."""
    right_vector = np.asarray(right)
    if right_vector.ndim != 1:
        raise ValueError("right must be a one-dimensional vector")
    return float(cosine_similarities(left, right_vector[np.newaxis, :])[0])


def _default_cluster_id(existing_ids: set[str], ordinal: int) -> str:
    while True:
        candidate = f"cluster_{ordinal}"
        if candidate not in existing_ids:
            return candidate
        ordinal += 1


def cluster_articles(
    article_embeddings: ArrayLike,
    existing_clusters: Sequence[ClusterInput] = (),
    *,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    cluster_id_factory: Callable[[int], str] | None = None,
) -> ClusteringResult:
    """Assign embeddings to the closest qualifying cluster, in input order.

    A row joins the cluster with the greatest cosine similarity when that
    score is at least ``similarity_threshold``. Its centroid and count are
    updated immediately. Otherwise a singleton cluster is appended, so
    later rows in the same batch can join it.

    Existing Mongo-style mappings are accepted directly. They must contain
    ``cluster_id``, ``centroid_embedding`` and either ``article_count`` or
    ``event_coverage.total_articles``. Caller-owned cluster values are never
    mutated.
    """
    threshold = _validate_threshold(similarity_threshold)
    embeddings = _embedding_matrix(article_embeddings)
    dimension = embeddings.shape[1] or None
    clusters: list[Cluster] = []
    for cluster_input in existing_clusters:
        cluster = _coerce_cluster(cluster_input, dimension=dimension)
        if dimension is None:
            dimension = cluster.centroid_embedding.shape[0]
        clusters.append(cluster)

    existing_ids = {cluster.cluster_id for cluster in clusters}
    if len(existing_ids) != len(clusters):
        raise ValueError("cluster_id values must be unique")

    assignments: list[str] = []
    assigned_similarities: list[float] = []
    new_cluster_ids: list[str] = []

    for article_index, embedding in enumerate(embeddings):
        if clusters:
            centroids = np.stack([cluster.centroid_embedding for cluster in clusters])
            scores = cosine_similarities(embedding, centroids)
            best_index = int(np.argmax(scores))
            best_similarity = float(scores[best_index])
        else:
            best_index = -1
            best_similarity = -np.inf

        if best_index >= 0 and best_similarity >= threshold:
            cluster = clusters[best_index]
            cluster.centroid_embedding = update_centroid(
                cluster.centroid_embedding,
                cluster.article_count,
                embedding,
            )
            cluster.article_count += 1
            cluster.article_indices.append(article_index)
            assigned_similarity = best_similarity
        else:
            ordinal = len(clusters) + 1
            cluster_id = (
                cluster_id_factory(article_index)
                if cluster_id_factory is not None
                else _default_cluster_id(existing_ids, ordinal)
            )
            if not isinstance(cluster_id, str) or not cluster_id:
                raise ValueError("cluster_id_factory must return a non-empty string")
            if cluster_id in existing_ids:
                raise ValueError(f"duplicate cluster_id generated: {cluster_id}")

            cluster = Cluster(
                cluster_id=cluster_id,
                centroid_embedding=embedding.copy(),
                article_count=1,
                article_indices=[article_index],
                is_new=True,
            )
            clusters.append(cluster)
            existing_ids.add(cluster_id)
            new_cluster_ids.append(cluster_id)
            assigned_similarity = 1.0

        assignments.append(cluster.cluster_id)
        assigned_similarities.append(assigned_similarity)

    return ClusteringResult(
        clusters=tuple(clusters),
        assignments=tuple(assignments),
        similarities=np.asarray(assigned_similarities, dtype=np.float64),
        new_cluster_ids=tuple(new_cluster_ids),
    )
