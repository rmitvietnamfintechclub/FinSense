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
    """
    Confidence-weighted average of per-source sentiment scores:

        S_event = Σ(S_source_i × Confidence_i) / Σ(Confidence_i)

    Each source's AI confidence acts as its weight, so a score the model
    was sure about pulls the event score harder than a hesitant one.

    Sources with `confidence < threshold` are dropped from *both* the
    numerator and the denominator — they do not dilute the result. The
    default threshold of 0.0 keeps every source (an identity filter); the
    real policy value lives in config (AI_CONFIDENCE_THRESHOLD) and is
    passed in by the caller.

    Returns None — never 0.0 — when no source survives the threshold or
    the surviving weights sum to zero. None means "no confident read",
    which is a different thing from a neutral 0.0 sentiment.

    Raises ValueError if the two sequences differ in length.
    """
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
