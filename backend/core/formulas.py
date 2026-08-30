from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

# Fixed per spec: naming the ticker directly is always the maximum
# possible weight. Not configurable — this is a modelling constant,
# not an environment-dependent setting.
W_TICKER = 1.0


# ============================================================
# Recency decay — W_time = e^(-lambda * age_hours)
# ============================================================
def recency_weight(age_hours: float, lambda_: float) -> float:
    if age_hours < 0:
        raise ValueError(f"age_hours cannot be negative, got {age_hours}")
    return math.exp(-lambda_ * age_hours)


# ============================================================
# Time-weighted average — shared shape for both S_bar_ticker and
# each S_bar_Ci (the two sub-formulas in s_final_formula.jpg use the
# identical math, just over a different subset of events)
# ============================================================
def time_weighted_average(scored_weights: list[tuple[float, float]]) -> float | None:
    if not scored_weights:
        return None

    weight_sum = sum(w for _, w in scored_weights)
    if weight_sum == 0:
        return None

    weighted_sum = sum(score * weight for score, weight in scored_weights)
    return weighted_sum / weight_sum


# ============================================================
# S_final blend
# ============================================================
@dataclass(frozen=True)
class SFinalResult:
    score: float
    is_empty: bool  # True = no valid events at all (empty state) — a
    # 0.0 with is_empty=True must be rendered differently from a
    # 0.0 with is_empty=False (genuinely neutral sentiment).


def blend_s_final(
    ticker_avg: float | None,
    concept_avgs: dict[str, float | None],
    concept_weights: dict[str, float],
) -> SFinalResult:
    numerator = 0.0
    denominator = 0.0

    if ticker_avg is not None:
        numerator += W_TICKER * ticker_avg
        denominator += W_TICKER

    for concept, avg in concept_avgs.items():
        if avg is None:
            continue  # I_Ci = 0 — term fully excluded, not zeroed-in
        wi = concept_weights.get(concept, 0.0)
        numerator += wi * avg
        denominator += wi

    if denominator == 0:
        return SFinalResult(score=0.0, is_empty=True)

    return SFinalResult(score=numerator / denominator, is_empty=False)



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


def bucket_sentiment(score: float, threshold: float) -> str:
    if score > threshold:
        return "positive"
    if score < -threshold:
        return "negative"
    return "neutral"

def clamp_score(score: float) -> float:
    """Nothing in the pipeline enforces the [-1, 1] range on stored AI scores,
    and the response models declare it — one out-of-bounds value would fail
    validation for the whole payload instead of degrading a single card."""
    return max(-1.0, min(1.0, score))
