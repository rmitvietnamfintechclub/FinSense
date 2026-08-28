
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TickerSentimentResponse(BaseModel):
    ticker: str = Field(..., description="Ma co phieu, vd 'HPG'")
    window: str = Field(..., description="Cua so thoi gian: '24h' | '48h' | '72h'")
    score: float | None = Field(
        ..., ge=-1.0, le=1.0, description="S_final, trong khoang [-1.0, 1.0]"
    )
    is_empty: bool = Field(
        ...,
        description=(
            "True neu khong co event hop le nao trong cua so nay — "
            "score se la null (KHONG phai 0.0), vi 0.0 la mot gia tri trung "
            "tinh hop le va khong duoc lan voi 'khong co du lieu'."
        ),
    )


# ============================================================
# FS-37 — Task 5b: GET /ticker/{symbol}
# ============================================================


class GaugeBreakdown(BaseModel):
    score: float | None = Field(
        ..., ge=-1.0, le=1.0, description="S_final cua ticker trong window — null neu is_empty_state"
    )
    positive_count: int
    neutral_count: int
    negative_count: int


class TickerDetail(BaseModel):
    ticker: str
    company_name: str
    window: str
    sentiment_score: float | None = Field(
        ...,
        ge=-1.0,
        le=1.0,
        description="S_final tinh tai thoi diem request tu event_clusters — null neu khong co du lieu, KHONG PHAI 0.0.",
    )
    gauge: GaugeBreakdown
    article_count: int = Field(..., description="Tong so bai bao cua cac event nhac toi ticker nay trong window")
    event_count: int = Field(..., description="So event nhac toi ticker nay trong window")
    last_updated: datetime | None = Field(
        ..., description="updated_at moi nhat trong cac event nhac toi ticker nay — null neu khong co event nao"
    )
    is_empty_state: bool = Field(
        ..., description="True neu khong co score hop le nao trong window — sentiment_score se la null"
    )


# ============================================================
# FS-37 — Task: GET /ticker/{symbol}/history
# ============================================================


class TickerHistoryRow(BaseModel):
    date: str = Field(..., description="'YYYY-MM-DD'")
    daily_sentiment_score: float | None = Field(..., ge=-1.0, le=1.0)
    closing_price: float | None = None


class TickerHistory(BaseModel):
    ticker: str
    days: int = Field(..., description="Gia tri days duoc yeu cau (7/30/90) — KHONG phai so dong thuc te tra ve")
    data: list[TickerHistoryRow] = Field(
        ...,
        description="Oldest -> newest. Co the ngan hon `days` neu EOD batch chua chay du so ngay do — khong phai loi.",
    )


# ============================================================
# FS-37 — Task 5c: GET /ticker/{symbol}/events
# ============================================================


class TickerEventSourceBreakdown(BaseModel):
    source: str = Field(..., description="Vd 'CafeF', 'VnExpress'")
    score: float = Field(
        ..., ge=-1.0, le=1.0, description="Diem cua rieng source nay cho ticker — luon co gia tri (khong null), vi source duoi AI_CONFIDENCE_THRESHOLD da bi loai khoi list nay"
    )
    article_title: str = Field(
        ...,
        description=(
            "Title cua representative_article. Fallback ve event_title cua cluster "
            "khi title la null — clusters tao truoc khi field nay ton tai khong co title."
        ),
    )
    article_url: str = Field(..., description="URL cua representative_article cua source nay")


class TickerEventItem(BaseModel):
    cluster_id: str
    event_title: str
    created_at: datetime
    article_count: int = Field(..., description="event_coverage.total_articles — bai da ingest, co the > so dong source_breakdown")
    sentiment_score: float | None = Field(
        ...,
        ge=-1.0,
        le=1.0,
        description="Entry cua ticker nay trong aggregated_analysis.ticker_sentiments — null neu khong source nao qua threshold",
    )
    source_breakdown: list[TickerEventSourceBreakdown] = Field(
        ..., description="Chi gom source ma ai_confidence >= AI_CONFIDENCE_THRESHOLD"
    )


class TickerEvents(BaseModel):
    ticker: str
    page: int
    has_more: bool
    items: list[TickerEventItem] = Field(..., description="Newest first (updated_at desc) — full history, not window-scoped")
