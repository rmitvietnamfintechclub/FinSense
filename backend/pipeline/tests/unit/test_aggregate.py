"""Unit tests for event-level aggregation.

Three layers, deliberately separated:
  1. confidence_weighted_avg   — pure math, no models, no I/O
  2. build_aggregated_analysis — shaping real EventCluster sub-models
  3. run_aggregate             — orchestration and persistence
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.core.config import pipeline_settings
from backend.core.enums import Concept, Ticker
from backend.core.formulas import confidence_weighted_avg
from backend.core.schemas.event_cluster import (
    EventCluster,
    EventCoverage,
    RepresentativeArticle,
    SourceBreakdown,
)
from backend.core.schemas.sentiment import (
    AIResponse,
    ConceptSentiment,
    TickerSentiment,
)
from backend.pipeline.stages.aggregate.event_aggregator import build_aggregated_analysis
from backend.pipeline.stages.aggregate.stage import run_aggregate

# --------------------------------------------------------------------------
# Layer 1: the math
# --------------------------------------------------------------------------


class TestConfidenceWeightedAvg:
    def test_weights_scores_by_confidence(self):
        # (0.8*0.9 + 0.6*0.5 + -0.2*0.8) / (0.9 + 0.5 + 0.8) = 0.86 / 2.2
        result = confidence_weighted_avg([0.8, 0.6, -0.2], [0.9, 0.5, 0.8])
        assert result == pytest.approx(0.86 / 2.2)

    def test_single_source_returns_its_own_score(self):
        assert confidence_weighted_avg([0.75], [0.6]) == pytest.approx(0.75)

    def test_single_source_score_is_independent_of_its_confidence(self):
        # One source can't be outvoted, so its confidence cancels out.
        assert confidence_weighted_avg([0.75], [0.05]) == pytest.approx(0.75)

    def test_equal_confidences_reduce_to_plain_mean(self):
        result = confidence_weighted_avg([0.2, 0.4, 0.9], [0.7, 0.7, 0.7])
        assert result == pytest.approx(0.5)

    def test_higher_confidence_source_pulls_harder(self):
        # Same two scores, confidence flipped -> result moves toward the
        # source that is now the confident one.
        toward_positive = confidence_weighted_avg([1.0, -1.0], [0.9, 0.5])
        toward_negative = confidence_weighted_avg([1.0, -1.0], [0.5, 0.9])
        assert toward_positive == pytest.approx(0.4 / 1.4)
        assert toward_negative == pytest.approx(-0.4 / 1.4)

    def test_result_stays_within_score_bounds(self):
        result = confidence_weighted_avg([1.0, -1.0, 0.3], [0.9, 0.2, 0.55])
        assert -1.0 <= result <= 1.0


class TestConfidenceThreshold:
    def test_below_threshold_sources_are_excluded_entirely(self):
        # The -1.0 @ 0.2 source is dropped from numerator AND denominator:
        # (0.8*0.9 + 0.6*0.5) / (0.9 + 0.5), not / 1.6.
        result = confidence_weighted_avg(
            [0.8, -1.0, 0.6], [0.9, 0.2, 0.5], threshold=0.4
        )
        assert result == pytest.approx(1.02 / 1.4)

    def test_excluded_source_does_not_dilute_denominator(self):
        # If the low-confidence source were merely zero-weighted in the
        # numerator but still counted in the denominator, the result
        # would be dragged toward 0.
        filtered = confidence_weighted_avg([0.8, 0.0], [0.9, 0.1], threshold=0.4)
        assert filtered == pytest.approx(0.8)

    def test_confidence_equal_to_threshold_is_kept(self):
        # Rule is confidence >= threshold, so 0.4 at a 0.4 threshold counts.
        result = confidence_weighted_avg([1.0, -1.0], [0.4, 0.399], threshold=0.4)
        assert result == pytest.approx(1.0)

    def test_default_threshold_filters_nothing(self):
        unfiltered = confidence_weighted_avg([0.8, -1.0], [0.9, 0.2])
        explicit_zero = confidence_weighted_avg([0.8, -1.0], [0.9, 0.2], threshold=0.0)
        assert unfiltered == explicit_zero == pytest.approx(0.52 / 1.1)


class TestNoConfidentRead:
    def test_all_sources_below_threshold_returns_none(self):
        assert (
            confidence_weighted_avg([0.9, -0.7, 0.3], [0.3, 0.1, 0.39], threshold=0.4)
            is None
        )

    def test_all_below_threshold_is_null_not_neutral_zero(self):
        # null means "no confident read"; 0.0 would mean "neutral sentiment".
        result = confidence_weighted_avg([0.9, 0.8], [0.1, 0.2], threshold=0.4)
        assert result is None
        assert result != 0.0

    def test_no_sources_returns_none(self):
        assert confidence_weighted_avg([], []) is None

    def test_zero_total_confidence_returns_none(self):
        assert confidence_weighted_avg([0.9, -0.7], [0.0, 0.0]) is None

    def test_mismatched_input_lengths_raise(self):
        with pytest.raises(ValueError):
            confidence_weighted_avg([0.5, 0.4], [0.9])


class TestThresholdConfig:
    def test_threshold_comes_from_config_with_expected_default(self):
        assert pipeline_settings.AI_CONFIDENCE_THRESHOLD == pytest.approx(0.4)


# --------------------------------------------------------------------------
# Fixtures: real schema objects, not hand-rolled dicts
# --------------------------------------------------------------------------


def _source(
    confidence: float,
    tickers=(),
    concepts=(),
    source: str = "CafeF",
) -> SourceBreakdown:
    """One SourceBreakdown entry with a populated ai_response."""
    return SourceBreakdown(
        source=source,
        representative_article=RepresentativeArticle(
            url=f"https://{source.lower()}.vn/{confidence}",
            published_at=datetime.now(UTC),
            centroid_similarity=0.95,
        ),
        ai_response=AIResponse(
            ticker_sentiments=[TickerSentiment(ticker=t, score=s) for t, s in tickers],
            concept_sentiments=[
                ConceptSentiment(concept=c, score=s) for c, s in concepts
            ],
            ai_confidence=confidence,
            model_version="gemini-3.6-flash",
            prompt_version="v1",
        ),
    )


def _unextracted_source(source: str = "CafeF") -> SourceBreakdown:
    """A source the extract stage hasn't reached yet: ai_response is None."""
    return SourceBreakdown(
        source=source,
        representative_article=RepresentativeArticle(
            url=f"https://{source.lower()}.vn/pending",
            published_at=datetime.now(UTC),
            centroid_similarity=0.95,
        ),
        ai_response=None,
    )


