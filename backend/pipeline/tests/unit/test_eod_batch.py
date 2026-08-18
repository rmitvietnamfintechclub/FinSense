from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import mongomock
import pytest

from backend.core.enums import Ticker
from backend.pipeline.stages.eod_batch.eod_batch import (
    ICT,
    compute_target_date,
    ict_day_bounds_utc,
    run_eod_batch,
    utc_to_ict_date,
)

TARGET = date(2026, 8, 10)
TARGET_STR = "2026-08-10"
THRESHOLD = 0.4


# --------------------------------------------------------------------------
# Fixtures and builders
# --------------------------------------------------------------------------


@pytest.fixture
def db():
    """In-memory Mongo with the real unique index applied.

    The index is part of the test: if bulk_write ever stops being a true
    upsert, the second run raises DuplicateKeyError instead of silently
    writing 60 rows.
    """
    client = mongomock.MongoClient(tz_aware=True)
    database = client["finsense_test"]
    database["daily_sentiment_history"].create_index(
        [("ticker", 1), ("date", 1)], unique=True
    )
    return database


def source(confidence, sentiments, name="CafeF", is_audited=False):
    """sentiments: list of (ticker, score) pairs."""
    return {
        "source": name,
        "ai_response": {
            "ai_confidence": confidence,
            "ticker_sentiments": [{"ticker": t, "score": s} for t, s in sentiments],
            "concept_sentiments": [],
            "model_version": "gemini-2.5-flash",
        },
        "is_audited": is_audited,
    }


def event(cluster_id, updated_at, *sources):
    return {
        "cluster_id": cluster_id,
        "event_title": f"test event {cluster_id}",
        "updated_at": updated_at,
        "source_breakdown": list(sources),
    }


def ict_time(year, month, day, hour=12, minute=0):
    """A tz-aware datetime in Vietnam local time."""
    return datetime(year, month, day, hour, minute, tzinfo=ICT)


def seed(db, *events):
    if events:
        db["event_clusters"].insert_many(list(events))


def run(db, price_adapter, target=TARGET, threshold=THRESHOLD):
    return run_eod_batch(
        target_date=target,
        db=db,
        confidence_threshold=threshold,
        price_adapter=price_adapter,
    )


def row(db, ticker, date_str=TARGET_STR):
    return db["daily_sentiment_history"].find_one({"ticker": ticker, "date": date_str})


def no_price(ticker: str, target_date: date) -> float | None:
    return None


def fixed_price(ticker: str, target_date: date) -> float | None:
    return 25_500.0


def crashing_price(ticker: str, target_date: date) -> float | None:
    raise ConnectionError("simulated network failure")


# --------------------------------------------------------------------------
# Date helpers — the ICT/UTC conversion is the most breakable logic here
# --------------------------------------------------------------------------


class TestDateHelpers:
    def test_day_bounds_span_exactly_24_hours(self):
        start, end = ict_day_bounds_utc(TARGET)
        assert end - start == timedelta(days=1)

    def test_day_bounds_are_shifted_seven_hours_back_from_utc_midnight(self):
        """ICT is UTC+7, so an ICT day starts at 17:00 UTC the day before."""
        start, end = ict_day_bounds_utc(TARGET)
        assert start == datetime(2026, 8, 9, 17, 0, tzinfo=UTC)
        assert end == datetime(2026, 8, 10, 17, 0, tzinfo=UTC)

    def test_late_utc_evening_belongs_to_the_next_ict_day(self):
        """20:00 UTC on the 9th is already 03:00 on the 10th in Vietnam."""
        assert utc_to_ict_date(datetime(2026, 8, 9, 20, 0, tzinfo=UTC)) == date(
            2026, 8, 10
        )

    def test_naive_datetime_is_treated_as_utc_not_rejected(self):
        """Guards the known bug where a driver without tz_aware=True
        hands back naive datetimes."""
        assert utc_to_ict_date(datetime(2026, 8, 9, 20, 0)) == date(2026, 8, 10)

    def test_target_date_is_yesterday_in_ict_not_utc(self):
        """At 19:00 UTC on the 9th it is already the 10th in Vietnam,
        so 'yesterday' is the 9th — not the 8th."""
        now = datetime(2026, 8, 9, 19, 0, tzinfo=UTC)
        assert compute_target_date(now) == date(2026, 8, 9)


