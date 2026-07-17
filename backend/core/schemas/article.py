"""Article — shared document contract for the pipeline."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Article(BaseModel):
    # Proposed article contract for the whole pipeline.


    title: str
    summary: str
    url: str
    source: str
    published_at: datetime
    full_content: str | None = None
