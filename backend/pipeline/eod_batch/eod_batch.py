from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pymongo import UpdateOne

from backend.core.corrections import effective_response_raw
from backend.core.enums import Ticker
from backend.core.formulas import confidence_weighted_avg
from backend.pipeline.eod_batch.real_price import get_closing_price

logger = logging.getLogger(__name__)
 
ICT = ZoneInfo("Asia/Ho_Chi_Minh")
 
EVENT_CLUSTERS_COLLECTION = "event_clusters"
DAILY_SENTIMENT_HISTORY_COLLECTION = "daily_sentiment_history"
 
 
def ict_day_bounds_utc(target_date: date) -> tuple[datetime, datetime]:
    start_ict = datetime.combine(target_date, time.min, tzinfo=ICT)
    end_ict = start_ict + timedelta(days=1)
    return start_ict.astimezone(UTC), end_ict.astimezone(UTC)
 
 
def utc_to_ict_date(utc_dt: datetime) -> date:
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=UTC)
    return utc_dt.astimezone(ICT).date()
 
 
def compute_target_date(now_utc: datetime | None = None) -> date:
    now = now_utc or datetime.now(UTC)
    today_ict = utc_to_ict_date(now)
    return today_ict - timedelta(days=1)
 
 
def _collect_ticker_scores(
    events: list[dict], ticker: str, confidence_threshold: float
) -> tuple[list[float], list[float], set[str]]:
    scores: list[float] = []
    confidences: list[float] = []
    contributing_event_ids: set[str] = set()
 
    for event in events:
        event_id = event.get("cluster_id") or str(event.get("_id"))
        for source in event.get("source_breakdown", []):
            # An admin correction is the better number by definition, and
            # re-running a past day is the documented repair path — so the
            # rollup reads it, not the AI's original.
            response = effective_response_raw(source) or {}
            confidence = response.get("ai_confidence")
            if confidence is None or confidence < confidence_threshold:
                continue
            for ts in response.get("ticker_sentiments", []):
                if ts.get("ticker") != ticker or ts.get("score") is None:
                    continue
                scores.append(ts["score"])
                confidences.append(confidence)
                contributing_event_ids.add(event_id)
 
    return scores, confidences, contributing_event_ids
 
 
def run_eod_batch(
    target_date: date,
    db,
    confidence_threshold: float,
    price_adapter: Callable[[str, date], float | None] = get_closing_price
) -> dict:
    start_utc, end_utc = ict_day_bounds_utc(target_date)
    date_str = target_date.isoformat()
 
    collection = db[EVENT_CLUSTERS_COLLECTION]
    history_collection = db[DAILY_SENTIMENT_HISTORY_COLLECTION]
 
    stats = {"tickers_processed": 0, "tickers_with_score": 0, "date": date_str}

    operations = []
    # Keyed on created_at, not updated_at: updated_at is bumped on every rewrite of
    # the cluster, so an event that gains an article the next day would silently move
    # out of this day's row and a re-run would not reproduce the original score.
    all_events = list(collection.find({"created_at": {"$gte": start_utc, "$lt": end_utc}}))
    for ticker_member in Ticker:
        ticker = ticker_member.value
 
        scores, confidences, contributing_ids = _collect_ticker_scores(all_events, ticker, confidence_threshold)
        daily_score = confidence_weighted_avg(
            scores, confidences, threshold=confidence_threshold
        )
 
        # The adapter is injected, so its failure modes are open-ended. One
        # ticker's price must never abort the other 29 rows.
        try:
            closing_price = price_adapter(ticker, target_date)
        except Exception as e:  # noqa: BLE001
            logger.warning("Price adapter failed for %s on %s: %s", ticker, date_str, e)
            closing_price = None
 
        record = {
            "ticker": ticker,
            "date": date_str,
            "daily_sentiment_score": daily_score,
            "data_points_used": len(contributing_ids),
        }
        update: dict = {"$set": record}

        # A None price means either "no price exists" (weekend, holiday) or "the
        # fetch failed" — the adapter cannot tell them apart. Writing it would let
        # a re-run whose fetch failed erase a price an earlier run already stored,
        # and re-running a past day is the documented repair path. $setOnInsert
        # still seeds the field as null on the row's first write.
        if closing_price is None:
            update["$setOnInsert"] = {"closing_price": None}
        else:
            record["closing_price"] = closing_price
 
        operations.append(
            UpdateOne(
                {"ticker": ticker, "date": date_str},
                update,
                upsert=True,
            )
        )
 
        stats["tickers_processed"] += 1
        if daily_score is not None:
            stats["tickers_with_score"] += 1

    if operations:
        history_collection.bulk_write(operations, ordered=False)
 
    logger.info("EOD batch complete for %s: %s", date_str, stats)
    return stats
 
 
if __name__ == "__main__":
    import sys
 
    from backend.core.config import pipeline_settings
    from backend.core.database import get_database
    from backend.core.log import setup_logging
 
    # Without this the root logger stays at WARNING with no handler, so every
    # logger.info below — including the run summary — is dropped and a healthy
    # nightly run leaves an empty log.
    setup_logging()
 
    target = compute_target_date()
    if len(sys.argv) > 1:
        # cho phep re-run tay: python -m backend.pipeline.eod_batch.eod_batch 2026-08-09
        target = date.fromisoformat(sys.argv[1])
 
    logger.info("EOD batch starting for %s (ICT)", target.isoformat())
 
    db = get_database()
    run_eod_batch(
        target_date=target,
        db=db,
        confidence_threshold=pipeline_settings.AI_CONFIDENCE_THRESHOLD,
        price_adapter=get_closing_price
    )

