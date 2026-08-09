"""
backend/api/features/ticker/service.py

"""

from __future__ import annotations

from backend.api.features.ticker.aggregator import compute_live_sentiment
from backend.api.features.ticker.schemas import TickerSentimentResponse


async def get_ticker_sentiment(ticker: str, window: str) -> TickerSentimentResponse:
    result = await compute_live_sentiment(ticker=ticker, window=window)
    return TickerSentimentResponse(**result)