
from urllib.parse import urlencode, parse_qsl, urlparse, urlunparse

# Chỉ những param này được coi là "rác" (tracking), an toàn để loại bỏ.
# Mọi param khác (kể cả lạ, chưa biết) đều được GIỮ LẠI để tránh gộp
# nhầm 2 bài viết khác nhau thành 1.
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "gclid",
    "fbclid",
}


def normalize_url(url: str) -> str:

    if not url or not url.strip():
        raise ValueError("URL is empty or whitespace-only, cannot normalize.")

    parsed = urlparse(url.strip())
    clean_path = parsed.path.rstrip("/")

    query_params = parse_qsl(parsed.query, keep_blank_values=True)
    kept_params = sorted(
        (k, v) for k, v in query_params if k.lower() not in TRACKING_PARAMS
    )
    clean_query = urlencode(kept_params)

    return urlunparse((parsed.scheme, parsed.netloc, clean_path, "", clean_query, ""))