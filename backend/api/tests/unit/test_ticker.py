"""
backend/api/tests/unit/test_ticker.py

FS-37 — GET /ticker/{symbol}, /ticker/{symbol}/history, /ticker/{symbol}/events.

No pytest-asyncio in this repo (see test_dashboard.py, which is stale from
before the sync->async migration and mocks a get_database() that no longer
exists). Async service functions are driven with asyncio.run() from plain
sync test functions instead — no new test-runner dependency required.

DB is mocked; formulas.py / lexicon.py / ticker_metadata.py are used for
real, since they are deterministic and mocking them would just re-assert
the mock instead of testing anything.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.api.features.dashboard import service as dashboard_svc
from backend.api.features.ticker import aggregator
from backend.api.features.ticker import service as svc
from backend.api.features.ticker.router import (
    db_dep,
    directory_router,
    router,
    valid_symbol,
)
from backend.api.features.ticker.schemas import (
    GaugeBreakdown,
    TickerDetail,
    TickerEventItem,
    TickerEvents,
    TickerEventSourceBreakdown,
    TickerHistory,
    TickerHistoryRow,
)
from backend.core.config import api_settings, pipeline_settings
from backend.core.enums import Ticker

REPO_ROOT = Path(__file__).resolve().parents[4]
OPENAPI_PATH = REPO_ROOT / "docs" / "openapi.yaml"


# The service windows history on ICT dates; a UTC "today" would disagree with it
# for seven hours a day and make these tests flaky near midnight.
def _today_ict():
    return datetime.now(svc._ICT).date()


def run(coro):
    return asyncio.run(coro)


# ============================================================
# Fakes — just enough of Motor's chained cursor API
# ============================================================


class FakeCursor:
    def __init__(self, items: list[dict]):
        self._items = list(items)
        self.sort_calls: list[tuple] = []
        self.skip_n: int | None = None
        self.limit_n: int | None = None

    def sort(self, *args, **kwargs):
        self.sort_calls.append(args or kwargs)
        # Ordering is part of the contract under test (the history window relies
        # on it), so actually sort rather than trusting hand-ordered fixtures.
        if args and isinstance(args[0], str):
            field = args[0]
            direction = args[1] if len(args) > 1 else 1
            self._items.sort(key=lambda d: d.get(field), reverse=direction < 0)
        return self

    def skip(self, n: int):
        self.skip_n = n
        self._items = self._items[n:]
        return self

    def limit(self, n: int):
        self.limit_n = n
        self._items = self._items[:n]
        return self

    async def to_list(self, length=None):
        return self._items[:length] if length is not None else self._items


class FakeCollection:
    def __init__(self, items: list[dict]):
        self.items = items
        self.last_query = None
        self.last_cursor: FakeCursor | None = None
        self.find_call_count = 0

    def find(self, query=None, **kwargs):
        self.find_call_count += 1
        self.last_query = query
        items = self.items
        date_filter = (query or {}).get("date")
        if isinstance(date_filter, dict) and "$gte" in date_filter:
            items = [d for d in items if d.get("date") >= date_filter["$gte"]]
        self.last_cursor = FakeCursor(items)
        return self.last_cursor


def make_event(
    cluster_id="evt_1",
    ticker_sentiments=None,
    updated_at=None,
    total_articles=3,
    source_breakdown=None,
    concept_sentiments=None,
    event_title="Event title",
):
    return {
        "cluster_id": cluster_id,
        "event_title": event_title,
        "created_at": updated_at,
        "updated_at": updated_at,
        "event_coverage": {"total_articles": total_articles, "all_urls": {}},
        "aggregated_analysis": {
            "ticker_sentiments": (
                ticker_sentiments if ticker_sentiments is not None else [{"ticker": "HPG", "score": 0.5}]
            ),
            "concept_sentiments": concept_sentiments or [],
        },
        "source_breakdown": source_breakdown or [],
    }


def make_source(source, ticker_scores: dict, confidence: float, url="https://example.com/a"):
    return {
        "source": source,
        "representative_article": {
            "url": url,
            "published_at": None,
            "content_fed_to_ai": None,
            "centroid_similarity": 0.9,
        },
        "ai_response": {
            "ticker_sentiments": [{"ticker": t, "score": s} for t, s in ticker_scores.items()],
            "concept_sentiments": [],
            "ai_confidence": confidence,
            "model_version": "test-model",
            "prompt_version": "v1",
        },
        "is_audited": False,
    }


def make_client(fake_db) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[db_dep] = lambda: fake_db
    return TestClient(app)


# ============================================================
# Shared scoring path — the AC that binds all three endpoints
# ============================================================


class TestSharedScoringPath:
    def test_ticker_service_reuses_the_exact_dashboard_scoring_function(self):
        """Not 'an equivalent implementation' — the literal same function
        object dashboard/service.py::get_tickers() calls."""
        assert svc.assemble_live_sentiment is aggregator.assemble_live_sentiment
        assert dashboard_svc.assemble_live_sentiment is aggregator.assemble_live_sentiment

    def test_history_endpoint_never_touches_event_clusters(self):
        """Task rule: history reads daily_sentiment_history ONLY."""
        history_collection = FakeCollection([])
        fake_db = {"daily_sentiment_history": history_collection}
        run(svc.get_ticker_history(fake_db, symbol="HPG", days=30))
        assert history_collection.find_call_count == 1
        assert "event_clusters" not in fake_db

    def test_detail_endpoint_never_touches_daily_sentiment_history(self):
        """Task rule (Task 5b): 'Do not read daily_sentiment_history; that
        collection only backs the chart.' Score comes from event_clusters
        at request time — a dict with no daily_sentiment_history key at all
        would KeyError the instant the service tried to touch it."""
        now = datetime.now(UTC)
        events_collection = FakeCollection([make_event(updated_at=now)])
        fake_db = {"event_clusters": events_collection}  # no daily_sentiment_history key
        result = run(svc.get_ticker_detail(fake_db, symbol="HPG", window="24h"))
        assert result.is_empty_state is False
        assert events_collection.find_call_count == 1


# ============================================================
# Task 5b — GET /ticker/{symbol}
# ============================================================


class TestGetTickerDetail:
    def test_no_events_in_window_returns_null_score_and_empty_state(self):
        fake_db = {"event_clusters": FakeCollection([])}
        result = run(svc.get_ticker_detail(fake_db, symbol="HPG", window="24h"))
        assert result.is_empty_state is True
        assert result.sentiment_score is None  # not 0.0
        assert result.gauge.score is None
        assert result.article_count == 0
        assert result.event_count == 0
        assert result.last_updated is None

    def test_score_is_not_zero_when_empty_it_is_none(self):
        """Regression guard for the exact wording in the ticket: 'null is not 0.0'."""
        fake_db = {"event_clusters": FakeCollection([])}
        result = run(svc.get_ticker_detail(fake_db, symbol="HPG", window="24h"))
        assert result.sentiment_score != 0.0
        assert result.sentiment_score is None

    def test_recency_decay_skews_toward_the_more_recent_event(self):
        from backend.core.formulas import recency_weight, time_weighted_average

        now = datetime.now(UTC)
        recent = make_event(cluster_id="evt_recent", ticker_sentiments=[{"ticker": "HPG", "score": 0.8}], updated_at=now - timedelta(hours=1))
        old = make_event(cluster_id="evt_old", ticker_sentiments=[{"ticker": "HPG", "score": -0.8}], updated_at=now - timedelta(hours=10))
        fake_db = {"event_clusters": FakeCollection([recent, old])}

        result = run(svc.get_ticker_detail(fake_db, symbol="HPG", window="24h"))

        lambda_ = api_settings.DECAY_LAMBDA["24h"]
        expected = time_weighted_average(
            [(0.8, recency_weight(1, lambda_)), (-0.8, recency_weight(10, lambda_))]
        )
        assert result.sentiment_score == pytest.approx(round(expected, 4), abs=1e-3)
        assert result.sentiment_score > 0  # more recent event dominates

    @pytest.mark.parametrize("window", ["24h", "48h", "72h"])
    def test_all_three_windows_work(self, window):
        now = datetime.now(UTC)
        event = make_event(updated_at=now - timedelta(hours=1))
        fake_db = {"event_clusters": FakeCollection([event])}
        result = run(svc.get_ticker_detail(fake_db, symbol="HPG", window=window))
        assert result.window == window
        assert result.is_empty_state is False

    def test_article_and_event_count_only_reflect_events_mentioning_this_ticker(self):
        """Events pulled in purely for concept-blending must not inflate the
        identity-card counts — those are about the ticker itself."""
        now = datetime.now(UTC)
        mentions_hpg = make_event(
            cluster_id="evt_hpg", ticker_sentiments=[{"ticker": "HPG", "score": 0.4}],
            updated_at=now - timedelta(hours=1), total_articles=4,
        )
        concept_only = make_event(
            cluster_id="evt_macro", ticker_sentiments=[{"ticker": "VNM", "score": 0.1}],
            concept_sentiments=[{"concept": "MATERIALS", "score": 0.2}],
            updated_at=now - timedelta(hours=2), total_articles=9,
        )
        fake_db = {"event_clusters": FakeCollection([mentions_hpg, concept_only])}
        result = run(svc.get_ticker_detail(fake_db, symbol="HPG", window="24h"))
        assert result.event_count == 1
        assert result.article_count == 4

    def test_last_updated_is_the_most_recent_mentioning_event(self):
        now = datetime.now(UTC)
        older = make_event(cluster_id="evt_a", updated_at=now - timedelta(hours=5))
        newer = make_event(cluster_id="evt_b", updated_at=now - timedelta(hours=1))
        fake_db = {"event_clusters": FakeCollection([older, newer])}
        result = run(svc.get_ticker_detail(fake_db, symbol="HPG", window="24h"))
        assert result.last_updated == newer["updated_at"]

    def test_company_name_comes_from_ticker_metadata(self):
        now = datetime.now(UTC)
        fake_db = {"event_clusters": FakeCollection([make_event(updated_at=now)])}
        result = run(svc.get_ticker_detail(fake_db, symbol="HPG", window="24h"))
        assert result.company_name == "Hoa Phat Group"

    def test_gauge_buckets_only_count_the_tickers_own_valid_scores(self):
        threshold = api_settings.SENTIMENT_BUCKET_THRESHOLD
        now = datetime.now(UTC)
        positive = make_event(cluster_id="p", ticker_sentiments=[{"ticker": "HPG", "score": threshold + 0.1}], updated_at=now)
        negative = make_event(cluster_id="n", ticker_sentiments=[{"ticker": "HPG", "score": -threshold - 0.1}], updated_at=now)
        null_score = make_event(cluster_id="x", ticker_sentiments=[{"ticker": "HPG", "score": None}], updated_at=now)
        fake_db = {"event_clusters": FakeCollection([positive, negative, null_score])}
        result = run(svc.get_ticker_detail(fake_db, symbol="HPG", window="24h"))
        assert result.gauge.positive_count == 1
        assert result.gauge.negative_count == 1
        assert result.gauge.neutral_count == 0
        # 3 events mention the ticker, but only 2 carry a non-null score
        assert result.event_count == 3

    def test_score_can_come_purely_from_concept_blend_with_zero_direct_mentions(self):
        """Not a bug — inherent to blend_s_final/assemble_live_sentiment,
        which dashboard's get_tickers() already shares. A ticker can carry a
        non-null, non-empty score purely from its sector's concept-level
        news even when NO article names the ticker itself; event_count and
        article_count correctly stay at 0 since they count direct mentions
        only. Locked in here so this doesn't silently drift into
        'inconsistent' being treated as a bug to paper over later."""
        now = datetime.now(UTC)
        concept_only_event = make_event(
            ticker_sentiments=[],  # HPG never named
            concept_sentiments=[{"concept": "MATERIALS", "score": 0.5}],  # HPG is weighted on MATERIALS
            updated_at=now,
        )
        fake_db = {"event_clusters": FakeCollection([concept_only_event])}
        result = run(svc.get_ticker_detail(fake_db, symbol="HPG", window="24h"))
        assert result.is_empty_state is False
        assert result.sentiment_score is not None
        assert result.event_count == 0
        assert result.article_count == 0

    def test_is_empty_state_and_null_score_are_never_inconsistent(self):
        """sentiment_score is None iff is_empty_state is True — provable
        from the code (both derive from the same result.is_empty), asserted
        explicitly across a few different shapes as a regression guard."""
        now = datetime.now(UTC)
        cases = [
            [],
            [make_event(ticker_sentiments=[{"ticker": "HPG", "score": None}], updated_at=now)],
            [make_event(ticker_sentiments=[{"ticker": "HPG", "score": 0.3}], updated_at=now)],
        ]
        for events in cases:
            fake_db = {"event_clusters": FakeCollection(events)}
            result = run(svc.get_ticker_detail(fake_db, symbol="HPG", window="24h"))
            assert (result.sentiment_score is None) == result.is_empty_state
            assert (result.gauge.score is None) == result.is_empty_state

    def test_response_matches_ticker_detail_schema_in_openapi(self):
        spec = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
        openapi_props = set(spec["components"]["schemas"]["TickerDetail"]["properties"].keys())
        assert set(TickerDetail.model_fields.keys()) == openapi_props
        gauge_props = set(spec["components"]["schemas"]["TickerDetail"]["properties"]["gauge"]["properties"].keys())
        assert set(GaugeBreakdown.model_fields.keys()) == gauge_props


class TestTickerDetailRouter:
    def test_unknown_symbol_returns_404(self):
        client = make_client({"event_clusters": FakeCollection([])})
        resp = client.get("/api/ticker/ZZZ")
        assert resp.status_code == 404

    def test_known_ticker_with_no_events_returns_200_with_empty_state(self):
        client = make_client({"event_clusters": FakeCollection([])})
        resp = client.get("/api/ticker/HPG")
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_empty_state"] is True
        assert body["sentiment_score"] is None

    def test_lowercase_symbol_is_accepted(self):
        client = make_client({"event_clusters": FakeCollection([])})
        resp = client.get("/api/ticker/hpg")
        assert resp.status_code == 200
        assert resp.json()["ticker"] == "HPG"


# ============================================================
# GET /ticker/{symbol}/history
# ============================================================


class TestGetTickerHistory:
    @pytest.mark.parametrize("days", [7, 30, 90])
    def test_all_three_ranges_work(self, days):
        today = _today_ict().isoformat()
        rows = [{"ticker": "HPG", "date": today, "daily_sentiment_score": 0.1, "closing_price": 100.0}]
        fake_db = {"daily_sentiment_history": FakeCollection(rows)}
        result = run(svc.get_ticker_history(fake_db, symbol="HPG", days=days))
        assert result.days == days
        assert len(result.data) == 1

    def test_rows_ordered_oldest_to_newest(self):
        # Deliberately unsorted: FakeCursor.sort() honours the service's own
        # .sort("date", 1), so this asserts the query's ordering, not the fixture's.
        shuffled = [
            {"ticker": "HPG", "date": "2026-08-03", "daily_sentiment_score": 0.3, "closing_price": 103.0},
            {"ticker": "HPG", "date": "2026-08-02", "daily_sentiment_score": 0.2, "closing_price": 102.0},
            {"ticker": "HPG", "date": "2026-08-01", "daily_sentiment_score": 0.1, "closing_price": 101.0},
        ]
        fake_db = {"daily_sentiment_history": FakeCollection(shuffled)}
        result = run(svc.get_ticker_history(fake_db, symbol="HPG", days=36500))
        assert [row.date for row in result.data] == ["2026-08-01", "2026-08-02", "2026-08-03"]

    def test_nulls_pass_through_untouched_no_interpolation(self):
        # Newest-first, as Mongo's own .sort("date", -1) would already hand back.
        rows = [
            {"ticker": "HPG", "date": "2026-08-03", "daily_sentiment_score": 0.3, "closing_price": None},
            {"ticker": "HPG", "date": "2026-08-02", "daily_sentiment_score": None, "closing_price": None},
            {"ticker": "HPG", "date": "2026-08-01", "daily_sentiment_score": 0.1, "closing_price": 100.0},
        ]
        fake_db = {"daily_sentiment_history": FakeCollection(rows)}
        result = run(svc.get_ticker_history(fake_db, symbol="HPG", days=36500))
        assert len(result.data) == 3  # no rows dropped, no rows synthesized
        assert result.data[1].daily_sentiment_score is None
        assert result.data[1].closing_price is None
        assert result.data[2].daily_sentiment_score == 0.3
        assert result.data[2].closing_price is None  # a null field next to a non-null one — not filled in

    def test_window_is_calendar_days_not_row_count(self):
        """`days` must be a calendar window. Limiting to the newest N *rows*
        reaches further back the more non-trading days the range contains — a
        weekday-only series would make days=7 span 9-10 calendar days."""
        today = _today_ict()
        # 10 consecutive calendar days ending today, so 3 fall outside a 7-day window.
        rows = [
            {
                "ticker": "HPG",
                "date": (today - timedelta(days=i)).isoformat(),
                "daily_sentiment_score": 0.1,
                "closing_price": 100.0,
            }
            for i in range(10)
        ]
        fake_db = {"daily_sentiment_history": FakeCollection(rows)}
        result = run(svc.get_ticker_history(fake_db, symbol="HPG", days=7))

        expected = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
        assert [row.date for row in result.data] == expected

    def test_gaps_in_the_window_stay_gaps_and_are_never_filled(self):
        """A weekend or holiday simply has no row. The response is shorter than
        `days` — it must not be padded, and must not silently reach further back
        to make up the count."""
        today = _today_ict()
        present = [0, 1, 4, 5, 6]  # days 2 and 3 missing, as a weekend would be
        rows = [
            {
                "ticker": "HPG",
                "date": (today - timedelta(days=i)).isoformat(),
                "daily_sentiment_score": 0.1,
                "closing_price": 100.0,
            }
            for i in present
        ]
        # Older rows that a row-count limit would wrongly pull in to reach 7.
        rows += [
            {"ticker": "HPG", "date": (today - timedelta(days=i)).isoformat(),
             "daily_sentiment_score": 0.9, "closing_price": 99.0}
            for i in (8, 9)
        ]
        fake_db = {"daily_sentiment_history": FakeCollection(rows)}
        result = run(svc.get_ticker_history(fake_db, symbol="HPG", days=7))

        assert len(result.data) == len(present)  # 5, not padded up to 7
        oldest_allowed = (today - timedelta(days=6)).isoformat()
        assert all(row.date >= oldest_allowed for row in result.data)

    def test_query_is_scoped_to_the_requested_ticker_only(self):
        """A history collection holds rows for all 30 tickers — the query
        filter, not client-side filtering, must isolate the requested one."""
        history_collection = FakeCollection([{"ticker": "HPG", "date": "2026-08-01", "daily_sentiment_score": 0.1, "closing_price": 100.0}])
        fake_db = {"daily_sentiment_history": history_collection}
        run(svc.get_ticker_history(fake_db, symbol="HPG", days=30))
        # The date window rides along in the same query — both halves must be
        # server-side, never a client-side filter over the whole collection.
        assert history_collection.last_query["ticker"] == "HPG"
        assert "$gte" in history_collection.last_query["date"]

    def test_fewer_available_days_than_requested_is_a_partial_array_not_an_error(self):
        rows = [
            {"ticker": "HPG", "date": "2026-08-01", "daily_sentiment_score": 0.1, "closing_price": 100.0},
            {"ticker": "HPG", "date": "2026-08-02", "daily_sentiment_score": 0.2, "closing_price": 101.0},
        ]
        client = make_client({"daily_sentiment_history": FakeCollection(rows)})
        resp = client.get("/api/ticker/HPG/history", params={"days": 90})
        assert resp.status_code == 200
        body = resp.json()
        assert body["days"] == 90
        assert len(body["data"]) == 2

    def test_unknown_symbol_returns_404(self):
        client = make_client({"daily_sentiment_history": FakeCollection([])})
        resp = client.get("/api/ticker/ZZZ/history")
        assert resp.status_code == 404

    def test_response_matches_ticker_history_schema_in_openapi(self):
        spec = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
        schema = spec["components"]["schemas"]["TickerHistory"]
        assert set(TickerHistory.model_fields.keys()) == set(schema["properties"].keys())
        row_props = set(schema["properties"]["data"]["items"]["properties"].keys())
        assert set(TickerHistoryRow.model_fields.keys()) == row_props


# ============================================================
# Task 5c — GET /ticker/{symbol}/events
# ============================================================


class TestGetTickerEvents:
    def test_event_level_score_is_the_requested_tickers_entry(self):
        now = datetime.now(UTC)
        event = make_event(
            ticker_sentiments=[{"ticker": "HPG", "score": 0.6}, {"ticker": "VNM", "score": -0.2}],
            updated_at=now,
        )
        fake_db = {"event_clusters": FakeCollection([event])}
        result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1, window="72h"))
        assert result.items[0].sentiment_score == 0.6

    def test_source_level_score_is_the_requested_tickers_entry(self):
        """Multi-ticker event, multi-ticker source ai_response — the row for
        the requested ticker must carry ITS score, not a sibling ticker's."""
        now = datetime.now(UTC)
        source = make_source("CafeF", {"HPG": 0.55, "VNM": -0.1}, confidence=0.9)
        event = make_event(
            ticker_sentiments=[{"ticker": "HPG", "score": 0.5}, {"ticker": "VNM", "score": -0.1}],
            source_breakdown=[source],
            updated_at=now,
        )
        fake_db = {"event_clusters": FakeCollection([event])}
        result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1, window="72h"))
        breakdown = result.items[0].source_breakdown
        assert len(breakdown) == 1
        assert breakdown[0].source == "CafeF"
        assert breakdown[0].score == 0.55

    def test_multi_ticker_event_returns_correct_score_at_both_levels_together(self):
        """Literal AC: 'Test with a multi-ticker event confirms the correct
        ticker's score is returned at both levels.' One event, one source,
        both HPG and VNM present at both the event level and inside that
        source's own ai_response — HPG's row must show HPG's numbers, not
        VNM's, at either level."""
        now = datetime.now(UTC)
        source = make_source("CafeF", {"HPG": 0.55, "VNM": -0.35}, confidence=0.9)
        event = make_event(
            ticker_sentiments=[{"ticker": "HPG", "score": 0.5}, {"ticker": "VNM", "score": -0.3}],
            source_breakdown=[source],
            updated_at=now,
        )
        fake_db = {"event_clusters": FakeCollection([event])}

        hpg_result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1, window="72h"))
        assert hpg_result.items[0].sentiment_score == 0.5  # event level
        assert hpg_result.items[0].source_breakdown[0].score == 0.55  # source level

        fake_db_2 = {"event_clusters": FakeCollection([event])}
        vnm_result = run(svc.get_ticker_events(fake_db_2, symbol="VNM", page=1, window="72h"))
        assert vnm_result.items[0].sentiment_score == -0.3
        assert vnm_result.items[0].source_breakdown[0].score == -0.35

    def test_sources_below_confidence_threshold_are_excluded(self):
        now = datetime.now(UTC)
        below = make_source("CafeF", {"HPG": 0.7}, confidence=pipeline_settings.AI_CONFIDENCE_THRESHOLD - 0.05)
        above = make_source("VnExpress", {"HPG": 0.3}, confidence=pipeline_settings.AI_CONFIDENCE_THRESHOLD + 0.05)
        event = make_event(source_breakdown=[below, above], updated_at=now)
        fake_db = {"event_clusters": FakeCollection([event])}
        result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1, window="72h"))
        sources = [row.source for row in result.items[0].source_breakdown]
        assert sources == ["VnExpress"]

    def test_source_exactly_at_threshold_is_included_not_excluded(self):
        """'Below AI_CONFIDENCE_THRESHOLD' is a strict '<' — a source AT the
        threshold cleared it and must count, matching the same '< threshold'
        convention core/formulas.py::confidence_weighted_avg already uses."""
        now = datetime.now(UTC)
        at_threshold = make_source("CafeF", {"HPG": 0.7}, confidence=pipeline_settings.AI_CONFIDENCE_THRESHOLD)
        event = make_event(source_breakdown=[at_threshold], updated_at=now)
        fake_db = {"event_clusters": FakeCollection([event])}
        result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1, window="72h"))
        assert [row.source for row in result.items[0].source_breakdown] == ["CafeF"]

    def test_event_with_null_ticker_score_still_appears_in_the_list(self):
        now = datetime.now(UTC)
        event = make_event(ticker_sentiments=[{"ticker": "HPG", "score": None}], updated_at=now)
        fake_db = {"event_clusters": FakeCollection([event])}
        result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1, window="72h"))
        assert len(result.items) == 1
        assert result.items[0].sentiment_score is None

    def test_article_count_comes_from_event_coverage_not_breakdown_row_count(self):
        now = datetime.now(UTC)
        source = make_source("CafeF", {"HPG": 0.4}, confidence=0.9)
        event = make_event(source_breakdown=[source], total_articles=12, updated_at=now)
        fake_db = {"event_clusters": FakeCollection([event])}
        result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1, window="72h"))
        assert result.items[0].article_count == 12
        assert len(result.items[0].source_breakdown) == 1  # 12 articles, 1 source row — expected

    def test_newest_first_sort_is_requested_from_mongo(self):
        now = datetime.now(UTC)
        fake_db = {"event_clusters": FakeCollection([make_event(updated_at=now)])}
        run(svc.get_ticker_events(fake_db, symbol="HPG", page=1, window="72h"))
        cursor = fake_db["event_clusters"].last_cursor
        assert cursor.sort_calls == [("updated_at", -1)]

    def test_response_order_matches_whatever_mongo_handed_back_unshuffled(self):
        """Complements the above: given events already newest-first (as real
        Mongo would deliver post-sort), the service must not silently
        re-sort or shuffle them while building response items."""
        now = datetime.now(UTC)
        newest_first = [
            make_event(cluster_id=f"evt_{i}", updated_at=now - timedelta(hours=i))
            for i in range(4)
        ]
        fake_db = {"event_clusters": FakeCollection(newest_first)}
        result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1, window="72h"))
        assert [item.cluster_id for item in result.items] == ["evt_0", "evt_1", "evt_2", "evt_3"]

    def test_pagination_boundary_exactly_one_page_reports_no_more(self):
        """Off-by-one guard: exactly page_size events must not falsely
        report has_more (the +1 probe row must not itself count as 'more')."""
        now = datetime.now(UTC)
        page_size = api_settings.TICKER_EVENTS_PAGE_SIZE
        events = [make_event(cluster_id=f"evt_{i}", updated_at=now - timedelta(hours=i)) for i in range(page_size)]
        fake_db = {"event_clusters": FakeCollection(events)}
        result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1, window="72h"))
        assert len(result.items) == page_size
        assert result.has_more is False

    def test_pagination_boundary_one_over_a_page_leaves_exactly_one_for_page_two(self):
        now = datetime.now(UTC)
        page_size = api_settings.TICKER_EVENTS_PAGE_SIZE
        events = [make_event(cluster_id=f"evt_{i}", updated_at=now - timedelta(hours=i)) for i in range(page_size + 1)]
        fake_db_1 = {"event_clusters": FakeCollection(events)}
        page1 = run(svc.get_ticker_events(fake_db_1, symbol="HPG", page=1, window="72h"))
        fake_db_2 = {"event_clusters": FakeCollection(events)}
        page2 = run(svc.get_ticker_events(fake_db_2, symbol="HPG", page=2, window="72h"))
        assert len(page1.items) == page_size
        assert page1.has_more is True
        assert len(page2.items) == 1
        assert page2.has_more is False

    def test_pagination_next_page_has_no_duplicates_or_skips(self):
        now = datetime.now(UTC)
        # 12 events, newest-first as Mongo would already have sorted them
        all_events = [
            make_event(cluster_id=f"evt_{i}", updated_at=now - timedelta(hours=i))
            for i in range(12)
        ]
        page_size = api_settings.TICKER_EVENTS_PAGE_SIZE

        fake_db_1 = {"event_clusters": FakeCollection(all_events)}
        page1 = run(svc.get_ticker_events(fake_db_1, symbol="HPG", page=1, window="72h"))
        fake_db_2 = {"event_clusters": FakeCollection(all_events)}
        page2 = run(svc.get_ticker_events(fake_db_2, symbol="HPG", page=2, window="72h"))
        fake_db_3 = {"event_clusters": FakeCollection(all_events)}
        page3 = run(svc.get_ticker_events(fake_db_3, symbol="HPG", page=3, window="72h"))

        ids_1 = [i.cluster_id for i in page1.items]
        ids_2 = [i.cluster_id for i in page2.items]
        ids_3 = [i.cluster_id for i in page3.items]

        assert len(ids_1) == page_size
        assert len(ids_2) == page_size
        assert len(ids_3) == 12 - 2 * page_size
        assert set(ids_1) & set(ids_2) == set()
        assert set(ids_2) & set(ids_3) == set()
        assert set(ids_1) | set(ids_2) | set(ids_3) == {e["cluster_id"] for e in all_events}
        assert page1.has_more is True
        assert page2.has_more is True
        assert page3.has_more is False

    def test_no_events_returns_empty_array(self):
        fake_db = {"event_clusters": FakeCollection([])}
        result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1, window="72h"))
        assert result.items == []

    def test_response_matches_ticker_events_schema_in_openapi(self):
        spec = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
        schema = spec["components"]["schemas"]["TickerEvents"]
        assert set(TickerEvents.model_fields.keys()) == set(schema["properties"].keys())
        item_props = set(schema["properties"]["items"]["items"]["properties"].keys())
        assert set(TickerEventItem.model_fields.keys()) == item_props
        breakdown_props = set(schema["properties"]["items"]["items"]["properties"]["source_breakdown"]["items"]["properties"].keys())
        assert set(TickerEventSourceBreakdown.model_fields.keys()) == breakdown_props


