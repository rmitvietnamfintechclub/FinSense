from urllib.parse import urlparse, urlunparse


def normalize_url(url: str) -> str:
    # ex: "https://cafef.vn/bai.html/?utm_source=fb" -> "https://cafef.vn/bai.html"
    
    parsed = urlparse(url.strip())
    clean_path = parsed.path.rstrip("/")
    return urlunparse((parsed.scheme, parsed.netloc, clean_path, "", "", ""))