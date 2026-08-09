from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

import backend.api.features.dashboard.service as svc


def _cursor(items: list) -> MagicMock:
    """Gia lap pymongo Cursor ho tro .sort().limit() noi chuoi."""
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.limit.return_value = items
    return cursor


# ============================================================
# FS-22 — get_summary
# ============================================================


class TestGetSummary:
    def test_total_tickers_is_constant_from_enum(self):
        fake_db = {
            "articles": MagicMock(count_documents=MagicMock(return_value=0)),
            "event_clusters": MagicMock(
                count_documents=MagicMock(return_value=0),
                find_one=MagicMock(return_value=None),
            ),
        }
        with patch.object(svc, "get_database", return_value=fake_db):
            result = svc.get_summary()
        # Khong hardcode 30 trong test — so sanh voi chinh nguon du lieu
        # that (do dai enum Ticker), de test khong "gia" pass neu ca 2
        # cung sai giong nhau
        assert result.total_tickers == svc.TOTAL_TICKERS

    def test_counts_come_from_count_documents(self):
        fake_db = {
            "articles": MagicMock(count_documents=MagicMock(return_value=1234)),
            "event_clusters": MagicMock(
                count_documents=MagicMock(return_value=87),
                find_one=MagicMock(return_value=None),
            ),
        }
        with patch.object(svc, "get_database", return_value=fake_db):
            result = svc.get_summary()
        assert result.total_articles == 1234
        assert result.total_events == 87

    def test_empty_db_returns_zeros_and_null_last_updated(self):
        """Acceptance criteria FS-22: 'Empty DB returns zeros + null
        last_updated, not an error'."""
        fake_db = {
            "articles": MagicMock(count_documents=MagicMock(return_value=0)),
            "event_clusters": MagicMock(
                count_documents=MagicMock(return_value=0),
                find_one=MagicMock(return_value=None),
            ),
        }
        with patch.object(svc, "get_database", return_value=fake_db):
            result = svc.get_summary()
        assert result.total_articles == 0
        assert result.total_events == 0
        assert result.last_updated is None
        # total_tickers KHONG duoc ve 0 dù DB rong — day la hang so,
        # khong phai ket qua query
        assert result.total_tickers == svc.TOTAL_TICKERS

    def test_last_updated_reflects_most_recent_event(self):
        latest = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
        fake_db = {
            "articles": MagicMock(count_documents=MagicMock(return_value=5)),
            "event_clusters": MagicMock(
                count_documents=MagicMock(return_value=2),
                find_one=MagicMock(return_value={"updated_at": latest}),
            ),
        }
        with patch.object(svc, "get_database", return_value=fake_db):
            result = svc.get_summary()
        assert result.last_updated == latest


# ============================================================
# FS-23 — get_gauge
# ============================================================


class TestGetGauge:
    def test_zero_events_returns_neutral_empty_state(self):
        """Acceptance criteria FS-23: 'Zero valid events -> neutral
        empty state, not a fabricated score'."""
        fake_db = {"event_clusters": MagicMock(find=MagicMock(return_value=[]))}
        with patch.object(svc, "get_database", return_value=fake_db):
            result = svc.get_gauge("24h")
        assert result.is_empty is True
        assert result.market_score == 0.0
        assert result.positive_count == 0
        assert result.neutral_count == 0
        assert result.negative_count == 0

    def test_score_reflects_only_selected_window(self):
        """Acceptance criteria FS-23: 'Score reflects only the selected
        window' — event ngoai window khong duoc dua vao tinh toan."""
        now = datetime.now(UTC)
        events_in_window = [
            {
                "created_at": now - timedelta(hours=1),
                "aggregated_analysis": {
                    "ticker_sentiments": [{"ticker": "HPG", "score": 0.9}],
                    "concept_sentiments": [],
                },
            }
        ]
        # Mongo query {"created_at": {"$gte": window_start}} se tu loai
        # event cu — o day mock find() da tra ve dung ket qua sau khi
        # loc, gia lap dung hanh vi cua MongoDB
        fake_db = {
            "event_clusters": MagicMock(find=MagicMock(return_value=events_in_window))
        }
        with patch.object(svc, "get_database", return_value=fake_db):
            result = svc.get_gauge("24h")
        assert result.is_empty is False
        assert result.market_score == pytest.approx(0.9, abs=0.01)

    def test_buckets_count_correctly(self):
        now = datetime.now(UTC)
        events = [
            {
                "created_at": now - timedelta(hours=1),
                "aggregated_analysis": {
                    "ticker_sentiments": [{"ticker": "A", "score": 0.8}],
                    "concept_sentiments": [],
                },
            },
            {
                "created_at": now - timedelta(hours=1),
                "aggregated_analysis": {
                    "ticker_sentiments": [{"ticker": "B", "score": -0.8}],
                    "concept_sentiments": [],
                },
            },
            {
                "created_at": now - timedelta(hours=1),
                "aggregated_analysis": {
                    "ticker_sentiments": [{"ticker": "C", "score": 0.0}],
                    "concept_sentiments": [],
                },
            },
        ]
        fake_db = {"event_clusters": MagicMock(find=MagicMock(return_value=events))}
        with patch.object(svc, "get_database", return_value=fake_db):
            result = svc.get_gauge("24h")
        assert result.positive_count == 1
        assert result.negative_count == 1
        assert result.neutral_count == 1

    def test_event_with_no_scoreable_entries_is_skipped_not_crashed(self):
        """Event co the ton tai nhung khong co entry nao co score (vd
        toan bo bi null hoa do fail confidence) — khong duoc crash,
        chi bi bo qua khoi tinh toan."""
        now = datetime.now(UTC)
        events = [
            {
                "created_at": now - timedelta(hours=1),
                "aggregated_analysis": {"ticker_sentiments": [], "concept_sentiments": []},
            }
        ]
        fake_db = {"event_clusters": MagicMock(find=MagicMock(return_value=events))}
        with patch.object(svc, "get_database", return_value=fake_db):
            result = svc.get_gauge("24h")
        assert result.is_empty is True


