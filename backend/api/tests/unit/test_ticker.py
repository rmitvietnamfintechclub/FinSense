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
from backend.api.features.ticker import aggregator, service as svc
from backend.api.features.ticker.router import db_dep, router, valid_symbol
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

REPO_ROOT = Path(__file__).resolve().parents[4]
OPENAPI_PATH = REPO_ROOT / "docs" / "openapi.yaml"


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
        self.last_cursor = FakeCursor(self.items)
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

    def test_company_name_and_sector_come_from_ticker_metadata(self):
        now = datetime.now(UTC)
        fake_db = {"event_clusters": FakeCollection([make_event(updated_at=now)])}
        result = run(svc.get_ticker_detail(fake_db, symbol="HPG", window="24h"))
        assert result.company_name == "Hoa Phat Group"
        assert result.sector == "MATERIALS"

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
        resp = client.get("/api/v1/ticker/ZZZ")
        assert resp.status_code == 404

    def test_known_ticker_with_no_events_returns_200_with_empty_state(self):
        client = make_client({"event_clusters": FakeCollection([])})
        resp = client.get("/api/v1/ticker/HPG")
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_empty_state"] is True
        assert body["sentiment_score"] is None

    def test_lowercase_symbol_is_accepted(self):
        client = make_client({"event_clusters": FakeCollection([])})
        resp = client.get("/api/v1/ticker/hpg")
        assert resp.status_code == 200
        assert resp.json()["ticker"] == "HPG"


# ============================================================
# GET /ticker/{symbol}/history
# ============================================================


