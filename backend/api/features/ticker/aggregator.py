from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.core.config import APISettings, api_settings
from backend.core.database import get_database
from backend.core.formulas import blend_s_final, recency_weight, time_weighted_average

# Ten collection da xac nhan voi MongoDB Schema Reference ban moi nhat
EVENT_CLUSTERS_COLLECTION = "event_clusters"
STATIC_ONTOLOGY_COLLECTION = "static_ontology"


def compute_live_sentiment(
    ticker: str,
    window: str,  # "24h" | "48h" | "72h"
    settings: APISettings = api_settings,
):
    now = datetime.now(timezone.utc)
    window_hours = {"24h": 24, "48h": 48, "72h": 72}[window]
    window_start = now - timedelta(hours=window_hours)

    lambda_ = settings.DECAY_LAMBDA[window] 

    db = get_database()
    events_collection = db[EVENT_CLUSTERS_COLLECTION]
    ontology_collection = db[STATIC_ONTOLOGY_COLLECTION]

    # ---------- Buoc 1: doc events hop le ----------
    # (vi du query — sua theo schema that cua event_clusters)
    cursor = events_collection.find(
        {
            "created_at": {"$gte": window_start},
            "$or": [
                {"aggregated_analysis.ticker_sentiments.ticker": ticker},
                {"aggregated_analysis.concept_sentiments": {"$exists": True}},
            ],
        }
    )
    events = list(cursor)

    ticker_scored_weights: list[tuple[float, float]] = []
    concept_scored_weights: dict[str, list[tuple[float, float]]] = {}

    for event in events:
        age_hours = (now - event["created_at"]).total_seconds() / 3600
        w_time = recency_weight(age_hours, lambda_)

        for ts in event.get("aggregated_analysis", {}).get("ticker_sentiments", []):
            if ts["ticker"] == ticker and ts["score"] is not None:
                ticker_scored_weights.append((ts["score"], w_time))

        for cs in event.get("aggregated_analysis", {}).get("concept_sentiments", []):
            if cs["score"] is None:
                continue
            concept_scored_weights.setdefault(cs["concept"], []).append(
                (cs["score"], w_time)
            )

    ticker_avg = time_weighted_average(ticker_scored_weights)
    concept_avgs = {
        concept: time_weighted_average(pairs)
        for concept, pairs in concept_scored_weights.items()
    }

    ontology_doc = ontology_collection.find_one({"ticker": ticker}) or {}
    concept_weights = {
        cw["concept"]: cw["weight"] for cw in ontology_doc.get("concept_weights", [])
    }

    result = blend_s_final(ticker_avg, concept_avgs, concept_weights)

    return {
        "ticker": ticker,
        "window": window,
        "score": round(result.score, 4),
        "is_empty": result.is_empty,
    }