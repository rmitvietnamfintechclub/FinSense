"""Event-level sentiment aggregation.

Pipeline-time stage: collapses each cluster's per-source extraction
scores (source_breakdown) into one confidence-weighted score per ticker
and per concept, written to aggregated_analysis.

The math lives in core/formulas.confidence_weighted_avg; this module is
orchestration only — reading cluster docs, shaping the result document,
and writing it back. Per-source raw scores in source_breakdown are never
touched, so audit corrections can re-derive scores without re-extraction.
"""
from __future__ import annotations

from typing import Any

from backend.core.config import pipeline_settings
from backend.core.formulas import confidence_weighted_avg


def _collect_mentions(
    source_breakdown: list[dict[str, Any]],
    response_field: str,
    key_field: str,
) -> dict[str, tuple[list[float], list[float]]]:
    """
    Gather (scores, confidences) per ticker/concept across all sources,
    preserving first-seen order. A source with no usable ai_confidence
    is kept with confidence 0.0 so the threshold filter drops it, while
    its tickers/concepts still show up in the output (with a null score
    if no confident source mentions them).
    """
    mentions: dict[str, tuple[list[float], list[float]]] = {}
    for source in source_breakdown:
        ai_response = source.get("ai_response") or {}
        confidence = ai_response.get("ai_confidence") or 0.0
        for item in ai_response.get(response_field) or []:
            key = item.get(key_field)
            score = item.get("score")
            if key is None or score is None:
                continue
            scores, confidences = mentions.setdefault(key, ([], []))
            scores.append(score)
            confidences.append(confidence)
    return mentions


def build_aggregated_analysis(
    source_breakdown: list[dict[str, Any]],
    threshold: float,
) -> dict[str, Any]:
    """
    Build the aggregated_analysis sub-document for one cluster.

    Tickers and concepts are aggregated separately. Every ticker/concept
    mentioned by any source appears in the output; ones with no source
    at or above the confidence threshold get score null (no confident
    read — deliberately not a neutral 0).

    needs_review is True when no source in the cluster meets the
    threshold, i.e. the event has no confident read at all.
    """
    result: dict[str, Any] = {}
    for out_field, response_field, key_field in (
        ("ticker_sentiments", "ticker_sentiments", "ticker"),
        ("concept_sentiments", "concept_sentiments", "concept"),
    ):
        mentions = _collect_mentions(source_breakdown, response_field, key_field)
        result[out_field] = [
            {
                key_field: key,
                "score": confidence_weighted_avg(
                    scores, confidences, threshold=threshold
                ),
            }
            for key, (scores, confidences) in mentions.items()
        ]

    result["needs_review"] = not any(
        ((source.get("ai_response") or {}).get("ai_confidence") or 0.0) >= threshold
        for source in source_breakdown
    )
    return result


def run_aggregate(clusters_collection: Any, *, threshold: float | None = None) -> int:
    """
    Aggregate every cluster in the collection and write the result to
    its aggregated_analysis field. Returns the number of clusters
    updated.

    Only aggregated_analysis is $set — source_breakdown and every other
    field stay untouched. Threshold comes from config
    (AI_CONFIDENCE_THRESHOLD) unless overridden by the caller.
    """
    if threshold is None:
        threshold = pipeline_settings.AI_CONFIDENCE_THRESHOLD

    updated = 0
    for cluster in clusters_collection.find({}):
        analysis = build_aggregated_analysis(
            cluster.get("source_breakdown") or [], threshold
        )
        clusters_collection.update_one(
            {"_id": cluster["_id"]},
            {"$set": {"aggregated_analysis": analysis}},
        )
        updated += 1
    return updated
