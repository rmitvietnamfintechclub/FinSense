from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.api.features.ticker.schemas import TickerSentimentResponse
from backend.api.features.ticker.service import get_ticker_sentiment
from backend.core.config import api_settings
from backend.core.database_async import get_db

router = APIRouter(prefix="/api/v1/ticker", tags=["ticker"])
EVENT_CLUSTERS_COLLECTION = "event_clusters"


@router.get("/{ticker}/sentiment", response_model=TickerSentimentResponse)
async def read_ticker_sentiment(
    ticker: str,
    window: str = api_settings.DEFAULT_WINDOW,
) -> TickerSentimentResponse:
    collection = get_db()[EVENT_CLUSTERS_COLLECTION]
    if window not in api_settings.WINDOW_HOURS:
        raise HTTPException(400, f"window must be one of {api_settings.WINDOW_HOURS}")
    return await get_ticker_sentiment(collection=collection, ticker=ticker.upper(), window=window)