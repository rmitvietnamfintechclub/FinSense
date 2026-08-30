"""
backend/api/features/audit/service.py

Admin audit panel. Reads and writes event_clusters, appends to audit_log.

The queue is FLAT — one row per (cluster_id, source) — because a source entry,
not a cluster, is the unit an admin approves or corrects.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import ValidationError

from backend.api.features.audit.schemas import (
    AuditAction,
    AuditActionResult,
    AuditArticleRow,
    AuditArticles,
    AuditLog,
    AuditLogEntry,
    AuditSort,
    AuditStatus,
    AuditSummary,
    ConceptScore,
    LastAudit,
    TickerScore,
)
from backend.api.features.auth.schemas import CurrentAdmin
from backend.core.aggregation import build_aggregated_analysis
from backend.core.config import APISettings, api_settings, pipeline_settings
from backend.core.corrections import effective_response_raw
from backend.core.schemas.event_cluster import SourceBreakdown

logger = logging.getLogger(__name__)

EVENT_CLUSTERS_COLLECTION = "event_clusters"
ARTICLES_COLLECTION = "articles"
AUDIT_LOG_COLLECTION = "audit_log"


class ClusterSourceNotFoundError(Exception):
    """No such cluster, or the cluster has no entry for that source."""


class InvalidAuditActionError(Exception):
    """The action is well-formed JSON but not a coherent audit action."""


# ============================================================
# GET /api/audit/summary
# ============================================================


async def get_audit_summary(db: AsyncIOMotorDatabase) -> AuditSummary:
    total_articles = await db[ARTICLES_COLLECTION].count_documents({})

    # is_audited lives inside the source_breakdown array, so counting audited
    # ENTRIES (not documents) needs an unwind — count_documents would count each
    # cluster once no matter how many of its sources are audited.
    pipeline: list[dict[str, Any]] = [
        {"$unwind": "$source_breakdown"},
        {"$match": {"source_breakdown.is_audited": True}},
        {"$count": "n"},
    ]
    rows = await db[EVENT_CLUSTERS_COLLECTION].aggregate(pipeline).to_list(length=1)
    audited = rows[0]["n"] if rows else 0

    # pending = total - audited by product decision, so it includes articles that
    # were never centroid-selected and have no ai_response to audit. max(0, ...)
    # because the two counts come from different collections and a mid-pipeline
    # read could otherwise produce a negative.
    return AuditSummary(
        total_articles=total_articles,
        audited_articles=audited,
        pending_review=max(0, total_articles - audited),
    )


# ============================================================
# GET /api/audit/articles
# ============================================================

_SORT_STAGES: dict[AuditSort, list[tuple[str, int]]] = {
    AuditSort.NEWEST: [("published_at", -1)],
    AuditSort.OLDEST: [("published_at", 1)],
    AuditSort.CONFIDENCE_DESC: [("ai_confidence", -1)],
    AuditSort.CONFIDENCE_ASC: [("ai_confidence", 1)],
}


def _coerce_scores(raw: list[dict], model, key: str, cluster_id: str) -> list:
    """Drops entries whose ticker/concept is outside the frozen vocabulary.

    A stored value can be out-of-vocabulary — STATE.md records extractions
    attributing sentiment to companies outside VN30 — and CLAUDE.md's rule is
    that such entries are logged and dropped, never fatal. Without this, ONE bad
    row 500s the entire audit queue rather than degrading that single row.
    """
    valid = []
    for item in raw or []:
        try:
            valid.append(model(**item))
        except ValidationError:
            logger.warning(
                "audit queue: dropping out-of-vocabulary %s %r on cluster %s",
                key, item.get(key), cluster_id,
            )
    return valid


def _row_from_flat(doc: dict) -> AuditArticleRow:
    sb = doc["source_breakdown"]
    ai = sb.get("ai_response") or {}
    # Current values are the admin's where one exists; the AI's are returned
    # alongside so the correction form can always show what it is changing FROM,
    # including on a second correction of the same row.
    effective = effective_response_raw(sb) or {}
    rep = sb.get("representative_article") or {}
    last = doc.get("last_audit")
    cluster_id = doc.get("cluster_id") or ""

    return AuditArticleRow(
        cluster_id=cluster_id,
        source=sb.get("source") or "",
        # Nullable in storage; the client falls back to event_title, and so does
        # this response by carrying event_title alongside rather than substituting.
        article_title=rep.get("title"),
        event_title=doc.get("event_title") or "",
        article_url=rep.get("url") or "",
        # created_at is always present on a cluster, so a representative_article
        # missing its own published_at degrades to the cluster's date rather than
        # raising KeyError and taking down the whole response.
        published_at=rep.get("published_at") or doc["created_at"],
        ticker_count=len(effective.get("ticker_sentiments") or []),
        ai_confidence=ai.get("ai_confidence") if ai.get("ai_confidence") is not None else 0.0,
        is_audited=bool(sb.get("is_audited")),
        content_fed_to_ai=rep.get("content_fed_to_ai"),
        model_version=ai.get("model_version") or "",
        prompt_version=ai.get("prompt_version") or "",
        ticker_sentiments=_coerce_scores(effective.get("ticker_sentiments"), TickerScore, "ticker", cluster_id),
        concept_sentiments=_coerce_scores(effective.get("concept_sentiments"), ConceptScore, "concept", cluster_id),
        original_ticker_sentiments=_coerce_scores(ai.get("ticker_sentiments"), TickerScore, "ticker", cluster_id),
        original_concept_sentiments=_coerce_scores(ai.get("concept_sentiments"), ConceptScore, "concept", cluster_id),
        last_audit=(
            LastAudit(
                admin_name=last.get("admin_name") or "",
                action_type=last.get("action_type") or "",
                error_type=last.get("error_type"),
                performed_at=last["performed_at"],
            )
            if last
            else None
        ),
    )


async def get_audit_articles(
    db: AsyncIOMotorDatabase,
    status: AuditStatus,
    sort: AuditSort,
    search: str | None,
    page: int,
    settings: APISettings = api_settings,
) -> AuditArticles:
    page_size = settings.AUDIT_PAGE_SIZE
    skip = (page - 1) * page_size

    match_stage: dict[str, Any] = {
        # A source with no extraction cannot be judged, so it never enters the queue.
        "source_breakdown.ai_response": {"$ne": None}
    }
    if status is AuditStatus.PENDING:
        match_stage["source_breakdown.is_audited"] = False
    elif status is AuditStatus.AUDITED:
        match_stage["source_breakdown.is_audited"] = True

    if search:
        # Escaped: a ticker or title from the search box is user input, and an
        # unescaped '(' or '*' would be read as regex syntax and raise.
        pattern = re.escape(search.strip())
        match_stage["$or"] = [
            {"source_breakdown.representative_article.title": {"$regex": pattern, "$options": "i"}},
            {"event_title": {"$regex": pattern, "$options": "i"}},
            {"source_breakdown.ai_response.ticker_sentiments.ticker": {"$regex": f"^{pattern}$", "$options": "i"}},
        ]

    sort_spec = dict(_SORT_STAGES[sort])
    # cluster_id + source break ties: $sort alone is not a total order here, and a
    # non-total order silently drops or repeats rows across pages.
    sort_spec_full = {
        **{
            (
                "source_breakdown.representative_article.published_at"
                if k == "published_at"
                else "source_breakdown.ai_response.ai_confidence"
            ): v
            for k, v in sort_spec.items()
        },
        "cluster_id": 1,
        "source_breakdown.source": 1,
    }

    pipeline: list[dict[str, Any]] = [
        {"$unwind": "$source_breakdown"},
        {"$match": match_stage},
        {"$sort": sort_spec_full},
        {
            "$facet": {
                # One round trip for both the page and the total, so the count
                # cannot disagree with the rows because of a write in between.
                "total": [{"$count": "n"}],
                "rows": [
                    {"$skip": skip},
                    {"$limit": page_size + 1},  # +1 probes has_more, never returned
                    {
                        "$lookup": {
                            "from": AUDIT_LOG_COLLECTION,
                            "let": {"cid": "$cluster_id", "src": "$source_breakdown.source"},
                            "pipeline": [
                                {"$match": {"$expr": {"$and": [
                                    {"$eq": ["$cluster_id", "$$cid"]},
                                    {"$eq": ["$source", "$$src"]},
                                ]}}},
                                {"$sort": {"performed_at": -1}},
                                {"$limit": 1},
                            ],
                            "as": "_last",
                        }
                    },
                    {"$addFields": {"last_audit": {"$first": "$_last"}}},
                ],
            }
        },
    ]

    result = await db[EVENT_CLUSTERS_COLLECTION].aggregate(pipeline).to_list(length=1)
    facet = result[0] if result else {"total": [], "rows": []}
    total = facet["total"][0]["n"] if facet["total"] else 0
    docs = facet["rows"]

    has_more = len(docs) > page_size
    return AuditArticles(
        page=page,
        has_more=has_more,
        total=total,
        items=[_row_from_flat(d) for d in docs[:page_size]],
    )


# ============================================================
# PATCH /api/audit/events/{cluster_id}/{source}
# ============================================================


def _merge_scores(
    existing: list[dict], corrections: list, key: str
) -> list[dict]:
    """Corrections are a PARTIAL list — only what the admin changed. Anything not
    named keeps its AI value. v1 has no removal: a correction can change or add a
    score but never drop one (a hallucinated ticker is recorded via error_type
    'Wrong ticker' instead)."""
    merged = {item[key]: dict(item) for item in existing}
    for correction in corrections or []:
        # str(): Ticker/Concept are StrEnums, and a bare member would be stored
        # as an enum in Mongo and compare unequal to the plain strings already
        # in the document — making scores_changed fire on an unchanged value.
        name = str(getattr(correction, key))
        merged[name] = {key: name, "score": correction.score}
    return list(merged.values())


def _reject_null_scores(corrections: list | None, key: str) -> None:
    """A null correction score has no meaning in v1.

    openapi's SentimentScore is nullable because a null is legitimate elsewhere
    (an aggregated score with no qualifying source, a history row with no data),
    and the audit models reuse it. But ai_response.ticker_sentiments[].score is
    non-nullable, so merging a null in makes the document fail validation on the
    way back out — previously as an uncaught ValidationError from
    _rebuild_analysis, i.e. a 500 on a request the contract said was legal.

    Refused here with the alternative spelled out, because v1 deliberately has no
    removal mechanism: a hallucinated ticker is recorded via error_type, and its
    score stays in the extraction.
    """
    for item in corrections or []:
        if item.score is None:
            raise InvalidAuditActionError(
                f"corrected {key} {str(getattr(item, key))!r} has a null score. "
                "v1 has no removal mechanism — to flag an entry the AI should not "
                "have produced, use error_type 'Wrong ticker' and leave its score."
            )


def _find_source(cluster: dict, source: str) -> dict:
    for sb in cluster.get("source_breakdown") or []:
        if sb.get("source") == source:
            return sb
    raise ClusterSourceNotFoundError(f"Cluster {cluster.get('cluster_id')!r} has no source {source!r}")


async def apply_audit_action(
    db: AsyncIOMotorDatabase,
    cluster_id: str,
    source: str,
    action: AuditAction,
    admin: CurrentAdmin,
) -> AuditActionResult:
    if action.action_type == "correct" and action.error_type is None:
        raise InvalidAuditActionError("error_type is required when action_type is 'correct'")
    if action.action_type == "approve" and (
        action.error_type is not None
        or action.corrected_ticker_sentiments
        or action.corrected_concept_sentiments
    ):
        # Rejected rather than ignored: an approve carrying an error_type would
        # be logged as an error nobody corrected, inflating the US-G5 taxonomy
        # with phantom entries that no score change backs up.
        raise InvalidAuditActionError(
            "approve must not carry error_type or corrected scores — use action_type 'correct'"
        )
    _reject_null_scores(action.corrected_ticker_sentiments, "ticker")
    _reject_null_scores(action.corrected_concept_sentiments, "concept")

    collection = db[EVENT_CLUSTERS_COLLECTION]
    cluster = await collection.find_one({"cluster_id": cluster_id})
    if cluster is None:
        raise ClusterSourceNotFoundError(f"No cluster {cluster_id!r}")

    entry = _find_source(cluster, source)
    ai_response = entry.get("ai_response")
    if ai_response is None:
        raise InvalidAuditActionError(
            f"Source {source!r} has no ai_response — there is nothing to audit yet"
        )

    # Corrections stack: a second correction edits the first admin's numbers,
    # not the AI's, so audit_log's old_* records what actually changed.
    base_response = effective_response_raw(entry) or ai_response
    old_tickers = list(base_response.get("ticker_sentiments") or [])
    old_concepts = list(base_response.get("concept_sentiments") or [])

    is_correction = action.action_type == "correct"
    new_tickers = (
        _merge_scores(old_tickers, action.corrected_ticker_sentiments, "ticker")
        if is_correction
        else old_tickers
    )
    new_concepts = (
        _merge_scores(old_concepts, action.corrected_concept_sentiments, "concept")
        if is_correction
        else old_concepts
    )
    scores_changed = is_correction and (
        new_tickers != old_tickers or new_concepts != old_concepts
    )

    set_fields: dict[str, Any] = {"source_breakdown.$[entry].is_audited": True}
    if scores_changed:
        # A whole AIResponse, not just the two score lists: audited_response has
        # to validate on its own, and it carries the confidence/model/prompt of
        # the run being corrected so the two stay comparable. ai_response is
        # never in the $set — that is the point of the split.
        set_fields["source_breakdown.$[entry].audited_response"] = {
            **base_response,
            "ticker_sentiments": new_tickers,
            "concept_sentiments": new_concepts,
        }

        # The dashboard and ticker pages read aggregated_analysis, never
        # source_breakdown — without this rebuild the correction would be
        # invisible everywhere outside the audit panel.
        rebuilt = _rebuild_analysis(cluster, source, new_tickers, new_concepts)
        set_fields["aggregated_analysis"] = rebuilt

    await collection.update_one(
        {"cluster_id": cluster_id},
        {"$set": set_fields},
        array_filters=[{"entry.source": source}],
    )

    # audit_log is append-only (US-G4): a re-audit adds a row, never rewrites one.
    await db[AUDIT_LOG_COLLECTION].insert_one(
        {
            "admin_id": admin.admin_id,
            "admin_name": admin.display_name,
            "action_type": action.action_type,
            "cluster_id": cluster_id,
            "source": source,
            "old_ticker_sentiments": old_tickers,
            "new_ticker_sentiments": new_tickers if scores_changed else None,
            "old_concept_sentiments": old_concepts,
            "new_concept_sentiments": new_concepts if scores_changed else None,
            "error_type": action.error_type.value if action.error_type else None,
            "performed_at": datetime.now(UTC),
        }
    )
    logger.info(
        "audit %s by %s on %s/%s (recomputed=%s)",
        action.action_type, admin.admin_id, cluster_id, source, scores_changed,
    )

    return AuditActionResult(
        success=True,
        cluster_id=cluster_id,
        source=source,
        action_type=action.action_type,
        aggregated_analysis_recomputed=scores_changed,
    )


def _rebuild_analysis(
    cluster: dict, source: str, new_tickers: list[dict], new_concepts: list[dict]
) -> dict:
    """Rebuilds the cluster blend from ALL its sources, with the corrected one
    substituted in. Uses core.aggregation — the same function the pipeline runs —
    so an admin correction and a pipeline run can never produce different maths.

    The substitution goes into audited_response because that is what
    core.aggregation resolves first; writing it to ai_response here would
    reproduce the right number by destroying the record it came from.
    """
    breakdowns: list[SourceBreakdown] = []
    for sb in cluster.get("source_breakdown") or []:
        if sb.get("ai_response") is None:
            continue
        patched = dict(sb)
        if sb.get("source") == source:
            patched["audited_response"] = {
                **(effective_response_raw(sb) or sb["ai_response"]),
                "ticker_sentiments": new_tickers,
                "concept_sentiments": new_concepts,
            }
        breakdowns.append(SourceBreakdown.model_validate(patched))

    analysis = build_aggregated_analysis(
        breakdowns, pipeline_settings.AI_CONFIDENCE_THRESHOLD
    )
    return analysis.model_dump(mode="json")


# ============================================================
# GET /api/audit/log
# ============================================================


async def get_audit_log(
    db: AsyncIOMotorDatabase, page: int, settings: APISettings = api_settings
) -> AuditLog:
    page_size = settings.AUDIT_PAGE_SIZE
    skip = (page - 1) * page_size
    cursor = (
        db[AUDIT_LOG_COLLECTION]
        .find({})
        .sort([("performed_at", -1), ("_id", -1)])  # _id breaks same-timestamp ties
        .skip(skip)
        .limit(page_size + 1)
    )
    rows = await cursor.to_list(length=page_size + 1)
    has_more = len(rows) > page_size

    return AuditLog(
        page=page,
        has_more=has_more,
        items=[
            AuditLogEntry(
                cluster_id=r.get("cluster_id") or "",
                source=r.get("source") or "",
                admin_id=r.get("admin_id") or "",
                admin_name=r.get("admin_name") or "",
                action_type=r.get("action_type") or "",
                error_type=r.get("error_type"),
                old_ticker_sentiments=[TickerScore(**t) for t in r.get("old_ticker_sentiments") or []],
                new_ticker_sentiments=(
                    [TickerScore(**t) for t in r["new_ticker_sentiments"]]
                    if r.get("new_ticker_sentiments")
                    else None
                ),
                old_concept_sentiments=[ConceptScore(**c) for c in r.get("old_concept_sentiments") or []],
                new_concept_sentiments=(
                    [ConceptScore(**c) for c in r["new_concept_sentiments"]]
                    if r.get("new_concept_sentiments")
                    else None
                ),
                performed_at=r["performed_at"],
            )
            for r in rows[:page_size]
        ],
    )
