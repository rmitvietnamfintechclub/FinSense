"""
backend/api/features/ticker/service.py

"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorCollection

from backend.api.features.ticker.aggregator import compute_live_sentiment
from backend.api.features.ticker.schemas import TickerSentimentResponse


async def get_ticker_sentiment(collection: AsyncIOMotorCollection, ticker: str, window: str) -> TickerSentimentResponse:
    result = await compute_live_sentiment(collection, ticker=ticker, window=window)
    return TickerSentimentResponse(**result)