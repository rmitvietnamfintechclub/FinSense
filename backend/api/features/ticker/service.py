"""
backend/api/features/ticker/service.py

"""

from __future__ import annotations

from backend.api.features.ticker.aggregator import compute_live_sentiment
from backend.api.features.ticker.schemas import TickerSentimentResponse


def get_ticker_sentiment(ticker: str, window: str) -> TickerSentimentResponse:
    result = compute_live_sentiment(ticker=ticker, window=window)
    return TickerSentimentResponse(
        ticker=result["ticker"],
        window=result["window"],
        score=result["score"],
        is_empty=result["is_empty"],
    )