from __future__ import annotations

import logging

import requests
from bs4 import BeautifulSoup

from ..config import HEADERS, TIMEOUT

logger = logging.getLogger("scraper.adapters.cafef")

SOURCE_NAME = "CafeF"

CONTENT_SELECTOR = {"tag": "div", "attrs": {"class": "detail-content"}}
JUNK_SELECTORS = ".ads, .box-related, .banner-ads, script, style"


def fetch_body(url: str, timeout: int = TIMEOUT) -> str | None:
    """
    Returns the HTML fragment of the main content region (site-specific
    junk already removed), or None on any failure - never raises, so
    the pipeline can continue processing other articles.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        logger.warning(f"Timeout ({timeout}s) while fetching: {url}")
        return None
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to fetch HTML [{url}]: {e}")
        return None

    # Use resp.content (raw bytes) instead of resp.text - lets
    # BeautifulSoup detect encoding from the page's own meta tags,
    # instead of trusting requests' charset guess (which can mangle
    # Vietnamese diacritics if the server doesn't set headers clearly).
    soup = BeautifulSoup(resp.content, "html.parser")
    content_div = soup.find(CONTENT_SELECTOR["tag"], attrs=CONTENT_SELECTOR["attrs"])

    if not content_div:
        logger.warning(f"Main content region not found (CafeF): {url}")
        return None

    for junk in content_div.select(JUNK_SELECTORS):
        junk.decompose()

    return str(content_div)