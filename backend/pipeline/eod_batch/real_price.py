import logging
from datetime import date as date_type

import requests

from backend.core.config import pipeline_settings

logger = logging.getLogger(__name__)


def get_closing_price(ticker: str, date: date_type) -> float | None:
    """Return the closing price of ticker on date in absolute VND, or None.

    Never raises: timeouts, HTTP errors, unknown tickers, non-trading days
    (weekends/holidays), and malformed payloads all yield None so the nightly
    pipeline keeps running with a null price field.
    """
    day = date.isoformat()

    if date.weekday() >= 5:
        logger.info(
            "No closing price for %s on %s: the market is closed on %s",
            ticker, day, date.strftime('%A'),
        )
        return None

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
        payload = resp.json()
    except requests.exceptions.Timeout:
        logger.warning(
            "Timeout (%ss) fetching closing price for %s on %s",
            pipeline_settings.PRICE_API_TIMEOUT, ticker, day,
        )
        return None
    except requests.exceptions.RequestException as e:
        # JSONDecodeError subclasses RequestException, so a non-JSON body lands here.
        logger.warning("Failed to fetch closing price for %s on %s: %s", ticker, day, e)
        return None

    if not isinstance(payload, dict):
        logger.warning("Malformed price response for %s on %s: %r", ticker, day, payload)
        return None

    rows = payload.get("data", [])
    if not isinstance(rows, list) or not rows:
        logger.info("No closing price for %s on %s (non-trading day or unknown ticker)", ticker, day)
        return None

    row = rows[0]
    if not isinstance(row, dict):
        logger.warning("Unexpected row shape for %s on %s: %r", ticker, day, row)
        return None

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