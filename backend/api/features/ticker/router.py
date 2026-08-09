from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.api.features.ticker.schemas import TickerSentimentResponse
from backend.api.features.ticker.service import get_ticker_sentiment
from backend.core.config import api_settings

router = APIRouter(prefix="/api/v1/ticker", tags=["ticker"])


@router.get("/{ticker}/sentiment", response_model=TickerSentimentResponse)
async def read_ticker_sentiment(
    ticker: str,
    window: str,
) -> TickerSentimentResponse:
    window = window or api_settings.DEFAULT_WINDOW
    if window not in api_settings.WINDOW_HOURS:
        raise HTTPException(400, f"window must be one of {api_settings.WINDOW_HOURS}")
    return await get_ticker_sentiment(ticker=ticker.upper(), window=window)