import logging

import requests
from bs4 import BeautifulSoup

from backend.core.config import pipeline_settings

logger = logging.getLogger("scraper.adapters.vnexpress")

SOURCE_NAME = "VnExpress"

# VnExpress renders the article body inside <article class="fck_detail">.
CONTENT_SELECTOR = {"tag": "article", "attrs": {"class": "fck_detail"}}
JUNK_SELECTORS = ".ads, .box-tag-list, .banner-ads, script, style"


def fetch_body(url: str, timeout: int = pipeline_settings.HTTP_TIMEOUT) -> str | None:
    """Return the VnExpress article body HTML fragment (junk removed), or None."""
    try:
        resp = requests.get(url, headers=pipeline_settings.HTTP_HEADERS, timeout=timeout)
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
        logger.warning("Main content not found (VnExpress): %s", url)
        return None

    for junk in content_div.select(JUNK_SELECTORS):
        junk.decompose()

    return str(content_div)
