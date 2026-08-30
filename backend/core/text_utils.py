from __future__ import annotations

from bs4 import BeautifulSoup


def strip_html(html_fragment: str | None) -> str | None:
    """
    Returns plain text, or None if the input is empty/None or if
    stripping tags leaves no text at all (e.g. fragment only had an
    image, no text content).
    """
    if not html_fragment:
        return None

    soup = BeautifulSoup(html_fragment, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    return text if text else None
