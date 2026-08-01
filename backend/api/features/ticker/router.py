

from __future__ import annotations

from fastapi import APIRouter, Query

from backend.api.features.ticker.schemas import TickerSentimentResponse
from backend.api.features.ticker.service import get_ticker_sentiment

router = APIRouter(prefix="/api/v1/ticker", tags=["ticker"])


@router.get("/{ticker}/sentiment", response_model=TickerSentimentResponse)
def read_ticker_sentiment(
    ticker: str,
    window: str = Query("24h", pattern="^(24h|48h|72h)$"),
) -> TickerSentimentResponse:
    return get_ticker_sentiment(ticker=ticker, window=window)