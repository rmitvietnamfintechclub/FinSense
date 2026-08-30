"""
backend/api/tests/unit/test_audit.py

Admin audit panel: summary counters, the flat (cluster, source) queue, the
approve/correct write path, and the immutable log.

Follows test_ticker.py's convention — no pytest-asyncio, so async service
functions are driven with asyncio.run() from plain sync tests. core.aggregation
and core.formulas are used for real; mocking them would assert the mock.

The Mongo aggregation pipelines in get_audit_articles/get_audit_summary are not
reimplemented by the fakes here — mongomock cannot run $facet or a $lookup with
a `let`/`pipeline` sub-query (see CLAUDE.md on its limits), so those two are
covered by asserting the pipeline SHAPE, while the write path — the part that
mutates data and must not be got wrong — is tested end to end against a fake.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from backend.api.features.audit import service as svc
from backend.api.features.audit.schemas import (
    AuditAction,
    AuditSort,
    AuditStatus,
    ErrorType,
)
from backend.api.features.auth.schemas import CurrentAdmin
from backend.core.aggregation import build_aggregated_analysis
from backend.core.config import pipeline_settings
from backend.core.schemas.event_cluster import SourceBreakdown

ADMIN = CurrentAdmin(admin_id="adm_minh", username="minh", display_name="Minh Chen")


def ai_response(tickers, concepts, confidence=0.9):
    return {
        "ticker_sentiments": [{"ticker": t, "score": s} for t, s in tickers],
        "concept_sentiments": [{"concept": c, "score": s} for c, s in concepts],
        "ai_confidence": confidence,
        "model_version": "gemini-3.6-flash",
        "prompt_version": "v1",
    }


def cluster_doc(**overrides):
    doc = {
        "cluster_id": "evt_hpg",
        "event_title": "HPG Q2 results",
        "created_at": datetime(2026, 8, 20, tzinfo=UTC),
        "updated_at": datetime(2026, 8, 20, tzinfo=UTC),
        "event_coverage": {"total_articles": 3, "all_urls": {}},
        "aggregated_analysis": {"ticker_sentiments": [], "concept_sentiments": []},
        "source_breakdown": [
            {
                "source": "CafeF",
                "representative_article": {
                    "title": "HPG công bố BCTC Q2",
                    "url": "https://cafef.vn/a",
                    "published_at": datetime(2026, 8, 20, tzinfo=UTC),
                    "content_fed_to_ai": "body",
                    "centroid_similarity": 0.95,
                },
                "ai_response": ai_response([("HPG", -0.5)], [("MATERIALS", -0.3)]),
                "is_audited": False,
            },
            {
                "source": "VnExpress",
                "representative_article": {
                    "title": "Thép quý 2",
                    "url": "https://vnexpress.net/b",
                    "published_at": datetime(2026, 8, 20, tzinfo=UTC),
                    "content_fed_to_ai": "body2",
                    "centroid_similarity": 0.92,
                },
                "ai_response": ai_response([("HPG", -0.1)], [("MATERIALS", -0.1)]),
                "is_audited": False,
            },
        ],
    }
    return {**doc, **overrides}


class FakeClusters:
    def __init__(self, doc):
        self.doc = doc
        self.updates: list[tuple[dict, dict, list | None]] = []

    async def find_one(self, query):
        return self.doc if self.doc and query.get("cluster_id") == self.doc["cluster_id"] else None

    async def update_one(self, query, update, array_filters=None):
        self.updates.append((query, update, array_filters))


class FakeLog:
    def __init__(self):
        self.inserted: list[dict] = []

    async def insert_one(self, doc):
        self.inserted.append(doc)


class FakeDb:
    def __init__(self, clusters=None, log=None, articles=None):
        self.clusters = clusters or FakeClusters(cluster_doc())
        self.log = log or FakeLog()
        self.articles = articles

    def __getitem__(self, name):
        return {
            "event_clusters": self.clusters,
            "audit_log": self.log,
            "articles": self.articles,
        }[name]


def run_action(db, action, cluster_id="evt_hpg", source="CafeF"):
    return asyncio.run(svc.apply_audit_action(db, cluster_id, source, action, ADMIN))


# ============================================================
# approve
# ============================================================


class TestApprove:
    def test_flips_is_audited_without_touching_scores(self):
        db = FakeDb()
        result = run_action(db, AuditAction(action_type="approve"))

        _, update, array_filters = db.clusters.updates[0]
        assert update["$set"] == {"source_breakdown.$[entry].is_audited": True}
        assert array_filters == [{"entry.source": "CafeF"}]
        assert result.aggregated_analysis_recomputed is False

    def test_writes_an_audit_log_entry_with_no_new_scores(self):
        db = FakeDb()
        run_action(db, AuditAction(action_type="approve"))

        entry = db.log.inserted[0]
        assert entry["action_type"] == "approve"
        assert entry["new_ticker_sentiments"] is None
        assert entry["old_ticker_sentiments"] == [{"ticker": "HPG", "score": -0.5}]

    def test_admin_identity_comes_from_the_token(self):
        db = FakeDb()
        run_action(db, AuditAction(action_type="approve"))
        entry = db.log.inserted[0]
        assert entry["admin_id"] == "adm_minh"
        assert entry["admin_name"] == "Minh Chen"


# ============================================================
# correct
# ============================================================


class TestCorrect:
    def test_merges_only_the_named_ticker_and_keeps_the_rest(self):
        db = FakeDb(FakeClusters(cluster_doc(source_breakdown=[
            {
                **cluster_doc()["source_breakdown"][0],
                "ai_response": ai_response([("HPG", -0.5), ("VNM", -0.25)], [("MATERIALS", -0.3)]),
            }
        ])))
        run_action(db, AuditAction(
            action_type="correct",
            error_type=ErrorType.WRONG_MAGNITUDE,
            corrected_ticker_sentiments=[{"ticker": "HPG", "score": -0.2}],
        ))
        _, update, _ = db.clusters.updates[0]
        new = update["$set"]["source_breakdown.$[entry].audited_response"]["ticker_sentiments"]
        assert {"ticker": "HPG", "score": -0.2} in new
        assert {"ticker": "VNM", "score": -0.25} in new, "untouched ticker must survive"

    def test_correction_can_add_a_missed_ticker(self):
        db = FakeDb()
        run_action(db, AuditAction(
            action_type="correct",
            error_type=ErrorType.MISSED_TICKER,
            corrected_ticker_sentiments=[{"ticker": "VNM", "score": 0.4}],
        ))
        _, update, _ = db.clusters.updates[0]
        new = update["$set"]["source_breakdown.$[entry].audited_response"]["ticker_sentiments"]
        assert {"ticker": "VNM", "score": 0.4} in new

    def test_v1_has_no_removal_wrong_ticker_keeps_its_score(self):
        """Product decision: 'Wrong ticker' is recorded for the error taxonomy but
        the hallucinated score stays. Pins the documented v1 limitation."""
        db = FakeDb(FakeClusters(cluster_doc(source_breakdown=[
            {
                **cluster_doc()["source_breakdown"][0],
                "ai_response": ai_response([("HPG", -0.5), ("VNM", -0.25)], []),
            }
        ])))
        run_action(db, AuditAction(
            action_type="correct",
            error_type=ErrorType.WRONG_TICKER,
            corrected_ticker_sentiments=[{"ticker": "HPG", "score": -0.4}],
        ))
        _, update, _ = db.clusters.updates[0]
        new = update["$set"]["source_breakdown.$[entry].audited_response"]["ticker_sentiments"]
        assert any(t["ticker"] == "VNM" for t in new)
        assert db.log.inserted[0]["error_type"] == "Wrong ticker"

    def test_correction_never_writes_ai_response(self):
        """ai_response is the accuracy evaluation's only record of what the model
        actually said. A correction that rewrites it makes every later evaluation
        score the AI on human numbers."""
        db = FakeDb()
        run_action(db, AuditAction(
            action_type="correct",
            error_type=ErrorType.WRONG_MAGNITUDE,
            corrected_ticker_sentiments=[{"ticker": "HPG", "score": -0.2}],
        ))
        _, update, _ = db.clusters.updates[0]
        assert not any(
            "ai_response" in path for path in update["$set"]
        ), "no $set path may touch ai_response"

    def test_audited_response_keeps_the_confidence_and_versions_of_the_run(self):
        """It has to validate as an AIResponse on its own, and the confidence is
        what core.aggregation weights the corrected source by."""
        db = FakeDb()
        run_action(db, AuditAction(
            action_type="correct",
            error_type=ErrorType.WRONG_MAGNITUDE,
            corrected_ticker_sentiments=[{"ticker": "HPG", "score": -0.2}],
        ))
        _, update, _ = db.clusters.updates[0]
        written = update["$set"]["source_breakdown.$[entry].audited_response"]
        original = cluster_doc()["source_breakdown"][0]["ai_response"]
        assert written["ai_confidence"] == original["ai_confidence"]
        assert written["model_version"] == original["model_version"]
        assert written["prompt_version"] == original["prompt_version"]

    def test_second_correction_edits_the_first_admins_numbers(self):
        """A re-edit stacks on the previous correction, so audit_log's old_* is
        what was on screen — not the AI's value, which was already superseded."""
        db = FakeDb(FakeClusters(cluster_doc(source_breakdown=[
            {
                **cluster_doc()["source_breakdown"][0],
                "ai_response": ai_response([("HPG", -0.9)], []),
                "audited_response": ai_response([("HPG", -0.5)], []),
            }
        ])))
        run_action(db, AuditAction(
            action_type="correct",
            error_type=ErrorType.WRONG_MAGNITUDE,
            corrected_ticker_sentiments=[{"ticker": "HPG", "score": -0.2}],
        ))
        logged = db.log.inserted[0]
        assert logged["old_ticker_sentiments"] == [{"ticker": "HPG", "score": -0.5}]
        assert logged["new_ticker_sentiments"] == [{"ticker": "HPG", "score": -0.2}]

    def test_error_type_is_required_for_a_correction(self):
        db = FakeDb()
        with pytest.raises(svc.InvalidAuditActionError):
            run_action(db, AuditAction(action_type="correct"))
        assert db.log.inserted == [], "nothing may be logged when the action is rejected"

    def test_recomputes_aggregated_analysis(self):
        """The whole point: dashboard and ticker pages read aggregated_analysis,
        so a correction that never reaches it is invisible outside this panel."""
        db = FakeDb()
        result = run_action(db, AuditAction(
            action_type="correct",
            error_type=ErrorType.WRONG_MAGNITUDE,
            corrected_ticker_sentiments=[{"ticker": "HPG", "score": 0.9}],
        ))
        _, update, _ = db.clusters.updates[0]
        assert "aggregated_analysis" in update["$set"]
        assert result.aggregated_analysis_recomputed is True

        hpg = next(
            t for t in update["$set"]["aggregated_analysis"]["ticker_sentiments"]
            if t["ticker"] == "HPG"
        )
        # Corrected CafeF (+0.9) blended with untouched VnExpress (-0.1),
        # both at confidence 0.9 — so the result must sit between them and be
        # far above the pre-correction value.
        assert -0.1 < hpg["score"] < 0.9

    def test_recompute_matches_the_pipeline_formula_exactly(self):
        """Guards against the audit path and the pipeline drifting apart."""
        db = FakeDb()
        run_action(db, AuditAction(
            action_type="correct",
            error_type=ErrorType.WRONG_MAGNITUDE,
            corrected_ticker_sentiments=[{"ticker": "HPG", "score": 0.9}],
        ))
        _, update, _ = db.clusters.updates[0]
        got = update["$set"]["aggregated_analysis"]

        doc = cluster_doc()
        doc["source_breakdown"][0]["ai_response"]["ticker_sentiments"] = [
            {"ticker": "HPG", "score": 0.9}
        ]
        expected = build_aggregated_analysis(
            [SourceBreakdown.model_validate(sb) for sb in doc["source_breakdown"]],
            pipeline_settings.AI_CONFIDENCE_THRESHOLD,
        ).model_dump(mode="json")
        assert got == expected

    def test_logs_both_old_and_new_scores(self):
        db = FakeDb()
        run_action(db, AuditAction(
            action_type="correct",
            error_type=ErrorType.WRONG_DIRECTION,
            corrected_ticker_sentiments=[{"ticker": "HPG", "score": 0.5}],
        ))
        entry = db.log.inserted[0]
        assert entry["old_ticker_sentiments"] == [{"ticker": "HPG", "score": -0.5}]
        assert {"ticker": "HPG", "score": 0.5} in entry["new_ticker_sentiments"]
        assert entry["error_type"] == "Wrong direction"


