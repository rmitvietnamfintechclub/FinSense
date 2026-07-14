import logging

from .adapters import cafef, vnexpress

logger = logging.getLogger("scraper.source_client")

_ADAPTERS = {
    cafef.SOURCE_NAME: cafef.fetch_body,
    vnexpress.SOURCE_NAME: vnexpress.fetch_body,
}


def fetch_body(source: str, url: str) -> str | None:
    
    fetch_fn = _ADAPTERS.get(source)
    if not fetch_fn:
        logger.warning(f"Chưa có adapter cho nguồn '{source}'.")
        return None
    return fetch_fn(url)