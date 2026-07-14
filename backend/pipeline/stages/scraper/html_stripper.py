from bs4 import BeautifulSoup


def strip_html(html_fragment: str | None) -> str | None:

    if not html_fragment:
        return None

    soup = BeautifulSoup(html_fragment, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    return text if text else None