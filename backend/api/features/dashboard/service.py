"""
backend/api/features/dashboard/service.py (bo sung FS-23, FS-24, FS-25)

Ghep vao file service.py da co get_summary() tu FS-22.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.core.config import APISettings, api_settings
from backend.core.database import get_database
from backend.core.enums import Ticker
from backend.core.formulas import (
    bucket_sentiment,
    recency_weight,
    time_weighted_average,
)
from backend.api.features.dashboard.schemas import (
    EventItem,
    EventsResponse,
    GaugeResponse,
    SummaryResponse,
    TickerItem,
    TickersResponse,
)
from backend.api.features.ticker.aggregator import compute_live_sentiment

EVENT_CLUSTERS_COLLECTION = "event_clusters"
ARTICLES_COLLECTION = "articles"

TOTAL_TICKERS = len(Ticker)

_WINDOW_HOURS = {"24h": 24, "48h": 48, "72h": 72}


def _window_start(window: str) -> datetime:
    now = datetime.now(timezone.utc)
    return now - timedelta(hours=_WINDOW_HOURS[window])


# ============================================================
# FS-22 — Summary (khong doi, giu nguyen tu ban truoc)
# ============================================================


def get_summary() -> SummaryResponse:
    db = get_database()
    total_articles = db[ARTICLES_COLLECTION].count_documents({})
    total_events = db[EVENT_CLUSTERS_COLLECTION].count_documents({})
    latest_event = db[EVENT_CLUSTERS_COLLECTION].find_one(
        {}, sort=[("updated_at", -1)]
    )
    last_updated = latest_event["updated_at"] if latest_event else None
    return SummaryResponse(
        total_tickers=TOTAL_TICKERS,
        total_articles=total_articles,
        total_events=total_events,
        last_updated=last_updated,
    )


# ============================================================
# FS-23 — Gauge
# ============================================================


def _event_score(event: dict) -> float | None:
    """
    DE XUAT (chua lead xac nhan): S_event_i = trung binh cong don gian
    cua TOAN BO entry trong ca ticker_sentiments va concept_sentiments
    cua 1 event — vi cong thuc market_score chi dung 1 so duy nhat cho
    moi event, nhung schema khong co san field "diem tong cua event".

    Tra ve None neu event khong co entry nao ca (khong the tinh).
    """
    analysis = event.get("aggregated_analysis", {})
    scores = [
        ts["score"]
        for ts in analysis.get("ticker_sentiments", [])
        if ts.get("score") is not None
    ]
    scores += [
        cs["score"]
        for cs in analysis.get("concept_sentiments", [])
        if cs.get("score") is not None
    ]
    if not scores:
        return None
    return sum(scores) / len(scores)


def get_gauge(window: str, settings: APISettings = api_settings) -> GaugeResponse:
    now = datetime.now(timezone.utc)
    lambda_ = settings.DECAY_LAMBDA[window]
    threshold = settings.SENTIMENT_BUCKET_THRESHOLD

    db = get_database()
    events = list(
        db[EVENT_CLUSTERS_COLLECTION].find(
            {"created_at": {"$gte": _window_start(window)}}
        )
    )

    scored_weights: list[tuple[float, float]] = []
    buckets = {"positive": 0, "neutral": 0, "negative": 0}

    for event in events:
        s_event = _event_score(event)
        if s_event is None:
            continue
        age_hours = (now - event["created_at"]).total_seconds() / 3600
        weight = recency_weight(age_hours, lambda_)
        scored_weights.append((s_event, weight))
        buckets[bucket_sentiment(s_event, threshold)] += 1

    market_score = time_weighted_average(scored_weights)
    is_empty = market_score is None

    return GaugeResponse(
        window=window,
        market_score=round(market_score, 4) if market_score is not None else 0.0,
        is_empty=is_empty,
        positive_count=buckets["positive"],
        neutral_count=buckets["neutral"],
        negative_count=buckets["negative"],
    )


# ============================================================
# FS-24 — Events
# ============================================================

DEFAULT_LIMIT = 5  # DE XUAT — ticket ghi "TBD", chua co lead xac nhan


def get_events(window: str, limit: int = DEFAULT_LIMIT) -> EventsResponse:
    db = get_database()
    cursor = (
        db[EVENT_CLUSTERS_COLLECTION]
        .find({"created_at": {"$gte": _window_start(window)}})
        .sort("event_coverage.total_articles", -1)
        .limit(limit)
    )

    items = []
    for event in cursor:
        coverage = event.get("event_coverage", {})
        tickers = [
            ts["ticker"]
            for ts in event.get("aggregated_analysis", {}).get("ticker_sentiments", [])
        ]
        items.append(
            EventItem(
                event_title=event.get("event_title", ""),
                total_articles=coverage.get("total_articles", 0),
                sources=list(coverage.get("all_urls", {}).keys()),
                tickers_mentioned=tickers,
            )
        )

    return EventsResponse(window=window, events=items)


# ============================================================
# FS-25 — Tickers
# ============================================================


def get_tickers(window: str, limit: int = DEFAULT_LIMIT) -> TickersResponse:
    db = get_database()

   
    pipeline = [
        {"$match": {"created_at": {"$gte": _window_start(window)}}},
        {"$unwind": "$aggregated_analysis.ticker_sentiments"},
        {
            "$match": {
                "aggregated_analysis.ticker_sentiments.score": {"$ne": None}
            }
        },
        {
            "$group": {
                "_id": "$aggregated_analysis.ticker_sentiments.ticker",
                "event_count": {"$sum": 1},
            }
        },
        {"$sort": {"event_count": -1}},
        {"$limit": limit},
    ]
    top_tickers = list(db[EVENT_CLUSTERS_COLLECTION].aggregate(pipeline))

    items = []
    for row in top_tickers:
        ticker = row["_id"]

        live = compute_live_sentiment(ticker=ticker, window=window)
        items.append(
            TickerItem(
                ticker=ticker,
                event_count=row["event_count"],
                sentiment_score=live["score"],
                is_empty=live["is_empty"],
            )
        )

    return TickersResponse(window=window, tickers=items)