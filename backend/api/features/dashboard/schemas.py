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