class TestGetTickerHistory:
    @pytest.mark.parametrize("days", [7, 30, 90])
    def test_all_three_ranges_work(self, days):
        rows = [{"ticker": "HPG", "date": "2026-08-01", "daily_sentiment_score": 0.1, "closing_price": 100.0}]
        fake_db = {"daily_sentiment_history": FakeCollection(rows)}
        result = run(svc.get_ticker_history(fake_db, symbol="HPG", days=days))
        assert result.days == days
        assert len(result.data) == 1

    def test_rows_ordered_oldest_to_newest(self):
        # Mongo would hand these back sorted descending (.sort("date", -1)) —
        # the FakeCursor's sort() is a no-op, so we hand it pre-sorted like
        # the real driver would, and assert the service reverses it.
        newest_first = [
            {"ticker": "HPG", "date": "2026-08-03", "daily_sentiment_score": 0.3, "closing_price": 103.0},
            {"ticker": "HPG", "date": "2026-08-02", "daily_sentiment_score": 0.2, "closing_price": 102.0},
            {"ticker": "HPG", "date": "2026-08-01", "daily_sentiment_score": 0.1, "closing_price": 101.0},
        ]
        fake_db = {"daily_sentiment_history": FakeCollection(newest_first)}
        result = run(svc.get_ticker_history(fake_db, symbol="HPG", days=30))
        assert [row.date for row in result.data] == ["2026-08-01", "2026-08-02", "2026-08-03"]

    def test_nulls_pass_through_untouched_no_interpolation(self):
        # Newest-first, as Mongo's own .sort("date", -1) would already hand back.
        rows = [
            {"ticker": "HPG", "date": "2026-08-03", "daily_sentiment_score": 0.3, "closing_price": None},
            {"ticker": "HPG", "date": "2026-08-02", "daily_sentiment_score": None, "closing_price": None},
            {"ticker": "HPG", "date": "2026-08-01", "daily_sentiment_score": 0.1, "closing_price": 100.0},
        ]
        fake_db = {"daily_sentiment_history": FakeCollection(rows)}
        result = run(svc.get_ticker_history(fake_db, symbol="HPG", days=7))
        assert len(result.data) == 3  # no rows dropped, no rows synthesized
        assert result.data[1].daily_sentiment_score is None
        assert result.data[1].closing_price is None
        assert result.data[2].daily_sentiment_score == 0.3
        assert result.data[2].closing_price is None  # a null field next to a non-null one — not filled in

    def test_more_rows_available_than_requested_keeps_the_most_recent_not_the_oldest(self):
        """Classic off-by-one spot: sort ascending + take first N would
        silently return the OLDEST N days instead of the most recent N."""
        ten_days_newest_first = [
            {"ticker": "HPG", "date": f"2026-08-{10 - i:02d}", "daily_sentiment_score": 0.1 * i, "closing_price": 100 + i}
            for i in range(10)
        ]
        fake_db = {"daily_sentiment_history": FakeCollection(ten_days_newest_first)}
        result = run(svc.get_ticker_history(fake_db, symbol="HPG", days=7))
        assert [row.date for row in result.data] == [
            "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-08", "2026-08-09", "2026-08-10",
        ]

    def test_query_is_scoped_to_the_requested_ticker_only(self):
        """A history collection holds rows for all 30 tickers — the query
        filter, not client-side filtering, must isolate the requested one."""
        history_collection = FakeCollection([{"ticker": "HPG", "date": "2026-08-01", "daily_sentiment_score": 0.1, "closing_price": 100.0}])
        fake_db = {"daily_sentiment_history": history_collection}
        run(svc.get_ticker_history(fake_db, symbol="HPG", days=30))
        assert history_collection.last_query == {"ticker": "HPG"}

    def test_fewer_available_days_than_requested_is_a_partial_array_not_an_error(self):
        rows = [
            {"ticker": "HPG", "date": "2026-08-01", "daily_sentiment_score": 0.1, "closing_price": 100.0},
            {"ticker": "HPG", "date": "2026-08-02", "daily_sentiment_score": 0.2, "closing_price": 101.0},
        ]
        client = make_client({"daily_sentiment_history": FakeCollection(rows)})
        resp = client.get("/api/v1/ticker/HPG/history", params={"days": 90})
        assert resp.status_code == 200
        body = resp.json()
        assert body["days"] == 90
        assert len(body["data"]) == 2

    def test_unknown_symbol_returns_404(self):
        client = make_client({"daily_sentiment_history": FakeCollection([])})
        resp = client.get("/api/v1/ticker/ZZZ/history")
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
        result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1))
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
        result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1))
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

        hpg_result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1))
        assert hpg_result.items[0].sentiment_score == 0.5  # event level
        assert hpg_result.items[0].source_breakdown[0].score == 0.55  # source level

        fake_db_2 = {"event_clusters": FakeCollection([event])}
        vnm_result = run(svc.get_ticker_events(fake_db_2, symbol="VNM", page=1))
        assert vnm_result.items[0].sentiment_score == -0.3
        assert vnm_result.items[0].source_breakdown[0].score == -0.35

    def test_sources_below_confidence_threshold_are_excluded(self):
        now = datetime.now(UTC)
        below = make_source("CafeF", {"HPG": 0.7}, confidence=pipeline_settings.AI_CONFIDENCE_THRESHOLD - 0.05)
        above = make_source("VnExpress", {"HPG": 0.3}, confidence=pipeline_settings.AI_CONFIDENCE_THRESHOLD + 0.05)
        event = make_event(source_breakdown=[below, above], updated_at=now)
        fake_db = {"event_clusters": FakeCollection([event])}
        result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1))
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
        result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1))
        assert [row.source for row in result.items[0].source_breakdown] == ["CafeF"]

    def test_event_with_null_ticker_score_still_appears_in_the_list(self):
        now = datetime.now(UTC)
        event = make_event(ticker_sentiments=[{"ticker": "HPG", "score": None}], updated_at=now)
        fake_db = {"event_clusters": FakeCollection([event])}
        result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1))
        assert len(result.items) == 1
        assert result.items[0].sentiment_score is None

    def test_article_count_comes_from_event_coverage_not_breakdown_row_count(self):
        now = datetime.now(UTC)
        source = make_source("CafeF", {"HPG": 0.4}, confidence=0.9)
        event = make_event(source_breakdown=[source], total_articles=12, updated_at=now)
        fake_db = {"event_clusters": FakeCollection([event])}
        result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1))
        assert result.items[0].article_count == 12
        assert len(result.items[0].source_breakdown) == 1  # 12 articles, 1 source row — expected

    def test_newest_first_sort_is_requested_from_mongo(self):
        now = datetime.now(UTC)
        fake_db = {"event_clusters": FakeCollection([make_event(updated_at=now)])}
        run(svc.get_ticker_events(fake_db, symbol="HPG", page=1))
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
        result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1))
        assert [item.cluster_id for item in result.items] == ["evt_0", "evt_1", "evt_2", "evt_3"]

    def test_pagination_boundary_exactly_one_page_reports_no_more(self):
        """Off-by-one guard: exactly page_size events must not falsely
        report has_more (the +1 probe row must not itself count as 'more')."""
        now = datetime.now(UTC)
        page_size = api_settings.TICKER_EVENTS_PAGE_SIZE
        events = [make_event(cluster_id=f"evt_{i}", updated_at=now - timedelta(hours=i)) for i in range(page_size)]
        fake_db = {"event_clusters": FakeCollection(events)}
        result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1))
        assert len(result.items) == page_size
        assert result.has_more is False

    def test_pagination_boundary_one_over_a_page_leaves_exactly_one_for_page_two(self):
        now = datetime.now(UTC)
        page_size = api_settings.TICKER_EVENTS_PAGE_SIZE
        events = [make_event(cluster_id=f"evt_{i}", updated_at=now - timedelta(hours=i)) for i in range(page_size + 1)]
        fake_db_1 = {"event_clusters": FakeCollection(events)}
        page1 = run(svc.get_ticker_events(fake_db_1, symbol="HPG", page=1))
        fake_db_2 = {"event_clusters": FakeCollection(events)}
        page2 = run(svc.get_ticker_events(fake_db_2, symbol="HPG", page=2))
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
        page1 = run(svc.get_ticker_events(fake_db_1, symbol="HPG", page=1))
        fake_db_2 = {"event_clusters": FakeCollection(all_events)}
        page2 = run(svc.get_ticker_events(fake_db_2, symbol="HPG", page=2))
        fake_db_3 = {"event_clusters": FakeCollection(all_events)}
        page3 = run(svc.get_ticker_events(fake_db_3, symbol="HPG", page=3))

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
        result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1))
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
        resp = client.get("/api/v1/ticker/ZZZ/events")
        assert resp.status_code == 404

    def test_no_events_returns_200_with_empty_array(self):
        client = make_client({"event_clusters": FakeCollection([])})
        resp = client.get("/api/v1/ticker/HPG/events")
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
        resp = client.get("/api/v1/ticker/HPG", params={"window": "99h"})
        assert resp.status_code == 422

    def test_events_endpoint_has_no_window_param_extra_query_arg_is_ignored(self):
        """Confirms the deliberate removal of window scoping from /events —
        this is 'full event history, paginated', not window-scoped like the
        gauge on GET /ticker/{symbol}. An unrecognized query string here
        must not error (FastAPI ignores unknown query params by default)."""
        now = datetime.now(UTC)
        client = make_client({"event_clusters": FakeCollection([make_event(updated_at=now)])})
        resp = client.get("/api/v1/ticker/HPG/events", params={"window": "1w"})
        assert resp.status_code == 200
        assert "window" not in resp.json()

    def test_invalid_days_is_422_not_silently_clamped(self):
        client = make_client({"daily_sentiment_history": FakeCollection([])})
        resp = client.get("/api/v1/ticker/HPG/history", params={"days": 15})
        assert resp.status_code == 422

    @pytest.mark.parametrize("page", [0, -1])
    def test_non_positive_page_is_422(self, page):
        client = make_client({"event_clusters": FakeCollection([])})
        resp = client.get("/api/v1/ticker/HPG/events", params={"page": page})
        assert resp.status_code == 422

    def test_omitted_window_falls_back_to_default_not_an_error(self):
        client = make_client({"event_clusters": FakeCollection([])})
        resp = client.get("/api/v1/ticker/HPG")
        assert resp.status_code == 200
        assert resp.json()["window"] == api_settings.DEFAULT_WINDOW

    def test_symbol_with_stray_characters_is_404_not_500(self):
        client = make_client({"event_clusters": FakeCollection([])})
        resp = client.get("/api/v1/ticker/HPG!")
        assert resp.status_code == 404


