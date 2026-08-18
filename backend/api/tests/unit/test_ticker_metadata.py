"""
tests/unit/test_ticker_dictionary.py

The static ticker dictionary (display_name + aliases) must cover the full
VN30 basket exactly, carry usable alias lists with no cross-ticker
collisions, and be read from disk once per process.
"""

import json
from unittest.mock import MagicMock

import pytest

from backend.core import ticker_metadata
from backend.core.enums import Ticker
from backend.core.schemas.ticker_metadata import TickerEntry
from backend.core.ticker_metadata import get_ticker_dictionary


class TestTickerCoverage:
    def test_every_ticker_present_no_gaps_no_extras(self):
        dictionary = get_ticker_dictionary()
        assert set(dictionary.keys()) == set(Ticker)
        assert len(dictionary) == 30

    def test_values_are_ticker_entry_models(self):
        for entry in get_ticker_dictionary().values():
            assert isinstance(entry, TickerEntry)

    def test_missing_ticker_raises_at_load(self):
        full = json.loads(
            ticker_metadata._DICTIONARY_PATH.read_text(encoding="utf-8")
        )
        dropped = next(iter(full))
        del full[dropped]

        fake_path = MagicMock()
        fake_path.read_text.return_value = json.dumps(full)

        original_path = ticker_metadata._DICTIONARY_PATH
        ticker_metadata._DICTIONARY_PATH = fake_path
        get_ticker_dictionary.cache_clear()
        try:
            with pytest.raises(ValueError, match=dropped):
                get_ticker_dictionary()
        finally:
            ticker_metadata._DICTIONARY_PATH = original_path
            get_ticker_dictionary.cache_clear()


class TestFieldValidity:
    def test_every_display_name_is_nonempty(self):
        for entry in get_ticker_dictionary().values():
            assert entry.display_name.strip()

    def test_every_ticker_has_at_least_one_alias(self):
        for symbol, entry in get_ticker_dictionary().items():
            assert entry.aliases, f"{symbol.value} has no aliases"

    def test_no_alias_is_blank(self):
        for symbol, entry in get_ticker_dictionary().items():
            for alias in entry.aliases:
                assert alias.strip(), f"{symbol.value} has a blank alias"

    def test_aliases_unique_within_a_ticker(self):
        for symbol, entry in get_ticker_dictionary().items():
            lowered = [alias.casefold() for alias in entry.aliases]
            assert len(lowered) == len(set(lowered)), (
                f"{symbol.value} has duplicate aliases"
            )

    def test_no_alias_shared_across_tickers(self):
        seen: dict[str, Ticker] = {}
        for symbol, entry in get_ticker_dictionary().items():
            for alias in entry.aliases:
                key = alias.casefold()
                assert key not in seen, (
                    f"alias {alias!r} claimed by both "
                    f"{seen.get(key)} and {symbol.value}"
                )
                seen[key] = symbol


class TestCaching:
    def test_second_call_does_not_reread_file(self):
        real_content = ticker_metadata._DICTIONARY_PATH.read_text(encoding="utf-8")
        fake_path = MagicMock()
        fake_path.read_text.return_value = real_content

        original_path = ticker_metadata._DICTIONARY_PATH
        ticker_metadata._DICTIONARY_PATH = fake_path
        get_ticker_dictionary.cache_clear()
        try:
            first = get_ticker_dictionary()
            second = get_ticker_dictionary()
        finally:
            ticker_metadata._DICTIONARY_PATH = original_path
            get_ticker_dictionary.cache_clear()

        assert fake_path.read_text.call_count == 1
        assert first is second