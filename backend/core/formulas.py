"""
core/formulas.py

Pure functions for computing a ticker's live sentiment score at
request time. No I/O here — callers (serving endpoints) are
responsible for reading events from `event_clusters` and weights from
`static_ontology`, then calling these functions with plain data.
Nothing here writes to MongoDB or calls an LLM.

Formulas (see team OneDrive, "recency_weight_formula" and
"s_final_formula"):

  W_time     = e^(-lambda * age_hours)
  S_final    = (I_ticker * W_ticker * S_ticker + sum(I_Ci * wi * S_Ci))
               / (I_ticker * W_ticker + sum(I_Ci * wi))

where S_ticker and each S_Ci are themselves time-weighted averages of
per-event consensus scores using W_time as the weight.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Fixed per spec: naming the ticker directly is always the maximum
# possible weight. Not configurable — this is a modelling constant,
# not an environment-dependent setting.
W_TICKER = 1.0


# ============================================================
# Recency decay — W_time = e^(-lambda * age_hours)
# ============================================================


def recency_weight(age_hours: float, lambda_: float) -> float:
    """
    Time-decay weight for a single event, per the exponential decay
    formula. age_hours=0 (just published) -> weight 1.0. Weight
    approaches 0 as age_hours grows, at a rate controlled by lambda_
    (larger lambda_ = faster decay).

    `lambda_` must come from APISettings.DECAY_LAMBDA[window] at the
    call site — this function never reads config itself, so it stays
    a pure function that's trivial to unit test with any lambda.

    Raises ValueError if age_hours is negative: a negative age means
    the event's created_at is in the future relative to "now", which
    signals a clock or data bug upstream. Silently computing a
    (nonsensical) weight > 1.0 would hide that bug instead of
    surfacing it.
    """
    if age_hours < 0:
        raise ValueError(f"age_hours cannot be negative, got {age_hours}")
    return math.exp(-lambda_ * age_hours)


# ============================================================
# Time-weighted average — shared shape for both S_bar_ticker and
# each S_bar_Ci (the two sub-formulas in s_final_formula.jpg use the
# identical math, just over a different subset of events)
# ============================================================


def time_weighted_average(scored_weights: list[tuple[float, float]]) -> float | None:
    """
    sum(score * weight) / sum(weight) over a list of (score, weight)
    pairs — this computes S_bar_ticker when given (S_event_consensus,
    W_time) pairs for events mentioning the ticker directly, or
    S_bar_Ci when given the same shape for events tagged with concept
    Ci.

    Returns None (not 0.0) if the list is empty or every weight is 0
    — i.e. there is no valid signal to average. This None is what lets
    blend_s_final() distinguish "no news" (I=0, term excluded) from
    "news that happens to average to 0" (a genuinely neutral score).
    """
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
    """
    Blends S_bar_ticker and each S_bar_Ci into S_final via the Dynamic
    Weighted Average formula:

        S_final = (I_ticker * W_ticker * S_ticker + sum(I_Ci * wi * S_Ci))
                  / (I_ticker * W_ticker + sum(I_Ci * wi))

    ticker_avg: S_bar_ticker (output of time_weighted_average() over
        events that directly mention the ticker), or None if no such
        event exists in the window — this None IS I_ticker=0; the
        ticker term is fully excluded from numerator and denominator,
        not just multiplied by 0.

    concept_avgs: {concept_name: S_bar_Ci or None}. A None value for a
        given concept means no event tagged with that concept exists
        in the window — that concept's term is fully excluded
        (I_Ci=0), it does NOT drag the score toward 0 by still adding
        its weight to the denominator.

    concept_weights: {concept_name: wi}, read from `static_ontology`
        for this ticker AT REQUEST TIME by the caller — never
        hardcoded here.

    Returns SFinalResult(0.0, is_empty=True) if there is nothing to
    average at all (ticker_avg is None AND every concept_avgs value
    is None) — the "no news is no signal" empty state, kept distinct
    from a real 0.0.
    """
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