from __future__ import annotations

from datetime import UTC, datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.api.features.dashboard.schemas import (
    EventArticle,
    EventArticles,
    EventItem,
    EventsResponse,
    GaugeResponse,
    SummaryResponse,
    TickerItem,
    TickersResponse,
)
from backend.api.features.ticker.aggregator import age_in_hours, assemble_live_sentiment
from backend.core.config import APISettings, api_settings, pipeline_settings
from backend.core.corrections import effective_response_raw
from backend.core.enums import Ticker
from backend.core.formulas import (
    bucket_sentiment,
    clamp_score,
    recency_weight,
    time_weighted_average,
)
from backend.core.lexicon import get_concept_weights
from backend.core.ticker_metadata import get_ticker_dictionary

EVENT_CLUSTERS_COLLECTION = "event_clusters"
ARTICLES_COLLECTION = "articles"
TOTAL_TICKERS = len(Ticker)


def _window_start(window: str, now: datetime) -> datetime:
    return now - timedelta(hours=api_settings.WINDOW_HOURS[window])


def _mean_score(analysis: dict) -> float | None:
    """Flat mean of every ticker and concept score in a ticker/concept block.
    Used for both the cluster's aggregated_analysis and a single source's
    extraction, so an expanded article and the event it sits under are scored
    the same way and cannot disagree in sign."""
    scores = [
        e["score"]
        for key in ("ticker_sentiments", "concept_sentiments")
        for e in (analysis.get(key) or [])
        if e.get("score") is not None
    ]
    return sum(scores) / len(scores) if scores else None


def _event_score(event: dict) -> float | None:
    return _mean_score(event.get("aggregated_analysis") or {})


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
                company_name=get_ticker_dictionary()[Ticker(ticker)].display_name,
                event_count=row["event_count"],
                sentiment_score=round(clamp_score(result.score), 4),
                is_empty=result.is_empty,
            )
        )

    return TickersResponse(
        window=window, page=page, limit=limit, has_more=has_more, tickers=items
    )


class EventNotFoundError(Exception):
    """No cluster with that id."""


async def get_event_articles(
    db: AsyncIOMotorDatabase,
    cluster_id: str,
    settings: APISettings = api_settings,
) -> EventArticles:
    """Backs the dashboard's expand-in-place row. Not window-scoped: the row was
    already selected by a windowed query, and re-filtering its own contents by
    time would make an event expand into nothing.

    Sub-threshold sources are excluded, matching the ticker detail page and
    matching what aggregated_analysis was actually blended from — showing a
    source the score ignored would explain the number wrongly.
    """
    event = await db[EVENT_CLUSTERS_COLLECTION].find_one({"cluster_id": cluster_id})
    if event is None:
        raise EventNotFoundError(f"No event cluster {cluster_id!r}")

    threshold = pipeline_settings.AI_CONFIDENCE_THRESHOLD
    event_title = event.get("event_title") or ""
    articles: list[EventArticle] = []

    for source in event.get("source_breakdown") or []:
        # An admin correction has to be visible on the public dashboard too.
        response = effective_response_raw(source) or {}
        confidence = response.get("ai_confidence")
        if confidence is None or confidence < threshold:
            continue
        rep = source.get("representative_article") or {}
        articles.append(
            EventArticle(
                source=source.get("source") or "",
                article_title=rep.get("title") or event_title,
                article_url=rep.get("url") or "",
                published_at=rep.get("published_at") or event["created_at"],
                score=_mean_score(response),
                ai_confidence=confidence,
            )
        )

    articles.sort(key=lambda a: a.published_at, reverse=True)
    return EventArticles(
        cluster_id=cluster_id,
        event_title=event_title,
        total_articles=(event.get("event_coverage") or {}).get("total_articles") or 0,
        articles_shown=len(articles),
        articles=articles,
    )
