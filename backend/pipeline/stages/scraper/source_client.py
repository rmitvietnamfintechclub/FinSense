import logging

from .adapters import cafef, vnexpress
from backend.core.text_utils import strip_html

logger = logging.getLogger("scraper.source_client")

# Keyed by lowercased source name so lookups tolerate whatever casing the
# rss stage tagged the article with ("CafeF", "cafef", " VnExpress ").
_ADAPTERS = {
    cafef.SOURCE_NAME.lower(): cafef.fetch_body,
    vnexpress.SOURCE_NAME.lower(): vnexpress.fetch_body,
}


def fetch_body(source: str, url: str) -> str | None:
    """Fetch the article body for `source` and return it as plain text.

    Dispatches to the per-source adapter (which returns an HTML fragment)
    then strips the markup down to text via html_stripper. Returns None
    if the source is unknown or the fetch/parse fails.
    """
    fetch_fn = _ADAPTERS.get((source or "").strip().lower())
    if not fetch_fn:
        logger.warning("No adapter for source '%s'.", source)
        return None

    return strip_html(fetch_fn(url))
