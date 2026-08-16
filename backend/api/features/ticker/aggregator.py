from __future__ import annotations

from datetime import UTC, datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorCollection

from backend.core.config import APISettings, api_settings
from backend.core.formulas import (
    SFinalResult,
    blend_s_final,
    recency_weight,
    time_weighted_average,
)
from backend.core.lexicon import get_concept_weights


# Fetch relevant clusters of the specified ticker
async def _fetch_events(ticker: str, concepts: list[str], window_start: datetime, events_collection: AsyncIOMotorCollection) -> list[dict]:
    cursor = events_collection.find(
        {
            "updated_at": {"$gte": window_start},
            "$or": [
                {"aggregated_analysis.ticker_sentiments.ticker": ticker},
                {"aggregated_analysis.concept_sentiments.concept": {"$in": concepts}},
            ],
        },
        # event_coverage/cluster_id/created_at are dead weight for
        # assemble_live_sentiment() itself, but ticker/service.py::get_ticker_detail
        # (FS-37) reuses this same fetch for its article/event counts + last_updated —
        # widened here instead of adding a second near-duplicate query.
        projection={
            "updated_at": 1,
            "aggregated_analysis": 1,
            "event_coverage": 1,
            "cluster_id": 1,
            "created_at": 1,
        },
    )
    return await cursor.to_list(length=None)


def assemble_live_sentiment(
    ticker: str,
    events: list[dict],
    concept_weights: dict[str, float],
    lambda_: float,
    now: datetime,
) -> SFinalResult:
    ticker_scored_weights: list[tuple[float, float]] = []
    concept_scored_weights: dict[str, list[tuple[float, float]]] = {c: [] for c in concept_weights}   

    for event in events:
        age_hours = (now - event["updated_at"]).total_seconds() / 3600
        w_time = recency_weight(age_hours, lambda_)

        analysis = event.get("aggregated_analysis") or {}
        for ts in analysis.get("ticker_sentiments", []):
            if ts.get("ticker") == ticker and ts.get("score") is not None:
                ticker_scored_weights.append((ts["score"], w_time))

        for cs in analysis.get("concept_sentiments", []):
            concept = cs.get("concept")
            if concept in concept_scored_weights and cs.get("score") is not None:
                concept_scored_weights[concept].append((cs["score"], w_time))

    ticker_avg = time_weighted_average(ticker_scored_weights)
    concept_avgs = {
        concept: time_weighted_average(pairs)
        for concept, pairs in concept_scored_weights.items()
    }

    return blend_s_final(ticker_avg, concept_avgs, concept_weights)


async def compute_live_sentiment(
    events_collection: AsyncIOMotorCollection,
    ticker: str,
    window: str,
    settings: APISettings = api_settings,
):
    now = datetime.now(UTC)
    window_hours = settings.WINDOW_HOURS[window]
    window_start = now - timedelta(hours=window_hours)

    lambda_ = settings.DECAY_LAMBDA[window] 

    concept_weights = get_concept_weights(ticker)
    relevant_concepts = list(concept_weights.keys())
    events = await _fetch_events(ticker, relevant_concepts, window_start, events_collection)

    result = assemble_live_sentiment(ticker, events, concept_weights, lambda_, now)

    return {
        "ticker": ticker,
        "window": window,
        "score": result.score,
        "is_empty": result.is_empty,
    }