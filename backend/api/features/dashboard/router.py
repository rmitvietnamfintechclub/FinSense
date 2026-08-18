from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.api.features.dashboard.schemas import (
    EventsResponse,
    GaugeResponse,
    SummaryResponse,
    TickersResponse,
)
from backend.api.features.dashboard.service import (
    get_events,
    get_gauge,
    get_summary,
    get_tickers,
)
from backend.core.config import api_settings
from backend.core.database_async import get_db

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


def window_param(
    window: str = Query(api_settings.DEFAULT_WINDOW, pattern="^(24h|48h|72h)$"),
) -> str:
    """Dung chung cho moi endpoint window-scoped — 1 cho thay doi format
    validate sau nay chi can sua o day, khong phai 3 cho."""
    return window


def db_dep() -> AsyncIOMotorDatabase:
    return get_db()


WindowDep = Annotated[str, Depends(window_param)]
DbDep = Annotated[AsyncIOMotorDatabase, Depends(db_dep)]


# FS-22 — KHONG co window param
@router.get("/summary", response_model=SummaryResponse)
async def read_summary(db: DbDep) -> SummaryResponse:
    return await get_summary(db)


# FS-23
@router.get("/gauge", response_model=GaugeResponse)
async def read_gauge(window: WindowDep, db: DbDep) -> GaugeResponse:
    return await get_gauge(db, window=window)


# FS-24
@router.get("/events", response_model=EventsResponse)
async def read_events(
    window: WindowDep,
    db: DbDep,
    limit: int = Query(api_settings.DEFAULT_EVENTS_LIMIT, ge=1, le=50),
) -> EventsResponse:
    return await get_events(db, window=window, limit=limit)


# FS-25
@router.get("/tickers", response_model=TickersResponse)
async def read_tickers(
    window: WindowDep,
    db: DbDep,
    limit: int = Query(api_settings.DEFAULT_TICKERS_LIMIT, ge=1, le=50),
) -> TickersResponse:
    return await get_tickers(db, window=window, limit=limit)