class TestTickerEventsRouter:
    def test_unknown_symbol_returns_404(self):
        client = make_client({"event_clusters": FakeCollection([])})
        resp = client.get("/api/ticker/ZZZ/events")
        assert resp.status_code == 404

    def test_no_events_returns_200_with_empty_array(self):
        client = make_client({"event_clusters": FakeCollection([])})
        resp = client.get("/api/ticker/HPG/events")
        assert resp.status_code == 200
        assert resp.json()["items"] == []


# ============================================================
# valid_symbol — shared 404 guard used by all three routes
# ============================================================


class TestValidSymbol:
    def test_uppercases_a_known_symbol(self):
        assert valid_symbol("hpg") == "HPG"

    def test_raises_404_for_unknown_symbol(self):
        with pytest.raises(HTTPException) as exc_info:
            valid_symbol("ZZZ")
        assert exc_info.value.status_code == 404


# ============================================================
# Bad-input scenarios — every query param FastAPI/we validate,
# confirmed to fail with a clean 422, never a 500 or wrong data.
# ============================================================


class TestValidationErrors:
    def test_invalid_window_on_detail_is_422_not_500(self):
        client = make_client({"event_clusters": FakeCollection([])})
        resp = client.get("/api/ticker/HPG", params={"window": "99h"})
        assert resp.status_code == 422

    def test_events_endpoint_rejects_a_window_outside_the_frozen_three(self):
        """/events is window-scoped now, on the same 24h|48h|72h vocabulary as
        every other windowed endpoint — so the ticker detail page can pin its
        header, score and event list to one identical span."""
        now = datetime.now(UTC)
        client = make_client({"event_clusters": FakeCollection([make_event(updated_at=now)])})
        assert client.get("/api/ticker/HPG/events", params={"window": "1w"}).status_code == 422

        resp = client.get("/api/ticker/HPG/events", params={"window": "72h"})
        assert resp.status_code == 200
        assert resp.json()["window"] == "72h"

    def test_invalid_days_is_422_not_silently_clamped(self):
        client = make_client({"daily_sentiment_history": FakeCollection([])})
        resp = client.get("/api/ticker/HPG/history", params={"days": 15})
        assert resp.status_code == 422

    @pytest.mark.parametrize("page", [0, -1])
    def test_non_positive_page_is_422(self, page):
        client = make_client({"event_clusters": FakeCollection([])})
        resp = client.get("/api/ticker/HPG/events", params={"page": page})
        assert resp.status_code == 422

    def test_omitted_window_falls_back_to_default_not_an_error(self):
        client = make_client({"event_clusters": FakeCollection([])})
        resp = client.get("/api/ticker/HPG")
        assert resp.status_code == 200
        assert resp.json()["window"] == api_settings.DEFAULT_WINDOW

    def test_symbol_with_stray_characters_is_404_not_500(self):
        client = make_client({"event_clusters": FakeCollection([])})
        resp = client.get("/api/ticker/HPG!")
        assert resp.status_code == 404


