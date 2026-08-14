from pydantic import BaseModel

from backend.core.enums import Concept


class TickerMetadata(BaseModel):
    display_name: str
    sector: Concept
