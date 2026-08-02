from __future__ import annotations

import copy

import pytest

from backend.core.config import pipeline_settings
from backend.core.formulas import confidence_weighted_avg
from backend.pipeline.stages.aggregate.event_aggregator import (
    build_aggregated_analysis,
    run_aggregate,
)


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
        assert confidence_weighted_avg([0.2, 0.4, 0.9], [0.7, 0.7, 0.7]) == pytest.approx(0.5)

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


def _source(confidence, tickers=(), concepts=()):
    return {
        "source": "CafeF",
        "ai_response": {
            "ticker_sentiments": [{"ticker": t, "score": s} for t, s in tickers],
            "concept_sentiments": [{"concept": c, "score": s} for c, s in concepts],
            "ai_confidence": confidence,
            "model_version": "gemini-1.5-flash",
        },
        "is_audited": False,
    }


class FakeCollection:
    """Duck-typed stand-in for a pymongo collection (find + update_one)."""

    def __init__(self, docs):
        self.docs = {doc["_id"]: doc for doc in docs}

    def find(self, query):
        assert query == {}
        return [copy.deepcopy(doc) for doc in self.docs.values()]

    def update_one(self, filter_, update):
        (op, fields), = update.items()
        assert op == "$set"
        doc = self.docs[filter_["_id"]]
        for key, value in fields.items():
            assert "." not in key
            doc[key] = value


class TestBuildAggregatedAnalysis:
    def test_aggregates_tickers_and_concepts_separately(self):
        analysis = build_aggregated_analysis(
            [
                _source(0.9, tickers=[("HPG", 0.8)], concepts=[("STEEL", 0.6)]),
                _source(0.5, tickers=[("HPG", 0.4)], concepts=[("STEEL", -0.2)]),
            ],
            threshold=0.4,
        )
        (hpg,) = analysis["ticker_sentiments"]
        (steel,) = analysis["concept_sentiments"]
        assert hpg["ticker"] == "HPG"
        assert hpg["score"] == pytest.approx((0.8 * 0.9 + 0.4 * 0.5) / 1.4)
        assert steel["concept"] == "STEEL"
        assert steel["score"] == pytest.approx((0.6 * 0.9 - 0.2 * 0.5) / 1.4)

    def test_below_threshold_source_is_excluded(self):
        analysis = build_aggregated_analysis(
            [
                _source(0.9, tickers=[("HPG", 0.8)]),
                _source(0.2, tickers=[("HPG", -1.0)]),
            ],
            threshold=0.4,
        )
        (hpg,) = analysis["ticker_sentiments"]
        assert hpg["score"] == pytest.approx(0.8)
        assert analysis["needs_review"] is False

    def test_all_sources_below_threshold_gives_null_and_review_flag(self):
        analysis = build_aggregated_analysis(
            [
                _source(0.3, tickers=[("HPG", 0.9)], concepts=[("STEEL", 0.5)]),
                _source(0.1, tickers=[("HPG", -0.7)]),
            ],
            threshold=0.4,
        )
        (hpg,) = analysis["ticker_sentiments"]
        (steel,) = analysis["concept_sentiments"]
        # null, not 0 — the tickers still appear so we know what the event
        # was about, but there is no confident read on them.
        assert hpg["ticker"] == "HPG" and hpg["score"] is None
        assert steel["concept"] == "STEEL" and steel["score"] is None
        assert analysis["needs_review"] is True

    def test_ticker_mentioned_only_by_weak_source_gets_null(self):
        # Event itself has a confident source, so no review flag — but the
        # ticker only weak sources mentioned still gets null, not 0.
        analysis = build_aggregated_analysis(
            [
                _source(0.9, tickers=[("HPG", 0.8)]),
                _source(0.2, tickers=[("HSG", 0.5)]),
            ],
            threshold=0.4,
        )
        scores = {t["ticker"]: t["score"] for t in analysis["ticker_sentiments"]}
        assert scores["HPG"] == pytest.approx(0.8)
        assert scores["HSG"] is None
        assert analysis["needs_review"] is False

    def test_empty_source_breakdown(self):
        analysis = build_aggregated_analysis([], threshold=0.4)
        assert analysis["ticker_sentiments"] == []
        assert analysis["concept_sentiments"] == []
        assert analysis["needs_review"] is True


class TestRunAggregate:
    def _cluster(self, _id="evt_1", sources=None):
        return {
            "_id": _id,
            "cluster_id": _id,
            "source_breakdown": (
                [_source(0.9, tickers=[("HPG", 0.8)])] if sources is None else sources
            ),
        }

    def test_writes_aggregated_analysis_to_each_cluster(self):
        collection = FakeCollection([self._cluster("evt_1"), self._cluster("evt_2")])
        assert run_aggregate(collection, threshold=0.4) == 2
        for doc in collection.docs.values():
            (hpg,) = doc["aggregated_analysis"]["ticker_sentiments"]
            assert hpg["score"] == pytest.approx(0.8)

    def test_source_breakdown_is_not_modified(self):
        cluster = self._cluster()
        before = copy.deepcopy(cluster["source_breakdown"])
        collection = FakeCollection([cluster])
        run_aggregate(collection, threshold=0.4)
        assert collection.docs["evt_1"]["source_breakdown"] == before

    def test_only_aggregated_analysis_is_written(self):
        cluster = self._cluster()
        expected_keys = set(cluster) | {"aggregated_analysis"}
        collection = FakeCollection([cluster])
        run_aggregate(collection, threshold=0.4)
        assert set(collection.docs["evt_1"]) == expected_keys

    def test_threshold_defaults_to_config_value(self, monkeypatch):
        # A 0.5-confidence source survives the real 0.4 default but must be
        # dropped once config says 0.6 — proving run_aggregate reads config.
        cluster = self._cluster(sources=[_source(0.5, tickers=[("HPG", 0.8)])])
        collection = FakeCollection([cluster])
        monkeypatch.setattr(pipeline_settings, "AI_CONFIDENCE_THRESHOLD", 0.6)
        run_aggregate(collection)
        analysis = collection.docs["evt_1"]["aggregated_analysis"]
        (hpg,) = analysis["ticker_sentiments"]
        assert hpg["score"] is None
        assert analysis["needs_review"] is True
