from __future__ import annotations

BUCKETS: tuple[tuple[float, float, str], ...] = (
    (-1.0, -0.6, "strongly_negative"),
    (-0.6, -0.2, "negative"),
    (-0.2,  0.2, "neutral"),
    ( 0.2,  0.6, "positive"),
    ( 0.6,  1.0, "strongly_positive"),
)