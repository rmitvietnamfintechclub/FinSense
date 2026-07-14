import logging

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("scraper.adapters.cafef")

SOURCE_NAME = "CafeF"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
TIMEOUT = 10

CONTENT_SELECTOR = {"tag": "div", "attrs": {"class": "detail-content"}}
JUNK_SELECTORS = ".ads, .box-related, .banner-ads, script, style"


def fetch_body(url: str, timeout: int = TIMEOUT) -> str | None:

    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        logger.warning(f"Timeout ({timeout}s) khi tải: {url}")
        return None
    except requests.exceptions.RequestException as e:
        logger.warning(f"Tải HTML thất bại [{url}]: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    content_div = soup.find(CONTENT_SELECTOR["tag"], attrs=CONTENT_SELECTOR["attrs"])

    if not content_div:
        logger.warning(f"Không tìm thấy vùng nội dung chính (CafeF): {url}")
        return None

    for junk in content_div.select(JUNK_SELECTORS):
        junk.decompose()

    return str(content_div)