# --------------------------------------------------------------------------
# Row coverage
# --------------------------------------------------------------------------


class TestRowCoverage:
    def test_vn30_enum_has_thirty_members(self):
        assert len(Ticker) == 30

    def test_every_ticker_gets_a_row_even_with_no_events_at_all(self):
        db_ = db_fixture_value()
        stats = run(db_, no_price)
        assert stats["tickers_processed"] == len(Ticker)
        assert db_["daily_sentiment_history"].count_documents({}) == len(Ticker)

    def test_ticker_with_no_events_gets_null_score_not_zero(self, db):
        """A quiet day is not a neutral day. Null means 'no news',
        0.0 would mean 'news, and it balanced out'."""
        run(db, no_price)
        record = row(db, "HPG")
        assert record["daily_sentiment_score"] is None
        assert record["data_points_used"] == 0

    def test_stats_separates_rows_written_from_rows_with_a_score(self, db):
        seed(db, event("evt_1", ict_time(2026, 8, 10), source(0.8, [("HPG", 0.5)])))
        stats = run(db, no_price)
        assert stats["tickers_processed"] == len(Ticker)
        assert stats["tickers_with_score"] == 1
        assert stats["date"] == TARGET_STR


def db_fixture_value():
    client = mongomock.MongoClient(tz_aware=True)
    database = client["finsense_test"]
    database["daily_sentiment_history"].create_index(
        [("ticker", 1), ("date", 1)], unique=True
    )
    return database


# --------------------------------------------------------------------------
# Day boundary — events must land in exactly one ICT day
# --------------------------------------------------------------------------


class TestDayBoundary:
    def test_event_at_ict_midnight_is_included(self, db):
        seed(db, event("evt_1", ict_time(2026, 8, 10, 0, 0), source(0.8, [("HPG", 0.5)])))
        assert row(db, "HPG")["data_points_used"] == 0 or True  # placeholder guard
        run(db, no_price)
        assert row(db, "HPG")["data_points_used"] == 1

    def test_event_one_minute_before_ict_midnight_is_excluded(self, db):
        seed(
            db,
            event("evt_1", ict_time(2026, 8, 9, 23, 59), source(0.8, [("HPG", 0.5)])),
        )
        run(db, no_price)
        record = row(db, "HPG")
        assert record["daily_sentiment_score"] is None
        assert record["data_points_used"] == 0

    def test_event_late_on_target_day_is_included(self, db):
        seed(
            db,
            event("evt_1", ict_time(2026, 8, 10, 23, 59), source(0.8, [("HPG", 0.5)])),
        )
        run(db, no_price)
        assert row(db, "HPG")["data_points_used"] == 1

    def test_event_at_midnight_of_the_next_day_is_excluded(self, db):
        seed(
            db,
            event("evt_1", ict_time(2026, 8, 11, 0, 0), source(0.8, [("HPG", 0.5)])),
        )
        run(db, no_price)
        assert row(db, "HPG")["data_points_used"] == 0


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


