from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.api.features.dashboard.schemas import (
    EventsResponse,
    GaugeResponse,
    SummaryResponse,
    TickersResponse,
)
from backend.api.features.dashboard.service import (
    DEFAULT_LIMIT,
    get_events,
    get_gauge,
    get_summary,
    get_tickers,
)

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


def window_param(
    window: str = Query("24h", pattern="^(24h|48h|72h)$"),
) -> str:
    """Dung chung cho moi endpoint window-scoped — 1 cho thay doi format
    validate sau nay chi can sua o day, khong phai 3 cho."""
    return window


# FS-22 — KHONG co window param
@router.get("/summary", response_model=SummaryResponse)
def read_summary() -> SummaryResponse:
    return get_summary()


# FS-23
@router.get("/gauge", response_model=GaugeResponse)
def read_gauge(window: str = Depends(window_param)) -> GaugeResponse:
    return get_gauge(window=window)


# FS-24
@router.get("/events", response_model=EventsResponse)
def read_events(
    window: str = Depends(window_param),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=50),
) -> EventsResponse:
    return get_events(window=window, limit=limit)


# FS-25
@router.get("/tickers", response_model=TickersResponse)
def read_tickers(
    window: str = Depends(window_param),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=50),
) -> TickersResponse:
    return get_tickers(window=window, limit=limit)