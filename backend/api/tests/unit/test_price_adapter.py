from __future__ import annotations

from datetime import date

import requests

import backend.api.external.price.adapters.vndirect as vndirect

TRADING_DAY = date(2026, 8, 7)
SUNDAY = date(2026, 8, 9)


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

    monkeypatch.setattr(vndirect.requests, "get", fake_get)


def _finfo_payload(close):
    return {
        "data": [{"code": "FPT", "date": TRADING_DAY.isoformat(), "close": close}],
        "totalElements": 1,
    }


# --- success path ----------------------------------------------------------
class TestSuccess:
    def test_returns_absolute_vnd(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse(_finfo_payload(70.8)))

        price = vndirect.get_closing_price("FPT", TRADING_DAY)

        assert price == 70800.0
        assert isinstance(price, float)

    def test_queries_the_requested_date(self, monkeypatch):
        captured: dict = {}
        _patch_get(monkeypatch, _FakeResponse(_finfo_payload(70.8)), captured)

        vndirect.get_closing_price("FPT", TRADING_DAY)

        assert "date:gte:2026-08-07~date:lte:2026-08-07" in captured["params"]["q"]
        assert "code:FPT" in captured["params"]["q"]


# --- network failures return None ------------------------------------------
class TestNetworkFailures:
    def test_timeout_returns_none(self, monkeypatch):
        _patch_get(monkeypatch, requests.exceptions.Timeout())

        assert vndirect.get_closing_price("FPT", TRADING_DAY) is None

    def test_connection_error_returns_none(self, monkeypatch):
        _patch_get(monkeypatch, requests.exceptions.ConnectionError())

        assert vndirect.get_closing_price("FPT", TRADING_DAY) is None

    def test_http_error_returns_none(self, monkeypatch):
        _patch_get(
            monkeypatch,
            _FakeResponse(status_error=requests.exceptions.HTTPError("500")),
        )

        assert vndirect.get_closing_price("FPT", TRADING_DAY) is None


# --- expected empty results return None -------------------------------------
class TestEmptyResults:
    def test_unknown_ticker_returns_none(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse({"data": [], "totalElements": 0}))

        assert vndirect.get_closing_price("XXXX", TRADING_DAY) is None

    def test_non_trading_day_returns_none(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse({"data": [], "totalElements": 0}))

        assert vndirect.get_closing_price("FPT", SUNDAY) is None


# --- malformed payloads return None -----------------------------------------
class TestMalformedPayloads:
    def test_invalid_json_returns_none(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse(ValueError("not json")))

        assert vndirect.get_closing_price("FPT", TRADING_DAY) is None

    def test_non_dict_payload_returns_none(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse(["not", "a", "dict"]))

        assert vndirect.get_closing_price("FPT", TRADING_DAY) is None

    def test_non_numeric_close_returns_none(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse(_finfo_payload("70.8")))

        assert vndirect.get_closing_price("FPT", TRADING_DAY) is None

    def test_missing_close_field_returns_none(self, monkeypatch):
        payload = {"data": [{"code": "FPT", "date": TRADING_DAY.isoformat()}]}
        _patch_get(monkeypatch, _FakeResponse(payload))

        assert vndirect.get_closing_price("FPT", TRADING_DAY) is None
