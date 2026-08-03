from __future__ import annotations

from collections.abc import Sequence

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
        if sb.ai_response is None:
            continue
        confidence = sb.ai_response.ai_confidence
        for item in getattr(sb.ai_response, items_attr):
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