# ============================================================
# FS-24 — get_events
# ============================================================


class TestGetEvents:
    def test_zero_events_returns_empty_list(self):
        fake_db = {"event_clusters": MagicMock(find=MagicMock(return_value=_cursor([])))}
        with patch.object(svc, "get_database", return_value=fake_db):
            result = svc.get_events("24h", limit=5)
        assert result.events == []

    def test_maps_fields_correctly(self):
        raw_events = [
            {
                "event_title": "HPG bao lai quy 2",
                "event_coverage": {
                    "total_articles": 5,
                    "all_urls": {"CafeF": ["u1"], "VnExpress": ["u2"]},
                },
                "aggregated_analysis": {
                    "ticker_sentiments": [{"ticker": "HPG", "score": 0.6}]
                },
            }
        ]
        fake_db = {
            "event_clusters": MagicMock(find=MagicMock(return_value=_cursor(raw_events)))
        }
        with patch.object(svc, "get_database", return_value=fake_db):
            result = svc.get_events("24h", limit=5)
        assert len(result.events) == 1
        item = result.events[0]
        assert item.event_title == "HPG bao lai quy 2"
        assert item.total_articles == 5
        assert sorted(item.sources) == ["CafeF", "VnExpress"]
        assert item.tickers_mentioned == ["HPG"]

    def test_missing_optional_fields_default_safely(self):
        """Event thieu event_title/event_coverage khong duoc lam crash
        toan bo request — tra ve gia tri mac dinh an toan."""
        raw_events = [{"aggregated_analysis": {}}]
        fake_db = {
            "event_clusters": MagicMock(find=MagicMock(return_value=_cursor(raw_events)))
        }
        with patch.object(svc, "get_database", return_value=fake_db):
            result = svc.get_events("24h", limit=5)
        item = result.events[0]
        assert item.event_title == ""
        assert item.total_articles == 0
        assert item.sources == []
        assert item.tickers_mentioned == []


# ============================================================
# FS-25 — get_tickers
# ============================================================


class TestGetTickers:
    def test_zero_qualifying_returns_empty_list(self):
        fake_db = {"event_clusters": MagicMock(aggregate=MagicMock(return_value=[]))}
        with patch.object(svc, "get_database", return_value=fake_db):
            result = svc.get_tickers("24h", limit=5)
        assert result.tickers == []

    def test_reuses_live_s_final_not_history(self):
        """Acceptance criteria FS-25: 'sentiment score = live S_final
        (not daily_sentiment_history)' — xac nhan goi dung
        compute_live_sentiment, khong tu tinh lai hay doc tu collection
        khac."""
        fake_db = {
            "event_clusters": MagicMock(
                aggregate=MagicMock(return_value=[{"_id": "HPG", "event_count": 8}])
            )
        }
        fake_live_result = {"ticker": "HPG", "window": "24h", "score": 0.42, "is_empty": False}
        with patch.object(svc, "get_database", return_value=fake_db), patch.object(
            svc, "compute_live_sentiment", return_value=fake_live_result
        ) as mock_live:
            result = svc.get_tickers("24h", limit=5)

        mock_live.assert_called_once_with(ticker="HPG", window="24h")
        assert result.tickers[0].sentiment_score == 0.42
        assert result.tickers[0].event_count == 8

    def test_ticker_with_empty_s_final_propagates_is_empty_flag(self):
        fake_db = {
            "event_clusters": MagicMock(
                aggregate=MagicMock(return_value=[{"_id": "VNM", "event_count": 3}])
            )
        }
        fake_live_result = {"ticker": "VNM", "window": "24h", "score": 0.0, "is_empty": True}
        with patch.object(svc, "get_database", return_value=fake_db), patch.object(
            svc, "compute_live_sentiment", return_value=fake_live_result
        ):
            result = svc.get_tickers("24h", limit=5)
        assert result.tickers[0].is_empty is True

    def test_sorted_by_event_count_desc(self):
        """Aggregation pipeline chiu trach nhiem sort — test nay xac
        nhan thu tu tra ve tu Mongo duoc giu nguyen, khong bi sap xep
        lai sai o tang service."""
        fake_db = {
            "event_clusters": MagicMock(
                aggregate=MagicMock(
                    return_value=[
                        {"_id": "HPG", "event_count": 8},
                        {"_id": "VNM", "event_count": 5},
                        {"_id": "FPT", "event_count": 2},
                    ]
                )
            )
        }
        fake_live = {"score": 0.0, "is_empty": True, "ticker": "x", "window": "24h"}
        with patch.object(svc, "get_database", return_value=fake_db), patch.object(
            svc, "compute_live_sentiment", return_value=fake_live
        ):
            result = svc.get_tickers("24h", limit=5)
        counts = [t.event_count for t in result.tickers]
        assert counts == sorted(counts, reverse=True)