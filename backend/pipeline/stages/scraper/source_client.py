from __future__ import annotations

import logging

from .adapters import cafef, vnexpress
from .html_stripper import strip_html

logger = logging.getLogger("scraper.source_client")

# Keys are lowercase - lookup normalizes the incoming `source` string
# so "CafeF", "cafef", " CafeF " all resolve to the same adapter.
_ADAPTERS = {
    cafef.SOURCE_NAME.lower(): cafef.fetch_body,
    vnexpress.SOURCE_NAME.lower(): vnexpress.fetch_body,
}


def fetch_body(source: str, url: str) -> str | None:
    """
    Returns clean plain text of the article body, or None if:
    - no adapter is registered for this source
    - the adapter itself failed to fetch/extract (see its own logs)
    """
    key = source.strip().lower()
    fetch_fn = _ADAPTERS.get(key)
    if not fetch_fn:
        logger.warning(f"No adapter registered for source '{source}'.")
        return None

    html_fragment = fetch_fn(url)
    # Bug fixed here: used to return html_fragment directly (still had
    # tags), never went through html_stripper - now returns plain text.
    return strip_html(html_fragment)