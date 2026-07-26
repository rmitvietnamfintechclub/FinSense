"""Article embedding, incremental event clustering, and EventCluster persistence."""

from backend.pipeline.stages.cluster.centroid import calculate_centroid, update_centroid
from backend.pipeline.stages.cluster.clustering import (
    DEFAULT_SIMILARITY_THRESHOLD,
    Cluster,
    ClusteringResult,
    cluster_articles,
    cosine_similarities,
    cosine_similarity,
)
from backend.pipeline.stages.cluster.stage import (
    backfill_article_cluster_ids,
    build_event_cluster,
    load_existing_clusters,
    merge_event_coverage,
    run_cluster,
    save_event_cluster,
    select_source_representatives,
    upsert_event_cluster,
)

__all__ = [
    "DEFAULT_SIMILARITY_THRESHOLD",
    "Cluster",
    "ClusteringResult",
    "backfill_article_cluster_ids",
    "build_event_cluster",
    "calculate_centroid",
    "cluster_articles",
    "cosine_similarities",
    "cosine_similarity",
    "load_existing_clusters",
    "merge_event_coverage",
    "run_cluster",
    "save_event_cluster",
    "select_source_representatives",
    "update_centroid",
    "upsert_event_cluster",
]
