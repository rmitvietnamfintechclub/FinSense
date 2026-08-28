from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorCollection

from backend.api.features.ticker.schemas import TickerSentimentResponse
from backend.api.features.ticker.service import get_ticker_sentiment
from backend.core.config import api_settings
from backend.core.database_async import get_db
from backend.core.enums import Ticker

router = APIRouter(prefix="/api/ticker", tags=["ticker"])
EVENT_CLUSTERS_COLLECTION = "event_clusters"


def events_collection_dep() -> AsyncIOMotorCollection:
    return get_db()[EVENT_CLUSTERS_COLLECTION]


def window_param(
    window: str = Query(api_settings.DEFAULT_WINDOW, pattern="^(24h|48h|72h)$"),
) -> str:
    return window


WindowDep = Annotated[str, Depends(window_param)]
CollectionDep = Annotated[AsyncIOMotorCollection, Depends(events_collection_dep)]


@router.get("/{ticker}/sentiment", response_model=TickerSentimentResponse)
async def read_ticker_sentiment(
    ticker: str,
    window: WindowDep,
    collection: CollectionDep,
) -> TickerSentimentResponse:
    symbol = ticker.upper()
    # Without this an unknown symbol returns a 200 with score 0.0 / is_empty
    # true, which the dashboard cannot tell apart from a real quiet ticker.
    if symbol not in Ticker.__members__:
        raise HTTPException(404, f"Unknown ticker: {ticker}")
    return await get_ticker_sentiment(
        collection=collection, ticker=symbol, window=window
    )
