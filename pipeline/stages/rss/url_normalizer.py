from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAM_NAMES = {"fbclid", "gclid", "ref", "spref"}


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    query_params = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.startswith(_TRACKING_PARAM_PREFIXES) and key not in _TRACKING_PARAM_NAMES
    ]
    return urlunparse(("https", netloc, path, "", urlencode(query_params), ""))
