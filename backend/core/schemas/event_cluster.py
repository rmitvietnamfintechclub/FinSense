"""EventCluster — persisted document contract for the `event_clusters` collection."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.core.schemas.sentiment import AIResponse, AggregatedAnalysis


class RepresentativeArticle(BaseModel):
    url: str
    published_at: datetime
    content_fed_to_ai: str | None = None
    # Cosine similarity to the cluster centroid at selection time. Raw embeddings
    # are not retained once folded into the centroid, so this is persisted to let
    # a later pipeline run decide whether a new candidate should replace it.
    centroid_similarity: float = Field(ge=-1.0, le=1.0)


class SourceBreakdown(BaseModel):
    source: str
    representative_article: RepresentativeArticle
    ai_response: AIResponse | None = None
    is_audited: bool = False


class EventCoverage(BaseModel):
    total_articles: int
    all_urls: dict[str, list[str]] = Field(default_factory=dict)


class EventCluster(BaseModel):
    cluster_id: str
    event_title: str
    created_at: datetime
    updated_at: datetime
    centroid_embedding: list[float]
    event_coverage: EventCoverage
    aggregated_analysis: AggregatedAnalysis = Field(default_factory=AggregatedAnalysis)
    source_breakdown: list[SourceBreakdown]
