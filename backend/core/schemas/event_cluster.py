"""EventCluster — persisted document contract for the `event_clusters` collection."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.core.schemas.sentiment import AggregatedAnalysis, AIResponse


class RepresentativeArticle(BaseModel):
    # Nullable, never required: documents written before this field existed carry
    # no title, and a required field would fail EventCluster.model_validate on
    # every pre-existing cluster — taking down the cluster stage's carry-forward.
    # Backfill by joining representative_article.url to articles.url.
    title: str | None = None
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
    # What the AI said. Written once by the extract stage and never rewritten —
    # an admin correction lands in audited_response instead, so the accuracy
    # evaluation can always recover the model's own output. Read the pair
    # through core.corrections.effective_response, never ai_response directly.
    ai_response: AIResponse | None = None
    audited_response: AIResponse | None = None
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
