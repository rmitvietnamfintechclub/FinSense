"""Unit tests for incremental cosine-similarity clustering."""

from __future__ import annotations

import numpy as np
import pytest

from backend.pipeline.stages.cluster.centroid import calculate_centroid, update_centroid
from backend.pipeline.stages.cluster.clustering import (
    DEFAULT_SIMILARITY_THRESHOLD,
    Cluster,
    cluster_articles,
    cosine_similarities,
    cosine_similarity,
)


def test_cosine_similarity_uses_direction_not_magnitude():
    assert cosine_similarity([2.0, 0.0], [10.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 3.0]) == pytest.approx(0.0)
    np.testing.assert_allclose(
        cosine_similarities([1.0, 0.0], [[4.0, 0.0], [0.0, 2.0], [-3.0, 0.0]]),
        [1.0, 0.0, -1.0],
    )


def test_calculate_and_incremental_centroid_equal_full_numpy_mean():
    embeddings = np.array(
        [[0.9, 0.1, 0.0], [0.8, 0.2, 0.0], [0.7, 0.2, 0.1]],
        dtype=np.float32,
    )
    expected = np.mean(embeddings, axis=0)

    centroid = calculate_centroid(embeddings[:2])
    actual = update_centroid(centroid, 2, embeddings[2])

    np.testing.assert_allclose(actual, expected, rtol=1e-6, atol=1e-7)
    assert actual.dtype == np.float32


def test_assigns_to_existing_cluster_and_recalculates_centroid():
    existing = {
        "cluster_id": "event_hpg_profit",
        "centroid_embedding": [1.0, 0.0],
        "event_coverage": {"total_articles": 2},
    }
    new_embeddings = np.array([[0.8, 0.2]], dtype=np.float32)

    result = cluster_articles(new_embeddings, [existing], similarity_threshold=0.91)

    assert result.assignments == ("event_hpg_profit",)
    assert result.new_cluster_ids == ()
    assert result.clusters[0].article_count == 3
    assert result.clusters[0].article_indices == [0]
    np.testing.assert_allclose(
        result.clusters[0].centroid_embedding,
        np.mean([[1.0, 0.0], [1.0, 0.0], [0.8, 0.2]], axis=0),
    )
    # Caller-owned persistence documents are not modified as a side effect.
    assert existing["centroid_embedding"] == [1.0, 0.0]
    assert existing["event_coverage"]["total_articles"] == 2


def test_non_matching_article_creates_singleton_then_later_article_can_join_it():
    existing = Cluster(
        cluster_id="event_profit",
        centroid_embedding=np.array([1.0, 0.0], dtype=np.float32),
        article_count=4,
    )
    new_embeddings = np.array([[0.0, 1.0], [0.05, 0.95]], dtype=np.float32)

    result = cluster_articles(new_embeddings, [existing], similarity_threshold=0.91)

    assert result.assignments == ("cluster_2", "cluster_2")
    assert result.new_cluster_ids == ("cluster_2",)
    assert result.similarities[0] == 1.0
    assert result.similarities[1] > 0.99
    assert result.clusters[0].article_count == 4
    assert result.clusters[1].article_count == 2
    assert result.clusters[1].article_indices == [0, 1]
    np.testing.assert_allclose(result.clusters[1].centroid_embedding, [0.025, 0.975])


def test_chooses_most_similar_cluster_above_threshold():
    clusters = [
        Cluster("first", np.array([1.0, 0.0]), 1),
        Cluster("second", np.array([0.8, 0.6]), 1),
    ]

    result = cluster_articles([[0.7, 0.7]], clusters, similarity_threshold=0.5)

    assert result.assignments == ("second",)
    assert result.clusters[0].article_count == 1
    assert result.clusters[1].article_count == 2


def test_similarity_equal_to_threshold_is_inclusive():
    threshold = 0.91
    embedding = [threshold, np.sqrt(1.0 - threshold**2)]
    cluster = Cluster("boundary", np.array([1.0, 0.0]), 1)

    result = cluster_articles([embedding], [cluster], similarity_threshold=threshold)

    assert result.assignments == ("boundary",)


def test_default_threshold_is_calibrated_value():
    assert DEFAULT_SIMILARITY_THRESHOLD == pytest.approx(0.91)


def test_custom_cluster_id_factory_is_used_for_new_clusters():
    result = cluster_articles(
        [[1.0, 0.0], [0.0, 1.0]],
        cluster_id_factory=lambda article_index: f"event_{article_index}",
    )

    assert result.assignments == ("event_0", "event_1")


def test_empty_batch_preserves_existing_cluster_without_mutating_it():
    original_centroid = np.array([1.0, 0.0], dtype=np.float32)
    existing = Cluster("existing", original_centroid, 3)

    result = cluster_articles(np.empty((0, 2), dtype=np.float32), [existing])

    assert result.assignments == ()
    assert result.clusters[0].article_count == 3
    assert result.clusters[0].centroid_embedding is not original_centroid
    np.testing.assert_array_equal(
        result.clusters[0].centroid_embedding, original_centroid
    )


def test_plain_empty_list_returns_empty_result():
    result = cluster_articles([])

    assert result.clusters == ()
    assert result.assignments == ()
    assert result.similarities.shape == (0,)


@pytest.mark.parametrize(
    ("embeddings", "clusters", "message"),
    [
        ([[0.0, 0.0]], (), "zero vectors"),
        ([[1.0, np.nan]], (), "finite"),
        (
            [[1.0, 0.0]],
            [{"cluster_id": "missing-count", "centroid_embedding": [1, 0]}],
            "article_count",
        ),
        (
            [[1.0, 0.0]],
            [Cluster("wrong-dimension", np.array([1.0, 0.0, 0.0]), 1)],
            "same dimension",
        ),
    ],
)
def test_rejects_invalid_cluster_inputs(embeddings, clusters, message):
    with pytest.raises((TypeError, ValueError), match=message):
        cluster_articles(embeddings, clusters)


def test_rejects_invalid_threshold_and_duplicate_cluster_ids():
    with pytest.raises(ValueError, match="between -1 and 1"):
        cluster_articles([[1.0, 0.0]], similarity_threshold=1.1)

    duplicate_clusters = [
        Cluster("same", np.array([1.0, 0.0]), 1),
        Cluster("same", np.array([0.0, 1.0]), 1),
    ]
    with pytest.raises(ValueError, match="unique"):
        cluster_articles([[1.0, 0.0]], duplicate_clusters)