# ============================================================
# failure paths
# ============================================================


class TestNotFound:
    def test_unknown_cluster_raises(self):
        db = FakeDb(FakeClusters(None))
        with pytest.raises(svc.ClusterSourceNotFoundError):
            run_action(db, AuditAction(action_type="approve"), cluster_id="nope")

    def test_unknown_source_within_a_real_cluster_raises(self):
        db = FakeDb()
        with pytest.raises(svc.ClusterSourceNotFoundError):
            run_action(db, AuditAction(action_type="approve"), source="Vietstock")

    def test_source_without_an_extraction_cannot_be_audited(self):
        doc = cluster_doc()
        doc["source_breakdown"][0]["ai_response"] = None
        db = FakeDb(FakeClusters(doc))
        with pytest.raises(svc.InvalidAuditActionError):
            run_action(db, AuditAction(action_type="approve"))


# ============================================================
# re-audit
# ============================================================


class TestReAudit:
    def test_already_audited_source_can_be_corrected_again(self):
        """The mockup's 'Re-edit' button. audit_log is append-only, so a second
        action adds a row rather than rewriting the first."""
        doc = cluster_doc()
        doc["source_breakdown"][0]["is_audited"] = True
        db = FakeDb(FakeClusters(doc))
        result = run_action(db, AuditAction(
            action_type="correct",
            error_type=ErrorType.WRONG_MAGNITUDE,
            corrected_ticker_sentiments=[{"ticker": "HPG", "score": -0.1}],
        ))
        assert result.success is True
        assert len(db.log.inserted) == 1


