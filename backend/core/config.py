"""Shared configuration for the FinSense pipeline.

Central home for tunables that more than one stage needs (HTTP settings,
feed list). Kept import-light so any stage can pull from it without
dragging in heavy dependencies.
"""
from __future__ import annotations

# --- HTTP settings (scraper stage: article body fetch) ---------------------
HTTP_TIMEOUT = 10  # seconds, per request
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# --- RSS discovery (rss stage) --------------------------------------------
# Each pair is (source, feed_url). `source` must match an adapter's
# SOURCE_NAME case-insensitively (see scraper/source_client.py) so the
# scraper can later dispatch the right body extractor.
RSS_FEEDS: list[tuple[str, str]] = [
    ("CafeF", "https://cafef.vn/trang-chu.rss"),
    ("VnExpress", "https://vnexpress.net/rss/kinh-doanh.rss"),
]
