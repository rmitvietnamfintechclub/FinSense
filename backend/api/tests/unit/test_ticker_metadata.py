"""
tests/unit/test_ticker_metadata.py

Static ticker metadata (display_name + sector) must cover the full VN30
basket exactly, use only valid Concept sectors, and be read from disk
once per process.
"""

from unittest.mock import MagicMock

from backend.core import ticker_metadata
from backend.core.enums import Concept, Ticker
from backend.core.schemas.ticker_metadata import TickerMetadata
from backend.core.ticker_metadata import get_ticker_metadata


class TestTickerCoverage:
    def test_every_ticker_present_no_gaps_no_extras(self):
        metadata = get_ticker_metadata()
        assert set(metadata.keys()) == set(Ticker)
        assert len(metadata) == 30

    def test_values_are_ticker_metadata_models(self):
        for entry in get_ticker_metadata().values():
            assert isinstance(entry, TickerMetadata)


class TestFieldValidity:
    def test_every_sector_is_a_valid_concept(self):
        for entry in get_ticker_metadata().values():
            assert isinstance(entry.sector, Concept)

    def test_every_display_name_is_nonempty(self):
        for entry in get_ticker_metadata().values():
            assert entry.display_name.strip()


class TestCaching:
    def test_second_call_does_not_reread_file(self):
        real_content = ticker_metadata._METADATA_PATH.read_text(encoding="utf-8")
        fake_path = MagicMock()
        fake_path.read_text.return_value = real_content

        original_path = ticker_metadata._METADATA_PATH
        ticker_metadata._METADATA_PATH = fake_path
        get_ticker_metadata.cache_clear()
        try:
            first = get_ticker_metadata()
            second = get_ticker_metadata()
        finally:
            ticker_metadata._METADATA_PATH = original_path
            get_ticker_metadata.cache_clear()

        assert fake_path.read_text.call_count == 1
        assert first is second