class TestPaginationExtremes:
    def test_page_far_beyond_available_data_is_empty_200_not_error(self):
        now = datetime.now(UTC)
        fake_db = {"event_clusters": FakeCollection([make_event(updated_at=now)])}
        client = make_client(fake_db)
        resp = client.get("/api/ticker/HPG/events", params={"page": 999})
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["has_more"] is False


class TestMalformedDocumentsDoNotCrash:
    """Documents missing optional/nested keys entirely (not just null) —
    a stricter case than 'field present but None', and one real Mongo data
    can actually produce (e.g. a doc written before a field existed)."""

    def test_detail_survives_event_missing_event_coverage_and_source_breakdown(self):
        now = datetime.now(UTC)
        bare_event = {
            "cluster_id": "evt_bare",
            "event_title": "bare",
            "created_at": now,
            "updated_at": now,
            "aggregated_analysis": {"ticker_sentiments": [{"ticker": "HPG", "score": 0.4}]},
            # event_coverage, source_breakdown, concept_sentiments all absent
        }
        fake_db = {"event_clusters": FakeCollection([bare_event])}
        result = run(svc.get_ticker_detail(fake_db, symbol="HPG", window="24h"))
        assert result.article_count == 0
        assert result.event_count == 1
        assert result.sentiment_score == 0.4

    def test_events_survives_source_missing_ai_response(self):
        now = datetime.now(UTC)
        event = make_event(
            source_breakdown=[{"source": "CafeF"}],  # no representative_article, no ai_response
            updated_at=now,
        )
        fake_db = {"event_clusters": FakeCollection([event])}
        result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1, window="72h"))
        assert result.items[0].source_breakdown == []  # excluded, not crashed

    def test_history_survives_row_missing_closing_price_key_entirely(self):
        row = {"ticker": "HPG", "date": "2026-08-01", "daily_sentiment_score": 0.2}  # no closing_price key at all
        fake_db = {"daily_sentiment_history": FakeCollection([row])}
        result = run(svc.get_ticker_history(fake_db, symbol="HPG", days=30))
        assert result.data[0].closing_price is None

    def test_every_vn30_ticker_resolves_metadata_with_zero_events(self):
        """Guards against Ticker enum / ticker_metadata.json drifting apart —
        see test_ticker_metadata.py for the source-of-truth coverage check."""
        from backend.core.enums import Ticker

        for ticker in Ticker:
            fake_db = {"event_clusters": FakeCollection([])}
            result = run(svc.get_ticker_detail(fake_db, symbol=ticker.value, window="24h"))
            assert result.company_name


