import logging
from datetime import date as date_type

import requests

from backend.core.config import pipeline_settings
from datetime import date

logger = logging.getLogger(__name__)


def get_closing_price(ticker: str, date: date_type) -> float | None:
    """Return the closing price of ticker on date in absolute VND, or None.

    Never raises: timeouts, HTTP errors, unknown tickers, non-trading days
    (weekends/holidays), and malformed payloads all yield None so the nightly
    pipeline keeps running with a null price field.
    """
    day = date.isoformat()
    params = {
        "sort": "date",
        "q": f"code:{ticker}~date:gte:{day}~date:lte:{day}",
        "size": 1,
    }
    try:
        resp = requests.get(
            pipeline_settings.PRICE_API_URL,
            params=params,
            headers=pipeline_settings.HTTP_HEADERS,
            timeout=pipeline_settings.PRICE_API_TIMEOUT,
        )
        resp.raise_for_status()
        rows = resp.json().get("data", [])
    except requests.exceptions.Timeout:
        logger.warning(
            "Timeout (%ss) fetching closing price for %s on %s",
            pipeline_settings.PRICE_API_TIMEOUT, ticker, day,
        )
        return None
    except requests.exceptions.RequestException as e:
        logger.warning("Failed to fetch closing price for %s on %s: %s", ticker, day, e)
        return None
    except Exception as e:
        logger.warning("Malformed price response for %s on %s: %s", ticker, day, e)
        return None

    if not isinstance(rows, list) or not rows:
        # The API returns HTTP 200 with an empty list for unknown tickers
        # and non-trading days — both are expected, not errors.
        logger.info("No closing price for %s on %s (non-trading day or unknown ticker)", ticker, day)
        return None

    row = rows[0]
    if not isinstance(row, dict):
        logger.warning("Unexpected row shape for %s on %s: %r", ticker, day, row)
        return None

    # Do not trust that the server honoured the query filter. A row for another
    # day or another ticker would be written as this ticker's close for this day.
    if row.get("date") != day or str(row.get("code", "")).upper() != ticker.upper():
        logger.warning(
            "Price API returned a mismatched row for %s on %s: code=%r date=%r",
            ticker, day, row.get("code"), row.get("date"),
        )
        return None

    close = row.get("close")
    if not isinstance(close, (int, float)) or isinstance(close, bool):
        logger.warning("Unexpected close value for %s on %s: %r", ticker, day, close)
        return None

    return float(close) * pipeline_settings.PRICE_QUOTE_MULTIPLIER

if __name__ == "__main__":

    print(get_closing_price("HPG", date(2026, 8, 14)))