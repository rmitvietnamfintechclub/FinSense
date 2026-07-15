from __future__ import annotations


def tag_source(article: dict, source_name: str) -> dict:
    return {**article, "source": source_name}