class TestPaginationExtremes:
    def test_page_far_beyond_available_data_is_empty_200_not_error(self):
        now = datetime.now(UTC)
        fake_db = {"event_clusters": FakeCollection([make_event(updated_at=now)])}
        client = make_client(fake_db)
        resp = client.get("/api/v1/ticker/HPG/events", params={"page": 999})
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
        result = run(svc.get_ticker_events(fake_db, symbol="HPG", page=1))
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
            assert result.sector


class TestNoAuthRequired:
    """Ticker detail is a public endpoint (openapi.yaml security: [] at the
    top level; only /audit/* and /auth/* declare bearerAuth) — it must never
    401 regardless of headers sent."""

    def test_request_with_no_authorization_header_still_succeeds(self):
        client = make_client({"event_clusters": FakeCollection([])})
        resp = client.get("/api/v1/ticker/HPG")
        assert resp.status_code != 401
        assert resp.status_code == 200

    def test_request_with_garbage_authorization_header_is_still_ignored(self):
        client = make_client({"event_clusters": FakeCollection([])})
        resp = client.get("/api/v1/ticker/HPG", headers={"Authorization": "Bearer not-a-real-token"})
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
        resp = client.get("/api/v1/ticker/HPG")
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
        resp = client.get("/api/v1/ticker/HPG/history")
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
