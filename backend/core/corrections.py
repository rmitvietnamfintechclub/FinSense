"""Which extraction a reader should use for a source: the admin's, or the AI's.

`ai_response` is immutable — it is what Gemini said, and the accuracy
evaluation depends on that staying true. An admin correction is written to
`audited_response` alongside it, so every consumer that wants "the current best
scores for this source" resolves the pair through here rather than reaching for
`ai_response` directly. Shared by the pipeline and the API, so the two can
never disagree about which one wins.

Two flavours because the call sites are split: the pipeline and
core.aggregation hold validated `SourceBreakdown` models, while the API read
paths and the EOD batch work on raw Mongo dicts.
"""

from __future__ import annotations

from typing import Any

from backend.core.schemas.event_cluster import SourceBreakdown
from backend.core.schemas.sentiment import AIResponse


def effective_response(source: SourceBreakdown) -> AIResponse | None:
    return source.audited_response or source.ai_response


def effective_response_raw(source: dict[str, Any]) -> dict[str, Any] | None:
    return source.get("audited_response") or source.get("ai_response")