def _cluster(cluster_id: str = "evt_1", sources=None) -> EventCluster:
    now = datetime.now(UTC)
    return EventCluster(
        cluster_id=cluster_id,
        event_title="HPG announces Q3 results",
        created_at=now,
        updated_at=now,
        centroid_embedding=[0.1, 0.2, 0.3],
        event_coverage=EventCoverage(total_articles=1),
        source_breakdown=(
            [_source(0.9, tickers=[(Ticker.HPG, 0.8)])] if sources is None else sources
        ),
    )


class FakeCollection:
    """Duck-typed stand-in for a pymongo collection (update_one only).

    Asserts the write contract itself: $set, matched on cluster_id, and
    only ever touching aggregated_analysis.
    """

    def __init__(self):
        self.writes: list[tuple[str, dict]] = []

    def update_one(self, filter_, update):
        ((operator, fields),) = update.items()
        assert operator == "$set"
        assert set(fields) == {"aggregated_analysis"}
        assert set(filter_) == {"cluster_id"}
        self.writes.append((filter_["cluster_id"], fields["aggregated_analysis"]))

    @property
    def payloads(self) -> dict[str, dict]:
        return dict(self.writes)


# --------------------------------------------------------------------------
# Layer 2: document shaping
# --------------------------------------------------------------------------