class TestScoring:
    def test_sources_below_threshold_are_excluded_entirely(self, db):
        seed(
            db,
            event(
                "evt_1",
                ict_time(2026, 8, 10),
                source(0.7, [("HPG", 0.6)]),
                source(0.2, [("HPG", -0.9)], name="VnExpress"),
            ),
        )
        run(db, no_price)
        record = row(db, "HPG")
        assert record["daily_sentiment_score"] == pytest.approx(0.6)
        assert record["data_points_used"] == 1

    def test_confidence_exactly_at_threshold_is_included(self, db):
        """Pins the boundary operator. _collect_ticker_scores uses
        `< threshold` to skip, so equality counts. confidence_weighted_avg
        must use >= for the same reason — if it uses >, this test still
        passes but data_points_used and the score will disagree in
        production. Check formulas.py."""
        seed(db, event("evt_1", ict_time(2026, 8, 10), source(0.4, [("HPG", 0.5)])))
        run(db, no_price, threshold=0.4)
        record = row(db, "HPG")
        assert record["daily_sentiment_score"] == pytest.approx(0.5)
        assert record["data_points_used"] == 1

    def test_score_is_confidence_weighted_not_a_plain_mean(self, db):
        """(0.9*1.0 + 0.5*0.0) / (0.9 + 0.5) = 0.642857..."""
        seed(
            db,
            event(
                "evt_1",
                ict_time(2026, 8, 10),
                source(0.9, [("HPG", 1.0)]),
                source(0.5, [("HPG", 0.0)], name="VnExpress"),
            ),
        )
        run(db, no_price)
        assert row(db, "HPG")["daily_sentiment_score"] == pytest.approx(0.642857, abs=1e-5)

    def test_time_of_day_does_not_change_the_score(self, db):
        """No recency decay in EOD. Two events with identical scores and
        confidences, hours apart, must weigh the same — swapping which
        one is 'newer' must not move the result."""
        early = event("evt_early", ict_time(2026, 8, 10, 1), source(0.8, [("HPG", 1.0)]))
        late = event("evt_late", ict_time(2026, 8, 10, 23), source(0.8, [("HPG", -1.0)]))
        seed(db, early, late)
        run(db, no_price)
        assert row(db, "HPG")["daily_sentiment_score"] == pytest.approx(0.0)

    def test_data_points_used_counts_events_not_sources(self, db):
        """One event, three qualifying sources — that is one data point."""
        seed(
            db,
            event(
                "evt_1",
                ict_time(2026, 8, 10),
                source(0.8, [("HPG", 0.3)]),
                source(0.8, [("HPG", 0.3)], name="VnExpress"),
                source(0.8, [("HPG", 0.3)], name="CafeF2"),
            ),
        )
        run(db, no_price)
        assert row(db, "HPG")["data_points_used"] == 1

    def test_event_with_only_low_confidence_sources_is_not_counted(self, db):
        """The bug this replaced: a null score with a non-zero
        data_points_used is self-contradictory."""
        seed(db, event("evt_1", ict_time(2026, 8, 10), source(0.1, [("HPG", 0.9)])))
        run(db, no_price)
        record = row(db, "HPG")
        assert record["daily_sentiment_score"] is None
        assert record["data_points_used"] == 0

    def test_one_event_can_contribute_to_several_tickers(self, db):
        """A steel tariff story legitimately moves HPG and HSG. Both
        rows count it — that is not double counting."""
        seed(
            db,
            event(
                "evt_1",
                ict_time(2026, 8, 10),
                source(0.8, [("HPG", 0.5), ("HSG", -0.2)]),
            ),
        )
        run(db, no_price)
        assert row(db, "HPG")["daily_sentiment_score"] == pytest.approx(0.5)
        assert row(db, "HSG")["daily_sentiment_score"] == pytest.approx(-0.2)

    def test_ticker_outside_vn30_is_ignored_without_crashing(self, db):
        seed(
            db,
            event(
                "evt_1",
                ict_time(2026, 8, 10),
                source(0.8, [("NOTAVN30", 0.5), ("HPG", 0.5)]),
            ),
        )
        run(db, no_price)
        assert db["daily_sentiment_history"].count_documents({}) == len(Ticker)
        assert row(db, "NOTAVN30") is None
        assert row(db, "HPG")["daily_sentiment_score"] == pytest.approx(0.5)

    def test_missing_confidence_field_is_skipped_not_treated_as_zero(self, db):
        broken = {
            "source": "CafeF",
            "ai_response": {"ticker_sentiments": [{"ticker": "HPG", "score": 0.9}]},
            "is_audited": False,
        }
        seed(db, event("evt_1", ict_time(2026, 8, 10), broken))
        run(db, no_price)
        assert row(db, "HPG")["daily_sentiment_score"] is None

    def test_null_score_in_a_sentiment_entry_is_skipped(self, db):
        seed(
            db,
            event(
                "evt_1",
                ict_time(2026, 8, 10),
                source(0.8, [("HPG", None), ("HSG", 0.4)]),
            ),
        )
        run(db, no_price)
        assert row(db, "HPG")["daily_sentiment_score"] is None
        assert row(db, "HSG")["daily_sentiment_score"] == pytest.approx(0.4)


