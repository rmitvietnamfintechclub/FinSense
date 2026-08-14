from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from backend.pipeline.stages.aggregate.eod_batch import run_eod_batch


class _FakeHistoryCollection:
    """Gia lap upsert that bang dict — cho phep test idempotency chinh
    xac (chay 2 lan khong tao ban ghi thu 2), khong chi ghi lai lenh goi."""

    def __init__(self):
        self.docs: dict[tuple[str, str], dict] = {}

    def update_one(self, filter_q, update_q, upsert):
        key = (filter_q["ticker"], filter_q["date"])
        self.docs[key] = update_q["$set"]

    def count_documents(self, query=None):
        return len(self.docs)


def _fake_db(events_by_ticker: dict[str, list] | None = None):
    events_by_ticker = events_by_ticker or {}

    class _FakeEventsCollection:
        def find(self, query):
            # query co chua "aggregated_analysis.ticker_sentiments.ticker": <ticker>
            ticker = query["aggregated_analysis.ticker_sentiments.ticker"]
            return events_by_ticker.get(ticker, [])

    return {
        "event_clusters": _FakeEventsCollection(),
        "daily_sentiment_history": _FakeHistoryCollection(),
    }


def _no_price(ticker: str, target_date: date) -> None:
    return None


class TestRunEodBatch:
    def test_all_30_tickers_get_a_row_every_run(self):
        db = _fake_db()
        stats = run_eod_batch(date(2026, 8, 10), db, _no_price, confidence_threshold=0.4)
        assert stats["tickers_processed"] == 30
        assert db["daily_sentiment_history"].count_documents() == 30

    def test_ticker_with_zero_events_gets_null_score_not_zero(self):
        """Acceptance criteria: 'A ticker with zero qualifying events
        gets a row with daily_sentiment_score: null'."""
        db = _fake_db()  # khong ticker nao co event
        run_eod_batch(date(2026, 8, 10), db, _no_price, confidence_threshold=0.4)
        record = db["daily_sentiment_history"].docs[("HPG", "2026-08-10")]
        assert record["daily_sentiment_score"] is None
        assert record["data_points_used"] == 0

    def test_only_sources_above_threshold_contribute(self):
        events = [
            {
                "cluster_id": "evt_1",
                "source_breakdown": [
                    {
                        "ai_response": {
                            "ai_confidence": 0.7,
                            "ticker_sentiments": [{"ticker": "HPG", "score": 0.6}],
                        },
                        "is_audited": True,
                    },
                    {
                        # duoi threshold -- phai bi loai hoan toan, khong
                        # duoc keo lech ket qua
                        "ai_response": {
                            "ai_confidence": 0.2,
                            "ticker_sentiments": [{"ticker": "HPG", "score": -0.9}],
                        },
                        "is_audited": False,
                    },
                ],
            }
        ]
        db = _fake_db({"HPG": events})
        run_eod_batch(date(2026, 8, 10), db, _no_price, confidence_threshold=0.4)
        record = db["daily_sentiment_history"].docs[("HPG", "2026-08-10")]
        assert record["daily_sentiment_score"] == pytest.approx(0.6)
        assert record["data_points_used"] == 1

    def test_price_adapter_returning_none_produces_null_and_completes(self):
        db = _fake_db()
        stats = run_eod_batch(date(2026, 8, 10), db, _no_price, confidence_threshold=0.4)
        assert stats["tickers_processed"] == 30
        assert db["daily_sentiment_history"].docs[("HPG", "2026-08-10")]["closing_price"] is None

    def test_price_adapter_raising_exception_never_crashes_the_run(self):
        """Acceptance criteria: 'Price adapter returning None produces
        closing_price: null and the run completes' — mo rong: adapter
        RAISE loi cung khong duoc lam sap ca batch."""

        def _crashing_price(ticker: str, target_date: date) -> float:
            raise ConnectionError("simulated network failure")

        db = _fake_db()
        stats = run_eod_batch(date(2026, 8, 10), db, _crashing_price, confidence_threshold=0.4)
        assert stats["tickers_processed"] == 30
        assert db["daily_sentiment_history"].docs[("HPG", "2026-08-10")]["closing_price"] is None

    def test_running_twice_for_same_date_produces_one_row_per_ticker(self):
        """Acceptance criteria: 'running the job twice for the same
        date produces exactly one row per ticker'."""
        db = _fake_db()
        run_eod_batch(date(2026, 8, 10), db, _no_price, confidence_threshold=0.4)
        run_eod_batch(date(2026, 8, 10), db, _no_price, confidence_threshold=0.4)
        assert db["daily_sentiment_history"].count_documents() == 30

    def test_no_recency_decay_score_is_plain_confidence_weighted_avg(self):
        """Acceptance criteria: 'No recency decay applied' — 2 nguon
        cung confidence, khong quan tam nguon nao 'moi hon', ket qua
        phai la trung binh don gian theo confidence, khong lech theo
        thoi gian trong ngay."""
        events = [
            {
                "cluster_id": "evt_1",
                "source_breakdown": [
                    {
                        "ai_response": {
                            "ai_confidence": 0.8,
                            "ticker_sentiments": [{"ticker": "HPG", "score": 0.4}],
                        },
                        "is_audited": True,
                    },
                    {
                        "ai_response": {
                            "ai_confidence": 0.8,
                            "ticker_sentiments": [{"ticker": "HPG", "score": -0.4}],
                        },
                        "is_audited": True,
                    },
                ],
            }
        ]
        db = _fake_db({"HPG": events})
        run_eod_batch(date(2026, 8, 10), db, _no_price, confidence_threshold=0.4)
        record = db["daily_sentiment_history"].docs[("HPG", "2026-08-10")]
        # 2 nguon cung trong so, diem trai dau -> trung binh phai la 0,
        # khong bi lech ve phia nao ca (neu co decay se bi lech)
        assert record["daily_sentiment_score"] == pytest.approx(0.0)


class TestEnsureIndex:
    def test_calls_create_index_with_correct_spec(self):
        from backend.pipeline.stages.aggregate.eod_batch import ensure_daily_sentiment_history_index
        from unittest.mock import MagicMock

        mock_collection = MagicMock()
        db = {"daily_sentiment_history": mock_collection}
        ensure_daily_sentiment_history_index(db)

        mock_collection.create_index.assert_called_once()
        call_args = mock_collection.create_index.call_args
        keys = call_args[0][0]
        assert keys == [("ticker", 1), ("date", 1)]
        assert call_args[1]["unique"] is True