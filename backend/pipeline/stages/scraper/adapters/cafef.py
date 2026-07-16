import logging

import requests
from bs4 import BeautifulSoup

from backend.core.config import HTTP_HEADERS, HTTP_TIMEOUT

logger = logging.getLogger("scraper.adapters.cafef")

SOURCE_NAME = "CafeF"

CONTENT_SELECTOR = {"tag": "div", "attrs": {"class": "detail-content"}}
JUNK_SELECTORS = ".ads, .box-related, .banner-ads, script, style"


def fetch_body(url: str, timeout: int = HTTP_TIMEOUT) -> str | None:
    """Return the CafeF article body HTML fragment (junk removed), or None."""
    try:
        resp = requests.get(url, headers=HTTP_HEADERS, timeout=timeout)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        logger.warning("Timeout (%ss) while fetching: %s", timeout, url)
        return None
    except requests.exceptions.RequestException as e:
        logger.warning("Failed to fetch HTML [%s]: %s", url, e)
        return None

    # Pass raw bytes so BeautifulSoup detects the page's declared charset
    # instead of requests guessing it wrong for Vietnamese content.
    soup = BeautifulSoup(resp.content, "html.parser")
    content_div = soup.find(CONTENT_SELECTOR["tag"], attrs=CONTENT_SELECTOR["attrs"])

    if not content_div:
        logger.warning("Main content not found (CafeF): %s", url)
        return None

    for junk in content_div.select(JUNK_SELECTORS):
        junk.decompose()

    return str(content_div)
