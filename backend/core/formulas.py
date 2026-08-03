"""Shared scoring math.

Pure functions only — no DB, no I/O, no config reads. Callers pass in the
numbers (and any policy values such as thresholds); these functions just
compute. Keeps the math unit-testable and identical across the pipeline
and the serving API.
"""
from __future__ import annotations

from collections.abc import Sequence


def confidence_weighted_avg(
    scores: Sequence[float],
    confidences: Sequence[float],
    *,
    threshold: float = 0.0,
) -> float | None:

    if len(scores) != len(confidences):
        raise ValueError(
            f"scores and confidences must be the same length, "
            f"got {len(scores)} and {len(confidences)}"
        )

    weighted_sum = 0.0
    weight_total = 0.0
    for score, confidence in zip(scores, confidences):
        if confidence < threshold:
            continue
        weighted_sum += score * confidence
        weight_total += confidence

    if weight_total <= 0.0:
        return None

    return weighted_sum / weight_total
