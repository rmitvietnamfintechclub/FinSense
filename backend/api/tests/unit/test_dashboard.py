"""
backend/api/tests/unit/test_dashboard.py

FS-22/23/24/25 — GET /dashboard/summary, /gauge, /events, /tickers.

Rewritten 2026-08-29. The previous version predated the sync->async migration:
it monkeypatched a `service.get_database` that no longer exists and called the
services synchronously, so all 15 of its tests failed.

Two conventions, both borrowed from the tests that already work here:

- No pytest-asyncio (see test_ticker.py). Async services are driven with
  asyncio.run() from plain sync test functions, so no new test-runner dependency.
- The database is mongomock behind a small async facade rather than a
  hand-written fake. get_tickers' ranking is a real aggregation pipeline
  ($unwind/$match/$group/$sort/$skip/$limit); asserting it against a fake would
  only re-assert the fake's idea of $unwind. mongomock executes it for real, and
  the dashboard read path uses none of the bulk_write/array_filters operators
  CLAUDE.md flags as unsupported.

formulas.py and lexicon.py are used for real — they are deterministic, and
mocking them would assert the mock instead of the blend.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import mongomock
import pytest

from backend.api.features.dashboard import service as svc
from backend.core.config import api_settings
from backend.core.formulas import SFinalResult


def run(coro):
    return asyncio.run(coro)


# ============================================================
# mongomock behind Motor's await-able surface
# ============================================================


class AsyncCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def sort(self, *args, **kwargs):
        self._cursor = self._cursor.sort(*args, **kwargs)
        return self

    def skip(self, n):
        self._cursor = self._cursor.skip(n)
        return self

    def limit(self, n):
        self._cursor = self._cursor.limit(n)
        return self

    async def to_list(self, length=None):
        docs = list(self._cursor)
        return docs if length is None else docs[:length]


class AsyncCollection:
    def __init__(self, sync):
        self._sync = sync

    async def count_documents(self, *args, **kwargs):
        return self._sync.count_documents(*args, **kwargs)

    async def find_one(self, *args, **kwargs):
        return self._sync.find_one(*args, **kwargs)

    def find(self, *args, **kwargs):
        return AsyncCursor(self._sync.find(*args, **kwargs))

    def aggregate(self, *args, **kwargs):
        return AsyncCursor(self._sync.aggregate(*args, **kwargs))


class AsyncDB:
    def __init__(self, sync_db):
        self._db = sync_db

    def __getitem__(self, name):
        return AsyncCollection(self._db[name])


@pytest.fixture
def db():
    # tz_aware=True mirrors database_async.py's real client. Without it mongomock
    # hands back naive datetimes and age_in_hours raises on the subtraction —
    # a fidelity gap that would make these tests pass against a client the app
    # never builds.
    return AsyncDB(mongomock.MongoClient(tz_aware=True).finsense)


# ============================================================
# Document builders
# ============================================================


def hours_ago(n: float) -> datetime:
    return datetime.now(UTC) - timedelta(hours=n)


def cluster(
    cluster_id: str,
    *,
    age_hours: float = 1.0,
    tickers: list[tuple[str, float | None]] | None = None,
    concepts: list[tuple[str, float | None]] | None = None,
    title: str = "An event",
    urls: dict[str, list[str]] | None = None,
) -> dict:
    urls = urls if urls is not None else {"CafeF": ["u1"]}
    return {
        "cluster_id": cluster_id,
        "event_title": title,
        "created_at": hours_ago(age_hours),
        "updated_at": hours_ago(age_hours),
        "event_coverage": {
            "total_articles": sum(len(v) for v in urls.values()),
            "all_urls": urls,
        },
        "aggregated_analysis": {
            "ticker_sentiments": [
                {"ticker": t, "score": s} for t, s in (tickers or [])
            ],
            "concept_sentiments": [
                {"concept": c, "score": s} for c, s in (concepts or [])
            ],
        },
    }


def seed(db: AsyncDB, *docs: dict, articles: int = 0) -> None:
    if docs:
        db["event_clusters"]._sync.insert_many(list(docs))
    if articles:
        db["articles"]._sync.insert_many([{"url": f"u{i}"} for i in range(articles)])


# ============================================================
# FS-22 — get_summary
# ============================================================


class TestGetSummary:
    def test_total_tickers_comes_from_the_enum_not_a_literal(self, db):
        # Compared against the real vocabulary, so the test cannot "pass" by
        # being wrong in the same direction as the code.
        result = run(svc.get_summary(db))
        assert result.total_tickers == len(list(svc.Ticker))

    def test_counts_both_collections(self, db):
        seed(db, cluster("a"), cluster("b"), cluster("c"), articles=7)

        result = run(svc.get_summary(db))

        assert result.total_articles == 7
        assert result.total_events == 3

    def test_empty_db_returns_zeros_and_null_last_updated(self, db):
        """FS-22 AC: an empty database is zeros and a null last_updated, not an
        error — the dashboard renders before the first pipeline run."""
        result = run(svc.get_summary(db))

        assert (result.total_articles, result.total_events) == (0, 0)
        assert result.last_updated is None

    def test_last_updated_is_the_most_recent_event(self, db):
        seed(db, cluster("old", age_hours=50), cluster("recent", age_hours=2))

        result = run(svc.get_summary(db))

        assert result.last_updated is not None
        assert abs((result.last_updated - hours_ago(2)).total_seconds()) < 5


# ============================================================
# FS-23 — get_gauge
# ============================================================


class TestGetGauge:
    def test_no_events_is_the_empty_state_not_a_neutral_score(self, db):
        # 0.0 with is_empty=True must stay distinguishable from a genuine 0.0.
        result = run(svc.get_gauge(db, window="24h"))

        assert result.is_empty is True
        assert result.market_score == 0.0
        assert result.scored_events == 0

    def test_only_events_inside_the_window_are_counted(self, db):
        seed(
            db,
            cluster("inside", age_hours=2, tickers=[("VIC", 0.8)]),
            cluster("outside", age_hours=40, tickers=[("VIC", -0.8)]),
        )

        day = run(svc.get_gauge(db, window="24h"))
        two_days = run(svc.get_gauge(db, window="48h"))

        assert day.total_events_in_window == 1
        assert day.market_score > 0
        # The 40h-old negative event is only visible in the wider window, and it
        # pulls the score down — proving the window bound is real, not cosmetic.
        assert two_days.total_events_in_window == 2
        assert two_days.market_score < day.market_score

    def test_buckets_split_on_the_configured_threshold(self, db):
        threshold = api_settings.SENTIMENT_BUCKET_THRESHOLD
        seed(
            db,
            cluster("pos", tickers=[("VIC", threshold + 0.1)]),
            cluster("neu", tickers=[("VIC", 0.0)]),
            cluster("neg", tickers=[("VIC", -(threshold + 0.1))]),
            # Exactly on the boundary is neutral: bucket_sentiment uses strict
            # comparisons, so a score equal to the threshold is not "positive".
            cluster("edge", tickers=[("VIC", threshold)]),
        )

        result = run(svc.get_gauge(db, window="24h"))

        assert (result.positive_count, result.neutral_count, result.negative_count) == (
            1,
            2,
            1,
        )
        assert result.scored_events == 4

    def test_an_event_with_no_scoreable_entry_is_skipped_not_crashed(self, db):
        seed(
            db,
            cluster("scored", tickers=[("VIC", 0.5)]),
            cluster("all_null", tickers=[("FPT", None)], concepts=[("BANKING", None)]),
            cluster("no_analysis", tickers=[], concepts=[]),
        )

        result = run(svc.get_gauge(db, window="24h"))

        # Counted in the window, but only one of them could be scored.
        assert result.total_events_in_window == 3
        assert result.scored_events == 1
        assert result.is_empty is False

    def test_recent_events_outweigh_older_ones(self, db):
        seed(
            db,
            cluster("fresh", age_hours=0.5, tickers=[("VIC", 1.0)]),
            cluster("stale", age_hours=23, tickers=[("VIC", -1.0)]),
        )

        result = run(svc.get_gauge(db, window="24h"))

        # Equal and opposite scores, so anything other than ~0 is the decay.
        assert result.market_score > 0.1

    def test_concept_scores_count_toward_the_market_score(self, db):
        seed(db, cluster("c", tickers=[], concepts=[("BANKING", 0.6)]))

        result = run(svc.get_gauge(db, window="24h"))

        assert result.scored_events == 1
        assert result.market_score == pytest.approx(0.6, abs=1e-3)


# ============================================================
# FS-24 — get_events
# ============================================================


class TestGetEvents:
    def test_no_events_returns_an_empty_list_not_an_error(self, db):
        result = run(svc.get_events(db, window="24h", page=1, limit=5))

        assert result.events == []
        assert result.has_more is False

    def test_maps_every_field_the_card_renders(self, db):
        seed(
            db,
            cluster(
                "evt_1",
                title="VN-Index rises",
                tickers=[("VIC", 0.4), ("FPT", -0.1)],
                urls={"CafeF": ["u1", "u2"], "VnExpress": ["u3"]},
            ),
        )

        result = run(svc.get_events(db, window="24h", page=1, limit=5))
        item = result.events[0]

        assert item.cluster_id == "evt_1"
        assert item.event_title == "VN-Index rises"
        assert item.total_articles == 3
        assert item.sources == {"CafeF": 2, "VnExpress": 1}
        assert item.tickers_mentioned == ["VIC", "FPT"]

    def test_out_of_vocabulary_tickers_are_dropped_not_rendered(self, db):
        # STATE.md records extractions attributing sentiment to companies outside
        # VN30; one must degrade that row's chip list, not 500 the endpoint.
        seed(db, cluster("evt_1", tickers=[("VIC", 0.4), ("PNJ", 0.2)]))

        result = run(svc.get_events(db, window="24h", page=1, limit=5))

        assert result.events[0].tickers_mentioned == ["VIC"]

    def test_missing_optional_fields_degrade_to_defaults(self, db):
        seed(db, {"cluster_id": "bare", "updated_at": hours_ago(1)})

        result = run(svc.get_events(db, window="24h", page=1, limit=5))
        item = result.events[0]

        assert item.event_title == ""
        assert item.total_articles == 0
        assert item.sources == {}
        assert item.tickers_mentioned == []

    def test_ranked_by_article_count_and_numbered_across_pages(self, db):
        seed(
            db,
            cluster("big", urls={"CafeF": ["a", "b", "c"]}),
            cluster("mid", urls={"CafeF": ["a", "b"]}),
            cluster("small", urls={"CafeF": ["a"]}),
        )

        first = run(svc.get_events(db, window="24h", page=1, limit=2))
        second = run(svc.get_events(db, window="24h", page=2, limit=2))

        assert [e.cluster_id for e in first.events] == ["big", "mid"]
        assert [e.rank for e in first.events] == [1, 2]
        assert first.has_more is True
        # rank continues across the page boundary rather than restarting at 1.
        assert [e.rank for e in second.events] == [3]
        assert second.has_more is False

    def test_the_has_more_probe_row_is_never_returned(self, db):
        seed(db, *(cluster(f"e{i}") for i in range(6)))

        result = run(svc.get_events(db, window="24h", page=1, limit=5))

        assert len(result.events) == 5
        assert result.has_more is True


# ============================================================
# FS-25 — get_tickers
# ============================================================


class TestGetTickers:
    def test_no_qualifying_tickers_returns_an_empty_list(self, db):
        result = run(svc.get_tickers(db, window="24h", page=1, limit=5))

        assert result.tickers == []
        assert result.has_more is False

    def test_ranked_by_how_many_events_mention_the_ticker(self, db):
        seed(
            db,
            cluster("e1", tickers=[("VIC", 0.5), ("FPT", 0.2)]),
            cluster("e2", tickers=[("VIC", 0.3)]),
            cluster("e3", tickers=[("VIC", -0.1), ("FPT", 0.4)]),
        )

        result = run(svc.get_tickers(db, window="24h", page=1, limit=5))

        assert [(t.ticker, t.event_count) for t in result.tickers] == [
            ("VIC", 3),
            ("FPT", 2),
        ]
        assert [t.rank for t in result.tickers] == [1, 2]

    def test_null_scores_and_unknown_tickers_do_not_qualify(self, db):
        seed(
            db,
            cluster("e1", tickers=[("VIC", 0.5), ("FPT", None), ("PNJ", 0.9)]),
        )

        result = run(svc.get_tickers(db, window="24h", page=1, limit=5))

        assert [t.ticker for t in result.tickers] == ["VIC"]

    def test_events_outside_the_window_do_not_qualify(self, db):
        seed(db, cluster("old", age_hours=40, tickers=[("VIC", 0.5)]))

        assert run(svc.get_tickers(db, window="24h", page=1, limit=5)).tickers == []
        assert run(svc.get_tickers(db, window="48h", page=1, limit=5)).tickers != []

    def test_score_is_the_live_s_final_blend_not_a_plain_mean(self, db):
        # VCB's own score is +0.8; BANKING carries weight 1.0 for VCB in
        # static_ontology.json and is -0.8 here. W_TICKER is also 1.0, so the
        # blend is exactly 0.0 while a plain mean of ticker scores would be 0.8.
        # VCB's other concepts (MACRO, REAL_ESTATE) have no score in this event,
        # so their terms are excluded entirely rather than counted as zero.
        seed(db, cluster("e1", tickers=[("VCB", 0.8)], concepts=[("BANKING", -0.8)]))

        result = run(svc.get_tickers(db, window="24h", page=1, limit=5))

        assert result.tickers[0].sentiment_score == pytest.approx(0.0, abs=1e-3)
        assert result.tickers[0].is_empty is False

    def test_is_empty_propagates_instead_of_collapsing_into_a_zero_score(
        self, db, monkeypatch
    ):
        # A ticker in the ranking always has a scoreable event, so the empty
        # state is not reachable through the data — but the flag must still
        # survive the trip from blend_s_final to the response, because a 0.0
        # with is_empty=True renders differently from a genuine neutral.
        monkeypatch.setattr(
            svc, "assemble_live_sentiment",
            lambda *a, **k: SFinalResult(score=0.0, is_empty=True),
        )
        seed(db, cluster("e1", tickers=[("VIC", 0.5)]))

        result = run(svc.get_tickers(db, window="24h", page=1, limit=5))

        assert result.tickers[0].is_empty is True
        assert result.tickers[0].sentiment_score == 0.0

    def test_pagination_is_stable_and_numbered_across_pages(self, db):
        seed(
            db,
            cluster("e1", tickers=[("VIC", 0.1), ("FPT", 0.1), ("HPG", 0.1)]),
            cluster("e2", tickers=[("VIC", 0.1), ("FPT", 0.1)]),
            cluster("e3", tickers=[("VIC", 0.1)]),
        )

        first = run(svc.get_tickers(db, window="24h", page=1, limit=2))
        second = run(svc.get_tickers(db, window="24h", page=2, limit=2))

        assert [t.ticker for t in first.tickers] == ["VIC", "FPT"]
        assert first.has_more is True
        assert [t.ticker for t in second.tickers] == ["HPG"]
        assert [t.rank for t in second.tickers] == [3]
        assert second.has_more is False
