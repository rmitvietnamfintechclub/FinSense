"""Stage 1 (rss) — canonicalizes candidate URLs before the dedup check.

Two links that point at the same article (different casing, a trailing
slash, a UTM tag tacked on by a share button) must normalize to the same
string, or filter.py's dedup will treat them as different articles.
Meaningful query params (e.g. ?id=123) are kept — they can distinguish
genuinely different articles.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# Query params that vary per-link-share but don't identify the article
# itself. Matched case-insensitively since sources aren't consistent
# about casing (utm_Source, UTM_SOURCE, ...).
_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAM_NAMES = {"fbclid", "gclid", "ref", "spref", "zarsrc"}


def normalize_url(url: str) -> str:
    """Canonicalize a URL for dedup comparison.

    - Forces the scheme to https and lowercases the host (news sites all
      redirect http -> https anyway; this just avoids treating the two
      as distinct articles before that redirect happens).
    - Strips a trailing slash from the path.
    - Drops only known tracking query params; keeps and sorts the rest so
      meaningful params survive and equivalent query strings in a
      different order still match.
    - Drops the fragment (never part of article identity).

    Raises ValueError on an empty or blank URL: a candidate with no URL
    can't be deduped, and silently canonicalizing it would produce a
    garbage key like "https:///". The caller must skip it.
    """
    if url is None or not url.strip():
        raise ValueError("normalize_url received an empty or blank URL")

    parsed = urlparse(url.strip())
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    query_params = sorted(
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith(_TRACKING_PARAM_PREFIXES)
        and key.lower() not in _TRACKING_PARAM_NAMES
    )
    return urlunparse(("https", netloc, path, "", urlencode(query_params), ""))
