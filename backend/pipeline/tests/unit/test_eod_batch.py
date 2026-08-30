from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import mongomock
import pytest
from pymongo import InsertOne, UpdateOne
from pymongo.errors import DuplicateKeyError

from backend.core.enums import Ticker
from backend.pipeline.eod_batch.eod_batch import (
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


class FakeHistoryCollection:
    """Duck-typed stand-in for daily_sentiment_history (bulk_write only).

    Hand-written because mongomock cannot take this collection's writes at all:
    pymongo 4.17's `UpdateOne` always passes `sort`, which mongomock 4.3.0 —
    the newest release — rejects.

    Enforces the real `{ticker, date}` unique index, so the upsert contract is
    part of the test: if bulk_write ever stops being a true upsert, the second
    run raises DuplicateKeyError instead of silently writing 60 rows.
    """

    def __init__(self):
        self.documents: dict[tuple[str, str], dict] = {}

    @staticmethod
    def _key(document: dict) -> tuple[str, str]:
        return document["ticker"], document["date"]

    def bulk_write(self, operations, ordered=True):
        for operation in operations:
            if isinstance(operation, InsertOne):
                key = self._key(operation._doc)
                if key in self.documents:
                    raise DuplicateKeyError(f"duplicate key {key}")
                self.documents[key] = dict(operation._doc)
                continue

            assert isinstance(operation, UpdateOne), f"unexpected op {operation!r}"
            # The unique index is on {ticker, date}; a filter that does not match it
            # exactly is not addressing a single row, whatever Mongo would do with it.
            assert set(operation._filter) == {"ticker", "date"}, operation._filter
            assert set(operation._doc) <= {"$set", "$setOnInsert"}, operation._doc
            fields = operation._doc.get("$set", {})
            on_insert = operation._doc.get("$setOnInsert", {})
            # Mongo rejects a field named in both; the fake would otherwise hide it.
            assert not (set(fields) & set(on_insert)), operation._doc

            key = (operation._filter["ticker"], operation._filter["date"])
            if key in self.documents:
                self.documents[key].update(fields)
            elif operation._upsert:
                self.documents[key] = {**operation._filter, **on_insert, **fields}
            else:
                raise DuplicateKeyError(
                    f"no row for {key} and the operation is not an upsert"
                )

    def find_one(self, filter_):
        for document in self.documents.values():
            if all(document.get(k) == v for k, v in filter_.items()):
                return document
        return None

    def count_documents(self, filter_):
        return sum(
            all(document.get(k) == v for k, v in filter_.items())
            for document in self.documents.values()
        )


class FakeDB:
    """`event_clusters` is read-only here, so mongomock serves it fine; only the
    history collection needs the hand-written fake."""

    def __init__(self):
        self.event_clusters = mongomock.MongoClient(tz_aware=True)["finsense_test"][
            "event_clusters"
        ]
        self.daily_sentiment_history = FakeHistoryCollection()

    def __getitem__(self, name):
        return getattr(self, name)


@pytest.fixture
def db():
    return FakeDB()


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


def event(cluster_id, created_at, *sources):
    """created_at is the day key — see the query in run_eod_batch. updated_at is
    set alongside it only so the fixture matches the real document shape."""
    return {
        "cluster_id": cluster_id,
        "event_title": f"test event {cluster_id}",
        "created_at": created_at,
        "updated_at": created_at,
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
        assert utc_to_ict_date(datetime(2026, 8, 9, 20, 0)) == date(  # noqa: DTZ001
            2026, 8, 10
        )

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

    def test_every_ticker_gets_a_row_even_with_no_events_at_all(self, db):
        stats = run(db, no_price)
        assert stats["tickers_processed"] == len(Ticker)
        assert db["daily_sentiment_history"].count_documents({}) == len(Ticker)

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


# --------------------------------------------------------------------------
# Day boundary — events must land in exactly one ICT day
# --------------------------------------------------------------------------


class TestDayBoundary:
    def test_event_at_ict_midnight_is_included(self, db):
        seed(db, event("evt_1", ict_time(2026, 8, 10, 0, 0), source(0.8, [("HPG", 0.5)])))
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

    def test_event_rewritten_the_next_day_stays_on_its_original_day(self, db):
        """The cluster stage bumps updated_at on every rewrite, so an event that
        gains an article on the 11th must not desert the 10th's row — otherwise a
        re-run of the 10th stops reproducing the score it first produced."""
        evt = event("evt_1", ict_time(2026, 8, 10, 9, 0), source(0.8, [("HPG", 0.5)]))
        evt["updated_at"] = ict_time(2026, 8, 11, 9, 0)
        seed(db, evt)

        run(db, no_price)
        assert row(db, "HPG")["data_points_used"] == 1
        assert row(db, "HPG")["daily_sentiment_score"] == pytest.approx(0.5)

    def test_event_from_an_earlier_day_does_not_leak_in_when_rewritten(self, db):
        """The mirror of the above: a rewrite on the target day must not drag an
        older event into it."""
        evt = event("evt_1", ict_time(2026, 8, 9, 9, 0), source(0.8, [("HPG", 0.5)]))
        evt["updated_at"] = ict_time(2026, 8, 10, 9, 0)
        seed(db, evt)

        run(db, no_price)
        assert row(db, "HPG")["data_points_used"] == 0
        assert row(db, "HPG")["daily_sentiment_score"] is None


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
        """A macro story legitimately moves HPG and VNM in opposite
        directions. Both rows count it — that is not double counting."""
        seed(
            db,
            event(
                "evt_1",
                ict_time(2026, 8, 10),
                source(0.8, [("HPG", 0.5), ("VNM", -0.2)]),
            ),
        )
        run(db, no_price)
        assert row(db, "HPG")["daily_sentiment_score"] == pytest.approx(0.5)
        assert row(db, "VNM")["daily_sentiment_score"] == pytest.approx(-0.2)

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
                source(0.8, [("HPG", None), ("VNM", 0.4)]),
            ),
        )
        run(db, no_price)
        assert row(db, "HPG")["daily_sentiment_score"] is None
        assert row(db, "VNM")["daily_sentiment_score"] == pytest.approx(0.4)


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

    def test_a_failed_refetch_does_not_erase_a_stored_price(self, db):
        """Re-running a past day is the documented repair path, so it must not be
        able to damage the day it is repairing."""
        run(db, fixed_price)
        assert row(db, "HPG")["closing_price"] == pytest.approx(25_500.0)

        run(db, crashing_price)
        assert row(db, "HPG")["closing_price"] == pytest.approx(25_500.0)

    def test_a_rerun_fills_in_a_price_the_first_run_missed(self, db):
        """The likely real ordering: the 00:30 ICT run finds no close published
        yet, and a later re-run supplies it."""
        run(db, no_price)
        assert row(db, "HPG")["closing_price"] is None

        run(db, fixed_price)
        assert row(db, "HPG")["closing_price"] == pytest.approx(25_500.0)

    def test_a_rerun_can_still_correct_a_wrong_price(self, db):
        run(db, fixed_price)

        def corrected(ticker: str, target_date: date) -> float | None:
            return 26_000.0

        run(db, corrected)
        assert row(db, "HPG")["closing_price"] == pytest.approx(26_000.0)

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