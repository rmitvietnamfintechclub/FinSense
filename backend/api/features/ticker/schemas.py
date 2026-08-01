
from __future__ import annotations

from pydantic import BaseModel, Field


class TickerSentimentResponse(BaseModel):
    ticker: str = Field(..., description="Ma co phieu, vd 'HPG'")
    window: str = Field(..., description="Cua so thoi gian: '24h' | '48h' | '72h'")
    score: float = Field(
        ..., ge=-1.0, le=1.0, description="S_final, trong khoang [-1.0, 1.0]"
    )
    is_empty: bool = Field(
        ...,
        description=(
            "True neu khong co event hop le nao trong cua so nay — "
            "score se la 0.0 nhung KHONG duoc hieu la trung tinh, "
            "ma la 'khong co du lieu'."
        ),
    )