"""Confidence-weighted blend of per-source extractions into a cluster's
aggregated_analysis.

Lives in core/, not the aggregate stage, because BOTH the pipeline (which
computes it on ingest) and the API (which must recompute it when an admin
corrects a source in the audit panel) need it, and the API may not import from
backend.pipeline. Same reasoning as core/formulas.py — see ADR-001.
"""

from __future__ import annotations

from collections.abc import Sequence

from backend.core.corrections import effective_response
from backend.core.formulas import confidence_weighted_avg
from backend.core.schemas.event_cluster import SourceBreakdown
from backend.core.schemas.sentiment import (
    AggregatedAnalysis,
    AggregatedConceptSentiment,
    AggregatedTickerSentiment,
)


def _collect_mentions(
    source_breakdown: Sequence[SourceBreakdown],
    items_attr: str,
    key_attr: str,
) -> dict[str, tuple[list[float], list[float]]]:
    
    mentions: dict[str, tuple[list[float], list[float]]] = {}
    for sb in source_breakdown:
        # Corrections must survive re-aggregation. Resolving the pair here, and
        # not in the audit service, means a pipeline run over a corrected
        # cluster reproduces the corrected blend rather than reverting it.
        response = effective_response(sb)
        if response is None:
            continue
        confidence = response.ai_confidence
        for item in getattr(response, items_attr):
            key = getattr(item, key_attr)
            scores, confidences = mentions.setdefault(key, ([], []))
            scores.append(item.score)
            confidences.append(confidence)
    return mentions


def build_aggregated_analysis(
    source_breakdown: Sequence[SourceBreakdown],
    threshold: float,
) -> AggregatedAnalysis:
    
    tickers = _collect_mentions(source_breakdown, "ticker_sentiments", "ticker")
    concepts = _collect_mentions(source_breakdown, "concept_sentiments", "concept")

    return AggregatedAnalysis(
        ticker_sentiments=[
            AggregatedTickerSentiment(
                ticker=key,
                score=confidence_weighted_avg(s, c, threshold=threshold),
            )
            for key, (s, c) in tickers.items()
        ],
        concept_sentiments=[
            AggregatedConceptSentiment(
                concept=key,
                score=confidence_weighted_avg(s, c, threshold=threshold),
            )
            for key, (s, c) in concepts.items()
        ]
    )