class TestNoAuthRequired:
    """Ticker detail is a public endpoint (openapi.yaml security: [] at the
    top level; only /audit/* and /auth/* declare bearerAuth) — it must never
    401 regardless of headers sent."""

    def test_request_with_no_authorization_header_still_succeeds(self):
        client = make_client({"event_clusters": FakeCollection([])})
        resp = client.get("/api/ticker/HPG")
        assert resp.status_code != 401
        assert resp.status_code == 200

    def test_request_with_garbage_authorization_header_is_still_ignored(self):
        client = make_client({"event_clusters": FakeCollection([])})
        resp = client.get("/api/ticker/HPG", headers={"Authorization": "Bearer not-a-real-token"})
        assert resp.status_code != 401
        assert resp.status_code == 200


class TestFailsClosedOnBackendTrouble:
    """DB outage or corrupted data must surface as a clean 500 — never a
    200 with wrong/fabricated numbers."""

    def test_db_not_initialized_surfaces_as_500(self):
        from backend.api.features.ticker.router import router as bare_router

        app = FastAPI()
        app.include_router(bare_router)
        # Deliberately NOT overriding db_dep — exercises the real get_db(),
        # which raises RuntimeError before init_db() has ever run.
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/ticker/HPG")
        assert resp.status_code == 500

    def test_out_of_range_score_in_db_is_rejected_not_served(self):
        """A daily_sentiment_score outside [-1, 1] can only mean corrupted
        data upstream — response-model validation must reject it, not pass
        it through to the frontend.

        make_client()'s default TestClient re-raises the ValidationError into
        the test process (a debug-mode convenience, not real deployed
        behavior) — raise_server_exceptions=False here reproduces what an
        actual uvicorn server sends over the wire, which was confirmed
        manually to be a clean 500."""
        corrupted_row = {"ticker": "HPG", "date": "2026-08-01", "daily_sentiment_score": 5.0, "closing_price": None}
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[db_dep] = lambda: {"daily_sentiment_history": FakeCollection([corrupted_row])}
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/ticker/HPG/history")
        assert resp.status_code == 500


