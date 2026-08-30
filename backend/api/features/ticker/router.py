from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from backend.api.features.ticker.schemas import (
    TickerDetail,
    TickerDirectory,
    TickerEvents,
    TickerHistory,
    TickerSentimentResponse,
)
from backend.api.features.ticker.service import (
    get_ticker_detail,
    get_ticker_directory,
    get_ticker_events,
    get_ticker_history,
    get_ticker_sentiment,
)
from backend.core.config import api_settings
from backend.core.database_async import get_db
from backend.core.enums import Ticker

router = APIRouter(prefix="/api/ticker", tags=["ticker"])
# Separate router because the path is plural and takes no {symbol}; mounting it
# under /api/ticker would collide with the {symbol} path param.
directory_router = APIRouter(prefix="/api/tickers", tags=["ticker"])
EVENT_CLUSTERS_COLLECTION = "event_clusters"


def db_dep() -> AsyncIOMotorDatabase:
    return get_db()


def events_collection_dep() -> AsyncIOMotorCollection:
    return get_db()[EVENT_CLUSTERS_COLLECTION]


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


WindowDep = Annotated[str, Depends(window_param)]
DaysDep = Annotated[int, Depends(days_param)]
SymbolDep = Annotated[str, Depends(valid_symbol)]
DbDep = Annotated[AsyncIOMotorDatabase, Depends(db_dep)]
CollectionDep = Annotated[AsyncIOMotorCollection, Depends(events_collection_dep)]


# ============================================================
# Task 5b — GET /ticker/{symbol}
# ============================================================


@router.get("/{symbol}", response_model=TickerDetail)
async def read_ticker_detail(
    symbol: SymbolDep,
    window: WindowDep,
    db: DbDep,
) -> TickerDetail:
    return await get_ticker_detail(db, symbol=symbol, window=window)


# ============================================================
# GET /ticker/{symbol}/history
# ============================================================


@router.get("/{symbol}/history", response_model=TickerHistory)
async def read_ticker_history(
    symbol: SymbolDep,
    days: DaysDep,
    db: DbDep,
) -> TickerHistory:
    return await get_ticker_history(db, symbol=symbol, days=days)


# ============================================================
# Task 5c — GET /ticker/{symbol}/events
# ============================================================


@router.get("/{symbol}/events", response_model=TickerEvents)
async def read_ticker_events(
    symbol: SymbolDep,
    window: WindowDep,
    db: DbDep,
    page: int = Query(1, ge=1),
) -> TickerEvents:
    return await get_ticker_events(db, symbol=symbol, page=page, window=window)


# ============================================================
# GET /api/tickers — the VN30 directory, for the search box
# ============================================================


@directory_router.get("", response_model=TickerDirectory)
def read_ticker_directory() -> TickerDirectory:
    """Not async: it reads a cached in-process dict, never the database, so an
    async def would only add an event-loop hop."""
    return get_ticker_directory()


# ============================================================
# Pre-existing (pre-FS-37). Path param stays {ticker} by request; the
# 404-on-unknown-symbol behaviour is now shared with the routes above,
# replacing the old 400-on-bad-window check.
# ============================================================


@router.get("/{ticker}/sentiment", response_model=TickerSentimentResponse)
async def read_ticker_sentiment(
    ticker: str,
    window: WindowDep,
    collection: CollectionDep,
) -> TickerSentimentResponse:
    symbol = valid_symbol(ticker)
    return await get_ticker_sentiment(
        collection=collection, ticker=symbol, window=window
    )
