from __future__ import annotations

from datetime import UTC, datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.api.features.dashboard.schemas import (
    EventItem,
    EventsResponse,
    GaugeResponse,
    SummaryResponse,
    TickerItem,
    TickersResponse,
)
from backend.api.features.ticker.aggregator import age_in_hours, assemble_live_sentiment
from backend.core.config import APISettings, api_settings
from backend.core.enums import Ticker
from backend.core.formulas import (
    bucket_sentiment,
    clamp_score,
    recency_weight,
    time_weighted_average,
)
from backend.core.lexicon import get_concept_weights

EVENT_CLUSTERS_COLLECTION = "event_clusters"
ARTICLES_COLLECTION = "articles"
TOTAL_TICKERS = len(Ticker)


def _window_start(window: str, now: datetime) -> datetime:
    return now - timedelta(hours=api_settings.WINDOW_HOURS[window])


def _event_score(event: dict) -> float | None:
    analysis = event.get("aggregated_analysis") or {}
    scores = [
        e["score"]
        for key in ("ticker_sentiments", "concept_sentiments")
        for e in (analysis.get(key) or [])
        if e.get("score") is not None
    ]
    return sum(scores) / len(scores) if scores else None


def _source_counts(event: dict) -> dict[str, int]:
    all_urls = (event.get("event_coverage") or {}).get("all_urls") or {}
    return {source: len(urls or []) for source, urls in all_urls.items()}


async def get_summary(db: AsyncIOMotorDatabase) -> SummaryResponse:
    total_articles = await db[ARTICLES_COLLECTION].count_documents({})
    total_events = await db[EVENT_CLUSTERS_COLLECTION].count_documents({})
    latest = await db[EVENT_CLUSTERS_COLLECTION].find_one({}, sort=[("updated_at", -1)])
    return SummaryResponse(
        total_tickers=TOTAL_TICKERS,
        total_articles=total_articles,
        total_events=total_events,
        last_updated=(latest or {}).get("updated_at"),
    )


async def get_gauge(
    db: AsyncIOMotorDatabase, window: str, settings: APISettings = api_settings
) -> GaugeResponse:
    now = datetime.now(UTC)
    lambda_ = settings.DECAY_LAMBDA[window]
    threshold = settings.SENTIMENT_BUCKET_THRESHOLD

    cursor = db[EVENT_CLUSTERS_COLLECTION].find(
        {"updated_at": {"$gte": _window_start(window, now)}}
    )
    events = await cursor.to_list(length=None)

    scored_weights: list[tuple[float, float]] = []
    buckets = {"positive": 0, "neutral": 0, "negative": 0}

    for event in events:
        s_event = _event_score(event)
        if s_event is None:
            continue
        age_hours = age_in_hours(now, event["updated_at"])
        scored_weights.append((s_event, recency_weight(age_hours, lambda_)))
        buckets[bucket_sentiment(s_event, threshold)] += 1

    market_score = time_weighted_average(scored_weights)
    return GaugeResponse(
        window=window,
        market_score=round(clamp_score(market_score), 4) if market_score is not None else 0.0,
        is_empty=market_score is None,
        positive_count=buckets["positive"],
        neutral_count=buckets["neutral"],
        negative_count=buckets["negative"],
        scored_events=len(scored_weights),
        total_events_in_window=len(events),
    )


async def get_events(
    db: AsyncIOMotorDatabase, window: str, page: int, limit: int
) -> EventsResponse:
    now = datetime.now(UTC)
    skip = (page - 1) * limit
    cursor = (
        db[EVENT_CLUSTERS_COLLECTION]
        .find({"updated_at": {"$gte": _window_start(window, now)}})
        .sort("event_coverage.total_articles", -1)
        .skip(skip)
        .limit(limit + 1)  # one extra row is the has_more probe, never returned
    )
    events = await cursor.to_list(length=limit + 1)
    has_more = len(events) > limit
    events = events[:limit]

    items = [
        EventItem(
            rank=skip + offset + 1,
            cluster_id=e.get("cluster_id") or "",
            event_title=e.get("event_title") or "",
            total_articles=(e.get("event_coverage") or {}).get("total_articles") or 0,
            sources=_source_counts(e),
            tickers_mentioned=[
                ts["ticker"]
                for ts in ((e.get("aggregated_analysis") or {}).get("ticker_sentiments") or [])
                if ts.get("ticker") in Ticker.__members__
            ],
        )
        for offset, e in enumerate(events)
    ]
    return EventsResponse(
        window=window, page=page, limit=limit, has_more=has_more, events=items
    )


async def get_tickers(
    db: AsyncIOMotorDatabase, window: str, page: int, limit: int,
    settings: APISettings = api_settings,
) -> TickersResponse:
    now = datetime.now(UTC)
    window_start = _window_start(window, now)
    lambda_ = settings.DECAY_LAMBDA[window]
    collection = db[EVENT_CLUSTERS_COLLECTION]
    skip = (page - 1) * limit

    pipeline = [
        {"$match": {"updated_at": {"$gte": window_start}}},
        {"$unwind": "$aggregated_analysis.ticker_sentiments"},
        {"$match": {
            "aggregated_analysis.ticker_sentiments.score": {"$ne": None},
            "aggregated_analysis.ticker_sentiments.ticker": {
                "$in": list(Ticker.__members__)
            },
        }},
        {"$group": {
            "_id": "$aggregated_analysis.ticker_sentiments.ticker",
            "event_count": {"$sum": 1},
        }},
        # _id breaks ties so paging is stable — $sort alone is not a total
        # order, and an unstable one silently drops or repeats rows across pages.
        {"$sort": {"event_count": -1, "_id": 1}},
        {"$skip": skip},
        {"$limit": limit + 1},
    ]
    top_tickers = await collection.aggregate(pipeline).to_list(length=limit + 1)
    has_more = len(top_tickers) > limit
    top_tickers = top_tickers[:limit]

    # ONE query for every ticker, instead of one per ticker
    events = await collection.find(
        {"updated_at": {"$gte": window_start}}
    ).to_list(length=None)

    items = []
    for offset, row in enumerate(top_tickers):
        ticker = row["_id"]
        weights = get_concept_weights(ticker)
        result = assemble_live_sentiment(ticker, events, weights, lambda_, now)
        items.append(
            TickerItem(
                rank=skip + offset + 1,
                ticker=ticker,
                event_count=row["event_count"],
                sentiment_score=round(clamp_score(result.score), 4),
                is_empty=result.is_empty,
            )
        )

    return TickersResponse(
        window=window, page=page, limit=limit, has_more=has_more, tickers=items
    )