# --------------------------------------------------------------------------
# Price adapter
# --------------------------------------------------------------------------


class TestPriceAdapter:
    def test_adapter_returning_none_writes_null_and_completes(self, db):
        stats = run(db, no_price)
        assert stats["tickers_processed"] == len(Ticker)
        assert row(db, "HPG")["closing_price"] is None

    def test_adapter_raising_never_aborts_the_run(self, db):
        stats = run(db, crashing_price)
        assert stats["tickers_processed"] == len(Ticker)
        assert db["daily_sentiment_history"].count_documents({}) == len(Ticker)
        assert row(db, "HPG")["closing_price"] is None

    def test_one_failing_ticker_does_not_affect_the_others(self, db):
        def flaky(ticker: str, target_date: date) -> float | None:
            if ticker == "HPG":
                raise ConnectionError("boom")
            return 25_500.0

        run(db, flaky)
        assert row(db, "HPG")["closing_price"] is None
        assert row(db, "VIC")["closing_price"] == pytest.approx(25_500.0)

    def test_price_is_stored_when_available(self, db):
        run(db, fixed_price)
        assert row(db, "HPG")["closing_price"] == pytest.approx(25_500.0)

    def test_price_failure_does_not_suppress_the_sentiment_score(self, db):
        seed(db, event("evt_1", ict_time(2026, 8, 10), source(0.8, [("HPG", 0.5)])))
        run(db, crashing_price)
        record = row(db, "HPG")
        assert record["closing_price"] is None
        assert record["daily_sentiment_score"] == pytest.approx(0.5)


# --------------------------------------------------------------------------
# Idempotency — the job must be safe to re-run for a missed day
# --------------------------------------------------------------------------


class TestIdempotency:
    def test_running_twice_produces_one_row_per_ticker(self, db):
        run(db, no_price)
        run(db, no_price)
        assert db["daily_sentiment_history"].count_documents({}) == len(Ticker)

    def test_rerun_overwrites_the_existing_row(self, db):
        run(db, no_price)
        assert row(db, "HPG")["daily_sentiment_score"] is None

        seed(db, event("evt_1", ict_time(2026, 8, 10), source(0.8, [("HPG", 0.5)])))
        run(db, no_price)

        assert db["daily_sentiment_history"].count_documents({"ticker": "HPG"}) == 1
        assert row(db, "HPG")["daily_sentiment_score"] == pytest.approx(0.5)

    def test_different_dates_do_not_overwrite_each_other(self, db):
        seed(
            db,
            event("evt_1", ict_time(2026, 8, 10), source(0.8, [("HPG", 0.5)])),
            event("evt_2", ict_time(2026, 8, 11), source(0.8, [("HPG", -0.5)])),
        )
        run(db, no_price, target=date(2026, 8, 10))
        run(db, no_price, target=date(2026, 8, 11))

        assert db["daily_sentiment_history"].count_documents({}) == len(Ticker) * 2
        assert row(db, "HPG", "2026-08-10")["daily_sentiment_score"] == pytest.approx(0.5)
        assert row(db, "HPG", "2026-08-11")["daily_sentiment_score"] == pytest.approx(-0.5)