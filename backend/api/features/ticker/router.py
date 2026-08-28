from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.api.features.ticker.schemas import (
    TickerDetail,
    TickerEvents,
    TickerHistory,
    TickerSentimentResponse,
)
from backend.api.features.ticker.service import (
    get_ticker_detail,
    get_ticker_events,
    get_ticker_history,
    get_ticker_sentiment,
)
from backend.core.config import api_settings
from backend.core.database_async import get_db
from backend.core.enums import Ticker

router = APIRouter(prefix="/api/ticker", tags=["ticker"])
EVENT_CLUSTERS_COLLECTION = "event_clusters"


def db_dep() -> AsyncIOMotorDatabase:
    return get_db()


def window_param(
    window: str = Query(api_settings.DEFAULT_WINDOW, pattern="^(24h|48h|72h)$"),
) -> str:
    """Ban sao co chu dich cua dashboard/router.py::window_param — day la
    param validator (3 dong), khong phai scoring logic, nen khong nam trong
    pham vi 'dung chung, dung viet lai' cua ticket FS-37."""
    return window


def days_param(days: int = Query(api_settings.DEFAULT_TICKER_HISTORY_DAYS)) -> int:
    """Query(..., Literal[7,30,90]) looks like the obvious spelling here, but
    Pydantic's Literal validator does not coerce the '90' query string into an
    int before matching — every request 422s. Plain int + explicit membership
    check sidesteps that."""
    if days not in api_settings.TICKER_HISTORY_DAYS:
        raise HTTPException(422, f"days must be one of {api_settings.TICKER_HISTORY_DAYS}")
    return days


def valid_symbol(symbol: str) -> str:
    """Chuan hoa + xac thuc symbol truoc khi cham DB. Unknown symbol phai
    tra ve 404 (theo AC) — vi vay path param nhan str tho, KHONG type thang
    thanh enum Ticker (FastAPI se tu tra 422 cho gia tri sai enum, khong phai 404)."""
    upper = symbol.upper()
    if upper not in Ticker.__members__:
        raise HTTPException(404, f"Unknown ticker symbol: {symbol}")
    return upper


# ============================================================
# Task 5b — GET /ticker/{symbol}
# ============================================================


@router.get("/{symbol}", response_model=TickerDetail)
async def read_ticker_detail(
    symbol: str,
    window: str = Depends(window_param),
    db: AsyncIOMotorDatabase = Depends(db_dep),
) -> TickerDetail:
    symbol = valid_symbol(symbol)
    return await get_ticker_detail(db, symbol=symbol, window=window)


# ============================================================
# GET /ticker/{symbol}/history
# ============================================================


@router.get("/{symbol}/history", response_model=TickerHistory)
async def read_ticker_history(
    symbol: str,
    days: int = Depends(days_param),
    db: AsyncIOMotorDatabase = Depends(db_dep),
) -> TickerHistory:
    symbol = valid_symbol(symbol)
    return await get_ticker_history(db, symbol=symbol, days=days)


# ============================================================
# Task 5c — GET /ticker/{symbol}/events
# ============================================================


@router.get("/{symbol}/events", response_model=TickerEvents)
async def read_ticker_events(
    symbol: str,
    page: int = Query(1, ge=1),
    db: AsyncIOMotorDatabase = Depends(db_dep),
) -> TickerEvents:
    symbol = valid_symbol(symbol)
    return await get_ticker_events(db, symbol=symbol, page=page)


# ============================================================
# Pre-existing (pre-FS-37) — kept as-is
# ============================================================


@router.get("/{ticker}/sentiment", response_model=TickerSentimentResponse)
async def read_ticker_sentiment(
    ticker: str,
    window: str = api_settings.DEFAULT_WINDOW,
) -> TickerSentimentResponse:
    collection = get_db()[EVENT_CLUSTERS_COLLECTION]
    if window not in api_settings.WINDOW_HOURS:
        raise HTTPException(400, f"window must be one of {api_settings.WINDOW_HOURS}")
    return await get_ticker_sentiment(collection=collection, ticker=ticker.upper(), window=window)