# ============================================================
# malformed stored data must degrade, never 500 the page
# ============================================================


class TestRowResilience:
    def _flat(self, doc):
        return {**doc, "source_breakdown": doc["source_breakdown"][0]}

    def test_out_of_vocabulary_ticker_is_dropped_not_fatal(self):
        """STATE.md records extractions attributing sentiment to companies
        outside VN30. One such row must not take down the whole queue."""
        doc = cluster_doc()
        doc["source_breakdown"][0]["ai_response"]["ticker_sentiments"] = [
            {"ticker": "PNJ", "score": 0.4},
            {"ticker": "HPG", "score": -0.5},
        ]
        row = svc._row_from_flat(self._flat(doc))
        assert [t.ticker for t in row.ticker_sentiments] == ["HPG"]

    def test_out_of_vocabulary_concept_is_dropped_not_fatal(self):
        doc = cluster_doc()
        doc["source_breakdown"][0]["ai_response"]["concept_sentiments"] = [
            {"concept": "STEEL", "score": 0.1}
        ]
        assert svc._row_from_flat(self._flat(doc)).concept_sentiments == []

    def test_missing_published_at_falls_back_to_cluster_created_at(self):
        doc = cluster_doc()
        del doc["source_breakdown"][0]["representative_article"]["published_at"]
        assert svc._row_from_flat(self._flat(doc)).published_at == doc["created_at"]

    def test_genuine_zero_confidence_is_preserved(self):
        doc = cluster_doc()
        doc["source_breakdown"][0]["ai_response"]["ai_confidence"] = 0.0
        assert svc._row_from_flat(self._flat(doc)).ai_confidence == 0.0

    def test_row_shows_the_correction_with_the_ai_original_beside_it(self):
        """The correction form's reference column. Without this the panel shows
        the previous admin's number as 'what the AI said' on every re-edit."""
        doc = cluster_doc()
        doc["source_breakdown"][0]["ai_response"] = ai_response([("HPG", -0.9)], [])
        doc["source_breakdown"][0]["audited_response"] = ai_response([("HPG", -0.2)], [])
        row = svc._row_from_flat(self._flat(doc))
        assert [(t.ticker, t.score) for t in row.ticker_sentiments] == [("HPG", -0.2)]
        assert [(t.ticker, t.score) for t in row.original_ticker_sentiments] == [("HPG", -0.9)]

    def test_uncorrected_row_reports_the_ai_value_as_both(self):
        doc = cluster_doc()
        doc["source_breakdown"][0]["ai_response"] = ai_response([("HPG", -0.5)], [])
        row = svc._row_from_flat(self._flat(doc))
        assert row.ticker_sentiments == row.original_ticker_sentiments

    def test_null_title_survives_for_the_client_fallback(self):
        doc = cluster_doc()
        doc["source_breakdown"][0]["representative_article"]["title"] = None
        row = svc._row_from_flat(self._flat(doc))
        assert row.article_title is None
        assert row.event_title == "HPG Q2 results"


