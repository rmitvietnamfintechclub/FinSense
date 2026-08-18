from __future__ import annotations

from datetime import date

import pytest
import requests

# NOTE: update this import if you collapse the package to backend/external/price.py
import backend.pipeline.stages.eod_batch.real_price as adapter

TRADING_DAY = date(2026, 8, 7)  # Friday
SUNDAY = date(2026, 8, 9)
OTHER_DAY = date(2026, 7, 30)

MULTIPLIER = 1000
TICKER = "FPT"


# --- fixtures --------------------------------------------------------------
@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail loudly if any test reaches the real internet.

    Without this, a refactor to requests.Session would silently bypass the
    requests.get stub and start making live calls instead of failing.
    """

    def _blocked(*args, **kwargs):
        raise AssertionError("unit test attempted a real network connection")

    monkeypatch.setattr("socket.socket.connect", _blocked)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    """Pin the settings the adapter reads, so tests never depend on .env."""
    monkeypatch.setattr(
        adapter.pipeline_settings, "PRICE_API_URL", "https://example.invalid/v4/stock_prices"
    )
    monkeypatch.setattr(adapter.pipeline_settings, "PRICE_API_TIMEOUT", 5)
    monkeypatch.setattr(adapter.pipeline_settings, "PRICE_QUOTE_MULTIPLIER", MULTIPLIER)
    monkeypatch.setattr(adapter.pipeline_settings, "HTTP_HEADERS", {"User-Agent": "test"})


# --- fakes -----------------------------------------------------------------
class _FakeResponse:
    """Only the pieces of requests.Response that the adapter touches."""

    def __init__(self, payload=None, status_error=None):
        self._payload = payload
        self._status_error = status_error

    def raise_for_status(self):
        if self._status_error is not None:
            raise self._status_error

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _patch_get(monkeypatch, outcome, captured=None):
    """requests.get stub: raises outcome if it is an exception, else returns it."""

    def fake_get(url, **kwargs):
        if captured is not None:
            captured.update(kwargs, url=url)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(adapter.requests, "get", fake_get)


def _row(close, on_date=TRADING_DAY, code=TICKER):
    return {"code": code, "date": on_date.isoformat(), "close": close}


def _payload(*rows):
    return {"data": list(rows), "totalElements": len(rows)}


# --- success path ----------------------------------------------------------
class TestSuccess:
    def test_applies_quote_multiplier(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse(_payload(_row(70.8))))

        price = adapter.get_closing_price(TICKER, TRADING_DAY)

        assert price == pytest.approx(70.8 * MULTIPLIER)
        assert isinstance(price, float)

    def test_accepts_integer_close(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse(_payload(_row(21))))

        assert adapter.get_closing_price(TICKER, TRADING_DAY) == pytest.approx(21 * MULTIPLIER)

    def test_queries_the_requested_ticker_and_date(self, monkeypatch):
        captured: dict = {}
        _patch_get(monkeypatch, _FakeResponse(_payload(_row(70.8))), captured)

        adapter.get_closing_price(TICKER, TRADING_DAY)

        q = captured["params"]["q"]
        assert f"code:{TICKER}" in q
        assert "date:gte:2026-08-07" in q
        assert "date:lte:2026-08-07" in q

    def test_passes_configured_timeout_and_headers(self, monkeypatch):
        captured: dict = {}
        _patch_get(monkeypatch, _FakeResponse(_payload(_row(70.8))), captured)

        adapter.get_closing_price(TICKER, TRADING_DAY)

        assert captured["timeout"] == 5
        assert captured["headers"] == {"User-Agent": "test"}
        assert captured["url"] == "https://example.invalid/v4/stock_prices"


# --- wrong data is rejected, not returned ----------------------------------
class TestWrongRowRejected:
    """The adapter must not trust that the server honoured the date filter.

    A 200 response carrying a row from another day is the one failure mode
    that silently writes a wrong price into daily_sentiment_history.
    """

    def test_rejects_row_from_a_different_date(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse(_payload(_row(70.8, on_date=OTHER_DAY))))

        assert adapter.get_closing_price(TICKER, TRADING_DAY) is None

    def test_rejects_row_for_a_different_ticker(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse(_payload(_row(70.8, code="VNM"))))

        assert adapter.get_closing_price(TICKER, TRADING_DAY) is None

    def test_rejects_row_with_missing_date_field(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse({"data": [{"code": TICKER, "close": 70.8}]}))

        assert adapter.get_closing_price(TICKER, TRADING_DAY) is None


# --- network failures return None ------------------------------------------
class TestNetworkFailures:
    def test_timeout_returns_none(self, monkeypatch):
        _patch_get(monkeypatch, requests.exceptions.Timeout())

        assert adapter.get_closing_price(TICKER, TRADING_DAY) is None

    def test_connection_error_returns_none(self, monkeypatch):
        _patch_get(monkeypatch, requests.exceptions.ConnectionError())

        assert adapter.get_closing_price(TICKER, TRADING_DAY) is None

    def test_http_error_returns_none(self, monkeypatch):
        _patch_get(
            monkeypatch,
            _FakeResponse(status_error=requests.exceptions.HTTPError("500 Server Error")),
        )

        assert adapter.get_closing_price(TICKER, TRADING_DAY) is None

    def test_rate_limit_returns_none(self, monkeypatch):
        _patch_get(
            monkeypatch,
            _FakeResponse(status_error=requests.exceptions.HTTPError("429 Too Many Requests")),
        )

        assert adapter.get_closing_price(TICKER, TRADING_DAY) is None


# --- expected empty results return None ------------------------------------
class TestEmptyResults:
    def test_unknown_ticker_returns_none(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse(_payload()))

        assert adapter.get_closing_price("ZZZZ", TRADING_DAY) is None

    def test_non_trading_day_returns_none(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse(_payload()))

        assert adapter.get_closing_price(TICKER, SUNDAY) is None

    def test_missing_data_key_returns_none(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse({"totalElements": 0}))

        assert adapter.get_closing_price(TICKER, TRADING_DAY) is None


# --- malformed payloads return None ----------------------------------------
class TestMalformedPayloads:
    def test_invalid_json_returns_none(self, monkeypatch):
        # requests raises JSONDecodeError, which subclasses both ValueError
        # and RequestException. Using a bare ValueError here would exercise a
        # different except branch than production does.
        _patch_get(
            monkeypatch,
            _FakeResponse(requests.exceptions.JSONDecodeError("not json", "", 0)),
        )

        assert adapter.get_closing_price(TICKER, TRADING_DAY) is None

    def test_top_level_list_returns_none(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse(["not", "a", "dict"]))

        assert adapter.get_closing_price(TICKER, TRADING_DAY) is None

    def test_data_is_dict_not_list_returns_none(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse({"data": {"close": 70.8}}))

        assert adapter.get_closing_price(TICKER, TRADING_DAY) is None

    def test_row_is_not_a_dict_returns_none(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse({"data": ["70.8"]}))

        assert adapter.get_closing_price(TICKER, TRADING_DAY) is None

    def test_string_close_returns_none(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse(_payload(_row("70.8"))))

        assert adapter.get_closing_price(TICKER, TRADING_DAY) is None

    def test_none_close_returns_none(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse(_payload(_row(None))))

        assert adapter.get_closing_price(TICKER, TRADING_DAY) is None

    def test_bool_close_returns_none(self, monkeypatch):
        # bool is a subclass of int; without an explicit guard, float(True)
        # would be written as a price of 1 * MULTIPLIER.
        _patch_get(monkeypatch, _FakeResponse(_payload(_row(True))))

        assert adapter.get_closing_price(TICKER, TRADING_DAY) is None

    def test_missing_close_field_returns_none(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse({"data": [{"code": TICKER, "date": "2026-08-07"}]}))

        assert adapter.get_closing_price(TICKER, TRADING_DAY) is None


# --- log level distinguishes expected gaps from real faults ----------------
class TestLogging:
    def test_empty_result_is_not_logged_as_an_error(self, monkeypatch, caplog):
        _patch_get(monkeypatch, _FakeResponse(_payload()))

        with caplog.at_level("DEBUG", logger=adapter.logger.name):
            adapter.get_closing_price(TICKER, SUNDAY)

        assert caplog.records, "expected the empty result to be logged"
        assert all(r.levelno < 30 for r in caplog.records), (
            "a closed market is expected, not a warning"
        )

    def test_timeout_is_logged_as_a_warning(self, monkeypatch, caplog):
        _patch_get(monkeypatch, requests.exceptions.Timeout())

        with caplog.at_level("DEBUG", logger=adapter.logger.name):
            adapter.get_closing_price(TICKER, TRADING_DAY)

        assert any(r.levelno >= 30 for r in caplog.records)