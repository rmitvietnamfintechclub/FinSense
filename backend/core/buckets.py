"""Sentiment bucket vocabulary — the code-side mirror of docs/RUBRICS/SENTIMENT.md.

"""

from __future__ import annotations

# ============================================================
# 5-band partition of the sentiment domain
#
# Written as explicit (lower, upper) literals — deliberately NOT derived from a
# step size or generated at import time, so that the bands are diffable against
# the rubric line by line.
#
# Inclusivity convention (bare floats cannot express it, so it is stated here and
# is part of the contract for whoever writes the lookup):
#   - The neutral band owns BOTH of its endpoints: [-0.2, 0.2].
#   - Every other band is OPEN on the edge facing zero and CLOSED on the edge
#     facing the extreme.
# Giving the resulting bands, in BUCKET_EDGES order:
#   [-1.0, -0.6)   [-0.6, -0.2)   [-0.2, 0.2]   (0.2, 0.6]   (0.6, 1.0]
#
# This is symmetric about zero, contiguous, non-overlapping, and jointly covers
# the full [-1.0, 1.0] domain. It also keeps the neutral band identical to the
# one the live 3-band path already produces at SENTIMENT_BUCKET_THRESHOLD = 0.2,
# so the 5-band scheme is a strict refinement of it rather than a competitor.
# See the "Divergence from the live 3-band path" section of the rubric.
# ============================================================
BUCKET_EDGES: tuple[tuple[float, float], ...] = (
    (-1.0, -0.6),
    (-0.6, -0.2),
    (-0.2, 0.2),
    (0.2, 0.6),
    (0.6, 1.0),
)

# Parallel to BUCKET_EDGES by index. The middle three deliberately reuse the
# exact strings bucket_sentiment() already returns, so the refinement collapses
# back onto the existing vocabulary without a translation table.
BUCKET_LABELS: tuple[str, ...] = (
    "strongly_negative",
    "negative",
    "neutral",
    "positive",
    "strongly_positive",
)
