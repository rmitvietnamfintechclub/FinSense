"""
backend/api/features/ticker/service.py

FS-37 — Ticker detail page endpoints. GET /ticker/{symbol}, .../history,
.../events. The live-sentiment score on every one of these paths that needs
one goes through aggregator.assemble_live_sentiment() — the exact function
dashboard/service.py::get_tickers() already uses — never recomputed here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from backend.api.features.ticker.aggregator import (
    _fetch_events,
    assemble_live_sentiment,
    compute_live_sentiment,
)
from backend.api.features.ticker.schemas import (
    GaugeBreakdown,
    TickerDetail,
    TickerEventItem,
    TickerEvents,
    TickerEventSourceBreakdown,
    TickerHistory,
    TickerHistoryRow,
    TickerSentimentResponse,
)
from backend.core.config import APISettings, api_settings, pipeline_settings
from backend.core.formulas import bucket_sentiment
from backend.core.lexicon import get_concept_weights
from backend.core.ticker_metadata import get_ticker_metadata

EVENT_CLUSTERS_COLLECTION = "event_clusters"
DAILY_SENTIMENT_HISTORY_COLLECTION = "daily_sentiment_history"


async def get_ticker_sentiment(collection: AsyncIOMotorCollection, ticker: str, window: str) -> TickerSentimentResponse:
    result = await compute_live_sentiment(collection, ticker=ticker, window=window)
    return TickerSentimentResponse(**result)


# ============================================================
# Task 5b — GET /ticker/{symbol}
# ============================================================


async def get_ticker_detail(
    db: AsyncIOMotorDatabase,
    symbol: str,
    window: str,
    settings: APISettings = api_settings,
) -> TickerDetail:
    """symbol is assumed already validated + uppercased by the router
    (valid_symbol dependency) — an unknown symbol is a 404, handled there,
    never a silent empty-state here."""
    now = datetime.now(UTC)
    window_start = now - timedelta(hours=settings.WINDOW_HOURS[window])
    lambda_ = settings.DECAY_LAMBDA[window]

    concept_weights = get_concept_weights(symbol)
    # Same fetch dashboard/get_tickers relies on via assemble_live_sentiment —
    # ticker OR concept matches, because S_final blends both.
    events = await _fetch_events(
        symbol, list(concept_weights), window_start, db[EVENT_CLUSTERS_COLLECTION]
    )
    result = assemble_live_sentiment(symbol, events, concept_weights, lambda_, now)
    score = None if result.is_empty else round(result.score, 4)

    # Identity-card counts (article_count/event_count/last_updated/gauge buckets)
    # are about THIS ticker specifically, not the broader concept-matched set
    # used only for the S_final blend — narrow to events that actually mention it.
    own_events = [
        e
        for e in events
        if any(
            ts.get("ticker") == symbol
            for ts in (e.get("aggregated_analysis") or {}).get("ticker_sentiments", [])
        )
    ]

    threshold = settings.SENTIMENT_BUCKET_THRESHOLD
    buckets = {"positive": 0, "neutral": 0, "negative": 0}
    for event in own_events:
        ts_score = next(
            (
                ts.get("score")
                for ts in (event.get("aggregated_analysis") or {}).get("ticker_sentiments", [])
                if ts.get("ticker") == symbol and ts.get("score") is not None
            ),
            None,
        )
        if ts_score is not None:
            buckets[bucket_sentiment(ts_score, threshold)] += 1

    article_count = sum((e.get("event_coverage") or {}).get("total_articles", 0) for e in own_events)
    last_updated = max((e["updated_at"] for e in own_events), default=None)

    metadata = get_ticker_metadata()[symbol]

    return TickerDetail(
        ticker=symbol,
        company_name=metadata.display_name,
        sector=metadata.sector.value,
        window=window,
        sentiment_score=score,
        gauge=GaugeBreakdown(
            score=score,
            positive_count=buckets["positive"],
            neutral_count=buckets["neutral"],
            negative_count=buckets["negative"],
        ),
        article_count=article_count,
        event_count=len(own_events),
        last_updated=last_updated,
        is_empty_state=result.is_empty,
    )


# ============================================================
# GET /ticker/{symbol}/history
# ============================================================


async def get_ticker_history(db: AsyncIOMotorDatabase, symbol: str, days: int) -> TickerHistory:
    """Reads daily_sentiment_history ONLY — pre-computed by the EOD batch job,
    zero live computation here. Nulls pass through untouched: no interpolation,
    no gap-filling, ever."""
    collection = db[DAILY_SENTIMENT_HISTORY_COLLECTION]
    # date is a zero-padded 'YYYY-MM-DD' string, so lexicographic sort == chronological.
    # Take the most recent `days` rows, then reverse to oldest -> newest for the response.
    cursor = collection.find({"ticker": symbol}).sort("date", -1).limit(days)
    rows = await cursor.to_list(length=days)
    rows.reverse()

    data = [
        TickerHistoryRow(
            date=row["date"],
            daily_sentiment_score=row.get("daily_sentiment_score"),
            closing_price=row.get("closing_price"),
        )
        for row in rows
    ]
    return TickerHistory(ticker=symbol, days=days, data=data)


# ============================================================
# Task 5c — GET /ticker/{symbol}/events
# ============================================================


def _event_ticker_score(analysis: dict, symbol: str) -> float | None:
    return next(
        (
            ts.get("score")
            for ts in analysis.get("ticker_sentiments", [])
            if ts.get("ticker") == symbol
        ),
        None,
    )


def _source_breakdown_for_event(event: dict, symbol: str, threshold: float) -> list[TickerEventSourceBreakdown]:
    """One row per source (never per article — a source that contributed 5
    articles still has exactly 1 representative ai_response). Sub-threshold
    sources are excluded entirely, not shown with a greyed-out score."""
    rows: list[TickerEventSourceBreakdown] = []
    for source in event.get("source_breakdown", []):
        ai_response = source.get("ai_response") or {}
        confidence = ai_response.get("ai_confidence")
        if confidence is None or confidence < threshold:
            continue

        source_score = next(
            (
                ts.get("score")
                for ts in ai_response.get("ticker_sentiments", [])
                if ts.get("ticker") == symbol
            ),
            None,
        )
        if source_score is None:
            continue  # this source's article didn't score this ticker at all

        representative_article = source.get("representative_article") or {}
        rows.append(
            TickerEventSourceBreakdown(
                source=source.get("source", ""),
                score=source_score,
                # See TickerEventSourceBreakdown.article_title docstring — no
                # per-article title persisted yet, event_title is the closest stand-in.
                article_title=event.get("event_title", ""),
                article_url=representative_article.get("url", ""),
            )
        )
    return rows


def _build_event_item(event: dict, symbol: str, threshold: float) -> TickerEventItem:
    analysis = event.get("aggregated_analysis") or {}
    return TickerEventItem(
        cluster_id=event.get("cluster_id", ""),
        event_title=event.get("event_title", ""),
        created_at=event["created_at"],
        article_count=(event.get("event_coverage") or {}).get("total_articles", 0),
        sentiment_score=_event_ticker_score(analysis, symbol),
        source_breakdown=_source_breakdown_for_event(event, symbol, threshold),
    )


async def get_ticker_events(
    db: AsyncIOMotorDatabase,
    symbol: str,
    page: int,
    settings: APISettings = api_settings,
) -> TickerEvents:
    """No time-window filter here on purpose — this is 'recent events
    mentioning the ticker,' paginated, not a live-scoring endpoint. Task 5b's
    window (24h/48h/72h) scopes the S_final gauge; this list keeps paging
    back through the ticker's full event history regardless of how quiet
    the last 72h were."""
    page_size = settings.TICKER_EVENTS_PAGE_SIZE
    skip = (page - 1) * page_size

    query = {"aggregated_analysis.ticker_sentiments.ticker": symbol}
    cursor = (
        db[EVENT_CLUSTERS_COLLECTION]
        .find(query)
        .sort("updated_at", -1)
        .skip(skip)
        # Fetch one extra row to detect "next page exists" without a separate count query.
        .limit(page_size + 1)
    )
    fetched = await cursor.to_list(length=page_size + 1)
    has_more = len(fetched) > page_size
    page_events = fetched[:page_size]

    threshold = pipeline_settings.AI_CONFIDENCE_THRESHOLD
    items = [_build_event_item(e, symbol, threshold) for e in page_events]

    return TickerEvents(ticker=symbol, page=page, has_more=has_more, items=items)