class TestOpenapiDocumentsTheValidationErrors:
    """The 422s above are real behavior — openapi.yaml must say so, not just
    list 200/404/500, or the contract undersells what callers actually see."""

    def test_all_three_paths_document_422(self):
        spec = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
        for path in ("/ticker/{symbol}", "/ticker/{symbol}/history", "/ticker/{symbol}/events"):
            assert "422" in spec["paths"][path]["get"]["responses"], f"{path} missing documented 422"

    def test_no_ticker_path_declares_auth_security(self):
        spec = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
        for path in ("/ticker/{symbol}", "/ticker/{symbol}/history", "/ticker/{symbol}/events"):
            assert "security" not in spec["paths"][path]["get"], f"{path} should stay public"


# ============================================================
# GET /api/tickers — the VN30 directory behind the search box
# ============================================================


class TestTickerDirectory:
    def _client(self) -> TestClient:
        app = FastAPI()
        app.include_router(directory_router)
        return TestClient(app)

    def test_returns_every_vn30_ticker(self):
        """30 rows, from the frozen enum — a directory missing a ticker makes it
        permanently unsearchable, with no error anywhere to show why."""
        rows = self._client().get("/api/tickers").json()["tickers"]
        assert {r["ticker"] for r in rows} == {t.value for t in Ticker}

    def test_carries_the_aliases_the_search_box_matches_on(self):
        """FE-01's acceptance criterion: 'HPG' and 'Hoa Phat' find the same
        ticker. That only works if the Vietnamese names ship with the row."""
        rows = self._client().get("/api/tickers").json()["tickers"]
        hpg = next(r for r in rows if r["ticker"] == "HPG")
        assert hpg["company_name"] == "Hoa Phat Group"
        assert any("Hòa Phát" in alias for alias in hpg["aliases"])

    def test_sorted_by_symbol_so_the_order_is_stable(self):
        rows = self._client().get("/api/tickers").json()["tickers"]
        assert [r["ticker"] for r in rows] == sorted(r["ticker"] for r in rows)

    def test_never_touches_the_database(self):
        """No db dependency is overridden here — if the route grew one, this
        client would raise rather than quietly connecting to a real Mongo."""
        assert self._client().get("/api/tickers").status_code == 200