class TestBuildAggregatedAnalysis:
    def test_aggregates_tickers_and_concepts_separately(self):
        analysis = build_aggregated_analysis(
            [
                _source(
                    0.9,
                    tickers=[(Ticker.HPG, 0.8)],
                    concepts=[(Concept.MATERIALS, 0.6)],
                    source="CafeF",
                ),
                _source(
                    0.5,
                    tickers=[(Ticker.HPG, 0.4)],
                    concepts=[(Concept.MATERIALS, -0.2)],
                    source="VnExpress",
                ),
            ],
            threshold=0.4,
        )
        (hpg,) = analysis.ticker_sentiments
        (materials,) = analysis.concept_sentiments
        assert hpg.ticker is Ticker.HPG
        assert hpg.score == pytest.approx((0.8 * 0.9 + 0.4 * 0.5) / 1.4)
        assert materials.concept is Concept.MATERIALS
        assert materials.score == pytest.approx((0.6 * 0.9 - 0.2 * 0.5) / 1.4)

    def test_below_threshold_source_is_excluded_from_the_average(self):
        analysis = build_aggregated_analysis(
            [
                _source(0.9, tickers=[(Ticker.HPG, 0.8)], source="CafeF"),
                _source(0.2, tickers=[(Ticker.HPG, -1.0)], source="VnExpress"),
            ],
            threshold=0.4,
        )
        (hpg,) = analysis.ticker_sentiments
        assert hpg.score == pytest.approx(0.8)

    def test_ticker_seen_only_by_a_weak_source_gets_null_not_zero(self):
        # SSI was mentioned only by the weak source: it still appears (we
        # know the event touched it) but with no confident read on it.
        analysis = build_aggregated_analysis(
            [
                _source(0.9, tickers=[(Ticker.HPG, 0.8)], source="CafeF"),
                _source(0.2, tickers=[(Ticker.SSI, 0.5)], source="VnExpress"),
            ],
            threshold=0.4,
        )
        scores = {t.ticker: t.score for t in analysis.ticker_sentiments}
        assert scores[Ticker.HPG] == pytest.approx(0.8)
        assert scores[Ticker.SSI] is None

    def test_all_sources_below_threshold_gives_all_null_scores(self):
        analysis = build_aggregated_analysis(
            [
                _source(
                    0.3,
                    tickers=[(Ticker.HPG, 0.9)],
                    concepts=[(Concept.MATERIALS, 0.5)],
                    source="CafeF",
                ),
                _source(0.1, tickers=[(Ticker.HPG, -0.7)], source="VnExpress"),
            ],
            threshold=0.4,
        )
        (hpg,) = analysis.ticker_sentiments
        (materials,) = analysis.concept_sentiments
        # Every score null is the signal for "no confident read on this
        # event" — derived at read time, not stored as a flag.
        assert hpg.score is None
        assert materials.score is None
        assert all(t.score is None for t in analysis.ticker_sentiments)

    def test_confidence_equal_to_threshold_counts_as_a_confident_read(self):
        analysis = build_aggregated_analysis(
            [_source(0.4, tickers=[(Ticker.HPG, 0.6)])], threshold=0.4
        )
        (hpg,) = analysis.ticker_sentiments
        assert hpg.score == pytest.approx(0.6)

    def test_unextracted_source_is_skipped(self):
        analysis = build_aggregated_analysis([_unextracted_source()], threshold=0.4)
        assert analysis.ticker_sentiments == []
        assert analysis.concept_sentiments == []

    def test_unextracted_source_alongside_a_confident_one(self):
        analysis = build_aggregated_analysis(
            [
                _source(0.9, tickers=[(Ticker.HPG, 0.8)], source="CafeF"),
                _unextracted_source(source="VnExpress"),
            ],
            threshold=0.4,
        )
        (hpg,) = analysis.ticker_sentiments
        assert hpg.score == pytest.approx(0.8)

    def test_empty_source_breakdown(self):
        analysis = build_aggregated_analysis([], threshold=0.4)
        assert analysis.ticker_sentiments == []
        assert analysis.concept_sentiments == []

    def test_output_order_follows_first_mention(self):
        analysis = build_aggregated_analysis(
            [
                _source(
                    0.9,
                    tickers=[(Ticker.VNM, 0.1), (Ticker.HPG, 0.2)],
                    source="CafeF",
                ),
                _source(0.9, tickers=[(Ticker.HPG, 0.3)], source="VnExpress"),
            ],
            threshold=0.4,
        )
        assert [t.ticker for t in analysis.ticker_sentiments] == [
            Ticker.VNM,
            Ticker.HPG,
        ]


