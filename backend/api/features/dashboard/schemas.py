"""
backend/api/features/dashboard/schemas.py (bo sung FS-23, FS-24, FS-25)

"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SummaryResponse(BaseModel):
    total_tickers: int = Field(
        ..., description="So luong ticker trong enum Ticker (VN30) — khong doc tu DB"
    )
    total_articles: int = Field(..., description="Tong so document trong articles")
    total_events: int = Field(..., description="Tong so document trong event_clusters")
    last_updated: datetime | None = Field(
        ...,
        description=(
            "Thoi diem event_clusters.updated_at moi nhat toan he thong. "
            "null neu chua co event nao (DB rong)."
        ),
    )


# ============================================================
# FS-23 — Gauge
# ============================================================


class GaugeResponse(BaseModel):
    window: str
    market_score: float = Field(..., ge=-1.0, le=1.0)
    is_empty: bool = Field(
        ...,
        description="True neu khong co event hop le nao trong window — market_score se la 0.0 nhung KHONG phai trung tinh thuc su.",
    )
    positive_count: int
    neutral_count: int
    negative_count: int
    scored_events: int = Field(
        ...,
        description=(
            "So event da gop vao market_score. Bang tong 3 bucket. "
            "Nho hon total_events_in_window khi co event chua duoc cham diem."
        ),
    )
    total_events_in_window: int = Field(
        ...,
        description="Tong event trong window, ke ca event chua co diem nao.",
    )


# ============================================================
# FS-24 — Events
# ============================================================


class EventItem(BaseModel):
    rank: int = Field(..., description="Thu hang toan cuc, tinh ca page truoc do (1-based)")
    cluster_id: str
    event_title: str
    total_articles: int
    sources: dict[str, int] = Field(
        ...,
        description="So bai bao theo tung nguon, vd {'CafeF': 3, 'VnExpress': 1}",
    )
    tickers_mentioned: list[str]


class EventsResponse(BaseModel):
    window: str
    page: int
    limit: int
    has_more: bool
    events: list[EventItem]


# ============================================================
# FS-25 — Tickers
# ============================================================


class TickerItem(BaseModel):
    rank: int = Field(..., description="Thu hang toan cuc, tinh ca page truoc do (1-based)")
    ticker: str
    company_name: str = Field(
        ..., description="Display name tu core/data/ticker_metadata.json"
    )
    event_count: int
    sentiment_score: float = Field(..., ge=-1.0, le=1.0)
    is_empty: bool = Field(
        ..., description="True neu S_final cua rieng ticker nay la empty state"
    )


class TickersResponse(BaseModel):
    window: str
    page: int
    limit: int
    has_more: bool
    tickers: list[TickerItem]


# ============================================================
# GET /api/dashboard/events/{cluster_id}/articles
# ============================================================


class EventArticle(BaseModel):
    """One SOURCE, not one article. A source that contributed 14 articles to an
    event still has exactly one representative article with one extraction, so
    this list is shorter than `total_articles` — see `articles_shown`."""

    source: str
    article_title: str = Field(
        ..., description="Falls back to the event title for clusters written before titles were stored"
    )
    article_url: str
    published_at: datetime
    score: float | None = Field(
        None,
        ge=-1.0,
        le=1.0,
        description=(
            "Mean of this source's ticker and concept scores — the per-source "
            "counterpart of the event score the dashboard ranks on. Null when "
            "the extraction produced no scores at all: render 'no data', never 0.00."
        ),
    )
    ai_confidence: float = Field(..., ge=0.0, le=1.0)


class EventArticles(BaseModel):
    cluster_id: str
    event_title: str
    total_articles: int = Field(
        ..., description="Every article ingested into this event, including those with no extraction of their own"
    )
    articles_shown: int = Field(
        ...,
        description=(
            "len(articles). Lower than total_articles: only one representative "
            "article per source carries an extraction, and sources below "
            "AI_CONFIDENCE_THRESHOLD are excluded entirely."
        ),
    )
    articles: list[EventArticle]
