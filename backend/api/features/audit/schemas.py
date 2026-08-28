"""
backend/api/features/audit/schemas.py

Response/request models for the admin audit panel. Shapes are fixed by the
audit section of docs/openapi.yaml, which was rewritten to match the panel UI:
the queue is FLAT — one row per (cluster_id, source) — because a source entry,
not a cluster, is what an admin approves or corrects.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from backend.core.enums import Concept, Ticker


class AuditStatus(StrEnum):
    PENDING = "pending"
    AUDITED = "audited"
    ALL = "all"


class AuditSort(StrEnum):
    NEWEST = "newest"
    OLDEST = "oldest"
    CONFIDENCE_DESC = "confidence_desc"
    CONFIDENCE_ASC = "confidence_asc"


class ErrorType(StrEnum):
    """Frozen taxonomy from openapi.yaml AuditAction.error_type. Values carry
    spaces because they are the admin-facing labels rendered as chips in the
    correction form, and they are persisted verbatim into audit_log.error_type
    for the US-G5 error grouping."""

    NO_ERROR = "No error"
    WRONG_MAGNITUDE = "Wrong magnitude"
    WRONG_DIRECTION = "Wrong direction"
    WRONG_TICKER = "Wrong ticker"
    MISSED_TICKER = "Missed ticker"


# ============================================================
# GET /api/audit/summary
# ============================================================


class AuditSummary(BaseModel):
    total_articles: int = Field(..., description="Every document in `articles`")
    audited_articles: int = Field(..., description="Source entries with is_audited true")
    pending_review: int = Field(
        ...,
        description=(
            "total_articles - audited_articles, by product decision. Counts "
            "articles that were never centroid-selected and therefore have no "
            "ai_response to audit, so it does not reach zero in normal operation."
        ),
    )


# ============================================================
# GET /api/audit/articles
# ============================================================


class TickerScore(BaseModel):
    ticker: Ticker
    score: float | None = Field(..., ge=-1.0, le=1.0)


class ConceptScore(BaseModel):
    concept: Concept
    score: float | None = Field(..., ge=-1.0, le=1.0)


class LastAudit(BaseModel):
    """Feeds the 'Audited by: admin · 09:50' line on an audited row."""

    admin_name: str
    action_type: str
    error_type: str | None = None
    performed_at: datetime


class AuditArticleRow(BaseModel):
    cluster_id: str
    source: str
    article_title: str | None = Field(
        ...,
        description=(
            "Null for rows ingested before titles were persisted. The service "
            "falls back to event_title so the table never renders blank."
        ),
    )
    event_title: str
    article_url: str
    published_at: datetime
    ticker_count: int
    ai_confidence: float = Field(..., ge=0.0, le=1.0)
    is_audited: bool
    content_fed_to_ai: str | None = Field(
        ..., description="Null until the scraper stage has fetched this article's body"
    )
    model_version: str
    prompt_version: str
    ticker_sentiments: list[TickerScore]
    concept_sentiments: list[ConceptScore]
    last_audit: LastAudit | None = None


class AuditArticles(BaseModel):
    page: int
    has_more: bool
    total: int = Field(
        ..., description="Rows matching the current status/search filter, all pages"
    )
    items: list[AuditArticleRow]


# ============================================================
# PATCH /api/audit/events/{cluster_id}/{source}
# ============================================================


class AuditAction(BaseModel):
    action_type: Literal["approve", "correct"]
    error_type: ErrorType | None = Field(
        default=None, description="Required when action_type is 'correct'"
    )
    corrected_ticker_sentiments: list[TickerScore] | None = Field(
        default=None,
        description="Only the tickers being corrected — merged, not a full replacement",
    )
    corrected_concept_sentiments: list[ConceptScore] | None = Field(
        default=None,
        description="Only the concepts being corrected — merged, not a full replacement",
    )


class AuditActionResult(BaseModel):
    success: bool
    cluster_id: str
    source: str
    action_type: str
    aggregated_analysis_recomputed: bool = Field(
        ...,
        description="True when scores changed and the cluster blend was rebuilt; False for a plain approve",
    )


# ============================================================
# GET /api/audit/log
# ============================================================


class AuditLogEntry(BaseModel):
    cluster_id: str
    source: str
    admin_id: str
    admin_name: str
    action_type: str
    error_type: str | None = None
    old_ticker_sentiments: list[TickerScore] = Field(default_factory=list)
    new_ticker_sentiments: list[TickerScore] | None = None
    old_concept_sentiments: list[ConceptScore] = Field(default_factory=list)
    new_concept_sentiments: list[ConceptScore] | None = None
    performed_at: datetime


class AuditLog(BaseModel):
    page: int
    has_more: bool
    items: list[AuditLogEntry]