# --------------------------------------------------------------------------
# Layer 3: orchestration and persistence
# --------------------------------------------------------------------------


class TestRunAggregate:
    def test_writes_and_mutates_each_cluster(self):
        collection = FakeCollection()
        clusters = [_cluster("evt_1"), _cluster("evt_2")]

        returned = run_aggregate(clusters, collection, threshold=0.4)

        assert [c.cluster_id for c in returned] == ["evt_1", "evt_2"]
        assert set(collection.payloads) == {"evt_1", "evt_2"}
        for cluster in returned:
            (hpg,) = cluster.aggregated_analysis.ticker_sentiments
            assert hpg.score == pytest.approx(0.8)

    def test_source_breakdown_is_not_modified(self):
        # Audit corrections re-derive from the raw per-source scores, so
        # aggregation must never touch them.
        cluster = _cluster()
        before = cluster.model_dump()["source_breakdown"]
        run_aggregate([cluster], FakeCollection(), threshold=0.4)
        assert cluster.model_dump()["source_breakdown"] == before

    def test_written_payload_is_bson_safe(self):
        # model_dump(mode="json") must turn the Ticker/Concept enums into
        # plain strings before they reach MongoDB.
        collection = FakeCollection()
        run_aggregate([_cluster()], collection, threshold=0.4)
        payload = collection.payloads["evt_1"]
        entry = payload["ticker_sentiments"][0]
        assert entry["ticker"] == "HPG"
        assert type(entry["ticker"]) is str
        assert set(payload) == {"ticker_sentiments", "concept_sentiments"}

    def test_null_score_survives_serialisation(self):
        collection = FakeCollection()
        cluster = _cluster(sources=[_source(0.1, tickers=[(Ticker.HPG, 0.8)])])
        run_aggregate([cluster], collection, threshold=0.4)
        payload = collection.payloads["evt_1"]
        assert payload["ticker_sentiments"][0]["score"] is None

    def test_result_round_trips_through_the_event_cluster_schema(self):
        # The regression guard: the cluster stage re-validates persisted
        # documents on every later run, so whatever aggregation writes must
        # still parse back as an EventCluster.
        cluster = _cluster(sources=[_source(0.1, tickers=[(Ticker.HPG, 0.8)])])
        run_aggregate([cluster], FakeCollection(), threshold=0.4)
        reloaded = EventCluster.model_validate(cluster.model_dump())
        assert reloaded.aggregated_analysis.ticker_sentiments[0].score is None

    def test_empty_input_writes_nothing(self):
        collection = FakeCollection()
        assert run_aggregate([], collection) == []
        assert collection.writes == []

    def test_threshold_defaults_to_config_value(self, monkeypatch):
        # A 0.5-confidence source survives the real 0.4 default but must be
        # dropped once config says 0.6 — proving run_aggregate reads config.
        cluster = _cluster(sources=[_source(0.5, tickers=[(Ticker.HPG, 0.8)])])
        monkeypatch.setattr(pipeline_settings, "AI_CONFIDENCE_THRESHOLD", 0.6)

        run_aggregate([cluster], FakeCollection())

        (hpg,) = cluster.aggregated_analysis.ticker_sentiments
        assert hpg.score is None

    def test_explicit_threshold_overrides_config(self, monkeypatch):
        cluster = _cluster(sources=[_source(0.5, tickers=[(Ticker.HPG, 0.8)])])
        monkeypatch.setattr(pipeline_settings, "AI_CONFIDENCE_THRESHOLD", 0.9)

        run_aggregate([cluster], FakeCollection(), threshold=0.4)

        (hpg,) = cluster.aggregated_analysis.ticker_sentiments
        assert hpg.score == pytest.approx(0.8)