class TestApproveIsNotACorrection:
    """An approve carrying correction fields would log an error_type that no
    score change backs up, inflating the US-G5 taxonomy with phantom entries."""

    def test_approve_with_error_type_is_rejected(self):
        db = FakeDb()
        with pytest.raises(svc.InvalidAuditActionError):
            run_action(db, AuditAction(action_type="approve", error_type=ErrorType.WRONG_DIRECTION))
        assert db.log.inserted == []
        assert db.clusters.updates == []

    def test_approve_with_corrected_scores_is_rejected(self):
        db = FakeDb()
        with pytest.raises(svc.InvalidAuditActionError):
            run_action(db, AuditAction(
                action_type="approve",
                corrected_ticker_sentiments=[{"ticker": "HPG", "score": 0.9}],
            ))
        assert db.log.inserted == []

    def test_plain_approve_still_works(self):
        db = FakeDb()
        assert run_action(db, AuditAction(action_type="approve")).success is True


class TestNullCorrectionScoreIsRejected:
    """openapi's SentimentScore is nullable and the audit models reuse it, so a
    null reaches the service — but ai_response scores are non-nullable, and
    merging one in used to escape _rebuild_analysis as an uncaught
    ValidationError, i.e. a 500 on a request the contract called legal."""

    def test_null_ticker_score_is_a_domain_error_not_a_crash(self):
        db = FakeDb()
        with pytest.raises(svc.InvalidAuditActionError) as exc:
            run_action(db, AuditAction(
                action_type="correct",
                error_type=ErrorType.WRONG_TICKER,
                corrected_ticker_sentiments=[{"ticker": "HPG", "score": None}],
            ))
        # The message has to name the alternative: v1 has no removal mechanism,
        # so the admin needs telling what to do instead.
        assert "error_type" in str(exc.value)
        assert db.log.inserted == []
        assert db.clusters.updates == []

    def test_null_concept_score_is_rejected_too(self):
        db = FakeDb()
        with pytest.raises(svc.InvalidAuditActionError):
            run_action(db, AuditAction(
                action_type="correct",
                error_type=ErrorType.WRONG_MAGNITUDE,
                corrected_concept_sentiments=[{"concept": "MATERIALS", "score": None}],
            ))
        assert db.clusters.updates == []

    def test_one_null_rejects_the_whole_correction(self):
        # Partial application would leave the admin unsure which half landed.
        db = FakeDb()
        with pytest.raises(svc.InvalidAuditActionError):
            run_action(db, AuditAction(
                action_type="correct",
                error_type=ErrorType.WRONG_MAGNITUDE,
                corrected_ticker_sentiments=[
                    {"ticker": "HPG", "score": 0.9},
                    {"ticker": "VIC", "score": None},
                ],
            ))
        assert db.clusters.updates == []

    def test_a_zero_score_is_not_treated_as_null(self):
        # 0.0 is a legitimate neutral correction and must still go through.
        db = FakeDb()
        result = run_action(db, AuditAction(
            action_type="correct",
            error_type=ErrorType.WRONG_MAGNITUDE,
            corrected_ticker_sentiments=[{"ticker": "HPG", "score": 0.0}],
        ))
        assert result.success is True
        assert result.aggregated_analysis_recomputed is True


