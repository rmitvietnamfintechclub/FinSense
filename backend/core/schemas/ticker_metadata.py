# backend/core/schemas/ticker_dictionary.py
from __future__ import annotations

from pydantic import BaseModel, Field


class TickerEntry(BaseModel):
    display_name: str = Field(min_length=1)
    aliases: list[str] = Field(min_length=1)