# ============================================================
# queue / summary pipeline shape
# ============================================================


class FakeAgg:
    """Captures the aggregation pipeline; mongomock cannot execute $facet or a
    $lookup with a sub-pipeline, so the shape is asserted instead."""

    def __init__(self, result):
        self.result = result
        self.pipeline = None

    def aggregate(self, pipeline):
        self.pipeline = pipeline
        outer = self

        class _Cursor:
            async def to_list(self, length=None):
                return outer.result

        return _Cursor()

    async def count_documents(self, query):
        return 147


class TestQueueShape:
    def _pipeline(self, status=AuditStatus.PENDING, sort=AuditSort.NEWEST, search=None):
        agg = FakeAgg([{"total": [], "rows": []}])
        db = FakeDb(clusters=agg)
        asyncio.run(svc.get_audit_articles(db, status=status, sort=sort, search=search, page=1))
        return agg.pipeline

    def test_unwinds_so_each_source_is_its_own_row(self):
        assert self._pipeline()[0] == {"$unwind": "$source_breakdown"}

    def test_excludes_sources_with_no_extraction(self):
        match = self._pipeline()[1]["$match"]
        assert match["source_breakdown.ai_response"] == {"$ne": None}

    def test_pending_filters_to_unaudited(self):
        assert self._pipeline(AuditStatus.PENDING)[1]["$match"]["source_breakdown.is_audited"] is False

    def test_audited_filters_to_audited(self):
        assert self._pipeline(AuditStatus.AUDITED)[1]["$match"]["source_breakdown.is_audited"] is True

    def test_all_does_not_filter_on_is_audited(self):
        assert "source_breakdown.is_audited" not in self._pipeline(AuditStatus.ALL)[1]["$match"]

    @pytest.mark.parametrize(
        "sort,field,direction",
        [
            (AuditSort.NEWEST, "source_breakdown.representative_article.published_at", -1),
            (AuditSort.OLDEST, "source_breakdown.representative_article.published_at", 1),
            (AuditSort.CONFIDENCE_DESC, "source_breakdown.ai_response.ai_confidence", -1),
            (AuditSort.CONFIDENCE_ASC, "source_breakdown.ai_response.ai_confidence", 1),
        ],
    )
    def test_every_sort_option_maps_to_the_right_field(self, sort, field, direction):
        assert self._pipeline(sort=sort)[2]["$sort"][field] == direction

    def test_every_sort_is_a_total_order(self):
        """Without a tiebreak, paging silently drops or repeats rows."""
        for sort in AuditSort:
            spec = self._pipeline(sort=sort)[2]["$sort"]
            assert "cluster_id" in spec and "source_breakdown.source" in spec

    def test_search_is_regex_escaped(self):
        """A ticker box accepts free text; an unescaped '(' would raise in Mongo."""
        match = self._pipeline(search="C(afeF")[1]["$match"]
        title_clause = match["$or"][0]["source_breakdown.representative_article.title"]
        assert title_clause["$regex"] == "C\\(afeF"

    def test_search_absent_means_no_or_clause(self):
        assert "$or" not in self._pipeline()[1]["$match"]


class TestSummary:
    def test_pending_is_total_minus_audited(self):
        agg = FakeAgg([{"n": 41}])
        summary = asyncio.run(svc.get_audit_summary(FakeDb(clusters=agg, articles=agg)))
        assert summary.total_articles == 147
        assert summary.audited_articles == 41
        assert summary.pending_review == 106

    def test_never_negative(self):
        class _Zero(FakeAgg):
            async def count_documents(self, query):
                return 0

        agg = _Zero([{"n": 5}])
        summary = asyncio.run(svc.get_audit_summary(FakeDb(clusters=agg, articles=agg)))
        assert summary.pending_review == 0
